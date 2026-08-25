# Changelog

All notable changes to this library are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
