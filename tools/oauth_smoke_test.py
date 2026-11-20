#!/usr/bin/env python3
"""OAuth 2.1 conformance test for a deployed mcp1c server (TZ 6.4).

Plays an AI client end to end: discovery from the 401 answer (protected resource and authorization server
metadata, the variants from the site root a proxy must serve), the authorization page in place of the user's
browser (connection code, consent), PKCE, code exchange, refresh token rotation, MCP calls with the access
token, scopes and step-up (403 insufficient_scope), revocation, and the protections: foreign resource,
redirect_uri and client_id, PKCE plain, replayed consent, reused authorization code and refresh token, deny.
The default client is Claude Code's Client ID Metadata Document, so the 1C server fetches it from claude.ai:
the test also shows that the server reaches claude.ai over HTTPS.

The administrator issues connection codes for a test access client (its card, tab «OAuth»): 4 codes, 5 with
--ip-block-test. They come in MCP1C_OAUTH_CODES, comma-separated. Neither codes nor tokens are printed. Every
connection the test opens ends revoked; the fifth code of --ip-block-test stays unused and expires.
Uses only the Python standard library.

Usage:
  MCP1C_OAUTH_CODES=ABCD-EFGH,... python tools/oauth_smoke_test.py --url https://mcp.company.ua/mcp
  # direct access to the 1C publication (no proxy): the token goes in X-MCP-Authorization, root metadata
  # variants are skipped
  python tools/oauth_smoke_test.py --url http://localhost/base/hs/mcp1c
  # without the 62-second wait that checks reuse of a replaced refresh token
  python tools/oauth_smoke_test.py --url ... --quick
  # brute force of connection codes from one address, only with direct access to the publication (a proxy
  # overwrites X-Real-IP, and the test would block your own address)
  python tools/oauth_smoke_test.py --url ... --ip-block-test 203.0.113.77

Exit code: 0 - all checks passed, 1 - some checks failed, 2 - usage error.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import os
import re
import secrets
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any

MODERN = "2026-07-28"
ALL_SCOPES = "mcp:read mcp:reports mcp:query"
CLAUDE_CODE = "https://claude.ai/oauth/claude-code-client-metadata"
CLAUDE_CODE_REDIRECT = "http://localhost:33418/callback"  # registered without a port: loopback ports are ignored
SECRET = re.compile(r"(mcp1c_(?:at|rt|ac)_[A-Z0-9]+_)[A-Za-z0-9_-]+")
# Tools that need more than mcp:read, for the step-up check.
SCOPED_TOOLS = {"list_reports": "mcp:reports", "describe_report": "mcp:reports", "run_report": "mcp:reports",
                "execute_query": "mcp:query"}


def safe(text: str) -> str:
    """Token and code secrets never reach the output: only the kind and the connection id stay."""
    return SECRET.sub(r"\1***", text)


def page_text(page: str, limit: int = 300) -> str:
    body = re.sub(r"(?s)<(style|head)\b.*?</\1>", " ", page)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", body))).strip()[:limit]


def hidden(page: str, name: str) -> str:
    match = re.search(r'name="%s" value="([^"]*)"' % re.escape(name), page)
    return html.unescape(match.group(1)) if match else ""


def pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


@dataclass
class Answer:
    status: int
    headers: dict[str, str]
    text: str

    def header(self, name: str) -> str:
        return self.headers.get(name.lower(), "")

    @property
    def json(self) -> Any:
        try:
            return json.loads(self.text) if self.text.strip() else {}
        except json.JSONDecodeError:
            return {}

    @property
    def data(self) -> dict:
        value = self.json
        return value if isinstance(value, dict) else {}

    @property
    def query(self) -> dict[str, str]:
        """Parameters of the redirect in Location."""
        return dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(self.header("Location")).query))


@dataclass
class Flow:
    """One pass through the authorization page: the redirect parameters and what is needed to finish."""
    query: dict[str, str]
    verifier: str
    state: str
    status: int = 0
    approval: str = ""
    detail: str = ""


class CheckFailed(Exception):
    pass


class Skipped(Exception):
    """The check does not apply or depends on a check that did not pass."""


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise CheckFailed(message)


def need(value: Any, what: str) -> None:
    if not value:
        raise Skipped(f"no {what}: an earlier check did not pass")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # the test reads 30x answers itself
        return None


@dataclass
class Session:
    url: str
    codes: list[str]
    client_id: str
    redirect_uri: str
    auth_header: str
    context: ssl.SSLContext | None
    timeout: float
    verbose: bool
    ip_block_test: str | None = None
    quick: bool = False
    counter: int = 0
    prm_url: str = ""
    issuer: str = ""
    request: str = ""          # signed request of the authorization page (O6)
    state: str = ""
    verifier: str = ""
    access: str = ""           # main connection: first access token
    refresh: str = ""
    scope: str = ""
    tools: list[str] = field(default_factory=list)
    last_access: str = ""      # main connection after rotations (O10)
    replaced_refresh: str = ""  # refresh token replaced by a later rotation (O15)
    issued: dict[str, str] = field(default_factory=dict)  # connection id -> a token, for the final revocation
    slowed: bool = False

    def __post_init__(self) -> None:
        handlers: list[Any] = [NoRedirect()]
        if self.context is not None:
            handlers.append(urllib.request.HTTPSHandler(context=self.context))
        self.opener = urllib.request.build_opener(*handlers)

    # --- HTTP ---------------------------------------------------------------------------------------------
    def http(self, method: str, url: str, body: bytes | None = None, headers: dict[str, str] | None = None) -> Answer:
        request = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
        for _ in range(60):
            try:
                with self.opener.open(request, timeout=self.timeout) as answer:
                    status, raw_headers, raw = answer.status, answer.headers, answer.read()
            except urllib.error.HTTPError as error:
                status, raw_headers, raw = error.code, error.headers, error.read()
            if status != 429 or "Забагато" in raw.decode("utf-8", "replace"):
                break  # the server's own 429 for a blocked address is a result (O14)
            # 429 of a rate limit did not reach the server: the proxy template allows 60 requests a minute
            # with a burst of 20, calls_per_minute of the profile answers with Retry-After.
            retry_after = raw_headers.get("Retry-After", "")
            pause = int(retry_after) + 1 if retry_after.isdigit() and int(retry_after) <= 120 else 2
            if not self.slowed:
                print("    .. 429 from a rate limit (proxy or calls_per_minute): requests slow down")
                self.slowed = True
            time.sleep(pause)
        result = Answer(status, {k.lower(): v for k, v in raw_headers.items()}, raw.decode("utf-8", "replace"))
        if self.verbose:
            print(f"    -> {method} {safe(url)[:120]} {status} {safe(result.text[:200])!r}")
        return result

    def form(self, url: str, fields: dict[str, str], headers: dict[str, str] | None = None) -> Answer:
        all_headers = {"Content-Type": "application/x-www-form-urlencoded"}
        all_headers.update(headers or {})
        return self.http("POST", url, urllib.parse.urlencode(fields).encode("ascii"), all_headers)

    def mcp(self, method: str, params: dict, token: str | None, name: str = "") -> Answer:
        self.counter += 1
        params = dict(params)
        params["_meta"] = {"io.modelcontextprotocol/protocolVersion": MODERN,
                           "io.modelcontextprotocol/clientInfo": {"name": "mcp1c-oauth-test", "version": "0.1.0"},
                           "io.modelcontextprotocol/clientCapabilities": {}}
        body = json.dumps({"jsonrpc": "2.0", "id": self.counter, "method": method, "params": params}).encode()
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
                   "MCP-Protocol-Version": MODERN, "Mcp-Method": method}
        if name:
            headers["Mcp-Name"] = name
        if token:
            headers[self.auth_header] = f"Bearer {token}"
        return self.http("POST", self.url, body, headers)

    # --- OAuth --------------------------------------------------------------------------------------------
    def authorize_url(self, challenge: str, state: str, scope: str = ALL_SCOPES, **overrides: str) -> str:
        params = {"response_type": "code", "client_id": self.client_id, "redirect_uri": self.redirect_uri,
                  "scope": scope, "state": state, "code_challenge": challenge, "code_challenge_method": "S256",
                  "resource": self.url}
        params.update(overrides)
        return self.issuer + "/authorize?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)

    def connect(self, code: str, scope: str = ALL_SCOPES, decision: str = "allow") -> Flow:
        """Authorization page -> connection code -> consent -> decision, as the user does in the browser."""
        verifier, challenge = pkce()
        state = secrets.token_urlsafe(12)
        flow = Flow({}, verifier, state)
        page = self.http("GET", self.authorize_url(challenge, state, scope))
        if page.status != 200:
            flow.detail = f"authorization page: HTTP {page.status}: {page_text(page.text)}"
            return flow
        consent = self.form(self.issuer + "/authorize", {"request": hidden(page.text, "request"),
                                                         "connection_code": code})
        if consent.status != 200 or 'name="approval"' not in consent.text:
            flow.detail = f"connection code: HTTP {consent.status}: {page_text(consent.text)}"
            return flow
        flow.approval = hidden(consent.text, "approval")
        answer = self.form(self.issuer + "/authorize", {"approval": flow.approval, "decision": decision})
        flow.status, flow.query = answer.status, answer.query
        flow.detail = f"decision: HTTP {answer.status}"
        return flow

    def token(self, fields: dict[str, str]) -> Answer:
        fields = dict(fields)
        fields.setdefault("client_id", self.client_id)
        answer = self.form(self.issuer + "/token", fields)
        for name in ("access_token", "refresh_token"):
            value = answer.data.get(name)
            if isinstance(value, str) and value.count("_") >= 3:
                self.issued[value.split("_", 3)[2]] = value
        return answer

    def exchange(self, flow: Flow) -> Answer:
        return self.token({"grant_type": "authorization_code", "code": flow.query.get("code", ""),
                           "redirect_uri": self.redirect_uri, "code_verifier": flow.verifier, "resource": self.url})

    def revoke(self, value: str) -> Answer:
        return self.form(self.issuer + "/revoke", {"token": value, "client_id": self.client_id})

    def revoke_all(self) -> int:
        """Revokes every connection the test got tokens for: none stays active after a failed check."""
        done = 0
        for value in self.issued.values():
            try:
                done += self.revoke(value).status == 200
            except (urllib.error.URLError, OSError):
                pass
        return done


# --- Discovery ----------------------------------------------------------------------------------------------
def check_challenge(s: Session) -> str:
    answer = s.mcp("tools/list", {}, None)
    expect(answer.status == 401, f"HTTP {answer.status}, expected 401")
    challenge = answer.header("WWW-Authenticate")
    match = re.search(r'resource_metadata="([^"]+)"', challenge)
    expect(match is not None, f"no resource_metadata: OAuth is off or canonicalUrl is not set ({challenge})")
    s.prm_url = match.group(1)
    scope = re.search(r'scope="([^"]*)"', challenge)
    expect(scope is not None and set(ALL_SCOPES.split()) <= set(scope.group(1).split()),
           f"the first 401 must list all scopes: {challenge}")
    return challenge


def check_resource_metadata(s: Session) -> str:
    need(s.prm_url, "resource_metadata address")
    answer = s.http("GET", s.prm_url)
    prm = answer.data
    expect(answer.status == 200, f"{s.prm_url}: HTTP {answer.status}")
    expect(prm.get("resource") == s.url,
           f"resource {prm.get('resource')!r} differs from --url: canonicalUrl must be the public address")
    expect(prm.get("bearer_methods_supported") == ["header"], f"bearer_methods_supported {prm.get('bearer_methods_supported')}")
    expect(set(ALL_SCOPES.split()) <= set(prm.get("scopes_supported") or []), f"scopes_supported {prm.get('scopes_supported')}")
    servers = prm.get("authorization_servers") or []
    expect(servers == [s.url + "/oauth"], f"authorization_servers {servers}, expected [resource + /oauth]")
    s.issuer = servers[0]
    expect("max-age" in answer.header("Cache-Control"), "metadata without Cache-Control max-age")
    return f"issuer {s.issuer}"


def check_root_metadata(s: Session) -> str:
    need(s.issuer, "issuer")
    parts = urllib.parse.urlsplit(s.url)
    if "/hs/" in parts.path:
        raise Skipped("direct 1C publication: the site root variants are served by the proxy")
    origin, path = f"{parts.scheme}://{parts.netloc}", parts.path.rstrip("/")
    issuer_path = urllib.parse.urlsplit(s.issuer).path.rstrip("/")
    checked = []
    for url in (f"{origin}/.well-known/oauth-protected-resource{path}", f"{origin}/.well-known/oauth-protected-resource"):
        answer = s.http("GET", url)
        expect(answer.status == 200 and answer.data.get("resource") == s.url, f"{url}: HTTP {answer.status}")
        checked.append(urllib.parse.urlsplit(url).path)
    for url in (f"{origin}/.well-known/oauth-authorization-server{issuer_path}",
                f"{origin}/.well-known/openid-configuration{issuer_path}"):
        answer = s.http("GET", url)
        expect(answer.status == 200 and answer.data.get("issuer") == s.issuer, f"{url}: HTTP {answer.status}")
        checked.append(urllib.parse.urlsplit(url).path)
    return ", ".join(checked)


def check_server_metadata(s: Session) -> str:
    need(s.issuer, "issuer")
    answer = s.http("GET", s.issuer + "/.well-known/openid-configuration")
    meta = answer.data
    expect(answer.status == 200 and meta.get("issuer") == s.issuer, f"HTTP {answer.status}: {answer.text[:200]}")
    expect(meta.get("authorization_endpoint") == s.issuer + "/authorize"
           and meta.get("token_endpoint") == s.issuer + "/token", "authorization_endpoint or token_endpoint")
    expect(meta.get("code_challenge_methods_supported") == ["S256"], "code_challenge_methods_supported must be [S256]")
    expect(meta.get("client_id_metadata_document_supported") is True
           and "none" in (meta.get("token_endpoint_auth_methods_supported") or []),
           "Claude picks CIMD only with client_id_metadata_document_supported and auth method none")
    expect(meta.get("authorization_response_iss_parameter_supported") is True, "iss in the authorization response")
    expect(bool(meta.get("jwks_uri")) and bool(meta.get("subject_types_supported")),
           "OpenID fields required by the MCP TypeScript SDK schema")
    expect("max-age" in answer.header("Cache-Control") and answer.header("Access-Control-Allow-Origin") == "*",
           "metadata must be cacheable and readable cross-origin")
    plain = s.http("GET", s.issuer + "/.well-known/oauth-authorization-server")
    expect(plain.status == 200 and plain.data.get("issuer") == s.issuer and "jwks_uri" not in plain.data,
           f"RFC 8414 variant: HTTP {plain.status}")
    registration = "dynamic registration on" if meta.get("registration_endpoint") else "dynamic registration off"
    return f"S256, CIMD, iss, {registration}"


def check_jwks_and_cors(s: Session) -> str:
    need(s.issuer, "issuer")
    jwks = s.http("GET", s.issuer + "/jwks")
    expect(jwks.status == 200 and jwks.json == {"keys": []}, f"jwks: HTTP {jwks.status} {jwks.text[:100]}")
    preflight = s.http("OPTIONS", s.issuer + "/token", None, {"Origin": "https://inspector.example",
                                                             "Access-Control-Request-Method": "POST"})
    expect(preflight.status == 204 and "POST" in preflight.header("Access-Control-Allow-Methods"),
           f"preflight: HTTP {preflight.status}")
    return "empty JWKS, preflight 204"


# --- Authorization page -------------------------------------------------------------------------------------
def check_authorize_page(s: Session) -> str:
    need(s.issuer, "issuer")
    s.verifier, challenge = pkce()
    s.state = "state-" + secrets.token_urlsafe(8)
    page = s.http("GET", s.authorize_url(challenge, s.state))
    expect(page.status == 200 and 'name="connection_code"' in page.text, f"HTTP {page.status}: {page_text(page.text)}")
    host = urllib.parse.urlsplit(s.client_id).hostname if s.client_id.startswith("https://") else None
    if host:
        expect(host in page.text, f"the page must name the client host {host}, not only its self-asserted name")
    expect("frame-ancestors 'none'" in page.header("Content-Security-Policy")
           and page.header("X-Frame-Options") == "DENY" and page.header("Cache-Control") == "no-store",
           "page headers: CSP frame-ancestors, X-Frame-Options, Cache-Control")
    s.request = hidden(page.text, "request")
    expect(bool(s.request), "no request field on the page")
    return f"client {host or s.client_id}: {page_text(page.text, 120)}"


def check_authorize_refusals(s: Session) -> str:
    need(s.request, "authorization page")
    _, challenge = pkce()
    answer = s.http("GET", s.authorize_url(challenge, "st1", resource="https://evil.example/mcp"))
    expect(answer.status == 302 and answer.query.get("error") == "invalid_target" and answer.query.get("state") == "st1"
           and answer.query.get("iss") == s.issuer, f"foreign resource: HTTP {answer.status} {answer.query}")
    answer = s.http("GET", s.authorize_url(challenge, "st2", code_challenge_method="plain"))
    expect(answer.status == 302 and answer.query.get("error") == "invalid_request", f"PKCE plain: {answer.query}")
    answer = s.http("GET", s.authorize_url(challenge, "st3", redirect_uri="https://evil.example/callback"))
    expect(answer.status == 400 and not answer.header("Location"),
           f"foreign redirect_uri must get an error page, not a redirect: HTTP {answer.status}")
    answer = s.http("GET", s.authorize_url(challenge, "st4", client_id="https://example.com/oauth/client.json"))
    expect(answer.status == 400 and not answer.header("Location"), f"client_id outside oauthCimdPrefixes: HTTP {answer.status}")
    answer = s.form(s.issuer + "/authorize", {"request": s.request[:-3] + "AAA", "connection_code": s.codes[0]})
    expect(answer.status == 400 and "застаріла" in answer.text, f"tampered request: HTTP {answer.status}")
    answer = s.form(s.issuer + "/authorize", {"request": s.request, "connection_code": "AAAA-AAAA"})
    expect(answer.status == 400 and "Код неправильний" in answer.text, f"wrong connection code: HTTP {answer.status}")
    return "invalid_target, invalid_request, error pages for redirect_uri, client_id, request and code"


def check_connect(s: Session) -> str:
    need(s.request, "authorization page")
    consent = s.form(s.issuer + "/authorize", {"request": s.request, "connection_code": s.codes[0]})
    expect(consent.status == 200 and 'name="approval"' in consent.text,
           f"connection code: HTTP {consent.status}: {page_text(consent.text)}")
    approval = hidden(consent.text, "approval")
    answer = s.form(s.issuer + "/authorize", {"approval": approval, "decision": "allow"})
    location, query = answer.header("Location"), answer.query
    expect(answer.status == 303 and location.startswith(s.redirect_uri + "?") and query.get("state") == s.state
           and query.get("iss") == s.issuer and query.get("code", "").startswith("mcp1c_ac_"),
           f"allow: HTTP {answer.status} {safe(location)[:160]}")
    replay = s.form(s.issuer + "/authorize", {"approval": approval, "decision": "allow"})
    expect(replay.status == 400 and not replay.header("Location"), f"replayed consent: HTTP {replay.status}")
    fields = {"grant_type": "authorization_code", "code": query["code"], "redirect_uri": s.redirect_uri,
              "code_verifier": pkce()[0], "resource": s.url}
    wrong = s.token(fields)
    expect(wrong.status == 400 and wrong.data.get("error") == "invalid_grant", f"wrong code_verifier: {wrong.data}")
    tokens = s.token(dict(fields, code_verifier=s.verifier))
    data = tokens.data
    expect(tokens.status == 200 and data.get("token_type") == "Bearer"
           and str(data.get("access_token", "")).startswith("mcp1c_at_")
           and str(data.get("refresh_token", "")).startswith("mcp1c_rt_")
           and isinstance(data.get("expires_in"), int) and tokens.header("Cache-Control") == "no-store",
           f"code exchange: HTTP {tokens.status} {safe(json.dumps(data))[:200]}")
    s.access, s.refresh, s.scope = data["access_token"], data["refresh_token"], str(data.get("scope", ""))
    return f"scope {s.scope}, access token for {data['expires_in']} s"


def check_mcp_calls(s: Session) -> str:
    need(s.access, "access token")
    answer = s.mcp("tools/list", {}, s.access)
    tools = [t.get("name") for t in answer.data.get("result", {}).get("tools", [])]
    expect(answer.status == 200 and bool(tools), f"tools/list: HTTP {answer.status} {answer.text[:200]}")
    s.tools = tools
    if "get_context" in tools:
        call = s.mcp("tools/call", {"name": "get_context", "arguments": {}}, s.access, "get_context")
        expect(call.status == 200 and call.data.get("result", {}).get("isError") is False,
               f"get_context: HTTP {call.status} {call.text[:200]}")
    tampered = s.mcp("tools/list", {}, s.access[:-2] + ("xx" if not s.access.endswith("xx") else "yy"))
    expect(tampered.status == 401 and 'error="invalid_token"' in tampered.header("WWW-Authenticate"),
           f"tampered token: HTTP {tampered.status} {tampered.header('WWW-Authenticate')}")
    return f"{len(tools)} tools, tampered token 401 invalid_token"


def check_refresh(s: Session) -> str:
    need(s.refresh, "refresh token")
    first = s.token({"grant_type": "refresh_token", "refresh_token": s.refresh, "resource": s.url})
    access2, refresh2 = first.data.get("access_token", ""), first.data.get("refresh_token", "")
    expect(first.status == 200 and refresh2 not in ("", s.refresh) and access2 not in ("", s.access),
           f"refresh: HTTP {first.status} {first.data.get('error')}")
    expect(s.mcp("tools/list", {}, s.access).status == 200, "the previous access token must work until it expires")
    expect(s.mcp("tools/list", {}, access2).status == 200, "the new access token does not work")
    # A narrower scope and an unknown one are accepted: the pair keeps the scopes of the connection.
    second = s.token({"grant_type": "refresh_token", "refresh_token": refresh2, "scope": "mcp:read offline_access"})
    refresh3 = second.data.get("refresh_token", "")
    expect(second.status == 200 and bool(refresh3), f"refresh with scope mcp:read offline_access: {second.data}")
    old = s.token({"grant_type": "refresh_token", "refresh_token": s.refresh})
    expect(old.status == 400 and old.data.get("error") == "invalid_grant",
           f"a refresh token two rotations old must get invalid_grant: {old.data}")
    # The refresh token replaced a moment ago still works once: a client may send parallel requests.
    third = s.token({"grant_type": "refresh_token", "refresh_token": refresh3})
    refresh4 = third.data.get("refresh_token", "")
    parallel = s.token({"grant_type": "refresh_token", "refresh_token": refresh3})
    expect(third.status == 200 and parallel.status == 200,
           f"previous refresh token within a minute: HTTP {third.status}/{parallel.status}")
    other = s.token({"grant_type": "refresh_token", "refresh_token": refresh4, "client_id": "https://example.com/other"})
    expect(other.status == 401 and other.data.get("error") == "invalid_client",
           f"refresh with another client_id: {other.data}")
    s.replaced_refresh, s.last_access = refresh4, parallel.data.get("access_token", "")
    return "rotation, previous access token valid, old refresh token refused, one-minute grace"


def check_scopes(s: Session) -> str:
    need(s.request, "authorization page")
    flow = s.connect(s.codes[1], scope="mcp:read")
    expect(bool(flow.query.get("code")), f"connection with scope mcp:read: {flow.detail}")
    tokens = s.exchange(flow)
    limited = tokens.data.get("access_token", "")
    expect(tokens.status == 200 and tokens.data.get("scope") == "mcp:read",
           f"tokens: HTTP {tokens.status} scope {tokens.data.get('scope')!r}")
    detail = "granted mcp:read"
    scoped = next((name for name in SCOPED_TOOLS if name in s.tools), None)
    if scoped:
        answer = s.mcp("tools/call", {"name": scoped, "arguments": {}}, limited, scoped)
        challenge = answer.header("WWW-Authenticate")
        expect(answer.status == 403 and 'error="insufficient_scope"' in challenge and SCOPED_TOOLS[scoped] in challenge,
               f"{scoped} with mcp:read: HTTP {answer.status} {challenge}")
        detail += f", {scoped} -> 403 insufficient_scope"
    else:
        detail += ", the profile has no report or query tools: step-up not checked"
    expect(s.revoke(limited).status == 200, "revocation endpoint")
    expect(s.mcp("tools/list", {}, limited).status == 401, "a revoked connection must get 401")
    return detail + ", revoked by the client"


def check_code_reuse(s: Session) -> str:
    need(s.issuer, "issuer")
    flow = s.connect(s.codes[2])
    expect(bool(flow.query.get("code")), f"connection: {flow.detail}")
    first = s.exchange(flow)
    expect(first.status == 200, f"code exchange: HTTP {first.status}")
    again = s.exchange(flow)
    expect(again.status == 400 and again.data.get("error") == "invalid_grant", f"reused code: {again.data}")
    expect(s.mcp("tools/list", {}, first.data.get("access_token", "")).status == 401,
           "a reused authorization code must revoke the connection")
    return "invalid_grant, connection revoked"


def check_deny(s: Session) -> str:
    need(s.request, "authorization page")
    flow = s.connect(s.codes[3], decision="deny")
    expect(flow.status == 303 and flow.query.get("error") == "access_denied" and flow.query.get("state") == flow.state,
           f"deny: {flow.detail} {flow.query}")
    spent = s.form(s.issuer + "/authorize", {"request": s.request, "connection_code": s.codes[3]})
    expect(spent.status == 400 and "Код неправильний" in spent.text, "the connection code must be spent by the deny")
    late = s.form(s.issuer + "/authorize", {"approval": flow.approval, "decision": "allow"})
    expect(late.status == 400 and not late.header("Location"), f"allow after deny: HTTP {late.status}")
    return "access_denied, code spent"


def check_ip_block(s: Session) -> str:
    if not s.ip_block_test:
        raise Skipped("pass --ip-block-test <IP> (direct access to the publication only)")
    need(s.request, "authorization page")
    blocked = None
    for attempt in range(1, 31):
        answer = s.form(s.issuer + "/authorize", {"request": s.request, "connection_code": "BBBB-BBBB"},
                        {"X-Real-IP": s.ip_block_test})
        if answer.status == 429:
            blocked = attempt
            break
        expect(answer.status == 400, f"wrong code {attempt}: HTTP {answer.status}")
    expect(blocked is not None, f"{s.ip_block_test} not blocked after 30 wrong codes (the server must trust X-Real-IP)")
    right = s.form(s.issuer + "/authorize", {"request": s.request, "connection_code": s.codes[4]},
                   {"X-Real-IP": s.ip_block_test})
    expect(right.status == 429, f"a right code from the blocked address: HTTP {right.status}")
    return f"{s.ip_block_test} blocked at attempt {blocked}; it stays blocked for ipBlockMinutes"


def check_refresh_reuse(s: Session) -> str:
    need(s.replaced_refresh, "rotated refresh tokens")
    if s.quick:
        expect(s.revoke(s.last_access).status == 200, "revocation endpoint")
        expect(s.mcp("tools/list", {}, s.last_access).status == 401, "a revoked connection must get 401")
        raise Skipped("--quick: the main connection is revoked through /revoke instead")
    print("    .. waiting 62 s for the grace minute of the replaced refresh token")
    time.sleep(62)
    answer = s.token({"grant_type": "refresh_token", "refresh_token": s.replaced_refresh})
    expect(answer.status == 400 and answer.data.get("error") == "invalid_grant", f"reuse: {answer.data}")
    expect(s.mcp("tools/list", {}, s.last_access).status == 401, "reuse of a replaced refresh token must revoke the connection")
    return "invalid_grant, connection revoked"


CHECKS = [
    ("O1", "401 і WWW-Authenticate", check_challenge),
    ("O2", "метадані ресурсу", check_resource_metadata),
    ("O3", "метадані від кореня сайту (проксі)", check_root_metadata),
    ("O4", "метадані сервера авторизації", check_server_metadata),
    ("O5", "JWKS і CORS", check_jwks_and_cors),
    ("O6", "сторінка підключення", check_authorize_page),
    ("O7", "відмови на сторінці підключення", check_authorize_refusals),
    ("O8", "код підключення, згода, обмін коду на токени", check_connect),
    ("O9", "виклики MCP з токеном OAuth", check_mcp_calls),
    ("O10", "оновлення токенів з ротацією", check_refresh),
    ("O11", "області й відкликання клієнтом", check_scopes),
    ("O12", "повторний код авторизації", check_code_reuse),
    ("O13", "відмова користувача", check_deny),
    ("O14", "блокування IP після невірних кодів", check_ip_block),
    ("O15", "повтор заміненого refresh-токена", check_refresh_reuse),
]


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", required=True, help="MCP endpoint = canonicalUrl, e.g. https://mcp.company.ua/mcp")
    parser.add_argument("--client-id", default=CLAUDE_CODE,
                        help="OAuth client_id (default: Claude Code's Client ID Metadata Document)")
    parser.add_argument("--redirect-uri", help=f"redirect_uri registered for the client (default for Claude Code: "
                                               f"{CLAUDE_CODE_REDIRECT})")
    parser.add_argument("--auth-header", help="header that carries the access token: Authorization (default behind a "
                                              "proxy) or X-MCP-Authorization (default for a /hs/ publication)")
    parser.add_argument("--cafile", help="CA bundle for a self-signed certificate")
    parser.add_argument("--ip-block-test", metavar="IP",
                        help="O14: wrong connection codes with X-Real-IP: IP until the address is blocked. Direct "
                             "access to the publication only: a proxy overwrites X-Real-IP")
    parser.add_argument("--quick", action="store_true", help="skip the 62-second check of refresh token reuse")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("-v", "--verbose", action="store_true", help="print answers (secrets masked)")
    args = parser.parse_args()

    codes = [code.strip() for code in os.environ.get("MCP1C_OAUTH_CODES", "").split(",") if code.strip()]
    required = 5 if args.ip_block_test else 4
    if len(codes) < required:
        parser.error(f"MCP1C_OAUTH_CODES: {required} connection codes are needed, got {len(codes)}")
    if args.redirect_uri is None:
        if args.client_id != CLAUDE_CODE:
            parser.error("--redirect-uri is required for a client other than Claude Code")
        args.redirect_uri = CLAUDE_CODE_REDIRECT
    url = args.url.rstrip("/")
    auth_header = args.auth_header or ("X-MCP-Authorization" if "/hs/" in urllib.parse.urlsplit(url).path
                                       else "Authorization")
    context = ssl.create_default_context(cafile=args.cafile) if args.cafile else None
    session = Session(url, codes, args.client_id, args.redirect_uri, auth_header, context, args.timeout,
                      args.verbose, args.ip_block_test, args.quick)
    print(f"client {args.client_id}, token in {auth_header}")

    failed = 0
    try:
        for code, title, check in CHECKS:
            try:
                detail = check(session)
                status = "OK  "
            except Skipped as reason:
                detail, status = f"skipped: {reason}", "SKIP"
            except CheckFailed as error:
                detail, status = str(error), "FAIL"
                failed += 1
            except (urllib.error.URLError, OSError, ValueError) as error:
                detail, status = f"{type(error).__name__}: {error}", "FAIL"
                failed += 1
            print(f"{status} {code:<4} {title}: {safe(detail)}")
    finally:
        revoked = session.revoke_all() if session.issuer else 0
        print(f"\nfinal revocation of the test's connections: {revoked} of {len(session.issued)} answered 200")

    print(f"{'all checks passed' if failed == 0 else f'{failed} check(s) failed'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
