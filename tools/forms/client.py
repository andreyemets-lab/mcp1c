"""Клієнт доступу (ТЗ п. 9.2): «Основне», «Обмеження», «Токени» (видача й відкликання), «OAuth» (код підключення
веб-коннектора і підключення, ТЗ п. 6.4), «Журнал»."""
from formxml import Attr, Button, Col, Command, Field, Form, Group, Label, Page, Pages, Table

PATH = "Catalogs/mcp1c_КлиентыДоступа/Forms/ФормаЭлемента/Form.form"

JOURNAL_QUERY = """ВЫБРАТЬ
	Журнал.Момент КАК Момент,
	Журнал.ИдентификаторЗапроса КАК ИдентификаторЗапроса,
	Журнал.ИдентификаторТокена КАК ИдентификаторТокена,
	Журнал.АдресКлиента КАК АдресКлиента,
	Журнал.ИнформацияКлиента КАК ИнформацияКлиента,
	Журнал.Метод КАК Метод,
	Журнал.Инструмент КАК Инструмент,
	Журнал.Объекты КАК Объекты,
	Журнал.Результат КАК Результат,
	Журнал.КоличествоСтрок КАК КоличествоСтрок,
	Журнал.ДлительностьМс КАК ДлительностьМс,
	Журнал.Причина КАК Причина
ИЗ
	РегистрСведений.mcp1c_ЖурналВызовов КАК Журнал
ГДЕ
	Журнал.Клиент = &Клиент"""


def obj(name: str, **kwargs) -> Field:
    return Field(name, "Объект." + name, **kwargs)


def check(name: str) -> Field:
    return Field(name, "Объект." + name, type="CheckBoxField", title_location="Right")


def column(table: str, name: str, title: str | None = None, type: str = "InputField", path: str = "",
           **kwargs) -> Field:
    return Field(table + name, f"{path or table}.{name}", type=type, title=title, **kwargs)


FORM = Form(
    kind="object",
    events={
        "OnCreateAtServer": "ПриСозданииНаСервере",
        "AfterWriteAtServer": "ПослеЗаписиНаСервере",
        "NotificationProcessing": "ОбработкаОповещения",
    },
    items=[
        Group(
            "ГруппаШапка",
            Field("Наименование", "Объект.Description", hstretch=True),
            obj("ТипКлиента"),
            group="Horizontal",
        ),
        Group(
            "ГруппаБлокировка",
            Label("ДекорацияБлокировка", "", hstretch=True, color="SpecialTextColor"),
            Button("КнопкаСнятьБлокировку", "СнятьБлокировку", type="Hyperlink"),
            group="Horizontal",
            visible=False,
        ),
        Pages(
            "Страницы",
            Page(
                "СтраницаОсновное", "Основне",
                obj("Профиль", hstretch=True),
                obj("ИмяПользователяИБ", hstretch=True, choice_button=True,
                    events={"StartChoice": "ИмяПользователяИБНачалоВыбора"}),
                obj("Ответственный", hstretch=True),
                check("ВнешнийПровайдер"),
                check("Заблокирован"),
                obj("Комментарий", multiline=True, height=3, hstretch=True, vstretch=False),
            ),
            Page(
                "СтраницаОграничения", "Обмеження",
                obj("РазрешенныеАдреса", multiline=True, height=3, hstretch=True),
                obj("РазрешенныеИсточники", multiline=True, height=3, hstretch=True),
                Group(
                    "ГруппаОкно",
                    obj("ДоступС"),
                    obj("ДоступПо"),
                    title="Вікно доступу (порожнє - будь-коли)",
                    show_title=True,
                    group="Horizontal",
                ),
                Group(
                    "ГруппаЛимиты",
                    obj("ЛимитСтрок", width=8),
                    obj("ВызововВМинуту", width=8),
                    obj("СтрокВСутки", width=10),
                    title="Ліміти клієнта (0 - за профілем)",
                    show_title=True,
                    group="Horizontal",
                ),
                Table(
                    "ЗначенияПараметров", "Объект.ЗначенияПараметров",
                    column("ЗначенияПараметров", "Параметр", width=20, path="Объект.ЗначенияПараметров"),
                    column("ЗначенияПараметров", "Значение", path="Объект.ЗначенияПараметров"),
                    title="Значення параметрів профілю",
                    title_location="Top",
                    auto_fill=True, change_row_set=True, change_row_order=True, height_rows=4,
                ),
            ),
            Page(
                "СтраницаТокены", "Токени",
                Label("ДекорацияТокеныНовыйКлиент", "Запишіть клієнта, щоб видати йому токен.", hstretch=True,
                      visible=False),
                Table(
                    "Токены", "Токены",
                    column("Токены", "Идентификатор", "Ідентифікатор", width=14),
                    column("Токены", "Состояние", "Стан"),
                    column("Токены", "Наименование", "Коментар"),
                    column("Токены", "ДатаВыпуска", "Видано"),
                    column("Токены", "ДействуетДо", "Діє до"),
                    column("Токены", "ПоследнееИспользование", "Останнє використання"),
                    column("Токены", "ОбластьДоступа", "Область (порожньо - усі можливості профілю)"),
                    column("Токены", "Автор", "Видав"),
                    read_only=True, change_row_set=False, height_rows=6,
                    buttons=[
                        Button("ТокеныВыпуститьТокен", "ВыпуститьТокен", representation="PictureAndText"),
                        Button("ТокеныОтозватьТокен", "ОтозватьТокен"),
                        Button("ТокеныОбновитьТокены", "ОбновитьТокены"),
                    ],
                ),
            ),
            Page(
                "СтраницаOAuth", "OAuth",
                Label("ДекорацияOAuth", "Веб-коннектори (claude.ai, ChatGPT) і Claude Code підключаються через браузер: "
                      "видайте код підключення й передайте його користувачу разом з адресою сервера. Код одноразовий "
                      "і діє кілька хвилин; підключення працює з правами цього клієнта доступу.", hstretch=True),
                Label("ДекорацияOAuthНовыйКлиент", "Запишіть клієнта, щоб видати код підключення.", hstretch=True,
                      visible=False),
                Field("КодПодключенияOAuth", "КодПодключенияOAuth", title="Код підключення (показується один раз)",
                      title_location="Top", read_only=True, multiline=True, height=7, auto_max_width=False,
                      hstretch=True, vstretch=False, visible=False),
                Table(
                    "ПодключенияOAuth", "ПодключенияOAuth",
                    column("ПодключенияOAuth", "Идентификатор", "Ідентифікатор", width=14),
                    column("ПодключенияOAuth", "Приложение", "Застосунок"),
                    column("ПодключенияOAuth", "Состояние", "Стан"),
                    column("ПодключенияOAuth", "ДатаПодключения", "Підключено"),
                    column("ПодключенияOAuth", "ДействуетДо", "Діє до"),
                    column("ПодключенияOAuth", "ПоследнееИспользование", "Останнє використання"),
                    column("ПодключенияOAuth", "Области", "Області"),
                    column("ПодключенияOAuth", "ХостВозврата", "Повернення на"),
                    column("ПодключенияOAuth", "Автор", "Видав код"),
                    read_only=True, change_row_set=False, height_rows=6,
                    buttons=[
                        Button("ПодключенияOAuthВыдатьКод", "ВыдатьКодПодключенияOAuth", representation="PictureAndText"),
                        Button("ПодключенияOAuthОтозвать", "ОтозватьПодключениеOAuth"),
                        Button("ПодключенияOAuthОбновить", "ОбновитьПодключенияOAuth"),
                    ],
                ),
            ),
            Page(
                "СтраницаЖурнал", "Журнал",
                Table(
                    "Журнал", "Журнал",
                    column("Журнал", "Момент", "Час (UTC)"),
                    column("Журнал", "Метод", "Метод"),
                    column("Журнал", "Инструмент", "Інструмент або ресурс"),
                    column("Журнал", "Результат", "Результат"),
                    column("Журнал", "КоличествоСтрок", "Рядків"),
                    column("Журнал", "ДлительностьМс", "Тривалість, мс"),
                    column("Журнал", "Причина", "Причина"),
                    column("Журнал", "АдресКлиента", "IP-адреса"),
                    column("Журнал", "ИнформацияКлиента", "Програма клієнта"),
                    read_only=True, dynamic=True, auto_fill=True, height_rows=10,
                ),
            ),
            representation="TabsOnTop",
        ),
    ],
    attributes=[
        Attr("Объект", "CatalogObject.mcp1c_КлиентыДоступа", main=True, saved=True),
        Attr("Токены", "ValueTable", columns=[
            Col("Ссылка", "CatalogRef.mcp1c_ТокеныДоступа"),
            Col("Идентификатор", "String(12)"),
            Col("Состояние", "String(50)"),
            Col("Наименование", "String(100)"),
            Col("ДатаВыпуска", "Date"),
            Col("ДействуетДо", "Date"),
            Col("ПоследнееИспользование", "Date"),
            Col("ОбластьДоступа", "String(1000)"),
            Col("Автор", "String(100)"),
        ]),
        Attr("КодПодключенияOAuth", "String"),
        Attr("ПодключенияOAuth", "ValueTable", columns=[
            Col("Ссылка", "CatalogRef.mcp1c_ПодключенияOAuth"),
            Col("Идентификатор", "String(12)"),
            Col("Приложение", "String(150)"),
            Col("Состояние", "String(50)"),
            Col("ДатаПодключения", "Date"),
            Col("ДействуетДо", "Date"),
            Col("ПоследнееИспользование", "Date"),
            Col("Области", "String(100)"),
            Col("ХостВозврата", "String(255)"),
            Col("Автор", "String(100)"),
        ]),
        Attr("Журнал", "DynamicList", dynamic_list={
            "query": JOURNAL_QUERY, "main_table": "InformationRegister.mcp1c_ЖурналВызовов"}),
    ],
    commands=[
        Command("ВыпуститьТокен", "Видати токен...", "Видати клієнту новий токен: термін, область, фрагменти "
                "підключення", picture="StdPicture.CreateListItem"),
        Command("ОтозватьТокен", "Відкликати", "Відкликати вибраний токен: діє з наступного запиту"),
        Command("ОбновитьТокены", "Оновити", "Оновити список токенів і час останнього використання",
                picture="StdPicture.Refresh"),
        Command("СнятьБлокировку", "Зняти блокування", "Зняти автоматичне блокування клієнта"),
        Command("ВыдатьКодПодключенияOAuth", "Видати код підключення", "Видати одноразовий код для підключення "
                "AI-клієнта через OAuth (claude.ai, ChatGPT, Claude Code)", picture="StdPicture.CreateListItem"),
        Command("ОтозватьПодключениеOAuth", "Відкликати", "Відкликати вибране підключення: його токени перестають "
                "діяти з наступного запиту"),
        Command("ОбновитьПодключенияOAuth", "Оновити", "Оновити список підключень OAuth", picture="StdPicture.Refresh"),
    ],
)
