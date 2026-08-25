# Билдеры

Билдер собирает одну команду шаг за шагом и отправляет её, когда вы скажете. Их пять:

| Билдер | Откуда берётся | Что отправляет |
|---|---|---|
| `DomainCreateBuilder` | `client.domain.create_builder(name)` | `domain.create()` |
| `DomainUpdateBuilder` | `client.domain.update_builder(name)` | `domain.update()` |
| `ContactCreateBuilder` | `client.contact.create_builder(contact_id, email)` | `contact.create()` |
| `ContactUpdateBuilder` | `client.contact.update_builder(contact_id)` | `contact.update()` |
| `HostUpdateBuilder` | `client.host.update_builder(name)` | `host.update()` |

Билдер не строит собственного XML. `send()` передаёт собранные им параметры обычному методу, поэтому
**билдер и эквивалентный прямой вызов дают идентичный кадр**, и всякая проверка, действующая для
одного, действует и для другого.

Именованные аргументы и так дают вам названные параметры и громкий `TypeError` при опечатке, поэтому
пишите прямой вызов, когда вся команда собрана в одном месте. За билдером тянитесь тогда, когда
команда собирается по частям — в разных ветках, в цикле или из формы:

```python
response = (client.domain.create_builder("example.com.ua")
            .years(1)
            .registrant("C1")
            .admin_contact("EXAMPLE-C2")
            .tech_contact("EXAMPLE-C3").tech_contact("EXAMPLE-C4")   # накапливает
            .nameserver("ns1.example.com.ua").nameserver("ns2.example.com.ua")
            .auth_info("D0main-Pw!")
            .max_fee("180.00", "UAH")
            .send())

response.object_name()     # 'example.com.ua'
response.expiry_date()     # сохраните её: renew() обязан вернуть её обратно
```

## Четыре правила, действующие для каждого билдера

**1. Каждый шаг возвращает билдер**, поэтому вызовы сцепляются. Больше ничего не возвращается, и
удерживать от шага нечего.

**2. Каждый шаг-список накапливает.** Передать несколько аргументов сразу, вызвать шаг ещё раз или и
то и другое — всё это одно и то же:

```python
b.tech_contact("EXAMPLE-C3", "EXAMPLE-C4")
b.tech_contact("EXAMPLE-C3").tech_contact("EXAMPLE-C4")   # то же самое
```

Одиночные шаги, наоборот, замещают: второй вызов `.years()` оставляет второе значение. В таблицах
ниже сказано, что есть что.

**3. До `send()` не отправляется ничего.** До этого момента билдер — обычное значение: храните его,
передавайте, проносите через ветвление, разглядывайте. `to_options()` показывает ровно то, что уйдёт.

**4. Билдер отправляет один раз.** Второй `send()` бросает `ValidationException` и не отправляет
ничего:

```python
builder = client.domain.create_builder("example.com.ua").years(1).registrant("C1")
builder.send()
builder.send()
# ValidationException: DomainCreateBuilder has already been sent. A builder carries one command;
# build another rather than re-sending this one.
```

Отправить дважды — это две регистрации и два списания, и второе никогда не то, что имел в виду
вызывающий. Там, где ту же команду действительно нужно повторить — второе имя, повтор после
сверки, — постройте другой билдер.

## to_options()

```python
builder.to_options() -> Dict[str, Any]
```

Возвращает параметры **ровно в том виде, в каком их принимает эквивалентный прямой вызов**, что и
превращает билдер в способ описать команду данными:

```python
builder = (client.domain.create_builder("example.com.ua")
           .years(2)
           .registrant("C1")
           .tech_contact("EXAMPLE-C3")
           .nameserver("ns1.example.com.ua")
           .max_fee("360.00", "UAH"))

builder.to_options()
# {'years': 2,
#  'registrant': 'C1',
#  'contacts': {'tech': ['EXAMPLE-C3']},
#  'nameservers': ['ns1.example.com.ua'],
#  'fee': {'amount': '360.00', 'currency': 'UAH'}}

# Та же команда, выписанная целиком:
client.domain.create("example.com.ua", **builder.to_options())
```

Два свойства, на которые можно положиться:

- **Он ничего не отправляет и не тратит билдер.** Вызовите его до `send()`, запишите результат в
  журнал и отправляйте после.
- **Это глубокая копия.** Полученный словарь не меняется, когда добавляется ещё один шаг, поэтому
  записанное в журнал и отправленное не разойдутся. Его можно безопасно хранить, ставить в очередь
  и сериализовать.

Это и делает пробный прогон честным:

```python
options = builder.to_options()
log.info("about to register %s: %r", "example.com.ua", options)
if not requires_approval(options):
    builder.send()
```

---

## DomainCreateBuilder

`client.domain.create_builder(name)` — отправляет [`domain.create`](domains.md#create). Имя — это
аргумент конструктора; всё остальное — шаги.

| Шаг | Аргументы | Что задаёт |
|---|---|---|
| `years(years)` | `int` | `years` — срок регистрации, `<domain:period unit="y">`. Замещает. Опустите его — и реестр применит своё значение по умолчанию |
| `registrant(handle)` | `str` | `registrant` — держатель домена. Замещает |
| `contact(role, *handles)` | `str`, `str…` | `contacts[role]` — по одному `<domain:contact type="role">` на идентификатор. **Накапливает** |
| `admin_contact(*handles)` | `str…` | то же самое, в роли `admin`. **Накапливает** |
| `tech_contact(*handles)` | `str…` | то же самое, в роли `tech`. **Накапливает** |
| `billing_contact(*handles)` | `str…` | то же самое, в роли `billing`. **Накапливает** |
| `nameserver(host)` | `str` | одно имя в `nameservers`, как `<domain:hostObj>`. **Накапливает** |
| `nameservers(*hosts)` | `str…` | то же самое, по нескольку за раз. **Накапливает** |
| `nameserver_with_glue(host, *addresses)` | `str`, `str…` | одна запись `{"name", "addresses"}` в `nameservers`, как `<domain:hostAttr>`. **Накапливает** |
| `auth_info(password)` | `str` | `auth_info` — секрет трансфера. Замещает |
| `license(number)` | `str` | `license` — номер товарного знака или лицензии. Замещает |
| `max_fee(amount, currency=None)` | `str`, `str` | `fee` — потолок по RFC 8748. Замещает |
| `ds_record(key_tag, alg, digest_type, digest)` | `int, int, int, str` | одна запись в `sec_dns["ds_data"]`. **Накапливает** |
| `ds_record_with_key(key_tag, alg, digest_type, digest, flags, protocol, key_alg, pub_key)` | `int, int, int, str, int, int, int, str` | одна DS-запись вместе с DNSKEY, из которого она вычислена. **Накапливает** |
| `key_record(flags, protocol, alg, pub_key)` | `int, int, int, str` | одна запись в `sec_dns["key_data"]`. **Накапливает** |
| `max_sig_life(seconds)` | `int` | `sec_dns["max_sig_life"]`. Замещает |
| `send()` | — | отправляет команду, возвращает [`Response`](responses.md) |

```python
r = (client.domain.create_builder("example.com.ua")
     .years(2)
     .registrant("C1")
     .admin_contact("EXAMPLE-C2")
     .tech_contact("EXAMPLE-C3", "EXAMPLE-C4")
     .nameserver("ns1.example.com.ua")
     .nameserver("ns2.example.com.ua")
     .auth_info("D0main-Pw!")
     .license("TM-2026-000123")                       # если ваш реестр его требует
     .ds_record(12345, 13, 2, "49FD46E6C4B45C55D4AC")
     .max_sig_life(1209600)
     .max_fee("360.00", "UAH")
     .send())

r.code()            # 1000 или 1001, если реестр поставил регистрацию в очередь
r.expiry_date()
r.fee_amount()      # сколько списано на самом деле
```

Собрано из формы — ради этого билдер и нужен:

```python
builder = client.domain.create_builder(form["name"]).years(int(form["years"]))
builder.registrant(form["registrant"])

for handle in form.get("tech", []):          # цикл, а не список аргументов
    builder.tech_contact(handle)

if form.get("glue"):
    for host, addresses in form["glue"].items():
        builder.nameserver_with_glue(host, *addresses)
else:
    builder.nameservers(*form.get("nameservers", []))

if form.get("max_fee"):
    builder.max_fee(form["max_fee"], "UAH")

response = builder.send()
```

### Две модели серверов имён

`nameserver()` / `nameservers()` называют **объект хоста**, который у реестра уже есть;
`nameserver_with_glue()` встраивает адреса. RFC 5731 делает `<domain:ns>` выбором между этими двумя,
поэтому одна команда пользуется либо одной моделью, либо другой. Смешение бросает
`ValidationException` в `send()`, до того как что-либо уйдёт на провод, — схема всё равно отклонила
бы такой кадр, голым 2001, не назвав ни одного поля.
Подробности — в [Домены → серверы имён](domains.md#серверы-имён-обе-модели).

### Шаги, которые отказывают значению

Шаг проверяет то, что может проверить там, где сообщение ещё способно назвать аргумент:

| Шаг | Отказывает |
|---|---|
| `max_fee()` | сумме, которая не является простой десятичной: `'100,00'`, `'$100'` |
| `ds_record()`, `ds_record_with_key()` | пустому дайджесту |
| `key_record()`, `ds_record_with_key()` | пустому открытому ключу |
| `contact()` | пустой роли |
| `nameserver_with_glue()` | пустому имени хоста |

Все они бросают `ValidationException`, и ничего не отправлено — билдер по-прежнему годен, так что
исправьте значение и продолжайте.

---

## DomainUpdateBuilder

`client.domain.update_builder(name)` — отправляет [`domain.update`](domains.md#update).

Обновление в EPP — это **дельта, а не замена**: то, чего вы не упомянули, остаётся ровно как было.
Три блока — это и есть семантика команды, и имя каждого шага говорит, в какой блок он попадёт:

| Блок | Означает | Шаги |
|---|---|---|
| `add` | добавить это к тому, что уже есть | `add_nameserver(s)`, `add_contact`, `add_status` |
| `rem` | убрать это | `rem_nameserver(s)`, `rem_contact`, `rem_status` |
| `chg` | заменить это одиночное поле | `change_registrant`, `change_auth_info`, `clear_auth_info` |

Один и тот же сервер имён в `add` и в `rem` — это две разные команды, а не разница в написании, и
шага, который «задаёт серверы имён», нет: в протоколе такой операции не существует.

| Шаг | Аргументы | Блок | Что задаёт |
|---|---|---|---|
| `add_nameserver(host)` | `str` | `add` | одно имя в `add["ns"]`. **Накапливает** |
| `add_nameservers(*hosts)` | `str…` | `add` | то же самое, по нескольку за раз. **Накапливает** |
| `rem_nameserver(host)` | `str` | `rem` | одно имя в `rem["ns"]`. **Накапливает** |
| `rem_nameservers(*hosts)` | `str…` | `rem` | то же самое, по нескольку за раз. **Накапливает** |
| `add_contact(role, *handles)` | `str`, `str…` | `add` | `add["contacts"][role]`. **Накапливает** |
| `rem_contact(role, *handles)` | `str`, `str…` | `rem` | `rem["contacts"][role]`. **Накапливает** |
| `add_status(*statuses)` | `str…` | `add` | `add["statuses"]` — клиентский статус, например `clientHold`. **Накапливает** |
| `rem_status(*statuses)` | `str…` | `rem` | `rem["statuses"]`. **Накапливает** |
| `change_registrant(handle)` | `str` | `chg` | `chg["registrant"]` — передать домен другому держателю. Замещает |
| `change_auth_info(password)` | `str` | `chg` | `chg["auth_info"]` — заменить секрет трансфера. Замещает |
| `clear_auth_info()` | — | `chg` | `chg["clear_auth_info"]` — **удалить** секрет трансфера полностью |
| `restore()` | — | верхний уровень | `restore=True` — запрос восстановления по RFC 3915 |
| `license(number)` | `str` | верхний уровень | `license` — номер товарного знака или лицензии |
| `max_fee(amount, currency=None)` | `str`, `str` | верхний уровень | `fee` — потолок по RFC 8748 для тарифицируемого обновления |
| `add_ds_record(key_tag, alg, digest_type, digest)` | `int, int, int, str` | `sec_dns["add"]` | одна DS-запись к добавлению. **Накапливает** |
| `rem_ds_record(key_tag, alg, digest_type, digest)` | `int, int, int, str` | `sec_dns["rem"]` | одна DS-запись к удалению; каждое поле должно совпадать с тем, что хранит реестр. **Накапливает** |
| `add_key_record(flags, protocol, alg, pub_key)` | `int, int, int, str` | `sec_dns["add"]` | один открытый ключ к добавлению. **Накапливает** |
| `rem_key_record(flags, protocol, alg, pub_key)` | `int, int, int, str` | `sec_dns["rem"]` | один открытый ключ к удалению. **Накапливает** |
| `remove_all_dnssec()` | — | `sec_dns` | `rem_all=True` — полностью снять подпись с домена |
| `max_sig_life(seconds)` | `int` | `sec_dns` | время жизни подписи. Замещает |
| `send()` | — | — | отправляет команду, возвращает [`Response`](responses.md) |

```python
# Переделегировать и заблокировать, одной командой.
(client.domain.update_builder("example.com.ua")
    .add_nameserver("ns3.example.com.ua")
    .rem_nameserver("ns2.example.com.ua")
    .add_status("clientUpdateProhibited")
    .send())

# Сменить ключ DNSSEC без окна, в котором домен остаётся неподписанным.
(client.domain.update_builder("example.com.ua")
    .rem_ds_record(12345, 13, 2, "49FD46E6C4B45C55D4AC")
    .add_ds_record(54321, 13, 2, "A1B2C3D4E5F60718293A")
    .send())

# Вернуть домен из выкупа, ограничив стоимость восстановления.
(client.domain.update_builder("example.com.ua")
    .restore()
    .max_fee("1200.00", "UAH")
    .send())
```

Заменяя что-либо, добавляйте раньше, чем удаляете, и в одной команде: оба блока применяются как одно
изменение, поэтому домен ни на мгновение не остаётся без серверов имён.

### clear_auth_info() — это не пустой пароль

`change_auth_info("")` сохранил бы пустую строку, а пустая строка — это значение, которое держатель
всё ещё может предъявить: домен останется ровно настолько же уводимым, каким был.
`clear_auth_info()` отправляет `<domain:authInfo><domain:null/>`, что удаляет код. Именно к этому
шагу тянутся после утечки; новый код задают через `change_auth_info()`, когда он снова понадобится
клиенту.

Схема не может выразить оба действия сразу, поэтому установка и очистка в одной команде бросают
`ValidationException`, а не применяют молча что-то одно.

### Удаление конкретных записей или всех сразу

`remove_all_dnssec()` и `rem_ds_record()` / `rem_key_record()` взаимно исключают друг друга: в
протоколе нет способа выразить и то и другое, а кадр, несущий оба, отклоняется. Билдер отказывает
первым, в любом порядке вызовов, чтобы сообщение могло сказать, что делать:

```python
(client.domain.update_builder("example.com.ua")
    .rem_ds_record(12345, 13, 2, "49FD46E6C4B45C55D4AC")
    .remove_all_dnssec())
# ValidationException: remove_all_dnssec() cannot be combined with
# rem_ds_record()/rem_key_record() — remove everything, or name what to remove, not both
```

Удалить всё и добавить новый набор в одной команде можно, и именно так заменяют весь набор ключей:
`remove_all_dnssec()` вместе с `add_ds_record()`.

---

## ContactCreateBuilder

`client.contact.create_builder(contact_id, email)` — отправляет
[`contact.create`](contacts.md#create).

Идентификатор и адрес электронной почты — аргументы конструктора, а не шаги, потому что реестр
требует оба: билдер, позволяющий забыть обязательное поле, переносит ошибку из вашего редактора на
провод. Передайте `Contact.AUTO_ID` в качестве идентификатора, чтобы его выдал реестр, и прочитайте
его обратно через `object_name()`.

| Шаг | Аргументы | Что задаёт |
|---|---|---|
| `international_address(name, city, country_code, street=(), org=None, state_province=None, postal_code=None)` | `str, str, str, Sequence[str], str, str, str` | один блок `postal_infos` типа `int` — ASCII. **Накапливает** |
| `localized_address(name, city, country_code, street=(), org=None, state_province=None, postal_code=None)` | те же | один блок `postal_infos` типа `loc` — местное письмо. **Накапливает** |
| `voice(number)` | `str` | `voice`, в форме EPP `+CC.NNNNNNNNN`. Замещает |
| `fax(number)` | `str` | `fax`, в той же форме. Замещает |
| `auth_info(password)` | `str` | `auth_info` — секрет трансфера контакта. Замещает |
| `publish(*fields)` | `str…` | `disclose` с флагом «публиковать». Замещает |
| `withhold(*fields)` | `str…` | `disclose` с флагом «скрывать». Замещает |
| `send()` | — | отправляет команду, возвращает [`Response`](responses.md) |

```python
handle = (client.contact.create_builder("C1", "contact@example.com")
          .international_address("Ivan Petrenko", "Kyiv", "UA",
                                 street=["vul. Khreshchatyk 1"],
                                 org="Pryklad LLC", postal_code="01001")
          .localized_address("Іван Петренко", "Київ", "UA",
                             street=["вул. Хрещатик 1"],
                             org="ТОВ «Приклад»", postal_code="01001")
          .voice("+380.441234567")
          .auth_info("C0ntact-Pw!")
          .withhold("email", "voice")
          .send()
          .object_name())
```

Хотя бы одна форма адреса обязательна. Давайте международную, если нет причин поступить иначе:
именно эта форма переживёт печать, отправку почтой и чтение системой, которая не знает кириллицы.
Локализованная форма — дополнение, а не альтернатива: контакт может нести обе, и `postal_info()`
вернёт те, что есть.

Пусть идентификатор выдаёт реестр, когда собственной схемы именования у вас нет:

```python
from epptools import Contact

handle = (client.contact.create_builder(Contact.AUTO_ID, "contact@example.com")
          .international_address("Ivan Petrenko", "Kyiv", "UA")
          .send()
          .object_name())        # 'c-9f4b2ad10e' — появляется здесь и больше нигде
```

### publish() и withhold()

Раскрытие данных по RFC 5733 — это флаг плюс элементы, к которым он относится, а ко всему
неперечисленному применяется обратное. Поэтому `publish()` и `withhold()` говорят одно и то же двумя
способами, и каждый **замещает** любое предыдущее раскрытие: выберите тот, который совпадает с вашим
способом об этом думать, и вызовите его один раз:

```python
.withhold("email", "voice")     # эти два скрыты; всё остальное — по политике реестра
.publish("name", "org")         # эти два можно публиковать; всё остальное скрыто
```

Имена полей — `name`, `org`, `addr`, `voice`, `fax` и `email`; что угодно другое бросает
`ValidationException` с перечислением этих шести. `name`, `org` и `addr` существуют по одному на
каждую почтовую форму, и обе формы называются за вас: скрыть только ASCII-адрес, оставив публичным
адрес в местном письме, — это настройка приватности, которая выглядит применённой, но таковой не
является.

---

## ContactUpdateBuilder

`client.contact.update_builder(contact_id)` — отправляет [`contact.update`](contacts.md#update).

Статусы идут в собственных блоках; всякое изменение поля попадает в `chg`.

| Шаг | Аргументы | Блок | Что задаёт |
|---|---|---|---|
| `change_international_address(name=None, city=None, country_code=None, street=None, org=None, state_province=None, postal_code=None)` | все необязательны | `chg` | один блок `postal_infos` типа `int`. **Накапливает** |
| `change_localized_address(…)` | те же | `chg` | один блок `postal_infos` типа `loc`. **Накапливает** |
| `change_voice(number)` | `str` | `chg` | `chg["voice"]`. Замещает |
| `change_fax(number)` | `str` | `chg` | `chg["fax"]`. Замещает |
| `change_email(email)` | `str` | `chg` | `chg["email"]`. Замещает |
| `change_auth_info(password)` | `str` | `chg` | `chg["auth_info"]` — заменить секрет трансфера. Замещает |
| `publish(*fields)` | `str…` | `chg` | `chg["disclose"]`, флаг «публиковать». Замещает |
| `withhold(*fields)` | `str…` | `chg` | `chg["disclose"]`, флаг «скрывать». Замещает |
| `add_status(*statuses)` | `str…` | `add_statuses` | например, `clientUpdateProhibited`. **Накапливает** |
| `rem_status(*statuses)` | `str…` | `rem_statuses` | снять клиентский статус. **Накапливает** |
| `send()` | — | — | отправляет команду, возвращает [`Response`](responses.md) |

```python
(client.contact.update_builder("C1")
    .change_email("new-contact@example.com")
    .change_voice("+380.443210000")
    .withhold("email", "voice")
    .add_status("clientUpdateProhibited")
    .send())
```

### Решает присутствие, а пустая строка очищает

Внутри адреса аргумент, которого вы не передали, не отправляется вовсе, поэтому реестр сохраняет то,
что у него есть. Аргумент, переданный как `""`, **отправляется** пустым, и именно это очищает поле —
и это единственный способ убрать `org`, область или почтовый индекс:

```python
# Убрать организацию, остальной адрес не трогать.
(client.contact.update_builder("C1")
    .change_international_address(org="", city="Kyiv", country_code="UA")
    .send())
```

**Передавайте `city` и `country_code` всякий раз, когда вообще трогаете адрес.** Элемент
`<contact:addr>` — это последовательность, город и страну в которой требует схема, поэтому он
отправляется целиком или не отправляется вовсе, — а раз отправляется, то вместе с городом и страной.
Не указать их в вызове, который меняет строку улицы, значит отправить их пустыми, а пустое — это
осознанная очистка. Команда ответит 1000, и контакт лишится города и страны.

Изменение одной почтовой формы оставляет другую ровно такой, какой она была.

### Здесь нет clear_auth_info()

RFC 5731 даёт домену обнуляемую форму для секрета трансфера; RFC 5733 не определяет для контакта
ничего подобного. Поэтому код контакта можно **заменить**, но нельзя удалить, и этот билдер не
предлагает шага, который делал бы вид, что это не так. Пустой пароль заменой не служит: пустое
значение — это всё ещё значение, которое держатель может предъявить.

---

## HostUpdateBuilder

`client.host.update_builder(name)` — отправляет [`host.update`](hosts.md#update).

| Шаг | Аргументы | Блок | Что задаёт |
|---|---|---|---|
| `add_address(ip)` | `str` | `add` | один адрес в `add_addresses`; v4 и v6 различаются автоматически. **Накапливает** |
| `add_addresses(*ips)` | `str…` | `add` | то же самое, по нескольку за раз. **Накапливает** |
| `rem_address(ip)` | `str` | `rem` | один адрес в `rem_addresses`. **Накапливает** |
| `rem_addresses(*ips)` | `str…` | `rem` | то же самое, по нескольку за раз. **Накапливает** |
| `add_status(*statuses)` | `str…` | `add` | `add_statuses` — `clientDeleteProhibited`, `clientUpdateProhibited`. **Накапливает** |
| `rem_status(*statuses)` | `str…` | `rem` | `rem_statuses`. **Накапливает** |
| `send()` | — | — | отправляет команду, возвращает [`Response`](responses.md) |

```python
# Перевести сервер имён на новый адрес без разрыва: добавить новый и убрать старый вместе.
(client.host.update_builder("ns1.example.com.ua")
    .add_addresses("203.0.113.11", "2001:db8::11")
    .rem_address("203.0.113.10")
    .send())
```

Шага переименования **нет**, потому что нет и самого переименования: этот реестр читает только блоки
добавления и удаления. Создайте хост-замену, перенаправьте на него домены, которые им пользуются, и
затем удалите старый — три команды приведены в
[Хосты → Переименования нет](hosts.md#переименования-не-существует).

Удаление последнего адреса подчинённого хоста отклоняется (2003), а не снимает молча делегирование, а
внешний хост вообще не может получить адреса (2306).

---

## Когда билдер не нужен

Когда вся команда написана в одном месте, прямой вызов короче и читается так же:

```python
client.domain.create("example.com.ua", years=1, registrant="C1",
                     nameservers=["ns1.example.com.ua"])
```

Обе формы поддерживаются, и ни одна не предпочтительнее. Билдер оправдывает себя, когда команда
собирается по веткам или в цикле, когда через `to_options()` её хочется записать в журнал или
поставить в очередь, или когда названные шаги обновления — `add_nameserver`, `rem_status`,
`change_registrant` — делают дельту понятнее, чем три вложенных словаря.

---

См. также: [Домены](domains.md) · [Контакты](contacts.md) · [Хосты](hosts.md) ·
[Баланс и цены](balance.md) · [Ответы](responses.md) · [Ошибки](errors.md)

[← Указатель руководства](README.md)
