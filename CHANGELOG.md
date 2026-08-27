# Changelog

All notable changes to this library are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.1]

### Fixed

- **The manuals now document `change()`, and every version they state matches the package.** 1.1.0
  shipped the feature with per-language manuals that did not mention it, and the install line
  offering a GitHub tag still named an older release — so a reader following the documented command
  installed a library older than the page describing it. All three languages now carry the section,
  and a test fails the build when any documented version drifts from the package's own.
## [1.1.0]

### Added

- **`change()` — what the registry did to your object, as data instead of a sentence (RFC 8590).**
  Some poll notices describe something that happened to one of your objects without you asking: it
  stopped existing at the registry, or it left on a transfer. Those are the ones you have to act on
  automatically — stop billing it, tell your customer, drop it from your own store — and the `<msg>`
  they carry is written in your account's notification language, so nothing in it is safe to parse.

  `change()` returns the operation, when it happened, who did it, the server transaction id and the
  registry's own finer name for the event, or `null` where the notice carries no change block. The
  object itself is in the response as usual, so the ordinary accessors read it.

  **`state` matters**: it says whether that object describes itself **before** the change or
  **after** it. A domain that no longer exists can only be described as it last was, so those
  notices read `before` — storing such a block as the object's *current* state is how a deleted
  domain comes back to life in your own records.

  To receive it, announce `urn:ietf:params:xml:ns:changePoll-1.0` at login. This library mirrors the
  server's greeting into `<svcs>`, so a server that offers it is announced for you unless you pin
  your own service list.
## [1.0.2]

### Fixed

- **A postal change that carried only part of the block could delete the rest of the address.** A
  `<contact:postalInfo>` inside `<contact:chg>` is not merged field by field by every registry: one
  that *replaces* the block stores exactly what you sent and drops everything else — while answering
  **1000**. Clearing an organisation on its own therefore left a contact with no name, no street, no
  city, no postal code and no country, and nothing in the response said so. `name`, `city` and `cc`
  are now required in every postal change, through `contact.update()` and the update builder alike.

### Changed

- A postal change missing `name`, `city` or `cc` now raises `ValidationException` instead of being
  sent. This rejects calls that previously appeared to succeed — those were the calls losing data.
  Read the current block with `client.contact.info(id).postal_info()` and send it back with your
  change applied.
- The documentation for partial postal updates was wrong in the same way and has been rewritten. A
  block is replaced, not merged: a field you leave out is deleted, not preserved.

## [1.0.1]

### Fixed

- **Clearing one optional part of an address built a frame the server rejects.** RFC 5733 makes
  `<contact:addr>` a sequence with a required `city` and `cc`, so a change to any part of it sends
  the whole block. What the library did was substitute an EMPTY STRING for whatever the caller had
  not supplied — so `{"sp": ""}`, the documented way to remove a state, went out with `<city/>` and
  `<cc/>` beside it. Both are schema-invalid (`postalLineType` has minLength 1, `ccType` is exactly
  two characters), and an invalid frame comes back as a bare `2001` naming no element. A caller
  following the manual got the least useful error in EPP.

  A partial address change now requires `city` and `cc` and says so before anything is sent. Read
  them back from `info()` and pass them through unchanged alongside what you are changing.

- **An empty value is now refused for the fields the schema forbids it on.** Which parts of a
  contact can be CLEARED is fixed by `contact-1.0.xsd` and not by convention: `org`, `street`, `sp`
  and `pc` have types with no minimum length, so sending them empty is what removes them; `name`,
  `city` and `cc` do not, so an empty one cannot be sent at all. Passing one is answered here, with
  the reason, instead of costing a round trip.

Neither changes a call that worked. Both turn a call the server was already rejecting into one that
fails immediately and says why.

## [1.0.0]

First public release.

### The library

- **EPP over TLS with no dependencies at all** — the standard library and nothing else, on Python
  3.8 and up. Domains, contacts and hosts (RFC 5730–5733), DNSSEC (RFC 5910), redemption and restore
  (RFC 3915), prices and fee agreements (RFC 8748) and login security (RFC 8807).
- **A registry's own extensions are discovered from its `<greeting>`**, not compiled in. This library
  ships no registry's URIs, so it works against a registry it has never seen — and keeps working when
  one changes its namespaces. `client.registry_ext_uri()` / `registry_balance_uri()` report what was
  found; `Config` can override both for a registry whose naming discovery cannot guess.
- **Responses are read by local element name**, never by namespace prefix, so extension data stays
  readable whatever namespace it arrived under and whatever prefix the server chose.
- **Commands that need an extension the server does not offer fail loudly.** `domain.create` with a
  licence, `host.delete` with `force` and `balance()` raise `ConfigException` naming what was wanted
  and listing what the server advertised — because an extension sent under a namespace the server
  does not recognise is ignored rather than rejected, so the alternative is a `1000 OK` with the
  value silently unset.
- **Misspelt keyword and option keys are refused, not dropped.** A key this library does not
  understand raises `ValidationException` with the nearest accepted spelling, instead of building a
  frame that omits what you asked for and comes back successful. DNSSEC blocks accept both the
  RFC's camelCase spelling and this library's snake_case, and nothing else.
- **Passwords never reach a log or a `repr()`.** Frame logging redacts `<pw>` and `<newPW>` in any
  namespace, `Config` keeps the password out of its own `repr()`, and a password too long for the
  RFC 5730 `<pw>` element is either carried by RFC 8807 or refused before a socket is opened.
- **Builders** for the commands with the most options — `domain.update`, `contact.create`,
  `contact.update` — so a long call site reads as a sequence of decisions.
- **Typed throughout, and it ships `py.typed`** (PEP 561), so mypy and pyright use the annotations
  instead of treating every import as untyped.

### The documentation

- A full reference manual in English, Ukrainian and Russian: `docs/en/`, `docs/uk/`, `docs/ru/`,
  twelve pages each — quickstart, session, domains, contacts, hosts, DNSSEC, transfers, poll, fees,
  balance, responses, errors, plus a commands reference and a builders guide.
- Every example runs against `epp.registry.example` with the login `EXAMPLE`. The examples name no
  real registry, and every hostname is under a TLD RFC 2606 reserves so a copied example cannot
  reach somebody's server.
