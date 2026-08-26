# Builders

A builder assembles one command a step at a time and sends it when you say so. There are five of
them:

| Builder | From | Sends |
|---|---|---|
| `DomainCreateBuilder` | `client.domain.create_builder(name)` | `domain.create()` |
| `DomainUpdateBuilder` | `client.domain.update_builder(name)` | `domain.update()` |
| `ContactCreateBuilder` | `client.contact.create_builder(contact_id, email)` | `contact.create()` |
| `ContactUpdateBuilder` | `client.contact.update_builder(contact_id)` | `contact.update()` |
| `HostUpdateBuilder` | `client.host.update_builder(name)` | `host.update()` |

A builder builds no XML of its own. `send()` hands the options it has collected to the ordinary
method, so **a builder and the equivalent direct call produce the identical frame** and every check
that applies to one applies to the other.

Keyword arguments already give you named parameters and a loud `TypeError` on a misspelling, so
write the direct call when the whole command is in one place. Reach for a builder when the command
is assembled in pieces — across branches, in a loop, or from a form:

```python
response = (client.domain.create_builder("example.com.ua")
            .years(1)
            .registrant("C1")
            .admin_contact("EXAMPLE-C2")
            .tech_contact("EXAMPLE-C3").tech_contact("EXAMPLE-C4")   # accumulates
            .nameserver("ns1.example.com.ua").nameserver("ns2.example.com.ua")
            .auth_info("D0main-Pw!")
            .max_fee("180.00", "UAH")
            .send())

response.object_name()     # 'example.com.ua'
response.expiry_date()     # store it; renew() has to quote it back
```

## Four rules that hold for every builder

**1. Every step returns the builder**, so calls chain. Nothing else is returned, and there is no
value to keep from a step.

**2. Every list step accumulates.** Passing several arguments at once, calling the step again, or
both, all come to the same thing:

```python
b.tech_contact("EXAMPLE-C3", "EXAMPLE-C4")
b.tech_contact("EXAMPLE-C3").tech_contact("EXAMPLE-C4")   # identical
```

Single-valued steps replace instead: calling `.years()` twice leaves the second value. The tables
below say which each step is.

**3. Nothing is sent until `send()`.** Until then a builder is an ordinary value: keep it, pass it
around, hold it across a branch, inspect it. `to_options()` shows exactly what would go out.

**4. A builder sends once.** A second `send()` raises `ValidationException` and sends nothing:

```python
builder = client.domain.create_builder("example.com.ua").years(1).registrant("C1")
builder.send()
builder.send()
# ValidationException: DomainCreateBuilder has already been sent. A builder carries one command;
# build another rather than re-sending this one.
```

Sending twice would be two registrations and two charges, and the second is never what the caller
meant. Where you really do want the same command again — a second name, a retry after a
reconciliation — build another builder.

## to_options()

```python
builder.to_options() -> Dict[str, Any]
```

Returns the options **exactly as the equivalent direct call takes them**, which makes a builder a
way to describe a command as data:

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

# The same command, written out:
client.domain.create("example.com.ua", **builder.to_options())
```

Two properties worth relying on:

- **It sends nothing and does not spend the builder.** Call it before `send()`, log the result, and
  send afterwards.
- **It is a deep copy.** The dict you get back does not change when another step is added, so what
  you logged and what you sent cannot drift apart. It is safe to store, queue or serialise.

That makes the dry run honest:

```python
options = builder.to_options()
log.info("about to register %s: %r", "example.com.ua", options)
if not requires_approval(options):
    builder.send()
```

---

## DomainCreateBuilder

`client.domain.create_builder(name)` — sends [`domain.create`](domains.md#create). The name is the
constructor argument; everything else is a step.

| Step | Arguments | What it sets |
|---|---|---|
| `years(years)` | `int` | `years` — the registration period, `<domain:period unit="y">`. Replaces. Omit it and the registry applies its own default |
| `registrant(handle)` | `str` | `registrant` — the holder of the domain. Replaces |
| `contact(role, *handles)` | `str`, `str…` | `contacts[role]` — one `<domain:contact type="role">` per handle. **Accumulates** |
| `admin_contact(*handles)` | `str…` | the same, in the `admin` role. **Accumulates** |
| `tech_contact(*handles)` | `str…` | the same, in the `tech` role. **Accumulates** |
| `billing_contact(*handles)` | `str…` | the same, in the `billing` role. **Accumulates** |
| `nameserver(host)` | `str` | one name in `nameservers`, as `<domain:hostObj>`. **Accumulates** |
| `nameservers(*hosts)` | `str…` | the same, several at a time. **Accumulates** |
| `nameserver_with_glue(host, *addresses)` | `str`, `str…` | one `{"name", "addresses"}` entry in `nameservers`, as `<domain:hostAttr>`. **Accumulates** |
| `auth_info(password)` | `str` | `auth_info` — the transfer secret. Replaces |
| `license(number)` | `str` | `license` — a trademark or licence number. Replaces |
| `max_fee(amount, currency=None)` | `str`, `str` | `fee` — the RFC 8748 cap. Replaces |
| `ds_record(key_tag, alg, digest_type, digest)` | `int, int, int, str` | one record in `sec_dns["ds_data"]`. **Accumulates** |
| `ds_record_with_key(key_tag, alg, digest_type, digest, flags, protocol, key_alg, pub_key)` | `int, int, int, str, int, int, int, str` | one DS record carrying the DNSKEY it was computed from. **Accumulates** |
| `key_record(flags, protocol, alg, pub_key)` | `int, int, int, str` | one record in `sec_dns["key_data"]`. **Accumulates** |
| `max_sig_life(seconds)` | `int` | `sec_dns["max_sig_life"]`. Replaces |
| `send()` | — | sends the command, returns the [`Response`](responses.md) |

```python
r = (client.domain.create_builder("example.com.ua")
     .years(2)
     .registrant("C1")
     .admin_contact("EXAMPLE-C2")
     .tech_contact("EXAMPLE-C3", "EXAMPLE-C4")
     .nameserver("ns1.example.com.ua")
     .nameserver("ns2.example.com.ua")
     .auth_info("D0main-Pw!")
     .license("TM-2026-000123")                       # where your registry requires one
     .ds_record(12345, 13, 2, "49FD46E6C4B45C55D4AC")
     .max_sig_life(1209600)
     .max_fee("360.00", "UAH")
     .send())

r.code()            # 1000, or 1001 when the registry queues the registration
r.expiry_date()
r.fee_amount()      # what it actually charged
```

Assembled from a form, which is what the builder is for:

```python
builder = client.domain.create_builder(form["name"]).years(int(form["years"]))
builder.registrant(form["registrant"])

for handle in form.get("tech", []):          # a loop, not an argument list
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

### The two nameserver models

`nameserver()` / `nameservers()` name a **host object** the registry already holds;
`nameserver_with_glue()` inlines the addresses. RFC 5731 makes `<domain:ns>` a choice between the
two, so one command uses one model or the other. Mixing them raises `ValidationException` at
`send()`, before anything reaches the wire — the schema would refuse the frame anyway, as a bare
2001 that names no field.
[Domains → nameservers](domains.md#nameservers-in-both-models) has the detail.

### Steps that refuse a value

A step checks what it can, where the message can still name the argument:

| Step | Refuses |
|---|---|
| `max_fee()` | an amount that is not a plain decimal: `'100,00'`, `'$100'` |
| `ds_record()`, `ds_record_with_key()` | an empty digest |
| `key_record()`, `ds_record_with_key()` | an empty public key |
| `contact()` | an empty role |
| `nameserver_with_glue()` | an empty host name |

All of them raise `ValidationException`, and nothing has been sent — the builder is still usable, so
fix the value and carry on.

---

## DomainUpdateBuilder

`client.domain.update_builder(name)` — sends [`domain.update`](domains.md#update).

An EPP update is a **delta, not a replacement**: what you do not mention is left exactly as it is.
The three blocks are the semantics of the command, and each step name says which block it lands in:

| Block | Means | Steps |
|---|---|---|
| `add` | add this to what is already there | `add_nameserver(s)`, `add_contact`, `add_status` |
| `rem` | take this away | `rem_nameserver(s)`, `rem_contact`, `rem_status` |
| `chg` | replace this single-valued field | `change_registrant`, `change_auth_info`, `clear_auth_info` |

The same nameserver in `add` and in `rem` is two different commands, not a spelling difference, and
there is no step that "sets the nameservers" — the protocol has no such operation.

| Step | Arguments | Block | What it sets |
|---|---|---|---|
| `add_nameserver(host)` | `str` | `add` | one name in `add["ns"]`. **Accumulates** |
| `add_nameservers(*hosts)` | `str…` | `add` | the same, several at a time. **Accumulates** |
| `rem_nameserver(host)` | `str` | `rem` | one name in `rem["ns"]`. **Accumulates** |
| `rem_nameservers(*hosts)` | `str…` | `rem` | the same, several at a time. **Accumulates** |
| `add_contact(role, *handles)` | `str`, `str…` | `add` | `add["contacts"][role]`. **Accumulates** |
| `rem_contact(role, *handles)` | `str`, `str…` | `rem` | `rem["contacts"][role]`. **Accumulates** |
| `add_status(*statuses)` | `str…` | `add` | `add["statuses"]` — a client-side status such as `clientHold`. **Accumulates** |
| `rem_status(*statuses)` | `str…` | `rem` | `rem["statuses"]`. **Accumulates** |
| `change_registrant(handle)` | `str` | `chg` | `chg["registrant"]` — hand the domain to a different holder. Replaces |
| `change_auth_info(password)` | `str` | `chg` | `chg["auth_info"]` — replace the transfer secret. Replaces |
| `clear_auth_info()` | — | `chg` | `chg["clear_auth_info"]` — **remove** the transfer secret entirely |
| `restore()` | — | top level | `restore=True` — the RFC 3915 restore request |
| `license(number)` | `str` | top level | `license` — a trademark or licence number |
| `max_fee(amount, currency=None)` | `str`, `str` | top level | `fee` — the RFC 8748 cap on a billable update |
| `add_ds_record(key_tag, alg, digest_type, digest)` | `int, int, int, str` | `sec_dns["add"]` | one DS record to add. **Accumulates** |
| `rem_ds_record(key_tag, alg, digest_type, digest)` | `int, int, int, str` | `sec_dns["rem"]` | one DS record to remove; every field must match what the registry holds. **Accumulates** |
| `add_key_record(flags, protocol, alg, pub_key)` | `int, int, int, str` | `sec_dns["add"]` | one public key to add. **Accumulates** |
| `rem_key_record(flags, protocol, alg, pub_key)` | `int, int, int, str` | `sec_dns["rem"]` | one public key to remove. **Accumulates** |
| `remove_all_dnssec()` | — | `sec_dns` | `rem_all=True` — unsign the domain entirely |
| `max_sig_life(seconds)` | `int` | `sec_dns` | the signature lifetime. Replaces |
| `send()` | — | — | sends the command, returns the [`Response`](responses.md) |

```python
# Re-delegate and lock, in one command.
(client.domain.update_builder("example.com.ua")
    .add_nameserver("ns3.example.com.ua")
    .rem_nameserver("ns2.example.com.ua")
    .add_status("clientUpdateProhibited")
    .send())

# Roll the DNSSEC key with no window in which the domain is unsigned.
(client.domain.update_builder("example.com.ua")
    .rem_ds_record(12345, 13, 2, "49FD46E6C4B45C55D4AC")
    .add_ds_record(54321, 13, 2, "A1B2C3D4E5F60718293A")
    .send())

# Bring a domain back from redemption, capping what the restore may cost.
(client.domain.update_builder("example.com.ua")
    .restore()
    .max_fee("1200.00", "UAH")
    .send())
```

Add before you remove, in the same command, whenever you are replacing something: both blocks are
applied as one change, so the domain is never left with no nameservers in between.

### clear_auth_info() is not an empty password

`change_auth_info("")` would store the empty string, and an empty string is a value the holder can
still present — the domain stays exactly as movable as it was. `clear_auth_info()` sends
`<domain:authInfo><domain:null/>`, which removes the code. That is the step to reach for after a
leak; set a fresh one with `change_auth_info()` when the customer needs one again.

The schema cannot express both at once, so setting and clearing in one command raises
`ValidationException` rather than silently applying one of them.

### Removing specific records, or all of them

`remove_all_dnssec()` and `rem_ds_record()` / `rem_key_record()` are mutually exclusive: the
protocol has no way to express both, and a frame carrying both is refused. The builder refuses it
first, in either order, so the message can say what to do:

```python
(client.domain.update_builder("example.com.ua")
    .rem_ds_record(12345, 13, 2, "49FD46E6C4B45C55D4AC")
    .remove_all_dnssec())
# ValidationException: remove_all_dnssec() cannot be combined with
# rem_ds_record()/rem_key_record() — remove everything, or name what to remove, not both
```

Removing everything and adding a new set in the same command is fine, and is how you replace a whole
key set: `remove_all_dnssec()` with `add_ds_record()`.

---

## ContactCreateBuilder

`client.contact.create_builder(contact_id, email)` — sends
[`contact.create`](contacts.md#create).

The id and the e-mail are constructor arguments rather than steps, because the registry requires
both: a builder that lets you forget a mandatory field has moved the error from your editor to the
wire. Pass `Contact.AUTO_ID` as the id to have the registry mint the handle, and read it back with
`object_name()`.

| Step | Arguments | What it sets |
|---|---|---|
| `international_address(name, city, country_code, street=(), org=None, state_province=None, postal_code=None)` | `str, str, str, Sequence[str], str, str, str` | one `postal_infos` block of type `int` — ASCII. **Accumulates** |
| `localized_address(name, city, country_code, street=(), org=None, state_province=None, postal_code=None)` | the same | one `postal_infos` block of type `loc` — the local script. **Accumulates** |
| `voice(number)` | `str` | `voice`, in the EPP form `+CC.NNNNNNNNN`. Replaces |
| `fax(number)` | `str` | `fax`, same form. Replaces |
| `auth_info(password)` | `str` | `auth_info` — the contact's transfer secret. Replaces |
| `publish(*fields)` | `str…` | `disclose` with the flag set to publish. Replaces |
| `withhold(*fields)` | `str…` | `disclose` with the flag set to withhold. Replaces |
| `send()` | — | sends the command, returns the [`Response`](responses.md) |

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

At least one address form is required. Give the international one unless you have a reason not to:
it is the form that survives being printed, e-mailed and read by a system that knows no Cyrillic.
The localized form is additional, not an alternative — a contact may carry both, and
`postal_info()` returns whichever it holds.

Let the registry mint the handle when you have no naming scheme of your own:

```python
from epptools import Contact

handle = (client.contact.create_builder(Contact.AUTO_ID, "contact@example.com")
          .international_address("Ivan Petrenko", "Kyiv", "UA")
          .send()
          .object_name())        # 'c-9f4b2ad10e' — appears here and nowhere else
```

### publish() and withhold()

RFC 5733 disclosure is a flag plus the elements it applies to, and everything not listed takes the
opposite treatment. `publish()` and `withhold()` therefore say the same thing two ways, and each one
**replaces** any previous disclosure — pick the one that matches how you think about it and call it
once:

```python
.withhold("email", "voice")     # these two are withheld; everything else follows registry policy
.publish("name", "org")         # these two may be published; everything else is withheld
```

The field names are `name`, `org`, `addr`, `voice`, `fax` and `email`; anything else raises
`ValidationException` naming the six. `name`, `org` and `addr` exist once per postal form, and both
forms are named for you — withholding only the ASCII address while the local-script one stayed
public would be a privacy setting that reads as applied and is not.

---

## ContactUpdateBuilder

`client.contact.update_builder(contact_id)` — sends [`contact.update`](contacts.md#update).

Statuses go in their own blocks; every field change lands in `chg`.

| Step | Arguments | Block | What it sets |
|---|---|---|---|
| `change_international_address(name=None, city=None, country_code=None, street=None, org=None, state_province=None, postal_code=None)` | all optional | `chg` | one `postal_infos` block of type `int`. **Accumulates** |
| `change_localized_address(…)` | the same | `chg` | one `postal_infos` block of type `loc`. **Accumulates** |
| `change_voice(number)` | `str` | `chg` | `chg["voice"]`. Replaces |
| `change_fax(number)` | `str` | `chg` | `chg["fax"]`. Replaces |
| `change_email(email)` | `str` | `chg` | `chg["email"]`. Replaces |
| `change_auth_info(password)` | `str` | `chg` | `chg["auth_info"]` — replace the transfer secret. Replaces |
| `publish(*fields)` | `str…` | `chg` | `chg["disclose"]`, flag set to publish. Replaces |
| `withhold(*fields)` | `str…` | `chg` | `chg["disclose"]`, flag set to withhold. Replaces |
| `add_status(*statuses)` | `str…` | `add_statuses` | e.g. `clientUpdateProhibited`. **Accumulates** |
| `rem_status(*statuses)` | `str…` | `rem_statuses` | clear a client-side status. **Accumulates** |
| `send()` | — | — | sends the command, returns the [`Response`](responses.md) |

```python
(client.contact.update_builder("C1")
    .change_email("new-contact@example.com")
    .change_voice("+380.443210000")
    .withhold("email", "voice")
    .add_status("clientUpdateProhibited")
    .send())
```

### An address is REPLACED, not merged

The block you pass **replaces** the one the registry holds. It is not merged field by field, so an
argument you do not pass is not sent — and the registry deletes what it held. An argument passed as
`""` is sent empty, which is what clears a field.

RFC 5733 can be read as "leave it out and the registry keeps what it holds", since every child of
`chgPostalInfoType` is optional, but that reading is not safe. Against a registry that replaces —
**every command answering 1000** — a block sent without its `org` comes back with the organisation
gone, and a block carrying only an `org` leaves the contact with no postal address at all: name,
street, city, postal code and country.

`name`, `city` and `country_code` are required in every address change for that reason, and the
builder refuses the call without them. They keep the frame valid; they cannot restore an argument you
did not pass. **Read the block first and pass it back with your change applied:**

```python
current = client.contact.info("C1").postal_info()["int"]

# Remove the organisation, keeping the rest of the address exactly as it was.
(client.contact.update_builder("C1")
    .change_international_address(name=current["name"], city=current["city"],
                                  country_code=current["cc"], street=current.get("street"),
                                  org="")
    .send())
```

The form you do not mention — local or international — is untouched: the two are addressed
separately.

Changing one postal form leaves the other exactly as it was.

### There is no clear_auth_info() here

RFC 5731 gives a domain a nullable form for its transfer secret; RFC 5733 defines no equivalent for
a contact. So a contact's code can be **replaced** but not removed, and this builder offers no step
that pretends otherwise. An empty password is not a substitute: an empty value is still a value the
holder can present.

---

## HostUpdateBuilder

`client.host.update_builder(name)` — sends [`host.update`](hosts.md#update).

| Step | Arguments | Block | What it sets |
|---|---|---|---|
| `add_address(ip)` | `str` | `add` | one address in `add_addresses`; v4 and v6 are told apart automatically. **Accumulates** |
| `add_addresses(*ips)` | `str…` | `add` | the same, several at a time. **Accumulates** |
| `rem_address(ip)` | `str` | `rem` | one address in `rem_addresses`. **Accumulates** |
| `rem_addresses(*ips)` | `str…` | `rem` | the same, several at a time. **Accumulates** |
| `add_status(*statuses)` | `str…` | `add` | `add_statuses` — `clientDeleteProhibited`, `clientUpdateProhibited`. **Accumulates** |
| `rem_status(*statuses)` | `str…` | `rem` | `rem_statuses`. **Accumulates** |
| `send()` | — | — | sends the command, returns the [`Response`](responses.md) |

```python
# Move a nameserver to a new address without a gap: add the new one, drop the old one, together.
(client.host.update_builder("ns1.example.com.ua")
    .add_addresses("203.0.113.11", "2001:db8::11")
    .rem_address("203.0.113.10")
    .send())
```

There is **no rename step**, because there is no rename: this registry reads only the add and remove
blocks. Create the replacement host, re-point the domains that use it, then delete the old one —
[Hosts → There is no rename](hosts.md#there-is-no-rename) has the three commands.

Removing a subordinate host's last address is refused (2003) rather than quietly undelegating it,
and an external host may not gain addresses at all (2306).

---

## When not to use a builder

When the whole command is written in one place, the direct call is shorter and reads the same:

```python
client.domain.create("example.com.ua", years=1, registrant="C1",
                     nameservers=["ns1.example.com.ua"])
```

Both forms are supported and neither is preferred. The builder earns its keep when the command is
built across branches or in a loop, when you want `to_options()` to log or queue it, or when the
named steps of an update — `add_nameserver`, `rem_status`, `change_registrant` — make the delta
plainer to read than three nested dicts.

---

See also: [Domains](domains.md) · [Contacts](contacts.md) · [Hosts](hosts.md) ·
[Balance and prices](balance.md) · [Responses](responses.md) · [Errors](errors.md)

[← Manual index](README.md)
