#!/usr/bin/env python3
"""Static checks for the mcp1c EDT extension project (no 1C platform needed).

Checks:
  * every .mdo / .rights / .project file is well-formed XML;
  * every object referenced in Configuration.mdo has a folder and an .mdo with the same name,
    and every object folder is referenced in Configuration.mdo;
  * own objects use the extension name prefix;
  * identifiers (uuid, typeId, valueTypeId, objectId) are well-formed and unique;
  * common modules and HTTP services have Module.bsl; HTTP handlers exist in the module;
  * role rights refer to existing objects, and the service role (<prefix>Сервис, the only role of
    the publication's technical user) may use every HTTP service method;
  * managed forms (Form.form): unique item names and ids, data paths point to form attributes and their
    columns, buttons point to form commands, event and command handlers exist in the form module;
  * subsystem command interfaces (CommandInterface.cmi) refer to existing objects;
  * BSL block keywords are balanced (Функция/КонецФункции, Если/КонецЕсли, ...);
  * calls like mcp1c_Module.Method( point to an existing exported method.

Usage: python tools/check_metadata.py [exts/mcp1c]
"""
from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

# Configuration.mdo element -> (reference prefix, folder name)
COLLECTIONS = {
    "subsystems": ("Subsystem", "Subsystems"),
    "roles": ("Role", "Roles"),
    "commonModules": ("CommonModule", "CommonModules"),
    "httpServices": ("HTTPService", "HTTPServices"),
    "scheduledJobs": ("ScheduledJob", "ScheduledJobs"),
    "constants": ("Constant", "Constants"),
    "catalogs": ("Catalog", "Catalogs"),
    "informationRegisters": ("InformationRegister", "InformationRegisters"),
    "dataProcessors": ("DataProcessor", "DataProcessors"),
    "commonForms": ("CommonForm", "CommonForms"),
    "commonCommands": ("CommonCommand", "CommonCommands"),
    "commonTemplates": ("CommonTemplate", "CommonTemplates"),
    "enums": ("Enum", "Enums"),
}

ID_ATTRS = ("uuid", "typeId", "valueTypeId", "objectId")
ROLES_NS = "{http://v8.1c.ru/8.2/roles}"
SERVICE_ROLE = "Сервис"  # suffix after the name prefix
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")

# (opening keyword, closing keyword); counted as whole words outside strings and comments.
BLOCKS = [
    ("функция", "конецфункции"),
    ("процедура", "конецпроцедуры"),
    ("если", "конецесли"),
    ("попытка", "конецпопытки"),
    ("цикл", "конеццикла"),
]
WORD = re.compile(r"[A-Za-zА-Яа-яЁё_][A-Za-zА-Яа-яЁё_0-9]*")
METHOD_DEF = re.compile(
    r"^[ \t]*(?:&\S+[ \t]+)?(Функция|Процедура)[ \t]+([^\s(]+)[ \t]*\(([^)]*)\)[ \t]*(Экспорт)?",
    re.IGNORECASE | re.MULTILINE,
)


class Checker:
    def __init__(self, project: Path) -> None:
        self.project = project
        self.src = project / "src"
        self.errors: list[str] = []
        self.prefix = ""
        self.objects: set[str] = set()  # "Catalog.mcp1c_X" for every object in Configuration.mdo

    def error(self, message: str) -> None:
        self.errors.append(message)

    @staticmethod
    def rel(path: Path) -> str:
        try:
            return str(path.relative_to(Path.cwd()))
        except ValueError:
            return str(path)

    # --- XML -----------------------------------------------------------------
    def parse(self, path: Path) -> ET.Element | None:
        try:
            return ET.parse(path).getroot()
        except ET.ParseError as exc:
            self.error(f"{self.rel(path)}: invalid XML: {exc}")
            return None

    def check_xml_files(self) -> None:
        """Parses every XML file once and checks that identifiers are unique."""
        seen: dict[str, str] = {}
        for pattern in ("*.mdo", "*.rights", "*.form", "*.cmi", ".project"):
            for path in sorted(self.project.rglob(pattern)):
                root = self.parse(path)
                if root is None:
                    continue
                for element in root.iter():
                    for attr in ID_ATTRS:
                        value = element.get(attr)
                        if value is None:
                            continue
                        where = f"{self.rel(path)} <{element.tag.split('}')[-1]} {attr}>"
                        if not UUID_RE.fullmatch(value):
                            self.error(f"{where}: malformed identifier {value}")
                        elif value in seen:
                            self.error(f"{where}: identifier {value} duplicates {seen[value]}")
                        else:
                            seen[value] = where

    # --- Configuration -------------------------------------------------------
    def check_configuration(self) -> None:
        path = self.src / "Configuration" / "Configuration.mdo"
        root = self.parse(path)
        if root is None:
            return
        prefix = root.find("namePrefix")
        self.prefix = prefix.text if prefix is not None and prefix.text else ""
        if not self.prefix:
            self.error(f"{self.rel(path)}: namePrefix is empty")

        referenced: set[tuple[str, str]] = set()
        for tag, (ref_prefix, folder) in COLLECTIONS.items():
            for element in root.findall(tag):
                text = (element.text or "").strip()
                if not text.startswith(ref_prefix + "."):
                    self.error(f"{self.rel(path)}: <{tag}> {text!r} must start with {ref_prefix}.")
                    continue
                name = text[len(ref_prefix) + 1 :]
                referenced.add((folder, name))
                self.objects.add(text)
                self.check_object(folder, name)

        for tag, (_, folder) in COLLECTIONS.items():
            folder_path = self.src / folder
            if not folder_path.is_dir():
                continue
            for child in sorted(folder_path.iterdir()):
                if child.is_dir() and (folder, child.name) not in referenced:
                    self.error(f"{self.rel(child)}: object is not listed in Configuration.mdo <{tag}>")

    def check_object(self, folder: str, name: str) -> None:
        mdo = self.src / folder / name / f"{name}.mdo"
        if not mdo.is_file():
            self.error(f"{self.rel(mdo)}: missing")
            return
        root = self.parse(mdo)
        if root is None:
            return
        name_element = root.find("name")
        if name_element is None or name_element.text != name:
            self.error(f"{self.rel(mdo)}: <name> must be {name!r}")
        if self.prefix and not name.startswith(self.prefix):
            self.error(f"{self.rel(mdo)}: own object name must start with {self.prefix!r}")

        module = self.src / folder / name / "Module.bsl"
        if folder in ("CommonModules", "HTTPServices") and not module.is_file():
            self.error(f"{self.rel(module)}: missing")
        if folder == "HTTPServices" and module.is_file():
            code = self.strip_code(module.read_text(encoding="utf-8"))
            defined = {m.group(2) for m in METHOD_DEF.finditer(code)}
            for handler in root.iter("handler"):
                if handler.text not in defined:
                    self.error(f"{self.rel(module)}: handler {handler.text} is not defined")
        if folder == "Roles" and not (self.src / folder / name / "Rights.rights").is_file():
            self.error(f"{self.rel(self.src / folder / name)}: Rights.rights missing")
        if folder == "CommonForms":
            for required in ("Form.form", "Module.bsl"):
                if not (self.src / folder / name / required).is_file():
                    self.error(f"{self.rel(self.src / folder / name / required)}: missing")

    # --- Roles ---------------------------------------------------------------
    def http_methods(self) -> set[str]:
        """Rights object names of all HTTP service methods: HTTPService.S.URLTemplate.T.Method.M."""
        methods: set[str] = set()
        for mdo in sorted((self.src / "HTTPServices").glob("*/*.mdo")):
            root = self.parse(mdo)
            if root is None:
                continue
            service = root.findtext("name")
            for template in root.findall("urlTemplates"):
                for method in template.findall("methods"):
                    methods.add(
                        f"HTTPService.{service}.URLTemplate.{template.findtext('name')}.Method.{method.findtext('name')}"
                    )
        return methods

    def check_roles(self) -> None:
        methods = self.http_methods()
        for path in sorted((self.src / "Roles").glob("*/Rights.rights")):
            root = self.parse(path)
            if root is None:
                continue
            used: set[str] = set()
            for element in root.findall(ROLES_NS + "object"):
                name = element.findtext(ROLES_NS + "name") or ""
                parts = name.split(".")
                if parts[0] == "Configuration":
                    pass
                elif ".".join(parts[:2]) not in self.objects:
                    self.error(f"{self.rel(path)}: rights for unknown object {name}")
                elif parts[0] == "HTTPService" and name not in methods:
                    self.error(f"{self.rel(path)}: rights for unknown HTTP service method {name}")
                for right in element.findall(ROLES_NS + "right"):
                    if right.findtext(ROLES_NS + "name") == "Use" and right.findtext(ROLES_NS + "value") == "true":
                        used.add(name)
            # Without the Use right the platform answers 403 before the service module runs.
            if path.parent.name == self.prefix + SERVICE_ROLE:
                for name in sorted(methods - used):
                    self.error(f"{self.rel(path)}: service role has no Use right for {name}")

    # --- Forms ---------------------------------------------------------------
    def check_forms(self) -> None:
        for path in sorted(self.src.rglob("Form.form")):
            root = self.parse(path)
            if root is not None:
                self.check_form(path, root)

    def check_form(self, path: Path, root: ET.Element) -> None:
        where = self.rel(path)
        names: set[str] = set()
        ids: set[str] = set()
        # Items, their extended tooltips, context menus, command bars and table additions share one id space.
        for element in root.iter():
            tag = element.tag
            if tag not in ("items", "extendedTooltip", "contextMenu", "autoCommandBar", "searchStringAddition",
                           "viewStatusAddition", "searchControlAddition"):
                continue
            name, ident = element.findtext("name"), element.findtext("id")
            if name is None or ident is None:
                continue
            if name in names:
                self.error(f"{where}: item name {name} is used twice")
            names.add(name)
            if ident != "-1":
                if ident in ids:
                    self.error(f"{where}: item id {ident} is used twice ({name})")
                ids.add(ident)

        attributes: dict[str, set[str]] = {}
        for attribute in root.findall("attributes"):
            attributes[attribute.findtext("name") or ""] = {c.findtext("name") or "" for c in attribute.findall("columns")}
        for data_path in root.iter("dataPath"):
            segments = (data_path.findtext("segments") or "").split(".")
            if segments[0] not in attributes:
                self.error(f"{where}: data path {'.'.join(segments)} - no form attribute {segments[0]}")
            elif len(segments) > 1 and attributes[segments[0]] and segments[1] not in attributes[segments[0]]:
                self.error(f"{where}: data path {'.'.join(segments)} - attribute has no column {segments[1]}")

        commands = {command.findtext("name") for command in root.findall("formCommands")}
        for command in root.iter("commandName"):
            text = command.text or ""
            if text.startswith("Form.Command.") and text[len("Form.Command."):] not in commands:
                self.error(f"{where}: button refers to unknown form command {text}")

        module = path.parent / "Module.bsl"
        defined = set()
        if module.is_file():
            defined = {m.group(2) for m in METHOD_DEF.finditer(self.strip_code(module.read_text(encoding="utf-8")))}
        handlers = [h.findtext("name") for h in root.iter("handlers")]
        handlers += [h.findtext("name") for h in root.iter("handler")]
        for handler in handlers:
            if handler and handler not in defined:
                self.error(f"{self.rel(module)}: form handler {handler} is not defined")

    def check_command_interfaces(self) -> None:
        for path in sorted(self.src.rglob("CommandInterface.cmi")):
            root = self.parse(path)
            if root is None:
                continue
            for element in root.iter():
                if element.tag not in ("command", "commands") or not element.text:
                    continue
                # "CommonForm.X.StandardCommand.Open", "Catalog.X.StandardCommand.OpenList", "CommonCommand.X"
                parts = element.text.split(".")
                owner = ".".join(parts[:2])
                if len(parts) >= 2 and parts[1].startswith(self.prefix) and owner not in self.objects:
                    self.error(f"{self.rel(path)}: command {element.text} - unknown object {owner}")

    # --- BSL -----------------------------------------------------------------
    @staticmethod
    def strip_code(text: str) -> str:
        """Removes comments and string literals, keeps line structure."""
        out_lines = []
        in_string = False
        for line in text.splitlines():
            result = []
            i = 0
            if in_string:
                stripped = line.lstrip()
                if stripped.startswith("|"):
                    i = len(line) - len(stripped) + 1
                else:
                    in_string = False
            while i < len(line):
                ch = line[i]
                if in_string:
                    if ch == '"':
                        if i + 1 < len(line) and line[i + 1] == '"':
                            i += 2
                            continue
                        in_string = False
                    i += 1
                    continue
                if ch == '"':
                    in_string = True
                    i += 1
                    continue
                if line.startswith("//", i):
                    break
                result.append(ch)
                i += 1
            out_lines.append("".join(result))
        return "\n".join(out_lines)

    def check_bsl(self) -> None:
        modules: dict[str, dict[str, bool]] = {}
        sources: dict[Path, str] = {}
        for path in sorted(self.src.rglob("*.bsl")):
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                self.error(f"{self.rel(path)}: not UTF-8")
                continue
            code = self.strip_code(text)
            sources[path] = code
            words = [w.lower() for w in WORD.findall(code)]
            for opening, closing in BLOCKS:
                if words.count(opening) != words.count(closing):
                    self.error(
                        f"{self.rel(path)}: {opening}={words.count(opening)} vs {closing}={words.count(closing)}"
                    )
            regions = len(re.findall(r"^\s*#Область\b", code, re.MULTILINE))
            end_regions = len(re.findall(r"^\s*#КонецОбласти\b", code, re.MULTILINE))
            if regions != end_regions:
                self.error(f"{self.rel(path)}: #Область={regions} vs #КонецОбласти={end_regions}")
            methods: dict[str, bool] = {}
            for match in METHOD_DEF.finditer(code):
                method = match.group(2)
                if method.lower() in (m.lower() for m in methods):
                    self.error(f"{self.rel(path)}: method {method} is defined twice")
                methods[method] = bool(match.group(4))
            if path.parent.parent.name == "CommonModules":
                modules[path.parent.name] = methods

        if not self.prefix:
            return
        call = re.compile(r"(?<![\w.])(" + re.escape(self.prefix) + r"[^\s.(]+)\.([^\s.(]+)\s*\(")
        for path, code in sources.items():
            for match in call.finditer(code):
                module, method = match.group(1), match.group(2)
                if module not in modules:
                    self.error(f"{self.rel(path)}: unknown module {module}")
                elif method not in modules[module]:
                    self.error(f"{self.rel(path)}: {module}.{method} is not defined")
                elif not modules[module][method]:
                    self.error(f"{self.rel(path)}: {module}.{method} is not exported")

    def run(self) -> int:
        self.check_configuration()
        self.check_roles()
        self.check_forms()
        self.check_command_interfaces()
        self.check_xml_files()
        self.check_bsl()
        for message in self.errors:
            print(f"ERROR {message}")
        print(f"{len(self.errors)} error(s)")
        return 1 if self.errors else 0


def main() -> int:
    project = Path(sys.argv[1] if len(sys.argv) > 1 else "exts/mcp1c").resolve()
    if not (project / "src" / "Configuration" / "Configuration.mdo").is_file():
        print(f"{project}: not an EDT project", file=sys.stderr)
        return 2
    return Checker(project).run()


if __name__ == "__main__":
    sys.exit(main())
