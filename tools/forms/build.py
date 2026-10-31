#!/usr/bin/env python3
"""Generates the managed forms of the extension (Form.form) from the descriptions in tools/forms.

Each description module defines PATH (form file relative to exts/mcp1c/src) and FORM (formxml.Form).
The form module (Module.bsl next to Form.form) is written by hand; the generator checks that it defines
every event and command handler the form refers to.

Usage:
  python tools/forms/build.py           regenerate Form.form files
  python tools/forms/build.py --check   fail if a Form.form differs from its description (CI)
"""
from __future__ import annotations

import argparse
import importlib
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE.parent.parent / "exts" / "mcp1c" / "src"
FORMS = ["workplace", "token_issue", "client", "sandbox", "profile"]

METHOD = re.compile(r"^[ \t]*(?:&\S+[ \t]+)?(?:Процедура|Функция)[ \t]+([^\s(]+)", re.IGNORECASE | re.MULTILINE)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="compare instead of writing")
    args = parser.parse_args()
    sys.path.insert(0, str(HERE))

    errors = 0
    for name in FORMS:
        spec = importlib.import_module(name)
        path = SRC / spec.PATH
        text = spec.FORM.render()
        module = path.parent / "Module.bsl"
        defined = set(METHOD.findall(module.read_text(encoding="utf-8-sig"))) if module.is_file() else set()
        for handler in spec.FORM.handlers():
            if handler not in defined:
                print(f"ERROR {module.relative_to(SRC)}: handler {handler} is not defined")
                errors += 1
        current = path.read_bytes().decode("utf-8") if path.is_file() else None
        if current == text:
            continue
        if args.check:
            print(f"ERROR {spec.PATH}: differs from tools/forms/{name}.py (run python tools/forms/build.py)")
            errors += 1
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(text.encode("utf-8"))
            print(f"written {spec.PATH}")
    print(f"{len(FORMS)} form(s), {errors} error(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
