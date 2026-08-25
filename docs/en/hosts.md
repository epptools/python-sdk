# Hosts

Everything under `client.host`. Host objects — nameservers — follow **RFC 5732**, and every method
here maps to one EPP command on the wire.

A host object exists so that domains can point at it by name. Where the registry uses the
host-object model, a nameserver must exist as an object before
[`domain.create`](domains.md#nameservers-in-both-models) or `domain.update` can reference it with
`<domain:hostObj>`. Where the registry takes inline glue instead, you may never need this page at
all — the addresses travel with the domain command.

Each method returns a [`Response`](responses.md), and a result code of 2000 or higher is raised as
an exception — see [Errors](errors.md).

## Subordinate and external hosts

The distinction decides what the registry will accept, so it is worth getting straight before the
first `create`:

| | Lives | Glue addresses |
|---|---|---|
| **Subordinate** | under a domain in a zone the registry serves, e.g. `ns1.example.com.ua` | **required** — a create without one is 2003 |
| **External** | under a domain the registry does not hold, e.g. `ns1.provider.net` | **refused** — its addresses live at its own registry, so sending any is 2306 |

Addresses must be public Internet addresses, and a host carries at most 13 of them; a fourteenth is
2001.

A client that always emits an address therefore has to stop doing that for external hosts. It is not
ignored — it is a refusal.

## The methods

| Method | EPP command |
|---|---|
| `check` | `<check><host:check>` |
| `info` | `<info><host:info>` |
| `create` | `<create><host:create>` |
| `update` | `<update><host:update>` |
| `delete` | `<delete><host:delete>` (optionally with the registry's forced-delete extension) |

`update_builder(name)` assembles the update step by step; see [Builders](builders.md).

---

## check

```python
client.host.check(names: List[str]) -> Response
```

One `<host:name>` per name, **at most 10 per command** — an eleventh is refused with 2001.

```python
r = client.host.check(["ns1.example.com.ua", "ns2.example.com.ua"])

r.availability()                          # {'ns1.example.com.ua': False, 'ns2.example.com.ua': True}
r.is_available("ns2.example.com.ua")      # True
r.unavailable_reason("ns1.example.com.ua")# 'in use', or None
```

`is_available()` returns `None` when the reply said nothing about that name, which is not the same
as "taken".

| Code | Meaning |
|---|---|
| 1000 | answered; read `availability()` |
| 2001 | more than 10 names in one command |

---

## info

```python
client.host.info(name: str) -> Response
```

Reads a host object. There is no `auth_info` argument: RFC 5732 gives a host no authorisation code
of its own, because a host is authorised through the domain it lives under.

```python
h = client.host.info("ns1.example.com.ua")

h.object_name()      # 'ns1.example.com.ua'
h.roid()             # the registry's own object id
h.statuses()         # ['linked'] once a domain uses it, else ['ok']
h.host_addresses()   # [{'ip': '203.0.113.10', 'version': 'v4'},
                     #  {'ip': '2001:db8::10',  'version': 'v6'}]
h.sponsor()          # clID
h.created_by()       # crID           h.created_date()   # crDate
h.updated_by()       # upID, or None  h.updated_date()   # upDate, or None
```

An **external host returns no addresses**, and that is the correct answer rather than a missing one
— only a host inside a served zone carries glue.

The status `linked` means at least one domain uses this host as a nameserver. It is the status that
blocks [`delete`](#delete).

| Code | Meaning |
|---|---|
| 1000 | answered |
| 2303 | no such host |

---

## create

```python
client.host.create(name: str, addresses: Optional[List[str]] = None) -> Response
```

Creates a host object. Not billable.

```python
# Subordinate host: glue required.
client.host.create("ns1.example.com.ua", ["203.0.113.10", "2001:db8::10"])

# External host: no addresses at all.
client.host.create("ns1.provider.net")
```

IPv4 and IPv6 are told apart from the literal itself, so each address goes out with the right
`ip="v4"` or `ip="v6"` attribute without your saying which. An address the client cannot parse as
either is sent labelled `v4` and refused by the registry with 2005 — the value was already wrong,
and the refusal names it.

Reading the reply is worth doing even here, because it confirms which name the registry recorded:

```python
r = client.host.create("ns1.example.com.ua", ["203.0.113.10"])
r.object_name()     # 'ns1.example.com.ua'
r.created_date()    # crDate
```

| Code | Meaning |
|---|---|
| 1000 | created |
| 2001 | more than 13 addresses |
| 2003 | a subordinate host with no address |
| 2005 | a malformed address or name |
| 2302 | that host already exists |
| 2306 | addresses on an external host, or another registry rule |

---

## update

```python
client.host.update(name: str, *,
                   add_addresses: Optional[List[str]] = None,
                   rem_addresses: Optional[List[str]] = None,
                   add_statuses: Optional[List[str]] = None,
                   rem_statuses: Optional[List[str]] = None,
                   new_name: Optional[str] = None) -> Response
```

An update is a **delta**: addresses and statuses you do not mention are left alone. `add_*` and
`rem_*` build one `<host:add>` and one `<host:rem>` block between them, and a block is built only if
you gave it something.

```python
# Move a nameserver to a new address without a gap: add the new one, then drop the old one.
client.host.update("ns1.example.com.ua",
                   add_addresses=["203.0.113.11", "2001:db8::11"],
                   rem_addresses=["203.0.113.10"])

# Freeze the object against changes.
client.host.update("ns1.example.com.ua", add_statuses=["clientUpdateProhibited"])
```

The client-settable statuses are `clientDeleteProhibited` and `clientUpdateProhibited`; the
`server*` counterparts belong to the registry.

The rules from [create](#create) still hold on an update: an external host may not gain addresses
(2306), and a subordinate one may not be left with none (2003). Removing a host's last address is
therefore a change that will be refused, not one that quietly undelegates it.

### There is no rename

**A host cannot be renamed.** The registry reads only `<host:add>` and `<host:rem>`; a `<host:chg>`
block carrying a new name is not applied. A frame that asks for an address change and a rename
together would apply the address change, drop the rename, and still answer 1000 — a success you
could act on for weeks before noticing the name never moved.

So `new_name` exists only to refuse:

```python
client.host.update("ns1.example.com.ua", new_name="ns9.example.com.ua")
# ValidationException: host rename is not supported by this registry (host:chg is ignored) —
# create the new host, re-point the domains with domain:update, then delete the old one
```

Nothing is sent. The answer comes from your own code, where it can say what to do instead — and
what to do instead is three commands:

```python
old, new = "ns1.example.com.ua", "ns9.example.com.ua"

# 1. Create the replacement, with the same glue.
addresses = [a["ip"] for a in client.host.info(old).host_addresses()]
client.host.create(new, addresses)

# 2. Re-point every domain that uses the old one. There is no "which domains use this host"
#    command, so this list comes from your own records.
for domain in domains_using(old):
    client.domain.update(domain, add={"ns": [new]}, rem={"ns": [old]})

# 3. Only now delete the old host — while a domain still references it the delete is 2305.
client.host.delete(old)
```

Add before you remove, in that order, in one command per domain: a domain left with no nameservers
in between stops resolving, and `<host:add>` and `<host:rem>` in the same `domain:update` are
applied as one change.

| Code | Meaning |
|---|---|
| 1000 | applied |
| 2001 | more than 13 addresses |
| 2003 | a subordinate host would be left with no address |
| 2303 | no such host |
| 2304 | a status forbids it |
| 2306 | addresses on an external host, or a status that is not client-settable |

---

## delete

```python
client.host.delete(name: str, force: bool = False) -> Response
```

```python
client.host.delete("ns1.example.com.ua")
```

**A host still used as a nameserver by any domain cannot be deleted** — the registry answers 2305,
and `info()` shows the status `linked`. Detach it from those domains with
[`domain.update`](domains.md#update) first.

### Forced delete

`force=True` adds the registry's native extension `<registry:delete><registry:deleteNS confirm="yes"/>`, which
removes the host from the nameserver set of **every domain that referenced it** and then deletes it,
in one command:

```python
client.host.delete("ns1.example.com.ua", force=True)
```

That is a convenience with a cost worth stating plainly: it changes the delegation of domains you
did not name in the command. A domain left with fewer nameservers than the zone's minimum stops
being delegated, and the registry does not ask twice — `confirm="yes"` is the confirmation. Use it
to retire a nameserver you have already replaced everywhere, and read back a
[`domain.info`](domains.md#info) for the affected domains afterwards to confirm what they are left
with.

A forced delete that could not complete the detach answers 2400.

| Code | Meaning |
|---|---|
| 1000 | deleted |
| 2303 | no such host |
| 2304 | a status forbids it (`clientDeleteProhibited`) |
| 2305 | still used as a nameserver by a domain (a plain delete) |
| 2400 | the forced detach could not complete — may be transient; `is_retryable()` is true |

---

See also: [Domains](domains.md) · [Contacts](contacts.md) · [Poll](poll.md) ·
[Responses](responses.md) · [Builders](builders.md) · [Errors](errors.md)

[Back to the index](README.md)
