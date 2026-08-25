"""A parsed EPP response (or greeting). Wraps the raw XML with convenience accessors: the
result code/message, transaction ids, the availability map for ``*:check``, and generic
value/values getters plus the underlying element tree for anything bespoke.

Element lookups are namespace-agnostic (by local name), so a variation in the response's
namespace prefixes never breaks a getter.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional

from . import namespaces as ns
from .exceptions import ConnectionException

_DOCTYPE_RE = re.compile(r"<!DOCTYPE", re.IGNORECASE)
_FEE_TAG_PREFIX = "{%s}" % ns.FEE


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _text(el: Optional[ET.Element]) -> str:
    return (el.text or "").strip() if el is not None else ""


class Response:
    def __init__(self, raw: str, root: ET.Element) -> None:
        self._raw = raw
        self._root = root

    @classmethod
    def from_xml(cls, xml: str) -> "Response":
        # ElementTree parses a DOCTYPE and expands its internal entities, so a hostile or
        # man-in-the-middle endpoint could hide a self-referencing entity inside the 1 MiB frame
        # budget and blow up the client's memory. An EPP response never carries a DOCTYPE.
        if _DOCTYPE_RE.search(xml) is not None:
            raise ConnectionException("Server returned XML with a DOCTYPE — refused")
        try:
            root = ET.fromstring(xml)
        except ET.ParseError as exc:
            raise ConnectionException("Server returned malformed XML: %s" % exc)
        return cls(xml, root)

    # --- generic element search (namespace-agnostic) ---------------------------

    def _all(self, local_name: str) -> List[ET.Element]:
        return [e for e in self._root.iter() if _local(e.tag) == local_name]

    def _first(self, local_name: str) -> Optional[ET.Element]:
        for e in self._root.iter():
            if _local(e.tag) == local_name:
                return e
        return None

    @staticmethod
    def _direct_child(parent: ET.Element, local_name: str) -> Optional[ET.Element]:
        for e in list(parent):
            if _local(e.tag) == local_name:
                return e
        return None

    # --- result / trID ---------------------------------------------------------

    def code(self) -> int:
        """The EPP result code (e.g. 1000, 1001, 2200), or 0 for a greeting/codeless frame."""
        result = self._first("result")
        if result is None:
            return 0
        raw = result.get("code")
        return int(raw) if raw and raw.isdigit() else 0

    def message(self) -> Optional[str]:
        result = self._first("result")
        if result is None:
            return None
        msg = self._direct_child(result, "msg")
        return _text(msg) if msg is not None else None

    def message_lang(self) -> Optional[str]:
        """The language of the result <msg> ("en", "uk", "ua" or "ru"), or None."""
        result = self._first("result")
        if result is None:
            return None
        msg = self._direct_child(result, "msg")
        return msg.get("lang") if msg is not None else None

    def is_success(self) -> bool:
        """A 1xxx code means success (1000 done, 1001 action pending)."""
        return 1000 <= self.code() < 2000

    def is_pending(self) -> bool:
        return self.code() == 1001

    def is_greeting(self) -> bool:
        return self._first("greeting") is not None

    def cl_trid(self) -> Optional[str]:
        trid = self._first("trID")
        if trid is None:
            return None
        node = self._direct_child(trid, "clTRID")
        return _text(node) if node is not None else None

    def sv_trid(self) -> Optional[str]:
        trid = self._first("trID")
        if trid is None:
            return None
        node = self._direct_child(trid, "svTRID")
        return _text(node) if node is not None else None

    # --- check / poll ----------------------------------------------------------

    def availability(self) -> Dict[str, bool]:
        """Availability map for a ``*:check`` response: name/id -> is-available."""
        # Only the name/id CHILD of a ``*:cd`` block. Matching any element carrying an ``avail``
        # attribute would also catch ``fee:cd``, which sets avail="0" on the block itself (with
        # fee:objID + fee:reason inside) when a zone is not served or the requested currency is
        # not supported — adding a junk entry beside the real one. A check that carries a fee
        # rider gets both kinds of block in one response.
        out: Dict[str, bool] = {}
        for cd in self._root.iter():
            if _local(cd.tag) != "cd":
                continue
            for child in cd:
                if "avail" in child.attrib:
                    out[(child.text or "").strip()] = child.get("avail") in ("1", "true")
        return out

    def message_id(self) -> Optional[str]:
        """Poll only: the queued message id to pass to poll().ack(), or None."""
        msgq = self._first("msgQ")
        return msgq.get("id") if msgq is not None else None

    def message_count(self) -> int:
        """Poll only: how many messages remain in the queue."""
        msgq = self._first("msgQ")
        if msgq is None:
            return 0
        raw = msgq.get("count")
        return int(raw) if raw and raw.isdigit() else 0

    def _queue_child(self, local: str) -> Optional[ET.Element]:
        msgq = self._first("msgQ")
        if msgq is None:
            return None
        for child in msgq:
            if _local(child.tag) == local:
                return child
        return None

    def queue_message(self) -> Optional[str]:
        """Poll only: the QUEUED NOTICE text, from ``<msgQ><msg>``.

        NOT the same as :meth:`message`, which returns ``<result><msg>`` — the command-result
        banner ("Command completed successfully; ack to dequeue"), identical on every poll reply.
        Reading a notice with :meth:`message` hands you that constant string while the real content
        is discarded, and the ack then dequeues it at the registry permanently.
        """
        el = self._queue_child("msg")
        return _text(el) if el is not None else None

    def queue_message_lang(self) -> Optional[str]:
        """Poll only: the language of the queued notice ('uk' | 'ru' | 'en'), or None."""
        el = self._queue_child("msg")
        return el.get("lang") if el is not None else None

    def queue_date(self) -> Optional[str]:
        """Poll only: when the notice was queued (``<msgQ><qDate>``), or None."""
        el = self._queue_child("qDate")
        return _text(el) if el is not None else None

    def pending_action_data(self) -> Optional[Dict[str, object]]:
        """Poll only: the outcome of an operation the registry processed OFFLINE.

        ``<domain:panData>`` / ``<contact:panData>`` (RFC 5731 §3.3, RFC 5733 §3.3). This is how a
        deferred command reports back: you send ``domain:create``, get **1001** ("queued; the result
        will arrive via poll") together with an svTRID, and the answer arrives later as a poll
        message. Returns ``None`` when the message carries no panData.

        The keys, and why each matters:

        ``success``
            The ``paResult`` attribute, and **the only thing that says whether it worked**. The
            surrounding ``<result code="1301">`` means "here is a message", not "your operation
            succeeded" — reading that instead makes every poll answer look like a success.
        ``svTRID`` / ``clTRID``
            From ``<paTRID>``: the transaction ids of the ORIGINAL command. Match the svTRID against
            the one you were given with the 1001 to know WHICH pending operation this answers. Poll
            is a queue; it is not necessarily the most recent one.
        ``date``
            ``<paDate>`` — when the action completed, not when you polled.

        Matched by LOCAL NAME, so it works across every object namespace and dialect.
        """
        pan = self._first("panData")
        if pan is None:
            return None
        name_el = self._first_in(pan, "name")
        if name_el is None:
            name_el = self._first_in(pan, "id")
        # xs:boolean: '1' and 'true' both mean success. Anything else — including absent — is not a
        # yes: a missing verdict is not a verdict.
        flag = (name_el.get("paResult") or "") if name_el is not None else ""
        trid = self._first_in(pan, "paTRID")
        date_el = self._first_in(pan, "paDate")

        def in_trid(local: str) -> Optional[str]:
            if trid is None:
                return None
            el = self._first_in(trid, local)
            text = _text(el) if el is not None else ""
            return text or None

        return {
            "object": _text(name_el) if name_el is not None else "",
            "success": flag == "1" or flag.lower() == "true",
            "clTRID": in_trid("clTRID"),
            "svTRID": in_trid("svTRID"),
            "date": _text(date_el) if date_el is not None else None,
        }

    @staticmethod
    def _first_in(node, local: str):
        """First DESCENDANT with this local name, in any namespace.

        Descendant, not child: paTRID's clTRID/svTRID sit two levels down.
        """
        for el in node.iter():
            if el is not node and _local(el.tag) == local:
                return el
        return None

    def statuses(self) -> List[str]:
        """Object status values from the ``s`` attribute (e.g. ['ok'] or ['clientHold', ...])."""
        return [el.get("s") for el in self._all("status") if el.get("s") is not None]

    # --- balance / prices / licence -------------------------------------------

    def balance(self) -> Optional[Dict[str, str]]:
        """Account figures from a balance:info response (creditLimit / balance /
        availableCredit), or None when this is not a balance response."""
        limit = self.value("creditLimit")
        avail = self.value("availableCredit")
        if limit is None and avail is None:
            return None
        return {
            "creditLimit": limit or "",
            "balance": self.value("balance") or "",
            "availableCredit": avail or "",
        }

    def prices(self) -> Dict[str, Dict[str, str]]:
        """Renewal/restore price hints from a domain:info response (the registry priceData
        extension), keyed by operation."""
        out: Dict[str, Dict[str, str]] = {}
        for node in self._all("price"):
            op = node.get("operation")
            if not op:
                continue
            out[op] = {"value": (node.text or "").strip(), "currency": node.get("currency", "")}
        return out

    def price_channel(self) -> Optional[str]:
        """The price channel this domain is billed on, as an opaque id — the key that matches these
        prices to a row of the registry's published price catalogue.

        None when the response carries no price data. A domain registered long ago may sit on a
        different channel from the one a new registration in the same zone would use, which is why
        this is per-domain rather than per-zone.
        """
        node = self._first("priceData")
        channel = (node.get("channel") or "").strip() if node is not None else ""
        return channel or None

    def registrar_of_record(self) -> Optional[str]:
        """The registrar of record at the registry, when it is not you.

        :meth:`sponsor` names the account this object belongs to — yours, in your own reseller
        hierarchy. This names the handle the registry's own WHOIS and RDAP publish as the
        registrar, which for a reseller is a different party. None when the response does not
        carry one.
        """
        node = self._first("registrar")
        handle = (node.text or "").strip() if node is not None else ""
        return handle or None

    def fees(self) -> Dict[str, object]:
        """Per-name prices from a domain:check + fee dict response (RFC 8748 fee:chkData),
        keyed by domain name::

            {'_currency': 'UAH',
             'example.com.ua': {
                 'avail': True,            # False -> see 'reason'
                 'class': 'premium',       # present only for premium names
                 'reason': None,
                 'commands': {'create': {'years': 1, 'fee': '100.00'},
                              'renew':  {'years': 1, 'fee': '90.00'}}}}

        Empty when the response carries no fee data."""
        chk = None
        for el in self._all("chkData"):
            if el.tag.startswith(_FEE_TAG_PREFIX):
                chk = el
                break
        if chk is None:
            return {}
        out: Dict[str, object] = {"_currency": _text(self._direct_child(chk, "currency"))}
        for cd in list(chk):
            if _local(cd.tag) != "cd":
                continue
            name = _text(self._direct_child(cd, "objID"))
            entry: Dict[str, object] = {
                "avail": cd.get("avail") != "0",
                "reason": _text(self._direct_child(cd, "reason")) or None,
                "commands": {},
                "periods": [],
            }
            klass = _text(self._direct_child(cd, "class"))
            if klass:
                entry["class"] = klass
            for cmd in list(cd):
                if _local(cmd.tag) != "command":
                    continue
                fee_el = self._direct_child(cmd, "fee")
                c: Dict[str, object] = {
                    "years": int(_text(self._direct_child(cmd, "period")) or 1),
                    "fee": _text(fee_el) if fee_el is not None else None,
                }
                cmd_reason = _text(self._direct_child(cmd, "reason"))
                if cmd_reason:
                    c["reason"] = cmd_reason
                op = cmd.get("name", "")
                entry["periods"].append(dict(op=op, **c))  # type: ignore[union-attr]
                # Asking one operation at several periods brings back one <fee:command> per period,
                # all with the same name. The map keeps the FIRST — the period you asked for first
                # — so a caller reading commands["create"] still gets an answer. Read "periods" for
                # the rest.
                if op not in entry["commands"]:  # type: ignore[operator]
                    entry["commands"][op] = c  # type: ignore[index]
            out[name] = entry
        return out

    def charged_fee(self) -> Optional[Dict[str, str]]:
        """The fee actually charged, echoed on a successful transform that carried a fee
        agreement (fee:creData / renData / trnData / updData), e.g.
        {'currency': 'UAH', 'fee': '100.00'} — or None when the response has none."""
        for local in ("creData", "renData", "trnData", "updData", "delData"):
            for el in self._all(local):
                if el.tag.startswith(_FEE_TAG_PREFIX):
                    return {
                        "currency": _text(self._direct_child(el, "currency")),
                        "fee": _text(self._direct_child(el, "fee")),
                    }
        return None

    def license(self) -> Optional[str]:
        """The trademark or licence number from a domain:info response, or None. Carried in the registry's own extension, so it is present only where that registry has one."""
        return self.value("license")

    def rgp_status(self) -> List[str]:
        """RGP status values from a domain:info response (e.g. ['redemptionPeriod'])."""
        return [el.get("s") for el in self._all("rgpStatus") if el.get("s") is not None]

    def transfer_status(self) -> Optional[str]:
        """The transfer status from a transfer response or poll trnData (e.g. "pending")."""
        return self.value("trStatus")

    # --- DNSSEC ----------------------------------------------------------------

    def ds_records(self) -> List[Dict[str, object]]:
        """DNSSEC DS records from a domain:info response (secDNS:dsData)."""
        out = []
        for ds in self._all("dsData"):
            out.append({
                "keyTag": int(_text(self._direct_child(ds, "keyTag")) or 0),
                "alg": int(_text(self._direct_child(ds, "alg")) or 0),
                "digestType": int(_text(self._direct_child(ds, "digestType")) or 0),
                "digest": _text(self._direct_child(ds, "digest")),
            })
        return out

    def key_records(self) -> List[Dict[str, object]]:
        """DNSSEC key records from a domain:info response (top-level secDNS:keyData)."""
        out = []
        for inf in self._all("infData"):
            for kd in list(inf):
                if _local(kd.tag) != "keyData":
                    continue
                out.append({
                    "flags": int(_text(self._direct_child(kd, "flags")) or 0),
                    "protocol": int(_text(self._direct_child(kd, "protocol")) or 0),
                    "alg": int(_text(self._direct_child(kd, "alg")) or 0),
                    "pubKey": _text(self._direct_child(kd, "pubKey")),
                })
        return out

    def is_signed(self) -> bool:
        """True when a domain:info response carries DNSSEC data (any DS or key records)."""
        return bool(self.ds_records() or self.key_records())

    # --- object fields ---------------------------------------------------------

    def object_name(self) -> Optional[str]:
        """The object this response is about: a domain name, a host name or a contact id."""
        # Taken from the DIRECT child of the object block. A document-wide search for <name> finds a
        # contact's postalInfo name first, so contact:info would answer with the person's full name
        # where the caller asked for the handle — and feeding that back as an id draws a 2303.
        data = self.res_data()
        obj = list(data) if data is not None else []
        if obj:
            for child in list(obj[0]):
                if _local(child.tag) in ("id", "name") and _text(child):
                    return _text(child)
        return self.value("name") or self.value("id")

    def expiry_date(self) -> Optional[str]:
        """Expiry, as the registry sent it: ``2027-04-01T09:15:00Z`` or with an offset.

        Kept as the SERVER's string rather than a ``datetime``. The registry decides which calendar
        day a renewal lands on, and re-formatting through a local timezone is how a client ends up
        displaying — and renewing against — the day before."""
        return self.value("exDate")

    def created_date(self) -> Optional[str]:
        """When the object was created, as the registry sent it."""
        return self.value("crDate")

    def updated_date(self) -> Optional[str]:
        """When the object was last changed, as the registry sent it; None if never."""
        return self.value("upDate")

    def roid(self) -> Optional[str]:
        """The registry's own identifier for the object (ROID)."""
        return self.value("roid")

    def registrant(self) -> Optional[str]:
        """The registrant contact handle of a domain."""
        return self.value("registrant")

    def sponsor(self) -> Optional[str]:
        """The registrar currently sponsoring the object."""
        return self.value("clID")

    def created_by(self) -> Optional[str]:
        """The registrar that created the object."""
        return self.value("crID")

    def updated_by(self) -> Optional[str]:
        """The registrar that last changed the object, or None when it has never been changed.

        Sent only to the sponsoring registrar. Pair it with :meth:`updated_date` when reconciling
        your own records: a change you did not make means it came from the registry side or from a
        support action, not from your system."""
        return self.value("upID")

    def transfer_date(self) -> Optional[str]:
        """When the object last changed hands, or None if it never has."""
        return self.value("trDate")

    def auth_info(self) -> Optional[str]:
        """The object's authorisation code (``<authInfo><pw>``), or None when the registry withheld it.

        Present only for the sponsoring registrar, and only on info commands that asked for it. This
        is the secret that lets ANY registrar take the domain away from you: never log it, never put
        it in a support ticket, and roll it after you have passed it to a customer."""
        for el in self._all("authInfo"):
            pw = _text(self._direct_child(el, "pw"))
            if pw:
                return pw
        return None

    def nameservers(self) -> List[str]:
        """A domain's nameservers, however the registry expressed them, lower-cased.

        Both EPP models are covered: ``<domain:hostObj>`` (a reference to a host object) and
        ``<domain:hostAttr>`` (the name inlined with its glue). A client that reads only hostObj
        sees an empty list against a registry using the other model, and concludes the domain has
        no nameservers at all."""
        out: List[str] = []
        for el in self._root.iter():
            if _local(el.tag) in ("hostObj", "hostName"):
                name = _text(el).lower()
                if name and name not in out:
                    out.append(name)
        return out

    def nameserver_addresses(self) -> Dict[str, List[Dict[str, str]]]:
        """A domain's INLINE glue, keyed by nameserver name::

            {'ns1.example.com.ua': [{'ip': '192.0.2.1', 'version': 'v4'}]}

        Only populated for registries that answer with ``<domain:hostAttr>``; one answering with
        ``<domain:hostObj>`` returns the names alone and you fetch the addresses with a host:info
        per name. Either way :meth:`nameservers` gives you the names, so use that for the list and
        this for the glue — an empty result here does NOT mean the domain is undelegated."""
        out: Dict[str, List[Dict[str, str]]] = {}
        for attr in self._all("hostAttr"):
            name = _text(self._direct_child(attr, "hostName")).lower()
            if not name:
                continue
            out[name] = self._addresses([e for e in list(attr) if _local(e.tag) == "hostAddr"])
        return out

    def host_addresses(self) -> List[Dict[str, str]]:
        """A host object's glue addresses: ``[{'ip': '192.0.2.1', 'version': 'v4'}, ...]``.

        Only a host INSIDE the zone it serves carries glue; for an external nameserver the registry
        returns none, and that is normal rather than a missing answer."""
        # Scoped to the host object itself. A document-wide search would also match the glue inside
        # a domain's hostAttr blocks — flattening the addresses of DIFFERENT nameservers into one
        # list, which reads as a single well-addressed host and loses which IP belongs to which
        # name. Per-name glue is nameserver_addresses(). The contact <addr> is a container, hence
        # the leaf test.
        data = self.res_data()
        obj = list(data) if data is not None else []
        if not obj:
            return []
        return self._addresses(
            [e for e in list(obj[0]) if _local(e.tag) == "addr" and len(list(e)) == 0]
        )

    @staticmethod
    def _addresses(nodes: List[ET.Element]) -> List[Dict[str, str]]:
        out: List[Dict[str, str]] = []
        for el in nodes:
            ip = _text(el)
            if not ip:
                continue
            # Absent @ip means v4 per the host schema's default, so an IPv4-only registry that
            # omits the attribute must not come back labelled as something else.
            out.append({"ip": ip, "version": el.get("ip") or "v4"})
        return out

    def subordinate_hosts(self) -> List[str]:
        """Nameserver objects that live UNDER this domain, listed as ``<domain:host>`` in a
        domain:info response, lower-cased.

        The registry refuses to delete a domain while these exist, so check the list before a
        delete and remove or rename them first."""
        out: List[str] = []
        for el in self._all("host"):
            if len(list(el)):
                continue
            name = _text(el).lower()
            if name and name not in out:
                out.append(name)
        return out

    def contacts(self) -> Dict[str, List[str]]:
        """A domain's role contacts, keyed by role::

            {'admin': ['c-1'], 'tech': ['c-1', 'c-2']}

        The registrant is NOT included — it is a separate element with its own meaning; see
        :meth:`registrant`."""
        out: Dict[str, List[str]] = {}
        for el in self._all("contact"):
            role = el.get("type")
            handle = _text(el)
            if not role or not handle:
                continue
            out.setdefault(role, []).append(handle)
        return out

    def contacts_for(self, role: str) -> List[str]:
        """The handles in ONE role: ``contacts_for('tech')`` -> ``['c-tech1', 'c-tech2']``.

        Empty when the domain carries nobody in that role — a legitimate answer, not an error,
        since only the registrant is mandatory everywhere. The role is matched case-insensitively:
        registries are inconsistent about ``tech`` vs ``Tech``, and an exact lookup silently
        reports "no technical contact" for a domain that has one."""
        for key, handles in self.contacts().items():
            if key.lower() == role.lower():
                return handles
        return []

    def admin_contacts(self) -> List[str]:
        """The administrative contacts — the people authorised to make decisions about the domain."""
        return self.contacts_for("admin")

    def tech_contacts(self) -> List[str]:
        """The technical contacts — the people to reach about DNS and delegation."""
        return self.contacts_for("tech")

    def billing_contacts(self) -> List[str]:
        """The billing contacts — the people to reach about invoices for this domain."""
        return self.contacts_for("billing")

    def all_contacts(self) -> List[str]:
        """Every handle attached to the domain in any capacity, registrant included, de-duplicated.

        Use this when you care THAT a contact is referenced rather than in which role — deleting a
        contact, or working out which of your contact objects are still in use."""
        out: List[str] = []
        registrant = self.registrant()
        if registrant:
            out.append(registrant)
        for handles in self.contacts().values():
            for handle in handles:
                if handle not in out:
                    out.append(handle)
        return out

    def email(self) -> Optional[str]:
        """A contact's e-mail address."""
        return self.value("email")

    def voice(self) -> Optional[str]:
        """A contact's voice number, in the EPP ``+CC.NNNN`` form."""
        return self.value("voice")

    def fax(self) -> Optional[str]:
        """A contact's fax number, in the EPP ``+CC.NNNN`` form."""
        return self.value("fax")

    def postal_info(self) -> Dict[str, Dict[str, object]]:
        """A contact's postal addresses, keyed by form: ``'int'`` (ASCII, always accepted by every
        registry) and ``'loc'`` (the local script, e.g. Cyrillic). A contact may carry either or
        both::

            {'int': {'name': ..., 'org': ..., 'street': [...],
                     'city': ..., 'sp': ..., 'pc': ..., 'cc': ...}}

        Read ``'int'`` when you need something you can safely print anywhere; read ``'loc'`` when
        you want the address as the registrant actually wrote it."""
        out: Dict[str, Dict[str, object]] = {}
        for el in self._all("postalInfo"):
            addr = self._direct_child(el, "addr")
            out[el.get("type") or "int"] = {
                "name": _text(self._direct_child(el, "name")),
                "org": _text(self._direct_child(el, "org")),
                "street": [
                    _text(s) for s in (list(addr) if addr is not None else [])
                    if _local(s.tag) == "street"
                ],
                "city": _text(self._direct_child(addr, "city")) if addr is not None else "",
                "sp": _text(self._direct_child(addr, "sp")) if addr is not None else "",
                "pc": _text(self._direct_child(addr, "pc")) if addr is not None else "",
                "cc": _text(self._direct_child(addr, "cc")) if addr is not None else "",
            }
        return out

    def disclose(self) -> Optional[Dict[str, object]]:
        """A contact's disclosure preference::

            {'flag': True, 'elements': ['email', 'voice']}

        None when the contact carries no preference and registry policy alone applies.

        ``flag`` True means the listed elements MAY be published; False means they must be
        withheld. The elements NOT listed take the opposite of the flag, so the list is meaningless
        without it."""
        el = self._first("disclose")
        if el is None:
            return None
        elements: List[str] = []
        for child in el.iter():
            if child is el:
                continue
            # postalInfo name/org/addr are distinguished by @type ("int" or "loc").
            kind = child.get("type")
            elements.append("%s:%s" % (_local(child.tag), kind) if kind else _local(child.tag))
        return {"flag": el.get("flag") in ("1", "true"), "elements": elements}

    def transfer(self) -> Optional[Dict[str, str]]:
        """A transfer notice in full — who asked, when, who must answer, and by when::

            {'status': 'pending', 'requested_by': 'gaining-clid', 'requested_at': ...,
             'acting_client': 'losing-clid', 'act_by': ..., 'expiry_date': ...}

        :meth:`transfer_status` alone says a transfer is pending without saying whose or how long
        you have to act, and ``act_by`` is the deadline after which the registry decides for you."""
        el = self._first("trnData")
        if el is None:
            return None
        return {
            "status": _text(self._direct_child(el, "trStatus")),
            "requested_by": _text(self._direct_child(el, "reID")),
            "requested_at": _text(self._direct_child(el, "reDate")),
            "acting_client": _text(self._direct_child(el, "acID")),
            "act_by": _text(self._direct_child(el, "acDate")),
            "expiry_date": _text(self._direct_child(el, "exDate")),
        }

    # --- availability / money shortcuts ----------------------------------------

    def is_available(self, name: str) -> Optional[bool]:
        """Is this one name available? None when the response says nothing about it — which is NOT
        the same as "taken", and must not look the same when the next line registers the name."""
        for candidate, free in self.availability().items():
            if candidate.lower() == name.lower():
                return free
        return None

    def unavailable_reason(self, name: str) -> Optional[str]:
        """Why a name in a check response is unavailable, e.g. "In use" or "Reserved"; None when it
        is available or the registry gave no reason."""
        for cd in self._all("cd"):
            # `a or b` is wrong on ElementTree: an element with no children is falsy, so a leaf
            # <name> would be discarded in favour of a missing <id> and every name read as
            # "no reason given".
            label = self._direct_child(cd, "name")
            if label is None:
                label = self._direct_child(cd, "id")
            if label is None or _text(label).lower() != name.lower():
                continue
            return _text(self._direct_child(cd, "reason")) or None
        return None

    def fee_for(self, name: str, operation: str, years: int = 1) -> Optional[str]:
        """The quoted price for ONE operation at ONE period, or None when the answer carried no
        such quote::

            r = client.domain.check(["example1.com.ua"], fee={"create": [1, 2, 5]})
            r.fee_for("example1.com.ua", "create", 5)   # the five-year price

        Use this rather than indexing :meth:`fees` whenever you asked one operation at several
        periods: the map there holds one entry per operation. ``transfer`` and ``restore`` are
        one-year operations however many years you ask for, so read those back at 1.
        """
        for key, entry in self.fees().items():
            if key == "_currency" or not isinstance(entry, dict) or key.lower() != name.lower():
                continue
            for quote in entry.get("periods") or []:
                if quote.get("op") == operation and quote.get("years") == years:
                    return quote.get("fee")
        return None

    def fee_class(self, name: Optional[str] = None) -> Optional[str]:
        """The registry's fee class for a name, e.g. ``'premium'`` or ``'standard'``; None when the
        answer carried no class.

        Take the price from :meth:`fees` rather than inferring it from the class — the class says
        which price list applies, not what it costs."""
        for key, entry in self.fees().items():
            if key == "_currency" or not isinstance(entry, dict):
                continue
            if name is not None and key.lower() != name.lower():
                continue
            klass = entry.get("class")
            if klass:
                return str(klass)
        return None

    def is_premium(self, name: Optional[str] = None) -> bool:
        """Whether the registry priced the name outside the standard list.

        A False here is not a promise of the standard price — it means the answer declared no
        special class. Always charge from :meth:`fees`, and re-check the fee on the create itself."""
        klass = self.fee_class(name)
        return klass is not None and klass.lower() != "standard"

    def credit_limit(self) -> Optional[str]:
        """The credit the registry extends beyond a zero balance, as an exact decimal string."""
        bal = self.balance()
        return bal.get("creditLimit") if bal else None

    def current_balance(self) -> Optional[str]:
        """Funds on the account right now, as an exact decimal string.

        Kept as a string, never a float: 0.1 + 0.2 is not 0.3 in binary floating point, and money
        compared or summed that way drifts. Use ``decimal.Decimal`` for arithmetic."""
        bal = self.balance()
        return bal.get("balance") if bal else None

    def available_credit(self) -> Optional[str]:
        """What you can actually spend — balance plus remaining credit — as an exact decimal string."""
        bal = self.balance()
        return bal.get("availableCredit") if bal else None

    def fee_amount(self) -> Optional[str]:
        """The amount actually charged by the transform that produced this response, or None."""
        fee = self.charged_fee()
        return fee.get("fee") if fee else None

    def fee_currency(self) -> Optional[str]:
        """The currency of :meth:`fee_amount`, or None when the response carried no fee."""
        fee = self.charged_fee()
        return fee.get("currency") if fee else None

    # --- diagnostics / greeting -----------------------------------------------

    def ext_values(self) -> List[Dict[str, object]]:
        """Every ``<extValue>`` on a failed command, unpacked::

            [{'element': 'name', 'namespace': 'urn:ietf:params:xml:ns:domain-1.0',
              'text': 'bad..name', 'values': {}, 'xml': '<domain:name>bad..name</domain:name>',
              'reason': 'Invalid label', 'lang': 'en'}]

        ``<extValue><value>`` echoes the offending element back, so this tells you WHICH of the
        names in a batch the registry rejected — :meth:`error_reasons` gives you the wording but
        not the subject, and on a multi-name command the wording alone is not actionable.

        The offending element is usually a leaf, and then ``text`` is the answer. When it is a
        CONTAINER — an RFC 9038 payload the server relocated here because the client did not
        announce its namespace — ``text`` is empty, because a container has no character data of its
        own. ``values`` carries the children by name, so the relocated figures are still readable,
        and ``xml`` is the element as it arrived if you would rather re-parse it."""
        out: List[Dict[str, object]] = []
        for ext in self._all("extValue"):
            value = self._direct_child(ext, "value")
            offender = list(value)[0] if value is not None and len(list(value)) else None
            reason = self._direct_child(ext, "reason")
            values: Dict[str, str] = {}
            xml = ""
            if offender is not None:
                for child in list(offender):
                    values[_local(child.tag)] = _text(child)
                xml = ET.tostring(offender, encoding="unicode")
            out.append(
                {
                    "element": _local(offender.tag) if offender is not None else "",
                    "namespace": (
                        offender.tag.split("}", 1)[0][1:]
                        if offender is not None and "}" in offender.tag
                        else ""
                    ),
                    "text": _text(offender) if offender is not None else _text(value),
                    "values": values,
                    "xml": xml,
                    "reason": _text(reason),
                    "lang": (reason.get("lang") or "") if reason is not None else "",
                }
            )
        return out

    def error_reasons(self) -> List[str]:
        """Extra diagnostic text from a failed command's <extValue><reason> elements."""
        out: List[str] = []
        for ext in self._all("extValue"):
            for reason in ext.iter():
                if _local(reason.tag) == "reason":
                    out.append((reason.text or "").strip())
        return out

    def security_events(self) -> List[Dict[str, str]]:
        """Login only: the server's security warnings about THIS session (RFC 8807 loginSec:event).

        Each entry has ``type`` (password|certificate|cipher|tlsProtocol|newPW|stat|custom),
        ``level`` ('warning' or 'error') and a human ``text``, plus whichever of ``name``,
        ``exDate``, ``value``, ``duration`` and ``lang`` the event carries. A certificate about to
        expire arrives here as type=certificate with the date in ``exDate`` — weeks before the day
        it would otherwise be discovered, which is the day logins stop.

        Empty when the session is healthy, so treat any entry as something to act on. The server
        sends these only to a client that took part in the extension; keep
        :attr:`Config.login_security` on.
        """
        out: List[Dict[str, str]] = []
        for data in self._all("loginSecData"):
            for event in data:
                if _local(event.tag) != "event":
                    continue
                entry = {"text": (event.text or "").strip()}
                for attr in ("type", "name", "level", "exDate", "value", "duration", "lang"):
                    if attr in event.attrib:
                        entry[attr] = event.attrib[attr]
                out.append(entry)
        return out

    def service_obj_uris(self) -> List[str]:
        """Greeting only: the object services the server advertises."""
        return [(e.text or "").strip() for e in self._all("objURI")]

    def service_ext_uris(self) -> List[str]:
        """Greeting only: the extension services the server advertises."""
        return [(e.text or "").strip() for e in self._all("extURI")]

    # --- generic getters -------------------------------------------------------

    def value(self, local_name: str) -> Optional[str]:
        """First element anywhere with this local name (namespace-agnostic), trimmed."""
        el = self._first(local_name)
        return _text(el) if el is not None else None

    def values(self, local_name: str) -> List[str]:
        """Every element with this local name, trimmed."""
        return [(e.text or "").strip() for e in self._all(local_name)]

    def res_data(self) -> Optional[ET.Element]:
        """The <resData> element of the response, if present (for custom parsing)."""
        return self._first("resData")

    @property
    def raw(self) -> str:
        return self._raw

    @property
    def root(self) -> ET.Element:
        return self._root
