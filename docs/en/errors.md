# Errors

Every failure this library raises extends `EppException`, so one `except` catches everything:

```python
from epptools.exceptions import EppException

try:
    client.domain.create("example.com.ua", years=1, registrant="C1")
except EppException as exc:
    log.error("EPP failed: %s", exc)
```

Beyond that, **a class exists where the right next step differs, and nowhere else**. There is no
class per result code, because you would not write different code for most of them; there is a class
wherever the answer is "top up the account", "reconnect", "pick another name" or "fix the
deployment", because those are four different programs.

`EppException` extends `RuntimeError`, so it is not caught by a bare `except ValueError` — with two
deliberate exceptions, noted below.

## The exception hierarchy

```
EppException                     (RuntimeError)
├── ConnectionException          transport: TLS, timeout, framing
├── ConfigException              (also ValueError) this client is set up wrong
├── ValidationException          (also ValueError) this call's arguments are wrong
└── CommandException             the registry refused (a result code >= 2000)
    ├── AuthenticationException  2200 — the login itself failed
    ├── InsufficientFundsError   2104
    ├── AuthorizationError       2201, 2202
    ├── ObjectExistsError        2302
    ├── ObjectDoesNotExistError  2303
    ├── ObjectStatusError        2304, 2305
    ├── PolicyError              2306, 2308
    └── SessionError             2500, 2501, 2502
```

| Catch | Raised when | Codes | What to do next |
|---|---|---|---|
| `ValidationException` | a value in **this call** cannot be used; nothing was sent | — | Fix the arguments. The next call with different arguments works. |
| `ConfigException` | the **client** is set up wrong: no host, no credentials, a password this server cannot carry | — | Fix the deployment. Every call fails the same way until you do. |
| `ConnectionException` | TLS, timeout, framing, a desynchronised stream, malformed XML from the server | — | The connection is finished. `connect()` and `login()` again — and see [When the outcome is unknown](#when-the-outcome-is-unknown) before resending anything. |
| `AuthenticationException` | `login()` was refused | 2200 | The clID or password is wrong. Do not loop: repeated failures get an address blocked. |
| `InsufficientFundsError` | the account cannot pay for this operation | 2104 | **Stop the batch.** Alert whoever funds the account, top up, resume. Every later billable command fails identically. |
| `AuthorizationError` | the object exists but not for you, or the `authInfo` does not match | 2201, 2202 | Not a retry. Check that you sponsor the object, and that the transfer code is current — it ages. |
| `ObjectExistsError` | already registered | 2302 | Pick another name or handle. Retrying cannot make it free. Use `create_auto()` to avoid handle collisions entirely. |
| `ObjectDoesNotExistError` | no such domain, handle or host | 2303 | A stale identifier or a typo. Re-read your records; do not create blindly. |
| `ObjectStatusError` | a status or an association is in the way | 2304, 2305 | Clear what blocks you — a `clientHold`, a linked contact, a subordinate host — then send the same command again. |
| `PolicyError` | the registry's own rules refuse the value | 2306, 2308 | The command is well-formed and you may send it; the value is not allowed. Change the request. |
| `SessionError` | the server is ending the session | 2500, 2501, 2502 | Reconnect and log in again. The command itself may be perfectly good — 2502 is a session limit, not a bad password. |
| `CommandException` | any other code of 2000 or more | — | Branch on `.epp_code`. |

Every one of the specific classes is still a `CommandException`, so an `except CommandException`
placed last catches whatever you did not name.

```python
from epptools.exceptions import (
    CommandException, InsufficientFundsError, ObjectExistsError, SessionError,
)

try:
    client.domain.create(name, years=1, registrant="C1")
except InsufficientFundsError:
    stop_the_batch()
except ObjectExistsError as exc:
    taken.append(exc.subject() or name)
except SessionError:
    reconnect()
except CommandException as exc:
    log.warning("EPP %d on %s: %s", exc.epp_code, name, exc)
```

`AuthenticationException` is what `login()` raises for 2200. A login refused for any other reason
raises the class that fits it — a 2502 session limit, a 2501 server shutdown, a 2307 service URI the
server does not offer, a 2002 second login on one connection — because calling them all an
authentication failure sends you to rotate a password that was never the problem.

## A bad argument is not a bad configuration

`ValidationException` and `ConfigException` look similar and need opposite responses, which is why
they are separate classes:

| | `ValidationException` | `ConfigException` |
|---|---|---|
| What is wrong | one call's arguments | the client, the deployment, the credentials |
| Whose mistake | usually the request being served | usually the operator's |
| Who should hear about it | the caller — a 400 to your API client, a message on a form | an alert to whoever runs the service |
| Does the next call work | yes, with different arguments | no. Every call fails until the deployment changes |

Sharing one class leaves a service guessing between them, and guessing wrong reports an operator's
own misconfiguration to a customer as their mistake — or hides a total outage behind a "bad request"
in somebody else's log.

Both are also `ValueError`s, so an `except ValueError` you already have keeps catching them, the way
`json.JSONDecodeError` is also a `ValueError`.

### What raises ValidationException

Nothing has been sent when one of these is raised — the socket is untouched and the client is still
usable:

| Raised by | Because |
|---|---|
| an unknown key in `chg` or `sec_dns` | a key nobody reads is a change that does not happen behind a 1000. The message names the closest key it recognises |
| a fee amount that is not a plain decimal | `'100,00'`, `'$100'` — see [Balance](balance.md#capping-what-you-agree-to-pay) |
| more than 20 fee entries in one `check` | the per-frame limit |
| a mixture of nameserver models in one command | RFC 5731 makes `<domain:ns>` a choice |
| `host.update(new_name=...)` | this registry has no rename; the message says what to do instead |
| `contact.create()` with no e-mail | RFC 5733 requires one |
| `auth_info` and `clear_auth_info` in one `chg` | the schema cannot express both |
| `remove_all_dnssec()` with `rem_ds_record()` | likewise |
| a builder's second `send()` | one builder carries one command |
| an `async def` handler passed to `poll.drain()` | it would ack every notice before any was processed |
| an empty contact role, an empty digest, an empty public key, an undisclosable field name | the value cannot go on the wire |

Each of these would otherwise be an opaque refusal from the registry — often a bare 2001 naming no
field — arriving after the command was attempted, or, worse, a 1000 for a command that quietly did
less than you asked.

### What raises ConfigException

| Raised by | Because |
|---|---|
| `Config(host="")` at `connect()` | there is nowhere to connect to |
| an empty `clid` or `password` at `login()` | the message says which of the two is empty, without printing either |
| a password outside 6–128 characters | checked before a socket is opened |
| a password longer than 16 characters against a server that does not offer RFC 8807 | the base `<pw>` element cannot carry it; the server would answer a bare 2001 |
| `Config.from_dict()` with an unknown key | a misspelt setting is a setting that is not applied |

See [Session → Config](session.md#config-field-by-field).

## What a CommandException carries

| Member | Type | What it is |
|---|---|---|
| `.epp_code` | `int` | The result code the registry sent |
| `.response` | `Response` | The whole parsed reply — `sv_trid()`, `ext_values()`, everything |
| `.subject()` | `Optional[str]` | The object the registry objected to, when it named one |
| `.reasons()` | `List[str]` | The extra `<extValue><reason>` text, beyond the one-line message |
| `.is_retryable()` | `bool` | Whether sending the very same command again could succeed |
| `str(exc)` | `str` | `EPP 2302: Object exists ('taken.com.ua')` |

```python
try:
    client.domain.check(["example1.com.ua", "example2.com.ua", "taken.com.ua"])
except CommandException as exc:
    exc.epp_code               # 2302
    exc.subject()              # 'taken.com.ua' — which of the three
    exc.reasons()              # ['Already registered']
    exc.response.sv_trid()     # the id support looks the operation up by
```

`subject()` is the part that makes a multi-name command actionable: "EPP 2302: Object exists" leaves
you to work out which of the three, and the answer is sitting in `<extValue>`. It is `None` when the
registry named nothing, which is common, so keep your own fallback — `exc.subject() or name`.

Store `exc.response.sv_trid()` with the failure. It is the value the registry's support desk can
look up; your clTRID means nothing to anyone but you.

## Retrying

```python
exc.is_retryable()
```

**True for exactly four codes**, and false for everything else:

| Code | Class | Why a retry can work |
|---|---|---|
| 2400 | `CommandException` | the command failed for a reason on the server's side, at that moment |
| 2500 | `SessionError` | the server is closing the connection — retry after reconnecting |
| 2501 | `SessionError` | likewise |
| 2502 | `SessionError` | the session limit was reached — retry after reconnecting, or with fewer sessions |

Everything else is false on purpose. Retrying a 2302 cannot make the name free; retrying a 2104
cannot pay for it; retrying a 2306 cannot change the registry's policy. A loop that treats every
failure as transient turns one refusal into a rate-limit ban, and an address blocked for hammering
is a worse outage than the failure that started it.

The three of the four that are `SessionError`s are retryable **after** you reconnect. Retrying them
on the connection that has already failed sends into a socket the server has finished with:

```python
for name in names:
    try:
        client.domain.create(name, years=1, registrant="C1")
    except SessionError:
        client.disconnect()
        client.connect()
        client.login()
        retry_later.append(name)          # reconciled first — see below
    except CommandException as exc:
        if not exc.is_retryable():
            raise
        retry_later.append(name)
```

Back off between attempts, and cap them. Two retries a few seconds apart is a recovery; a tight loop
is a denial of service you are running against your own account.

## Reading codes instead of catching them

```python
client.throw_on_failure(False)     # returns the client, so it chains
response = client.domain.check(["example.com.ua"])
if not response.is_success():
    log.warning("EPP %d: %s", response.code(), response.message())
```

`ResultCode` has a named constant for every code, so a branch does not have to spell out a number:

```python
from epptools import ResultCode

if response.code() == ResultCode.OBJECT_EXISTS:
    ...
```

Two things keep raising even with the switch off, because there is no useful `Response` to hand back
instead:

- **`login()`**, on any code other than 1000. There is no session to continue into.
- **`poll.drain()`**, when a poll reply is neither a notice nor an empty queue. Reading a refusal as
  "drained" would report success while nothing had been read.

Switching it off means every failure is now yours to notice. A `create` whose 2104 nobody checked is
a domain your system believes it registered.

## The result codes in full

`1xxx` is success. `2xxx` is refusal, and — apart from the unknown-outcome case below — nothing was
changed and nothing was charged.

### Success

| Code | `ResultCode` | Meaning | What to do |
|---|---|---|---|
| 1000 | `SUCCESS` | done | continue |
| 1001 | `SUCCESS_PENDING` | accepted, completing offline | **do not resend.** Record the svTRID; the outcome arrives as a [poll notice](poll.md#the-outcome-of-a-deferred-action) |
| 1300 | `SUCCESS_NO_MESSAGES` | the poll queue is empty | stop draining |
| 1301 | `SUCCESS_ACK_TO_DEQUEUE` | a poll notice is attached | process it, then ack it |
| 1500 | `SUCCESS_END_SESSION` | the logout was accepted | disconnect |

### Protocol and syntax

| Code | `ResultCode` | Meaning | What to do |
|---|---|---|---|
| 2000 | `UNKNOWN_COMMAND` | the server does not know this command | check the verb; a raw frame is the usual cause |
| 2001 | `COMMAND_SYNTAX_ERROR` | the frame does not satisfy the schema | the message names no field: compare the frame against the RFC, or against a command the library builds |
| 2002 | `COMMAND_USE_ERROR` | right command, wrong moment — a second `login()` on one connection | fix the sequence |
| 2003 | `REQUIRED_PARAMETER_MISSING` | a required element is absent, or the command carries no change at all | supply it |
| 2004 | `PARAMETER_VALUE_RANGE_ERROR` | a value is out of range — a period, or a fee agreement that does not cover the price | see [Balance](balance.md#what-a-refusal-at-2004-means) |
| 2005 | `PARAMETER_VALUE_SYNTAX_ERROR` | a value is malformed: a bad label, a bad address, Cyrillic in an `int` postal block | fix the value |

### Unimplemented, and billing

| Code | `ResultCode` | Meaning | What to do |
|---|---|---|---|
| 2100 | `UNIMPLEMENTED_PROTOCOL_VERSION` | the login `<version>` must be 1.0 | not reachable through this library's own login |
| 2101 | `UNIMPLEMENTED_COMMAND` | the server does not implement this command | ask the registry what it serves |
| 2102 | `UNIMPLEMENTED_OPTION` | an option the server does not implement, such as an unsupported `lang` | change `Config.lang` |
| 2103 | `UNIMPLEMENTED_EXTENSION` | you used an extension this endpoint does not serve | check the greeting: `service_ext_uris()` |
| 2104 | `BILLING_FAILURE` | insufficient funds — **`InsufficientFundsError`** | stop the batch, top up, resume |
| 2105 | `NOT_ELIGIBLE_FOR_RENEWAL` | `cur_exp_date` does not match, or the domain cannot be renewed | re-read `expiry_date()`; this is reconciliation, not a retry |
| 2106 | `NOT_ELIGIBLE_FOR_TRANSFER` | the object cannot be transferred | check its statuses and the zone's rules |

### Security

| Code | `ResultCode` | Meaning | What to do |
|---|---|---|---|
| 2200 | `AUTHENTICATION_ERROR` | the login failed — **`AuthenticationException`** | fix the credentials; do not loop |
| 2201 | `AUTHORIZATION_ERROR` | the object is not yours — **`AuthorizationError`** | you do not sponsor it, or you may not send this transfer op |
| 2202 | `INVALID_AUTHORIZATION` | the `authInfo` is wrong — **`AuthorizationError`** | get a current code; a transfer code ages out 30 days after it was set |

### Object lifecycle

| Code | `ResultCode` | Meaning | What to do |
|---|---|---|---|
| 2300 | `OBJECT_PENDING_TRANSFER` | already pending transfer | wait for it, or `approve`/`reject`/`cancel` |
| 2301 | `OBJECT_NOT_PENDING_TRANSFER` | nothing to approve, reject, cancel or query | the transfer is already decided |
| 2302 | `OBJECT_EXISTS` | already registered — **`ObjectExistsError`** | pick another name or handle |
| 2303 | `OBJECT_DOES_NOT_EXIST` | no such object — **`ObjectDoesNotExistError`** | a stale identifier, a typo, or an already-acked poll id |
| 2304 | `OBJECT_STATUS_PROHIBITS_OPERATION` | a status forbids it — **`ObjectStatusError`** | clear the status, then repeat |
| 2305 | `OBJECT_ASSOCIATION_PROHIBITS_OPERATION` | an association forbids it — **`ObjectStatusError`** | detach the linked contact, host or domain first |
| 2306 | `PARAMETER_VALUE_POLICY_ERROR` | a registry rule refuses the value — **`PolicyError`** | change the request |
| 2307 | `UNIMPLEMENTED_OBJECT_SERVICE` | the object service, or the zone, is not served here | check the greeting |
| 2308 | `DATA_MANAGEMENT_POLICY_VIOLATION` | a data-management rule refuses it — **`PolicyError`** | change the request |

### Server

| Code | `ResultCode` | Meaning | What to do |
|---|---|---|---|
| 2400 | `COMMAND_FAILED` | the command failed on the server side | **retryable**; back off, then try once or twice more |
| 2500 | `COMMAND_FAILED_SERVER_CLOSING` | failed, and the connection is closing — **`SessionError`** | reconnect, log in, then retry |
| 2501 | `AUTHENTICATION_SERVER_CLOSING` | the server is closing the connection — **`SessionError`** | reconnect and log in |
| 2502 | `SESSION_LIMIT_EXCEEDED_SERVER_CLOSING` | too many concurrent sessions — **`SessionError`** | close sessions you are not using; always `logout()` |

## When the outcome is unknown

A read timeout, a dropped connection or a `ConnectionException` in the middle of a `create`,
`renew`, `transfer` or `restore` leaves a genuinely unknown outcome. The registry may have carried
the command out and billed you before the reply was lost. This library cannot tell the difference,
and neither can you from the exception: there is no reply to read.

> **Do not simply retry.** A blind retry is how a domain gets registered — and paid for — twice.

Ask the registry what is true instead, on a fresh connection, and reconcile from the answer:

| The command that failed | How to find out what happened | Retry only if |
|---|---|---|
| `domain.create` | `domain.info(name)` | the domain does not exist, or exists under another sponsor |
| `domain.renew` | `domain.info(name)`, compare `expiry_date()` with what you expected | the expiry is still the old one |
| `domain.transfer("request", …)` | `domain.transfer("query", name)` | no transfer is pending |
| `domain.restore` | `domain.info(name)`, read `rgp_status()` | the domain is still in `redemptionPeriod` |
| `contact.create` | `contact.info(id)` — or nothing, for `create_auto()` | the handle does not exist |

```python
from epptools.exceptions import ConnectionException, ObjectDoesNotExistError

try:
    created = client.domain.create(name, years=1, registrant="C1", fee=price)
except ConnectionException:
    # The connection is finished; the command's fate is not known.
    client.disconnect()
    client.connect()
    client.login()

    try:
        info = client.domain.info(name)
    except ObjectDoesNotExistError:
        created = client.domain.create(name, years=1,          # it really did not happen
                                       registrant="C1", fee=price)
    else:
        if info.sponsor() == my_clid:
            book_as_registered(name, info.expiry_date())       # it did happen; do not resend
        else:
            alert_operator("%s exists and belongs to %s" % (name, info.sponsor()))
```

Three things this shows, and each is deliberate:

- **The check runs on a new connection.** A `ConnectionException` means the byte stream is at an
  unknown offset; the socket is finished and every later call on it raises.
- **`create_auto()` is the one case you cannot reconcile.** Every call mints a fresh handle, so a
  second attempt is a second contact rather than a collision — which is exactly why the handle
  appears only in the reply you lost. Reconcile a lost `create_auto()` by hand.
- **A failure whose outcome you cannot determine deserves an operator's attention**, not an
  automatic second attempt. Alert on it; do not fold it into the retry queue.

The same reasoning applies to a **1001**: the command was accepted and is completing offline. It is
not a failure and it is not something to resend. Record the svTRID and wait for the
[poll notice](poll.md#the-outcome-of-a-deferred-action) that carries the result.

## A batch that fails well

```python
from epptools.exceptions import (
    CommandException, InsufficientFundsError, ObjectExistsError, ValidationException,
)

taken, retry_later, refused = [], [], []

for name in names_to_register:
    try:
        client.domain.create_builder(name).years(1).registrant("C1").send()
    except InsufficientFundsError as exc:
        # Not this name's problem — the account's. Every remaining name fails identically.
        alert_billing(str(exc))
        break
    except ObjectExistsError as exc:
        taken.append(exc.subject() or name)
    except ValidationException as exc:
        refused.append((name, str(exc)))        # our own input; nothing was sent
    except CommandException as exc:
        if not exc.is_retryable():
            refused.append((name, "EPP %d: %s" % (exc.epp_code, exc)))
            continue
        retry_later.append(name)
```

The shape is the point. One failure stops the run because carrying on cannot help; one is a per-name
outcome to record; one never reached the wire at all; and only the genuinely transient ones go to the
retry queue.

## Reporting a problem

Include the **svTRID** from the response (`exc.response.sv_trid()`) and the **clTRID** your client
sent. Together they identify the exact transaction in the registry's logs, which is what makes a
report answerable without a round trip. Send the frames too if you can, but redact `<pw>`, `<newPW>`
and `<authInfo>` first: those are live credentials, and the library masks them in its own logs for
the same reason.

Questions about the library, a frame the registry rejected, or a bug: **https://github.com/epptools/python-sdk/issues**.

---

See also: [Commands](commands.md) · [Session](session.md) · [Responses](responses.md) ·
[Balance and prices](balance.md) · [Poll](poll.md)

[← Manual index](README.md)
