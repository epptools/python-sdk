# Commands

The command surface as a whole: where the methods live, what they all return, how a reply is matched
to the request that caused it, how to turn the raising off, and how to send a frame the library does
not model.

## Where the commands live

Everything reachable after a successful `login()` hangs off four resource properties and one method
on the client:

```python
client.domain     # RFC 5731 domain commands
client.contact    # RFC 5733 contact commands
client.host       # RFC 5732 host commands
client.poll       # the message queue
client.balance()  # the registry's native account query
```

Each property is built once and reused, so `client.domain` is the same object every time and holding
a reference to it is fine.

## The whole command index

Every method here sends exactly one EPP command and returns a [`Response`](responses.md). The detail
— arguments, examples, what comes back — is on the object pages.

### Domain — [domains.md](domains.md)

| Method | EPP |
|---|---|
| `check(names: List[str], fee: Optional[Dict[str, Any]] = None, currency: Optional[str] = None)` | `<check>` + RFC 8748 `fee:check` |
| `info(name: str, auth_info: Optional[str] = None, hosts: str = "all")` | `<info>` |
| `create(name, *, years=None, registrant=None, contacts=None, nameservers=None, auth_info=None, license=None, sec_dns=None, fee=None)` | `<create>` |
| `update(name, *, add=None, rem=None, chg=None, restore=False, license=None, sec_dns=None, fee=None)` | `<update>` |
| `renew(name: str, cur_exp_date: str, years: int = 1, fee=None)` | `<renew>` |
| `restore(name: str, fee=None)` | `<update>` + RFC 3915 `rgp:restore` |
| `delete(name: str)` | `<delete>` |
| `transfer(op: str, name: str, auth_info=None, years=None, fee=None)` | `<transfer op="…">` |
| `create_builder(name: str)` | a [builder](builders.md) for `create` |
| `update_builder(name: str)` | a [builder](builders.md) for `update` |

### Contact — [contacts.md](contacts.md)

| Method | EPP |
|---|---|
| `check(ids: List[str])` | `<check>` |
| `info(contact_id: str, auth_info: Optional[str] = None)` | `<info>` |
| `create(contact_id, *, name=None, org=None, street=None, city=None, sp=None, pc=None, cc=None, type="int", postal_infos=None, voice=None, fax=None, email=None, auth_info=None, disclose=None)` | `<create>` |
| `create_auto(**options)` | `<create>` with `Contact.AUTO_ID` as the id — the registry mints the handle |
| `update(contact_id, *, add_statuses=None, rem_statuses=None, chg=None)` | `<update>` |
| `delete(contact_id: str)` | `<delete>` |
| `transfer(op: str, contact_id: str, auth_info: Optional[str] = None)` | `<transfer op="…">` |
| `create_builder(contact_id: str, email: str)` | a [builder](builders.md) for `create` |
| `update_builder(contact_id: str)` | a [builder](builders.md) for `update` |

`Contact.AUTO_ID` is the reserved id that asks the registry to choose the handle instead of naming
it yourself. The minted handle comes back in the response and **that reply is the only place it
appears** — read it with `object_name()` and store it.

### Host — [hosts.md](hosts.md)

| Method | EPP |
|---|---|
| `check(names: List[str])` | `<check>` |
| `info(name: str)` | `<info>` |
| `create(name: str, addresses: Optional[List[str]] = None)` | `<create>` |
| `update(name, *, add_addresses=None, rem_addresses=None, add_statuses=None, rem_statuses=None, new_name=None)` | `<update>` |
| `delete(name: str, force: bool = False)` | `<delete>`, with the registry's native forced delete when `force` is set |
| `update_builder(name: str)` | a [builder](builders.md) for `update` |

### Poll — [poll.md](poll.md)

| Method | EPP |
|---|---|
| `request()` | `<poll op="req">` — 1301 with a message, 1300 when the queue is empty |
| `ack(message_id: str)` | `<poll op="ack">` — **deletes** the notice at the registry |
| `drain(handler: Callable[[Response], None], limit: int = 0)` | the two above in a loop, acking only after your callback returns |

### Balance — [balance.md](balance.md)

| Method | EPP |
|---|---|
| `client.balance()` | `<info>` in the registry's balance namespace |

## What a command returns

Every command returns a `Response` — never `None`, never a bare dict. The object wraps the parsed
reply and answers questions about it; [Responses](responses.md) documents every accessor.

```python
response = client.domain.create("example.com.ua", years=1, registrant="acme-01")
response.code()          # 1000
response.is_success()    # True for any 1xxx
response.is_pending()    # True for 1001
response.object_name()   # "example.com.ua"
response.sv_trid()       # the registry's identifier for this operation — store it
```

| Code | Meaning | What the library does | What you do |
|---|---|---|---|
| `1000` | done | returns the `Response` | continue |
| `1001` | accepted, completing offline | returns the `Response`; `is_success()` and `is_pending()` are both `True` | **do not resend.** The outcome arrives later as a poll notice |
| `1300` / `1301` | poll: empty / a message waiting | returns the `Response` | see [Poll](poll.md) |
| `1500` | session ending | returns the `Response` from `logout()` | disconnect |
| `2xxx` | refused; nothing changed | raises, unless you turned that off | see [Errors](errors.md) |

**1001 is the one that catches people out.** The command was accepted and is being processed
offline — a transfer always, and other operations depending on the zone. Treat it as
success-in-progress: record the svTRID, watch the poll queue for the outcome, and never send the
command again to make sure. The matching notice carries `pending_action_data()`, whose `svTRID` is
what ties it back to the command you sent.

Dates and money in a response are the **server's own strings** — `2027-04-01T09:15:00Z`,
`"100.00"` — never a `datetime` and never a `float`. That is deliberate, and the reasons are worth
knowing before you build on them: see [Responses](responses.md#dates-and-money).

## Client transaction ids

Every command carries a `clTRID` that you choose and the server echoes back; every response carries
an `svTRID` that the registry assigns.

The library stamps a clTRID on every frame automatically:

```
PYTHON-SDK-20260816093012-4821-0001
│       │              │    └── a counter, per client object
│       │              └─────── the process id
│       └────────────────────── a UTC timestamp
└────────────────────────────── Config.cltrid_prefix
```

Ids from one process share a stable middle segment and stay unique across concurrent processes.
Change the prefix with `Config.cltrid_prefix` to make your own traffic recognisable in a shared log,
and keep it short: the protocol caps the whole id at 64 characters.

**Store the svTRID against the object the command was about.** It is the value support looks an
operation up by; a clTRID means nothing to anyone but you. Log both, on every command, including the
ones that succeeded — those are what you compare against when a later one does not.

### Replies are matched to their command

Every reply is checked against the clTRID its command sent. A mismatch means the byte stream has
desynchronised — a stray unsolicited frame, or two commands in flight at once — and the library
raises `ConnectionException` and closes the connection instead of handing you someone else's result.

The consequence of not checking is why it does: a reply belonging to the previous command is
otherwise indistinguishable from this one's, and for a renew that means `renew("example2.com.ua")` returning
1000 carrying a's expiry date, with both billed. Once the offsets disagree, every later frame on the
stream is suspect too, so the connection is finished rather than merely reported. Reconnect and log
in again.

This is also why you send one command at a time on a connection. Open more sessions for throughput;
do not overlap commands inside one.

## The throw_on_failure switch

By default any result code of 2000 or more raises — the class depending on the code, see
[Errors](errors.md). The message names the subject when the registry identified one, so a rejection
inside a batch of five names says which name it was.

```python
client.throw_on_failure(False)      # returns the client, so it chains

response = client.domain.check(["example.com.ua"])
if not response.is_success():
    log.warning("EPP %d: %s", response.code(), response.message())
```

`throw_on_failure(False)` turns the raising off for the object commands, and `throw_on_failure(True)`
turns it back on. Two things keep raising either way, because there is no useful `Response` to hand
back instead:

- **`login()`**, which raises on any code other than 1000. There is no session to continue into.
- **`poll.drain()`**, when a poll reply is neither a notice nor an empty queue. Reading that as
  "drained" would report success while nothing had been read.

Switching it off means the failure is now yours to notice. A `create` whose 2104 you did not check is
a domain your system believes it registered.

## Custom frames

Anything the high-level API does not model can be assembled with `Frame` and sent with
`client.request()`. This is the escape hatch for a registry extension specific to your account, not
something a normal integration needs.

```python
from epptools import Frame, Namespaces

frame = client.frame()                       # a <command> with a clTRID already stamped
check = frame.ns(frame.verb("check"), Namespaces.DOMAIN, "domain:check")
frame.ns(check, Namespaces.DOMAIN, "domain:name", "example.com.ua")

response = client.request(frame)             # or client.request(raw_xml_string)
print(response.availability())
```

| Member | What it does |
|---|---|
| `client.frame()` | A new `Frame` with a generated clTRID already on it. |
| `Frame.command(cltrid)` | A frame with a clTRID you choose. |
| `frame.verb(name)` | Adds the command verb — `check`, `info`, `create`, `update`, `renew`, `transfer`, `delete`, `poll`, `login`, `logout` — and returns it. |
| `frame.extension()` | Adds `<extension>` once and returns it; call it as often as you like. |
| `frame.epp(parent, name, text=None, attrs=None)` | Appends an element in the base `epp-1.0` namespace. |
| `frame.ns(parent, ns_uri, qname, text=None, attrs=None)` | Appends a namespaced element, e.g. `frame.ns(parent, Namespaces.DOMAIN, "domain:name", "example.com.ua")`. |
| `frame.to_xml()` | Serializes the frame. Safe to call more than once — log it, then send it. |
| `frame.root` | The underlying `ElementTree` element, for anything the helpers do not cover. |
| `client.request(frame_or_xml)` | Sends a `Frame` or a raw XML string and returns the parsed `Response`. |

The frame builder guarantees the RFC 5730 child order — command content, then the optional
`<extension>`, then `<clTRID>` last — and sets text on element nodes rather than concatenating
strings, so a value containing `&` or `<` is escaped rather than producing a frame the server
answers with 2001.

`Namespaces` carries the URI constants so you never type one out: `EPP`, `DOMAIN`, `CONTACT`,
`HOST`, `SECDNS` (RFC 5910), `RGP` (RFC 3915), `FEE` (RFC 8748), `LOGINSEC` (RFC 8807), plus
`DEFAULT_OBJ_URIS` and `DEFAULT_EXT_URIS`.

A frame you build yourself gets the same treatment as one the library built: the clTRID echo is
checked, the response is parsed into a `Response`, and an error code raises unless you turned that
off. Use `Namespaces` URIs the greeting actually advertised — an extension the server does not serve
is refused with 2103.

### Your registry's own extensions

Every URI in `Namespaces` is defined by an RFC and is the same string at every registry on earth. A
registry's OWN extensions — a trademark licence, a price, an account balance — are not, and there is
no constant for them there, because there is no value that would be right for more than one registry.

They are **discovered from the `<greeting>`**. Every server lists what it supports before you send
anything, so after `connect()` the client already knows:

```python
client.connect()

client.registry_ext_uri()      # e.g. 'http://registry.example/epp/registry-1.0', or None
client.registry_balance_uri()  # e.g. 'http://registry.example/epp/balance-1.0', or None
```

`None` means that server advertises no such extension — a fact about the server, not an error. The
commands that need one say so instead of guessing: `domain.create` with a `license`, `host.delete`
with `force` and `balance()` all raise `ConfigException` naming what was wanted and listing what the
server did offer. That refusal is the point. An extension sent under a namespace a server does not
recognise is **ignored, not rejected**, so a guess would come back `1000 OK` with the licence
silently unset.

Discovery matches the last segment of an advertised URI — `.../registry-1.0`, `urn:…:balance` —
which is the convention registries follow, not a rule anyone enforces. For a registry that names its
extensions something else, set them yourself and the greeting is not consulted:

```python
config = Config(
    host="epp.registry.example", clid="EXAMPLE", password="...",
    registry_ext_uri="urn:example:params:xml:ns:myreg-1.0",
    registry_balance_uri="urn:example:params:xml:ns:myreg-balance-1.0",
)
```

---

[← Manual index](README.md)
