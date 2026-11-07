"""Користувацький інструмент (ТЗ п. 5.5, 9.2): запит, схема компонування або метод модуля, параметри з
автозаповненням, профілі, опис для моделі (inputSchema й outputSchema) і тест у пісочниці."""
from formxml import Attr, Button, Command, CommandBar, Field, Form, Group, Label, Page, Pages, Table

PATH = "Catalogs/mcp1c_ПользовательскиеИнструменты/Forms/ФормаЭлемента/Form.form"

METHOD_HINT = ("Експортна функція серверного загального модуля конфігурації чи розширення: Функция Имя(Параметры, "
               "Контекст) Экспорт. Параметры - структура зі значеннями аргументів (ключі - імена параметрів), "
               "Контекст - клієнт, профіль, ліміт рядків. Повертає масив структур або таблицю значень.")
MODEL_HINT = ("Так інструмент бачить модель у tools/list: inputSchema будується з параметрів (параметри, прив'язані "
              "до параметрів профілю, моделі не видно), outputSchema - з колонок запиту. Оновлюється при відкритті, "
              "записі й командою «Оновити».")


def obj(name: str, **kwargs) -> Field:
    return Field(name, "Объект." + name, **kwargs)


def ts(table: str, name: str, title: str | None = None, type: str = "InputField", **kwargs) -> Field:
    return Field(table + name, f"Объект.{table}.{name}", type=type, title=title, **kwargs)


FORM = Form(
    kind="object",
    events={
        "OnCreateAtServer": "ПриСозданииНаСервере",
        "AfterWriteAtServer": "ПослеЗаписиНаСервере",
    },
    buttons=[
        Button("ФормаПроверить", "Проверить"),
        Button("ФормаТест", "Тест"),
    ],
    items=[
        Group(
            "ГруппаШапка",
            Field("Наименование", "Объект.Description", title="Назва", hstretch=True),
            obj("Имя", title="Ім'я для моделі", width=24, input_hint="наприклад customer_debt"),
            group="Horizontal",
        ),
        Group(
            "ГруппаВид",
            obj("Вид", width=22, events={"OnChange": "ВидПриИзменении"}),
            obj("ЛимитСтрок", width=8, input_hint="0 - ліміт профілю"),
            group="Horizontal",
        ),
        obj("Описание", title="Опис для моделі", title_location="Top", multiline=True, height=4, hstretch=True,
            vstretch=False, input_hint="що повертає інструмент, коли його викликати, одиниці й знак значень"),
        Pages(
            "Страницы",
            Page(
                "СтраницаЗапрос", "Запит",
                CommandBar(
                    "ПанельЗапроса",
                    Button("ЗапросКонструкторЗапроса", "КонструкторЗапроса"),
                    Button("ЗапросЗаполнитьПараметры", "ЗаполнитьПараметры"),
                ),
                obj("ТекстЗапроса", title_location="None", multiline=True, height=14, hstretch=True, vstretch=True),
            ),
            Page(
                "СтраницаСхема", "Схема компонування",
                CommandBar("ПанельСхемы", Button("СхемаЗаполнитьПараметры", "ЗаполнитьПараметры")),
                obj("СхемаКомпоновки", title_location="None", multiline=True, height=14, hstretch=True,
                    vstretch=True),
            ),
            Page(
                "СтраницаМетод", "Метод модуля",
                Label("ДекорацияМетод", METHOD_HINT, hstretch=True),
                obj("ИмяМодуля", width=40),
                obj("ИмяМетода", width=40),
            ),
            Page(
                "СтраницаПараметры", "Параметри",
                Table(
                    "Параметры", "Объект.Параметры",
                    ts("Параметры", "Имя", "Аргумент для моделі", width=18),
                    ts("Параметры", "ИмяПараметра", "Параметр запиту", width=18),
                    ts("Параметры", "ТипЗначения", "Типи", width=20),
                    ts("Параметры", "Описание", "Опис для моделі", width=30),
                    ts("Параметры", "Обязательный", "Обов'язковий", type="CheckBoxField"),
                    ts("Параметры", "Список", "Список", type="CheckBoxField"),
                    ts("Параметры", "ЗначениеПоУмолчанию", "За замовчуванням (JSON)", width=14),
                    ts("Параметры", "ДопустимыеЗначения", "Допустимі (JSON-масив)", width=14),
                    ts("Параметры", "ПараметрПрофиля", "Параметр профілю", width=16),
                    change_row_set=True, change_row_order=True, auto_fill=True, height_rows=8,
                ),
            ),
            Page(
                "СтраницаПрофили", "Профілі",
                Table(
                    "Профили", "Объект.Профили",
                    ts("Профили", "Профиль", "Профіль доступу", width=40),
                    change_row_set=True, auto_fill=True, height_rows=6,
                ),
            ),
            Page(
                "СтраницаДляМодели", "Як бачить модель",
                Label("ДекорацияДляМодели", MODEL_HINT, hstretch=True),
                CommandBar("ПанельДляМодели", Button("ДляМоделиОбновить", "ОбновитьОписание")),
                Field("ОписаниеДляМодели", "ОписаниеДляМодели", title_location="None", read_only=True,
                      multiline=True, height=14, hstretch=True, vstretch=True),
            ),
            representation="TabsOnTop",
        ),
    ],
    attributes=[
        Attr("Объект", "CatalogObject.mcp1c_ПользовательскиеИнструменты", main=True, saved=True),
        Attr("ОписаниеДляМодели", "String"),
    ],
    commands=[
        Command("КонструкторЗапроса", "Конструктор запиту", "Відкрити конструктор запиту платформи (товстий клієнт)"),
        Command("ЗаполнитьПараметры", "Параметри з тексту",
                "Додати в «Параметри» параметри &Ім'я із запиту чи схеми, яких там ще немає"),
        Command("Проверить", "Перевірити", "Перевірити ім'я, опис, запит, параметри й профілі, як під час запису"),
        Command("Тест", "Тест у пісочниці",
                "Записати інструмент і відкрити пісочницю: виклик від імені клієнта з профілем інструмента"),
        Command("ОбновитьОписание", "Оновити", "Оновити опис інструмента для моделі за поточними даними форми",
                picture="StdPicture.Refresh"),
    ],
)
