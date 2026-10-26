#!/usr/bin/env python3
"""Извлекает тексты запросов из модулей BSL для проверки на платформе.

Литерал считается текстом запроса, если начинается с ВЫБРАТЬ (после пробелов). Литералы, которые
склеиваются с другими выражениями, содержат подстановки %1 для СтрШаблон или собираются построчно
(Строки.Добавить("ВЫБРАТЬ")), помечаются partial: целиком их проверить нельзя. Результат - JSON-массив {file, line, text, partial}.

Проверка на платформе (Windows, внешнее соединение с базой, где установлено расширение):
    python tools/query_texts.py exts/mcp1c/src --output queries.json
    powershell -File tools/check_queries.ps1 -Queries queries.json -Connection 'File="...";Usr="...";Pwd="";'
"""
import argparse
import json
import pathlib
import sys


def literals(text):
    """Строковые литералы модуля: (номер строки, значение, текст до литерала, символ после)."""
    i, n, line = 0, len(text), 1
    while i < n:
        c = text[i]
        if c == '\n':
            line += 1
            i += 1
        elif text.startswith('//', i):
            while i < n and text[i] != '\n':
                i += 1
        elif c == '"':
            start_line, start = line, i
            i += 1
            value = []
            while i < n:
                c = text[i]
                if c == '"':
                    if i + 1 < n and text[i + 1] == '"':
                        value.append('"')
                        i += 2
                        continue
                    i += 1
                    break
                if c == '\n':
                    value.append('\n')
                    line += 1
                    i += 1
                    # Продолжение литерала: пробелы, затем | или строка комментария.
                    while True:
                        while i < n and text[i] in ' \t\r':
                            i += 1
                        if text.startswith('//', i):
                            while i < n and text[i] != '\n':
                                i += 1
                            if i < n:
                                line += 1
                                i += 1
                            continue
                        break
                    if i < n and text[i] == '|':
                        i += 1
                    continue
                if c != '\r':
                    value.append(c)
                i += 1
            prefix = text[:start].rstrip()
            yield start_line, ''.join(value), prefix, text[i:].lstrip()[:1]
        else:
            i += 1


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('src', nargs='?', default='exts/mcp1c/src', help='каталог src проекта EDT')
    parser.add_argument('--output', help='файл JSON (UTF-8); без него - стандартный вывод')
    args = parser.parse_args()
    root = pathlib.Path(args.src)
    result = []
    for path in sorted(root.rglob('*.bsl')):
        text = path.read_text(encoding='utf-8-sig')
        for line, value, prefix, after in literals(text):
            if not value.lstrip().upper().startswith('ВЫБРАТЬ'):
                continue
            # Части текста: склейка, подстановки СтрШаблон, построчная сборка через Добавить.
            partial = (prefix.endswith('+') or after == '+' or '%1' in value
                       or prefix.endswith('Добавить('))
            result.append({'file': path.relative_to(root).as_posix(), 'line': line, 'text': value,
                           'partial': partial})
    text = json.dumps(result, ensure_ascii=False, indent=1) + '\n'
    if args.output:
        # Файлом, а не перенаправлением: PowerShell 5.1 пишет перенаправленный вывод в UTF-16.
        pathlib.Path(args.output).write_text(text, encoding='utf-8')
    else:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stdout.write(text)


if __name__ == '__main__':
    main()
