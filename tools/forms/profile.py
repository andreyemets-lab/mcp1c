"""Профіль доступу (ТЗ п. 7.3-7.5, 9.2): дерево метаданих із доступом, режимом і масками, правила й шаблони,
рядкові обмеження з параметрами, інструменти, ліміти."""
from formxml import Attr, Button, Col, Command, Field, Form, Group, Label, Page, Pages, Table

PATH = "Catalogs/mcp1c_ПрофилиДоступа/Forms/ФормаЭлемента/Form.form"

TREE = "Дерево"
RULES_HINT = ("Правила для шаблонів: «*» - будь-які символи, наприклад «Справочник.*» або «*». Правило з точним іменем "
              "об'єкта важливіше за шаблон, довший шаблон - за коротший. Дерево на вкладці «Доступ до даних» показує, "
              "як діють усі правила разом.")
RESTRICTIONS_HINT = ("Обмеження додаються до кожного запиту до об'єкта через І. Значення - JSON, як в аргументах "
                     "інструментів: {\"type\": \"Справочник.Организации\", \"ref\": \"<uuid>\"} або масив таких "
                     "значень; або параметр профілю, значення якого задаються в кожному клієнті.")
LIMITS_HINT = "0 - значення за замовчуванням; ліміти клієнта можуть лише зменшити ліміти профілю."


def obj(name: str, **kwargs) -> Field:
    return Field(name, "Объект." + name, **kwargs)


def col(table: str, name: str, title: str | None = None, type: str = "InputField", path: str = "",
        **kwargs) -> Field:
    return Field(table + name, f"{path or table}.{name}", type=type, title=title, **kwargs)


def ts(table: str, name: str, title: str | None = None, type: str = "InputField", **kwargs) -> Field:
    return col(table, name, title, type, path="Объект." + table, **kwargs)


def limit(name: str, title: str) -> Group:
    """Ліміт профілю і підказка праворуч: типове й граничне значення (заповнює модуль форми)."""
    return Group(
        "Группа" + name,
        obj(name, title=title, width=10, spin_button=True, min_value=0),
        Label("Подсказка" + name, ""),
        group="Horizontal",
    )


FORM = Form(
    kind="object",
    events={
        "OnCreateAtServer": "ПриСозданииНаСервере",
        "BeforeWriteAtServer": "ПередЗаписьюНаСервере",
        "AfterWriteAtServer": "ПослеЗаписиНаСервере",
        "NotificationProcessing": "ОбработкаОповещения",
    },
    items=[
        Group(
            "ГруппаШапка",
            Field("Наименование", "Объект.Description", hstretch=True),
            Field("Версия", "Объект.Версия", type="LabelField", title="Версія"),
            group="Horizontal",
        ),
        obj("Описание", multiline=True, height=2, hstretch=True, vstretch=False),
        Pages(
            "Страницы",
            Page(
                "СтраницаДоступ", "Доступ до даних",
                Group(
                    "ГруппаОтбор",
                    Field("СтрокаПоиска", "СтрокаПоиска", title="Пошук", width=30, clear_button=True,
                          input_hint="ім'я або синонім об'єкта", events={"OnChange": "СтрокаПоискаПриИзменении"}),
                    Field("ТолькоДоступные", "ТолькоДоступные", type="CheckBoxField", title="Лише відкриті профілем",
                          title_location="Right", events={"OnChange": "ТолькоДоступныеПриИзменении"}),
                    group="Horizontal",
                ),
                Table(
                    TREE, TREE,
                    col(TREE, "Представление", "Об'єкт або поле", read_only=True, width=28),
                    col(TREE, "Имя", "Ім'я", read_only=True, width=28),
                    col(TREE, "Доступ", "Доступ", type="CheckBoxField",
                        events={"OnChange": "ДеревоДоступПриИзменении"}),
                    col(TREE, "Режим", "Режим", width=14, clear_button=True, events={"OnChange": "ДеревоРежимПриИзменении"}),
                    col(TREE, "ВидМаски", "Маска", width=12, clear_button=True,
                        events={"OnChange": "ДеревоВидМаскиПриИзменении"}),
                    col(TREE, "ПараметрМаски", "Параметр маски", width=8,
                        events={"OnChange": "ДеревоПараметрМаскиПриИзменении"}),
                    col(TREE, "Пояснение", "Як діє", read_only=True, width=40),
                    col(TREE, "Чувствительное", "Чутливе поле", read_only=True, width=16),
                    tree=True, change_row_set=False, height_rows=14,
                    events={"BeforeExpand": "ДеревоПередРазворачиванием"},
                    buttons=[
                        Button("ДеревоЗамаскироватьРекомендуемой", "ЗамаскироватьРекомендуемой"),
                        Button("ДеревоОбновить", "ОбновитьДерево"),
                    ],
                ),
            ),
            Page(
                "СтраницаПравила", "Правила і шаблони",
                Label("ДекорацияПравила", RULES_HINT, hstretch=True),
                Table(
                    "Объекты", "Объект.Объекты",
                    ts("Объекты", "Объект", "Об'єкт або шаблон", width=30),
                    ts("Объекты", "Режим", "Режим", width=14),
                    ts("Объекты", "ПолитикаПолей", "Поля", width=18),
                    ts("Объекты", "ОбязательныйФильтрПериода", "Фільтр періоду", type="CheckBoxField"),
                    ts("Объекты", "МинимальныйРазмерГруппы", "Мін. група (агрегати)", width=6),
                    title="Об'єкти", title_location="Top", change_row_set=True, change_row_order=True,
                    auto_fill=True, height_rows=6,
                ),
                Table(
                    "Поля", "Объект.Поля",
                    ts("Поля", "Объект", "Об'єкт або шаблон", width=30),
                    ts("Поля", "Поле", "Поле (ТабличнаЧастина.Поле)", width=24),
                    ts("Поля", "Действие", "Дія", width=12),
                    ts("Поля", "ВидМаски", "Маска", width=12),
                    ts("Поля", "ПараметрМаски", "Параметр маски", width=8),
                    title="Поля", title_location="Top", change_row_set=True, change_row_order=True,
                    auto_fill=True, height_rows=6,
                ),
            ),
            Page(
                "СтраницаОграничения", "Обмеження рядків",
                Label("ДекорацияОграничения", RESTRICTIONS_HINT, hstretch=True),
                Table(
                    "ОграниченияСтрок", "Объект.ОграниченияСтрок",
                    ts("ОграниченияСтрок", "Объект", "Об'єкт", width=28, choice_button=True,
                       events={"StartChoice": "ОграниченияСтрокОбъектНачалоВыбора"}),
                    ts("ОграниченияСтрок", "Поле", "Поле", width=20, choice_button=True,
                       events={"StartChoice": "ОграниченияСтрокПолеНачалоВыбора"}),
                    ts("ОграниченияСтрок", "ВидСравнения", "Умова", width=12),
                    ts("ОграниченияСтрок", "Значение", "Значення (JSON)", width=30),
                    ts("ОграниченияСтрок", "Параметр", "або параметр профілю", width=16, choice_button=True,
                       events={"StartChoice": "ОграниченияСтрокПараметрНачалоВыбора"}),
                    ts("ОграниченияСтрок", "Комментарий", "Опис", width=20),
                    title="Обмеження", title_location="Top", change_row_set=True, change_row_order=True,
                    auto_fill=True, height_rows=6,
                ),
                Table(
                    "Параметры", "Объект.Параметры",
                    ts("Параметры", "Имя", "Ім'я параметра", width=20),
                    ts("Параметры", "ТипЗначения", "Типи значень", width=30,
                       input_hint="наприклад Справочник.Организации"),
                    ts("Параметры", "Описание", "Опис", width=30),
                    title="Параметри профілю (значення - у клієнтах)", title_location="Top", change_row_set=True,
                    change_row_order=True, auto_fill=True, height_rows=4,
                ),
            ),
            Page(
                "СтраницаИнструменты", "Інструменти",
                Field("ВсеВстроенные", "ВсеВстроенные", type="CheckBoxField",
                      title="Усі вбудовані інструменти читання, зокрема нові в наступних версіях розширення",
                      title_location="Right", events={"OnChange": "ВсеВстроенныеПриИзменении"}),
                Table(
                    "ВстроенныеИнструменты", "ВстроенныеИнструменты",
                    col("ВстроенныеИнструменты", "Пометка", " ", type="CheckBoxField"),
                    col("ВстроенныеИнструменты", "Имя", "Інструмент", read_only=True, width=20),
                    col("ВстроенныеИнструменты", "Описание", "Опис", read_only=True, width=50),
                    command_bar=False, change_row_set=False, height_rows=9,
                ),
                Label("ДекорацияПользовательские", "Користувацькі інструменти й промпти, призначені профілю "
                      "(призначення - у формі інструмента чи промпту):", hstretch=True),
                Table(
                    "ПользовательскиеИнструменты", "ПользовательскиеИнструменты",
                    col("ПользовательскиеИнструменты", "Имя", "Ім'я", width=24),
                    col("ПользовательскиеИнструменты", "Заголовок", "Назва", width=30),
                    col("ПользовательскиеИнструменты", "Вид", "Вид", width=16),
                    read_only=True, command_bar=False, height_rows=4,
                    events={"Selection": "ПользовательскиеИнструментыВыбор"},
                ),
            ),
            Page(
                "СтраницаЛимиты", "Ліміти",
                Label("ДекорацияЛимиты", LIMITS_HINT, hstretch=True),
                limit("ЛимитСтрок", "Рядків за виклик"),
                limit("ВызововВМинуту", "Викликів за хвилину"),
                limit("СтрокВСутки", "Рядків за добу"),
                limit("ГлубинаПериодаДней", "Глибина періоду, днів"),
                limit("РазмерОтветаКБ", "Розмір відповіді, КБ"),
                limit("ГлубинаРазыменования", "Глибина розіменування"),
                obj("РазрешитьПомеченныеНаУдаление", type="CheckBoxField", title_location="Right"),
            ),
            representation="TabsOnTop",
            events={"OnCurrentPageChange": "СтраницыПриСменеСтраницы"},
        ),
    ],
    attributes=[
        Attr("Объект", "CatalogObject.mcp1c_ПрофилиДоступа", main=True, saved=True),
        Attr(TREE, "ValueTree", columns=[
            Col("Представление", "String(300)"),
            Col("Имя", "String(300)"),
            Col("Вид", "Number(1,0)"),
            Col("КодВида", "String(50)"),
            Col("ПолноеИмя", "String(255)"),
            Col("Путь", "String(255)"),
            Col("Типы", "String"),
            Col("Загружено", "Boolean"),
            Col("Доступ", "Boolean"),
            Col("Режим", "EnumRef.mcp1c_РежимыДоступаКОбъектам"),
            Col("ВидМаски", "EnumRef.mcp1c_ВидыМасок"),
            Col("ПараметрМаски", "Number(15,2,+)"),
            Col("Пояснение", "String(500)"),
            Col("Чувствительное", "String(100)"),
            Col("КатегорияЧувствительности", "String(20)"),
            Col("ТолькоПросмотр", "Boolean"),
        ]),
        Attr("СтрокаПоиска", "String(100)", title="Пошук"),
        Attr("ТолькоДоступные", "Boolean", title="Лише відкриті профілем"),
        Attr("ВсеВстроенные", "Boolean", title="Усі вбудовані інструменти", saved=True),
        Attr("ВстроенныеИнструменты", "ValueTable", saved=True, columns=[
            Col("Пометка", "Boolean"),
            Col("Имя", "String(64)"),
            Col("Описание", "String(300)"),
        ]),
        Attr("ПользовательскиеИнструменты", "ValueTable", columns=[
            Col("Ссылка", ["CatalogRef.mcp1c_ПользовательскиеИнструменты", "CatalogRef.mcp1c_Промпты"]),
            Col("Имя", "String(100)"),
            Col("Заголовок", "String(150)"),
            Col("Вид", "String(50)"),
        ]),
    ],
    commands=[
        Command("ЗамаскироватьРекомендуемой", "Замаскувати рекомендованою маскою",
                "Замаскувати вибране чутливе поле маскою, рекомендованою для його категорії"),
        Command("ОбновитьДерево", "Оновити", "Перебудувати дерево за поточними правилами профілю",
                picture="StdPicture.Refresh"),
    ],
)
