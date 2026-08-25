# Білдери

Білдер збирає одну команду крок за кроком і надсилає її, коли ви скажете. Їх п'ять:

| Білдер | Звідки | Надсилає |
|---|---|---|
| `DomainCreateBuilder` | `client.domain.create_builder(name)` | `domain.create()` |
| `DomainUpdateBuilder` | `client.domain.update_builder(name)` | `domain.update()` |
| `ContactCreateBuilder` | `client.contact.create_builder(contact_id, email)` | `contact.create()` |
| `ContactUpdateBuilder` | `client.contact.update_builder(contact_id)` | `contact.update()` |
| `HostUpdateBuilder` | `client.host.update_builder(name)` | `host.update()` |

Білдер не будує жодного власного XML. `send()` передає зібрані ним опції звичайному методу, тож
**білдер і рівнозначний прямий виклик дають однаковий кадр**, і кожна перевірка, що діє для одного,
діє й для другого.

Іменовані аргументи вже дають вам названі параметри і гучний `TypeError` на одруку, тож пишіть прямий
виклик, коли вся команда лежить в одному місці. Беріться за білдер, коли команда збирається
частинами — по гілках, у циклі або з форми:

```python
response = (client.domain.create_builder("example.com.ua")
            .years(1)
            .registrant("C1")
            .admin_contact("EXAMPLE-C2")
            .tech_contact("EXAMPLE-C3").tech_contact("EXAMPLE-C4")   # накопичується
            .nameserver("ns1.example.com.ua").nameserver("ns2.example.com.ua")
            .auth_info("D0main-Pw!")
            .max_fee("180.00", "UAH")
            .send())

response.object_name()     # 'example.com.ua'
response.expiry_date()     # збережіть її; renew() має надіслати її назад
```

## Чотири правила, які діють для кожного білдера

**1. Кожен крок повертає білдер**, тож виклики шикуються в ланцюжок. Нічого іншого не повертається, і
з кроку нема чого лишати собі.

**2. Кожен списковий крок накопичує.** Передати кілька аргументів одразу, викликати крок ще раз чи
зробити і те, і те — усе зводиться до одного:

```python
b.tech_contact("EXAMPLE-C3", "EXAMPLE-C4")
b.tech_contact("EXAMPLE-C3").tech_contact("EXAMPLE-C4")   # те саме
```

Кроки з одним значенням натомість замінюють: після двох викликів `.years()` лишиться друге значення.
У таблицях нижче для кожного кроку вказано, який він.

**3. Нічого не надсилається до `send()`.** Доти білдер — звичайне значення: тримайте його,
передавайте, проносьте через гілку, розглядайте. `to_options()` показує рівно те, що піде.

**4. Білдер надсилає один раз.** Другий `send()` підіймає `ValidationException` і не надсилає нічого:

```python
builder = client.domain.create_builder("example.com.ua").years(1).registrant("C1")
builder.send()
builder.send()
# ValidationException: DomainCreateBuilder has already been sent. A builder carries one command;
# build another rather than re-sending this one.
```

Надіслати двічі означало б дві реєстрації і два списання, і друге — ніколи не те, чого хотів той, хто
викликав. Там, де ви справді хочете ту саму команду ще раз — інше ім'я, повтор після звірки, —
збудуйте інший білдер.

## to_options()

```python
builder.to_options() -> Dict[str, Any]
```

Повертає опції **рівно в тому вигляді, в якому їх бере рівнозначний прямий виклик**, і це робить
білдер способом описати команду як дані:

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

# Та сама команда, виписана прямо:
client.domain.create("example.com.ua", **builder.to_options())
```

Дві властивості, на які варто спиратися:

- **Він нічого не надсилає і не витрачає білдер.** Викличте його до `send()`, запишіть результат у
  журнал і надішліть після цього.
- **Це глибока копія.** Отриманий dict не змінюється, коли ви додаєте ще один крок, тож те, що ви
  записали в журнал, і те, що надіслали, не можуть розійтися. Його безпечно зберігати, ставити в чергу
  чи серіалізувати.

Саме це робить пробний прогін чесним:

```python
options = builder.to_options()
log.info("about to register %s: %r", "example.com.ua", options)
if not requires_approval(options):
    builder.send()
```

---

## DomainCreateBuilder

`client.domain.create_builder(name)` — надсилає [`domain.create`](domains.md#create). Ім'я є
аргументом конструктора; усе решта — кроки.

| Крок | Аргументи | Що задає |
|---|---|---|
| `years(years)` | `int` | `years` — строк реєстрації, `<domain:period unit="y">`. Замінює. Пропустіть його — і реєстр застосує власне типове значення |
| `registrant(handle)` | `str` | `registrant` — власник домену. Замінює |
| `contact(role, *handles)` | `str`, `str…` | `contacts[role]` — по одному `<domain:contact type="role">` на ідентифікатор. **Накопичується** |
| `admin_contact(*handles)` | `str…` | те саме, у ролі `admin`. **Накопичується** |
| `tech_contact(*handles)` | `str…` | те саме, у ролі `tech`. **Накопичується** |
| `billing_contact(*handles)` | `str…` | те саме, у ролі `billing`. **Накопичується** |
| `nameserver(host)` | `str` | одне ім'я в `nameservers`, як `<domain:hostObj>`. **Накопичується** |
| `nameservers(*hosts)` | `str…` | те саме, кілька за раз. **Накопичується** |
| `nameserver_with_glue(host, *addresses)` | `str`, `str…` | один запис `{"name", "addresses"}` у `nameservers`, як `<domain:hostAttr>`. **Накопичується** |
| `auth_info(password)` | `str` | `auth_info` — трансферний код. Замінює |
| `license(number)` | `str` | `license` — номер торгової марки або ліцензії. Замінює |
| `max_fee(amount, currency=None)` | `str`, `str` | `fee` — стеля за RFC 8748. Замінює |
| `ds_record(key_tag, alg, digest_type, digest)` | `int, int, int, str` | один запис у `sec_dns["ds_data"]`. **Накопичується** |
| `ds_record_with_key(key_tag, alg, digest_type, digest, flags, protocol, key_alg, pub_key)` | `int, int, int, str, int, int, int, str` | один DS-запис разом із DNSKEY, з якого його обчислено. **Накопичується** |
| `key_record(flags, protocol, alg, pub_key)` | `int, int, int, str` | один запис у `sec_dns["key_data"]`. **Накопичується** |
| `max_sig_life(seconds)` | `int` | `sec_dns["max_sig_life"]`. Замінює |
| `send()` | — | надсилає команду, повертає [`Response`](responses.md) |

```python
r = (client.domain.create_builder("example.com.ua")
     .years(2)
     .registrant("C1")
     .admin_contact("EXAMPLE-C2")
     .tech_contact("EXAMPLE-C3", "EXAMPLE-C4")
     .nameserver("ns1.example.com.ua")
     .nameserver("ns2.example.com.ua")
     .auth_info("D0main-Pw!")
     .license("TM-2026-000123")                       # якщо ваш реєстр його вимагає
     .ds_record(12345, 13, 2, "49FD46E6C4B45C55D4AC")
     .max_sig_life(1209600)
     .max_fee("360.00", "UAH")
     .send())

r.code()            # 1000 або 1001, коли реєстр ставить реєстрацію в чергу
r.expiry_date()
r.fee_amount()      # скільки насправді списано
```

Зібране з форми — це те, заради чого білдер і потрібен:

```python
builder = client.domain.create_builder(form["name"]).years(int(form["years"]))
builder.registrant(form["registrant"])

for handle in form.get("tech", []):          # цикл, а не список аргументів
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

### Дві моделі серверів імен

`nameserver()` / `nameservers()` називають **об'єкт хоста**, який реєстр уже тримає;
`nameserver_with_glue()` вбудовує адреси. RFC 5731 робить `<domain:ns>` вибором між цими двома, тож
одна команда користується або однією моделлю, або другою. Змішування підіймає `ValidationException`
у `send()`, ще до того, як щось потрапить у канал передачі, — схема все одно відхилила б кадр, голим
2001, що не називає жодного поля.
Подробиці — у розділі [Домени → nameservers](domains.md#nameservers-в-обох-моделях).

### Кроки, які відхиляють значення

Крок перевіряє те, що може перевірити, поки повідомлення ще здатне назвати аргумент:

| Крок | Що відхиляє |
|---|---|
| `max_fee()` | суму, яка не є простим десятковим числом: `'100,00'`, `'$100'` |
| `ds_record()`, `ds_record_with_key()` | порожній дайджест |
| `key_record()`, `ds_record_with_key()` | порожній публічний ключ |
| `contact()` | порожню роль |
| `nameserver_with_glue()` | порожнє ім'я хоста |

Усі вони підіймають `ValidationException`, і при цьому нічого не надіслано — білдер лишається
придатним, тож виправте значення і продовжуйте.

---

## DomainUpdateBuilder

`client.domain.update_builder(name)` — надсилає [`domain.update`](domains.md#update).

Оновлення EPP — це **дельта, а не заміна**: те, чого ви не згадали, лишається рівно таким, як було.
Три блоки і є семантикою команди, а ім'я кожного кроку каже, в який блок він потрапляє:

| Блок | Означає | Кроки |
|---|---|---|
| `add` | додати це до того, що вже є | `add_nameserver(s)`, `add_contact`, `add_status` |
| `rem` | забрати це | `rem_nameserver(s)`, `rem_contact`, `rem_status` |
| `chg` | замінити це поле з одним значенням | `change_registrant`, `change_auth_info`, `clear_auth_info` |

Той самий сервер імен у `add` і в `rem` — це дві різні команди, а не різниця в написанні, і кроку,
який «задає сервери імен», немає — у протоколі немає такої операції.

| Крок | Аргументи | Блок | Що задає |
|---|---|---|---|
| `add_nameserver(host)` | `str` | `add` | одне ім'я в `add["ns"]`. **Накопичується** |
| `add_nameservers(*hosts)` | `str…` | `add` | те саме, кілька за раз. **Накопичується** |
| `rem_nameserver(host)` | `str` | `rem` | одне ім'я в `rem["ns"]`. **Накопичується** |
| `rem_nameservers(*hosts)` | `str…` | `rem` | те саме, кілька за раз. **Накопичується** |
| `add_contact(role, *handles)` | `str`, `str…` | `add` | `add["contacts"][role]`. **Накопичується** |
| `rem_contact(role, *handles)` | `str`, `str…` | `rem` | `rem["contacts"][role]`. **Накопичується** |
| `add_status(*statuses)` | `str…` | `add` | `add["statuses"]` — клієнтський статус, як-от `clientHold`. **Накопичується** |
| `rem_status(*statuses)` | `str…` | `rem` | `rem["statuses"]`. **Накопичується** |
| `change_registrant(handle)` | `str` | `chg` | `chg["registrant"]` — передати домен іншому власнику. Замінює |
| `change_auth_info(password)` | `str` | `chg` | `chg["auth_info"]` — замінити трансферний код. Замінює |
| `clear_auth_info()` | — | `chg` | `chg["clear_auth_info"]` — **прибрати** трансферний код повністю |
| `restore()` | — | верхній рівень | `restore=True` — запит на відновлення за RFC 3915 |
| `license(number)` | `str` | верхній рівень | `license` — номер торгової марки або ліцензії |
| `max_fee(amount, currency=None)` | `str`, `str` | верхній рівень | `fee` — стеля за RFC 8748 для оновлення, за яке стягується плата |
| `add_ds_record(key_tag, alg, digest_type, digest)` | `int, int, int, str` | `sec_dns["add"]` | один DS-запис на додавання. **Накопичується** |
| `rem_ds_record(key_tag, alg, digest_type, digest)` | `int, int, int, str` | `sec_dns["rem"]` | один DS-запис на видалення; кожне поле має збігатися з тим, що тримає реєстр. **Накопичується** |
| `add_key_record(flags, protocol, alg, pub_key)` | `int, int, int, str` | `sec_dns["add"]` | один публічний ключ на додавання. **Накопичується** |
| `rem_key_record(flags, protocol, alg, pub_key)` | `int, int, int, str` | `sec_dns["rem"]` | один публічний ключ на видалення. **Накопичується** |
| `remove_all_dnssec()` | — | `sec_dns` | `rem_all=True` — зняти підпис з домену повністю |
| `max_sig_life(seconds)` | `int` | `sec_dns` | час життя підпису. Замінює |
| `send()` | — | — | надсилає команду, повертає [`Response`](responses.md) |

```python
# Переделегувати і замкнути — однією командою.
(client.domain.update_builder("example.com.ua")
    .add_nameserver("ns3.example.com.ua")
    .rem_nameserver("ns2.example.com.ua")
    .add_status("clientUpdateProhibited")
    .send())

# Змінити ключ DNSSEC без проміжку, в якому домен лишається непідписаним.
(client.domain.update_builder("example.com.ua")
    .rem_ds_record(12345, 13, 2, "49FD46E6C4B45C55D4AC")
    .add_ds_record(54321, 13, 2, "A1B2C3D4E5F60718293A")
    .send())

# Повернути домен із викупу, обмеживши те, скільки може коштувати відновлення.
(client.domain.update_builder("example.com.ua")
    .restore()
    .max_fee("1200.00", "UAH")
    .send())
```

Додавайте перед тим, як видаляти, в одній команді, щоразу коли ви щось заміняєте: обидва блоки
застосовуються як одна зміна, тож домен ніколи не лишається без серверів імен у проміжку.

### clear_auth_info() — це не порожній пароль

`change_auth_info("")` зберіг би порожній рядок, а порожній рядок — це значення, яке власник усе одно
може пред'явити: домен лишається рівно так само рухомим, як і був. `clear_auth_info()` надсилає
`<domain:authInfo><domain:null/>`, що прибирає код. Саме за цим кроком варто тягтися після витоку, а
новий задавайте через `change_auth_info()`, коли клієнту знову буде потрібен.

Схема не може виразити обидва одночасно, тож задавання і прибирання в одній команді підіймає
`ValidationException`, а не тихо застосовує щось одне.

### Видалення окремих записів або всіх одразу

`remove_all_dnssec()` і `rem_ds_record()` / `rem_key_record()` взаємно виключні: протокол не має
способу виразити обидва, і кадр, що несе обидва, буде відхилено. Білдер відхиляє це першим, у
будь-якому порядку, щоб повідомлення могло сказати, що робити:

```python
(client.domain.update_builder("example.com.ua")
    .rem_ds_record(12345, 13, 2, "49FD46E6C4B45C55D4AC")
    .remove_all_dnssec())
# ValidationException: remove_all_dnssec() cannot be combined with
# rem_ds_record()/rem_key_record() — remove everything, or name what to remove, not both
```

Видалити все й додати новий набір в одній команді — нормально, і саме так замінюють цілий набір
ключів: `remove_all_dnssec()` разом із `add_ds_record()`.

---

## ContactCreateBuilder

`client.contact.create_builder(contact_id, email)` — надсилає
[`contact.create`](contacts.md#create).

Ідентифікатор і адреса пошти є аргументами конструктора, а не кроками, бо реєстр вимагає обох:
білдер, який дозволяє забути обов'язкове поле, переніс помилку з вашого редактора в канал передачі.
Передайте `Contact.AUTO_ID` як ідентифікатор, щоб реєстр згенерував його сам, і прочитайте його назад
через `object_name()`.

| Крок | Аргументи | Що задає |
|---|---|---|
| `international_address(name, city, country_code, street=(), org=None, state_province=None, postal_code=None)` | `str, str, str, Sequence[str], str, str, str` | один блок `postal_infos` типу `int` — ASCII. **Накопичується** |
| `localized_address(name, city, country_code, street=(), org=None, state_province=None, postal_code=None)` | те саме | один блок `postal_infos` типу `loc` — локальне письмо. **Накопичується** |
| `voice(number)` | `str` | `voice`, у формі EPP `+CC.NNNNNNNNN`. Замінює |
| `fax(number)` | `str` | `fax`, тієї самої форми. Замінює |
| `auth_info(password)` | `str` | `auth_info` — трансферний код контакту. Замінює |
| `publish(*fields)` | `str…` | `disclose` із прапорцем на публікацію. Замінює |
| `withhold(*fields)` | `str…` | `disclose` із прапорцем на приховування. Замінює |
| `send()` | — | надсилає команду, повертає [`Response`](responses.md) |

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

Щонайменше одна форма адреси обов'язкова. Давайте міжнародну, якщо не маєте причини не давати: саме
ця форма переживає друк, пересилання поштою і прочитання системою, яка не знає кирилиці. Локалізована
форма є додатковою, а не альтернативою — контакт може нести обидві, і `postal_info()` повертає ті, що
він тримає.

Дозвольте реєстру згенерувати ідентифікатор, коли у вас немає власної схеми найменування:

```python
from epptools import Contact

handle = (client.contact.create_builder(Contact.AUTO_ID, "contact@example.com")
          .international_address("Ivan Petrenko", "Kyiv", "UA")
          .send()
          .object_name())        # 'c-9f4b2ad10e' — з'являється тут і більше ніде
```

### publish() і withhold()

Розкриття за RFC 5733 — це прапорець плюс елементи, яких він стосується, а все неперелічене отримує
протилежне поводження. Тому `publish()` і `withhold()` кажуть одне й те саме двома способами, і кожен
із них **замінює** будь-яке попереднє розкриття: оберіть той, що відповідає вашому способу думати, і
викличте його один раз:

```python
.withhold("email", "voice")     # ці два приховано; усе решта за політикою реєстру
.publish("name", "org")         # ці два можна публікувати; усе решта приховано
```

Імена полів — це `name`, `org`, `addr`, `voice`, `fax` та `email`; будь-що інше підіймає
`ValidationException` із переліком цих шести. `name`, `org` і `addr` існують по одному на поштову
форму, і обидві форми називаються за вас — приховати саму лише ASCII-адресу, поки та, що локальним
письмом, лишається публічною, означало б налаштування приватності, яке читається як застосоване, а
насправді ним не є.

---

## ContactUpdateBuilder

`client.contact.update_builder(contact_id)` — надсилає [`contact.update`](contacts.md#update).

Статуси йдуть у власних блоках; кожна зміна поля потрапляє в `chg`.

| Крок | Аргументи | Блок | Що задає |
|---|---|---|---|
| `change_international_address(name=None, city=None, country_code=None, street=None, org=None, state_province=None, postal_code=None)` | усі необов'язкові | `chg` | один блок `postal_infos` типу `int`. **Накопичується** |
| `change_localized_address(…)` | те саме | `chg` | один блок `postal_infos` типу `loc`. **Накопичується** |
| `change_voice(number)` | `str` | `chg` | `chg["voice"]`. Замінює |
| `change_fax(number)` | `str` | `chg` | `chg["fax"]`. Замінює |
| `change_email(email)` | `str` | `chg` | `chg["email"]`. Замінює |
| `change_auth_info(password)` | `str` | `chg` | `chg["auth_info"]` — замінити трансферний код. Замінює |
| `publish(*fields)` | `str…` | `chg` | `chg["disclose"]`, прапорець на публікацію. Замінює |
| `withhold(*fields)` | `str…` | `chg` | `chg["disclose"]`, прапорець на приховування. Замінює |
| `add_status(*statuses)` | `str…` | `add_statuses` | напр. `clientUpdateProhibited`. **Накопичується** |
| `rem_status(*statuses)` | `str…` | `rem_statuses` | зняти клієнтський статус. **Накопичується** |
| `send()` | — | — | надсилає команду, повертає [`Response`](responses.md) |

```python
(client.contact.update_builder("C1")
    .change_email("new-contact@example.com")
    .change_voice("+380.443210000")
    .withhold("email", "voice")
    .add_status("clientUpdateProhibited")
    .send())
```

### Вирішує наявність, а порожній рядок очищає

Усередині адреси аргумент, якого ви не передали, не надсилається взагалі, тож реєстр зберігає те, що
тримає. Аргумент, переданий як `""`, **надсилається** — порожнім, і саме це очищає поле; це єдиний
спосіб прибрати `org`, область чи поштовий індекс:

```python
# Прибрати організацію, решту адреси не чіпати.
(client.contact.update_builder("C1")
    .change_international_address(org="", city="Kyiv", country_code="UA")
    .send())
```

**Указуйте `city` і `country_code`, щойно ви взагалі торкаєтесь адреси.** Елемент `<contact:addr>` є
послідовністю, чиї місто і країну вимагає схема, тож він надсилається цілком або не надсилається
зовсім, — а коли надсилається, місто і країна їдуть разом із ним. Якщо не вказати їх у виклику, який
змінює рядок вулиці, вони підуть порожніми, а порожнє — це свідоме очищення. Команда відповість 1000,
і контакт втратить своє місто та країну.

Зміна однієї поштової форми лишає другу рівно такою, як була.

### Тут немає clear_auth_info()

RFC 5731 дає домену форму трансферного коду, яку можна занулити; RFC 5733 не визначає для контакту
нічого рівнозначного. Тому код контакту можна **замінити**, але не прибрати, і цей білдер не пропонує
кроку, який удавав би протилежне. Порожній пароль не є заміною: порожнє значення — це все ще
значення, яке власник може пред'явити.

---

## HostUpdateBuilder

`client.host.update_builder(name)` — надсилає [`host.update`](hosts.md#update).

| Крок | Аргументи | Блок | Що задає |
|---|---|---|---|
| `add_address(ip)` | `str` | `add` | одна адреса в `add_addresses`; v4 і v6 розрізняються автоматично. **Накопичується** |
| `add_addresses(*ips)` | `str…` | `add` | те саме, кілька за раз. **Накопичується** |
| `rem_address(ip)` | `str` | `rem` | одна адреса в `rem_addresses`. **Накопичується** |
| `rem_addresses(*ips)` | `str…` | `rem` | те саме, кілька за раз. **Накопичується** |
| `add_status(*statuses)` | `str…` | `add` | `add_statuses` — `clientDeleteProhibited`, `clientUpdateProhibited`. **Накопичується** |
| `rem_status(*statuses)` | `str…` | `rem` | `rem_statuses`. **Накопичується** |
| `send()` | — | — | надсилає команду, повертає [`Response`](responses.md) |

```python
# Перевести сервер імен на нову адресу без проміжку: додати нову, зняти стару, разом.
(client.host.update_builder("ns1.example.com.ua")
    .add_addresses("203.0.113.11", "2001:db8::11")
    .rem_address("203.0.113.10")
    .send())
```

Кроку перейменування **немає**, бо немає й самого перейменування: цей реєстр читає лише блоки
додавання та видалення. Створіть хост-заміну, переспрямуйте на нього домени, які ним користуються,
потім видаліть старий — [Хости → Перейменування не існує](hosts.md#перейменування-не-існує) містить
ці три команди.

Видалення останньої адреси підпорядкованого хоста отримує відмову (2003), а не тихо знімає
делегування, а зовнішній хост не може отримати адреси взагалі (2306).

---

## Коли білдер не потрібен

Коли вся команда написана в одному місці, прямий виклик коротший і читається так само:

```python
client.domain.create("example.com.ua", years=1, registrant="C1",
                     nameservers=["ns1.example.com.ua"])
```

Обидві форми підтримуються, і жодна не є кращою. Білдер відпрацьовує своє, коли команда будується по
гілках чи в циклі, коли ви хочете записати її в журнал або поставити в чергу через `to_options()`,
або коли названі кроки оновлення — `add_nameserver`, `rem_status`, `change_registrant` — роблять
дельту зрозумілішою, ніж три вкладені dict.

---

Див. також: [Домени](domains.md) · [Контакти](contacts.md) · [Хости](hosts.md) ·
[Баланс і ціни](balance.md) · [Відповіді](responses.md) · [Помилки](errors.md)

[← Зміст посібника](README.md)
