"""Fluent command builders.

A builder is a typed façade over the keyword arguments the command takes. It builds no XML of its
own: ``send()`` hands the options straight to the ordinary method, so a builder and the equivalent
call produce the identical frame, and every check that applies to one applies to the other.

Python's keyword arguments already give you named parameters and a loud ``TypeError`` on a
misspelling, so reach for a builder when the command is assembled in pieces — across branches, in
a loop, or from a form — rather than written out in one place. Both forms are supported::

    client.domain.create("example3.com.ua", years=1, registrant="C1")          # direct

    (client.domain.create_builder("example3.com.ua")                          # step by step
        .years(1)
        .registrant("C1")
        .nameserver("ns1.example")
        .send())
"""

from __future__ import annotations

import copy
import re
from typing import Any, Dict, List, Optional, Sequence

from .exceptions import ValidationException
from .response import Response

_FEE_AMOUNT_RE = re.compile(r"^\d{1,10}(\.\d{1,2})?$")


def _fee_agreement(amount: str, currency: Optional[str]) -> Any:
    """The RFC 8748 fee AGREEMENT: the most you consent to pay.

    Not a price you set — the registry charges its own. If the real price is HIGHER the command is
    refused (2004) and nothing is charged, which is the point: a tariff change or a premium name
    cannot bill you more than you agreed to.
    """
    value = str(amount).strip()
    if _FEE_AMOUNT_RE.match(value) is None:
        # Checked here rather than on the wire: a malformed agreement draws a bare 2001 that names
        # no field, and it arrives after the command has been attempted.
        raise ValidationException(
            "a fee amount must be a plain decimal like '100.00' (got %r)" % (value,)
        )
    return value if currency is None else {"amount": value, "currency": currency}


def _ds_record(key_tag: int, alg: int, digest_type: int, digest: str) -> Dict[str, Any]:
    value = str(digest or "").strip()
    if not value:
        raise ValidationException("a DS record needs a digest")
    return {"key_tag": key_tag, "alg": alg, "digest_type": digest_type, "digest": value}


def _key_record(flags: int, protocol: int, alg: int, pub_key: str) -> Dict[str, Any]:
    value = str(pub_key or "").strip()
    if not value:
        raise ValidationException("a key record needs a public key")
    return {"flags": flags, "protocol": protocol, "alg": alg, "pub_key": value}


def _postal_info(kind: str, name: str, city: str, country_code: str,
                 street: Sequence[str] = (), org: Optional[str] = None,
                 state_province: Optional[str] = None,
                 postal_code: Optional[str] = None) -> Dict[str, Any]:
    block: Dict[str, Any] = {"type": kind, "name": name, "city": city, "cc": country_code}
    if street:
        block["street"] = [str(line) for line in street]
    if org is not None:
        block["org"] = org
    if state_province is not None:
        block["sp"] = state_province
    if postal_code is not None:
        block["pc"] = postal_code
    return block


def _disclosure(publish: bool, fields: Sequence[str]) -> Dict[str, Any]:
    spec: Dict[str, Any] = {"flag": publish}
    for field in fields:
        name = str(field).strip()
        # name/org/addr exist once per postal form, so the choice is per form. Both are named:
        # withholding only the ASCII form while the local one stays public is a privacy setting
        # that reads as applied and is not.
        if name in ("name", "org", "addr"):
            spec[name] = ["int", "loc"]
        elif name in ("voice", "fax", "email"):
            spec[name] = True
        else:
            raise ValidationException(
                "%r is not a disclosable field. Use: name, org, addr, voice, fax, email." % (name,)
            )
    return spec


def _append(target: Dict[str, Any], key: str, values: Sequence[str]) -> Dict[str, Any]:
    existing: List[str] = list(target.get(key) or [])
    for value in values:
        text = str(value).strip()
        if text:
            existing.append(text)
    target[key] = existing
    return target


def _append_contacts(target: Dict[str, Any], role: str, handles: Sequence[str]) -> Dict[str, Any]:
    name = str(role).strip()
    if not name:
        raise ValidationException("a contact role must not be empty (admin, tech, billing, …)")
    return _append(target, name, handles)


class Builder:
    """Shared behaviour of the fluent builders."""

    def __init__(self, handler: Any, object_id: str) -> None:
        self._handler = handler
        self._id = object_id
        self._options: Dict[str, Any] = {}
        self._sent = False

    def to_options(self) -> Dict[str, Any]:
        """The options as the equivalent direct call would take them.

        Useful for a dry run, for logging what you are about to do, or for handing the command to a
        queue. Sends nothing and does not spend the builder.
        """
        # A COPY, and a deep one: the result is a value you can keep, log or queue. Handing back
        # the live dict would make it change under the caller every time another step is added, so
        # what was logged and what was sent could differ.
        return copy.deepcopy(self._options)

    def _mark_sent(self) -> None:
        # A builder is a command that has not happened yet, so sending it twice would be two
        # registrations and two charges — and the second is never what the caller meant.
        if self._sent:
            raise ValidationException(
                "%s has already been sent. A builder carries one command; build another rather "
                "than re-sending this one." % type(self).__name__
            )
        self._sent = True


class DomainCreateBuilder(Builder):
    """Registers a domain, one named step at a time."""

    def years(self, years: int) -> "DomainCreateBuilder":
        """Registration period in years. Omit it and the registry applies its own default."""
        self._options["years"] = years
        return self

    def registrant(self, handle: str) -> "DomainCreateBuilder":
        """The registrant — the holder of the domain. Required by the registry."""
        self._options["registrant"] = handle
        return self

    def contact(self, role: str, *handles: str) -> "DomainCreateBuilder":
        """Attach contacts in a role.

        Every list method ACCUMULATES: pass several at once, or call it again, or both — the effect
        is the same. RFC 5731 puts no limit on handles per role.
        """
        self._options["contacts"] = _append_contacts(self._options.get("contacts") or {}, role, handles)
        return self

    def admin_contact(self, *handles: str) -> "DomainCreateBuilder":
        """The people authorised to make decisions about the domain. Accumulates."""
        return self.contact("admin", *handles)

    def tech_contact(self, *handles: str) -> "DomainCreateBuilder":
        """The people to reach about DNS and delegation. Accumulates."""
        return self.contact("tech", *handles)

    def billing_contact(self, *handles: str) -> "DomainCreateBuilder":
        """The people to reach about invoices for this domain. Accumulates."""
        return self.contact("billing", *handles)

    def nameserver(self, host: str) -> "DomainCreateBuilder":
        """One nameserver to delegate to. Accumulates; suits a loop or a conditional."""
        return self.nameservers(host)

    def nameservers(self, *hosts: str) -> "DomainCreateBuilder":
        """The nameservers to delegate to. Accumulates."""
        _append(self._options, "nameservers", hosts)
        return self

    def nameserver_with_glue(self, host: str, *addresses: str) -> "DomainCreateBuilder":
        """A nameserver given with its glue addresses, inlined in the command (RFC 5731 hostAttr).

        Use this where the registry expects the addresses with the name rather than a reference to
        a host object created beforehand; ask yours which model it takes. A command cannot mix the
        two, so use either this or :meth:`nameserver`, not both.
        """
        name = str(host).strip()
        if not name:
            raise ValidationException("a nameserver name must not be empty")
        # Appended directly rather than through _append(), which is for plain names and would
        # stringify this one into a hostObj reading "{'name': ...}".
        existing = list(self._options.get("nameservers") or [])
        existing.append({"name": name, "addresses": [str(a) for a in addresses]})
        self._options["nameservers"] = existing
        return self

    def auth_info(self, password: str) -> "DomainCreateBuilder":
        """The transfer secret.

        Anyone holding it can move the domain to another registrar, so treat it as a credential:
        never log it, and roll it after handing it to a customer.
        """
        self._options["auth_info"] = password
        return self

    def license(self, number: str) -> "DomainCreateBuilder":
        """A trademark or licence number, for registries that require one to register a name."""
        self._options["license"] = number
        return self

    def max_fee(self, amount: str, currency: Optional[str] = None) -> "DomainCreateBuilder":
        """The most you agree to pay for this registration (RFC 8748).

        Optional: without it the registry's own price is charged; with it, a higher real price
        refuses the command instead of billing you the difference.
        """
        self._options["fee"] = _fee_agreement(amount, currency)
        return self

    def ds_record(self, key_tag: int, alg: int, digest_type: int, digest: str) -> "DomainCreateBuilder":
        """Sign the domain with a DS record (RFC 5910). Call it again for a second key."""
        sec = self._options.get("sec_dns") or {}
        sec["ds_data"] = list(sec.get("ds_data") or []) + [_ds_record(key_tag, alg, digest_type, digest)]
        self._options["sec_dns"] = sec
        return self

    def ds_record_with_key(self, key_tag: int, alg: int, digest_type: int, digest: str,
                           flags: int, protocol: int, key_alg: int,
                           pub_key: str) -> "DomainCreateBuilder":
        """A DS record that carries the DNSKEY it was computed from (RFC 5910).

        A registry that accepts this can verify the digest against the key for you, catching a
        mistyped digest before it reaches the zone. One that does not accept DNSKEY data refuses the
        command rather than ignoring the extra element, so trying costs you nothing but a 2306.
        """
        sec = self._options.get("sec_dns") or {}
        record = _ds_record(key_tag, alg, digest_type, digest)
        record["key_data"] = _key_record(flags, protocol, key_alg, pub_key)
        sec["ds_data"] = list(sec.get("ds_data") or []) + [record]
        self._options["sec_dns"] = sec
        return self

    def key_record(self, flags: int, protocol: int, alg: int, pub_key: str) -> "DomainCreateBuilder":
        """Sign with a public key instead, where the registry accepts one."""
        sec = self._options.get("sec_dns") or {}
        sec["key_data"] = list(sec.get("key_data") or []) + [_key_record(flags, protocol, alg, pub_key)]
        self._options["sec_dns"] = sec
        return self

    def max_sig_life(self, seconds: int) -> "DomainCreateBuilder":
        """Maximum signature lifetime in seconds. Only meaningful alongside a DS or key record."""
        sec = self._options.get("sec_dns") or {}
        sec["max_sig_life"] = seconds
        self._options["sec_dns"] = sec
        return self

    def send(self) -> Response:
        """Send the command and return the registry's answer."""
        self._mark_sent()
        return self._handler.create(self._id, **self._options)


class DomainUpdateBuilder(Builder):
    """Changes a domain, one named step at a time.

    An EPP update is a DELTA, not a replacement: what you do not mention is left alone. The method
    names say which of the three blocks each change lands in — add, rem or chg — because that
    distinction is the whole semantics of the command.
    """

    def _block(self, name: str) -> Dict[str, Any]:
        block = self._options.get(name) or {}
        self._options[name] = block
        return block

    def add_nameserver(self, host: str) -> "DomainUpdateBuilder":
        """Delegate to one more nameserver. Accumulates."""
        return self.add_nameservers(host)

    def add_nameservers(self, *hosts: str) -> "DomainUpdateBuilder":
        """Delegate to these nameservers as well as the ones already there. Accumulates."""
        _append(self._block("add"), "ns", hosts)
        return self

    def rem_nameserver(self, host: str) -> "DomainUpdateBuilder":
        """Stop delegating to one nameserver. Accumulates."""
        return self.rem_nameservers(host)

    def rem_nameservers(self, *hosts: str) -> "DomainUpdateBuilder":
        """Stop delegating to these nameservers. Accumulates."""
        _append(self._block("rem"), "ns", hosts)
        return self

    def add_contact(self, role: str, *handles: str) -> "DomainUpdateBuilder":
        """Attach contacts in a role, keeping the ones already there."""
        block = self._block("add")
        block["contacts"] = _append_contacts(block.get("contacts") or {}, role, handles)
        return self

    def rem_contact(self, role: str, *handles: str) -> "DomainUpdateBuilder":
        """Detach contacts from a role."""
        block = self._block("rem")
        block["contacts"] = _append_contacts(block.get("contacts") or {}, role, handles)
        return self

    def add_status(self, *statuses: str) -> "DomainUpdateBuilder":
        """Set a client-side status, e.g. ``clientHold`` (takes the domain out of DNS)."""
        _append(self._block("add"), "statuses", statuses)
        return self

    def rem_status(self, *statuses: str) -> "DomainUpdateBuilder":
        """Clear a client-side status."""
        _append(self._block("rem"), "statuses", statuses)
        return self

    def change_registrant(self, handle: str) -> "DomainUpdateBuilder":
        """Hand the domain to a different holder.

        Many registries treat this as a change of ownership with its own rules, so a refusal is
        usually policy rather than a malformed command.
        """
        self._block("chg")["registrant"] = handle
        return self

    def change_auth_info(self, password: str) -> "DomainUpdateBuilder":
        """Replace the transfer secret."""
        self._block("chg")["auth_info"] = password
        return self

    def clear_auth_info(self) -> "DomainUpdateBuilder":
        """REMOVE the transfer secret entirely, so no code will move this domain.

        This is the answer to a leak, and it is not the same as setting an empty one: an empty
        password is a value the holder can still present, so the domain stays exactly as movable as
        it was. Only this clears it. Set a fresh one with :meth:`change_auth_info` when the customer
        needs it again.
        """
        self._block("chg")["clear_auth_info"] = True
        return self

    def restore(self) -> "DomainUpdateBuilder":
        """Ask to bring a deleted domain back from the redemption period (RFC 3915)."""
        self._options["restore"] = True
        return self

    def license(self, number: str) -> "DomainUpdateBuilder":
        """A trademark or licence number, for registries that require one."""
        self._options["license"] = number
        return self

    def max_fee(self, amount: str, currency: Optional[str] = None) -> "DomainUpdateBuilder":
        """The most you agree to pay, when the change is a billable one (RFC 8748)."""
        self._options["fee"] = _fee_agreement(amount, currency)
        return self

    def add_ds_record(self, key_tag: int, alg: int, digest_type: int, digest: str) -> "DomainUpdateBuilder":
        """Add a DS record to an existing domain."""
        return self._sec_dns("add", "ds_data", _ds_record(key_tag, alg, digest_type, digest))

    def rem_ds_record(self, key_tag: int, alg: int, digest_type: int, digest: str) -> "DomainUpdateBuilder":
        """Remove one specific DS record. Everything must match what the registry holds."""
        return self._sec_dns("rem", "ds_data", _ds_record(key_tag, alg, digest_type, digest))

    def add_key_record(self, flags: int, protocol: int, alg: int, pub_key: str) -> "DomainUpdateBuilder":
        """Add a public key to an existing domain."""
        return self._sec_dns("add", "key_data", _key_record(flags, protocol, alg, pub_key))

    def rem_key_record(self, flags: int, protocol: int, alg: int, pub_key: str) -> "DomainUpdateBuilder":
        """Remove one specific public key."""
        return self._sec_dns("rem", "key_data", _key_record(flags, protocol, alg, pub_key))

    def remove_all_dnssec(self) -> "DomainUpdateBuilder":
        """Unsign the domain entirely.

        Mutually exclusive with removing specific records — the protocol has no way to express
        both, and a frame carrying both is refused. Refused here instead, where the message can say
        so.
        """
        sec = self._options.get("sec_dns") or {}
        if "rem" in sec:
            raise ValidationException(
                "remove_all_dnssec() cannot be combined with rem_ds_record()/rem_key_record() — "
                "remove everything, or name what to remove, not both"
            )
        sec["rem_all"] = True
        self._options["sec_dns"] = sec
        return self

    def max_sig_life(self, seconds: int) -> "DomainUpdateBuilder":
        """Maximum signature lifetime in seconds."""
        sec = self._options.get("sec_dns") or {}
        sec["max_sig_life"] = seconds
        self._options["sec_dns"] = sec
        return self

    def send(self) -> Response:
        """Send the command and return the registry's answer."""
        self._mark_sent()
        return self._handler.update(self._id, **self._options)

    def _sec_dns(self, block: str, kind: str, record: Dict[str, Any]) -> "DomainUpdateBuilder":
        sec = self._options.get("sec_dns") or {}
        if block == "rem" and sec.get("rem_all"):
            raise ValidationException(
                "rem_ds_record()/rem_key_record() cannot be combined with remove_all_dnssec() — "
                "remove everything, or name what to remove, not both"
            )
        spec = sec.get(block) or {}
        spec[kind] = list(spec.get(kind) or []) + [record]
        sec[block] = spec
        self._options["sec_dns"] = sec
        return self


class ContactCreateBuilder(Builder):
    """Creates a contact, one named step at a time.

    The id and the e-mail are constructor arguments because the registry requires both — a builder
    that lets you forget a mandatory field has moved the error from your editor to the wire.
    """

    def __init__(self, handler: Any, contact_id: str, email: str) -> None:
        super().__init__(handler, contact_id)
        self._options["email"] = email

    def international_address(self, name: str, city: str, country_code: str,
                              street: Sequence[str] = (), org: Optional[str] = None,
                              state_province: Optional[str] = None,
                              postal_code: Optional[str] = None) -> "ContactCreateBuilder":
        """The address in ASCII, which every registry accepts.

        At least one form is required. Give this one unless you have a reason not to: it is the
        form that survives being printed, e-mailed and read by a system that knows no Cyrillic.
        """
        return self._address("int", name, city, country_code, street, org, state_province, postal_code)

    def localized_address(self, name: str, city: str, country_code: str,
                          street: Sequence[str] = (), org: Optional[str] = None,
                          state_province: Optional[str] = None,
                          postal_code: Optional[str] = None) -> "ContactCreateBuilder":
        """The address in the local script — Cyrillic for a Ukrainian registrant.

        Optional, and additional: a contact may carry this form as well as the international one.
        """
        return self._address("loc", name, city, country_code, street, org, state_province, postal_code)

    def voice(self, number: str) -> "ContactCreateBuilder":
        """Voice number in the EPP form: ``+CC.NNNNNNNNN``."""
        self._options["voice"] = number
        return self

    def fax(self, number: str) -> "ContactCreateBuilder":
        """Fax number, same form as :meth:`voice`."""
        self._options["fax"] = number
        return self

    def auth_info(self, password: str) -> "ContactCreateBuilder":
        """The transfer secret for this contact."""
        self._options["auth_info"] = password
        return self

    def publish(self, *fields: str) -> "ContactCreateBuilder":
        """Consent to publish these fields: name, org, addr, voice, fax, email.

        Anything not listed takes the opposite treatment, so publish() and withhold() say the same
        thing two ways — pick the one that matches how you think about it, and do not call both.
        """
        self._options["disclose"] = _disclosure(True, fields)
        return self

    def withhold(self, *fields: str) -> "ContactCreateBuilder":
        """Withhold these fields from publication. See :meth:`publish` for the field names."""
        self._options["disclose"] = _disclosure(False, fields)
        return self

    def send(self) -> Response:
        """Send the command and return the registry's answer."""
        self._mark_sent()
        return self._handler.create(self._id, **self._options)

    def _address(self, kind, name, city, country_code, street, org, state_province, postal_code):
        blocks = list(self._options.get("postal_infos") or [])
        blocks.append(_postal_info(kind, name, city, country_code, street, org, state_province, postal_code))
        self._options["postal_infos"] = blocks
        return self


class ContactUpdateBuilder(Builder):
    """Changes a contact, one named step at a time.

    What you do not mention is left alone. That holds inside an address too: a field you leave out
    keeps its value, and a field passed as an empty string is cleared. The one thing to know is
    that the address block is a sequence with a required city and country, so touching any part of
    it sends the whole block — give city and country_code whenever you change street, sp or pc.
    """

    def change_international_address(self, name: Optional[str] = None, city: Optional[str] = None,
                                     country_code: Optional[str] = None,
                                     street: Optional[Sequence[str]] = None,
                                     org: Optional[str] = None,
                                     state_province: Optional[str] = None,
                                     postal_code: Optional[str] = None) -> "ContactUpdateBuilder":
        """Change the ASCII address.

        THE BLOCK YOU PASS REPLACES THE ONE THE REGISTRY HOLDS. It is not merged field by field,
        so anything you leave out is deleted:

        ==================  ===========================================================
        give a value        the field is set to it
        give ``""``         the field is CLEARED — the way to remove org, state province
                            or postal code
        leave it out/None   the field is not sent, and the registry DELETES what it held
        ==================  ===========================================================

        RFC 5733 can be read as "leave it out and the registry keeps its value", since every child
        of chgPostalInfoType is optional, but that reading is not safe: against a registry that
        replaces, a block sent without its org comes back 1000 with the org gone, and a block
        carrying only an org leaves the contact with no postal address at all. ``name``, ``city``
        and ``country_code`` are required here for that reason — but they only keep the frame valid,
        they cannot restore a field you did not send. Read the current block with ``contact.info()``
        and pass it back with your change applied.

        The other form (local or international) IS untouched — the two are addressed separately.
        """
        return self._address("int", name, city, country_code, street, org, state_province, postal_code)

    def change_localized_address(self, name: Optional[str] = None, city: Optional[str] = None,
                                 country_code: Optional[str] = None,
                                 street: Optional[Sequence[str]] = None,
                                 org: Optional[str] = None,
                                 state_province: Optional[str] = None,
                                 postal_code: Optional[str] = None) -> "ContactUpdateBuilder":
        """Change the local-script address. Same rules as :meth:`change_international_address`."""
        return self._address("loc", name, city, country_code, street, org, state_province, postal_code)

    def change_voice(self, number: str) -> "ContactUpdateBuilder":
        return self._chg("voice", number)

    def change_fax(self, number: str) -> "ContactUpdateBuilder":
        return self._chg("fax", number)

    def change_email(self, email: str) -> "ContactUpdateBuilder":
        return self._chg("email", email)

    def change_auth_info(self, password: str) -> "ContactUpdateBuilder":
        """Replace the transfer secret."""
        return self._chg("auth_info", password)

    # There is deliberately no clear_auth_info() here. RFC 5731 gives a domain a nullable form,
    # <domain:authInfo><domain:null/>, and RFC 5733 defines no equivalent for a contact — so a
    # contact's transfer secret can be REPLACED but not removed. Do not reach for an empty password
    # as a substitute: an empty value is still a value the holder can present.
    def publish(self, *fields: str) -> "ContactUpdateBuilder":
        """Consent to publish these fields: name, org, addr, voice, fax, email."""
        return self._chg("disclose", _disclosure(True, fields))

    def withhold(self, *fields: str) -> "ContactUpdateBuilder":
        """Withhold these fields from publication."""
        return self._chg("disclose", _disclosure(False, fields))

    def add_status(self, *statuses: str) -> "ContactUpdateBuilder":
        """Set a client-side status, e.g. ``clientUpdateProhibited``."""
        _append(self._options, "add_statuses", statuses)
        return self

    def rem_status(self, *statuses: str) -> "ContactUpdateBuilder":
        """Clear a client-side status."""
        _append(self._options, "rem_statuses", statuses)
        return self

    def send(self) -> Response:
        """Send the command and return the registry's answer."""
        self._mark_sent()
        return self._handler.update(self._id, **self._options)

    def _chg(self, key: str, value: Any) -> "ContactUpdateBuilder":
        chg = self._options.get("chg") or {}
        chg[key] = value
        self._options["chg"] = chg
        return self

    def _address(self, kind, name, city, country_code, street, org, state_province, postal_code):
        # Only the arguments actually given become keys. The emitter reads presence, so an absent
        # key is not sent and a key holding "" is sent empty, which is what clears a field.
        block: Dict[str, Any] = {"type": kind}
        for key, value in (("name", name), ("org", org), ("city", city),
                           ("sp", state_province), ("pc", postal_code), ("cc", country_code)):
            if value is not None:
                block[key] = value
        if street is not None:
            block["street"] = [str(line) for line in street]

        chg = self._options.get("chg") or {}
        blocks = list(chg.get("postal_infos") or [])
        blocks.append(block)
        chg["postal_infos"] = blocks
        self._options["chg"] = chg
        return self


class HostUpdateBuilder(Builder):
    """Changes a nameserver's glue addresses or statuses.

    There is no rename: this registry reads only the add and remove blocks, so a rename request is
    discarded and the command still answers 1000. Create the new host, repoint the domains that use
    it, then delete the old one.
    """

    def add_address(self, ip: str) -> "HostUpdateBuilder":
        """Add one glue address. Accumulates."""
        return self.add_addresses(ip)

    def add_addresses(self, *ips: str) -> "HostUpdateBuilder":
        """Add glue addresses. IPv4 and IPv6 are told apart automatically. Accumulates."""
        _append(self._options, "add_addresses", ips)
        return self

    def rem_address(self, ip: str) -> "HostUpdateBuilder":
        """Remove one glue address. Accumulates."""
        return self.rem_addresses(ip)

    def rem_addresses(self, *ips: str) -> "HostUpdateBuilder":
        """Remove glue addresses. Accumulates."""
        _append(self._options, "rem_addresses", ips)
        return self

    def add_status(self, *statuses: str) -> "HostUpdateBuilder":
        """Set a client-side status."""
        _append(self._options, "add_statuses", statuses)
        return self

    def rem_status(self, *statuses: str) -> "HostUpdateBuilder":
        """Clear a client-side status."""
        _append(self._options, "rem_statuses", statuses)
        return self

    def send(self) -> Response:
        """Send the command and return the registry's answer."""
        self._mark_sent()
        return self._handler.update(self._id, **self._options)
