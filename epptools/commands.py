"""Object command handlers (domain / contact / host / poll). Reached through the Client
resource properties: ``client.domain``, ``client.contact``, ``client.host``, ``client.poll``.

Nested option dicts use snake_case keys, e.g. ``chg={'auth_info': 'pw'}``,
``sec_dns={'ds_data': [{'key_tag': 123, 'alg': 8, 'digest_type': 2, 'digest': '...'}]}``.
The DNSSEC block also accepts the RFC 5910 camelCase spelling (``dsData``, ``keyTag``,
``maxSigLife``, …) as written in the RFC, and refuses anything else outright.
"""

from __future__ import annotations

import inspect
import ipaddress
import re
import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Union

from . import namespaces as ns
from .exceptions import ValidationException
from .frame import Frame
from .response import Response

if TYPE_CHECKING:  # pragma: no cover
    from .client import Client

_ADMIN = ns.CONTACT
_D = ns.DOMAIN
_H = ns.HOST


_DATE_HEAD = re.compile(r"^(\d{4}-\d{2}-\d{2})")


def _date_only(value: str) -> str:
    """The calendar date at the front of an EPP timestamp, or the string unchanged.

    WHY THIS EXISTS. Two EPP elements carry the same expiry and are DIFFERENT XML types.
    ``<domain:exDate>`` is an ``xs:dateTime`` — ``2027-04-01T09:15:00.0Z`` — and
    ``<domain:curExpDate>`` is an ``xs:date`` — ``2027-04-01``. So the obvious code, feeding what
    ``info()`` returned straight back into ``renew()``, is refused: the frame fails schema
    validation, or the registry reads a date it cannot match and answers 2105 "expiry is not what
    you said". The renewal does not happen, and the reason names neither element.

    WHY NO TIMEZONE CONVERSION. The date is taken as the SERVER WROTE IT, with no parsing and no
    reformatting. EPP timestamps are UTC, and the registry's own expiry date is the UTC one; a
    client that reformats through a local zone — which ``datetime.fromisoformat(...).date()`` on a
    naive value invites — lands a day either side of it for every domain expiring near midnight,
    and then renews against a date the registry does not hold.

    Anything not starting with a ``YYYY-MM-DD`` is passed through untouched, so an unusual value
    reaches the server and earns the server's own error rather than being silently truncated into a
    date that means something else.
    """
    m = _DATE_HEAD.match(str(value))
    return m.group(1) if m else str(value)


def _ip_version(ip: str) -> str:
    try:
        return "v6" if ipaddress.ip_address(ip).version == 6 else "v4"
    except ValueError:
        return "v4"


def _append_nameservers(frame: Any, parent: Any, nameservers: Any) -> None:
    """Append a ``<domain:ns>`` block.

    A nameserver is either a NAME — a reference to a host object that already exists at the
    registry — or a name WITH its glue addresses, inlined. Registries take one model or the other,
    so ask yours which; a plain string gives the first and ``{"name": ..., "addresses": [...]}``
    gives the second.

    RFC 5731 makes ``<domain:ns>`` a choice, so the two cannot be mixed in one command: a frame
    carrying both is refused by the schema, which is a bare 2001 naming no field.
    """
    inline = [isinstance(host, dict) and "name" in host for host in nameservers]
    if True in inline and False in inline:
        raise ValidationException(
            "nameservers must be all names or all name-with-glue, not a mixture — "
            "RFC 5731 makes <domain:ns> a choice between the two models"
        )
    ns_el = frame.ns(parent, _D, "domain:ns")
    for host in nameservers:
        if not isinstance(host, dict):
            frame.ns(ns_el, _D, "domain:hostObj", str(host))
            continue
        attr = frame.ns(ns_el, _D, "domain:hostAttr")
        frame.ns(attr, _D, "domain:hostName", str(host["name"]))
        for ip in host.get("addresses") or []:
            frame.ns(attr, _D, "domain:hostAddr", str(ip), {"ip": _ip_version(ip)})


def _opt(spec: Dict[str, Any], *names: str, default: Any = None) -> Any:
    """Read an option that RFC 5910 spells in camelCase and this SDK in snake_case.

    Both spellings are accepted, and every DNSSEC lookup goes through here, so
    ``sec_dns={"dsData": [...]}`` — the spelling written in the RFC — and
    ``sec_dns={"ds_data": [...]}`` build the same ``<secDNS:create>`` block. Any other spelling is
    refused (see :func:`_check_secdns_keys`) rather than left out of the frame: an option nobody
    reads never reaches the registry, and the registry answers 1000 for the command it did receive.
    """
    for name in names:
        if name in spec:
            return spec[name]
    return default


#: Every key a domain.update / contact.update ``chg`` block understands, in both the snake_case
#: spelling this library uses and the camelCase spelling written in the RFCs. Anything else is
#: refused rather than dropped.
_DOMAIN_CHG_KEYS = frozenset({"registrant", "auth_info", "authInfo", "clear_auth_info", "clearAuthInfo"})
_CONTACT_CHG_KEYS = frozenset({
    "postal_info", "postalInfo", "postal_infos", "postalInfos",
    "voice", "fax", "email", "auth_info", "authInfo", "disclose",
})

_SECDNS_KEYS = frozenset({
    "ds_data", "dsData", "key_data", "keyData", "max_sig_life", "maxSigLife",
    # Both the plain word and EPP's abbreviation - see Domain.update() for why both stay.
    "add", "rem", "remove", "rem_all", "remAll", "remove_all", "removeAll",
})


def _normalise_key(key: str) -> str:
    return key.lower().replace("_", "").replace("-", "")


def _closest(key: str, allowed: "Any") -> Optional[str]:
    """The allowed key a misspelling most likely meant, or None when nothing is close enough."""
    target = _normalise_key(key)
    for candidate in allowed:
        if _normalise_key(candidate) == target:
            return candidate
    # Two letters swapped is the commonest typo of all; same letters in a different order is a
    # transposition and nothing else.
    for candidate in allowed:
        if sorted(_normalise_key(candidate)) == sorted(target):
            return candidate
    best, best_distance = None, None
    for candidate in allowed:
        distance = _edit_distance(target, _normalise_key(candidate))
        if best_distance is None or distance < best_distance:
            best, best_distance = candidate, distance
    # Beyond a third of the key's length the "suggestion" is noise that sends the reader looking in
    # the wrong place, which is worse than offering none.
    return best if best_distance is not None and best_distance <= max(1, len(target) // 3) else None


def _edit_distance(a: str, b: str) -> int:
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1,
                               previous[j - 1] + (0 if ca == cb else 1)))
        previous = current
    return previous[len(b)]


def _check_keys(spec: Dict[str, Any], allowed: "Any", context: str) -> None:
    """Refuse an option key this library does not understand.

    A dict of options is convenient and, without this, silent: a key that is misspelled or in the
    wrong case is simply never read. The command still goes out, the registry still answers 1000,
    and the part you asked for is missing. Nothing in the response says so, because as far as the
    registry is concerned you never asked.
    """
    unknown = [str(k) for k in spec if k not in allowed]
    if not unknown:
        return
    details = []
    for key in sorted(unknown):
        suggestion = _closest(key, allowed)
        details.append("'%s'" % key if suggestion is None
                       else "'%s' (did you mean '%s'?)" % (key, suggestion))
    raise ValidationException("%s does not accept %s. Accepted: %s."
                          % (context, ", ".join(details), ", ".join(sorted(allowed))))


def _check_secdns_keys(spec: Dict[str, Any]) -> None:
    """Refuse a misspelt DNSSEC key instead of silently registering the domain unsigned."""
    _check_keys(spec, _SECDNS_KEYS, "sec_dns")


def _ds_data(spec: Dict[str, Any]) -> List[Dict[str, Any]]:
    return _opt(spec, "ds_data", "dsData") or []


def _key_data(spec: Dict[str, Any]) -> List[Dict[str, Any]]:
    return _opt(spec, "key_data", "keyData") or []


def _max_sig_life(spec: Dict[str, Any]) -> Any:
    return _opt(spec, "max_sig_life", "maxSigLife")


def _is_true(value: Any) -> bool:
    """Truth of a disclosure switch. ``"0"`` / ``"false"`` / ``""`` reach an integrator from HTML
    forms and JSON payloads and are all truthy strings in Python, so every switch is resolved here
    rather than by plain truthiness: ``disclose={"flag": "0"}`` means WITHHOLD, the way the caller
    wrote it, and only a value that really is true consents to publication."""
    if isinstance(value, str):
        return value.strip().lower() not in ("", "0", "false")
    return bool(value)


# The RFC 8748 fee you agree to pay on a transform: '100.00' or {'amount': '100.00',
# 'currency': 'UAH'}. The server refuses (2004) when the real price is higher — you are
# never charged more than you consented to.
FeeAgreement = Union[str, Dict[str, str]]

#: A nameserver is either a name — a host object the registry already holds — or that name together
#: with its glue addresses, inlined in the command: ``{"name": "ns1.example.net", "addresses": [...]}``.
Nameserver = Union[str, Dict[str, Any]]


def _contact_pairs(contacts) -> List[tuple]:
    """Flattens a ``contacts`` option into (role, handle) pairs, accepting EITHER one handle per
    role or SEVERAL: ``{'admin': 'A1', 'tech': ['T1', 'T2']}``.

    RFC 5731 allows repeated ``<domain:contact type="...">`` and the registry parses them into a
    list per role, so every handle is emitted as its own element. Flattening a role's list into one
    element instead would put the literal text ``"['T1', 'T2']"`` on the wire as a single handle.
    """
    out = []
    for ctype, handles in (contacts or {}).items():
        seq = handles if isinstance(handles, (list, tuple)) else [handles]
        for handle in seq:
            h = str(handle if handle is not None else "").strip()
            if h:
                out.append((str(ctype), h))
    return out

#: A fee query carries at most this many <fee:command> entries; a longer one is refused (2306).
MAX_FEE_COMMANDS = 20

_FEE_AMOUNT_RE = re.compile(r"^\d{1,10}(\.\d{1,2})?$")


def _append_fee_agreement(frame: Frame, local: str, fee: FeeAgreement) -> None:
    raw = fee.get("amount") if isinstance(fee, dict) else fee
    currency = fee.get("currency") if isinstance(fee, dict) else None
    # A numeric 0 is a legitimate agreement ("this operation is free"), so the amount is coerced to
    # a string: ElementTree refuses to serialize a non-string and would fail with a raw TypeError
    # far from the call. The shape is checked here too, so '100,00' or '$100' fails with a readable
    # message rather than as an opaque refusal on the wire.
    amount = "" if raw is None else str(raw).strip()
    if _FEE_AMOUNT_RE.match(amount) is None:
        raise ValidationException("fee amount must be a plain decimal like '100.00' (got %r)" % (raw,))
    el = frame.ns(frame.extension(), ns.FEE, "fee:%s" % local)
    if currency:
        frame.ns(el, ns.FEE, "fee:currency", str(currency))
    frame.ns(el, ns.FEE, "fee:fee", amount)


class Domain:
    def __init__(self, client: "Client") -> None:
        self._client = client

    def check(self, names: List[str], fee: Optional[Dict[str, Any]] = None,
              currency: Optional[str] = None) -> Response:
        """Check availability, optionally asking for prices at the same time (RFC 8748).

        ``fee`` is operation -> years. A LIST of years asks the SAME operation at SEVERAL periods
        in the one command, so a whole price table costs one round trip instead of five::

            client.domain.check(["example1.com.ua"], fee={"create": [1, 2, 3, 5, 10], "renew": 1})

        Read the reply with :meth:`Response.fee_for` for a single figure, or
        :meth:`Response.fees` for the lot. Operations: create|renew|transfer|restore|update|delete.

        ``transfer`` and ``restore`` are one-year operations however many years you ask for, and the
        reply echoes the period that would actually be charged — so read those back at one year.

        :param currency: ask for the quote in this currency; omit to take the registry's own. A
            currency it does not price in comes back as unavailable with a reason, not as a
            converted guess.
        """
        frame = self._client.frame()
        check = frame.ns(frame.verb("check"), _D, "domain:check")
        for name in names:
            frame.ns(check, _D, "domain:name", name)
        wanted = []
        for op, years in (fee or {}).items():
            for y in (years if isinstance(years, (list, tuple)) else [years]):
                wanted.append((str(op), max(1, int(y))))
        if len(wanted) > MAX_FEE_COMMANDS:
            raise ValidationException(
                "a fee query carries at most %d entries; this one has %d"
                % (MAX_FEE_COMMANDS, len(wanted))
            )
        if wanted or currency is not None:
            fee_check = frame.ns(frame.extension(), ns.FEE, "fee:check")
            if currency is not None:
                frame.ns(fee_check, ns.FEE, "fee:currency", str(currency).upper())
            for op, y in wanted:
                cmd = frame.ns(fee_check, ns.FEE, "fee:command", None, {"name": op})
                frame.ns(cmd, ns.FEE, "fee:period", str(y), {"unit": "y"})
        return self._client.request(frame)

    def info(self, name: str, auth_info: Optional[str] = None, hosts: str = "all") -> Response:
        """``hosts`` picks which hosts the answer lists: all (default), del, sub or none."""
        frame = self._client.frame()
        info = frame.ns(frame.verb("info"), _D, "domain:info")
        frame.ns(info, _D, "domain:name", name, {"hosts": hosts})
        if auth_info is not None:
            ai = frame.ns(info, _D, "domain:authInfo")
            frame.ns(ai, _D, "domain:pw", auth_info)
        return self._client.request(frame)

    def create_builder(self, name: str) -> "DomainCreateBuilder":
        """Build a registration step by step instead of passing every argument at once.

            client.domain.create_builder("example3.com.ua").years(1).registrant("C1").send()

        Same command, same frame, same result — :meth:`create` is what it calls.
        """
        from .builders import DomainCreateBuilder

        return DomainCreateBuilder(self, name)

    def update_builder(self, name: str) -> "DomainUpdateBuilder":
        """Build a change step by step. See :meth:`create_builder`; this one calls :meth:`update`."""
        from .builders import DomainUpdateBuilder

        return DomainUpdateBuilder(self, name)

    def create(self, name: str, *, years: Optional[int] = None, registrant: Optional[str] = None,
               contacts: Optional[Dict[str, str]] = None,
               nameservers: Optional[List[Nameserver]] = None,
               auth_info: Optional[str] = None, license: Optional[str] = None,
               sec_dns: Optional[Dict[str, Any]] = None,
               fee: Optional[FeeAgreement] = None) -> Response:
        frame = self._client.frame()
        create = frame.ns(frame.verb("create"), _D, "domain:create")
        frame.ns(create, _D, "domain:name", name)
        if years is not None:
            frame.ns(create, _D, "domain:period", str(int(years)), {"unit": "y"})
        if nameservers:
            _append_nameservers(frame, create, nameservers)
        if registrant is not None:
            frame.ns(create, _D, "domain:registrant", registrant)
        for ctype, handle in _contact_pairs(contacts):
            frame.ns(create, _D, "domain:contact", handle, {"type": ctype})
        # authInfo is MANDATORY on domain:create (RFC 5731). Always emit it — with the caller's
        # transfer secret, or an empty <pw/> (pwType allows minLength 0) so the registry applies
        # its per-zone authInfo policy.
        ai = frame.ns(create, _D, "domain:authInfo")
        frame.ns(ai, _D, "domain:pw", auth_info or "")

        if isinstance(sec_dns, dict):
            _check_secdns_keys(sec_dns)
        # secDNS:create requires at least one dsData or keyData record (RFC 5910); an empty or
        # keyless mapping must not emit a childless <secDNS:create/>, which is invalid.
        has_secdns = isinstance(sec_dns, dict) and bool(_ds_data(sec_dns) or _key_data(sec_dns))
        if has_secdns or license is not None:
            ext = frame.extension()
            if has_secdns:
                sec_create = frame.ns(ext, ns.SECDNS, "secDNS:create")
                max_sig_life = _max_sig_life(sec_dns)
                if max_sig_life is not None:
                    frame.ns(sec_create, ns.SECDNS, "secDNS:maxSigLife", str(int(max_sig_life)))
                _append_secdns(frame, sec_create, sec_dns)
            if license is not None:
                uri = self._client.require_registry_ext_uri("domain:create with a licence")
                u = frame.ns(ext, uri, "registry:create")
                frame.ns(u, uri, "registry:license", license)
        if fee is not None:
            _append_fee_agreement(frame, "create", fee)
        return self._client.request(frame)

    def update(self, name: str, *, add: Optional[Dict[str, Any]] = None,
               rem: Optional[Dict[str, Any]] = None, chg: Optional[Dict[str, Any]] = None,
               restore: bool = False, license: Optional[str] = None,
               sec_dns: Optional[Dict[str, Any]] = None,
               fee: Optional[FeeAgreement] = None,
               remove: Optional[Dict[str, Any]] = None,
               change: Optional[Dict[str, Any]] = None) -> Response:
        # PLAIN WORDS BESIDE EPP'S ABBREVIATIONS. `rem` and `chg` are EPP's own, and EPP abbreviates
        # because it is XML on a wire budget; a keyword argument has no wire budget, and a reader who
        # has not memorised RFC 5731 cannot tell `chg` from a typo or guess that `rem` is not short
        # for `remark`. `remove` and `change` are what the documentation shows.
        #
        # THE SHORT FORMS ARE NOT DEPRECATED. This library refuses an unrecognised option rather than
        # ignoring it, so dropping a spelling would turn working code into an exception rather than
        # into silence. Both stay, and the plain word wins when both are given - the only ordering
        # that lets a codebase migrate one call at a time.
        if remove is not None:
            rem = remove
        if change is not None:
            chg = change

        frame = self._client.frame()
        update = frame.ns(frame.verb("update"), _D, "domain:update")
        frame.ns(update, _D, "domain:name", name)

        for op, spec in (("add", add), ("rem", rem)):
            if not spec:
                continue
            block = frame.ns(update, _D, "domain:%s" % op)
            if spec.get("ns"):
                _append_nameservers(frame, block, spec["ns"])
            for ctype, handle in _contact_pairs(spec.get("contacts")):
                frame.ns(block, _D, "domain:contact", handle, {"type": ctype})
            for status in (spec.get("statuses") or []):
                frame.ns(block, _D, "domain:status", None, {"s": status})

        if chg:
            # Both spellings, and nothing else: `auth_info` and the RFC's `authInfo` are read
            # alike, so a mixed call like {"registrant": "C9", "authInfo": "new"} applies both.
            # Any other spelling is refused here rather than left out of the frame, because a key
            # nobody reads is a change that does not happen behind a 1000.
            _check_keys(chg, _DOMAIN_CHG_KEYS, "domain.update chg")
            block = frame.ns(update, _D, "domain:chg")
            registrant = _opt(chg, "registrant")
            if registrant is not None:
                frame.ns(block, _D, "domain:registrant", registrant)
            auth_info = _opt(chg, "auth_info", "authInfo")
            if _opt(chg, "clear_auth_info", "clearAuthInfo"):
                # <authInfo><null/> REMOVES the transfer secret rather than setting it to something.
                # The distinction matters after a leak: an empty <pw/> stores the empty string,
                # which is a value the holder can still present, so the domain stays as movable as
                # it was. Only this clears it. The schema cannot express both at once.
                if auth_info is not None:
                    raise ValidationException(
                        "domain.update chg cannot both set auth_info and clear it — "
                        "drop one of auth_info / clear_auth_info"
                    )
                ai = frame.ns(block, _D, "domain:authInfo")
                frame.ns(ai, _D, "domain:null")
            elif auth_info is not None:
                ai = frame.ns(block, _D, "domain:authInfo")
                frame.ns(ai, _D, "domain:pw", auth_info)

        if restore:
            rgp = frame.ns(frame.extension(), ns.RGP, "rgp:update")
            frame.ns(rgp, ns.RGP, "rgp:restore", None, {"op": "request"})
        if license is not None:
            uri = self._client.require_registry_ext_uri("domain:update with a licence")
            u = frame.ns(frame.extension(), uri, "registry:update")
            frame.ns(u, uri, "registry:license", license)

        # DNSSEC delta (RFC 5910): rem (specific or all), add, chg maxSigLife. At least one of them
        # is required — sec_dns={} must NOT emit a childless <secDNS:update/>, which the server
        # rejects with 2003 for what reads as a no-op, so the DNSSEC change is lost behind a 1000.
        if isinstance(sec_dns, dict) and sec_dns:
            _check_secdns_keys(sec_dns)
            rem_all = _opt(sec_dns, "remove_all", "removeAll", "rem_all", "remAll")
            rem_spec = _opt(sec_dns, "remove", "rem")
            add_spec = _opt(sec_dns, "add")
            max_sig_life = _max_sig_life(sec_dns)
            if rem_all or rem_spec or add_spec or max_sig_life is not None:
                sec_update = frame.ns(frame.extension(), ns.SECDNS, "secDNS:update")
                if rem_all:
                    rem_el = frame.ns(sec_update, ns.SECDNS, "secDNS:rem")
                    frame.ns(rem_el, ns.SECDNS, "secDNS:all", "true")
                elif rem_spec:
                    rem_el = frame.ns(sec_update, ns.SECDNS, "secDNS:rem")
                    _append_secdns(frame, rem_el, rem_spec)
                if add_spec:
                    add_el = frame.ns(sec_update, ns.SECDNS, "secDNS:add")
                    _append_secdns(frame, add_el, add_spec)
                if max_sig_life is not None:
                    chg_sec = frame.ns(sec_update, ns.SECDNS, "secDNS:chg")
                    frame.ns(chg_sec, ns.SECDNS, "secDNS:maxSigLife", str(int(max_sig_life)))
        if fee is not None:
            _append_fee_agreement(frame, "update", fee)
        return self._client.request(frame)

    def renew(self, name: str, cur_exp_date: str, years: int = 1,
              fee: Optional[FeeAgreement] = None) -> Response:
        """Renew a domain.

        ``cur_exp_date`` accepts EITHER form and needs no trimming by the caller: the date the
        registry wants (``2027-04-01``) or the full timestamp its ``<exDate>`` carries
        (``2027-04-01T09:15:00.0Z``), which is what :meth:`Response.expiry_date` returns. See
        :func:`_date_only` for why this is the library's job rather than yours.
        """
        frame = self._client.frame()
        renew = frame.ns(frame.verb("renew"), _D, "domain:renew")
        frame.ns(renew, _D, "domain:name", name)
        frame.ns(renew, _D, "domain:curExpDate", _date_only(cur_exp_date))
        frame.ns(renew, _D, "domain:period", str(int(years)), {"unit": "y"})
        if fee is not None:
            _append_fee_agreement(frame, "renew", fee)
        return self._client.request(frame)

    def delete(self, name: str) -> Response:
        frame = self._client.frame()
        d = frame.ns(frame.verb("delete"), _D, "domain:delete")
        frame.ns(d, _D, "domain:name", name)
        return self._client.request(frame)

    def restore(self, name: str, fee: Optional[FeeAgreement] = None) -> Response:
        """Restore a redemption-period domain (rgp:restore op="request").
        fee: the RFC 8748 restore price you agree to pay."""
        return self.update(name, restore=True, fee=fee)

    def transfer(self, op: str, name: str, auth_info: Optional[str] = None,
                 years: Optional[int] = None, fee: Optional[FeeAgreement] = None) -> Response:
        """op is one of request|approve|reject|cancel|query.
        fee: the RFC 8748 transfer price you agree to pay (request only)."""
        frame = self._client.frame()
        transfer = frame.verb("transfer")
        transfer.set("op", op)
        d = frame.ns(transfer, _D, "domain:transfer")
        frame.ns(d, _D, "domain:name", name)
        if years is not None:
            frame.ns(d, _D, "domain:period", str(int(years)), {"unit": "y"})
        if auth_info is not None:
            ai = frame.ns(d, _D, "domain:authInfo")
            frame.ns(ai, _D, "domain:pw", auth_info)
        if fee is not None:
            _append_fee_agreement(frame, "transfer", fee)
        return self._client.request(frame)


def _append_secdns(frame: Frame, parent: ET.Element, spec: Dict[str, Any]) -> None:
    """Append RFC 5910 dsData / keyData records to a secDNS block (create / add / rem).

    Record fields accept the snake_case and the RFC camelCase spelling alike (see _opt)."""
    for ds in _ds_data(spec):
        ds_data = frame.ns(parent, ns.SECDNS, "secDNS:dsData")
        frame.ns(ds_data, ns.SECDNS, "secDNS:keyTag", str(int(_opt(ds, "key_tag", "keyTag", default=0))))
        frame.ns(ds_data, ns.SECDNS, "secDNS:alg", str(int(_opt(ds, "alg", default=0))))
        frame.ns(ds_data, ns.SECDNS, "secDNS:digestType", str(int(_opt(ds, "digest_type", "digestType", default=0))))
        frame.ns(ds_data, ns.SECDNS, "secDNS:digest", str(_opt(ds, "digest", default="")))
        # RFC 5910 lets a DS record carry the DNSKEY it was computed from. Registries that accept
        # it can verify the digest for you; ones that do not answer 2306 rather than ignoring it.
        nested = _opt(ds, "key_data", "keyData")
        if isinstance(nested, dict):
            _append_key_data(frame, ds_data, nested)
    for key in _key_data(spec):
        _append_key_data(frame, parent, key)


def _append_key_data(frame: Frame, parent, key: Dict[str, Any]) -> None:
    """One <secDNS:keyData> block, in the element order the schema fixes."""
    key_data = frame.ns(parent, ns.SECDNS, "secDNS:keyData")
    frame.ns(key_data, ns.SECDNS, "secDNS:flags", str(int(_opt(key, "flags", default=257))))
    frame.ns(key_data, ns.SECDNS, "secDNS:protocol", str(int(_opt(key, "protocol", default=3))))
    frame.ns(key_data, ns.SECDNS, "secDNS:alg", str(int(_opt(key, "alg", default=0))))
    frame.ns(key_data, ns.SECDNS, "secDNS:pubKey", str(_opt(key, "pub_key", "pubKey", default="")))


class Contact:
    #: The reserved id that asks the registry to CHOOSE the handle instead of you naming it.
    #:
    #: Send it in place of a contact id on create. It is a request, not a name — the handle the
    #: registry mints comes back in the response, and that reply is the only place it appears, so
    #: store what :meth:`Response.object_name` gives you.
    AUTO_ID = "autonic"

    def __init__(self, client: "Client") -> None:
        self._client = client

    def create_auto(self, **options: Any) -> Response:
        """Create a contact and let the registry choose the handle. Read it back with object_name()::

            handle = client.contact.create_auto(email="contact@example.com", ...).object_name()

        Useful when you have no naming scheme of your own, and when you would otherwise have to
        retry around 2302 because someone else took the handle first. Every call mints a fresh one,
        so a repeat is a second contact, never a collision.
        """
        return self.create(self.AUTO_ID, **options)

    def check(self, ids: List[str]) -> Response:
        frame = self._client.frame()
        check = frame.ns(frame.verb("check"), _ADMIN, "contact:check")
        for cid in ids:
            frame.ns(check, _ADMIN, "contact:id", cid)
        return self._client.request(frame)

    def info(self, contact_id: str, auth_info: Optional[str] = None) -> Response:
        frame = self._client.frame()
        info = frame.ns(frame.verb("info"), _ADMIN, "contact:info")
        frame.ns(info, _ADMIN, "contact:id", contact_id)
        if auth_info is not None:
            ai = frame.ns(info, _ADMIN, "contact:authInfo")
            frame.ns(ai, _ADMIN, "contact:pw", auth_info)
        return self._client.request(frame)

    def create_builder(self, contact_id: str, email: str) -> "ContactCreateBuilder":
        """Build a contact step by step. The id and e-mail are required by the registry, so they
        are arguments here rather than steps you can forget.

        Pass :data:`Contact.AUTO_ID` as the id to have the registry mint the handle.
        """
        from .builders import ContactCreateBuilder

        return ContactCreateBuilder(self, contact_id, email)

    def update_builder(self, contact_id: str) -> "ContactUpdateBuilder":
        """Build a contact change step by step."""
        from .builders import ContactUpdateBuilder

        return ContactUpdateBuilder(self, contact_id)

    def create(self, contact_id: str, *, name: Optional[str] = None, org: Optional[str] = None,
               street: Optional[List[str]] = None, city: Optional[str] = None,
               sp: Optional[str] = None, pc: Optional[str] = None, cc: Optional[str] = None,
               type: str = "int", postal_infos: Optional[List[Dict[str, Any]]] = None,
               voice: Optional[str] = None, fax: Optional[str] = None,
               email: Optional[str] = None, auth_info: Optional[str] = None,
               disclose: Optional[Dict[str, Any]] = None) -> Response:
        frame = self._client.frame()
        c = frame.ns(frame.verb("create"), _ADMIN, "contact:create")
        frame.ns(c, _ADMIN, "contact:id", contact_id)

        if postal_infos:
            for pi in postal_infos:
                _append_postal(frame, c, pi)
        else:
            _append_postal(frame, c, {"name": name, "org": org, "street": street, "city": city,
                                      "sp": sp, "pc": pc, "cc": cc, "type": type})
        if voice:
            frame.ns(c, _ADMIN, "contact:voice", voice)
        if fax:
            frame.ns(c, _ADMIN, "contact:fax", fax)
        if not email:
            # RFC 5733 requires a contact email (emailType minLength 1). Fail fast client-side.
            raise ValidationException("contact.create() requires a non-empty 'email'")
        frame.ns(c, _ADMIN, "contact:email", email)
        ai = frame.ns(c, _ADMIN, "contact:authInfo")
        frame.ns(ai, _ADMIN, "contact:pw", auth_info or "")
        if disclose:
            _append_disclose(frame, c, disclose)
        return self._client.request(frame)

    def update(self, contact_id: str, *, add_statuses: Optional[List[str]] = None,
               rem_statuses: Optional[List[str]] = None,
               chg: Optional[Dict[str, Any]] = None,
               remove_statuses: Optional[List[str]] = None,
               change: Optional[Dict[str, Any]] = None) -> Response:
        # Plain words beside EPP's abbreviations - see Domain.update() for why both spellings stay.
        if remove_statuses is not None:
            rem_statuses = remove_statuses
        if change is not None:
            chg = change

        frame = self._client.frame()
        update = frame.ns(frame.verb("update"), _ADMIN, "contact:update")
        frame.ns(update, _ADMIN, "contact:id", contact_id)
        # contact:updateType allows a SINGLE add/rem block (each holding up to 7 statuses); emit
        # the wrapper once and append every status into it.
        if add_statuses:
            add = frame.ns(update, _ADMIN, "contact:add")
            for status in add_statuses:
                frame.ns(add, _ADMIN, "contact:status", None, {"s": status})
        if rem_statuses:
            rem = frame.ns(update, _ADMIN, "contact:rem")
            for status in rem_statuses:
                frame.ns(rem, _ADMIN, "contact:status", None, {"s": status})
        if chg:
            # Both spellings, and nothing else — see the note on domain.update's chg.
            _check_keys(chg, _CONTACT_CHG_KEYS, "contact.update chg")
            block = frame.ns(update, _ADMIN, "contact:chg")
            # RFC 5733 chg order: postalInfo*, voice?, fax?, email?, authInfo?, disclose?
            pis = _opt(chg, "postal_infos", "postalInfos")
            single = _opt(chg, "postal_info", "postalInfo")
            if pis is None and single is not None:
                pis = [single]
            for pi in (pis or []):
                _append_postal(frame, block, pi, partial=True)
            if "voice" in chg:
                frame.ns(block, _ADMIN, "contact:voice", chg["voice"])
            if "fax" in chg:
                frame.ns(block, _ADMIN, "contact:fax", chg["fax"])
            if "email" in chg:
                frame.ns(block, _ADMIN, "contact:email", chg["email"])
            auth_info = _opt(chg, "auth_info", "authInfo")
            if auth_info is not None:
                ai = frame.ns(block, _ADMIN, "contact:authInfo")
                frame.ns(ai, _ADMIN, "contact:pw", auth_info)
            if chg.get("disclose"):
                _append_disclose(frame, block, chg["disclose"])
        return self._client.request(frame)

    def delete(self, contact_id: str) -> Response:
        frame = self._client.frame()
        d = frame.ns(frame.verb("delete"), _ADMIN, "contact:delete")
        frame.ns(d, _ADMIN, "contact:id", contact_id)
        return self._client.request(frame)

    def transfer(self, op: str, contact_id: str, auth_info: Optional[str] = None) -> Response:
        frame = self._client.frame()
        transfer = frame.verb("transfer")
        transfer.set("op", op)
        c = frame.ns(transfer, _ADMIN, "contact:transfer")
        frame.ns(c, _ADMIN, "contact:id", contact_id)
        if auth_info is not None:
            ai = frame.ns(c, _ADMIN, "contact:authInfo")
            frame.ns(ai, _ADMIN, "contact:pw", auth_info)
        return self._client.request(frame)


def _append_postal(frame: Frame, parent: ET.Element, pi: Dict[str, Any],
                   partial: bool = False) -> None:
    """Build one <contact:postalInfo> block from name/org/street/city/sp/pc/cc/type.

    On an update (``partial=True``) PRESENCE decides. A key you leave out is not sent, so the
    registry keeps what it holds; a key present but EMPTY is sent as an empty element, which is how
    an optional field (org, sp, pc) is cleared. On a create every field is sent, because there is
    nothing to merge with.
    """
    block = frame.ns(parent, _ADMIN, "contact:postalInfo", None, {"type": pi.get("type") or "int"})

    # A postalInfo inside <contact:chg> REPLACES the stored one. It is not merged field by field.
    #
    # RFC 5733 can be read the other way: in chgPostalInfoType each of name/org/addr is optional,
    # which looks like "omit it and the registry keeps what it holds". That reading is not safe.
    # Against a registry that replaces, a chg carrying only <contact:org/> answers **1000** and leaves
    # the contact with NO postalInfo at all — name, street, city, postal code and country gone, in
    # both the int and loc blocks — and a complete block sent without an <org> removes the
    # organisation just as surely.
    #
    # So the short form does not fail, it DESTROYS, and it reports success while doing it. A client
    # cannot tell a replacing registry from a merging one, and the cost of guessing wrong is a
    # registrant's postal address. Every change therefore carries the whole block.
    for required in ("name", "city", "cc"):
        if not str(pi.get(required) or "").strip():
            raise ValidationException(
                "postalInfo: a <contact:postalInfo> is REPLACED as a whole, not merged, so every "
                f'change must carry the complete block — "{required}" is missing. (A registry that '
                "replaces answers 1000 and silently drops everything you left out.) Read the current "
                "block with contact.info() and send it back with your change applied."
            )

    # name is postalLineType, minLength 1: there is NO WAY to clear a name. An empty element is
    # schema-invalid and the server answers a bare 2001 naming no field — refused here, where the
    # message can say so.
    _require_not_empty(pi.get("name"), "name")
    frame.ns(block, _ADMIN, "contact:name", pi["name"])

    # org is optPostalLineType, which HAS no minLength — an empty one is legal and is exactly how an
    # organisation is removed.
    if ("org" in pi) if partial else bool(pi.get("org")):
        frame.ns(block, _ADMIN, "contact:org", pi.get("org") or "")

    # <addr> is a sequence with a required city and cc, and it is always emitted: the block replaces
    # what the registry holds, so leaving the address out is what deletes it. The required parts were
    # already asserted above, before anything was written.

    addr = frame.ns(block, _ADMIN, "contact:addr")
    for line in (pi.get("street") or []):
        frame.ns(addr, _ADMIN, "contact:street", line)
    frame.ns(addr, _ADMIN, "contact:city", pi["city"])
    if ("sp" in pi) if partial else bool(pi.get("sp")):
        frame.ns(addr, _ADMIN, "contact:sp", pi.get("sp") or "")
    if ("pc" in pi) if partial else bool(pi.get("pc")):
        frame.ns(addr, _ADMIN, "contact:pc", pi.get("pc") or "")
    frame.ns(addr, _ADMIN, "contact:cc", pi["cc"])


def _require_not_empty(value: Any, field: str) -> None:
    """Refuse an empty value for an element whose schema type forbids one.

    The distinction is not a house rule, it is contact-1.0.xsd: ``optPostalLineType`` (org, street,
    sp) has no minLength and ``pcType`` has none either, so those four clear by being sent empty.
    ``postalLineType`` (name, city) has minLength 1 and ``ccType`` is exactly two characters, so an
    empty one of those cannot be sent at all. Getting it wrong costs a round trip and returns a bare
    2001 with no field named — the least useful error in EPP.
    """
    if not str(value or "").strip():
        raise ValidationException(
            'postalInfo: "%s" cannot be empty — RFC 5733 gives it a schema type with a minimum '
            "length, so there is no way to clear it. Omit the key to leave it unchanged." % field
        )


def _append_disclose(frame: Frame, parent: ET.Element, disclose: Dict[str, Any]) -> None:
    """Build a <contact:disclose flag="0|1"> block. name/org/addr take a list of types
    (int|loc); voice/fax/email are bare flags. Every flag is read through _is_true, so the
    string "0" means HIDE."""
    flag = "1" if _is_true(disclose.get("flag")) else "0"
    disc = frame.ns(parent, _ADMIN, "contact:disclose", None, {"flag": flag})
    for f in ("name", "org", "addr"):
        if f not in disclose:
            continue
        for t in disclose[f]:
            frame.ns(disc, _ADMIN, "contact:%s" % f, None, {"type": t})
    for f in ("voice", "fax", "email"):
        if _is_true(disclose.get(f)):
            frame.ns(disc, _ADMIN, "contact:%s" % f)


class Host:
    def __init__(self, client: "Client") -> None:
        self._client = client

    def check(self, names: List[str]) -> Response:
        frame = self._client.frame()
        check = frame.ns(frame.verb("check"), _H, "host:check")
        for name in names:
            frame.ns(check, _H, "host:name", name)
        return self._client.request(frame)

    def info(self, name: str) -> Response:
        frame = self._client.frame()
        info = frame.ns(frame.verb("info"), _H, "host:info")
        frame.ns(info, _H, "host:name", name)
        return self._client.request(frame)

    def create(self, name: str, addresses: Optional[List[str]] = None) -> Response:
        """addresses: IPv4 or IPv6 literals; the version is auto-detected."""
        frame = self._client.frame()
        create = frame.ns(frame.verb("create"), _H, "host:create")
        frame.ns(create, _H, "host:name", name)
        for ip in (addresses or []):
            frame.ns(create, _H, "host:addr", ip, {"ip": _ip_version(ip)})
        return self._client.request(frame)

    def update_builder(self, name: str) -> "HostUpdateBuilder":
        """Build a nameserver change step by step."""
        from .builders import HostUpdateBuilder

        return HostUpdateBuilder(self, name)

    def update(self, name: str, *, add_addresses: Optional[List[str]] = None,
               rem_addresses: Optional[List[str]] = None, add_statuses: Optional[List[str]] = None,
               rem_statuses: Optional[List[str]] = None, new_name: Optional[str] = None,
               remove_addresses: Optional[List[str]] = None,
               remove_statuses: Optional[List[str]] = None) -> Response:
        # Plain words beside EPP's abbreviations - see Domain.update() for why both spellings stay.
        if remove_addresses is not None:
            rem_addresses = remove_addresses
        if remove_statuses is not None:
            rem_statuses = remove_statuses

        frame = self._client.frame()
        update = frame.ns(frame.verb("update"), _H, "host:update")
        frame.ns(update, _H, "host:name", name)
        for op, addrs, statuses in (("add", add_addresses, add_statuses),
                                    ("rem", rem_addresses, rem_statuses)):
            addrs = addrs or []
            statuses = statuses or []
            if not addrs and not statuses:
                continue
            block = frame.ns(update, _H, "host:%s" % op)
            for ip in addrs:
                frame.ns(block, _H, "host:addr", ip, {"ip": _ip_version(ip)})
            for status in statuses:
                frame.ns(block, _H, "host:status", None, {"s": status})
        # RENAMING IS NOT SUPPORTED by this registry: it reads only <host:add> and <host:rem>, so a
        # <host:chg> is discarded without comment. Sending one lets an address change in the same
        # frame succeed while the rename does not, and the caller is told 1000 — or, with new_name
        # alone, the frame carries no change at all and draws an opaque 2003. Refused here so the
        # answer comes from your own code, where it names the problem.
        if new_name:
            from .exceptions import ValidationException

            raise ValidationException(
                "host rename is not supported by this registry (host:chg is ignored) — "
                "create the new host, re-point the domains with domain:update, then delete the old one"
            )
        return self._client.request(frame)

    def delete(self, name: str, force: bool = False) -> Response:
        frame = self._client.frame()
        d = frame.ns(frame.verb("delete"), _H, "host:delete")
        frame.ns(d, _H, "host:name", name)
        if force:
            # Registry extension: detach the host from every domain before deleting it. Not every
            # registry offers this, so the URI comes from the greeting and its absence is reported
            # rather than guessed at — a forced delete sent without the extension the server knows is
            # an ORDINARY delete, which fails on a host that is still in use and leaves the caller
            # wondering why `force` did nothing.
            uri = self._client.require_registry_ext_uri("host:delete with force")
            u = frame.ns(frame.extension(), uri, "registry:delete")
            frame.ns(u, uri, "registry:deleteNS", None, {"confirm": "yes"})
        return self._client.request(frame)


class Poll:
    def __init__(self, client: "Client") -> None:
        self._client = client

    def request(self) -> Response:
        """Request the next service message (1301 with a message, 1300 when empty)."""
        frame = self._client.frame()
        frame.verb("poll").set("op", "req")
        return self._client.request(frame)

    def ack(self, message_id: str) -> Response:
        """Acknowledge a message, which DELETES it at the registry. There is no way to get it back."""
        frame = self._client.frame()
        poll = frame.verb("poll")
        poll.set("op", "ack")
        poll.set("msgID", str(message_id))
        return self._client.request(frame)

    def drain(self, handler: Callable[[Response], None], limit: int = 0) -> int:
        """Read the queue to the end, handing each notice to your callback::

            client.poll.drain(lambda notice: store(notice.queue_message()))

        The ORDER is the point, and it is the thing this loop exists to get right: the message is
        acknowledged only AFTER your callback returns. An ack deletes the notice at the registry
        permanently, so a loop that acks first and processes second loses every notice whose
        processing fails — a transfer request, a delete notification, the outcome of a pending
        create — with nothing left to retry from and no record that anything was lost.

        So: if your callback raises, the notice is NOT acked. It stays at the head of the queue and
        the exception reaches you. Fix the cause and drain again; nothing was lost. That also means
        a callback which always raises will see the same notice every time — deliberately, because
        the alternative is discarding it.

        Delivery is AT LEAST ONCE. If the acknowledgement itself fails — the connection drops
        between your callback returning and the ack landing — the notice is still in the queue and
        the next drain hands it to you again. Make the callback idempotent and use
        :meth:`Response.message_id` as the de-duplication key.

        Returns the number of notices processed successfully; stops at the first empty queue (1300).
        Any other reply that carries no notice is raised rather than read as "empty".

        :param limit: stop after this many notices; 0 means "until the queue is empty". A queue
            that fills faster than you drain it would otherwise keep this call running forever.
        """
        from .exceptions import command_exception_for
        from .result_code import ResultCode

        if inspect.iscoroutinefunction(handler):
            # An async handler returns a coroutine the moment it is called, so this loop would ack
            # every notice before any of them had been processed — the exact loss this method
            # exists to prevent, and silently.
            raise ValidationException(
                "poll.drain() runs synchronously and cannot await an async handler — "
                "wrap it, or drive the queue yourself with request() and ack()"
            )
        processed = 0
        while limit == 0 or processed < limit:
            notice = self.request()
            # Only 1300 means the queue is empty. Inferring emptiness from "no <msgQ>" would make a
            # refusal — the session closed, the account suspended — look exactly like a drained
            # queue, and the loop would report success while nothing had been read.
            if notice.code() == ResultCode.SUCCESS_NO_MESSAGES:
                break
            message_id = notice.message_id()
            if message_id is None:
                raise command_exception_for(
                    notice.code(),
                    "poll returned neither a message nor an empty queue (EPP %d: %s)"
                    % (notice.code(), notice.message() or "no message"),
                    notice,
                )
            handler(notice)
            self.ack(message_id)
            processed += 1
        return processed
