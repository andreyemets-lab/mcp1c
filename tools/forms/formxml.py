"""Builds 1C:EDT managed form XML (Form.form) from a compact Python description.

A form is a tree of items (Group, Pages, Page, CommandBar, Field, Label, Button, Table), form
attributes (Attr, with Col for table columns) and form commands (Command). The builder numbers
items, adds the service sub-elements EDT expects (extended tooltip, context menu, table command bar
and search additions) and writes properties in the order EDT writes them. Properties that are false
by default in the EDT model (visible, enabled, header, showTitle, ...) are written only when true,
as EDT does, so a hidden item simply omits <visible>.

Texts are written in Ukrainian (see CLAUDE.md) under the language codes in LANGS: the extension adopts only
the "ru" language, but a session in Ukrainian (BAS) shows the "uk" value and falls back to the item name, not
to "ru", when it is missing.
"""
from __future__ import annotations

import re
from typing import Iterable, Sequence

LANGS = ("ru", "uk")

# Form events handled in the object form extension (catalog and data processor forms).
OBJECT_FORM_EVENTS = {
    "OnReadAtServer", "BeforeWrite", "BeforeWriteAtServer", "OnWriteAtServer", "AfterWriteAtServer", "AfterWrite",
}
# Field events written on the field itself; the rest go to the field's extension (extInfo).
FIELD_EVENTS = {"OnChange"}


def _text(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class Xml:
    """Indented XML writer with CRLF line ends, like EDT on Windows."""

    def __init__(self) -> None:
        self.lines: list[str] = []
        self.level = 0

    @staticmethod
    def _type(xsi: str | None) -> str:
        return f' xsi:type="{xsi}"' if xsi else ""

    def open(self, tag: str, xsi: str | None = None) -> None:
        self.lines.append("  " * self.level + f"<{tag}{self._type(xsi)}>")
        self.level += 1

    def close(self, tag: str) -> None:
        self.level -= 1
        self.lines.append("  " * self.level + f"</{tag}>")

    def leaf(self, tag: str, value: object, xsi: str | None = None) -> None:
        if value is None or value is False:
            return
        self.lines.append("  " * self.level + f"<{tag}{self._type(xsi)}>{_text(value)}</{tag}>")

    def empty(self, tag: str, xsi: str | None = None) -> None:
        self.lines.append("  " * self.level + f"<{tag}{self._type(xsi)}/>")

    def mls(self, tag: str, value: str | None) -> None:
        """Multilingual string: the same text for every language in LANGS."""
        if value is None:
            return
        for lang in LANGS:
            self.open(tag)
            self.leaf("key", lang)
            self.leaf("value", value)
            self.close(tag)

    def handlers(self, events: dict[str, str]) -> None:
        for event, name in events.items():
            self.open("handlers")
            self.leaf("event", event)
            self.leaf("name", name)
            self.close("handlers")

    def common(self, tag: str, value: bool = True) -> None:
        """<view>, <edit>, <use>, <userVisible>: availability for all roles."""
        self.open(tag)
        self.leaf("common", value)
        self.close(tag)

    def data_path(self, tag: str, path: str) -> None:
        self.open(tag, "form:DataPath")
        self.leaf("segments", path)
        self.close(tag)

    def text(self) -> str:
        return "\r\n".join(self.lines) + "\r\n"


class Ids:
    def __init__(self) -> None:
        self.next = 1

    def __call__(self) -> int:
        value = self.next
        self.next += 1
        return value


# --- Value types ------------------------------------------------------------------------------------

TYPE_SPEC = re.compile(r"^(String|Number|Date)(?:\((.*)\))?$")


def write_type(x: Xml, tag: str, spec: str | Sequence[str] | None) -> None:
    """Value type: "String(100)", "String" (unlimited), "Number(10,2)", "Number(10,0,+)" (non-negative),
    "Date" (date and time), "Date(Date)", "Boolean", "ValueTable", "CatalogRef.X", ... ; a list - composite type;
    None - arbitrary type."""
    if spec is None:
        x.empty(tag)
        return
    specs = [spec] if isinstance(spec, str) else list(spec)
    x.open(tag)
    qualifiers: list[tuple[str, str]] = []
    for item in specs:
        match = TYPE_SPEC.match(item)
        if match:
            x.leaf("types", match.group(1))
            qualifiers.append((match.group(1), match.group(2) or ""))
        else:
            x.leaf("types", item)
    for kind, args in qualifiers:
        if kind == "String":
            if args and args != "0":
                x.open("stringQualifiers")
                x.leaf("length", args)
                x.close("stringQualifiers")
            else:
                x.empty("stringQualifiers")
        elif kind == "Number":
            parts = [part.strip() for part in args.split(",")] if args else ["10", "0"]
            x.open("numberQualifiers")
            x.leaf("precision", parts[0])
            if len(parts) > 1 and parts[1] not in ("", "0"):
                x.leaf("scale", parts[1])
            if "+" in parts[2:]:
                x.leaf("nonNegative", True)
            x.close("numberQualifiers")
        elif kind == "Date":
            x.open("dateQualifiers")
            x.leaf("dateFractions", args or "DateTime")
            x.close("dateQualifiers")
    x.close(tag)


class Col:
    """Column of a value table or value tree attribute."""

    def __init__(self, name: str, type: str | Sequence[str] | None = "String", title: str | None = None) -> None:
        self.name = name
        self.type = type
        self.title = title

    def write(self, x: Xml, ident: int) -> None:
        x.open("columns")
        x.leaf("name", self.name)
        x.mls("title", self.title)
        x.leaf("id", ident)
        write_type(x, "valueType", self.type)
        x.common("view")
        x.common("edit")
        x.close("columns")


class Attr:
    """Form attribute. dynamic_list: dict with query, main_table and optional flags for a DynamicList."""

    def __init__(self, name: str, type: str | Sequence[str] | None = "String", title: str | None = None,
                 columns: Iterable[Col] = (), main: bool = False, saved: bool = False,
                 dynamic_list: dict | None = None) -> None:
        self.name = name
        self.type = type
        self.title = title
        self.columns = list(columns)
        self.main = main
        self.saved = saved
        self.dynamic_list = dynamic_list

    def write(self, x: Xml, ident: int) -> None:
        x.open("attributes")
        x.leaf("name", self.name)
        x.mls("title", self.title)
        x.leaf("id", ident)
        write_type(x, "valueType", self.type)
        x.common("view")
        x.common("edit")
        x.leaf("main", self.main)
        x.leaf("savedData", self.saved)
        if self.dynamic_list is not None:
            spec = self.dynamic_list
            x.open("extInfo", "form:DynamicListExtInfo")
            if spec.get("query"):
                x.leaf("queryText", spec["query"])
            x.leaf("mainTable", spec.get("main_table"))
            x.leaf("dynamicDataRead", spec.get("dynamic_read", True))
            x.leaf("autoFillAvailableFields", True)
            x.leaf("customQuery", bool(spec.get("query")))
            x.leaf("autoSaveUserSettings", True)
            x.leaf("getInvisibleFieldPresentations", True)
            x.close("extInfo")
        for number, column in enumerate(self.columns, start=1):
            column.write(x, number)
        x.close("attributes")


class Param:
    """Form parameter."""

    def __init__(self, name: str, type: str | Sequence[str] | None = None, key: bool = False) -> None:
        self.name = name
        self.type = type
        self.key = key

    def write(self, x: Xml) -> None:
        x.open("parameters")
        x.leaf("name", self.name)
        write_type(x, "valueType", self.type)
        x.leaf("keyParameter", self.key)
        x.close("parameters")


class Command:
    """Form command; the handler defaults to the command name."""

    def __init__(self, name: str, title: str, tooltip: str | None = None, handler: str | None = None,
                 picture: str | None = None, representation: str | None = None) -> None:
        self.name = name
        self.title = title
        self.tooltip = tooltip if tooltip is not None else title
        self.handler = handler or name
        self.picture = picture
        self.representation = representation

    def write(self, x: Xml, ident: int) -> None:
        x.open("formCommands")
        x.leaf("name", self.name)
        x.mls("title", self.title)
        x.leaf("id", ident)
        x.mls("toolTip", self.tooltip)
        x.common("use")
        if self.picture:
            x.open("picture", "core:PictureRef")
            x.leaf("picture", self.picture)
            x.close("picture")
        x.open("action", "form:FormCommandHandlerContainer")
        x.open("handler")
        x.leaf("name", self.handler)
        x.close("handler")
        x.close("action")
        x.leaf("representation", self.representation)
        x.leaf("currentRowUse", "DontUse")
        x.close("formCommands")


# --- Items --------------------------------------------------------------------------------------------

def _tooltip(x: Xml, ids: Ids, name: str) -> None:
    x.open("extendedTooltip")
    x.leaf("name", name + "РасширеннаяПодсказка")
    x.leaf("id", ids())
    x.leaf("type", "Label")
    x.leaf("autoMaxWidth", True)
    x.leaf("autoMaxHeight", True)
    x.open("extInfo", "form:LabelDecorationExtInfo")
    x.leaf("horizontalAlign", "Left")
    x.close("extInfo")
    x.close("extendedTooltip")


def _context_menu(x: Xml, ids: Ids, name: str) -> None:
    x.open("contextMenu")
    x.leaf("name", name + "КонтекстноеМеню")
    x.leaf("id", ids())
    x.leaf("autoFill", True)
    x.close("contextMenu")


def _visibility(x: Xml, item: "Item") -> None:
    x.leaf("visible", item.visible)
    x.leaf("enabled", item.enabled)
    x.common("userVisible")


class Item:
    def __init__(self, name: str, title: str | None = None, tooltip: str | None = None, visible: bool = True,
                 enabled: bool = True) -> None:
        self.name = name
        self.title = title
        self.tooltip = tooltip
        self.visible = visible
        self.enabled = enabled

    def children(self) -> list["Item"]:
        return []

    def handlers(self) -> list[str]:
        return []

    def write(self, x: Xml, ids: Ids) -> None:  # pragma: no cover - abstract
        raise NotImplementedError


class Field(Item):
    """Form field. type: InputField, LabelField, CheckBoxField, RadioButtonField, TextDocumentField.

    events: {"OnChange": "...", "StartChoice": "...", "Click": "..."}; OnChange is written on the field,
    other events go to the field extension. choice_list: [(value, presentation)], value - str, int or
    "Enum.X.EnumValue.Y" (reference)."""

    EXT = {
        "InputField": "form:InputFieldExtInfo",
        "LabelField": "form:LabelFieldExtInfo",
        "CheckBoxField": "form:CheckBoxFieldExtInfo",
        "RadioButtonField": "form:RadioButtonsFieldExtInfo",
        "TextDocumentField": "form:TextDocFieldExtInfo",
    }

    def __init__(self, name: str, path: str, type: str = "InputField", title: str | None = None,
                 tooltip: str | None = None, visible: bool = True, enabled: bool = True,
                 title_location: str | None = None, tooltip_representation: str | None = None,
                 events: dict[str, str] | None = None, read_only: bool = False, default_item: bool = False,
                 horizontal_align: str | None = None, width: int | None = None, max_width: int | None = None,
                 height: int | None = None, hstretch: bool | None = None, vstretch: bool | None = None,
                 multiline: bool = False, password: bool = False, wrap: bool = True,
                 choice_button: bool | None = None, clear_button: bool | None = None, open_button: bool | None = None,
                 list_choice: bool = False, choice_list: Sequence[tuple[object, str]] = (),
                 input_hint: str | None = None, hyperlink: bool = False, format: str | None = None,
                 columns_count: int | None = None) -> None:
        super().__init__(name, title, tooltip, visible, enabled)
        if type not in self.EXT:
            raise ValueError(f"{name}: unknown field type {type}")
        self.path = path
        self.type = type
        self.title_location = title_location
        self.tooltip_representation = tooltip_representation
        self.events = dict(events or {})
        self.read_only = read_only
        self.default_item = default_item
        self.horizontal_align = horizontal_align
        self.width = width
        self.max_width = max_width
        self.height = height
        self.hstretch = hstretch
        self.vstretch = vstretch
        self.multiline = multiline
        self.password = password
        self.wrap = wrap
        self.choice_button = choice_button
        self.clear_button = clear_button
        self.open_button = open_button
        self.list_choice = list_choice
        self.choice_list = list(choice_list)
        self.input_hint = input_hint
        self.hyperlink = hyperlink
        self.format = format
        self.columns_count = columns_count

    def handlers(self) -> list[str]:
        return list(self.events.values())

    def _choice_value(self, x: Xml, value: object) -> None:
        if isinstance(value, bool):
            x.open("value", "core:BooleanValue")
        elif isinstance(value, (int, float)):
            x.open("value", "core:NumberValue")
        elif isinstance(value, str) and ".EnumValue." in value:
            x.open("value", "core:ReferenceValue")
        else:
            x.open("value", "core:StringValue")
        x.leaf("value", value if not isinstance(value, bool) else ("true" if value else "false"))
        x.close("value")

    def write(self, x: Xml, ids: Ids) -> None:
        x.open("items", "form:FormField")
        x.leaf("name", self.name)
        x.leaf("id", ids())
        x.mls("title", self.title)
        _visibility(x, self)
        x.data_path("dataPath", self.path)
        x.leaf("defaultItem", self.default_item)
        x.leaf("titleLocation", self.title_location)
        x.handlers({e: n for e, n in self.events.items() if e in FIELD_EVENTS})
        x.mls("toolTip", self.tooltip)
        x.leaf("toolTipRepresentation", self.tooltip_representation)
        _tooltip(x, ids, self.name)
        _context_menu(x, ids, self.name)
        x.leaf("type", self.type)
        x.leaf("readOnly", self.read_only)
        x.leaf("horizontalAlign", self.horizontal_align)
        x.leaf("editMode", "Enter")
        x.leaf("showInHeader", True)
        x.leaf("headerHorizontalAlign", "Left")
        x.leaf("showInFooter", True)
        ext_events = {e: n for e, n in self.events.items() if e not in FIELD_EVENTS}
        ext = self.EXT[self.type]
        if self.type == "CheckBoxField" and not ext_events:
            x.empty("extInfo", ext)
            x.close("items")
            return
        x.open("extInfo", ext)
        x.handlers(ext_events)
        if self.type == "RadioButtonField":
            x.leaf("columnsCount", self.columns_count)
            self._choice_list(x)
            x.close("extInfo")
            x.close("items")
            return
        x.leaf("width", self.width)
        x.leaf("autoMaxWidth", self.max_width is None)
        x.leaf("maxWidth", self.max_width)
        x.leaf("height", self.height)
        x.leaf("autoMaxHeight", True)
        x.leaf("horizontalStretch", self.hstretch)
        x.leaf("verticalStretch", self.vstretch)
        if self.type == "InputField":
            x.leaf("wrap", self.wrap)
            x.leaf("passwordMode", self.password)
            x.leaf("multiLine", self.multiline)
            x.leaf("choiceButton", self.choice_button)
            x.leaf("clearButton", self.clear_button)
            x.leaf("openButton", self.open_button)
            x.leaf("listChoiceMode", self.list_choice)
            x.leaf("chooseType", True)
            x.leaf("typeDomainEnabled", True)
            x.leaf("textEdit", True)
            self._choice_list(x)
            x.mls("inputHint", self.input_hint)
        elif self.type == "LabelField":
            x.leaf("hyperlink", self.hyperlink)
            x.mls("format", self.format)
        x.close("extInfo")
        x.close("items")

    def _choice_list(self, x: Xml) -> None:
        for value, presentation in self.choice_list:
            x.open("choiceList")
            x.mls("presentation", presentation)
            self._choice_value(x, value)
            x.close("choiceList")


class Label(Item):
    """Label decoration; the text is the title. events: {"Click": "..."} (with hyperlink=True).
    color: style color ("SpecialTextColor"); bold: bold normal text font."""

    def __init__(self, name: str, title: str = "", tooltip: str | None = None, visible: bool = True,
                 hyperlink: bool = False, events: dict[str, str] | None = None, width: int | None = None,
                 max_width: int | None = None, height: int | None = None, hstretch: bool | None = None,
                 vstretch: bool | None = None, align: str = "Left", color: str | None = None,
                 bold: bool = False) -> None:
        super().__init__(name, title, tooltip, visible)
        self.hyperlink = hyperlink
        self.events = dict(events or {})
        self.width = width
        self.max_width = max_width
        self.height = height
        self.hstretch = hstretch
        self.vstretch = vstretch
        self.align = align
        self.color = color
        self.bold = bold

    def handlers(self) -> list[str]:
        return list(self.events.values())

    def write(self, x: Xml, ids: Ids) -> None:
        x.open("items", "form:Decoration")
        x.leaf("name", self.name)
        x.leaf("id", ids())
        x.mls("title", self.title)
        _visibility(x, self)
        x.mls("toolTip", self.tooltip)
        _tooltip(x, ids, self.name)
        _context_menu(x, ids, self.name)
        x.leaf("type", "Label")
        x.leaf("width", self.width)
        x.leaf("autoMaxWidth", self.max_width is None and not self.hstretch)
        x.leaf("maxWidth", self.max_width)
        x.leaf("height", self.height)
        x.leaf("autoMaxHeight", True)
        x.leaf("horizontalStretch", self.hstretch)
        x.leaf("verticalStretch", self.vstretch)
        if self.color:
            x.open("textColor", "core:ColorRef")
            x.leaf("color", "Style." + self.color)
            x.close("textColor")
        if self.bold:
            x.open("font", "core:FontRef")
            x.leaf("font", "Style.NormalTextFont")
            x.leaf("bold", True)
            x.leaf("italic", "false")
            x.leaf("underline", "false")
            x.leaf("strikeout", "false")
            x.close("font")
        x.open("extInfo", "form:LabelDecorationExtInfo")
        x.handlers(self.events)
        x.leaf("hyperlink", self.hyperlink)
        x.leaf("horizontalAlign", self.align)
        x.close("extInfo")
        x.close("items")


class Button(Item):
    """Button. command: form command name, or a full name ("Form.StandardCommand.Close",
    "CommonCommand.X", "Form.Item.Table.StandardCommand.Add"). type: UsualButton or Hyperlink in the
    form body; buttons in command bars have no type."""

    def __init__(self, name: str, command: str, title: str | None = None, tooltip: str | None = None,
                 visible: bool = True, enabled: bool = True, type: str = "UsualButton", default: bool = False,
                 representation: str = "Auto", picture: str | None = None) -> None:
        super().__init__(name, title, tooltip, visible, enabled)
        self.command = command if "." in command else "Form.Command." + command
        self.type: str | None = type
        self.default = default
        self.representation = representation
        self.picture = picture

    def write(self, x: Xml, ids: Ids) -> None:
        x.open("items", "form:Button")
        x.leaf("name", self.name)
        x.leaf("id", ids())
        x.mls("title", self.title)
        _visibility(x, self)
        x.mls("toolTip", self.tooltip)
        _tooltip(x, ids, self.name)
        x.leaf("type", self.type)
        x.leaf("commandName", self.command)
        x.leaf("representation", self.representation)
        x.leaf("defaultButton", self.default)
        x.leaf("autoMaxWidth", True)
        x.leaf("autoMaxHeight", True)
        x.leaf("placementArea", "UserCmds")
        if self.picture:
            x.open("picture", "core:PictureRef")
            x.leaf("picture", self.picture)
            x.close("picture")
        x.leaf("representationInContextMenu", "Auto")
        x.close("items")


class _Container(Item):
    def __init__(self, name: str, items: Iterable[Item], title: str | None = None, tooltip: str | None = None,
                 visible: bool = True, enabled: bool = True) -> None:
        super().__init__(name, title, tooltip, visible, enabled)
        self.items = list(items)

    def children(self) -> list[Item]:
        return self.items

    def _head(self, x: Xml, ids: Ids) -> None:
        x.open("items", "form:FormGroup")
        x.leaf("name", self.name)
        x.leaf("id", ids())
        for item in self.items:
            item.write(x, ids)
        _visibility(x, self)
        x.mls("title", self.title)
        x.mls("toolTip", self.tooltip)


class Group(_Container):
    """Usual group. group: Vertical, Horizontal, HorizontalIfPossible, AlwaysHorizontal.
    representation: None, NormalSeparation, WeakSeparation, StrongSeparation."""

    def __init__(self, name: str, *items: Item, title: str | None = None, tooltip: str | None = None,
                 visible: bool = True, enabled: bool = True, group: str = "Vertical",
                 representation: str | None = None, show_title: bool = False, behavior: str = "Usual",
                 collapsed: bool = False, united: bool = True, hstretch: bool | None = None,
                 vstretch: bool | None = None) -> None:
        super().__init__(name, items, title, tooltip, visible, enabled)
        self.group = group
        self.representation = representation
        self.show_title = show_title
        self.behavior = behavior
        self.collapsed = collapsed
        self.united = united
        self.hstretch = hstretch
        self.vstretch = vstretch

    def write(self, x: Xml, ids: Ids) -> None:
        self._head(x, ids)
        x.leaf("horizontalStretch", self.hstretch)
        x.leaf("verticalStretch", self.vstretch)
        _tooltip(x, ids, self.name)
        x.leaf("type", "UsualGroup")
        x.open("extInfo", "form:UsualGroupExtInfo")
        x.leaf("group", self.group)
        x.leaf("behavior", self.behavior)
        x.leaf("collapsed", self.collapsed)
        x.leaf("representation", self.representation)
        x.leaf("showLeftMargin", True)
        x.leaf("united", self.united)
        x.leaf("showTitle", self.show_title)
        x.leaf("throughAlign", "Auto")
        x.leaf("currentRowUse", "Auto")
        x.close("extInfo")
        x.close("items")


class Page(_Container):
    def __init__(self, name: str, title: str, *items: Item, visible: bool = True, group: str = "Vertical") -> None:
        super().__init__(name, items, title, None, visible)
        self.group = group

    def write(self, x: Xml, ids: Ids) -> None:
        self._head(x, ids)
        _tooltip(x, ids, self.name)
        x.leaf("type", "Page")
        x.open("extInfo", "form:PageGroupExtInfo")
        x.leaf("group", self.group)
        x.leaf("showTitle", True)
        x.close("extInfo")
        x.close("items")


class Pages(_Container):
    """Pages; representation: TabsOnTop, TabsOnBottom, None, ..."""

    def __init__(self, name: str, *pages: Page, title: str | None = None, representation: str | None = None,
                 events: dict[str, str] | None = None) -> None:
        super().__init__(name, pages, title)
        self.representation = representation
        self.events = dict(events or {})

    def handlers(self) -> list[str]:
        return list(self.events.values())

    def write(self, x: Xml, ids: Ids) -> None:
        self._head(x, ids)
        _tooltip(x, ids, self.name)
        x.leaf("type", "Pages")
        x.open("extInfo", "form:PagesGroupExtInfo")
        x.handlers(self.events)
        x.leaf("pagesRepresentation", self.representation)
        x.leaf("currentRowUse", "Auto")
        x.close("extInfo")
        x.close("items")


class CommandBar(_Container):
    """Command bar group in the form body; its buttons have no type."""

    def __init__(self, name: str, *buttons: Button, title: str | None = None, align: str = "Left",
                 visible: bool = True) -> None:
        for button in buttons:
            button.type = None
        super().__init__(name, buttons, title, None, visible)
        self.align = align

    def write(self, x: Xml, ids: Ids) -> None:
        self._head(x, ids)
        _tooltip(x, ids, self.name)
        x.leaf("type", "CommandBar")
        x.open("extInfo", "form:CommandBarExtInfo")
        x.leaf("horizontalAlign", self.align)
        x.close("extInfo")
        x.close("items")


class Table(Item):
    """Table bound to a value table or value tree attribute (path = attribute name).

    columns: Field items with paths "<path>.<column>". buttons: command bar buttons; command_bar=False hides
    the bar. events: Selection, OnActivateRow, BeforeAddRow, BeforeDeleteRow, OnChange, ..."""

    def __init__(self, name: str, path: str, *columns: Field, title: str | None = None, visible: bool = True,
                 enabled: bool = True, title_location: str = "None", read_only: bool = False, header: bool = True,
                 buttons: Sequence[Button] = (), command_bar: bool = True, auto_fill: bool = False,
                 events: dict[str, str] | None = None, height_rows: int | None = None,
                 selection: str = "SingleRow", tree: bool = False, initial_tree_view: str | None = None,
                 lines: bool = True, alternation: bool = False, hstretch: bool = True, vstretch: bool = True,
                 change_row_set: bool = False, change_row_order: bool = False,
                 excluded_commands: Sequence[str] = (), auto_insert: bool = False) -> None:
        super().__init__(name, title, None, visible, enabled)
        self.path = path
        self.columns = list(columns)
        self.title_location = title_location
        self.read_only = read_only
        self.header = header
        self.buttons = list(buttons)
        for button in self.buttons:
            button.type = None
        self.command_bar = command_bar
        self.auto_fill = auto_fill
        self.events = dict(events or {})
        self.height_rows = height_rows
        self.selection = selection
        self.tree = tree
        self.initial_tree_view = initial_tree_view
        self.lines = lines
        self.alternation = alternation
        self.hstretch = hstretch
        self.vstretch = vstretch
        self.change_row_set = change_row_set
        self.change_row_order = change_row_order
        self.excluded_commands = list(excluded_commands)
        self.auto_insert = auto_insert

    def children(self) -> list[Item]:
        return [*self.columns, *self.buttons]

    def handlers(self) -> list[str]:
        return list(self.events.values())

    def _addition(self, x: Xml, ids: Ids, tag: str, suffix: str, kind: str | None, ext: str) -> None:
        name = self.name + suffix
        x.open(tag)
        x.leaf("name", name)
        x.leaf("id", ids())
        _tooltip(x, ids, name)
        _context_menu(x, ids, name)
        x.leaf("type", kind)
        x.leaf("source", self.name)
        x.open("extInfo", ext)
        x.leaf("autoMaxWidth", True)
        x.close("extInfo")
        x.close(tag)

    def write(self, x: Xml, ids: Ids) -> None:
        x.open("items", "form:Table")
        x.leaf("name", self.name)
        x.leaf("id", ids())
        x.mls("title", self.title)
        _visibility(x, self)
        x.data_path("dataPath", self.path)
        x.leaf("titleLocation", self.title_location)
        for command in self.excluded_commands:
            x.leaf("excludedCommands", command)
        for column in self.columns:
            column.write(x, ids)
        x.leaf("commandBarLocation", None if self.command_bar else "None")
        x.open("autoCommandBar")
        x.leaf("name", self.name + "КоманднаяПанель")
        x.leaf("id", ids())
        for button in self.buttons:
            button.write(x, ids)
        x.leaf("horizontalAlign", "Left")
        x.leaf("autoFill", self.auto_fill)
        x.close("autoCommandBar")
        x.handlers(self.events)
        self._addition(x, ids, "searchStringAddition", "СтрокаПоиска", None, "form:SearchStringAdditionExtInfo")
        self._addition(x, ids, "viewStatusAddition", "СостояниеПросмотра", "ViewStatusAddition",
                       "form:ViewStatusAdditionExtInfo")
        self._addition(x, ids, "searchControlAddition", "УправлениеПоиском", "SearchControlAddition",
                       "form:SearchControlAdditionExtInfo")
        _tooltip(x, ids, self.name)
        _context_menu(x, ids, self.name)
        x.leaf("representation", "Tree" if self.tree else None)
        x.leaf("readOnly", self.read_only)
        x.leaf("changeRowSet", self.change_row_set)
        x.leaf("changeRowOrder", self.change_row_order)
        x.leaf("autoMaxWidth", True)
        x.leaf("autoMaxHeight", True)
        x.leaf("heightInTableRows", self.height_rows)
        x.leaf("autoMaxRowsCount", True)
        x.leaf("selectionMode", self.selection)
        x.leaf("header", self.header)
        x.leaf("headerHeight", 1)
        x.leaf("footerHeight", 1)
        x.leaf("horizontalScrollBar", "AutoUse")
        x.leaf("verticalScrollBar", "AutoUse")
        x.leaf("horizontalLines", self.lines)
        x.leaf("verticalLines", self.lines)
        x.leaf("useAlternationRowColor", self.alternation)
        x.leaf("autoInsertNewRow", self.auto_insert)
        x.leaf("searchOnInput", "Auto")
        x.leaf("initialListView", "Auto")
        x.leaf("initialTreeView", self.initial_tree_view)
        x.leaf("horizontalStretch", self.hstretch)
        x.leaf("verticalStretch", self.vstretch)
        x.leaf("searchStringLocation", "None")
        x.leaf("viewStatusLocation", "None")
        x.leaf("searchControlLocation", "None")
        x.empty("rowFilter", "core:UndefinedValue")
        x.close("items")


# --- Form ---------------------------------------------------------------------------------------------

class Form:
    """Managed form. kind: common (common form), object (catalog item form: CatalogFormExtInfo)."""

    def __init__(self, items: Iterable[Item], attributes: Iterable[Attr] = (), commands: Iterable[Command] = (),
                 parameters: Iterable[Param] = (), title: str | None = None, kind: str = "common",
                 events: dict[str, str] | None = None, buttons: Sequence[Button] = (), auto_fill: bool = True,
                 command_bar_location: str | None = None, window_mode: str | None = None,
                 excluded_commands: Sequence[str] = (), auto_title: bool | None = None,
                 save_window_settings: bool = True) -> None:
        self.items = list(items)
        self.attributes = list(attributes)
        self.commands = list(commands)
        self.parameters = list(parameters)
        self.title = title
        self.kind = kind
        self.events = dict(events or {})
        self.buttons = list(buttons)
        for button in self.buttons:
            button.type = None
        self.auto_fill = auto_fill
        self.command_bar_location = command_bar_location
        self.window_mode = window_mode
        self.excluded_commands = list(excluded_commands)
        self.auto_title = auto_title if auto_title is not None else title is None
        self.save_window_settings = save_window_settings

    def all_items(self) -> list[Item]:
        result: list[Item] = []

        def walk(items: Iterable[Item]) -> None:
            for item in items:
                result.append(item)
                walk(item.children())

        walk([*self.items, *self.buttons])
        return result

    def handlers(self) -> list[str]:
        """Names of all event and command handlers: they must exist in the form module."""
        names = list(self.events.values())
        for item in self.all_items():
            names.extend(item.handlers())
        names.extend(command.handler for command in self.commands)
        return names

    def validate(self) -> None:
        names = [item.name for item in self.all_items()]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(f"duplicate item names: {', '.join(duplicates)}")
        attributes = {attr.name: attr for attr in self.attributes}
        for item in self.all_items():
            path = getattr(item, "path", None)
            if path is None:
                continue
            head, _, rest = path.partition(".")
            attr = attributes.get(head)
            if attr is None:
                raise ValueError(f"{item.name}: unknown attribute {head}")
            if rest and attr.columns and rest.split(".")[0] not in {c.name for c in attr.columns}:
                raise ValueError(f"{item.name}: attribute {head} has no column {rest}")
        commands = {command.name for command in self.commands}
        for item in self.all_items():
            command = getattr(item, "command", "")
            if command.startswith("Form.Command.") and command[len("Form.Command."):] not in commands:
                raise ValueError(f"{item.name}: unknown command {command}")

    def render(self) -> str:
        self.validate()
        x = Xml()
        x.lines.append('<?xml version="1.0" encoding="UTF-8"?>')
        x.lines.append('<form:Form xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
                       'xmlns:core="http://g5.1c.ru/v8/dt/mcore" xmlns:form="http://g5.1c.ru/v8/dt/form">')
        x.level = 1
        ids = Ids()
        x.mls("title", self.title)
        for item in self.items:
            item.write(x, ids)
        x.leaf("commandBarLocation", self.command_bar_location)
        x.open("autoCommandBar")
        x.leaf("name", "ФормаКоманднаяПанель")
        x.leaf("id", -1)
        for button in self.buttons:
            button.write(x, ids)
        x.leaf("horizontalAlign", "Left")
        x.leaf("autoFill", self.auto_fill)
        x.close("autoCommandBar")
        x.handlers({e: n for e, n in self.events.items() if e not in OBJECT_FORM_EVENTS})
        for command in self.excluded_commands:
            x.leaf("excludedCommands", command)
        x.leaf("windowOpeningMode", self.window_mode)
        x.leaf("saveWindowSettings", self.save_window_settings)
        x.leaf("autoTitle", self.auto_title)
        x.leaf("autoUrl", True)
        x.leaf("group", "Vertical")
        x.leaf("autoFillCheck", True)
        x.leaf("allowFormCustomize", True)
        x.leaf("enabled", True)
        x.leaf("showTitle", True)
        x.leaf("showCloseButton", True)
        for number, attr in enumerate(self.attributes, start=1):
            attr.write(x, number)
        for number, command in enumerate(self.commands, start=1):
            command.write(x, number)
        for parameter in self.parameters:
            parameter.write(x)
        x.open("commandInterface")
        x.empty("navigationPanel")
        x.empty("commandBar")
        x.close("commandInterface")
        object_events = {e: n for e, n in self.events.items() if e in OBJECT_FORM_EVENTS}
        if self.kind == "object":
            if object_events:
                x.open("extInfo", "form:CatalogFormExtInfo")
                x.handlers(object_events)
                x.close("extInfo")
            else:
                x.empty("extInfo", "form:CatalogFormExtInfo")
        elif object_events:
            raise ValueError(f"object form events in a {self.kind} form: {', '.join(object_events)}")
        x.level = 0
        x.lines.append("</form:Form>")
        return x.text()
