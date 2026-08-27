# Quick start

One complete program: connect to the registry, log in, ask two questions that cost nothing, read
your balance, and close the session cleanly. Copy it, fill in your own credentials, run it. The
walk-through after it explains every line.

## Install

```bash
pip install epptools
```

Pinned to a release tag straight from GitHub, if you would rather not depend on PyPI:

```bash
pip install "epptools @ git+https://github.com/epptools/python-sdk@v1.1.1"
```

No packaging at all? Copy the `epptools/` package folder next to your code and `import epptools`.
There is nothing else to install: the library uses only the Python standard library.

## What you need before you start

| What | Where it comes from |
|---|---|
| Host and port | Issued with your account. `epp.registry.example`, port **700**. |
| Your clID | Your registrar identifier, e.g. `EXAMPLE`. |
| Password | Issued with the account. Rotated through `<login>`, never by e-mail. |
| The registry CA bundle | A `.pem` file. Port 700 presents a certificate from the registry's own private CA, so this is required — see [Session](session.md#tls-and-the-certificate). |
| An allow-listed source IP | You may connect only from the addresses registered for the clID. |

Build against the registry's test identity before you point anything at production.

## The whole program

```python
"""A first EppTools program: connect, ask, log out. Nothing here is billable."""

import logging
import os
from decimal import Decimal

from epptools import Client, Config
from epptools.exceptions import CommandException, EppException

logging.basicConfig(level=logging.INFO)

config = Config(
    host="epp.registry.example",
    clid="EXAMPLE",
    password="your-secret",
    port=700,                 # the default; override only if the endpoint moves
    lang="en",                # result messages: en | uk | ua | ru
    ca_file=os.environ.get("EPP_CA", "/path/to/registry-ca.pem"),
)

client = Client(config, logger=logging.getLogger("epp"))

try:
    greeting = client.connect()
    print("server:", greeting.value("svID"))

    login = client.login()
    for event in login.security_events():
        print("session %s (%s): %s" % (event["level"], event["type"], event["text"]))

    name = "example.com.ua"
    check = client.domain.check([name], fee={"create": 1})
    available = check.is_available(name)
    if available is None:
        print("the registry said nothing about", name)
    elif available:
        print("%s is free; a create would cost %s %s" % (
            name, check.fee_for(name, "create", 1), check.fees().get("_currency")))
    else:
        print("%s is taken: %s" % (name, check.unavailable_reason(name)))

    info = client.domain.info(name)
    print("expires:", info.expiry_date())
    print("nameservers:", info.nameservers())
    print("svTRID:", info.sv_trid())

    money = client.balance()
    print("available credit:", Decimal(money.available_credit() or "0"))

    client.logout()
except CommandException as exc:
    print("the registry refused: EPP %d — %s" % (exc.epp_code, exc))
except EppException as exc:
    print("client-side failure:", exc)
finally:
    client.disconnect()
```

Expected output, against a name someone else already holds:

```
server: Registry EPP Server
example.com.ua is taken: In use
the registry refused: EPP 2201 — EPP 2201: Authorization error
```

That third line is the program working correctly: `domain.info` on a domain that is not yours is
refused, the exception carries the code, and the `finally` still closes the socket. Point it at a
name you sponsor and the two `info` lines print instead.

## Line by line

**1 — Imports.** `Client` and `Config` are the whole entry point; both are exported from the package
root. The exceptions live in `epptools.exceptions`. `CommandException` is what the registry refusing
a command looks like; `EppException` is its base and catches everything the library raises, so the
two `except` clauses between them leave nothing unhandled. See [Errors](errors.md).

**2 — `logging.basicConfig`.** Optional, and worth having from the first run. The logger you hand to
the client prints one line per command with the result code and both transaction ids, and the whole
frame at `DEBUG`. Passwords and `authInfo` are masked before anything is written — see
[Session → Logging](session.md#logging).

**3 — `Config(...)`.** Immutable connection settings. `host`, `clid` and `password` are required and
have no defaults; everything else does. `port=700` is already the default and is written out here
only to be explicit. `lang` sets the language of every result message the server sends this session.
`ca_file` is the one that catches people out on the first run: the endpoint presents a private-CA
certificate, the system trust store does not contain that CA, and without the bundle the handshake
fails verification. Every field is documented in [Session → Config](session.md#config-field-by-field).

**4 — `Client(config, logger=...)`.** Constructing a client opens nothing. It is safe to build one
at import time and connect later.

**5 — `client.connect()`.** Opens the TLS socket and reads the server's unsolicited `<greeting>`,
which it returns as a `Response`. The greeting lists the object and extension namespaces this
endpoint serves; the login that follows advertises exactly those, so your session is never refused
for asking for a service the server does not offer. `greeting.value("svID")` pulls one element out of
it by local name.

**6 — `client.login()`.** Sends `<login>` with your clID and password (RFC 5730). It returns the
login `Response`; anything other than 1000 is raised, with `AuthenticationException` for a 2200 and
a more specific class for the rest — a 2502 is a session limit, not a bad password, and the two need
opposite fixes.

**7 — `login.security_events()`.** RFC 8807. The server returns what it wants you to fix about this
session: a client certificate weeks from expiry, an obsolete TLS version, a weak cipher suite. The
list is empty on a healthy session, so treat any entry as something to act on. The alternative to
hearing about an expiring certificate here is finding out on the morning it stops working. See
[Session → Login security](session.md#login-security-rfc-8807).

**8 — `client.domain.check([name], fee={"create": 1})`.** One `<check>` command (RFC 5731) carrying
an RFC 8748 fee rider, so availability and price arrive in a single round trip. `check` changes
nothing and costs nothing, which makes it the safe first command against a live account.

**9 — `check.is_available(name)`.** Three-valued on purpose: `True`, `False`, or `None` when the
answer said nothing about that name. `None` is not "taken", and it must not be treated as one by the
line that registers the name next.

**10 — `check.fee_for(name, "create", 1)`.** The quoted price for one operation at one period, as
the registry's own exact decimal string — never a float, because `0.1 + 0.2` is not `0.3` in binary
floating point and money summed that way drifts. `check.fees()` returns the whole per-name table and
its `_currency` key. Prices in this manual are illustrative. See [Balance](balance.md).

**11 — `client.domain.info(name)`.** `<info>` for one domain. `expiry_date()` gives the expiry
exactly as the registry wrote it (`2027-04-01T09:15:00Z`), as a string and not a `datetime`: the
registry decides which calendar day a renewal lands on, and re-formatting through a local timezone
is how a client ends up renewing against the day before. `nameservers()` returns the names whichever
of the two EPP models the registry uses to express them.

**12 — `info.sv_trid()`.** The registry's own identifier for that operation. Store it against the
object the command was about. It is the value support looks an operation up by; your clTRID means
nothing to anyone but you.

**13 — `client.balance()`.** The registry's native balance query. `available_credit()` is what you
can actually spend — balance plus remaining credit — as an exact decimal string, which is why it
goes through `Decimal` rather than `float`. See [Balance](balance.md).

**14 — `client.logout()`.** Ends the session politely; the server answers 1500 and closes the link.
Skipping it leaves a session occupying one of your concurrent-session slots until the server times
it out, and the next connection can be refused with 2502 for a slot you are no longer using.

**15 — `except CommandException`.** The registry answered with an error code. `exc.epp_code` is that
code and `exc.response` is the full parsed reply. Catch narrower subclasses where the right next step
differs — `InsufficientFundsError` should stop a batch rather than skip one name.

**16 — `finally: client.disconnect()`.** Closes the socket whatever happened. `Client` is also a
context manager (`with Client(config) as client:`) that disconnects on exit — it does not connect,
log in, or send `<logout>` for you, so keep the `logout()` call inside the block.

## Where to go next

- [Session](session.md) — every `Config` field, TLS diagnosis, password rotation, logging.
- [Commands](commands.md) — what a command returns, transaction ids, raw frames.
- [Errors](errors.md) — which exception to catch, and what to do after a failure whose outcome you
  cannot determine.
- [Domains](domains.md) — the first command that costs money.

---

[← Manual index](README.md)
