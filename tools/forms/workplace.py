"""Робоче місце MCP-сервера (ТЗ п. 8.3, 9.2): стан, адреса, увімкнення, попередження, моніторинг, OAuth (п. 6.4)."""
from formxml import Attr, Button, Col, Command, Field, Form, Group, Label, Page, Pages, Table

PATH = "CommonForms/mcp1c_РабочееМесто/Form.form"

CLIENT = "CatalogRef.mcp1c_КлиентыДоступа"
TOKEN = "CatalogRef.mcp1c_ТокеныДоступа"
OAUTH_CLIENT = "CatalogRef.mcp1c_КлиентыOAuth"


def column(table: str, name: str, title: str, align: str | None = None) -> Field:
    return Field(table + name, f"{table}.{name}", title=title, horizontal_align=align)


def hint(name: str, text: str) -> Label:
    return Label(name, text, hstretch=True)


FORM = Form(
    title="MCP-сервер",
    events={"OnCreateAtServer": "ПриСозданииНаСервере"},
    buttons=[
        Button("ФормаОбновить", "Обновить"),
        Button("ФормаВключить", "Включить"),
        Button("ФормаВыключить", "Выключить"),
        Button("ФормаПодтвердитьПеренос", "ПодтвердитьПеренос"),
        Button("ФормаПроверитьЧувствительныеПоля", "ПроверитьЧувствительныеПоля"),
        Button("ФормаОткрытьМастер", "ОткрытьМастер"),
    ],
    items=[
        Group(
            "ГруппаСостояние",
            Label("ДекорацияСостояние", "Стан сервера", hstretch=True, bold=True),
            Group(
                "ГруппаАдрес",
                Field("КаноническийАдрес", "КаноническийАдрес", title="Публічна адреса", hstretch=True,
                      input_hint="https://mcp.company.ua/mcp"),
                Button("КнопкаЗаписатьАдрес", "ЗаписатьАдрес"),
                group="Horizontal",
            ),
            Field("Привязка", "Привязка", type="LabelField", title="Прив'язка до бази", hstretch=True),
            Label("ДекорацияПодробности", "", hstretch=True),
            group="Vertical",
        ),
        Group(
            "ГруппаПредупреждения",
            Label("ДекорацияПредупреждения", "", hstretch=True, color="SpecialTextColor"),
            title="Попередження",
            show_title=True,
            representation="NormalSeparation",
        ),
        Pages(
            "Страницы",
            Page(
                "СтраницаПоказатели", "Показники",
                hint("ДекорацияПоказатели", "Останні 24 години і 7 днів. Тривалість - виклики інструментів, "
                     "ресурсів і промптів."),
                Table(
                    "Показатели", "Показатели",
                    column("Показатели", "Показатель", "Показник"),
                    column("Показатели", "ЗаСутки", "За добу", "Right"),
                    column("Показатели", "ЗаНеделю", "За тиждень", "Right"),
                    read_only=True, command_bar=False,
                ),
            ),
            Page(
                "СтраницаИнструменты", "Інструменти",
                hint("ДекорацияИнструменты", "Виклики tools/call за 7 днів."),
                Table(
                    "Инструменты", "Инструменты",
                    column("Инструменты", "Инструмент", "Інструмент"),
                    column("Инструменты", "Вызовов", "Викликів"),
                    column("Инструменты", "Ошибок", "Неуспішних"),
                    column("Инструменты", "Средняя", "Середня тривалість", "Right"),
                    column("Инструменты", "P95", "p95", "Right"),
                    column("Инструменты", "Максимум", "Найдовший", "Right"),
                    read_only=True, command_bar=False,
                ),
            ),
            Page(
                "СтраницаОбъекты", "Об'єкти",
                hint("ДекорацияОбъекты", "Об'єкти, до яких зверталися клієнти за 7 днів."),
                Table(
                    "Объекты", "Объекты",
                    column("Объекты", "Объект", "Об'єкт"),
                    column("Объекты", "Обращений", "Звернень"),
                    read_only=True, command_bar=False,
                ),
            ),
            Page(
                "СтраницаОтказы", "Відмови і помилки",
                hint("ДекорацияОтказы", "Останні 50 неуспішних викликів за 7 днів."),
                Table(
                    "Отказы", "Отказы",
                    column("Отказы", "Момент", "Час"),
                    column("Отказы", "Клиент", "Клієнт"),
                    column("Отказы", "Вызов", "Виклик"),
                    column("Отказы", "Результат", "Результат"),
                    column("Отказы", "Причина", "Причина"),
                    column("Отказы", "АдресКлиента", "IP-адреса"),
                    read_only=True, command_bar=False, events={"Selection": "ОтказыВыбор"},
                ),
            ),
            Page(
                "СтраницаТокены", "Токени, що спливають",
                hint("ДекорацияТокены", "Діючі токени, термін яких спливає протягом 7 днів."),
                Table(
                    "Токены", "Токены",
                    column("Токены", "Клиент", "Клієнт"),
                    column("Токены", "Токен", "Токен"),
                    column("Токены", "ДействуетДо", "Діє до"),
                    column("Токены", "Осталось", "Залишилось"),
                    read_only=True, command_bar=False, events={"Selection": "ТокеныВыбор"},
                ),
            ),
            Page(
                "СтраницаБлокировки", "Блокування",
                hint("ДекорацияБлокировки", "Тимчасові блокування IP-адрес після перебору токенів і клієнтів "
                     "після серії відмов політики."),
                Table(
                    "Блокировки", "Блокировки",
                    column("Блокировки", "Вид", "Вид"),
                    column("Блокировки", "Объект", "Заблоковано"),
                    column("Блокировки", "ДействуетДо", "Діє до"),
                    column("Блокировки", "Осталось", "Залишилось"),
                    column("Блокировки", "Причина", "Причина"),
                    read_only=True, buttons=[Button("БлокировкиСнятьБлокировку", "СнятьБлокировку")],
                    events={"Selection": "БлокировкиВыбор"},
                ),
            ),
            Page(
                "СтраницаOAuth", "OAuth",
                hint("ДекорацияOAuth", "OAuth 2.1 для веб-коннекторів (claude.ai, ChatGPT) і Claude Code: користувач "
                     "вводить на сторінці 1С код підключення з картки клієнта доступу. Потрібні публічна адреса HTTPS "
                     "і маршрути проксі /mcp/oauth/ та /.well-known/ (deploy/nginx, deploy/iis)."),
                Group(
                    "ГруппаOAuthНастройки",
                    Field("OAuthВключен", "OAuthВключен", type="CheckBoxField", title="OAuth увімкнено",
                          title_location="Right"),
                    Group(
                        "ГруппаOAuthСроки",
                        Field("СрокДоступаМинут", "СрокДоступаМинут", title="Токен доступу, хв", width=5,
                              spin_button=True, min_value=5, max_value=1440),
                        Field("СрокОбновленияДней", "СрокОбновленияДней", title="токен оновлення, дн.", width=4,
                              spin_button=True, min_value=1, max_value=365),
                        Field("СрокПодключенияДней", "СрокПодключенияДней", title="підключення, дн.", width=4,
                              spin_button=True, min_value=1, max_value=365),
                        Field("СрокКодаМинут", "СрокКодаМинут", title="код підключення, хв", width=3,
                              spin_button=True, min_value=1, max_value=60),
                        group="Horizontal",
                    ),
                    Field("ПрефиксыCIMD", "ПрефиксыCIMD", title="Довірені адреси документів клієнтів (CIMD), по одній "
                          "у рядку", title_location="Top", multiline=True, height=3, hstretch=True),
                    Field("ДинамическаяРегистрация", "ДинамическаяРегистрация", type="CheckBoxField",
                          title="Динамічна реєстрація клієнтів (RFC 7591, лише для сумісності)", title_location="Right"),
                    Button("КнопкаЗаписатьНастройкиOAuth", "ЗаписатьНастройкиOAuth"),
                    Field("АдресаOAuth", "АдресаOAuth", type="LabelField", title="Адреси", title_location="Top",
                          hstretch=True),
                    group="Vertical",
                ),
                Field("ДанныеКлиентаOAuth", "ДанныеКлиентаOAuth", title="Зареєстрований клієнт (секрет показується "
                      "один раз)", title_location="Top", read_only=True, multiline=True, height=5, hstretch=True,
                      vstretch=False, auto_max_width=False, visible=False),
                Table(
                    "КлиентыOAuth", "КлиентыOAuth",
                    column("КлиентыOAuth", "Имя", "Клієнт OAuth"),
                    column("КлиентыOAuth", "ИдентификаторКлиента", "client_id"),
                    column("КлиентыOAuth", "Источник", "Реєстрація"),
                    column("КлиентыOAuth", "СпособАутентификации", "Автентифікація"),
                    column("КлиентыOAuth", "АдресаВозврата", "Адреси повернення"),
                    column("КлиентыOAuth", "Состояние", "Стан"),
                    read_only=True,
                    buttons=[
                        Button("КлиентыOAuthЗарегистрировать", "ЗарегистрироватьКлиентаOAuth"),
                        Button("КлиентыOAuthЗаблокировать", "ЗаблокироватьКлиентаOAuth"),
                    ],
                ),
            ),
            representation="TabsOnTop",
        ),
    ],
    attributes=[
        Attr("КаноническийАдрес", "String(500)", title="Публічна адреса"),
        Attr("Привязка", "String(500)", title="Прив'язка до бази"),
        Attr("ЕстьПраваАдминистратора", "Boolean"),
        Attr("НастройкиДоступны", "Boolean"),
        Attr("Включен", "Boolean"),
        Attr("ТребуетсяПодтверждениеПереноса", "Boolean"),
        Attr("ЧувствительныеПоляПроверены", "Boolean"),
        Attr("ПрофилиСЧувствительнымиПолями", "String"),
        Attr("АдресПроверки", "String"),
        Attr("ЗаданиеПроверки", "String(36)"),
        Attr("OAuthВключен", "Boolean", title="OAuth увімкнено"),
        Attr("СрокДоступаМинут", "Number(4,0,+)", title="Токен доступу, хв"),
        Attr("СрокОбновленияДней", "Number(3,0,+)", title="Токен оновлення, дн."),
        Attr("СрокПодключенияДней", "Number(3,0,+)", title="Підключення, дн."),
        Attr("СрокКодаМинут", "Number(2,0,+)", title="Код підключення, хв"),
        Attr("ПрефиксыCIMD", "String", title="Довірені адреси документів клієнтів"),
        Attr("ДинамическаяРегистрация", "Boolean", title="Динамічна реєстрація клієнтів"),
        Attr("АдресаOAuth", "String", title="Адреси"),
        Attr("ДанныеКлиентаOAuth", "String"),
        Attr("НовыйКлиентOAuth", "String(150)"),
        Attr("АдресаНовогоКлиентаOAuth", "String"),
        Attr("КлиентыOAuth", "ValueTable", columns=[
            Col("Ссылка", OAUTH_CLIENT),
            Col("Имя", "String(150)"),
            Col("ИдентификаторКлиента", "String(500)"),
            Col("Источник", "String(50)"),
            Col("СпособАутентификации", "String(30)"),
            Col("АдресаВозврата", "String"),
            Col("Заблокирован", "Boolean"),
            Col("Состояние", "String(50)"),
        ]),
        Attr("Показатели", "ValueTable", columns=[
            Col("Показатель", "String(150)"),
            Col("ЗаСутки", "String(50)"),
            Col("ЗаНеделю", "String(50)"),
        ]),
        Attr("Инструменты", "ValueTable", columns=[
            Col("Инструмент", "String(100)"),
            Col("Вызовов", "Number(10,0)"),
            Col("Ошибок", "Number(10,0)"),
            Col("Средняя", "String(30)"),
            Col("P95", "String(30)"),
            Col("Максимум", "String(30)"),
        ]),
        Attr("Объекты", "ValueTable", columns=[
            Col("Объект", "String(255)"),
            Col("Обращений", "Number(10,0)"),
        ]),
        Attr("Отказы", "ValueTable", columns=[
            Col("Момент", "Date"),
            Col("Клиент", CLIENT),
            Col("Вызов", "String(150)"),
            Col("Результат", "String(50)"),
            Col("Причина", "String(500)"),
            Col("АдресКлиента", "String(45)"),
        ]),
        Attr("Токены", "ValueTable", columns=[
            Col("Токен", TOKEN),
            Col("Клиент", CLIENT),
            Col("ДействуетДо", "Date"),
            Col("Осталось", "String(50)"),
        ]),
        Attr("Блокировки", "ValueTable", columns=[
            Col("ВидБлокировки", "String(20)"),
            Col("Вид", "String(20)"),
            Col("Ключ", "String(100)"),
            Col("Объект", "String(255)"),
            Col("Клиент", CLIENT),
            Col("ДействуетДо", "Date"),
            Col("Осталось", "String(50)"),
            Col("Причина", "String(500)"),
        ]),
    ],
    commands=[
        Command("Обновить", "Оновити", "Оновити стан і показники", picture="StdPicture.Refresh"),
        Command("Включить", "Увімкнути", "Увімкнути MCP-сервер із вказаною публічною адресою"),
        Command("Выключить", "Вимкнути", "Вимкнути MCP-сервер: клієнти отримуватимуть 503"),
        Command("ПодтвердитьПеренос", "Підтвердити перенесення бази",
                "Прийняти нове розташування бази після перенесення або відновлення з копії; усі токени буде відкликано"),
        Command("ЗаписатьАдрес", "Зберегти адресу", "Зберегти публічну адресу MCP-ендпоінта"),
        Command("ПроверитьЧувствительныеПоля", "Перевірити профілі на чутливі поля",
                "Знайти профілі клієнтів, які показують чутливі поля без маски (фонове завдання)"),
        Command("СнятьБлокировку", "Зняти блокування", "Зняти вибране блокування IP-адреси або клієнта"),
        Command("ЗаписатьНастройкиOAuth", "Зберегти налаштування OAuth", "Зберегти налаштування OAuth: увімкнення, "
                "строки токенів і коду підключення, довірені адреси документів клієнтів"),
        Command("ЗарегистрироватьКлиентаOAuth", "Зареєструвати клієнта...", "Попередньо зареєструвати клієнта OAuth "
                "без документа метаданих: client_id (і секрет) вводяться в налаштуваннях коннектора",
                picture="StdPicture.CreateListItem"),
        Command("ЗаблокироватьКлиентаOAuth", "Заблокувати / розблокувати", "Заблокувати вибраного клієнта OAuth або "
                "зняти блокування: підключення заблокованого клієнта перестають працювати"),
        Command("ОткрытьМастер", "Майстер налаштування",
                "Публікація і проксі, чутливі поля, профіль «Тільки метадані» і перший клієнт"),
    ],
)
