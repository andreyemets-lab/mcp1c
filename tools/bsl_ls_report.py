#!/usr/bin/env python3
"""Summarises a BSL Language Server JSON report (bsl-json.json).

Prints findings grouped by module, optionally writes a Markdown summary for a PR comment,
and exits with code 1 when there are findings at or above the --fail-on severity.

Usage:
  python tools/bsl_ls_report.py build/bsl-ls/bsl-json.json --markdown build/bsl-ls/report.md
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.parse
from collections import Counter
from pathlib import Path

SEVERITIES = ["Error", "Warning", "Information", "Hint"]
TITLES = {"Error": "помилки", "Warning": "попередження", "Information": "інформаційні", "Hint": "підказки"}
MAX_ROWS = 200


def severity_name(value) -> str:
    if isinstance(value, int) and 1 <= value <= 4:
        return SEVERITIES[value - 1]
    if isinstance(value, str):
        for name in SEVERITIES:
            if value.lower() == name.lower():
                return name
    return "Information"


METADATA_FOLDERS = re.compile(
    r"(?:^|/)((?:CommonModules|HTTPServices|WebServices|Catalogs|Documents|Enums|Constants|InformationRegisters|"
    r"AccumulationRegisters|DataProcessors|Reports|CommonCommands|CommonForms|Roles|Subsystems|ScheduledJobs|"
    r"Configuration)/.*)$"
)


def display_path(raw, mdo_ref: str) -> str:
    text = str(raw or "")
    if text.startswith("file:"):
        text = urllib.parse.unquote(urllib.parse.urlsplit(text).path)
    text = text.replace("\\", "/")
    match = METADATA_FOLDERS.search(text)
    if match:
        return match.group(1)
    cwd = os.getcwd().replace("\\", "/") + "/"
    if text.startswith(cwd):
        text = text[len(cwd):]
    return text or mdo_ref or "?"


def load_findings(report: Path) -> list[dict]:
    data = json.loads(report.read_text(encoding="utf-8"))
    findings = []
    for info in data.get("fileinfos") or []:
        path = display_path(info.get("path"), info.get("mdoRef", ""))
        for diagnostic in info.get("diagnostics") or []:
            start = (diagnostic.get("range") or {}).get("start") or {}
            message = diagnostic.get("message")
            if isinstance(message, dict):
                message = message.get("value", "")
            findings.append({
                "path": path,
                "line": int(start.get("line", 0)) + 1,
                "severity": severity_name(diagnostic.get("severity")),
                "code": str(diagnostic.get("code") or ""),
                "message": str(message or "").strip(),
            })
    order = {name: index for index, name in enumerate(SEVERITIES)}
    findings.sort(key=lambda f: (order[f["severity"]], f["path"], f["line"]))
    return findings


def markdown(findings: list[dict], files: int, title: str) -> str:
    counts = Counter(f["severity"] for f in findings)
    summary = ", ".join(f"{TITLES[s]}: {counts.get(s, 0)}" for s in SEVERITIES)
    lines = [f"### {title}", "", f"Модулів: {files}. {summary}.", ""]
    if not findings:
        lines.append("Зауважень немає.")
        return "\n".join(lines) + "\n"
    by_code = Counter((f["severity"], f["code"]) for f in findings)
    lines += ["| Важливість | Діагностика | Кількість |", "| --- | --- | --- |"]
    for (severity, code), count in sorted(by_code.items(), key=lambda item: (SEVERITIES.index(item[0][0]), -item[1])):
        lines.append(f"| {severity} | `{code}` | {count} |")
    lines += ["", "<details><summary>Усі зауваження</summary>", "",
              "| Важливість | Місце | Діагностика | Повідомлення |", "| --- | --- | --- | --- |"]
    for f in findings[:MAX_ROWS]:
        message = f["message"].replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {f['severity']} | `{f['path']}:{f['line']}` | `{f['code']}` | {message} |")
    if len(findings) > MAX_ROWS:
        lines.append(f"| … | ще {len(findings) - MAX_ROWS} | | |")
    lines += ["", "</details>"]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("report", type=Path)
    parser.add_argument("--markdown", type=Path, help="write a Markdown summary to this file")
    parser.add_argument("--title", default="BSL Language Server")
    parser.add_argument("--fail-on", choices=SEVERITIES, default="Error",
                        help="fail when findings of this severity or higher exist (default: Error)")
    args = parser.parse_args()

    if not args.report.is_file():
        print(f"{args.report}: report not found", file=sys.stderr)
        return 2
    data_files = len(json.loads(args.report.read_text(encoding="utf-8")).get("fileinfos") or [])
    findings = load_findings(args.report)

    for f in findings:
        print(f"{f['severity']:<11} {f['path']}:{f['line']} [{f['code']}] {f['message']}")
    counts = Counter(f["severity"] for f in findings)
    print(f"{data_files} module(s); " + ", ".join(f"{s}: {counts.get(s, 0)}" for s in SEVERITIES))

    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(markdown(findings, data_files, args.title), encoding="utf-8")

    threshold = SEVERITIES.index(args.fail_on)
    failing = [f for f in findings if SEVERITIES.index(f["severity"]) <= threshold]
    return 1 if failing else 0


if __name__ == "__main__":
    sys.exit(main())
