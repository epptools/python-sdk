# Responses

Every command returns a `Response`. It wraps the reply the registry sent and answers questions about
it, so reading an answer never means indexing into a dict by a string you had to guess, and never
means walking XML.

Element lookups are namespace-agnostic — they match on the element's local name — so a change in the
prefixes a reply uses never breaks an accessor.

Two conventions hold throughout:

- An accessor that has nothing to report returns `None`, an empty list or an empty dict. It does not
  raise. Which of the three, per accessor, is in the tables below.
- **`None` means "the answer said nothing about this"**, which is not the same as a negative. The
  distinction matters most on `is_available()`, and the line that registers a domain must not treat
  the two alike.

## Dates and money

- **Dates come back as the registry's own string** — `2027-04-01T09:15:00Z`, or with an offset —
  never a `datetime`. The registry decides which calendar day a renewal lands on, and re-formatting
  through a local timezone is how a client ends up displaying, and renewing against, the day before.
- **Money comes back as an exact decimal string**, never a `float`. `0.1 + 0.2` is not `0.3` in
  binary floating point, and a balance summed that way drifts. Use `decimal.Decimal` for arithmetic
  and keep the string for storage.

## Result and transaction ids

| Accessor | Returns | When the answer carries nothing |
|---|---|---|
| `code() -> int` | The EPP result code: 1000, 1001, 2303 … | `0` for a greeting or any frame with no `<result>` |
| `message() -> Optional[str]` | The human-readable `<result><msg>` | `None` |
| `message_lang() -> Optional[str]` | The language of that message: `en`, `uk`, `ua`, `ru` | `None` |
| `is_success() -> bool` | `True` for any 1xxx code | `False` |
| `is_pending() -> bool` | `True` only for 1001 — accepted, completing offline | `False` |
| `is_greeting() -> bool` | `True` when this frame is a `<greeting>` | `False` |
| `cl_trid() -> Optional[str]` | The client transaction id echoed back | `None` |
| `sv_trid() -> Optional[str]` | The registry's own identifier for the operation | `None` |

Store `sv_trid()` against the object the command was about. It is what support looks an operation up
by. `message()` is the result banner — on a poll reply it is the same constant sentence every time,
and the notice text is `queue_message()`.

## Object identity — any object

These answer for a domain, a host or a contact alike.

| Accessor | Returns | When the answer carries nothing |
|---|---|---|
| `object_name() -> Optional[str]` | The object this response is about: a domain name, a host name, or a contact **handle** | `None` |
| `roid() -> Optional[str]` | The registry's own identifier for the object | `None` |
| `sponsor() -> Optional[str]` | `clID` — the registrar the object belongs to now | `None` |
| `created_by() -> Optional[str]` | `crID` — the registrar that created it | `None` |
| `created_date() -> Optional[str]` | `crDate`, as the registry wrote it | `None` |
| `updated_by() -> Optional[str]` | `upID` — who last changed it | `None` when it has never been changed, or when you do not sponsor it |
| `updated_date() -> Optional[str]` | `upDate` | `None` when never changed |
| `transfer_date() -> Optional[str]` | `trDate` — when it last changed hands | `None` when it never has |
| `auth_info() -> Optional[str]` | The `<authInfo><pw>` transfer secret | `None` when the registry withheld it |
| `statuses() -> List[str]` | Status values: `["ok"]`, `["clientHold", "pendingTransfer"]` … | `[]` |

`object_name()` is taken from the object block itself, so on a `contact:info` it gives you the
handle and not the registrant's personal name. It is also how you read the handle the registry
minted for a `create_auto()` contact — that reply is the only place that handle appears.

`auth_info()` is the secret that lets **any** registrar take the domain away from you. Never log it,
never put it in a support ticket, and roll it after you have passed it to a customer.

`updated_by()` is worth reconciling against your own records: a change you did not make means it came
from the registry side or from a support action, not from your system.

## Domain

| Accessor | Returns | When the answer carries nothing |
|---|---|---|
| `expiry_date() -> Optional[str]` | `exDate`, exactly as the registry wrote it | `None` |
| `registrant() -> Optional[str]` | The registrant handle | `None` |
| `contacts() -> Dict[str, List[str]]` | Role contacts: `{"admin": ["c-1"], "tech": ["c-1", "c-2"]}`. The registrant is **not** included | `{}` |
| `contacts_for(role: str) -> List[str]` | The handles in one role, matched case-insensitively | `[]` when nobody holds that role — a legitimate answer |
| `admin_contacts() -> List[str]` | The administrative contacts | `[]` |
| `tech_contacts() -> List[str]` | The technical contacts | `[]` |
| `billing_contacts() -> List[str]` | The billing contacts | `[]` |
| `all_contacts() -> List[str]` | Every handle attached in any capacity, registrant included, de-duplicated | `[]` |
| `nameservers() -> List[str]` | The nameserver names, lower-cased, whichever EPP model the registry used | `[]` |
| `nameserver_addresses() -> Dict[str, List[Dict[str, str]]]` | Inline glue keyed by nameserver name: `{"ns1.example.com.ua": [{"ip": "192.0.2.1", "version": "v4"}]}` | `{}` |
| `subordinate_hosts() -> List[str]` | Host objects living **under** this domain, lower-cased | `[]` |
| `rgp_status() -> List[str]` | RGP status values, e.g. `["redemptionPeriod"]` (RFC 3915) | `[]` |
| `license() -> Optional[str]` | A trademark or licence number, from the registry's own extension | `None` |
| `prices() -> Dict[str, Dict[str, str]]` | Renewal and restore price hints from a `domain:info`, keyed by operation: `{"renewal": {"value": "…", "currency": "UAH"}}` | `{}` |
| `price_channel() -> Optional[str]` | An opaque id naming which row of the registry's published price catalogue those prices come from | `None` |
| `registrar_of_record() -> Optional[str]` | The handle the registry's WHOIS and RDAP publish as the registrar | `None` |
| `transfer() -> Optional[Dict[str, str]]` | A transfer in full — see below | `None` when the reply carries no `trnData` |
| `transfer_status() -> Optional[str]` | Just the status: `"pending"`, `"serverApproved"`, `"clientRejected"` … | `None` |
| `ds_records() -> List[Dict[str, object]]` | DNSSEC DS records: `[{"keyTag": …, "alg": …, "digestType": …, "digest": "…"}]` (RFC 5910) | `[]` |
| `key_records() -> List[Dict[str, object]]` | DNSSEC keys: `[{"flags": …, "protocol": …, "alg": …, "pubKey": "…"}]` | `[]` |
| `is_signed() -> bool` | Whether any DNSSEC data is present | `False` |

```python
info = client.domain.info("example.com.ua")

info.nameservers()              # ["ns1.example.com.ua", "ns2.example.com.ua"]
info.tech_contacts()            # ["acme-ns1"]
info.subordinate_hosts()        # ["ns1.example.com.ua"]
```

`nameservers()` covers both EPP models — a reference to a host object, and the name inlined with its
glue — because a client that reads only one of them sees an empty list against a registry using the
other and concludes the domain has no delegation at all. `nameserver_addresses()` returns the glue
only where the registry inlined it; an empty result there does **not** mean the domain is
undelegated, it means you fetch the addresses with a `host.info()` per name.

`subordinate_hosts()` is what to check before a delete: the registry refuses to delete a domain while
host objects live under it.

`transfer()` answers who asked, when, who must act, and by when:

```python
t = client.domain.transfer("query", "example.com.ua")
t.transfer()
# {'status': 'pending', 'requested_by': 'ACME', 'requested_at': '2026-08-14T10:00:00Z',
#  'acting_client': 'EXAMPLE', 'act_by': '2026-08-19T10:00:00Z', 'expiry_date': '2028-04-01T09:15:00Z'}
```

`transfer_status()` alone says a transfer is pending without saying whose, or how long you have —
and `act_by` is the deadline after which the registry decides for you.

`registrar_of_record()` is not `sponsor()`. `sponsor()` names the account the object belongs to —
yours, inside your own reseller hierarchy; `registrar_of_record()` names the party the registry
publishes, which for a reseller is somebody else.

## Host

| Accessor | Returns | When the answer carries nothing |
|---|---|---|
| `host_addresses() -> List[Dict[str, str]]` | This host object's glue: `[{"ip": "192.0.2.1", "version": "v4"}, …]` | `[]` |

Only a host inside the zone it serves carries glue. For an external nameserver the registry returns
none, and that is normal rather than a missing answer. The addresses are scoped to the host object
itself, so a domain's per-nameserver glue stays in `nameserver_addresses()` where you can tell which
address belongs to which name.

## Contact

| Accessor | Returns | When the answer carries nothing |
|---|---|---|
| `email() -> Optional[str]` | The e-mail address | `None` |
| `voice() -> Optional[str]` | The voice number, in the EPP `+CC.NNNN` form | `None` |
| `fax() -> Optional[str]` | The fax number, same form | `None` |
| `postal_info() -> Dict[str, Dict[str, object]]` | Addresses keyed by form: `"int"` (ASCII) and `"loc"` (local script). Each holds `name`, `org`, `street` (a list), `city`, `sp`, `pc`, `cc` | `{}` |
| `disclose() -> Optional[Dict[str, object]]` | `{"flag": True, "elements": ["email", "voice"]}` (RFC 5733) | `None` when the contact expresses no preference and registry policy alone applies |

A contact may carry either postal form or both. Read `"int"` when you need something safe to print
anywhere; read `"loc"` for the address as the registrant actually wrote it.

In `disclose()`, `flag` `True` means the listed elements **may** be published and `False` means they
must be withheld; everything not listed takes the opposite of the flag. The list is meaningless
without the flag, so never read one without the other. Postal `name`, `org` and `addr` appear per
form, as `name:int` or `addr:loc`.

## Check and money

| Accessor | Returns | When the answer carries nothing |
|---|---|---|
| `availability() -> Dict[str, bool]` | The whole `*:check` map: name or handle to availability | `{}` |
| `is_available(name: str) -> Optional[bool]` | One name's availability, matched case-insensitively | **`None`** — the answer said nothing about it, which is not "taken" |
| `unavailable_reason(name: str) -> Optional[str]` | Why a name is unavailable: `"In use"`, `"Reserved"` | `None` when it is available, or when the registry gave no reason |
| `fees() -> Dict[str, object]` | The RFC 8748 price table — see below | `{}` |
| `fee_for(name: str, operation: str, years: int = 1) -> Optional[str]` | One quoted price, as an exact decimal string | `None` when the answer carried no such quote |
| `fee_class(name: Optional[str] = None) -> Optional[str]` | The registry's fee class: `"premium"`, `"standard"` | `None` when the answer declared none |
| `is_premium(name: Optional[str] = None) -> bool` | Whether the name is priced outside the standard list | `False` |
| `charged_fee() -> Optional[Dict[str, str]]` | What a transform actually charged: `{"currency": "UAH", "fee": "100.00"}` | `None` |
| `fee_amount() -> Optional[str]` | Just the amount from `charged_fee()` | `None` |
| `fee_currency() -> Optional[str]` | Just the currency from `charged_fee()` | `None` |
| `balance() -> Optional[Dict[str, str]]` | `{"creditLimit": …, "balance": …, "availableCredit": …}` | `None` when this is not a balance response |
| `credit_limit() -> Optional[str]` | The credit extended beyond a zero balance | `None` |
| `current_balance() -> Optional[str]` | Funds on the account right now | `None` |
| `available_credit() -> Optional[str]` | What you can actually spend — balance plus remaining credit | `None` |

`fees()` is keyed by name, plus a `_currency` key for the quote's currency:

```python
r = client.domain.check(["example.com.ua"], fee={"create": [1, 2, 5]}, currency="UAH")
r.fees()
# {'_currency': 'UAH',
#  'example.com.ua': {
#      'avail': True,
#      'reason': None,
#      'class': 'premium',                       # present only when the registry declared one
#      'commands': {'create': {'years': 1, 'fee': '100.00'}},
#      'periods': [{'op': 'create', 'years': 1, 'fee': '100.00'},
#                  {'op': 'create', 'years': 2, 'fee': '195.00'},
#                  {'op': 'create', 'years': 5, 'fee': '480.00'}]}}

r.fee_for("example.com.ua", "create", 5)      # '480.00'
```

Asking one operation at several periods brings back one quote per period. `commands` keeps the first
of them, so a caller reading `commands["create"]` still gets an answer; `periods` has the lot, and
`fee_for()` is how you pick one out. Read `transfer` and `restore` back at one year — they are
one-year operations however many years you asked about. Amounts here are illustrative, not the
registry's tariff.

`avail` `False` on an entry comes with a `reason`: the zone is not served, or the currency you asked
for is not one the registry prices in — never a converted guess.

`is_premium()` returning `False` is not a promise of the standard price; it means the answer declared
no special class. Charge from `fees()`, and cap the transform itself with a fee agreement so a name
that is priced differently refuses at 2004 instead of billing you the difference. See
[Balance](balance.md).

## Poll

| Accessor | Returns | When the answer carries nothing |
|---|---|---|
| `message_id() -> Optional[str]` | The queued message id to pass to `poll.ack()` | `None` — there is no notice in this reply |
| `message_count() -> int` | How many messages remain in the queue | `0` |
| `queue_message() -> Optional[str]` | **The notice text**, from `<msgQ><msg>` | `None` |
| `queue_message_lang() -> Optional[str]` | The notice's language: `uk`, `ru`, `en` | `None` |
| `queue_date() -> Optional[str]` | When the notice was queued | `None` |
| `pending_action_data() -> Optional[Dict[str, object]]` | The outcome of an operation the registry processed offline | `None` when the notice carries none |

**`queue_message()` is the notice; `message()` is not.** `message()` returns the command-result
banner — "Command completed successfully; ack to dequeue" — which is identical on every poll reply.
Reading a notice with `message()` hands you that constant string while the real content is discarded,
and the ack that follows destroys it at the registry permanently.

`pending_action_data()` is how a deferred command reports back. You send a `create`, get 1001 with an
svTRID, and the answer arrives later in the queue:

```python
notice = client.poll.request()
pan = notice.pending_action_data()
# {'object': 'example.com.ua', 'success': True,
#  'clTRID': 'PYTHON-SDK-20260814101500-4821-0007',
#  'svTRID': 'SRV-19700101103512-24191-00007',
#  'date': '2026-08-14T10:20:00Z'}
```

| Key | Why it matters |
|---|---|
| `success` | **The only thing that says whether it worked.** The surrounding 1301 means "here is a message", not "your operation succeeded" |
| `svTRID` / `clTRID` | The transaction ids of the **original** command. Match the svTRID against the one you were given with the 1001 to know which pending operation this answers — poll is a queue, not necessarily the most recent one |
| `date` | When the action completed, not when you polled |
| `object` | The domain name or contact handle it was about |

See [Poll](poll.md) for the queue itself and the ordering rule that keeps a notice from being lost.

## Session security and the greeting

| Accessor | Returns | When the answer carries nothing |
|---|---|---|
| `security_events() -> List[Dict[str, str]]` | RFC 8807 warnings about **this session** — each with `text`, and whichever of `type`, `name`, `level`, `exDate`, `value`, `duration`, `lang` the event carries | `[]` on a healthy session |
| `service_obj_uris() -> List[str]` | Greeting: the object services the server advertises | `[]` |
| `service_ext_uris() -> List[str]` | Greeting: the extension services the server advertises | `[]` |

```python
greeting = client.connect()
if Namespaces.FEE in greeting.service_ext_uris():
    ...                                  # this endpoint quotes prices
```

An empty `security_events()` is a clean session, so treat any entry as something to act on. The
server returns them only to a client that took part in the extension — see
[Session → Login security](session.md#login-security-rfc-8807).

## Diagnostics on a failure

| Accessor | Returns | When the answer carries nothing |
|---|---|---|
| `ext_values() -> List[Dict[str, object]]` | Every `<extValue>`, unpacked: `element`, `namespace`, `text`, `values`, `xml`, `reason`, `lang` | `[]` |
| `error_reasons() -> List[str]` | Just the `<extValue><reason>` texts | `[]` |

`error_reasons()` gives you the wording; `ext_values()` gives you the **subject**, which on a command
carrying five names is the part you need — "EPP 2302: Object exists" leaves you to work out which of
the five, and the answer is sitting in `<extValue>`.

```python
for ext in response.ext_values():
    print(ext["element"], ext["text"], "—", ext["reason"])
# name bad..name — Invalid label
```

The offending element is usually a leaf, and then `text` is the answer. Where it is a container,
`text` is empty because a container has no character data of its own: `values` carries the children
by name and `xml` is the element as it arrived, if you would rather re-parse it.

The same information reaches you through the exception: `CommandException.subject()` and
`.reasons()`. See [Errors](errors.md).

## Raw access

| Accessor | Returns | When the answer carries nothing |
|---|---|---|
| `value(local_name: str) -> Optional[str]` | The first element anywhere with that local name, trimmed | `None` |
| `values(local_name: str) -> List[str]` | Every element with that local name, trimmed | `[]` |
| `res_data() -> Optional[ET.Element]` | The `<resData>` element, for custom parsing | `None` |
| `raw -> str` | Property: the response XML exactly as it arrived | the frame is always present |
| `root -> ET.Element` | Property: the parsed `ElementTree` root | always present |
| `Response.from_xml(xml: str) -> Response` | Classmethod: parse a frame you obtained yourself | raises `ConnectionException` on malformed XML |

`value()` and `values()` are the general form the named accessors are built on — reach for them when
a registry extension carries something this manual does not name:

```python
response.value("exDate")        # same as expiry_date()
response.values("hostObj")      # every <domain:hostObj> in the reply
```

`Response.from_xml()` refuses a frame carrying a DOCTYPE outright, with `ConnectionException`. An EPP
response never has one, and a parser that expands internal entities is how a hostile endpoint turns a
frame inside the 1 MiB budget into a client that runs out of memory.

---

[← Manual index](README.md)
