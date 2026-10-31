"""Пісочниця (ТЗ п. 9.2): клієнт -> інструмент -> аргументи -> точна відповідь для моделі й застосовані правила."""
from formxml import Attr, Button, Col, Command, Field, Form, Group, Page, Pages, Param, Table

PATH = "CommonForms/mcp1c_Песочница/Form.form"

FORM = Form(
    title="Пісочниця MCP",
    events={"OnCreateAtServer": "ПриСозданииНаСервере"},
    auto_fill=False,
    buttons=[
        Button("ФормаВыполнитьВызов", "ВыполнитьВызов", default=True),
        Button("ФормаЗакрыть", "Form.StandardCommand.Close"),
    ],
    items=[
        Group(
            "ГруппаКлиент",
            Field("Клиент", "Клиент", title="Клієнт", hstretch=True, events={"OnChange": "КлиентПриИзменении"}),
            Field("ОбластьТокена", "ОбластьТокена", title="Область токена", hstretch=True,
                  input_hint="порожньо - усі можливості профілю; інструменти через кому",
                  events={"OnChange": "ОбластьТокенаПриИзменении"}),
            group="Horizontal",
        ),
        Group(
            "ГруппаВызов",
            Table(
                "Вызовы", "Вызовы",
                Field("ВызовыПредставление", "Вызовы.Представление", title="Що викликати"),
                read_only=True, command_bar=False, height_rows=10,
                events={"OnActivateRow": "ВызовыПриАктивизацииСтроки"},
            ),
            Field("Аргументы", "Аргументы", title="Аргументи (JSON) або URI ресурсу", title_location="Top",
                  multiline=True, height=10, hstretch=True, vstretch=True),
            group="Horizontal",
        ),
        Pages(
            "Результат",
            Page(
                "СтраницаОтвет", "Відповідь для моделі",
                Field("Ответ", "Ответ", title_location="None", read_only=True, multiline=True, height=14,
                      hstretch=True, vstretch=True),
            ),
            Page(
                "СтраницаПравила", "Правила і попередження",
                Field("Правила", "Правила", title_location="None", read_only=True, multiline=True, height=14,
                      hstretch=True, vstretch=True),
            ),
            representation="TabsOnTop",
        ),
    ],
    attributes=[
        Attr("Клиент", "CatalogRef.mcp1c_КлиентыДоступа", title="Клієнт"),
        Attr("ОбластьТокена", "String(1000)", title="Область токена"),
        Attr("Вызовы", "ValueTable", columns=[
            Col("Представление", "String(300)"),
            Col("Метод", "String(50)"),
            Col("Имя", "String(100)"),
            Col("Пример", "String"),
        ]),
        Attr("Аргументы", "String", title="Аргументи"),
        Attr("Ответ", "String"),
        Attr("Правила", "String"),
    ],
    commands=[
        Command("ВыполнитьВызов", "Виконати", "Виконати виклик від імені клієнта: ліміти не витрачаються, у журнал "
                "викликів не пишеться"),
    ],
    parameters=[
        Param("Клиент", "CatalogRef.mcp1c_КлиентыДоступа"),
    ],
)
