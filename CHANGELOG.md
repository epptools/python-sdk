# Changelog

All notable changes to this library are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
