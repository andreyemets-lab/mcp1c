#!/usr/bin/env python3
"""Load test for a deployed mcp1c server (TZ 10.1 targets, 13.3).

One client first: sequential calls of get_context (overhead of authentication, policies, serialization and
audit with almost no DBMS work), list_objects and describe_object (metadata cache) and query_records with
limit 50. Then N clients in parallel, each with its own token (calls_per_minute is counted per client),
each repeating the same sequence. Prints p50/p95/max per tool for both runs, the slowdown of the parallel
run and every failed call (HTTP status, JSON-RPC error, isError text: lock conflicts show up here).
A 429 is a failure, not a pause: give the clients a profile with calls_per_minute above the load.
Uses only the Python standard library.

Usage:
  MCP1C_TOKENS=mcp1c_...,mcp1c_... python tools/mcp_load_test.py --url http://localhost/base/hs/mcp1c \\
      --auth-header X-MCP-Authorization --object Справочник.Номенклатура \\
      --filter '{"field": "Наименование", "op": "starts_with", "value": "А"}'

Exit code: 0 - targets met and no failed calls, 1 - otherwise, 2 - usage error.
"""
from __future__ import annotations

import argparse
import json
import os
import ssl
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request
from typing import Any

MODERN = "2026-07-28"
TOOLS = ["get_context", "list_objects", "describe_object", "query_records"]
# TZ 10.1: p95 targets in milliseconds for the single client; the parallel run may be at most 30 % slower
# (a difference within NOISE_MS is not counted: for calls of a few milliseconds the share is meaningless).
TARGETS = {"get_context": 150, "list_objects": 300, "describe_object": 300, "query_records": 2000}
SLOWDOWN = 0.30
NOISE_MS = 20
# Prefix of a full object name -> kind code of list_objects.
KINDS = {"справочник": "catalog", "catalog": "catalog", "документ": "document", "document": "document",
         "перечисление": "enum", "enum": "enum", "плансчетов": "chart_of_accounts",
         "chartofaccounts": "chart_of_accounts", "планвидовхарактеристик": "chart_of_characteristic_types",
         "chartofcharacteristictypes": "chart_of_characteristic_types", "регистрсведений": "information_register",
         "informationregister": "information_register", "регистрнакопления": "accumulation_register",
         "accumulationregister": "accumulation_register"}


def percentile(values: list[float], share: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return float("nan")
    index = max(0, min(len(ordered) - 1, round(share * len(ordered) + 0.5) - 1))
    return ordered[index]


class Caller:
    def __init__(self, url: str, token: str, auth_header: str, timeout: float, context: ssl.SSLContext | None):
        self.url, self.token, self.auth_header, self.timeout, self.context = url, token, auth_header, timeout, context
        self.counter = 0

    def call(self, name: str, arguments: dict[str, Any]) -> tuple[float, str | None]:
        """Duration in ms and the failure text (None - success)."""
        self.counter += 1
        body = {"jsonrpc": "2.0", "id": self.counter, "method": "tools/call", "params": {
            "name": name, "arguments": arguments, "_meta": {
                "io.modelcontextprotocol/protocolVersion": MODERN,
                "io.modelcontextprotocol/clientInfo": {"name": "mcp1c-load-test", "version": "0.1.0"},
                "io.modelcontextprotocol/clientCapabilities": {}}}}
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
                   "MCP-Protocol-Version": MODERN, "Mcp-Method": "tools/call", "Mcp-Name": name,
                   self.auth_header: f"Bearer {self.token}"}
        request = urllib.request.Request(self.url, data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                                         headers=headers, method="POST")
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout, context=self.context) as answer:
                status, raw = answer.status, answer.read()
        except urllib.error.HTTPError as error:
            status, raw = error.code, error.read()
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            return (time.perf_counter() - started) * 1000, f"{name}: {error}"
        elapsed = (time.perf_counter() - started) * 1000
        text = raw.decode("utf-8", errors="replace")
        if status != 200:
            return elapsed, f"{name}: HTTP {status} {text[:200]}"
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return elapsed, f"{name}: not JSON {text[:200]}"
        if "error" in data:
            return elapsed, f"{name}: JSON-RPC {data['error']}"
        result = data.get("result") or {}
        if result.get("isError"):
            content = result.get("content") or [{}]
            return elapsed, f"{name}: isError {str(content[0].get('text', ''))[:200]}"
        return elapsed, None


def sequence(args: argparse.Namespace) -> list[tuple[str, dict[str, Any]]]:
    query: dict[str, Any] = {"object": args.object, "limit": args.limit}
    if args.filter:
        query["filters"] = [json.loads(args.filter)]
    kind = KINDS.get(args.object.split(".")[0].lower(), "catalog")
    return [("get_context", {}), ("list_objects", {"kinds": [kind], "limit": 50}),
            ("describe_object", {"object": args.object}), ("query_records", query)]


def run_client(caller: Caller, steps, rounds: int, results: dict[str, list[float]], failures: list[str],
               lock: threading.Lock, barrier: threading.Barrier | None = None) -> None:
    if barrier is not None:
        barrier.wait()
    for _ in range(rounds):
        for name, arguments in steps:
            elapsed, failure = caller.call(name, arguments)
            with lock:
                if failure:
                    failures.append(failure)
                else:
                    results[name].append(elapsed)


def summary(values: list[float]) -> str:
    if not values:
        return "   -       -       -   "
    return f"{statistics.median(values):7.0f} {percentile(values, 0.95):7.0f} {max(values):7.0f}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", required=True, help="MCP endpoint")
    parser.add_argument("--tokens", default=os.environ.get("MCP1C_TOKENS"),
                        help="comma-separated PATs of different clients (or env MCP1C_TOKENS)")
    parser.add_argument("--auth-header", default="Authorization", help="header for the token")
    parser.add_argument("--object", required=True, help="object for describe_object and query_records")
    parser.add_argument("--filter", help='filter for query_records, e.g. {"field": "Код", "op": "ge", "value": "0"}')
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--rounds", type=int, default=20, help="sequences per client")
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--cafile", help="CA bundle for a self-signed certificate")
    parser.add_argument("--json-out", help="file for all measured durations")
    args = parser.parse_args()
    tokens = [t.strip() for t in (args.tokens or "").split(",") if t.strip()]
    if not tokens:
        print("no tokens: pass --tokens or MCP1C_TOKENS", file=sys.stderr)
        return 2
    context = ssl.create_default_context(cafile=args.cafile) if args.cafile else None
    steps = sequence(args)
    lock = threading.Lock()

    def callers() -> list[Caller]:
        return [Caller(args.url, token, args.auth_header, args.timeout, context) for token in tokens]

    # Warm-up: metadata cache and sessions of the web server pool.
    warm_failures: list[str] = []
    run_client(callers()[0], steps, 1, {name: [] for name in TOOLS}, warm_failures, lock)
    if warm_failures:
        print("warm-up failed:\n  " + "\n  ".join(warm_failures))
        return 1

    single: dict[str, list[float]] = {name: [] for name in TOOLS}
    single_failures: list[str] = []
    started = time.perf_counter()
    run_client(callers()[0], steps, args.rounds, single, single_failures, lock)
    single_seconds = time.perf_counter() - started

    parallel: dict[str, list[float]] = {name: [] for name in TOOLS}
    parallel_failures: list[str] = []
    barrier = threading.Barrier(len(tokens))
    threads = [threading.Thread(target=run_client, args=(caller, steps, args.rounds, parallel, parallel_failures,
                                                         lock, barrier)) for caller in callers()]
    started = time.perf_counter()
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    parallel_seconds = time.perf_counter() - started

    calls_single = sum(len(v) for v in single.values()) + len(single_failures)
    calls_parallel = sum(len(v) for v in parallel.values()) + len(parallel_failures)
    print(f"single client: {calls_single} calls in {single_seconds:.1f} s; "
          f"{len(tokens)} clients in parallel: {calls_parallel} calls in {parallel_seconds:.1f} s "
          f"({calls_parallel / parallel_seconds:.1f} calls/s)")
    print(f"{'tool':16} {'single p50/p95/max, ms':>24} {'parallel p50/p95/max, ms':>26} {'p95 +%':>7} target")
    ok = not single_failures and not parallel_failures
    for name in TOOLS:
        p95_single = percentile(single[name], 0.95)
        p95_parallel = percentile(parallel[name], 0.95)
        slowdown = p95_parallel / p95_single - 1 if single[name] and parallel[name] else float("nan")
        met = p95_single <= TARGETS[name] and (slowdown <= SLOWDOWN or p95_parallel - p95_single <= NOISE_MS)
        ok = ok and met
        print(f"{name:16} {summary(single[name]):>24} {summary(parallel[name]):>26} {slowdown * 100:6.0f}% "
              f"{'OK  ' if met else 'MISS'} p95 <= {TARGETS[name]} ms, +{SLOWDOWN * 100:.0f}% or {NOISE_MS} ms")
    for title, failures in (("single", single_failures), ("parallel", parallel_failures)):
        if failures:
            print(f"{title}: {len(failures)} failed call(s)")
            for text in sorted(set(failures))[:20]:
                print(f"  {failures.count(text)} x {text}")
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as out:
            json.dump({"single": single, "parallel": parallel, "single_failures": single_failures,
                       "parallel_failures": parallel_failures, "clients": len(tokens), "rounds": args.rounds},
                      out, ensure_ascii=False)
    print("targets met" if ok else "targets missed or calls failed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
