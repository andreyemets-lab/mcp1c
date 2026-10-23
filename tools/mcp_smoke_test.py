#!/usr/bin/env python3
"""Smoke and conformance test for a deployed mcp1c server (stages 0-2).

Checks transport security (token, Origin, Content-Type), MCP 2026-07-28 behaviour
(server/discover, mirrored headers, error codes, tools), the 2025-11-25 / 2025-06-18
compatibility mode (initialize, ping), the stage 1 data tools (paging and cursor
signatures, query injection attempts, hidden objects, profile limits) and stage 2:
resources and resource templates, prompts, custom tools. Data checks use the objects
the token's profile allows and are skipped when the base has no suitable data.
Uses only the Python standard library.

Usage:
  MCP1C_TOKEN=mcp1c_... python tools/mcp_smoke_test.py --url https://mcp.company.ua/mcp
  python tools/mcp_smoke_test.py --url http://localhost/base/hs/mcp1c --token mcp1c_... -v
  # if the 1C web server extension intercepts "Authorization: Bearer":
  python tools/mcp_smoke_test.py --url ... --auth-header X-MCP-Authorization
  # publication without the technical user in its connection string (1C asks for Basic):
  python tools/mcp_smoke_test.py --url ... --platform-auth "user:password"
  # an object that exists but is outside the profile must look like a missing one:
  python tools/mcp_smoke_test.py --url ... --denied-object Справочник.Пользователи

Exit code: 0 - all checks passed, 1 - some checks failed, 2 - usage error.
"""
from __future__ import annotations

import argparse
import base64
import datetime
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable

MODERN = "2026-07-28"
LEGACY = "2025-11-25"
ALL_TOOLS = ["get_context", "list_objects", "describe_object", "find_objects", "get_object",
             "query_records", "get_balances", "get_turnovers", "get_slice"]
NOT_FOUND = "не знайдено або недоступний"
MCP_NAME = re.compile(r"^[a-z][a-z0-9_]{2,63}$")


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


class Skipped(Exception):
    """The check does not apply: no suitable objects or data, or the profile forbids the tool."""


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
    denied_object: str | None = None
    platform_auth: str | None = None  # "Basic ..." for the 1C publication itself
    counter: int = field(default=0)
    cache: dict[str, Any] = field(default_factory=dict)

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
        if self.platform_auth:
            request_headers["Authorization"] = self.platform_auth
        if token == "default":
            token = self.token
        if token:
            request_headers[self.auth_header] = f"Bearer {token}"
        request_headers.update(headers or {})
        request = urllib.request.Request(
            url or self.url, data=data, method=method,
            headers={k: v for k, v in request_headers.items() if v is not None},
        )
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout, context=self.context) as answer:
                    status, raw_headers, raw = answer.status, answer.headers, answer.read()
            except urllib.error.HTTPError as error:
                status, raw_headers, raw = error.code, error.headers, error.read()
            # 429 - calls_per_minute of the profile: wait as the server asks and repeat.
            retry_after = raw_headers.get("Retry-After") if status == 429 else None
            if not (retry_after and retry_after.isdigit() and int(retry_after) <= 120 and attempt < 2):
                break
            print(f"    .. 429, waiting {retry_after} s (calls per minute of the profile)")
            time.sleep(int(retry_after) + 1)
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


def tool_data(c: Client, name: str, arguments: dict) -> dict:
    """structuredContent of a successful tools/call."""
    result = tool_payload(c.call_tool(name, arguments))
    expect(result.get("isError") is False, f"{name}: isError: {tool_text(result)[:300]}")
    return result.get("structuredContent", {})


def tool_error(c: Client, name: str, arguments: dict) -> str:
    """Text of a tools/call that must end with isError."""
    result = tool_payload(c.call_tool(name, arguments))
    expect(result.get("isError") is True, f"{name}: isError must be true, got {str(result)[:300]}")
    return tool_text(result)


def tool_text(result: dict) -> str:
    content = result.get("content") or [{}]
    return str(content[0].get("text", ""))


def available_tools(c: Client) -> list[str]:
    if "tools" not in c.cache:
        c.cache["tools"] = [t.get("name") for t in tool_payload(c.modern("tools/list")).get("tools", [])]
    return c.cache["tools"]


def require_tools(c: Client, *names: str) -> None:
    missing = [name for name in names if name not in available_tools(c)]
    if missing:
        raise Skipped(f"profile does not allow {', '.join(missing)}")


def objects_of_kind(c: Client, kind: str, limit: int = 50) -> list[str]:
    data = tool_data(c, "list_objects", {"kinds": [kind], "limit": limit})
    return [item["object"] for item in data.get("items", [])]


def sample_catalog(c: Client) -> dict:
    """A catalog with at least one row: name, first page of query_records (limit 2)."""
    if "catalog" not in c.cache:
        require_tools(c, "list_objects", "query_records")
        c.cache["catalog"] = None
        for name in objects_of_kind(c, "catalog")[:10]:
            result = tool_payload(c.call_tool("query_records", {"object": name, "limit": 2}))
            data = result.get("structuredContent") or {}
            if result.get("isError") is False and data.get("row_count", 0) > 0:
                c.cache["catalog"] = {"object": name, "page": data}
                break
    if not c.cache["catalog"]:
        raise Skipped("no readable catalog with rows")
    return c.cache["catalog"]


def column_index(page: dict, name: str) -> int | None:
    for index, column in enumerate(page.get("columns", [])):
        if column.get("name") == name:
            return index
    return None


def first_ref(page: dict) -> dict | None:
    index = column_index(page, "Ссылка")
    if index is None:
        return None
    value = page["rows"][0][index]
    return value if isinstance(value, dict) and value.get("ref") else None


def tampered(cursor: str) -> str:
    body, _, signature = cursor.partition(".")
    last = "A" if signature[-1:] != "A" else "B"
    return f"{body}.{signature[:-1]}{last}"


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
    capabilities = result.get("capabilities", {})
    for capability in ("tools", "resources", "prompts"):
        expect(capability in capabilities, f"capabilities.{capability} missing")
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
    r = c.modern("completion/complete")
    expect(r.status == 404 and r.error_code == -32601, f"HTTP {r.status}, code {r.error_code}; expected 404/-32601")
    return "404 / -32601"


def check_tools_list(c: Client) -> str:
    first = tool_payload(c.modern("tools/list"))
    second = tool_payload(c.modern("tools/list"))
    names = [tool.get("name") for tool in first.get("tools", [])]
    expect(names == [tool.get("name") for tool in second.get("tools", [])], "tool order is not deterministic")
    expect("get_context" in names, f"get_context missing in {names}")
    # Built-in tools in canonical order, then the administrator's custom tools by name (stage 2).
    builtin = [name for name in names if name in ALL_TOOLS]
    custom = names[len(builtin):]
    expect(names[:len(builtin)] == [name for name in ALL_TOOLS if name in names],
           f"built-in tools are not first or not in canonical order: {names}")
    expect(custom == sorted(custom), f"custom tools are not sorted by name: {custom}")
    expect(all(MCP_NAME.match(name or "") for name in custom), f"custom tool names: {custom}")
    c.cache["custom_tools"] = custom
    for tool in first["tools"]:
        expect(tool.get("inputSchema", {}).get("type") == "object", f"{tool.get('name')}: inputSchema.type")
        expect(tool.get("outputSchema", {}).get("type") == "object", f"{tool.get('name')}: outputSchema.type")
        expect(tool.get("annotations", {}).get("readOnlyHint") is True, f"{tool.get('name')}: readOnlyHint")
    expect(first.get("cacheScope") == "private" and isinstance(first.get("ttlMs"), int), "ttlMs/cacheScope missing")
    c.cache["tools"] = names
    return ", ".join(names) + (f" (custom: {len(custom)})" if custom else "")


def check_get_context(c: Client) -> str:
    result = tool_payload(c.call_tool("get_context"))
    expect(result.get("isError") is False, f"isError: {result.get('content')}")
    data = result.get("structuredContent", {})
    configuration = data.get("configuration", {})
    expect(bool(configuration.get("name")), "configuration.name is empty")
    expect(result.get("content", [{}])[0].get("type") == "text", "content[0] is not text")
    access = data.get("access", {})
    limits = access.get("limits", {})
    expect(isinstance(limits.get("rows_per_call"), int) and limits["rows_per_call"] > 0,
           f"access.limits.rows_per_call: {limits}")
    c.cache["limits"] = limits
    return (f"{configuration.get('synonym') or configuration.get('name')} {configuration.get('version')}, "
            f"platform {data.get('platform', {}).get('version')}, tz {data.get('server_time', {}).get('timezone')}, "
            f"profile {access.get('profile')!r}, {limits.get('rows_per_call')} rows per call")


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
    expect([t["name"] for t in tools.get("tools", [])] == available_tools(c), "tools/list differs")
    expect("resultType" not in tools, "resultType must not be sent to 2025-era clients")
    call = tool_payload(c.legacy("tools/call", {"name": "get_context", "arguments": {}}))
    expect(call.get("isError") is False, "get_context failed")
    return "202, ping, tools/list, tools/call"


def check_legacy_without_header(c: Client) -> str:
    r = c.legacy("tools/list", version=None)
    expect(r.status == 400 and r.error_code == -32020, f"HTTP {r.status}, code {r.error_code}; expected 400/-32020")
    return "400 / -32020"


# --- stage 1: data tools --------------------------------------------------------

def check_query_records(c: Client) -> str:
    sample = sample_catalog(c)
    page = sample["page"]
    columns = page.get("columns", [])
    expect(bool(columns) and all("name" in col and "kind" in col for col in columns), f"columns: {columns}")
    expect(all(len(row) == len(columns) for row in page.get("rows", [])), "row width differs from columns")
    expect(page.get("row_count") == len(page.get("rows", [])) <= 2, f"row_count={page.get('row_count')}")
    names = ", ".join(col["name"] for col in columns)
    if not page.get("has_more"):
        return f"{sample['object']}: {page['row_count']} row(s), one page; {names}"
    expect(bool(page.get("next_cursor")), "has_more without next_cursor")
    second = tool_data(c, "query_records", {"object": sample["object"], "limit": 2, "cursor": page["next_cursor"]})
    first_rows = {json.dumps(row, sort_keys=True, ensure_ascii=False) for row in page["rows"]}
    second_rows = {json.dumps(row, sort_keys=True, ensure_ascii=False) for row in second.get("rows", [])}
    expect(second_rows and not first_rows & second_rows, "second page is empty or overlaps the first")
    return f"{sample['object']}: 2 pages; {names}"


def check_cursor_tampering(c: Client) -> str:
    sample = sample_catalog(c)
    cursor = sample["page"].get("next_cursor")
    if not cursor:
        raise Skipped("one page only: no cursor to tamper with")
    text = tool_error(c, "query_records", {"object": sample["object"], "limit": 2, "cursor": tampered(cursor)})
    expect("урсор" in text, f"tampered cursor: unexpected error {text[:200]}")
    first_column = sample["page"]["columns"][0]["name"]
    text = tool_error(c, "query_records", {"object": sample["object"], "limit": 2, "cursor": cursor,
                                           "fields": [first_column]})
    expect("урсор" in text, f"cursor accepted for other arguments: {text[:200]}")
    return "tampered signature and other arguments rejected"


def check_get_object(c: Client) -> str:
    sample = sample_catalog(c)
    require_tools(c, "get_object")
    ref = first_ref(sample["page"])
    if ref is None:
        raise Skipped("no Ссылка column in the sample")
    data = tool_data(c, "get_object", {"object": sample["object"], "ref": ref["ref"], "tabular_limit": 1})
    expect((data.get("ref") or {}).get("ref") == ref["ref"], f"ref={data.get('ref')}")
    expect(isinstance(data.get("fields"), dict), "fields missing")
    text = tool_error(c, "get_object", {"object": sample["object"], "ref": "00000000-0000-0000-0000-000000000000"})
    expect(NOT_FOUND in text, f"unknown ref: unexpected error {text[:200]}")
    detail = f"{len(data['fields'])} field(s); unknown ref - not found"
    query = (ref.get("presentation") or "").strip()[:20]
    if "find_objects" in available_tools(c) and query and query != "<приховано>":
        found = tool_data(c, "find_objects", {"query": query, "objects": [sample["object"]], "limit": 5})
        expect(isinstance(found.get("items"), list), "find_objects: items missing")
        detail += f"; find_objects {query!r}: {found.get('returned')}"
    return detail


def check_injection(c: Client) -> str:
    sample = sample_catalog(c)
    name = sample["object"]
    for field_name in ("Ссылка КАК Х ИЗ Справочник.Пользователи //", "Ссылка) ИЛИ (ИСТИНА", "Ссылка;ВЫБРАТЬ 1"):
        tool_error(c, "query_records", {"object": name, "fields": [field_name], "limit": 1})
    tool_error(c, "query_records", {"object": name + " ГДЕ ИСТИНА", "limit": 1})
    tool_error(c, "query_records", {"object": name, "limit": 1, "order_by": [{"field": "Ссылка УБЫВ, 1"}]})
    string_columns = [col["name"] for col in sample["page"]["columns"] if col.get("kind") == "string"]
    if not string_columns:
        return "field, table and order names rejected"
    data = tool_data(c, "query_records", {"object": name, "limit": 1, "filters": [
        {"field": string_columns[0], "op": "eq", "value": "' ИЛИ ИСТИНА ИЛИ '"}]})
    expect(data.get("row_count", 0) == 0, "a string value changed the query")
    return f"field, table and order names rejected; a value is only a parameter ({string_columns[0]})"


def check_hidden_object(c: Client) -> str:
    require_tools(c, "query_records")
    missing_name = "Справочник.НетТакогоОбъекта_mcp1c"
    missing = tool_error(c, "query_records", {"object": missing_name, "limit": 1})
    expect(NOT_FOUND in missing, f"missing object: unexpected error {missing[:200]}")
    if not c.denied_object:
        return "missing object - not found; pass --denied-object to compare with a hidden one"
    denied = tool_error(c, "query_records", {"object": c.denied_object, "limit": 1})
    expect(denied.replace(c.denied_object, "<object>") == missing.replace(missing_name, "<object>"),
           f"hidden object differs from a missing one: {denied[:200]}")
    short_name = c.denied_object.split(".")[-1]
    listing = tool_data(c, "list_objects", {"search": short_name, "limit": 100})
    listed = [item["object"] for item in listing.get("items", [])]
    expect(c.denied_object not in listed, f"{c.denied_object} is listed by list_objects")
    return f"{c.denied_object} looks like a missing object and is not listed"


def check_row_limit(c: Client) -> str:
    sample = sample_catalog(c)
    if "limits" not in c.cache:
        c.cache["limits"] = tool_data(c, "get_context", {}).get("access", {}).get("limits", {})
    per_call = c.cache["limits"].get("rows_per_call", 0)
    data = tool_data(c, "query_records", {"object": sample["object"], "limit": 1000})
    expect(data.get("row_count", 0) <= per_call, f"row_count {data.get('row_count')} > rows_per_call {per_call}")
    if per_call < 1000:
        expect(any("обмежено" in str(note) for note in data.get("notes", [])), "no note about the profile limit")
    return f"{data.get('row_count')} row(s), rows_per_call {per_call}"


def recent_period(days: int = 30) -> dict:
    end = datetime.date.today()
    return {"from": (end - datetime.timedelta(days=days)).isoformat(), "to": end.isoformat()}


def check_period_limit(c: Client) -> str:
    require_tools(c, "list_objects", "get_turnovers")
    registers = objects_of_kind(c, "accumulation_register", 5)
    if not registers:
        raise Skipped("no readable accumulation registers")
    if "limits" not in c.cache:
        c.cache["limits"] = tool_data(c, "get_context", {}).get("access", {}).get("limits", {})
    days = c.cache["limits"].get("max_period_days") or 366
    text = tool_error(c, "get_turnovers", {"register": registers[0], "period": recent_period(days + 1)})
    expect("Період довший" in text, f"unexpected error: {text[:200]}")
    return f"{days + 2} days for {registers[0]} rejected"


def check_registers(c: Client) -> str:
    require_tools(c, "list_objects", "describe_object")
    done = []
    for name in objects_of_kind(c, "accumulation_register", 10)[:3]:
        tools = tool_data(c, "describe_object", {"object": name, "include": ["properties"]}).get("tools", [])
        if "get_balances" in tools:
            data = tool_data(c, "get_balances", {"register": name, "limit": 3})
            done.append(f"get_balances {name}: {data.get('row_count')}")
        if "get_turnovers" in tools:
            data = tool_data(c, "get_turnovers", {"register": name, "period": recent_period(), "limit": 3})
            done.append(f"get_turnovers {name}: {data.get('row_count')}")
        if done:
            break
    for name in objects_of_kind(c, "information_register", 50)[:8]:
        tools = tool_data(c, "describe_object", {"object": name, "include": ["properties"]}).get("tools", [])
        if "get_slice" in tools:
            data = tool_data(c, "get_slice", {"register": name, "limit": 3})
            done.append(f"get_slice {name}: {data.get('row_count')}")
            break
    if not done:
        raise Skipped("no readable registers with balance, turnover or slice tools")
    return "; ".join(done)


def encoded_name(value: str) -> str:
    """Mcp-Name value: ASCII as is, anything else in the base64 form of MCP 2026-07-28."""
    if value.isascii():
        return value
    return "=?base64?" + base64.b64encode(value.encode("utf-8")).decode("ascii") + "?="


def read_resource(c: Client, uri: str) -> Response:
    return c.modern("resources/read", {"uri": uri}, name_header=encoded_name(uri))


def resource_json(c: Client, uri: str) -> dict:
    result = tool_payload(read_resource(c, uri))
    contents = result.get("contents") or [{}]
    expect(contents[0].get("uri") == uri, f"contents[0].uri={contents[0].get('uri')!r}")
    expect(contents[0].get("mimeType") == "application/json", f"mimeType={contents[0].get('mimeType')!r}")
    return json.loads(contents[0].get("text") or "{}")


def check_resources_list(c: Client) -> str:
    listed = tool_payload(c.modern("resources/list"))
    uris = [item.get("uri") for item in listed.get("resources", [])]
    expect("onec://context" in uris, f"onec://context missing in {uris}")
    expect(listed.get("cacheScope") == "private", "cacheScope missing")
    templates = tool_payload(c.modern("resources/templates/list")).get("resourceTemplates", [])
    patterns = [item.get("uriTemplate") for item in templates]
    c.cache["resource_templates"] = patterns
    return f"resources {uris}, templates {patterns}"


def check_resource_context(c: Client) -> str:
    data = resource_json(c, "onec://context")
    expect(bool(data.get("configuration", {}).get("name")), "configuration.name is empty")
    return f"onec://context: {data['configuration']['name']}"


def check_resource_metadata(c: Client) -> str:
    if "onec://metadata/{object}" not in c.cache.get("resource_templates", []):
        tool_payload(c.modern("resources/templates/list"))
        raise Skipped("profile does not allow describe_object")
    objects = objects_of_kind(c, "catalog", 1) or objects_of_kind(c, "document", 1)
    if not objects:
        raise Skipped("no readable catalogs or documents")
    uri = "onec://metadata/" + urllib.parse.quote(objects[0], safe=".")
    data = resource_json(c, uri)
    expect(data.get("object") == objects[0], f"object={data.get('object')!r}, expected {objects[0]!r}")
    return f"{uri} (Mcp-Name in base64 if needed)"


def check_resource_not_found(c: Client) -> str:
    r = read_resource(c, "onec://nowhere")
    expect(r.status == 200 and r.error_code == -32602, f"HTTP {r.status}, code {r.error_code}; expected 200/-32602")
    data = (r.json or {}).get("error", {}).get("data", {})
    expect(data.get("uri") == "onec://nowhere", f"error.data={data}")
    return "-32602 Resource not found"


def check_prompts(c: Client) -> str:
    prompts = tool_payload(c.modern("prompts/list")).get("prompts", [])
    if not prompts:
        raise Skipped("no prompts for the profile")
    prompt = prompts[0]
    arguments = {arg["name"]: "test" for arg in prompt.get("arguments", []) if arg.get("required")}
    result = tool_payload(c.modern("prompts/get", {"name": prompt["name"], "arguments": arguments},
                                   name_header=prompt["name"]))
    messages = result.get("messages", [])
    expect(messages and messages[0].get("content", {}).get("type") == "text", f"messages={str(messages)[:200]}")
    missing = c.modern("prompts/get", {"name": "no_such_prompt_xyz", "arguments": {}}, name_header="no_such_prompt_xyz")
    expect(missing.error_code == -32602, f"unknown prompt: code {missing.error_code}, expected -32602")
    return f"{len(prompts)} prompt(s), {prompt['name']}: {len(messages)} message(s)"


def check_custom_tools(c: Client) -> str:
    if "custom_tools" not in c.cache:
        check_tools_list(c)
    custom = c.cache.get("custom_tools", [])
    if not custom:
        raise Skipped("no custom tools for the profile")
    result = tool_payload(c.call_tool(custom[0], {}))
    text = tool_text(result)
    if result.get("isError"):
        expect("аргумент" in text or "argument" in text.lower(), f"{custom[0]}: unexpected error {text[:200]}")
        return f"{custom[0]}: arguments are validated ({text[:80]})"
    data = result.get("structuredContent", {})
    expect(isinstance(data.get("rows"), list), f"{custom[0]}: structuredContent.rows missing")
    return f"{custom[0]}: {len(data['rows'])} row(s)"


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
    ("D1", "query_records і сторінки", check_query_records),
    ("Б10", "підроблений курсор і курсор інших аргументів", check_cursor_tampering),
    ("D2", "get_object, find_objects", check_get_object),
    ("Б8", "спроби ін'єкції в іменах і значеннях", check_injection),
    ("Б9", "прихований об'єкт не відрізняється від відсутнього", check_hidden_object),
    ("Б11", "ліміт рядків профілю", check_row_limit),
    ("Б12", "ліміт довжини періоду", check_period_limit),
    ("D3", "залишки, обороти, зріз", check_registers),
    ("R1", "resources/list і шаблони", check_resources_list),
    ("R2", "resources/read onec://context", check_resource_context),
    ("R3", "resources/read onec://metadata/{object}", check_resource_metadata),
    ("R4", "невідомий ресурс", check_resource_not_found),
    ("P1", "prompts/list і prompts/get", check_prompts),
    ("U1", "користувацький інструмент", check_custom_tools),
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", required=True, help="MCP endpoint, e.g. https://mcp.company.ua/mcp")
    parser.add_argument("--token", default=os.environ.get("MCP1C_TOKEN"), help="PAT (or env MCP1C_TOKEN)")
    parser.add_argument("--auth-header", default="Authorization",
                        help="header that carries the token: Authorization (default) or X-MCP-Authorization")
    parser.add_argument("--platform-auth", default=os.environ.get("MCP1C_PLATFORM_AUTH"), metavar="USER:PASSWORD",
                        help="1C credentials for a publication without the technical user in its connection string "
                             "(or env MCP1C_PLATFORM_AUTH): sent as Authorization: Basic, the token goes in "
                             "X-MCP-Authorization")
    parser.add_argument("--cafile", help="CA bundle for a self-signed certificate")
    parser.add_argument("--denied-object", help="full name of an existing object outside the token's profile")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--only", help="comma-separated check codes to run, e.g. M1,M6")
    parser.add_argument("-v", "--verbose", action="store_true", help="print raw responses")
    args = parser.parse_args()
    if not args.token:
        parser.error("token is required: --token or MCP1C_TOKEN")

    platform_auth = None
    if args.platform_auth:
        if ":" not in args.platform_auth:
            parser.error("--platform-auth: expected USER:PASSWORD (the password may be empty: USER:)")
        if args.auth_header.lower() == "authorization":
            args.auth_header = "X-MCP-Authorization"  # Authorization is taken by the 1C credentials
        platform_auth = "Basic " + base64.b64encode(args.platform_auth.encode("utf-8")).decode("ascii")

    context = ssl.create_default_context(cafile=args.cafile) if args.cafile else None
    client = Client(args.url, args.token, context, args.timeout, args.verbose, args.auth_header,
                    args.denied_object, platform_auth=platform_auth)
    selected = {code.strip() for code in args.only.split(",")} if args.only else None

    failed = 0
    for code, title, check in CHECKS:
        if selected and code not in selected:
            continue
        try:
            detail = check(client)
            status = "OK  "
        except Skipped as reason:
            detail, status = f"skipped: {reason}", "SKIP"
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
