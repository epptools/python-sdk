# EppTools — EPP SDK for Python

A small, **dependency-free** Python client for **any** EPP domain registry — standard
**RFC 5730–5734** EPP over TLS, conventionally on port 700. It speaks the wire protocol directly
(no framework, no server-side code), so you can drop it into any Python 3.8+ project.
Every command frame is standard, schema-valid EPP.

**Manual:** [English](docs/en/README.md) · [Українською](docs/uk/README.md) · [Русский](docs/ru/README.md) — every command, every builder step and every response accessor, with examples.

- TLS transport with correct RFC 5734 framing (4-byte length prefix, UTF-8 byte-safe).
- Session: `connect` / `login` / `logout`, with the login services taken from the server
  greeting automatically (never rejected for an unsupported service).
- Full object commands: **domain**, **contact**, **host** (check / info / create / update /
  delete / transfer / renew), plus **poll**.
- Extensions: **secDNS** (RFC 5910), **RGP restore** (RFC 3915), **fees** (RFC 8748:
  prices in ``check``, fee agreement on transforms) and **login security** (RFC 8807).
- **Your registry's own extensions, without configuring anything.** No registry's namespaces are
  compiled in: they are read from the `<greeting>` the server sends before you say a word, so this
  works against a registry it has never seen — and keeps working when one changes its URIs. Override
  them in `Config` for a registry whose naming discovery cannot guess.
- Clean `Response` objects (result code, message, availability map, value getters) and typed
  exceptions, and the package ships `py.typed`.

## Install

```bash
pip install epptools
```

Or straight from GitHub, pinned to a release tag, if you would rather not depend on PyPI:

```bash
pip install "epptools @ git+https://github.com/epptools/python-sdk@v1.0.0"
```

No packaging at all? Copy the `epptools/` package folder next to your code and
`import epptools`. The SDK requires only the Python standard library
(`ssl`, `socket`, `xml.etree`).

## Quick start

```python
from epptools import Client, Config
from epptools.exceptions import EppException

client = Client(Config(
    host="epp.registry.example",
    clid="your-clid",
    password="your-secret",
    port=700,                # the EPP convention; some registries differ
    lang="uk",               # result-message language, from the greeting's <lang> list
    # ca_file="/path/to/ca.pem",  # only for a private-CA or self-signed certificate
))

try:
    client.connect()          # TLS + read <greeting>
    client.login()

    avail = client.domain.check(["example.com.ua"]).availability()
    #  => {"example.com.ua": True}

    info = client.domain.info("example.com.ua")
    print(info.value("exDate"))

    client.logout()
except EppException as exc:
    print("EPP error:", exc)
finally:
    client.disconnect()
```

`Client` is also a context manager (`with Client(cfg) as client: ...`) that disconnects on exit.

## TLS notes

| Scenario | Config |
|---|---|
| Public, browser-trusted certificate | nothing — the defaults (`verify_peer=True`, `verify_peer_name=True`) are correct |
| Private-CA or self-signed certificate | `ca_file` → the PEM bundle of the CA that signed the **server** certificate |
| Mutual TLS (the registry requires a client certificate) | `client_cert` + `client_key` (+ `client_key_passphrase` if the key is encrypted) |
| Hostname mismatch (development only) | `verify_peer_name=False` |

**Which of these applies is your registry's choice, so ask them.** Many present an ordinary
browser-trusted certificate, and then there is nothing to configure. Others run their own CA, whose
certificate is in no system trust store: `ca_file` must point at that bundle or the handshake fails
with verification errors.

Authentication is clID + password inside TLS. A client certificate is needed only where the registry
requires mutual TLS, and many additionally restrict access to registered source addresses — that
part is policy, not protocol.

### When the handshake fails

The commonest first-run failure is certificate verification, and it looks like this:

```
ConnectionException: TLS connect failed: certificate verify failed
```

That almost always means `ca_file` is unset or points at the wrong bundle. Check it before anything
else:

```bash
openssl s_client -connect epp.registry.example:700 -CAfile /path/to/registry-ca.pem </dev/null
# "Verify return code: 0 (ok)" means the bundle is right; anything else means it is not.
```

**Do not reach for `verify_peer=False`.** It makes the message go away and leaves you sending your
clID, your password and every transfer secret to whatever answers on that address, with no way to
tell. If the handshake will not verify, the bundle is wrong — ask the registry for the current one.
`verify_peer_name=False` is a narrower loosening (right certificate, wrong hostname) and is
occasionally reasonable in development; `verify_peer=False` is not reasonable anywhere.

## Commands

```python
# Session
client.connect(); client.login(); client.logout(); client.disconnect()
client.login("new-password")          # rotate the EPP password during login
client.hello()                        # re-read the greeting / keep-alive

# Domain
client.domain.check(["example1.com.ua", "example2.com.ua"])
client.domain.info("example1.com.ua", "pw")
client.domain.create("example1.com.ua",
    years=1, registrant="C1", contacts={"admin": "C1", "tech": "C2"},
    nameservers=["ns1.example.net", "ns2.example.net"], auth_info="pw",
    # Or with the glue inlined, where the registry wants the addresses with the name rather
    # than a reference to a host object you created first. A command uses one model or the
    # other — a mixture is a ValidationException here rather than a 2001 from the registry:
    # nameservers=[{"name": "ns1.example.net", "addresses": ["203.0.113.1", "2001:db8::1"]}],
    license="TM-123",                                        # where your registry requires one
    sec_dns={"ds_data": [{"key_tag": 12345, "alg": 8, "digest_type": 2, "digest": "ABCD..."}]})
client.domain.update("example1.com.ua",
    add={"ns": ["ns3.example.net"], "statuses": ["clientHold"]},
    rem={"statuses": ["clientHold"]},
    chg={"registrant": "C9", "auth_info": "newpw"},
    # DNSSEC (RFC 5910): sec_dns={"add": {"ds_data": [...]}, "rem_all": True, "max_sig_life": 1209600}
    # (the RFC camelCase spelling — dsData / remAll / maxSigLife / keyTag — is accepted too;
    #  anything else raises ValidationException instead of silently dropping the DNSSEC block)
)
client.domain.renew("example1.com.ua", "2027-01-15", 1)
client.domain.restore("example1.com.ua")     # RGP restore (op="request")
client.domain.delete("example1.com.ua")
client.domain.transfer("request", "example1.com.ua", "pw", 1)

# Prices (RFC 8748 fee extension) — every fee= below is OPTIONAL. Without it the
# registry's own price is charged. Two independent uses: ASK the price in check();
# CAP what you agree to pay on a transform — if the actual price is HIGHER (tariff
# change, premium name, stale cache) the command is refused (2004) and nothing is
# charged, instead of silently billing you more.
r = client.domain.check(["example1.com.ua"], fee={"create": 1, "renew": 1})
fees = r.fees()   # {"_currency": "UAH", "example1.com.ua": {"commands": {"create": {"fee": "100.00", ...}}}}
# A whole price table in ONE round trip: a LIST of years asks the same operation at each period.
# Up to 20 entries per frame; transfer and restore are one-year operations however many you ask.
table = client.domain.check(["example1.com.ua"], fee={"create": [1, 2, 3, 5, 10]}, currency="UAH")
table.fee_for("example1.com.ua", "create", 5)   # "480.00" — or None with a reason in fees()
client.domain.create("example1.com.ua", years=1, registrant="C1",
                     fee="100.00")   # "I agree to pay up to 100.00" — not a price you set
client.domain.renew("example1.com.ua", "2027-01-15", 1, fee={"amount": "90.00", "currency": "UAH"})
client.domain.restore("example1.com.ua", fee="500.00")

# Contact
client.contact.check(["c1"])
client.contact.info("c1", "pw")
client.contact.create("c1", name="ACME", city="Kyiv", cc="UA", email="contact@example.com", auth_info="pw",
    # postal_infos=[{"type": "int", ...}, {"type": "loc", ...}],   # int + localized
    # disclose={"flag": False, "addr": ["int"], "voice": True},    # RFC 5733 privacy
)
# No naming scheme of your own? Let the registry choose the handle and read it back. Every call
# mints a fresh one, so a repeat is a second contact rather than a 2302 collision.
handle = client.contact.create_auto(
    name="ACME", city="Kyiv", cc="UA", email="contact@example.com").object_name()  # appears HERE and nowhere else
client.contact.update("c1",
    # Inside an address, PRESENCE decides: a field you leave out keeps its value, and a field given
    # as "" is CLEARED — the only way to remove org, sp or pc. The block needs its city and country
    # whenever you touch it, because the schema makes them required.
    chg={"email": "new-contact@example.com",
         "postal_info": {"name": "New Name", "city": "Lviv", "cc": "UA", "org": ""}},
    add_statuses=["clientUpdateProhibited"])
client.contact.delete("c1")
client.contact.transfer("request", "c1", "pw")

# Host
client.host.check(["ns1.example.net"])
client.host.info("ns1.example.net")
client.host.create("ns1.example.net", ["203.0.113.10", "2001:db8::1"])  # v4/v6 auto-detected
client.host.update("ns1.example.net", add_addresses=["203.0.113.11"])
client.host.delete("ns1.example.net")

# Poll & balance
msg = client.poll.request()           # 1301 with a message, 1300 when empty
if msg.message_id() is not None:      # message_count() = how many remain
    msg.queue_message()               # the NOTICE text (<msgQ><msg>) — read this
    msg.queue_message_lang()          # its language: "uk" | "ru" | "en"
    msg.queue_date()                  # when it was queued
    client.poll.ack(msg.message_id()) # ack DESTROYS it at the registry
b = client.balance().balance()        # {"creditLimit": ..., "balance": ..., "availableCredit": ...}
```

## Responses

Every command returns a `Response`:

```python
r.code()            # int EPP result code (1000, 1001, 2303, ...)
r.is_success()      # True for 1xxx
r.is_pending()      # True for 1001 (registry resolves via a poll message)
r.message()         # human-readable <msg>
r.message_lang()    # "en" | "uk" | "ua" | "ru"
r.availability()    # {name: bool} for *:check
r.statuses()        # ["ok"] or ["clientHold", ...]
r.value("exDate")   # first element with that local name
r.values("hostObj") # all elements with that local name (nameservers are <domain:hostObj>)
r.balance()         # {"creditLimit": ..., "balance": ..., "availableCredit": ...} or None
r.prices()          # {"renewal": {"value": ..., "currency": "UAH"}, ...}
r.fees()            # check+fee: per-name RFC 8748 prices (see above), {} when absent
r.charged_fee()     # transform echo: {"currency": "UAH", "fee": "100.00"} or None
r.price_channel()   # domain:info: which price channel those prices belong to, or None
r.license()         # a trademark or licence number, or None
r.rgp_status()      # ["redemptionPeriod"], ...
r.transfer_status() # "pending" | "serverApproved" | ... or None
r.ds_records()      # [{"keyTag":..,"alg":..,"digestType":..,"digest":..}, ...]
r.key_records()     # [{"flags":..,"protocol":..,"alg":..,"pubKey":..}, ...]
r.is_signed()       # bool: any DNSSEC data present
r.message_id()      # poll: id to pass to poll.ack(); message_count() = queue size
r.queue_message()   # poll: the NOTICE text (<msgQ><msg>), NOT the result banner
r.queue_message_lang()  # poll: the notice's language ("uk" | "ru" | "en")
r.queue_date()      # poll: when the notice was queued
r.error_reasons()   # extra <extValue><reason> text on a failed command
r.sv_trid()         # server transaction id
r.raw               # the raw XML
r.root              # the parsed ElementTree root, for anything bespoke
```

### Reading an object without touching XML

The getters above return the frame's shape; these return the answer. Everything an ``info``,
``check`` or ``transfer`` response carries has a named accessor, so you never index into a dict by
a string you had to guess.

```python
# Any object
r.object_name()     # the domain name, the host name or the contact HANDLE
r.roid()            # the registry's own identifier
r.sponsor()         # clID — the registrar it belongs to now
r.created_by()      # crID           r.created_date()  # crDate
r.updated_by()      # upID, or None when never changed    r.updated_date()
r.auth_info()       # <authInfo><pw> — the transfer secret; never log it

# Domain
r.expiry_date()           # exDate, exactly as the registry wrote it (see the note below)
r.registrant()            # the registrant handle
r.contacts()              # {"admin": ["c-1"], "tech": ["c-1", "c-2"]}
r.tech_contacts()         # just that role — also admin_contacts() / billing_contacts()
r.contacts_for("tech")    # any role, matched case-insensitively; [] when nobody holds it
r.all_contacts()          # every handle including the registrant, de-duplicated
r.nameservers()           # names, whether the registry sent hostObj or hostAttr
r.nameserver_addresses()  # hostAttr glue, keyed by nameserver name
r.subordinate_hosts()     # hosts living UNDER this domain — they block a delete
r.transfer()              # {"status","requested_by","requested_at","acting_client","act_by","expiry_date"}
r.transfer_date()         # when it last changed hands, or None
r.registrar_of_record()   # the handle the registry's own WHOIS/RDAP publishes as the registrar
                          # — which for a reseller is not the same party as sponsor()

# Host
r.host_addresses()  # [{"ip": "192.0.2.1", "version": "v4"}, ...]

# Contact
r.postal_info()     # {"int": {...}, "loc": {...}} — name, org, street[], city, sp, pc, cc
r.email()   r.voice()   r.fax()
r.disclose()        # {"flag": False, "elements": ["email", "voice"]} or None

# Check + money
r.is_available("example.com.ua")       # True | False | None ("the answer said nothing")
r.unavailable_reason("taken.com.ua")   # "In use", or None when it is available
r.is_premium("rare.com.ua")            # priced outside the standard list
r.fee_class("rare.com.ua")             # "premium" | "standard" | None
r.credit_limit()   r.current_balance()   r.available_credit()
r.fee_amount()     r.fee_currency()      # what this transform actually charged
r.ext_values()     # per-<extValue>: which ELEMENT the registry rejected, plus the reason
```

Two things worth knowing before you build on these:

- **Dates come back as the registry's own string** (``2027-04-01T09:15:00Z``), never a
  ``datetime``. The registry decides which calendar day a renewal lands on; re-formatting through a
  local timezone is how a client ends up displaying — and renewing against — the day before.
- **Money comes back as an exact decimal string**, never a ``float``. ``0.1 + 0.2`` is not ``0.3``
  in binary floating point, and a balance summed that way drifts. Use ``decimal.Decimal``.


## Building a command step by step

Keyword arguments already give you named parameters and a loud `TypeError` on a misspelling, so
write the direct call when the whole command is in one place. Reach for a builder when it is
assembled in pieces — across branches, in a loop, or from a form:

```python
response = (client.domain.create_builder("your-brand.com.ua")
            .years(1)
            .registrant("acme-01")
            .admin_contact("acme-01")
            .tech_contact("acme-ns1").tech_contact("acme-ns2")   # accumulates
            .nameserver("ns1.acme.example").nameserver("ns2.acme.example")
            # or, where the registry wants the glue inlined instead of a host object:
            # .nameserver_with_glue("ns1.acme.example", "203.0.113.1", "2001:db8::1")
            .auth_info("D0main-Pw")
            .max_fee("180.00", "UAH")     # a cap you consent to, not a price you set
            .send())
```

Available on `domain.create_builder()` / `update_builder()`, `contact.create_builder(id, email)` /
`update_builder()`, and `host.update_builder()`. Same command, same frame, same result — the
builder calls the ordinary method. Three things worth knowing:

- **Every list step accumulates.** `.tech_contact("a").tech_contact("b")` and
  `.tech_contact("a", "b")` are the same thing.
- **Nothing is sent until `send()`.** Until then the builder is an ordinary value you can keep,
  pass around, or inspect with `to_options()` — which returns exactly the keyword arguments the
  direct call takes.
- **A builder sends once.** Sending twice would be two registrations and two charges, so the second
  `send()` is refused.

An update builder names the block each change lands in — `add_nameserver`, `rem_status`,
`change_registrant` — because an EPP update is a delta, and which block a change belongs to is the
whole semantics of the command.

## Reading the message queue

```python
client.poll.drain(lambda notice: store(notice.queue_message(), notice.pending_action_data()))
```

The order matters and is the reason this helper exists: each notice is acknowledged only **after**
your callback returns. An ack deletes the notice at the registry permanently, so a loop that acks
first and processes second loses every notice whose processing fails — a transfer request, the
outcome of a pending create — with nothing left to retry from. If your callback raises, the notice
stays in the queue and the exception reaches you.

## Session security warnings (RFC 8807)

Where the server offers the Login Security extension, the login carries a small block identifying
this client, and the server answers with anything it wants you to fix about the session:

```python
for event in client.login().security_events():
    # type: certificate | cipher | tlsProtocol | password | newPW | stat | custom
    # level: "warning" or "error";  text: a sentence to show an operator
    alert(event["level"], event["type"], event["text"], event.get("exDate"))
```

The list is empty on a healthy session, so treat any entry as something to act on. The commonest
one is a client certificate approaching its expiry date — the alternative to hearing about it here
is finding out on the morning it stops working.

A server sends these only to a client that took part in the extension, because announcing a URI is
not evidence of supporting it. That is why the block goes out even when nothing needs to travel in
it. If you would rather stay off the extension, set `login_security=False` in the config; it is
still used for a password longer than the 16 characters the base `<pw>` element can carry, since
there is nowhere else for that to go.

## Error handling

Every failure extends `EppException`, so one `except` handles everything. Beyond that, a class
exists where the right next step differs — and nowhere else:

| Catch | When | What to do |
|---|---|---|
| `ValidationException` | a value in THIS call is unusable; nothing was sent | fix the arguments |
| `ConfigException` | the client is set up wrong: no host, no credentials | fix the deployment; every call fails until then |
| `ConnectionException` | TLS, timeout, framing | see the TLS notes above; the connection is closed |
| `InsufficientFundsError` | 2104 | **stop the batch**, top up, resume — every later billable command fails the same way |
| `AuthorizationError` | 2201 / 2202 | not yours, or the wrong authInfo |
| `ObjectExistsError` | 2302 | already registered |
| `ObjectDoesNotExistError` | 2303 | stale handle or typo |
| `ObjectStatusError` | 2304 / 2305 | clear the status or association, then repeat |
| `PolicyError` | 2306 / 2308 | the registry's rules refuse this value |
| `SessionError` | 2500–2502 | reconnect and log in again |
| `AuthenticationException` | 2200 | the login itself failed |
| `CommandException` | any other >= 2000 | branch on `.epp_code` |

`ValidationException` and `ConfigException` are also `ValueError`s, so an `except ValueError` you
already have keeps catching them.

```python
from epptools.exceptions import CommandException, InsufficientFundsError, ObjectExistsError

for name in names_to_register:
    try:
        client.domain.create_builder(name).years(1).registrant("acme-01").send()
    except InsufficientFundsError as exc:
        # Not this name's problem — the account's. Carrying on would produce the same failure
        # for every remaining name.
        alert_billing(str(exc))
        break
    except ObjectExistsError as exc:
        taken.append(exc.subject() or name)     # which one the registry objected to
    except CommandException as exc:
        if not exc.is_retryable():              # retrying cannot change the answer
            raise
        retry_later.append(name)
```

`is_retryable()` is true only for failures about the moment rather than the request (2400, and the
2500-family after you reconnect). It is deliberately false for everything else: retrying a 2302
cannot make the name free, and a loop that treats every failure as transient turns one refusal into
a rate-limit ban.

`ResultCode` has named constants for every code, and `throw_on_failure(False)` turns raising off
entirely if you would rather read `response.code()` yourself.

### When a transform fails and you do not know whether it happened

A read timeout, a dropped connection or a `ConnectionException` in the middle of a `create`,
`renew` or `transfer` leaves a genuinely unknown outcome: the registry may have carried the command
out and billed you before the reply was lost. This library cannot tell the difference, and neither
can you from the exception.

**Do not simply retry.** A blind retry is how a domain gets registered — and paid for — twice.
Instead, ask the registry what is true: `domain.info()` for a create, and compare `expiry_date()`
against what you expected for a renew. Reconcile from that, then retry only if the object really is
in the state you started from. A failure whose outcome you cannot determine deserves an operator's
attention, not an automatic second attempt.

## Custom frames

Anything the high-level API doesn't cover can be built with `Frame` and sent raw:

```python
from epptools import Frame, Namespaces

frame = Frame.command("my-trid-1")
check = frame.ns(frame.verb("check"), Namespaces.DOMAIN, "domain:check")
frame.ns(check, Namespaces.DOMAIN, "domain:name", "example3.com.ua")
resp = client.request(frame)          # or client.request(raw_xml_string)
```

## Testing

A no-dependency offline self-test (frame building + response parsing, no server, no network):

```bash
python tests/offline_test.py
```

## Support

Questions about the library, a frame the registry rejected, or a bug: **https://github.com/epptools/python-sdk/issues**.

When reporting a problem, include the **svTRID** from the response (`sv_trid()`) and the clTRID your
client sent — together they identify the exact transaction in the registry's logs, which is what
makes a report answerable without a round trip. Send the frames too if you can, but **redact
`<pw>`, `<newPW>` and `<authInfo>` first**: those are live credentials, and the library masks them
in its own logs for the same reason.

Account, billing and registration questions go to your registry account manager, not here — this
address is for the client libraries.
## License

MIT — see [LICENSE](LICENSE).
