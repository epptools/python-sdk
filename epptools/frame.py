"""EPP command frame builder.

Guarantees the RFC 5730 child order (command content, then an optional ``<extension>``,
then ``<clTRID>``) and proper XML escaping — text is set on element nodes, never
concatenated. Public so you can assemble bespoke frames for anything the high-level client
does not cover and send them via ``Client.request()``.

The base ``epp-1.0`` namespace is emitted as the default (unprefixed) namespace; the object
and extension namespaces carry the conventional ``domain:`` / ``contact:`` / ``host:`` /
``secDNS:`` prefixes.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any, Dict, Optional

from . import namespaces as ns

# The conventional prefix for each namespace this library knows by name. Only RFC namespaces are
# here: a registry's own extension URI is not known until the greeting is read, so its prefix is
# bound per frame instead — see Frame.ns().
_PREFIXES = {
    "": ns.EPP,
    "domain": ns.DOMAIN,
    "contact": ns.CONTACT,
    "host": ns.HOST,
    "secDNS": ns.SECDNS,
    "rgp": ns.RGP,
    "fee": ns.FEE,
}
_URI_TO_PREFIX = {uri: prefix for prefix, uri in _PREFIXES.items()}

# ElementTree's prefix table. register_namespace() writes to this INTERPRETER-GLOBAL dict and is
# the only way to choose a prefix — and it *deletes* any other URI already claiming the same one.
# Calling it at import time would claim the DEFAULT (empty) prefix for epp-1.0 process-wide, so a
# host application that has registered its own default namespace could end up serializing two
# xmlns= attributes on one element: malformed XML out of a library it never called. _serialize()
# therefore installs these prefixes for the duration of ONE serialization and puts back exactly
# what was there.
_NS_MAP = getattr(ET, "_namespace_map", None)

_XML_DECL = '<?xml version="1.0" encoding="UTF-8"?>'
_MISSING = object()


def _clark(uri: str, local: str) -> str:
    """ElementTree "Clark notation" tag for a namespaced element."""
    return "{%s}%s" % (uri, local)


def _serialize(root: ET.Element, extra: Optional[Dict[str, str]] = None) -> str:
    """Serialize with the conventional EPP prefixes, leaving no global state behind.

    ``extra`` maps a namespace URI to the prefix this frame asked for, for namespaces that are not
    in ``_PREFIXES`` — a registry's own extension, whose URI is only known at run time. Without it
    ElementTree invents ``ns0``, which is valid XML that nobody can read in a log.
    """
    bindings = dict(_URI_TO_PREFIX)
    if extra:
        taken = set(bindings.values())
        for uri, prefix in extra.items():
            # Never let a run-time prefix displace a conventional one. Two URIs sharing a prefix on
            # one element is malformed output, and the RFC prefixes are the ones a reader expects.
            if uri not in bindings and prefix not in taken:
                bindings[uri] = prefix
                taken.add(prefix)
    if _NS_MAP is None:  # pragma: no cover - an ElementTree without the prefix table
        for uri, prefix in bindings.items():
            ET.register_namespace(prefix, uri)
        return ET.tostring(root, encoding="unicode")
    saved = {uri: _NS_MAP.get(uri, _MISSING) for uri in bindings}
    _NS_MAP.update(bindings)
    try:
        return ET.tostring(root, encoding="unicode")
    finally:
        for uri, prefix in saved.items():
            if prefix is _MISSING:
                _NS_MAP.pop(uri, None)
            else:
                _NS_MAP[uri] = prefix


class Frame:
    def __init__(self) -> None:
        self._epp = ET.Element(_clark(ns.EPP, "epp"))
        self._command = ET.SubElement(self._epp, _clark(ns.EPP, "command"))
        self._extension: Optional[ET.Element] = None
        self._cltrid = ""
        # Namespace URI -> the prefix a caller asked for, for namespaces this library does not know
        # by name. Per frame rather than global: the URI belongs to whichever registry this frame is
        # going to, and a process may well be talking to two.
        self._extra_prefixes: Dict[str, str] = {}

    @classmethod
    def command(cls, cltrid: str) -> "Frame":
        """Start a <command> frame."""
        frame = cls()
        frame._cltrid = cltrid
        return frame

    @property
    def root(self) -> ET.Element:
        return self._epp

    def verb(self, name: str) -> ET.Element:
        """Add the command verb element (<check>, <create>, <login>, <poll>, ...)."""
        return ET.SubElement(self._command, _clark(ns.EPP, name))

    def extension(self) -> ET.Element:
        """Lazily add (once) and return the <extension> element."""
        if self._extension is None:
            self._extension = ET.SubElement(self._command, _clark(ns.EPP, "extension"))
        return self._extension

    def epp(self, parent: ET.Element, name: str, text: Optional[str] = None,
            attrs: Optional[Dict[str, Any]] = None) -> ET.Element:
        """Append an element in the base epp-1.0 namespace (no prefix)."""
        return self._fill(ET.SubElement(parent, _clark(ns.EPP, name)), text, attrs)

    def ns(self, parent: ET.Element, ns_uri: str, qname: str, text: Optional[str] = None,
           attrs: Optional[Dict[str, Any]] = None) -> ET.Element:
        """Append a namespaced element (e.g. ``domain:name``) carrying its xmlns prefix."""
        prefix, _, local = qname.rpartition(":")
        if prefix and ns_uri not in _URI_TO_PREFIX:
            self._extra_prefixes.setdefault(ns_uri, prefix)
        return self._fill(ET.SubElement(parent, _clark(ns_uri, local)), text, attrs)

    def to_xml(self) -> str:
        # clTRID is always the FINAL child of <command> (RFC 5730 ordering) — and there is exactly
        # one. to_xml() is public, so a caller may serialize the same Frame twice (log it, then
        # send it); a second <clTRID> makes the frame schema-invalid and the server answers a
        # bare 2001. Any earlier one is dropped before the current value is appended.
        tag = _clark(ns.EPP, "clTRID")
        for existing in self._command.findall(tag):
            self._command.remove(existing)
        cl = ET.SubElement(self._command, tag)
        cl.text = self._cltrid
        return _XML_DECL + _serialize(self._epp, self._extra_prefixes)

    @staticmethod
    def _fill(el: ET.Element, text: Optional[str], attrs: Optional[Dict[str, Any]]) -> ET.Element:
        if text is not None:
            el.text = text
        if attrs:
            for name, value in attrs.items():
                el.set(name, str(value))
        return el
