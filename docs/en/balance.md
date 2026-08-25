# Balance and prices

Two things live on this page, and they answer the two money questions an integration has: **what
can I spend**, and **what will this cost**.

The first is `client.balance()`, the registry's own account query. The second is the **RFC 8748 fee
extension**, which rides on the commands you were sending anyway: a `check` can ask a price, and a
`create`, `renew`, `transfer` or `restore` can carry a cap on what you consent to pay.

Every amount in this manual is illustrative. The registry's tariff is the registry's to publish.

## Money is a string

**Every figure on this page comes back as an exact decimal string, never a `float`.** `0.1 + 0.2` is
not `0.3` in binary floating point, and a balance summed or compared that way drifts — quietly, and
in the direction nobody notices until a reconciliation. Keep the string for storage and use
`decimal.Decimal` for arithmetic:

```python
from decimal import Decimal

spendable = Decimal(client.balance().available_credit() or "0")
if spendable < Decimal("500.00"):
    stop_the_batch()
```

---

## The balance command

```python
client.balance() -> Response
```

Sends an `<info>` command in the registry's own balance namespace, which is read from the
`<greeting>` — see [`client.registry_balance_uri()`](commands.md#your-registrys-own-extensions). It
is not billable, it changes nothing, and it is the safe command to run on a schedule.

```python
money = client.balance()

money.balance()            # {'creditLimit': '1000.00', 'balance': '250.50',
                           #  'availableCredit': '1250.50'}
money.credit_limit()       # '1000.00'
money.current_balance()    # '250.50'
money.available_credit()   # '1250.50'
```

| Accessor | Returns | When the answer carries nothing |
|---|---|---|
| `balance() -> Optional[Dict[str, str]]` | All three figures at once, keyed `creditLimit`, `balance`, `availableCredit` | `None` when this is not a balance response |
| `credit_limit() -> Optional[str]` | The credit the registry extends **beyond** a zero balance | `None` |
| `current_balance() -> Optional[str]` | The funds on the account right now | `None` |
| `available_credit() -> Optional[str]` | What you can actually spend — the balance plus the credit still unused | `None` |

The three are not interchangeable, and the one to gate a batch on is the third:

- `current_balance()` can be zero while you are still able to register domains, because the credit
  limit is still there.
- `credit_limit()` is a ceiling, not money. It does not fall as you spend.
- `available_credit()` is the number that reaches zero at the moment the next billable command
  starts failing with 2104.

`balance()` returns `None` on any response that is not a balance reply, so a stray call against the
wrong response gives you `None` rather than a wrong number.

| Code | Meaning |
|---|---|
| 1000 | answered |
| 2103 | this endpoint does not serve the balance extension |

A balance query is not part of any RFC, so a registry may not offer one — and the client knows that
before it sends anything, from the greeting. `balance()` raises `ConfigException` rather than sending
a frame the server would ignore, so you can also just ask:

```python
client.connect()
if client.registry_balance_uri() is None:
    ...                     # no account query here; ask the registry for one
```

### Watching it

Read the balance before a batch, not after it fails. A 2104 mid-run raises
[`InsufficientFundsError`](errors.md#the-exception-hierarchy) and every later billable command in
that run fails the same way, so the loop grinds through its queue producing identical failures
unless you stop it.

The registry also warns you before the account runs dry, and that warning arrives as a
[poll notice](poll.md#a-low-balance-warning). Draining the queue is therefore part of billing, not
only of provisioning.

---

## Where a price comes from

Three different answers to three different questions:

| Question | How you ask | What you read |
|---|---|---|
| What would this name cost me? | `domain.check(names, fee={...})` | `fees()`, `fee_for()` |
| What does a domain I already hold renew at? | `domain.info(name)` | `prices()`, `price_channel()` |
| What did that command charge? | any transform | `charged_fee()`, `fee_amount()` |

The first is RFC 8748 and is the bulk of this page. The extension is optional on both sides: without
a `fee=` argument, nothing changes and the registry charges its own price.

---

## Asking a price on check

```python
client.domain.check(names: List[str],
                    fee: Optional[Dict[str, Any]] = None,
                    currency: Optional[str] = None) -> Response
```

`fee` maps an **operation** to the **number of years** to price it at. It adds a `<fee:check>` rider
in `<extension>`, so availability and price arrive in one round trip:

```python
r = client.domain.check(["example.com.ua"], fee={"create": 1, "renew": 1})

r.is_available("example.com.ua")                 # True
r.fee_for("example.com.ua", "create", 1)         # '100.00'
r.fee_for("example.com.ua", "renew", 1)          # '90.00'
r.fees()["_currency"]                            # 'UAH'
```

The operations you may name are `create`, `renew`, `transfer`, `restore`, `update` and `delete` —
one `<fee:command name="…">` each, carrying a `<fee:period unit="y">`.

A period below one year is not expressible: the schema's period type starts at 1, and a `0` you pass
is sent as `1` rather than as a frame the registry refuses.

The rest of `check` — the ten-names-per-command limit, `availability()`, `is_available()` returning
`None` — is on [Domains → check](domains.md#check).

### A whole price table in one command

A **list** of years asks the same operation at each period, so a five-row price table costs one round
trip instead of five:

```python
table = client.domain.check(["example.com.ua"],
                            fee={"create": [1, 2, 3, 5, 10], "renew": [1, 2]},
                            currency="UAH")

table.fee_for("example.com.ua", "create", 5)     # '480.00'
table.fee_for("example.com.ua", "create", 10)    # '940.00'
table.fee_for("example.com.ua", "renew", 2)      # '175.00'
```

**A frame carries at most 20 fee entries.** Entries are counted across every operation, so the
example above uses seven of them: five create periods and two renew periods.

Over twenty, the library raises `ValidationException` and sends nothing:

```python
client.domain.check(["example.com.ua"], fee={"create": list(range(1, 22))})
# ValidationException: a fee query carries at most 20 entries; this one has 21
```

Refusing here rather than on the wire is the difference between a message that names the limit and a
2306 that names nothing. The limit is `MAX_FEE_COMMANDS` in `epptools.commands` if you would rather
batch against the constant than against the number.

### Transfer and restore are one-year operations

Say it plainly, because asking otherwise wastes entries and misreads the answer:

> **`transfer` and `restore` are priced for one year, however many years you ask for.** The reply
> echoes the period that was actually priced, which is one.

```python
r = client.domain.check(["example.com.ua"], fee={"transfer": [1, 2, 5]})

r.fee_for("example.com.ua", "transfer", 1)   # '180.00' — the answer
r.fee_for("example.com.ua", "transfer", 5)   # None — nothing was priced at five years
```

Ask for those two at one year, and read them back at one year. `fee_for()` matches on the period in
the *reply*, so a lookup at a period the registry did not quote returns `None` rather than a figure
from a neighbouring row.

On the Reglament zones a transfer also carries a mandatory one-year renewal, which is a separate
matter from the fee period — see [Domains → transfer](domains.md#transfer).

### Naming a currency

`currency` asks for the quote in a currency you name. It goes out upper-cased, in `<fee:currency>`:

```python
r = client.domain.check(["example.com.ua"], fee={"create": 1}, currency="UAH")
r.fees()["_currency"]        # 'UAH'
```

Omit it and you get the registry's own. A currency the registry does **not** price in comes back as
an unavailable entry with a reason — never as a converted guess, because a conversion the registry
did not make is a number nobody will honour:

```python
r = client.domain.check(["example.com.ua"], fee={"create": 1}, currency="XXX")
entry = r.fees()["example.com.ua"]
entry["avail"]      # False
entry["reason"]     # 'Currency not supported'
```

Pass `currency` together with `fee`. On its own there is nothing for the registry to price.

---

## Reading the answer

`fees()` returns the whole table, keyed by name, plus a `_currency` key:

```python
r.fees()
# {'_currency': 'UAH',
#  'example.com.ua': {
#      'avail': True,
#      'reason': None,
#      'class': 'premium',                      # present only when the registry declared one
#      'commands': {'create': {'years': 1, 'fee': '100.00'},
#                   'renew':  {'years': 1, 'fee': '90.00'}},
#      'periods': [{'op': 'create', 'years': 1,  'fee': '100.00'},
#                  {'op': 'create', 'years': 5,  'fee': '480.00'},
#                  {'op': 'create', 'years': 10, 'fee': '940.00'},
#                  {'op': 'renew',  'years': 1,  'fee': '90.00'}]}}
```

| Key | What it holds |
|---|---|
| `_currency` | The currency every quote in the table is in |
| `avail` | Whether this name could be priced at all; `False` comes with a `reason` |
| `reason` | Why not: the zone is not served, the currency is not priced in, the operation is not offered |
| `class` | The registry's fee class, present only when it declared one |
| `commands` | One entry per operation — the **first** period asked for |
| `periods` | Every quote, in the order the reply carried them |

`commands` is keyed by operation alone, so it holds one entry per operation however many periods you
asked about. `periods` holds them all. When you asked for several periods, read `periods` — or let
`fee_for()` pick one out:

| Accessor | Returns | When the answer carries nothing |
|---|---|---|
| `fees() -> Dict[str, object]` | The table above | `{}` when the reply carried no fee data |
| `fee_for(name, operation, years=1) -> Optional[str]` | One quote, as an exact decimal string | `None` when nothing was quoted for that combination |
| `fee_class(name=None) -> Optional[str]` | `'premium'`, `'standard'` … | `None` when the answer declared no class |
| `is_premium(name=None) -> bool` | Whether the name is priced outside the standard list | `False` |

```python
r = client.domain.check(["rare.com.ua"], fee={"create": 1})

if r.is_premium("rare.com.ua"):
    price = r.fee_for("rare.com.ua", "create", 1)
    require_operator_approval("rare.com.ua", price, r.fee_class("rare.com.ua"))
```

**`is_premium()` returning `False` is not a promise of the standard price.** It means the answer
declared no special class. Charge from `fees()`, and cap the transform itself — which is the next
section.

An unavailable name is a normal 1000 with `avail: False`, not an error. A fee entry for a name the
registry will not price is the same: normal, answered, and carrying its reason.

---

## Capping what you agree to pay

Every transform that can be billed takes an optional `fee` argument. It is **not a price you set**.
The registry charges its own price; the agreement is the most you consent to pay:

> If the real price is **higher** than what you agreed to, the command is refused with **2004** and
> **nothing is charged**.

That is the whole point of sending one. A tariff change, a premium name, a quote your cache is a day
late on — any of those bill you the difference in silence if you send no agreement, and refuse the
command outright if you do.

```python
client.domain.create("example.com.ua", years=1, registrant="C1", fee="100.00")
client.domain.renew("example.com.ua", "2027-04-01", 1,
                    fee={"amount": "90.00", "currency": "UAH"})
client.domain.transfer("request", "example.com.ua", "the-code", 1, fee="180.00")
client.domain.restore("example.com.ua", fee="1200.00")
client.domain.update("example.com.ua", chg={"registrant": "EXAMPLE-C9"}, fee="50.00")
```

| Form | Meaning |
|---|---|
| `fee="100.00"` | up to 100.00 in the registry's own currency |
| `fee={"amount": "100.00", "currency": "UAH"}` | up to 100.00, and in that currency |

| Command | The element the agreement travels in |
|---|---|
| `domain.create` | `<fee:create>` |
| `domain.renew` | `<fee:renew>` |
| `domain.transfer` | `<fee:transfer>` |
| `domain.update` | `<fee:update>` |
| `domain.restore` | `<fee:update>` — a restore is a `domain:update` on the wire (RFC 3915) |

The amount must be a plain decimal — digits, optionally a point and one or two more digits.
`'100,00'`, `'$100'` and `'1 000.00'` raise `ValidationException` before anything is sent, because
the alternative is a bare 2001 that names no field and arrives after the command was attempted:

```python
client.domain.create("example.com.ua", years=1, registrant="C1", fee="100,00")
# ValidationException: fee amount must be a plain decimal like '100.00' (got '100,00')
```

`fee="0"` is a legitimate agreement — "this operation is free" — and is sent as such.

The [builders](builders.md) carry the same thing under a name that says what it is:

```python
(client.domain.create_builder("example.com.ua")
    .years(1)
    .registrant("C1")
    .max_fee("180.00", "UAH")            # a cap you consent to, not a price you set
    .send())
```

### What a refusal at 2004 means

2004 on a transform carrying a fee agreement means: **the registry's price is higher than the figure
you sent, so it did nothing.** The domain was not registered, the renewal did not happen, and no
money moved. It is a safe failure, and the right response is to find out the real price and decide,
not to remove the cap and resend:

```python
from epptools.exceptions import CommandException

try:
    client.domain.create("example.com.ua", years=1, registrant="C1", fee="100.00")
except CommandException as exc:
    if exc.epp_code != 2004:
        raise
    quote = client.domain.check(["example.com.ua"], fee={"create": 1})
    price = quote.fee_for("example.com.ua", "create", 1)
    if approved_by_operator("example.com.ua", price):
        client.domain.create("example.com.ua", years=1,
                             registrant="C1", fee=price)
```

2004 is also the answer when the period is out of range, so read the message and
`exc.reasons()` rather than assuming the fee was the reason.

Note the shape of that flow: the cap is re-set from a **fresh quote**, and only after somebody
decided the new price is acceptable. Retrying with the cap removed defeats the mechanism entirely —
it is the same as never having sent one.

---

## What a transform actually charged

A successful transform that carried a fee agreement echoes what it charged. Read it, and store it
against the object and the svTRID:

```python
r = client.domain.renew("example.com.ua", "2027-04-01", 1, fee="180.00")

r.fee_amount()      # '180.00'  — what was actually charged
r.fee_currency()    # 'UAH'
r.charged_fee()     # {'currency': 'UAH', 'fee': '180.00'}
r.expiry_date()     # the new expiry
r.sv_trid()         # the registry's id for this operation
```

| Accessor | Returns | When the answer carries nothing |
|---|---|---|
| `charged_fee() -> Optional[Dict[str, str]]` | `{'currency': …, 'fee': …}` | `None` |
| `fee_amount() -> Optional[str]` | The amount alone | `None` |
| `fee_currency() -> Optional[str]` | The currency alone | `None` |

`None` here is not "it was free": a registry that does not echo the extension answers `None` while
still having charged you. Your own record of what a command was expected to cost, plus the account
balance, is what reconciles a period — the echo is the confirmation, not the ledger.

---

## What a domain you already hold renews at

A `domain:info` may carry the registry's own price hints for that specific domain:

```python
info = client.domain.info("example.com.ua")

info.prices()          # {'renewal': {'value': '180.00', 'currency': 'UAH'}, …}
info.price_channel()   # '7' — which row of the published catalogue these come from
```

This is per **domain**, not per zone: a name registered years ago can sit on a different price
channel from the one a new registration in the same zone would use, and `price_channel()` is the
opaque id that matches it to a catalogue row. `prices()` is `{}` when the reply carried none.

---

## Quote, cap, register, reconcile

```python
from decimal import Decimal

from epptools import Client, Config
from epptools.exceptions import CommandException, InsufficientFundsError

name = "example.com.ua"

client = Client(Config(host="epp.registry.example", clid="EXAMPLE",
                       password="your-secret", ca_file="/etc/ssl/registry-ca.pem"))
client.connect()
client.login()

# 1. Can we afford anything at all?
if Decimal(client.balance().available_credit() or "0") < Decimal("500.00"):
    raise SystemExit("top up before running the batch")

# 2. Availability and price, one round trip.
quote = client.domain.check([name], fee={"create": [1, 2]}, currency="UAH")
if quote.is_available(name) is not True:
    raise SystemExit("%s: %s" % (name, quote.unavailable_reason(name) or "no answer"))

price = quote.fee_for(name, "create", 1)
if price is None:
    raise SystemExit("the registry quoted no create price for %s" % name)

# 3. Register, agreeing to exactly what was quoted and no more.
try:
    created = client.domain.create(name, years=1, registrant="C1", fee=price)
except InsufficientFundsError:
    raise SystemExit("out of credit — stop the batch, top up, resume")
except CommandException as exc:
    if exc.epp_code == 2004:
        raise SystemExit("price moved since the quote; re-quote before retrying")
    raise

# 4. Reconcile against what was quoted.
charged = created.fee_amount()
if charged is not None and Decimal(charged) != Decimal(price):
    alert_billing(name, quoted=price, charged=charged, sv_trid=created.sv_trid())

client.logout()
client.disconnect()
```

The 2004 branch is the one worth keeping: it is the mechanism working. Nothing was registered and
nothing was billed, and the decision about the new price belongs to a person or to a rule, not to a
retry.

---

## Result codes

| Code | Where | Meaning |
|---|---|---|
| 1000 | `balance()`, `check` | answered |
| 2004 | a transform | the agreed fee does not cover the price — **nothing was charged** — or the period is out of range |
| 2004 | `check` | a fee rider asked for an operation the registry does not price |
| 2103 | any | this endpoint does not serve the extension you used |
| 2104 | a transform | insufficient funds — raised as `InsufficientFundsError`; stop the batch |
| 2306 | `check` | more than 20 fee entries in one command |
| 2307 | `check` | the zone is not served |

---

See also: [Domains](domains.md) · [Poll](poll.md) · [Responses](responses.md) ·
[Builders](builders.md) · [Errors](errors.md)

[Back to the index](README.md)
