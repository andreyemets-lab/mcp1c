#!/usr/bin/env python3
"""Smoke and conformance test for a deployed mcp1c server (stage 0).

Checks transport security (token, Origin, Content-Type), MCP 2026-07-28 behaviour
(server/discover, mirrored headers, error codes, tools) and the 2025-11-25 / 2025-06-18
compatibility mode (initialize, ping). Uses only the Python standard library.

Usage:
  MCP1C_TOKEN=mcp1c_... python tools/mcp_smoke_test.py --url https://mcp.company.ua/mcp
  python tools/mcp_smoke_test.py --url http://localhost/base/hs/mcp1c --token mcp1c_... -v
  # if the 1C web server extension intercepts "Authorization: Bearer":
  python tools/mcp_smoke_test.py --url ... --auth-header X-MCP-Authorization

Exit code: 0 - all checks passed, 1 - some checks failed, 2 - usage error.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable

MODERN = "2026-07-28"
LEGACY = "2025-11-25"
EXPECTED_TOOLS = ["get_context", "list_objects", "describe_object"]


@dataclass
class Response:
    status: int
    headers: dict[str, str]
    text: str
    json: Any = None

    def header(self, name: str) -> str | None:
        return self.headers.get(name.lower())

    @property
    def error_code(self) -> int | None:
        if isinstance(self.json, dict) and isinstance(self.json.get("error"), dict):
            return self.json["error"].get("code")
        return None

    @property
    def result(self) -> dict:
        if isinstance(self.json, dict) and isinstance(self.json.get("result"), dict):
            return self.json["result"]
        return {}


class CheckFailed(Exception):
    pass


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise CheckFailed(message)


@dataclass
class Client:
    url: str
    token: str
    context: ssl.SSLContext | None
    timeout: float
    verbose: bool
    auth_header: str = "Authorization"
    counter: int = field(default=0)

    def next_id(self) -> int:
        self.counter += 1
        return self.counter

    def send(
        self,
        body: bytes | str | dict | list | None,
        *,
        method: str = "POST",
        headers: dict[str, str] | None = None,
        token: str | None = "default",
        url: str | None = None,
    ) -> Response:
        if isinstance(body, (dict, list)):
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        elif isinstance(body, str):
            data = body.encode("utf-8")
        else:
            data = body
        request_headers = {"Accept": "application/json, text/event-stream"}
        if data is not None:
            request_headers["Content-Type"] = "application/json"
        if token == "default":
            token = self.token
        if token:
            request_headers[self.auth_header] = f"Bearer {token}"
        request_headers.update(headers or {})
        request = urllib.request.Request(
            url or self.url, data=data, method=method,
            headers={k: v for k, v in request_headers.items() if v is not None},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout, context=self.context) as answer:
                status, raw_headers, raw = answer.status, answer.headers, answer.read()
        except urllib.error.HTTPError as error:
            status, raw_headers, raw = error.code, error.headers, error.read()
        text = raw.decode("utf-8", errors="replace")
        parsed = None
        if text.strip():
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
        response = Response(status, {k.lower(): v for k, v in raw_headers.items()}, text, parsed)
        if self.verbose:
            print(f"    -> {method} {status} {text[:300]}")
        return response

    # --- MCP helpers ---------------------------------------------------------
    @staticmethod
    def meta(version: str = MODERN) -> dict:
        return {
            "io.modelcontextprotocol/protocolVersion": version,
            "io.modelcontextprotocol/clientInfo": {"name": "mcp1c-smoke-test", "version": "0.1.0"},
            "io.modelcontextprotocol/clientCapabilities": {},
        }

    def modern(
        self,
        rpc_method: str,
        params: dict | None = None,
        *,
        name_header: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> Response:
        params = dict(params or {})
        params["_meta"] = self.meta()
        request_headers = {"MCP-Protocol-Version": MODERN, "Mcp-Method": rpc_method}
        if name_header is not None:
            request_headers["Mcp-Name"] = name_header
        request_headers.update(headers or {})
        body = {"jsonrpc": "2.0", "id": self.next_id(), "method": rpc_method, "params": params}
        return self.send(body, headers=request_headers)

    def call_tool(self, name: str, arguments: dict | None = None) -> Response:
        return self.modern("tools/call", {"name": name, "arguments": arguments or {}}, name_header=name)

    def legacy(self, rpc_method: str, params: dict | None = None, *, notification: bool = False,
               version: str | None = LEGACY) -> Response:
        body: dict[str, Any] = {"jsonrpc": "2.0", "method": rpc_method}
        if params is not None:
            body["params"] = params
        if not notification:
            body["id"] = self.next_id()
        headers = {"MCP-Protocol-Version": version} if version else {}
        return self.send(body, headers=headers)


def tool_payload(response: Response) -> dict:
    expect(response.status == 200, f"HTTP {response.status}, expected 200: {response.text[:200]}")
    expect(response.error_code is None, f"JSON-RPC error {response.json}")
    return response.result


# --- checks -------------------------------------------------------------------

def check_get_not_allowed(c: Client) -> str:
    r = c.send(None, method="GET")
    expect(r.status == 405, f"HTTP {r.status}, expected 405")
    expect((r.header("allow") or "").upper() == "POST", f"Allow: {r.header('allow')!r}, expected POST")
    return "405, Allow: POST"


def check_no_token(c: Client) -> str:
    r = c.send({"jsonrpc": "2.0", "id": 1, "method": "server/discover", "params": {"_meta": c.meta()}},
               headers={"MCP-Protocol-Version": MODERN, "Mcp-Method": "server/discover"}, token=None)
    expect(r.status == 401, f"HTTP {r.status}, expected 401")
    challenge = r.header("www-authenticate") or ""
    expect(challenge.lower().startswith("bearer"), f"WWW-Authenticate: {challenge!r}")
    return f"401, WWW-Authenticate: {challenge}"


def check_invalid_token(c: Client) -> str:
    fake = "mcp1c_AAAAAAAAAAAA_" + "A" * 43
    r = c.send({"jsonrpc": "2.0", "id": 1, "method": "server/discover", "params": {"_meta": c.meta()}},
               headers={"MCP-Protocol-Version": MODERN, "Mcp-Method": "server/discover"}, token=fake)
    expect(r.status == 401, f"HTTP {r.status}, expected 401")
    expect('invalid_token' in (r.header("www-authenticate") or ""), "no error=\"invalid_token\" in WWW-Authenticate")
    return "401 invalid_token"


def check_token_in_query(c: Client) -> str:
    separator = "&" if "?" in c.url else "?"
    url = c.url + separator + urllib.parse.urlencode({"AccessToken": c.token})
    r = c.send({"jsonrpc": "2.0", "id": 1, "method": "server/discover", "params": {"_meta": c.meta()}},
               headers={"MCP-Protocol-Version": MODERN, "Mcp-Method": "server/discover"}, token=None, url=url)
    expect(r.status in (400, 401), f"HTTP {r.status}, expected 400 (proxy) or 401 (server)")
    return f"HTTP {r.status}"


def check_content_type(c: Client) -> str:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "server/discover", "params": {"_meta": c.meta()}})
    r = c.send(body, headers={"Content-Type": "text/plain", "MCP-Protocol-Version": MODERN,
                              "Mcp-Method": "server/discover"})
    expect(r.status == 415, f"HTTP {r.status}, expected 415")
    return "415"


def check_origin(c: Client) -> str:
    r = c.modern("server/discover", headers={"Origin": "https://evil.example"})
    expect(r.status == 403, f"HTTP {r.status}, expected 403")
    return "403 for https://evil.example"


def check_discover(c: Client) -> str:
    r = c.modern("server/discover")
    result = tool_payload(r)
    expect(MODERN in result.get("supportedVersions", []), f"supportedVersions={result.get('supportedVersions')}")
    expect(result.get("resultType") == "complete", f"resultType={result.get('resultType')!r}")
    expect("tools" in result.get("capabilities", {}), "capabilities.tools missing")
    expect(isinstance(result.get("ttlMs"), int) and result.get("cacheScope") in ("public", "private"),
           "ttlMs/cacheScope missing")
    info = result.get("_meta", {}).get("io.modelcontextprotocol/serverInfo", {})
    expect(info.get("name") == "mcp1c", f"serverInfo={info}")
    expect(bool(result.get("instructions")), "instructions are empty")
    expect(r.header("mcp-session-id") is None, "server must not issue Mcp-Session-Id")
    return f"versions {result['supportedVersions']}, server {info.get('version')}"


def check_version_mismatch(c: Client) -> str:
    r = c.modern("server/discover", headers={"MCP-Protocol-Version": LEGACY})
    expect(r.status == 400 and r.error_code == -32020, f"HTTP {r.status}, code {r.error_code}; expected 400/-32020")
    return "400 / -32020"


def check_missing_method_header(c: Client) -> str:
    body = {"jsonrpc": "2.0", "id": c.next_id(), "method": "tools/list", "params": {"_meta": c.meta()}}
    r = c.send(body, headers={"MCP-Protocol-Version": MODERN})
    expect(r.status == 400 and r.error_code == -32020, f"HTTP {r.status}, code {r.error_code}; expected 400/-32020")
    return "400 / -32020"


def check_unsupported_version(c: Client) -> str:
    body = {"jsonrpc": "2.0", "id": c.next_id(), "method": "server/discover",
            "params": {"_meta": c.meta("2099-01-01")}}
    r = c.send(body, headers={"MCP-Protocol-Version": "2099-01-01", "Mcp-Method": "server/discover"})
    expect(r.status == 400 and r.error_code == -32022, f"HTTP {r.status}, code {r.error_code}; expected 400/-32022")
    supported = (r.json or {}).get("error", {}).get("data", {}).get("supported", [])
    expect(MODERN in supported, f"error.data.supported={supported}")
    return f"400 / -32022, supported {supported}"


def check_unknown_method(c: Client) -> str:
    r = c.modern("resources/list")
    expect(r.status == 404 and r.error_code == -32601, f"HTTP {r.status}, code {r.error_code}; expected 404/-32601")
    return "404 / -32601"


def check_tools_list(c: Client) -> str:
    first = tool_payload(c.modern("tools/list"))
    second = tool_payload(c.modern("tools/list"))
    names = [tool.get("name") for tool in first.get("tools", [])]
    expect(names == [tool.get("name") for tool in second.get("tools", [])], "tool order is not deterministic")
    for expected_name in EXPECTED_TOOLS:
        expect(expected_name in names, f"tool {expected_name} missing in {names}")
    for tool in first["tools"]:
        expect(tool.get("inputSchema", {}).get("type") == "object", f"{tool.get('name')}: inputSchema.type")
        expect(tool.get("annotations", {}).get("readOnlyHint") is True, f"{tool.get('name')}: readOnlyHint")
    expect(first.get("cacheScope") == "private" and isinstance(first.get("ttlMs"), int), "ttlMs/cacheScope missing")
    return ", ".join(names)


def check_get_context(c: Client) -> str:
    result = tool_payload(c.call_tool("get_context"))
    expect(result.get("isError") is False, f"isError: {result.get('content')}")
    data = result.get("structuredContent", {})
    configuration = data.get("configuration", {})
    expect(bool(configuration.get("name")), "configuration.name is empty")
    expect(result.get("content", [{}])[0].get("type") == "text", "content[0] is not text")
    return (f"{configuration.get('synonym') or configuration.get('name')} {configuration.get('version')}, "
            f"platform {data.get('platform', {}).get('version')}, tz {data.get('server_time', {}).get('timezone')}")


def check_base64_name_header(c: Client) -> str:
    encoded = "=?base64?" + base64.b64encode(b"get_context").decode() + "?="
    r = c.modern("tools/call", {"name": "get_context", "arguments": {}}, name_header=encoded)
    result = tool_payload(r)
    expect(result.get("isError") is False, "isError is true")
    return "encoded Mcp-Name accepted"


def check_missing_name_header(c: Client) -> str:
    r = c.modern("tools/call", {"name": "get_context", "arguments": {}})
    expect(r.status == 400 and r.error_code == -32020, f"HTTP {r.status}, code {r.error_code}; expected 400/-32020")
    return "400 / -32020"


def check_name_header_mismatch(c: Client) -> str:
    r = c.modern("tools/call", {"name": "get_context", "arguments": {}}, name_header="list_objects")
    expect(r.status == 400 and r.error_code == -32020, f"HTTP {r.status}, code {r.error_code}; expected 400/-32020")
    return "400 / -32020"


def check_list_objects(c: Client) -> str:
    first = tool_payload(c.call_tool("list_objects", {"kinds": ["catalog"], "limit": 3}))
    expect(first.get("isError") is False, f"isError: {first.get('content')}")
    page = first["structuredContent"]
    items = page.get("items", [])
    expect(len(items) <= 3 and page.get("returned") == len(items), f"returned={page.get('returned')}")
    for item in items:
        expect(item.get("kind") == "catalog" and str(item.get("object", "")).startswith("Справочник."),
               f"unexpected item {item}")
    if page.get("total", 0) > 3:
        expect(bool(page.get("next_cursor")), "next_cursor missing")
        second = tool_payload(c.call_tool("list_objects", {"kinds": ["catalog"], "limit": 3,
                                                           "cursor": page["next_cursor"]}))
        overlap = {i["object"] for i in items} & {i["object"] for i in second["structuredContent"]["items"]}
        expect(not overlap, f"pages overlap: {overlap}")
    return f"{page.get('total')} catalogs"


def check_describe_object(c: Client) -> str:
    listing = tool_payload(c.call_tool("list_objects", {"kinds": ["catalog"], "limit": 1}))
    items = listing["structuredContent"].get("items", [])
    if not items:
        return "skipped: no catalogs"
    name = items[0]["object"]
    result = tool_payload(c.call_tool("describe_object", {"object": name}))
    expect(result.get("isError") is False, f"isError: {result.get('content')}")
    data = result["structuredContent"]
    expect(data.get("object") == name and data.get("kind") == "catalog", f"object={data.get('object')}")
    attributes = len(data.get("attributes", [])) + len(data.get("standard_attributes", []))
    return f"{name}: {attributes} attributes"


def check_describe_missing(c: Client) -> str:
    result = tool_payload(c.call_tool("describe_object", {"object": "Справочник.НетТакогоОбъекта_mcp1c"}))
    expect(result.get("isError") is True, "isError must be true")
    return "isError for a missing object"


def check_invalid_arguments(c: Client) -> str:
    result = tool_payload(c.call_tool("list_objects", {"unknown_argument": 1}))
    expect(result.get("isError") is True, "isError must be true")
    return "isError for an unknown argument"


def check_unknown_tool(c: Client) -> str:
    r = c.call_tool("no_such_tool")
    expect(r.status == 200 and r.error_code == -32602, f"HTTP {r.status}, code {r.error_code}; expected 200/-32602")
    return "-32602"


def check_parse_error(c: Client) -> str:
    r = c.send("{", headers={"MCP-Protocol-Version": MODERN, "Mcp-Method": "tools/list"})
    expect(r.status == 400 and r.error_code == -32700, f"HTTP {r.status}, code {r.error_code}; expected 400/-32700")
    expect(isinstance(r.json, dict) and "id" in r.json and r.json["id"] is None, "id must be null")
    return "400 / -32700"


def check_batch(c: Client) -> str:
    body = [{"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"_meta": c.meta()}}]
    r = c.send(body, headers={"MCP-Protocol-Version": MODERN, "Mcp-Method": "tools/list"})
    expect(r.status == 400 and r.error_code == -32600, f"HTTP {r.status}, code {r.error_code}; expected 400/-32600")
    return "400 / -32600"


def check_legacy_initialize(c: Client) -> str:
    params = {"protocolVersion": LEGACY, "capabilities": {},
              "clientInfo": {"name": "mcp1c-smoke-test", "version": "0.1.0"}}
    r = c.legacy("initialize", params, version=None)
    result = tool_payload(r)
    expect(result.get("protocolVersion") == LEGACY, f"protocolVersion={result.get('protocolVersion')}")
    expect(result.get("serverInfo", {}).get("name") == "mcp1c", f"serverInfo={result.get('serverInfo')}")
    expect(r.header("mcp-session-id") is None, "server must not issue Mcp-Session-Id")
    old = tool_payload(c.legacy("initialize", dict(params, protocolVersion="2025-03-26"), version=None))
    expect(old.get("protocolVersion") == LEGACY, f"counter-offer {old.get('protocolVersion')}")
    return f"{LEGACY}; 2025-03-26 -> {old.get('protocolVersion')}"


def check_legacy_flow(c: Client) -> str:
    notification = c.legacy("notifications/initialized", notification=True)
    expect(notification.status == 202, f"notifications/initialized: HTTP {notification.status}, expected 202")
    ping = tool_payload(c.legacy("ping"))
    expect(ping == {}, f"ping result {ping}")
    tools = tool_payload(c.legacy("tools/list"))
    expect([t["name"] for t in tools.get("tools", [])][:3] == EXPECTED_TOOLS, "tools/list differs")
    expect("resultType" not in tools, "resultType must not be sent to 2025-era clients")
    call = tool_payload(c.legacy("tools/call", {"name": "get_context", "arguments": {}}))
    expect(call.get("isError") is False, "get_context failed")
    return "202, ping, tools/list, tools/call"


def check_legacy_without_header(c: Client) -> str:
    r = c.legacy("tools/list", version=None)
    expect(r.status == 400 and r.error_code == -32020, f"HTTP {r.status}, code {r.error_code}; expected 400/-32020")
    return "400 / -32020"


CHECKS: list[tuple[str, str, Callable[[Client], str]]] = [
    ("Б1", "запит без токена", check_no_token),
    ("Б2", "недійсний токен", check_invalid_token),
    ("Б3", "токен у рядку запиту", check_token_in_query),
    ("Б5", "чужий Origin", check_origin),
    ("T1", "GET на ендпоінт", check_get_not_allowed),
    ("T2", "Content-Type не JSON", check_content_type),
    ("M1", "server/discover", check_discover),
    ("M2", "розбіжність версії в заголовку і _meta", check_version_mismatch),
    ("M3", "немає заголовка Mcp-Method", check_missing_method_header),
    ("M4", "непідтримувана версія", check_unsupported_version),
    ("M5", "невідомий метод", check_unknown_method),
    ("M6", "tools/list", check_tools_list),
    ("M7", "get_context", check_get_context),
    ("M8", "Mcp-Name у base64", check_base64_name_header),
    ("Б15", "немає заголовка Mcp-Name", check_missing_name_header),
    ("Б15", "Mcp-Name не збігається з тілом", check_name_header_mismatch),
    ("M9", "list_objects і курсор", check_list_objects),
    ("M10", "describe_object", check_describe_object),
    ("M11", "describe_object для неіснуючого об'єкта", check_describe_missing),
    ("M12", "невідомий аргумент", check_invalid_arguments),
    ("M13", "невідомий інструмент", check_unknown_tool),
    ("M14", "некоректний JSON", check_parse_error),
    ("M15", "пакетний запит", check_batch),
    ("L1", "initialize (сумісність)", check_legacy_initialize),
    ("L2", "сценарій клієнта 2025-11-25", check_legacy_flow),
    ("L3", "запит 2025-ї редакції без заголовка версії", check_legacy_without_header),
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", required=True, help="MCP endpoint, e.g. https://mcp.company.ua/mcp")
    parser.add_argument("--token", default=os.environ.get("MCP1C_TOKEN"), help="PAT (or env MCP1C_TOKEN)")
    parser.add_argument("--auth-header", default="Authorization",
                        help="header that carries the token: Authorization (default) or X-MCP-Authorization")
    parser.add_argument("--cafile", help="CA bundle for a self-signed certificate")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--only", help="comma-separated check codes to run, e.g. M1,M6")
    parser.add_argument("-v", "--verbose", action="store_true", help="print raw responses")
    args = parser.parse_args()
    if not args.token:
        parser.error("token is required: --token or MCP1C_TOKEN")

    context = ssl.create_default_context(cafile=args.cafile) if args.cafile else None
    client = Client(args.url, args.token, context, args.timeout, args.verbose, args.auth_header)
    selected = {code.strip() for code in args.only.split(",")} if args.only else None

    failed = 0
    for code, title, check in CHECKS:
        if selected and code not in selected:
            continue
        try:
            detail = check(client)
            status = "OK  "
        except CheckFailed as error:
            detail, status = str(error), "FAIL"
            failed += 1
        except (urllib.error.URLError, OSError, ValueError) as error:
            detail, status = f"{type(error).__name__}: {error}", "FAIL"
            failed += 1
        print(f"{status} {code:<4} {title}: {detail}")

    print(f"\n{'all checks passed' if failed == 0 else f'{failed} check(s) failed'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
