# Session

Everything between opening the socket and closing it: how the client is configured, how TLS is
verified, how a session is opened and closed, how the password is rotated, what the server tells you
about the session's security, and how to log all of it without writing a credential to disk.

## The shape of a session

```
connect()  →  <greeting>            the server speaks first
login()    →  1000                  clID + password, services taken from the greeting
  ... commands, one at a time, each with its own clTRID ...
logout()   →  1500                  the server then closes the link
disconnect()                        close the socket
```

A session is a TLS connection with state. Commands are sent one at a time and each reply is read
before the next command goes out; the library does not pipeline, and neither should you. If you need
throughput, open more sessions rather than overlapping commands inside one — but mind the concurrent
session limit on your account, because exceeding it is refused with 2502 and the server closes the
connection.

```python
from epptools import Client, Config

client = Client(Config(host="epp.registry.example", clid="EXAMPLE", password="your-secret",
                       ca_file="/path/to/registry-ca.pem"))
client.connect()
client.login()
try:
    print(client.domain.check(["example.com.ua"]).availability())
    client.logout()
finally:
    client.disconnect()
```

## Config, field by field

`Config` is an immutable dataclass. `host`, `clid` and `password` are required and have no default;
everything else has one, and the defaults are the right answer for the public endpoint.

```python
from epptools import Config

config = Config(host="epp.registry.example", clid="EXAMPLE", password="your-secret",
                ca_file="/path/to/registry-ca.pem")
```

| Field | Default | What it is, and what happens if it is wrong |
|---|---|---|
| `host` | — required | The registry endpoint, `epp.registry.example`. An empty string raises `ConfigException` from `connect()` before a socket is opened. A name that does not resolve, or a host that refuses the connection, raises `ConnectionException`. |
| `clid` | — required | Your registrar identifier, e.g. `EXAMPLE`. Empty raises `ConfigException` from `login()`. Wrong: the login fails with 2200 (`AuthenticationException`) — which is also what a connection from an IP outside your allowlist looks like, so check the address before you rotate the password. |
| `password` | — required | Your EPP password. Empty raises `ConfigException`. Outside 6–128 characters raises `ConfigException` before any socket is opened. Longer than 16 against a server that does not offer RFC 8807 raises `ConfigException` naming the extension, because the base `<pw>` element cannot carry it. Wrong: 2200. |
| `port` | `700` | The EPP port. Override only if the endpoint moves. |
| `lang` | `"en"` | The language of every result message this session: `en`, `uk`, `ua` or `ru` (`ua` and `uk` are both Ukrainian). A language the server does not advertise fails the login with 2102. |
| `connect_timeout` | `10.0` | Seconds allowed for the TCP connect. Exceeded: `ConnectionException`, nothing was sent. |
| `read_timeout` | `30.0` | Seconds allowed for one read. Values below 1 are raised to 1. Exceeded: `ConnectionException("Read timed out")`, and the connection is finished — see [Recovering a connection](#recovering-a-connection). |
| `verify_peer` | `True` | Verify the server certificate chain. `False` disables verification entirely; see the warning below. |
| `verify_peer_name` | `True` | Check that the certificate matches the hostname you connected to. `False` accepts a valid certificate issued for a different name. |
| `ca_file` | `None` | Path to the CA bundle that signs the **server** certificate. Required on port 700. When set, that bundle **replaces** the system trust store rather than adding to it; when unset and `verify_peer` is on, the system store is used. A path that does not exist raises `ConnectionException` at `connect()`. |
| `client_cert` | `None` | Your client certificate (PEM), only where the endpoint requires mutual TLS. The standard profile on port 700 does not. |
| `client_key` | `None` | The private key (PEM). May be omitted when it is bundled into `client_cert`. |
| `client_key_passphrase` | `None` | Passphrase for an encrypted private key. A wrong one raises `ConnectionException` at `connect()`. |
| `obj_uris` | `None` | Override the object services advertised in `<login>`. `None` — or an empty list — means "exactly what the greeting offered", which is why a session is never refused for asking for a service the server does not serve. A URI the server does not serve fails the login with 2307. |
| `ext_uris` | `None` | Override the extension services. `None` means the greeting's. An **empty list** is a deliberate "advertise no extensions", and every command carrying one then draws 2103 — including DNSSEC, RGP restore, fees and the balance query. |
| `cltrid_prefix` | `"PYTHON-SDK"` | The leading segment of every generated client transaction id. Keep it short: the protocol caps the whole id at 64 characters. See [Commands → Transaction ids](commands.md#client-transaction-ids). |
| `registry_ext_uri` | `None` | The namespace of this registry's OWN object extension. `None` — the normal case — reads it from the greeting; set it only for a registry whose extension is not named `…/registry-<version>`, which is what discovery matches on. A wrong value is not refused: an extension in a namespace the server does not know is IGNORED, so the data goes missing in silence. See [Commands](commands.md#your-registrys-own-extensions). |
| `registry_balance_uri` | `None` | The same, for the account-balance extension. |
| `login_security` | `True` | Take part in the RFC 8807 Login Security extension when the server offers it. Leaving it on is what makes the server's security events come back — see [Login security](#login-security-rfc-8807). |

Two fields are deliberately excluded from the dataclass's `repr()`: `password` and
`client_key_passphrase`. A dataclass prints its fields in cleartext, so one `logging.debug("%r",
config)`, one traceback rendered with locals, or one test dump would otherwise put the live password
into a log file that outlives the process.

### Config.from_dict

```python
Config.from_dict(values: Dict[str, Any]) -> Config
```

Builds a `Config` from a plain mapping whose keys are the field names — configuration read from
JSON, TOML or the environment. A key that is not a field raises `ConfigException` listing the
offenders, rather than being ignored: a silently dropped `ca_file` is a session that fails
verification for a reason nothing in the config explains.

```python
config = Config.from_dict({
    "host": "epp.registry.example",
    "clid": "EXAMPLE",
    "password": os.environ["EPP_PASSWORD"],
    "ca_file": os.environ["EPP_CA"],
})
```

## TLS and the certificate

The transport is EPP over TLS (RFC 5734) on port 700. The client refuses anything below **TLS 1.2**,
so a server offering only older versions fails the handshake rather than negotiating down.

| Scenario | Config |
|---|---|
| `epp.registry.example:700` — a private-CA certificate | set `ca_file` to the registry CA `.pem`; **required** |
| A public, browser-trusted certificate | the defaults (`verify_peer=True`, `verify_peer_name=True`) |
| Right certificate, wrong hostname (development) | `verify_peer_name=False` |
| A mutual-TLS endpoint | `client_cert` + `client_key` (+ `client_key_passphrase` if the key is encrypted) |

The public endpoint presents a certificate issued by the registry's **own private CA**. The system
trust store does not contain that CA, so `ca_file` must point at the bundle the registry issued you
and the handshake fails without it. Beyond that it is strict RFC EPP and needs **no client
certificate**: you authenticate with clID and password over TLS, from an allow-listed IP address.

### When the handshake fails

The commonest first-run failure is certificate verification, and it looks like this:

```
ConnectionException: TLS handshake with epp.registry.example:700 failed — [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed
```

That almost always means `ca_file` is unset or points at the wrong bundle. Check the bundle outside
Python before you change any code:

```bash
openssl s_client -connect epp.registry.example:700 -CAfile /path/to/registry-ca.pem -servername epp.registry.example </dev/null
# "Verify return code: 0 (ok)" means the bundle is right; anything else means it is not.
```

A successful handshake there is also followed by the server's `<greeting>` on the terminal, which
confirms you reached an EPP endpoint and not something else listening on the port.

**Do not reach for `verify_peer=False`.** It makes the message go away and leaves you sending your
clID, your password and every transfer secret to whatever answers on that address, with no way to
tell that you did. If the handshake will not verify, the bundle is wrong — ask the registry for the
current one. `verify_peer_name=False` is a narrower loosening (right certificate, wrong hostname)
and is occasionally reasonable in development; `verify_peer=False` is not reasonable anywhere.

Other handshake-time failures raise the same `ConnectionException`, with the underlying reason in
the message: a missing or unreadable `ca_file`, a `client_cert` whose key does not match, a wrong
`client_key_passphrase`.

## Opening and closing a session

| Method | Returns | What it does |
|---|---|---|
| `Client(config, connection=None, logger=None)` | — | Builds the client. Opens nothing; safe at import time. |
| `Client.connect_and_login(config)` | `Client` | Classmethod: construct, `connect()`, `login()`, hand back the ready client. |
| `connect()` | `Response` | Opens the TLS socket and reads the unsolicited `<greeting>`. |
| `greeting` | `Optional[Response]` | Property: the greeting last read, or `None` before `connect()`. |
| `hello()` | `Response` | Sends `<hello>`; the server answers with a fresh `<greeting>`. |
| `login(new_password=None)` | `Response` | Authenticates (RFC 5730 `<login>`), optionally rotating the password. |
| `logout()` | `Response` | Ends the session; the server answers 1500 and closes the link. |
| `disconnect()` | `None` | Closes the socket. Safe to call twice, and safe when never connected. |
| `is_connected()` | `bool` | Whether the socket is open and usable. |
| `is_logged_in()` | `bool` | Whether a `login()` has succeeded on this connection. |

**`connect()`** returns the greeting as an ordinary `Response`. Read what the endpoint serves with
`service_obj_uris()` and `service_ext_uris()`; that list is what the login mirrors back. `connect()`
on an already-open connection re-reads a frame, so call it once per session.

**`login()`** advertises exactly the services the greeting offered, unless `Config.obj_uris` /
`ext_uris` override them, and the base `epp-1.0` URI is never listed as an object service. If you
call `login()` without having called `connect()`, it connects first. Anything other than 1000 raises:
2200 as `AuthenticationException`, and everything else as the class that fits — 2502 is a session
limit, 2501 is the server closing the connection, 2307 is an unserved service URI, 2002 is a second
login on one connection. Calling them all an authentication failure would send you to rotate a
password that was never the problem.

**`logout()`** is worth the round trip. Dropping the socket instead leaves a session occupying one of
your concurrent slots until the server times it out, and the next connection can be refused with 2502
for a slot you are no longer using.

**`hello()`** re-reads the greeting mid-session. It is the keep-alive on an otherwise idle
connection, and the way to re-read the service menu without reconnecting.

`Client` is a context manager:

```python
with Client(config) as client:
    client.connect()
    client.login()
    ...
    client.logout()          # the block does not send this for you
```

The block disconnects on exit whatever happened, including on an exception. It does not connect, log
in or log out — keep `logout()` inside the block so the session ends cleanly rather than by timeout.

### Recovering a connection

A `ConnectionException` from a read or a write is terminal for that connection: a failed transfer
leaves the byte stream at an unknown offset, and the next command would read the previous command's
reply — an off-by-one across billable transforms. Every later call on it raises rather than resuming
on a stream that cannot be trusted.

Recovery is `connect()` and `login()` again, which reopens the socket. What you must not do is
re-send the command that failed: if it was a `create`, a `renew` or a `transfer`, its outcome is
genuinely unknown and a blind retry is how a domain gets registered — and paid for — twice. Ask the
registry what is true first; the procedure is in
[Errors → When the outcome is unknown](errors.md#when-the-outcome-is-unknown).

### Swapping the transport

`Client(config, connection=...)` accepts anything implementing the `Transport` interface —
`open()`, `is_open()`, `write_frame(xml)`, `read_frame()`, `close()` — which is how you drive the
client against a recorded exchange in tests without a socket. `Connection` is the built-in TLS
implementation and is used when the argument is omitted.

## Rotating the password

The EPP password is changed by the login that uses it (RFC 5730 `<newPW>`), not by a separate
command:

```python
client.connect()
response = client.login("a-new-secret")     # authenticates with the old one, sets the new one
assert response.code() == 1000
```

The change takes effect only if the login succeeds, and from that moment the old password is dead.
**Persist the new password before you rotate**, or at the very least in the same transaction as the
call: a process that changes the password and then crashes before storing it has locked the account
out of every future session, and only the registry can undo that.

Both passwords are length-checked before a socket is opened. The base `<pw>` element is capped at
**16 characters** by the protocol schema; RFC 8807 raises the ceiling to **128** where the server
offers it. Asking for more than the server can carry raises `ConfigException` naming the extension,
rather than sending a frame the server answers with a bare 2001 that names no field.

Rotation across the 16-character boundary is handled per element, not per frame: changing a short
password to a long one relocates only the new one into the extension, and the old one still travels
in `<pw>` where the server expects it.

> Before you set a password longer than 16 characters, check what else authenticates with this
> account. A password that can only travel in the RFC 8807 extension cannot be sent by software
> talking to an endpoint that does not offer it.

## Login security (RFC 8807)

Where the server offers the Login Security extension, the login carries a small block identifying
this client — the library name and version, the Python version, the operating system — and the
server answers with anything it wants you to fix about the session:

```python
for event in client.login().security_events():
    # type:  certificate | cipher | tlsProtocol | password | newPW | stat | custom
    # level: "warning" or "error"
    # text:  a sentence to show an operator
    alert(event["level"], event["type"], event["text"], event.get("exDate"))
```

| `type` | Raised when |
|---|---|
| `certificate` | your client certificate is close to expiry — `exDate` carries the exact moment |
| `tlsProtocol` | the session negotiated an obsolete TLS version — `name` carries it |
| `cipher` | the session negotiated a cipher suite that is not AEAD — `name` carries it |
| `password` / `newPW` | something about the credential itself the server wants changed |
| `stat` | session statistics the server chose to report |
| `custom` | server-specific; `name` identifies it |

Each entry always has `text` and carries whichever of `type`, `name`, `level`, `exDate`, `value`,
`duration` and `lang` the event used. The list is empty on a healthy session, so treat any entry as
something to act on rather than as noise. The commonest one is a client certificate approaching its
expiry date; the alternative to hearing about it here is finding out on the morning it stops working.

A server sends these only to a client that **took part** in the extension, because announcing a URI
is not evidence of being able to read one — many clients build their `<svcExtension>` by echoing the
greeting back. That is why the block goes out even when nothing needs to travel in it, and why
`security_events()` is empty on a client that stays off the extension.

Set `login_security=False` to stay off it. It is then used only where it is unavoidable — a password
longer than the 16 characters the base `<pw>` element can carry, which has nowhere else to go.

## Logging

```python
import logging

logging.basicConfig(level=logging.DEBUG)
client = Client(config, logger=logging.getLogger("epp"))
# or later, and with None to switch it off again:
client.set_logger(logging.getLogger("epp"))
```

`set_logger(logger)` returns the client, so it chains. Any object with `debug`, `info` and `warning`
methods works; a `logging.Logger` is the obvious one.

| Level | What is written |
|---|---|
| `DEBUG` | the greeting, and every request and response frame in full |
| `INFO` | one line per successful command: the result code, the svTRID and the clTRID |
| `WARNING` | the same line for a command the registry refused |

**Secrets are masked before anything is written.** Every `<pw>` and `<newPW>` element is replaced
with `***` in the logged frame, in any namespace prefix and whatever attributes the element carries —
which covers the login password, the new password during a rotation, and the `<domain:pw>` /
`<contact:pw>` transfer secrets inside `authInfo`. The masking is applied to the text handed to the
logger, so it holds for whatever handler you have attached.

That masking is the library's own logs. If you log frames yourself — and you may want to while
integrating — redact the same three elements before the text reaches a file or a support ticket:
`<pw>`, `<newPW>` and `<authInfo>` are live credentials, and an `authInfo` is what lets any registrar
take a domain away from you.

The INFO line is the one to keep in production. Both transaction ids on one line, for every command
including the ones that succeeded, is what you compare against when a later one does not.

---

[← Manual index](README.md)
