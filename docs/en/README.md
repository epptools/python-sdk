# EppTools for Python — reference manual

**EppTools 1.1.1** · `pip install epptools`

This manual is for a developer at a sub-registrar who has to provision domains and bill for them
against a domain registry that speaks EPP, and who has not written an EPP client before.

EppTools is an EPP client. It opens a TLS socket to the registry on port 700, writes RFC 5734
frames and reads the replies. The vocabulary throughout is the protocol's own — session, greeting,
command, response, result code, object, extension, poll queue — and every method in the library
corresponds to something that goes on the wire. Where a method maps to a specific EPP command or
RFC, the page says which, so you can hold this manual and the registry's own registrar manual open
side by side.

The library needs only the Python standard library (`ssl`, `socket`, `xml.etree`) and runs on
Python 3.8 or later.

## The twelve pages, in reading order

| Page | What it covers |
|---|---|
| [Index](README.md) | This page: who the manual is for, what is in it, and where to ask for help. |
| [Quick start](quickstart.md) | One complete runnable program — install, connect, log in, one real command, log out — then a line-by-line walk through it. |
| [Session](session.md) | `Config` field by field, TLS verification and failed handshakes, connect/hello/login/logout, password rotation, RFC 8807 login security, logging with secrets masked. |
| [Commands](commands.md) | The command surface as a whole: what every command returns, client transaction ids, the `throw_on_failure` switch, and building a raw frame. |
| [Domains](domains.md) | Every domain method — check, info, create, update, renew, restore, delete, transfer — with a signature, an example and what comes back. |
| [Contacts](contacts.md) | Every contact method, including the registry-minted handle, partial address changes and RFC 5733 disclosure. |
| [Hosts](hosts.md) | Every host method, glue addresses, the forced delete, and why a nameserver is replaced rather than renamed. |
| [Poll](poll.md) | The message queue: request, ack, drain, and what a notice carries — including the outcome of a pending action. |
| [Balance](balance.md) | The account balance, and RFC 8748 prices: asking for them, capping what you agree to pay, reading the answer. |
| [Responses](responses.md) | Every `Response` accessor, grouped by what it answers, with what each returns when the answer carries nothing. |
| [Builders](builders.md) | The fluent builders: every step of every builder, the accumulate rule, `to_options()` and the send-once rule. |
| [Errors](errors.md) | The exception hierarchy, result codes, `is_retryable()`, and what to do when a transform's outcome is unknown. |

Read [Quick start](quickstart.md) first, then [Session](session.md) and
[Errors](errors.md). Those three are what an integration lives or dies by; the object pages are
reference you come back to.

## Support

Questions about the library, a frame the registry rejected, or a bug: **https://github.com/epptools/python-sdk/issues**.

When you report a problem, include the **svTRID** from the response (`sv_trid()`) and the **clTRID**
your client sent. Together they identify the exact transaction in the registry's logs, which is what
makes a report answerable without a round trip. Send the frames too if you can, but redact `<pw>`,
`<newPW>` and `<authInfo>` first: those are live credentials, and the library masks them in its own
logs for the same reason.

Include the library version as well — `epptools.__version__`, the same version this client reports
to the server in its login (RFC 8807 `<loginSec:app>`), so the version in your report and the
version the registry saw are the one version:

```python
import epptools

print(epptools.__version__)          # '1.1.1'
```

Account, billing and registration questions go to your registry account manager, not here — this
address is for the client library.
