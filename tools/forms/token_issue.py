"""Видача токена (ТЗ п. 6.3, 9.2, 9.3): термін, коментар, область; токен і фрагменти підключення один раз."""
from formxml import Attr, Button, Col, Command, Field, Form, Group, Label, Page, Pages, Param, Table

PATH = "CommonForms/mcp1c_ВыпускТокена/Form.form"

SCOPES = [
    ("all", "Усі можливості профілю"),
    ("metadata", "Лише структура бази: get_context, list_objects, describe_object"),
    ("custom", "Вибрані інструменти"),
]

FORM = Form(
    title="Видача токена MCP",
    events={"OnCreateAtServer": "ПриСозданииНаСервере"},
    window_mode="LockOwnerWindow",
    auto_fill=False,
    save_window_settings=False,
    buttons=[
        Button("ФормаВыпустить", "Выпустить", default=True),
        Button("ФормаЗакрыть", "Form.StandardCommand.Close"),
    ],
    items=[
        Pages(
            "Страницы",
            Page(
                "СтраницаПараметры", "Параметри",
                Field("Клиент", "Клиент", type="LabelField", title="Клієнт"),
                Field("Профиль", "Профиль", type="LabelField", title="Профіль"),
                Group(
                    "ГруппаСрок",
                    Field("СрокДействия", "СрокДействия", title="Термін дії, днів", width=5, spin_button=True,
                          min_value=1, events={"OnChange": "СрокДействияПриИзменении"}),
                    Field("ДействуетДо", "ДействуетДо", type="LabelField", title="діятиме до", format="ДЛФ=DT"),
                    group="Horizontal",
                ),
                Field("Комментарий", "Комментарий", title="Коментар", hstretch=True,
                      input_hint="де й ким використовуватиметься токен, наприклад: Claude Code, ноутбук Андрія"),
                Field("ВариантОбласти", "ВариантОбласти", type="RadioButtonField", title="Область токена",
                      title_location="Top", choice_list=SCOPES, columns_count=1,
                      events={"OnChange": "ВариантОбластиПриИзменении"}),
                Table(
                    "Инструменты", "Инструменты",
                    Field("ИнструментыПометка", "Инструменты.Пометка", type="CheckBoxField", title=" "),
                    Field("ИнструментыИмя", "Инструменты.Имя", title="Інструмент", read_only=True),
                    Field("ИнструментыОписание", "Инструменты.Описание", title="Опис", read_only=True),
                    command_bar=False, height_rows=8, change_row_set=False,
                ),
                Label("ДекорацияОбласть", "Область лише звужує профіль клієнта: інструменти, яких профіль не "
                      "дозволяє, токен не відкриє.", hstretch=True),
            ),
            Page(
                "СтраницаРезультат", "Токен",
                Label("ДекорацияОдинРаз", "Токен показується один раз: скопіюйте його зараз. Після закриття вікна "
                      "отримати його знову неможливо - лише видати новий.", hstretch=True, color="SpecialTextColor",
                      bold=True),
                Field("Токен", "Токен", title="Токен", read_only=True, width=80, auto_max_width=False,
                      hstretch=True),
                Field("ДействуетДоТокена", "ДействуетДо", type="LabelField", title="Діє до", format="ДЛФ=DT"),
                Field("Фрагменты", "Фрагменты", title="Фрагменти підключення", title_location="Top", read_only=True,
                      multiline=True, height=14, auto_max_width=False, hstretch=True, vstretch=True),
            ),
            representation="None",
        ),
    ],
    attributes=[
        Attr("Клиент", "CatalogRef.mcp1c_КлиентыДоступа", title="Клієнт"),
        Attr("Профиль", "CatalogRef.mcp1c_ПрофилиДоступа", title="Профіль"),
        Attr("СрокДействия", "Number(3,0,+)", title="Термін дії, днів"),
        Attr("МаксимумДней", "Number(5,0)"),
        Attr("ДействуетДо", "Date"),
        Attr("Комментарий", "String(100)", title="Коментар"),
        Attr("ВариантОбласти", "String(20)", title="Область токена"),
        Attr("Инструменты", "ValueTable", columns=[
            Col("Пометка", "Boolean"),
            Col("Имя", "String(64)"),
            Col("Описание", "String(300)"),
        ]),
        Attr("Токен", "String"),
        Attr("Фрагменты", "String"),
    ],
    commands=[
        Command("Выпустить", "Видати токен", "Видати токен клієнту з вибраними терміном і областю"),
    ],
    parameters=[
        Param("Клиент", "CatalogRef.mcp1c_КлиентыДоступа"),
    ],
)
