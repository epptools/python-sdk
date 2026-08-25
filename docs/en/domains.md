# Domains

Everything under `client.domain`. Domain objects follow **RFC 5731**, and every method on this page
maps to one EPP command on the wire, so the registry's own manual and the RFC describe the same
exchange from the server's side.

Each method returns a [`Response`](responses.md). By default a result code of 2000 or higher is
raised as an exception before you ever see the response — see [Errors](errors.md) for the taxonomy
and for `throw_on_failure(False)` if you would rather read `code()` yourself.

A first complete program, so the fragments below have something to hang on:

```python
from epptools import Client, Config
from epptools.exceptions import EppException

client = Client(Config(
    host="epp.registry.example",
    clid="EXAMPLE",
    password="your-secret",
    ca_file="/etc/ssl/registry-ca.pem",
))

try:
    client.connect()
    client.login()

    check = client.domain.check(["example.com.ua"])
    if check.is_available("example.com.ua"):
        created = client.domain.create("example.com.ua", years=1, registrant="C1")
        print("registered until", created.expiry_date())
    else:
        print("taken:", check.unavailable_reason("example.com.ua"))

    client.logout()
except EppException as exc:
    print("EPP error:", exc)
finally:
    client.disconnect()
```

## The methods

| Method | EPP command |
|---|---|
| `check` | `<check><domain:check>` |
| `info` | `<info><domain:info>` |
| `create` | `<create><domain:create>` |
| `update` | `<update><domain:update>` |
| `delete` | `<delete><domain:delete>` |
| `renew` | `<renew><domain:renew>` |
| `transfer` | `<transfer op="…"><domain:transfer>` |
| `restore` | `<update><domain:update>` + `<rgp:restore op="request"/>` |

`create_builder()` and `update_builder()` assemble the same two commands step by step; they are
documented in [Builders](builders.md) and produce the identical frame.

---

## check

```python
client.domain.check(names: List[str],
                    fee: Optional[Dict[str, Any]] = None,
                    currency: Optional[str] = None) -> Response
```

Asks whether names are registrable. One `<domain:name>` per name, and optionally an RFC 8748
`<fee:check>` rider in `<extension>` that asks the price at the same time — the fee half is covered
in full on the [Balance and prices](balance.md) page.

**At most 10 names per command.** An eleventh is refused with 2001 by the registry, so batch in
tens.

```python
r = client.domain.check(["example.com.ua", "taken.com.ua"])

r.availability()          # {'example.com.ua': True, 'taken.com.ua': False}
r.is_available("example.com.ua")        # True
r.unavailable_reason("taken.com.ua")    # 'in use'
```

`is_available()` returns `None` when the answer said nothing about that name at all. That is not the
same as "taken", and it must not be treated the same way by the line that registers it:

```python
free = r.is_available("example.com.ua")
if free is None:
    raise RuntimeError("the check said nothing about this name — ask again before registering")
if free:
    client.domain.create("example.com.ua", years=1, registrant="C1")
```

| Code | Meaning |
|---|---|
| 1000 | answered; read `availability()` — an unavailable name is a normal 1000, not an error |
| 2001 | more than 10 names in one command |
| 2004 | a fee rider asked for an operation the registry does not price |
| 2306 | more than 20 fee entries in one command |
| 2307 | the zone is not served |

---

## info

```python
client.domain.info(name: str,
                   auth_info: Optional[str] = None,
                   hosts: str = "all") -> Response
```

Reads a domain. As the sponsoring registrar you get the full record. As a non-sponsor you get the
public subset (name, roid, statuses, dates, sponsor) — and the full record instead if you pass the
domain's `auth_info`. Passing a *wrong* one is 2202; passing none is not an error.

`hosts` sets the `hosts` attribute of `<domain:name>` and picks which nameserver information comes
back (RFC 5731 §3.1.2):

| Value | Returns |
|---|---|
| `"all"` | both the delegated nameservers and the subordinate hosts (default) |
| `"del"` | only the nameservers this domain is delegated to |
| `"sub"` | only the hosts that live under this domain |
| `"none"` | neither |

```python
info = client.domain.info("example.com.ua")

info.object_name()          # 'example.com.ua'
info.roid()                 # the registry's own object id
info.expiry_date()          # '2027-04-01T09:15:00.0Z' — the registry's own string
info.created_date()         # crDate            info.created_by()   # crID
info.updated_date()         # upDate, or None   info.updated_by()   # upID, or None
info.transfer_date()        # trDate, or None if it never changed hands
info.sponsor()              # clID — the account it belongs to
info.registrar_of_record()  # the handle WHOIS/RDAP publishes, when that is a different party

info.registrant()           # 'C1'
info.contacts()             # {'admin': ['EXAMPLE-C2'], 'tech': ['EXAMPLE-C3']}
info.tech_contacts()        # ['EXAMPLE-C3']  — also admin_contacts(), billing_contacts()
info.contacts_for("Tech")   # same list; the role is matched case-insensitively
info.all_contacts()         # every handle including the registrant, de-duplicated

info.statuses()             # ['ok'] or ['clientHold', 'clientTransferProhibited', ...]
info.nameservers()          # ['ns1.example.com.ua', 'ns2.example.com.ua']
info.nameserver_addresses() # inline glue, keyed by nameserver name (empty under the hostObj model)
info.subordinate_hosts()    # hosts living UNDER this domain
info.auth_info()            # the transfer secret — never log it
info.license()              # a trademark or licence number, or None
info.rgp_status()           # ['redemptionPeriod'] while the domain is deleted-but-restorable
info.is_signed()            # True when DNSSEC data came back
info.ds_records()           # [{'keyTag': 12345, 'alg': 13, 'digestType': 2, 'digest': '…'}]
info.key_records()          # [{'flags': 257, 'protocol': 3, 'alg': 13, 'pubKey': '…'}]
info.prices()               # {'renewal': {'value': '180.00', 'currency': 'UAH'}, …}
info.price_channel()        # the opaque catalogue id those prices belong to
```

Three things that cost money or data when they are misread:

- **Dates are the registry's own strings**, never `datetime`. The registry decides which calendar
  day a renewal lands on; re-formatting through a local timezone is how a client ends up displaying
  — and renewing against — the day before.
- **`rgp_status()` is where redemption lives**, not `statuses()`. A domain days away from permanent
  deletion can report a plain `ok` in `statuses()`, and a client that reads only that sees nothing
  wrong until the name is gone.
- **`nameserver_addresses()` being empty does not mean the domain is undelegated.** It carries only
  inline glue. Under the host-object model the names come back alone; use `nameservers()` for the
  list and a [`host.info`](hosts.md#info) per name for the addresses.

| Code | Meaning |
|---|---|
| 1000 | answered |
| 2202 | you are not the sponsor and the `auth_info` you supplied is wrong |
| 2303 | no such domain |

---

## create

```python
client.domain.create(name: str, *,
                     years: Optional[int] = None,
                     registrant: Optional[str] = None,
                     contacts: Optional[Dict[str, str]] = None,
                     nameservers: Optional[List[Nameserver]] = None,
                     auth_info: Optional[str] = None,
                     license: Optional[str] = None,
                     sec_dns: Optional[Dict[str, Any]] = None,
                     fee: Optional[FeeAgreement] = None) -> Response
```

Registers a domain. **This is a billable command**: the create fee is charged on success.

Every option after `name` is keyword-only, so a misspelling is a `TypeError` in your editor rather
than a missing element on the wire.

| Option | Type | Goes on the wire as |
|---|---|---|
| `years` | `int` | `<domain:period unit="y">`; omitted entirely when you do not pass it, and the registry then applies its own default |
| `registrant` | `str` | `<domain:registrant>` |
| `contacts` | `{role: handle}` or `{role: [handle, …]}` | one `<domain:contact type="role">` per handle |
| `nameservers` | `[name, …]` or `[{"name": …, "addresses": [...]}, …]` | `<domain:ns>` with `<domain:hostObj>` or `<domain:hostAttr>` |
| `auth_info` | `str` | `<domain:authInfo><domain:pw>` |
| `license` | `str` | `<extension><registry:create><registry:license>` |
| `sec_dns` | `dict` | `<extension><secDNS:create>` (RFC 5910) |
| `fee` | `str` or `{"amount", "currency"}` | `<extension><fee:create>` (RFC 8748) |

A complete registration using all of them:

```python
created = client.domain.create(
    "example.com.ua",
    years=2,
    registrant="C1",
    contacts={"admin": "EXAMPLE-C2", "tech": ["EXAMPLE-C3", "EXAMPLE-C4"]},
    nameservers=["ns1.example.com.ua", "ns2.example.com.ua"],
    auth_info="D0main-Pw!",
    license="TM-2026-000123",                       # where your registry requires one
    sec_dns={"ds_data": [{"key_tag": 12345, "alg": 13,
                          "digest_type": 2, "digest": "49FD46E6C4B45C55D4AC"}]},
    fee="200.00",                                 # a cap, not a price
)

created.code()          # 1000, or 1001 when the registry queues the registration
created.object_name()   # 'example.com.ua'
created.created_date()  # crDate
created.expiry_date()   # exDate — store this; renew() has to quote it back
created.fee_amount()    # what the registry charged — at most the cap you agreed to, often less
```

### years

Whole years, within the zone's range (1–10 by default), and the resulting expiry may not pass the
registry's horizon. A period outside the range is 2004; one below the zone's minimum is 2306.

### registrant and contacts

`contacts` takes **either one handle per role or several**:

```python
contacts={"admin": "EXAMPLE-C2", "tech": ["EXAMPLE-C3", "EXAMPLE-C4"]}
```

Each handle becomes its own `<domain:contact type="tech">` element, which is what RFC 5731 allows
and what the registry parses back into a list per role. Empty or `None` handles are dropped rather
than sent as empty elements. The registry accepts at most 8 handles in any one role (2306 beyond
that) and 16 in total.

Which roles a zone *requires* is the zone's own rule; a create missing a required role is 2003.

### nameservers, in both models

RFC 5731 makes `<domain:ns>` a choice between two ways of naming a nameserver, and a registry takes
one or the other. Ask yours which:

```python
# Host objects: the name references a host you created first (see hosts.md).
nameservers=["ns1.example.com.ua", "ns2.example.com.ua"]

# Inline glue: the name arrives with its addresses, no host object involved.
nameservers=[
    {"name": "ns1.example.com.ua", "addresses": ["203.0.113.10", "2001:db8::10"]},
    {"name": "ns2.example.com.ua", "addresses": ["203.0.113.11"]},
]
```

IPv4 and IPv6 are told apart from the literal, so each address gets the right `ip="v4"` / `ip="v6"`
attribute without your saying so.

**The two cannot be mixed in one command.** A list holding both a plain string and a dict raises
`ValidationException` before anything is sent — the schema would refuse the frame anyway, and it
would refuse it as a bare 2001 that names no field, which is a considerably worse thing to debug.

A domain created with no nameservers at all is legal and reports the computed status `inactive`.
That is not an error; it means the domain is not yet delegated.

### auth_info

`<domain:authInfo>` is mandatory on `domain:create`, so the element always goes out. Pass a code and
that becomes the transfer secret; omit it and an empty `<domain:pw/>` is sent, which asks the
registry to apply its own zone policy and mint one. Read the minted code back with
`client.domain.info(name).auth_info()`.

A code you supply must satisfy the zone's strength policy — a minimum length and a number of
character classes — or the create is refused with 2306.

Anyone holding this code can move the domain to another registrar. Treat it as a credential: never
log it, and set a fresh one after you have handed it to a customer.

### licence

Some registries will not register certain names without a trademark or licence number — commonly the
short, valuable ones directly under the TLD. It travels in the registry's **own** extension, whose
namespace the client reads from the `<greeting>`, so against a registry that advertises none this
raises `ConfigException` rather than sending a frame the server would ignore. See
[Commands](commands.md#your-registrys-own-extensions).

Which names need one is the registry's policy, not the protocol's, so ask yours. Omitting a required
one is usually 2003; sending one where none is wanted is 2306.

### DNSSEC on create

`sec_dns` builds a `<secDNS:create>` block (RFC 5910). Two record shapes, and both may appear:

```python
sec_dns={
    "ds_data": [
        {"key_tag": 12345, "alg": 13, "digest_type": 2, "digest": "49FD46E6C4B45C55D4AC"},
        # A DS record may carry the DNSKEY it was computed from, where the registry accepts it:
        {"key_tag": 54321, "alg": 13, "digest_type": 2, "digest": "A1B2C3D4E5F60718293A",
         "key_data": {"flags": 257, "protocol": 3, "alg": 13, "pub_key": "AwEAAb…"}},
    ],
    "key_data": [{"flags": 257, "protocol": 3, "alg": 13, "pub_key": "AwEAAb…"}],
    "max_sig_life": 1209600,
}
```

Every key accepts the RFC's own camelCase spelling as well: `dsData`, `keyData`, `keyTag`,
`digestType`, `pubKey`, `maxSigLife`. **Anything else raises `ValidationException`**, naming the
closest key it recognises. That refusal is the point: an option key nobody reads is silently absent
from the frame, the registry answers 1000 for the command it did receive, and you have an unsigned
domain that every part of your system believes is signed.

`max_sig_life` on its own emits nothing — a `<secDNS:create>` needs at least one DS or key record,
so a `sec_dns` with no records is left out of the frame rather than sent as an invalid empty block.

The registry accepts SHA-256 (`digest_type` 2) and SHA-384 (`digest_type` 4), up to 6 DS records per
domain, and refuses duplicates. A DNSSEC command on a zone that does not offer DNSSEC is 2103 or
2306.

### fee

Optional, and it is a **cap, not a price**: "I agree to pay up to this much". Without it the
registry charges its own price and the command succeeds. With it, a higher real price refuses the
command with 2004 and charges nothing. See [Balance and prices](balance.md#capping-what-you-agree-to-pay).

| Code | Meaning |
|---|---|
| 1000 | registered |
| 1001 | queued; the outcome arrives as a [poll notice](poll.md) |
| 2003 | a required element is missing — a role the zone requires, or a licence it requires |
| 2004 | the period is out of range, or the fee you agreed to does not cover the price |
| 2005 | a value is malformed (a bad label, a bad address) |
| 2103 | DNSSEC is not offered on this zone |
| 2104 | insufficient funds — raised as `InsufficientFundsError`; stop the batch |
| 2302 | already registered |
| 2306 | a registry rule refuses a value: weak `auth_info`, too many contacts in a role, a licence where none applies |
| 2307 | the zone is not served |

---

## update

```python
client.domain.update(name: str, *,
                     add: Optional[Dict[str, Any]] = None,
                     rem: Optional[Dict[str, Any]] = None,
                     chg: Optional[Dict[str, Any]] = None,
                     restore: bool = False,
                     license: Optional[str] = None,
                     sec_dns: Optional[Dict[str, Any]] = None,
                     fee: Optional[FeeAgreement] = None) -> Response
```

An EPP update is a **delta, not a replacement**. What you do not mention is left exactly as it is,
and which of the three blocks a change belongs to is the whole semantics of the command.

### add and rem

Both take the same three keys, and both build the block only if you give it something:

| Key | Type | Effect |
|---|---|---|
| `ns` | list, in either nameserver model | delegate to / stop delegating to these nameservers |
| `contacts` | `{role: handle}` or `{role: [handle, …]}` | attach / detach contacts in a role |
| `statuses` | `[str, …]` | set / clear a client-side status |

```python
client.domain.update(
    "example.com.ua",
    add={"ns": ["ns3.example.com.ua"],
         "contacts": {"tech": "EXAMPLE-C4"},
         "statuses": ["clientHold"]},
    rem={"ns": ["ns2.example.com.ua"],
         "statuses": ["clientTransferProhibited"]},
)
```

The client statuses you may set are `clientHold`, `clientDeleteProhibited`,
`clientUpdateProhibited`, `clientTransferProhibited` and `clientRenewProhibited`. The `server*`
counterparts belong to the registry and a command that tries to set one is refused. `clientHold`
takes the domain out of DNS — the name stops resolving — so it is a change worth confirming rather
than a flag worth toggling.

### chg

`chg` changes the single-valued fields a domain has, and takes exactly these keys:

| Key | Effect |
|---|---|
| `registrant` | hand the domain to a different holder |
| `auth_info` (or `authInfo`) | replace the transfer secret |
| `clear_auth_info` (or `clearAuthInfo`) | remove the transfer secret altogether |

```python
client.domain.update("example.com.ua",
                     chg={"registrant": "EXAMPLE-C9", "auth_info": "New-Str0ng!"})
```

Any other key raises `ValidationException`, with a suggestion when the mistake looks like a typo. A
key that is quietly ignored is a change that did not happen behind a 1000 — you would have no way of
telling from the response, because as far as the registry is concerned you never asked.

Changing the registrant is treated by many zones as a change of ownership with rules of its own, so
a refusal there is usually policy (2306) rather than a malformed command.

### Revoking a leaked transfer code

If a transfer secret has leaked, setting an empty one does not help you: an empty password is still
a value the holder can present, and the domain stays exactly as movable as it was. The protocol has
a separate form for removal — `<domain:authInfo><domain:null/>` — and that is what
`clear_auth_info` sends:

```python
# The code is gone. No code will move this domain until you set a new one.
client.domain.update("example.com.ua", chg={"clear_auth_info": True})

# Later, when the customer legitimately needs one again:
client.domain.update("example.com.ua", chg={"auth_info": "Fresh-C0de!"})
```

Setting and clearing in the same command is a contradiction the schema cannot express, so passing
both `auth_info` and `clear_auth_info` raises `ValidationException` rather than silently picking one.

Note also that the registry ages the code: it is valid for transfer for 30 days from the moment it
was **set**, not from the moment a transfer starts. A code issued today and used five weeks later is
refused with 2202 even though it matches, and a fresh one has to be set.

### DNSSEC on update

An update carries a `<secDNS:update>` delta, which is a different shape from the create block:

```python
# Replace one key with another, in a single command, with no window where the domain is unsigned.
client.domain.update("example.com.ua", sec_dns={
    "rem": {"ds_data": [{"key_tag": 12345, "alg": 13,
                         "digest_type": 2, "digest": "49FD46E6C4B45C55D4AC"}]},
    "add": {"ds_data": [{"key_tag": 54321, "alg": 13,
                         "digest_type": 2, "digest": "A1B2C3D4E5F60718293A"}]},
})

# Unsign entirely.
client.domain.update("example.com.ua", sec_dns={"rem_all": True})

# Replace the whole key set: remove everything and add the new set together.
client.domain.update("example.com.ua", sec_dns={
    "rem_all": True,
    "add": {"ds_data": [{"key_tag": 54321, "alg": 13,
                         "digest_type": 2, "digest": "A1B2C3D4E5F60718293A"}]},
})

# Change only the signature lifetime.
client.domain.update("example.com.ua", sec_dns={"max_sig_life": 1209600})
```

| Key | Effect |
|---|---|
| `add` | a mapping with `ds_data` and/or `key_data`, appended to what the domain already has |
| `rem` | the same shape; every field must match the record the registry holds |
| `rem_all` (or `remAll`) | remove every key |
| `max_sig_life` (or `maxSigLife`) | set the signature lifetime in seconds; may travel alone |

On an update the records live **inside `add` and `rem`**. `ds_data` at the top level is the create
spelling and has no meaning in a delta.

`sec_dns={}` sends no `<secDNS:update>` at all. An empty one would be a 2003 for what reads as a
no-op, which is exactly the case a client hits when it builds the block unconditionally and only
sometimes fills it.

Removing a specific record and removing everything cannot both be expressed in one command, and the
same applies to the [update builder](builders.md), which refuses the combination by name.

### The licence and the fee on an update

`license=` sends `<registry:update><registry:license>` to change the trademark number. `fee=` caps a billable
update the same way it does on a create.

| Code | Meaning |
|---|---|
| 1000 | applied |
| 1001 | queued; the outcome arrives via [poll](poll.md) |
| 2003 | a required parameter is missing, or the command carries no change at all |
| 2004 | a value is out of range, or the agreed fee does not cover the price |
| 2005 | a value is malformed |
| 2303 | no such domain |
| 2304 | a status forbids it (`clientUpdateProhibited`, `serverUpdateProhibited`, a pending transfer) |
| 2305 | an association forbids it |
| 2306 | a registry rule refuses the value: a weak `auth_info`, a registrant change the zone does not allow |

---

## delete

```python
client.domain.delete(name: str) -> Response
```

```python
info = client.domain.info("example.com.ua")
if info.subordinate_hosts():
    raise RuntimeError("hosts still live under this domain: %s" % info.subordinate_hosts())

client.domain.delete("example.com.ua")
```

What a delete *does* depends on when you send it. Inside the add-grace window (5 days from
registration) the domain is removed immediately. Afterwards it enters `redemptionPeriod` for 30 days
— visible in `rgp_status()`, not in `statuses()` — during which it can be brought back with
[restore](#restore). It then spends 5 days in `pendingDelete` and the name is released.

Check `subordinate_hosts()` first, as above: the registry refuses to delete a domain while
nameserver objects live under it, and a 2305 after the fact is a round trip you did not need.

| Code | Meaning |
|---|---|
| 1000 | deleted, or moved into redemption |
| 1001 | queued; the outcome arrives via [poll](poll.md) |
| 2303 | no such domain |
| 2304 | a status forbids it (`clientDeleteProhibited`, `serverDeleteProhibited`) |
| 2305 | subordinate hosts still exist under the domain |

---

## renew

```python
client.domain.renew(name: str,
                    cur_exp_date: str,
                    years: int = 1,
                    fee: Optional[FeeAgreement] = None) -> Response
```

Extends the registration. **Billable.** `cur_exp_date` goes out as `<domain:curExpDate>` and must
equal the domain's current expiry — it is the protocol's guard against renewing a domain that
someone else already renewed while your view of it went stale.

Quote it back from the registry, never from your own calendar arithmetic — and pass it straight in:

```python
info = client.domain.info("example.com.ua")
current = info.expiry_date()            # e.g. '2027-04-01T09:15:00.0Z'

renewed = client.domain.renew("example.com.ua", current, 1, fee="180.00")   # sends '2027-04-01'

renewed.expiry_date()   # the NEW expiry — store it
renewed.fee_amount()    # '180.00'
renewed.fee_currency()  # 'UAH'
```

`<domain:exDate>` is a timestamp and `<domain:curExpDate>` is a date, and the library takes the date
part for you — as the server wrote it, with no parsing and no timezone conversion. That is
deliberate: EPP timestamps are UTC and the registry's expiry date is the UTC one, so a client that
reformats through a local zone lands a day either side for every domain expiring near midnight, and
then renews against a date the registry does not hold. Convert to local time where you display it,
never before sending it back.

The new expiry may not pass the registry's own horizon, commonly ten years.

A mismatch is 2105, and 2105 is the answer worth handling explicitly: it means the domain's expiry
is not what you thought, which is a reconciliation problem, not something a retry can fix.

| Code | Meaning |
|---|---|
| 1000 | renewed |
| 2004 | the period is out of range, or the agreed fee does not cover the price |
| 2104 | insufficient funds — `InsufficientFundsError` |
| 2105 | `cur_exp_date` does not match, or the domain cannot be renewed |
| 2303 | no such domain |
| 2304 | a status forbids it (`clientRenewProhibited`, a pending transfer) |
| 2306 | a registry rule refuses the request |

---

## transfer

```python
client.domain.transfer(op: str,
                       name: str,
                       auth_info: Optional[str] = None,
                       years: Optional[int] = None,
                       fee: Optional[FeeAgreement] = None) -> Response
```

`op` is one of `request`, `approve`, `reject`, `cancel`, `query`, and goes on the wire as the `op`
attribute of `<transfer>`. Which ones you may send depends on which side of the transfer you are on.

```python
# Gaining side: ask for a domain, quoting the code the customer got from the losing registrar.
r = client.domain.transfer("request", "example.com.ua", "the-code", 1, fee="180.00")

r.code()                # 1001 — a transfer is decided later, not now
t = r.transfer()
t["status"]             # 'pending'
t["requested_by"]       # reID — the registrar that asked
t["requested_at"]       # reDate
t["acting_client"]      # acID — the registrar that must answer
t["act_by"]             # acDate — the DEADLINE
t["expiry_date"]        # the expiry that will apply once it completes
```

```python
# Losing side: a poll notice told you someone wants a domain you sponsor.
client.domain.transfer("approve", "example.com.ua")
client.domain.transfer("reject", "example.com.ua")

# Gaining side, changed your mind while it is still pending:
client.domain.transfer("cancel", "example.com.ua")

# Either side, at any time — reports where the request has got to, changes nothing:
client.domain.transfer("query", "example.com.ua").transfer_status()   # 'pending'
```

Three things about `act_by` that decide whether you keep the domain:

- **Silence completes the transfer.** Past the deadline the registry *approves* it — it does not
  cancel it. A losing registrar that files the notice instead of answering it loses the domain, and
  the window is 5 days.
- Both registrars hear about every step through [poll](poll.md). A transfer notice is something to
  answer, not something to record.
- While `pendingTransfer` is set, no other operation on the domain is accepted.

`years` sends `<domain:period>` and is the zone's business, not yours to choose: on the Reglament
zones a transfer includes a mandatory one-year renewal, so `1` (or omitting it) is the only accepted
value and anything else is 2004. On the free-transfer zones you omit it entirely — a literal `0` is
not a smaller period but a schema violation, because the element's type starts at 1, and the frame
is refused as 2001 before any policy runs.

`auth_info` carries the code. On a zone that does not use transfer codes, leave it out.

| Code | Meaning |
|---|---|
| 1000 / 1001 | accepted; 1001 means the outcome arrives later via [poll](poll.md) |
| 2004 | a `years` value the zone does not accept |
| 2106 | the object cannot be transferred (locked or status-prohibited) |
| 2201 | you are not a party who may send this op |
| 2202 | the `auth_info` is wrong, or has aged past its 30-day validity |
| 2300 | already pending transfer (on a second `request`) |
| 2301 | not pending transfer (on an `approve`/`reject`/`cancel`/`query`) |
| 2303 | no such domain |
| 2304 | a status forbids it |

---

## restore

```python
client.domain.restore(name: str, fee: Optional[FeeAgreement] = None) -> Response
```

Brings back a domain sitting in `redemptionPeriod` (RFC 3915). **Billable**, and the restore price
is typically several times a registration.

It is a convenience over `update`: `restore(name, fee)` is exactly
`update(name, restore=True, fee=fee)`, which sends a `domain:update` carrying no add, rem or chg
block and an `<rgp:update><rgp:restore op="request"/>` extension.

```python
info = client.domain.info("example.com.ua")
if "redemptionPeriod" not in info.rgp_status():
    raise RuntimeError("not in redemption; nothing to restore")

r = client.domain.restore("example.com.ua", fee={"amount": "1200.00", "currency": "UAH"})

r.code()             # 1000 restored now, or 1001 restored later
r.expiry_date()      # the expiry after the restore
r.fee_amount()       # what it cost
```

**A restore must be the only thing in the command.** Combining `restore=True` with an `add`, `rem`,
`chg`, licence or DNSSEC change in the same `update` is refused with 2306; re-point the nameservers
in a second command once the domain is back.

A 1001 here is normal on some zones: the registry defers the restore, marks the domain
`pendingUpdate`, and the outcome arrives as a poll notice. Do not resend it — a second command
while one is in flight is how a restore fee gets paid twice.

| Code | Meaning |
|---|---|
| 1000 | restored |
| 1001 | queued; the outcome arrives via [poll](poll.md) |
| 2104 | insufficient funds — `InsufficientFundsError` |
| 2303 | no such domain |
| 2304 | not in the redemption period, the window has closed, or a status forbids the update |
| 2306 | the restore was not the only operation in the command |

---

## When a transform fails and you do not know whether it happened

A dropped connection or a read timeout in the middle of a `create`, `renew`, `transfer` or `restore`
leaves a genuinely unknown outcome: the registry may have carried the command out and billed you
before the reply was lost.

**Do not simply retry.** A blind retry is how a domain gets registered — and paid for — twice. Ask
the registry what is true instead: `domain.info()` for a create, and compare `expiry_date()` against
what you expected for a renew. Retry only if the object really is in the state you started from.
[Errors](errors.md) covers this in full.

---

See also: [Contacts](contacts.md) · [Hosts](hosts.md) · [Poll](poll.md) ·
[Balance and prices](balance.md) · [Responses](responses.md) · [Builders](builders.md) ·
[Errors](errors.md)

[Back to the index](README.md)
