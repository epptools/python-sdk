# Poll

Everything under `client.poll`. The poll queue is **RFC 5730 `<poll>`**, and it is how the registry
talks to you: everything that happens to your objects without your having asked for it in that
moment arrives here and nowhere else.

Nothing is pushed to you and nothing calls you back. A notice sits in your queue until you ask for
it and acknowledge it, and an acknowledgement destroys it at the registry. Both halves of that
sentence matter, and the second one is why this page spends most of its length on the order in
which you do the two things.

Each method returns a [`Response`](responses.md), and a result code of 2000 or higher is raised as
an exception — see [Errors](errors.md).

## The methods

| Method | EPP command |
|---|---|
| `request()` | `<poll op="req"/>` — 1301 with a notice, 1300 when the queue is empty |
| `ack(message_id)` | `<poll op="ack" msgID="…"/>` — **deletes** the notice at the registry |
| `drain(handler, limit=0)` | the two above in a loop, acknowledging only after your callback returns |

---

## request

```python
client.poll.request() -> Response
```

Asks for the notice at the head of the queue. The queue is a queue: the same notice comes back on
every `request()` until it is acknowledged, so a client that polls without acking reads one message
for ever.

```python
notice = client.poll.request()

if notice.code() == 1300:
    return                       # nothing waiting

notice.message_id()              # '42' — the id you pass to ack()
notice.message_count()           # 3 — how many messages remain in the queue
notice.queue_message()           # the NOTICE text
notice.queue_message_lang()      # 'uk' | 'ru' | 'en'
notice.queue_date()              # '2026-08-14T10:20:00Z' — when it was queued
```

| Code | Meaning |
|---|---|
| 1301 | a notice is attached; `message_id()` is set |
| 1300 | the queue is empty; `message_id()` is `None` and there is nothing to ack |

Both are 1xxx, so `is_success()` is `True` for either and neither raises. Branch on
`message_id() is not None` — or on `code() == 1300` — rather than on success.

```python
notice = client.poll.request()
if notice.message_id() is not None:
    handle(notice)
    client.poll.ack(notice.message_id())
```

### The notice text is not the result message

**`queue_message()` is the notice. `message()` is not.**

`message()` returns `<result><msg>` — the command-result banner, "Command completed successfully;
ack to dequeue", which is identical on every poll reply the registry ever sends. Reading a notice
with `message()` hands you that constant sentence, discards the actual content, and the ack that
follows deletes the content at the registry. The notice is in `<msgQ><msg>`, which is
`queue_message()`.

The same distinction applies to the language. `message_lang()` is the language of the banner, which
follows the `lang` you logged in with; `queue_message_lang()` is the language of the notice itself,
which the registry chooses from your account's notification settings. They need not agree, so read
the notice's own language rather than assuming the session's:

```python
text = notice.queue_message()
lang = notice.queue_message_lang() or "en"
show_to_operator(text, lang)
```

`queue_date()` is the registry's own string, as every date in this library is — the moment the
notice was queued, not the moment you read it.

---

## What the notices carry

A notice always carries text. Some kinds also carry a structured payload, and where there is one it
is the part to act on: the text is written for a human, the payload is written for your code.

| Kind | Structured payload | Accessor |
|---|---|---|
| A transfer request, approval, rejection or cancellation | `<domain:trnData>` / `<contact:trnData>` | `transfer()`, `transfer_status()` |
| The outcome of an action the registry completed offline | `<domain:panData>` / `<contact:panData>` | `pending_action_data()` |
| A low-balance warning | the account figures, where the registry attaches them | `balance()`, `available_credit()` |
| Anything else the registry wants to tell you | none | `queue_message()` |

### A transfer request

The most consequential notice there is, because it has a deadline and silence has a verdict.

```python
t = notice.transfer()
# {'status': 'pending', 'requested_by': 'ACME', 'requested_at': '2026-08-14T10:00:00Z',
#  'acting_client': 'EXAMPLE', 'act_by': '2026-08-19T10:00:00Z',
#  'expiry_date': '2028-04-01T09:15:00Z'}

if t and t["status"] == "pending" and t["acting_client"] == my_clid:
    client.domain.transfer("approve", notice.object_name())     # or "reject"
```

`act_by` is the deadline. **Past it the registry approves the transfer** — it does not cancel it —
so a losing registrar that files this notice instead of answering it loses the domain. The window is
5 days. See [Domains → transfer](domains.md#transfer).

### The outcome of a deferred action

When a command answers **1001**, the registry accepted it and is completing it offline. The answer
comes back here:

```python
pan = notice.pending_action_data()
# {'object': 'example.com.ua', 'success': True,
#  'clTRID': 'PYTHON-SDK-20260814101500-4821-0007',
#  'svTRID': 'SRV-19700101103512-24191-00007',
#  'date': '2026-08-14T10:20:00Z'}
```

Two things to be exact about:

- **`success` is the only thing that says whether it worked.** The surrounding `1301` means "here is
  a message", not "your operation succeeded". A failed create arrives as a perfectly successful poll
  reply carrying `success: False`.
- **`svTRID` identifies which operation this answers.** It is the svTRID of the *original* command —
  the one you were given with the 1001 — not of the poll. A queue is not necessarily in the order you
  sent things, and you may have several pending at once, so match on this rather than assuming the
  notice belongs to your most recent command.

```python
if pan is not None:
    booking = bookings_by_svtrid.get(pan["svTRID"])
    if booking is None:
        alert_operator("pending outcome for an operation we do not recognise", pan)
    elif pan["success"]:
        booking.confirm(pan["date"])
    else:
        booking.fail(notice.queue_message())
```

`pending_action_data()` returns `None` for a notice that carries none, which is most of them, so
test it before reading the keys. It is matched by local name, so a domain payload and a contact
payload are read the same way, and `object` holds the domain name or the contact handle.

### A low-balance warning

The registry warns before the account runs dry, because the alternative is discovering it as a 2104
in the middle of a batch. Read the figures rather than parsing the sentence:

```python
if notice.balance() is not None:
    alert_billing(notice.available_credit())
else:
    alert_billing(client.balance().available_credit())
```

Money is an exact decimal string, never a float. See [Balance](balance.md).

---

## ack

```python
client.poll.ack(message_id: str) -> Response
```

Acknowledges one notice, which **deletes it at the registry**. There is no undelete, no archive and
no second copy: after a successful ack, the content of that notice exists only where your code put
it.

```python
r = client.poll.ack(notice.message_id())
r.code()             # 1000
r.message_count()    # how many are left, where the registry reported it
```

An id that names nothing — one already acked, or one that never existed — is 2303.

| Code | Meaning |
|---|---|
| 1000 | acknowledged and deleted |
| 2303 | no message with that id: already acknowledged, or never existed |

### Acknowledge after processing, never before

This is the whole operational discipline of the queue, and it is worth stating as a rule:

> Store the notice, or act on it, **and only then** ack it.

The failure mode of the other order is silent and unrecoverable. A loop that acks first and
processes second loses every notice whose processing fails — a transfer request that needed
answering in five days, the outcome of a pending create you are still holding money against — with
nothing left to retry from and no record that anything was lost. The registry has deleted it, and it
was the only copy.

```python
# Wrong. The ack is a commit of work that has not happened yet.
notice = client.poll.request()
client.poll.ack(notice.message_id())
store(notice.queue_message())          # if this raises, the notice is already gone

# Right. Nothing is destroyed until the work is durable.
notice = client.poll.request()
if notice.message_id() is not None:
    store(notice.queue_message())      # if this raises, the notice is still in the queue
    client.poll.ack(notice.message_id())
```

`drain()` exists so you do not have to get this right by hand.

---

## drain

```python
client.poll.drain(handler: Callable[[Response], None], limit: int = 0) -> int
```

Reads the queue to the end, handing each notice to your callback and acknowledging it **after** the
callback returns. Returns how many notices were processed successfully.

```python
processed = client.poll.drain(lambda notice: store(
    notice.message_id(),
    notice.queue_message(),
    notice.queue_message_lang(),
    notice.queue_date(),
    notice.pending_action_data(),
))
```

| Behaviour | What it means for you |
|---|---|
| The ack comes after the callback returns | A notice is destroyed only once your side of the work is done. |
| A callback that raises stops the drain | The exception reaches you, the notice is **not** acked, and it is still at the head of the queue. Fix the cause and drain again; nothing was lost. |
| It stops at the first 1300 | The queue is empty. That is the normal end of a drain. |
| Any other reply carrying no notice raises | A refusal — the session closed, the account suspended — must not look like a drained queue. This raises even with `throw_on_failure(False)`, because reporting success while nothing was read is worse than an exception. |
| `limit` caps the number processed | `0` means "until empty". A queue that fills faster than you drain it would otherwise keep the call running indefinitely. |
| An `async def` handler is refused | `ValidationException`, before anything is read. |

A callback that always raises will see the same notice on every drain. That is deliberate: the
alternative is discarding it.

```python
# Drain in bounded batches, so one call cannot run away.
while client.poll.drain(handle_notice, limit=50) == 50:
    pass
```

### Why an async handler is refused

`drain()` is synchronous. An `async def` function called from synchronous code returns a coroutine
immediately and runs none of its body, so the loop would ack every notice before any of them had
been processed — exactly the loss this method exists to prevent, and with no error to show for it.
Wrap the coroutine, or drive the queue yourself with `request()` and `ack()`:

```python
import asyncio

async def handle(notice):
    await store(notice.queue_message())

# Refused before a single frame is read:
#   ValidationException: poll.drain() runs synchronously and cannot await an async handler
client.poll.drain(handle)

# Wrap it, and the ordering is the drain's again.
client.poll.drain(lambda notice: asyncio.run(handle(notice)))
```

Or drive the queue yourself, keeping the same order — work first, ack second:

```python
async def drain_async(client):
    processed = 0
    while True:
        notice = client.poll.request()
        if notice.message_id() is None:      # 1300: the queue is empty
            break
        await handle(notice)
        client.poll.ack(notice.message_id())
        processed += 1
    return processed
```

### Delivery is at least once

If the ack itself fails — the connection drops between your callback returning and the ack landing —
the notice is still in the queue and the next drain hands it to you again. That is the safe
direction to fail in, and it means your handler has to tolerate seeing a notice twice.

Make it idempotent, and use `message_id()` as the de-duplication key:

```python
def handle_notice(notice):
    message_id = notice.message_id()
    if already_processed(message_id):        # a second delivery, not a second event
        return
    with transaction():
        store(message_id, notice.queue_message(), notice.pending_action_data())
        mark_processed(message_id)
```

Commit your side before the ack and the two failure directions are covered: a crash before the ack
replays the notice, and the de-duplication absorbs it.

---

## A complete poller

```python
from epptools import Client, Config
from epptools.exceptions import EppException

def handle(notice):
    pan = notice.pending_action_data()
    transfer = notice.transfer()

    if pan is not None:
        reconcile_pending(pan["svTRID"], pan["success"], pan["date"])
    elif transfer is not None and transfer["status"] == "pending":
        queue_for_review(notice.object_name(), transfer["act_by"])
    elif notice.balance() is not None:
        alert_billing(notice.available_credit())
    else:
        store_operator_message(notice.queue_message(), notice.queue_message_lang())

client = Client(Config(host="epp.registry.example", clid="EXAMPLE",
                       password="your-secret", ca_file="/etc/ssl/registry-ca.pem"))
try:
    client.connect()
    client.login()
    print("handled", client.poll.drain(handle), "notices")
    client.logout()
except EppException as exc:
    print("poll run failed:", exc)
finally:
    client.disconnect()
```

Run it on a schedule — every few minutes is usual — and always drain to 1300 rather than taking one
notice per run. A queue only shrinks when you ack, and a transfer request you read four days late
is a transfer request you have one day to answer.

Poll on its own session if your provisioning traffic is busy: one command at a time per connection
is the rule everywhere in this library, and a drain that shares a connection with a create is a
drain that has to wait for it.

---

See also: [Commands](commands.md) · [Domains](domains.md) · [Contacts](contacts.md) ·
[Balance and prices](balance.md) · [Responses](responses.md) · [Errors](errors.md)

[Back to the index](README.md)
