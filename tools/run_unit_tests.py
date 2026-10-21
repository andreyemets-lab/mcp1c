#!/usr/bin/env python3
"""Runs OneScript unit tests for the pure-logic modules of the mcp1c extension.

The modules listed in tests/modules.txt are copied from exts/mcp1c/src/CommonModules
into build/oslib as <ModuleName>.os together with tests/lib/*.os; OneScript loads
the folder as a library (`#Использовать "../build/oslib"`) so the tests call the
modules exactly like 1C code does (mcp1c_Сеть.АдресВСписке(...)).

Usage: python tools/run_unit_tests.py [--oscript "dotnet build/onescript/oscript.dll"]
"""
from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def prepare(lib: Path) -> list[str]:
    if lib.exists():
        shutil.rmtree(lib)
    lib.mkdir(parents=True)
    modules = [
        line.strip()
        for line in (ROOT / "tests" / "modules.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    for name in modules:
        source = ROOT / "exts" / "mcp1c" / "src" / "CommonModules" / name / "Module.bsl"
        if not source.is_file():
            raise SystemExit(f"{source}: module not found")
        shutil.copyfile(source, lib / f"{name}.os")
    for helper in sorted((ROOT / "tests" / "lib").glob("*.os")):
        shutil.copyfile(helper, lib / helper.name)
    return modules


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--oscript", default=os.environ.get("ONESCRIPT", "oscript"),
                        help="command that starts OneScript (default: $ONESCRIPT or oscript)")
    args = parser.parse_args()

    modules = prepare(ROOT / "build" / "oslib")
    print(f"Modules under test: {', '.join(modules)}")
    command = shlex.split(args.oscript) + [str(ROOT / "tests" / "run.os")]
    return subprocess.call(command, cwd=ROOT)


if __name__ == "__main__":
    sys.exit(main())
