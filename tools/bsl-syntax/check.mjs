// Синтаксична перевірка модулів BSL граматикою 1c-syntax/codemirror-lang-bsl (Lezer).
// Знаходить структурні помилки (незакриті блоки, зламані вирази, зайві токени).
// Не замінює перевірку в EDT: типи, імена методів платформи і пропущені ";" між
// рядками граматика не перевіряє.
//
// Використання: node check.mjs <каталог або файл> [...]
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { bslLanguage } from "@1c-syntax/codemirror-lang-bsl";

const parser = bslLanguage.parser;

function collect(path, files) {
  if (statSync(path).isDirectory()) {
    for (const name of readdirSync(path).sort()) collect(join(path, name), files);
  } else if (path.endsWith(".bsl")) {
    files.push(path);
  }
  return files;
}

function position(text, offset) {
  const before = text.slice(0, offset);
  const line = before.split("\n").length;
  const column = offset - before.lastIndexOf("\n");
  return { line, column };
}

export function syntaxErrors(text) {
  const tree = parser.parse(text);
  const errors = [];
  tree.iterate({
    enter(node) {
      if (node.type.isError) errors.push(node.from);
    },
  });
  return [...new Set(errors)].sort((a, b) => a - b);
}

const roots = process.argv.slice(2);
if (roots.length === 0) {
  console.error("usage: node check.mjs <dir|file> [...]");
  process.exit(2);
}

let total = 0;
let filesCount = 0;
for (const root of roots) {
  for (const file of collect(root, [])) {
    filesCount += 1;
    const text = readFileSync(file, "utf8").replace(/^﻿/, "").replace(/\r\n/g, "\n");
    for (const offset of syntaxErrors(text)) {
      const { line, column } = position(text, offset);
      const snippet = text.split("\n")[line - 1].trim().slice(0, 100);
      console.log(`${relative(process.cwd(), file)}:${line}:${column}: syntax error near: ${snippet}`);
      total += 1;
    }
  }
}
console.log(`${filesCount} file(s), ${total} syntax error(s)`);
process.exit(total > 0 ? 1 : 0);
