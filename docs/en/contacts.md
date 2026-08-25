# Contacts

Everything under `client.contact`. Contact objects follow **RFC 5733**, and every method here maps
to one EPP command on the wire.

Contacts come first in any provisioning flow: a domain references handles that must already exist,
so the usual order is create the registrant and the role contacts, then
[create the domain](domains.md#create) that points at them.

Each method returns a [`Response`](responses.md), and a result code of 2000 or higher is raised as
an exception — see [Errors](errors.md).

## The methods

| Method | EPP command |
|---|---|
| `check` | `<check><contact:check>` |
| `info` | `<info><contact:info>` |
| `create` | `<create><contact:create>` |
| `create_auto` | the same, with the reserved id that has the registry mint the handle |
| `update` | `<update><contact:update>` |
| `delete` | `<delete><contact:delete>` |
| `transfer` | `<transfer op="…"><contact:transfer>` |

`create_builder(id, email)` and `update_builder(id)` assemble the same commands step by step; see
[Builders](builders.md).

---

## check

```python
client.contact.check(ids: List[str]) -> Response
```

Asks whether contact ids are free. One `<contact:id>` per id, **at most 10 per command** — an
eleventh is refused with 2001.

```python
r = client.contact.check(["C1", "EXAMPLE-C2"])

r.availability()                    # {'C1': False, 'EXAMPLE-C2': True}
r.is_available("EXAMPLE-C2")       # True
r.unavailable_reason("C1") # 'in use', or None
```

`is_available()` returns `None` when the reply said nothing about that id — distinct from "taken",
and worth distinguishing before you build a handle around the answer.

Checking is only worth the round trip if you mint your own handles. If you do not,
[`create_auto()`](#create_auto) removes the question entirely.

| Code | Meaning |
|---|---|
| 1000 | answered; read `availability()` |
| 2001 | more than 10 ids in one command |

---

## info

```python
client.contact.info(contact_id: str, auth_info: Optional[str] = None) -> Response
```

Reads a contact. As the sponsor you see the full record; as a non-sponsor you see the public subset,
or the full record if you pass the contact's `auth_info`. A *wrong* code is 2202; no code at all is
not an error.

```python
c = client.contact.info("C1")

c.object_name()     # 'C1' — the HANDLE, not the person's name
c.roid()            # the registry's own object id
c.email()           # 'contact@example.com'
c.voice()           # '+380.441234567'
c.fax()             # or None
c.statuses()        # ['linked'] once a domain references it
c.sponsor()         # clID
c.created_by()      # crID          c.created_date()   # crDate
c.updated_by()      # upID, or None c.updated_date()   # upDate, or None
c.auth_info()       # the transfer secret — never log it
c.disclose()        # {'flag': False, 'elements': ['email', 'voice']} or None

postal = c.postal_info()
postal["int"]["name"]     # 'Ivan Petrenko'          — ASCII form
postal["int"]["street"]   # ['vul. Khreshchatyk 1']  — a list, up to 3 lines
postal["loc"]["city"]     # 'Київ'                   — local-script form, when present
```

`object_name()` is the handle. That distinction matters: a document-wide search for a `<name>`
element in a contact reply finds the *person's* name first, and feeding that back as an id is a
2303 with a confusing message.

| Code | Meaning |
|---|---|
| 1000 | answered |
| 2202 | you are not the sponsor and the `auth_info` you supplied is wrong |
| 2303 | no such contact |

---

## create

```python
client.contact.create(contact_id: str, *,
                      name: Optional[str] = None,
                      org: Optional[str] = None,
                      street: Optional[List[str]] = None,
                      city: Optional[str] = None,
                      sp: Optional[str] = None,
                      pc: Optional[str] = None,
                      cc: Optional[str] = None,
                      type: str = "int",
                      postal_infos: Optional[List[Dict[str, Any]]] = None,
                      voice: Optional[str] = None,
                      fax: Optional[str] = None,
                      email: Optional[str] = None,
                      auth_info: Optional[str] = None,
                      disclose: Optional[Dict[str, Any]] = None) -> Response
```

Creates a contact. Not billable.

The single-address form takes the address fields directly, which is the short way to write the
common case:

```python
r = client.contact.create(
    "C1",
    name="Ivan Petrenko",
    org="Pryklad LLC",
    street=["vul. Khreshchatyk 1"],
    city="Kyiv",
    pc="01001",
    cc="UA",
    voice="+380.441234567",
    email="contact@example.com",
    auth_info="C0ntact-Pw!",
)

r.object_name()    # 'C1'
r.created_date()   # crDate
```

| Option | Goes on the wire as |
|---|---|
| `name`, `org`, `street`, `city`, `sp`, `pc`, `cc`, `type` | one `<contact:postalInfo type="…">` block |
| `postal_infos` | several such blocks — see below |
| `voice`, `fax` | `<contact:voice>` / `<contact:fax>`, in the EPP form `+CC.NNNNNNNNN` |
| `email` | `<contact:email>` — **required** |
| `auth_info` | `<contact:authInfo><contact:pw>` |
| `disclose` | `<contact:disclose flag="0\|1">` (RFC 5733 privacy) |

`email` is checked before anything is sent: an empty or missing one raises `ValidationException`,
because RFC 5733 requires it and the registry would refuse the frame anyway, with a message that
takes longer to read than this one.

`<contact:authInfo>` always goes out. Pass a code and it becomes the contact's transfer secret;
omit it and an empty `<contact:pw/>` is sent.

The registry requires the id to be 3–16 characters of letters, digits and `-`; anything else is
2005.

### Both postal forms

A contact carries one or two `<contact:postalInfo>` blocks, and which you send is a real decision
rather than a formality:

| `type` | Contents | Notes |
|---|---|---|
| `"int"` | **ASCII / Latin only** | Cyrillic here is refused with 2005. This is the form the registry can show to any party, so at least one ASCII form is needed |
| `"loc"` | the local script — Cyrillic for a Ukrainian registrant | optional, and additional |

Send both when you have both. Nothing is discarded, and `contact.info()` returns everything you
sent. Use `postal_infos` for that:

```python
client.contact.create(
    "C1",
    postal_infos=[
        {"type": "int", "name": "Ivan Petrenko", "org": "Pryklad LLC",
         "street": ["vul. Khreshchatyk 1"], "city": "Kyiv", "pc": "01001", "cc": "UA"},
        {"type": "loc", "name": "Іван Петренко", "org": "ТОВ «Приклад»",
         "street": ["вул. Хрещатик 1"], "city": "Київ", "pc": "01001", "cc": "UA"},
    ],
    voice="+380.441234567",
    email="contact@example.com",
)
```

**`postal_infos` replaces the single-address arguments.** When you pass it, `name`, `city`, `cc` and
the rest are not read at all — mixing the two forms in one call sends only the blocks in the list.

Each block takes up to 3 `street` lines, and `city` and `cc` are required by the schema.

### The disclose block

RFC 5733 lets a contact state which of its elements may be published. The block is a flag plus a
list of elements the flag applies to; everything not listed takes the opposite treatment, so the
list means nothing without the flag.

```python
# Withhold the e-mail and the phone; everything else follows registry policy.
disclose={"flag": False, "email": True, "voice": True}

# Withhold the address and the organisation in BOTH postal forms.
disclose={"flag": False, "addr": ["int", "loc"], "org": ["int", "loc"]}

# Consent to publish the name in both forms.
disclose={"flag": True, "name": ["int", "loc"]}
```

| Key | Value | Wire |
|---|---|---|
| `flag` | truth value | `flag="1"` (publish) or `flag="0"` (withhold) |
| `name`, `org`, `addr` | a list of postal types: `["int"]`, `["loc"]` or both | one element per type |
| `voice`, `fax`, `email` | a truth value | a bare element when true |

`name`, `org` and `addr` exist once per postal form, so the choice is **per form**. Naming only
`["int"]` withholds the ASCII address while the local-script one stays public — a privacy setting
that reads as applied and is not.

Every flag is resolved as a *value*, not by Python truthiness: the strings `"0"`, `"false"` and
`""` all mean false here. Those reach an integrator from HTML forms and stored JSON, and all three
are truthy strings in Python, so `disclose={"flag": "0"}` means WITHHOLD, the way it was written.

Read it back with `disclose()`, where the postal elements are qualified by form:

```python
client.contact.info("C1").disclose()
# {'flag': False, 'elements': ['addr:int', 'addr:loc', 'email']}
```

| Code | Meaning |
|---|---|
| 1000 | created |
| 2003 | no postal block, or no e-mail |
| 2005 | a malformed value: Cyrillic in an `int` block, a bad e-mail, an id outside 3–16 characters |
| 2302 | that id already exists |
| 2306 | a registry rule refuses a value (a weak `auth_info`) |

---

## create_auto

```python
client.contact.create_auto(**options: Any) -> Response
Contact.AUTO_ID = "autonic"
```

Creates a contact and lets **the registry choose the handle**. It takes the same keyword options as
`create()`; the only difference is that it sends the reserved id `autonic` in place of one of yours.

```python
handle = client.contact.create_auto(
    name="Ivan Petrenko", city="Kyiv", cc="UA", email="contact@example.com",
).object_name()          # 'c-9f4b2ad10e'

# Use it wherever a handle is wanted.
client.domain.create("example.com.ua", years=1, registrant=handle)
```

The minted handle appears in **that response and nowhere else**. Store it as you read it; there is
no command that asks "what did you call the contact I created a minute ago".

This is the answer to two problems at once. If you have no naming scheme, you do not need to invent
one. And if you do have one, there is no retry loop around 2302 for a handle somebody else took
first: `autonic` is a request rather than a name, it is never stored as a handle, and **every call
mints a fresh one** — so repeating the same request produces a second contact, never a collision.
Generated ids use lowercase Latin letters, digits and `-`, within the 3–16 characters the protocol
allows.

The reserved value is available as `Contact.AUTO_ID` if you would rather pass it to `create()`
yourself, or to the [contact create builder](builders.md), which takes the id as an argument:

```python
from epptools import Contact

client.contact.create(Contact.AUTO_ID, name="Ivan Petrenko", city="Kyiv",
                      cc="UA", email="contact@example.com")
```

Result codes are those of `create`, minus 2302 — which is the point.

---

## update

```python
client.contact.update(contact_id: str, *,
                      add_statuses: Optional[List[str]] = None,
                      rem_statuses: Optional[List[str]] = None,
                      chg: Optional[Dict[str, Any]] = None) -> Response
```

Changes a contact. Statuses go in their own arguments; every field change goes in `chg`.

```python
client.contact.update(
    "C1",
    chg={"email": "new-contact@example.com",
         "postal_info": {"name": "Ivan Petrenko", "city": "Lviv", "cc": "UA", "org": ""}},
    add_statuses=["clientUpdateProhibited"],
)
```

`chg` accepts exactly these keys, in the snake_case spelling and the RFC's camelCase alike:

| Key | Effect |
|---|---|
| `postal_info` / `postalInfo` | one postal block |
| `postal_infos` / `postalInfos` | several postal blocks |
| `voice` | replace the phone number; `""` clears it |
| `fax` | replace the fax number; `""` clears it |
| `email` | replace the e-mail; it is required, so it cannot be cleared |
| `auth_info` / `authInfo` | replace the transfer secret |
| `disclose` | replace the disclosure preference — same shape as on create |

Any other key raises `ValidationException`, with a suggestion when it looks like a typo. A key
nobody reads is a change that does not happen behind a 1000, and nothing in the response would say
so.

There is no way to *remove* a contact's transfer secret. RFC 5731 gives a domain a nullable form and
RFC 5733 defines no equivalent for a contact, so a contact's code can be replaced but not cleared.
An empty password is not a substitute: an empty value is still a value the holder can present.

### The partial-update rule: presence decides

Inside a postal block, **presence decides and an empty string clears**:

| You write | What happens |
|---|---|
| the key is absent | the field is not sent, and the registry keeps what it holds |
| the key holds a value | the field is set to it |
| the key holds `""` | the field is sent empty, which **clears** it |

That is the only way to remove an `org`, an `sp` or a `pc`. It is also the only postal form that is
touched: changing the `int` block leaves the `loc` block exactly as it was, and the other way round.

```python
# Remove the organisation, change nothing else about the address.
client.contact.update("C1",
                      chg={"postal_info": {"type": "int", "org": "",
                                           "city": "Kyiv", "cc": "UA"}})
```

**Give `city` and `cc` whenever you touch the address at all.** The `<contact:addr>` element is a
sequence whose city and country are required by the schema, so it is sent whole or not at all — and
when it is sent, city and country go with it. Leaving them out of a call that changes a street line
sends them **empty**, and an empty value is a deliberate clear. The command answers 1000 and the
contact loses its city and country.

Street lines behave differently and in your favour: an address block sent without any `street`
leaves the existing lines untouched.

If you are only changing the name, the organisation or the phone, do not mention `street`, `city`,
`sp`, `pc` or `cc` at all — then no address block is sent and nothing in it can be affected:

```python
# The address is not touched, because nothing addressed it.
client.contact.update("C1", chg={"postal_info": {"name": "Ivan Petrenko"}})
```

### Statuses

`add_statuses` and `rem_statuses` each build one block holding every status you name. The
client-settable ones are `clientDeleteProhibited`, `clientUpdateProhibited` and
`clientTransferProhibited`; the `server*` counterparts belong to the registry and a command that
tries to set one is refused with 2306.

`clientUpdateProhibited` blocks the contact against further changes — including the one that would
lift it, with a single deliberate exception: a command whose *only* content is removing
`clientUpdateProhibited` is accepted. So the way out is a command on its own:

```python
client.contact.update("C1", rem_statuses=["clientUpdateProhibited"])
# ...and only then the edit
client.contact.update("C1", chg={"email": "new-contact@example.com"})
```

Combining the unlock with the edit in one command is 2304.

| Code | Meaning |
|---|---|
| 1000 | applied |
| 2303 | no such contact |
| 2304 | a status forbids it — see the unlock rule above |
| 2305 | an association forbids it |
| 2306 | a registry rule refuses the value, or a status that is not client-settable |

---

## delete

```python
client.contact.delete(contact_id: str) -> Response
```

```python
client.contact.delete("C1")
```

**A contact still referenced by a domain cannot be deleted** — the registry answers 2305 and the
contact carries the status `linked`. Detach it first: point the domains at another handle with
[`domain.update`](domains.md#update), then delete.

`all_contacts()` on a domain reply is the quick way to find out which of your contacts are still in
use, since it lists every handle including the registrant:

```python
in_use = set(client.domain.info("example.com.ua").all_contacts())
if "C1" not in in_use:
    client.contact.delete("C1")
```

| Code | Meaning |
|---|---|
| 1000 | deleted |
| 2303 | no such contact |
| 2304 | a status forbids it (`clientDeleteProhibited`) |
| 2305 | still linked to a domain |

---

## transfer

```python
client.contact.transfer(op: str,
                        contact_id: str,
                        auth_info: Optional[str] = None) -> Response
```

`op` is one of `request`, `approve`, `reject`, `cancel`, `query`, and goes out as the `op` attribute
of `<transfer>`. There is no period and no fee: a contact transfer moves sponsorship and nothing
else.

```python
# Gaining side, with the code from the current sponsor.
r = client.contact.transfer("request", "C1", "the-code")
r.code()                    # 1000, or 1001 when it is decided later
r.transfer_status()         # 'pending'

# Losing side, after a poll notice said someone asked for a contact you sponsor.
client.contact.transfer("approve", "C1")
client.contact.transfer("reject", "C1")

# Gaining side, withdrawing your own request.
client.contact.transfer("cancel", "C1")

# Either side: where has it got to?
t = client.contact.transfer("query", "C1").transfer()
t["status"], t["requested_by"], t["acting_client"], t["act_by"]
```

`transfer()` returns the whole notice — who asked, when, who must answer and by when. `act_by` is
the deadline after which the registry decides for you, so a transfer notice arriving through
[poll](poll.md) is something to answer rather than something to file.

| Code | Meaning |
|---|---|
| 1000 / 1001 | accepted; 1001 means the outcome arrives later via [poll](poll.md) |
| 2201 | you are not a party who may send this op |
| 2202 | the `auth_info` is wrong |
| 2300 | already pending transfer (on a second `request`) |
| 2301 | not pending transfer (on an `approve`/`reject`/`cancel`/`query`) |
| 2303 | no such contact |
| 2304 | a status forbids it |

---

See also: [Domains](domains.md) · [Hosts](hosts.md) · [Poll](poll.md) ·
[Responses](responses.md) · [Builders](builders.md) · [Errors](errors.md)

[Back to the index](README.md)
