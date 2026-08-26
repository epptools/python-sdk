"""Offline self-test: exercises frame building and response parsing with a fake in-memory
transport — no server, no network.

    python tests/offline_test.py
"""

import os
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from epptools import Client, Config, Contact, Namespaces
from epptools.exceptions import (
    AuthenticationException,
    EppException,
    AuthorizationError,
    CommandException,
    ConfigException,
    InsufficientFundsError,
    ObjectDoesNotExistError,
    ObjectExistsError,
    ObjectStatusError,
    PolicyError,
    SessionError,
    ValidationException,
)
from epptools.transport import Transport

_passed = 0
_failed = 0


def check(label, ok):
    global _passed, _failed
    print(("  ok  " if ok else " FAIL ") + label)
    if ok:
        _passed += 1
    else:
        _failed += 1


_CLTRID = __import__("re").compile(r"<clTRID>([^<]*)</clTRID>")


class FakeTransport(Transport):
    """Records what was written and replays queued responses."""

    def __init__(self):
        self.written = []
        self.queue = []
        self._open = False

    def open(self):
        self._open = True

    def is_open(self):
        return self._open

    def write_frame(self, xml):
        self.written.append(xml)

    def read_frame(self):
        if not self.queue:
            raise RuntimeError("FakeTransport: no queued response")
        frame = self.queue.pop(0)
        # A real server echoes back the clTRID it was sent, and the client refuses a reply that
        # does not. A fixture with a fixed clTRID would make every test fail that check for the
        # wrong reason — or, if the check were relaxed to suit the fixture, would stop testing it
        # at all.
        if not self.written:
            return frame
        sent = _CLTRID.search(self.written[-1])
        if sent is None:
            return frame
        return _CLTRID.sub("<clTRID>%s</clTRID>" % sent.group(1), frame, count=1)

    def close(self):
        self._open = False


# The extension namespaces of the fictional registry these fixtures simulate.
#
# They are NOT constants of the library, and there is no equivalent there to compare them against:
# the library knows the RFC namespaces and discovers a registry's own from its <greeting>. So these
# belong to the fixture, the way a hostname or a password in a fixture does.
#
# Deliberately a registry no version of this code has ever named. A fixture written with the URIs the
# library used to hard-code would keep passing if discovery quietly regressed to a constant — the
# strings would still line up — and would prove only that the code agrees with itself. Under a URI
# that appears nowhere in the package, these tests can pass only by actually reading the greeting.
EXT_REGISTRY = "http://registry.example/epp/registry-1.0"
EXT_BALANCE = "http://registry.example/epp/balance-1.0"

GREETING = (
    '<?xml version="1.0" encoding="UTF-8"?><epp xmlns="urn:ietf:params:xml:ns:epp-1.0"><greeting>'
    "<svID>Registry EPP</svID><svDate>2026-07-04T00:00:00Z</svDate><svcMenu><version>1.0</version>"
    "<lang>en</lang><lang>uk</lang>"
    "<objURI>urn:ietf:params:xml:ns:contact-1.0</objURI><objURI>urn:ietf:params:xml:ns:domain-1.0</objURI>"
    "<objURI>urn:ietf:params:xml:ns:host-1.0</objURI>"
    "<svcExtension><extURI>urn:ietf:params:xml:ns:secDNS-1.1</extURI><extURI>urn:ietf:params:xml:ns:rgp-1.0</extURI>"
    '<extURI>http://registry.example/epp/registry-1.0</extURI><extURI>http://registry.example/epp/balance-1.0</extURI>'
    "</svcExtension></svcMenu></greeting></epp>"
)


def OK(code=1000, msg="ok", lang="en"):
    return (
        '<?xml version="1.0"?><epp xmlns="urn:ietf:params:xml:ns:epp-1.0"><response>'
        '<result code="%d"><msg lang="%s">%s</msg></result>'
        "<trID><clTRID>C1</clTRID><svTRID>SRV-1</svTRID></trID></response></epp>" % (code, lang, msg)
    )


def make_client(responses, password="secret", **opts):
    fake = FakeTransport()
    fake.queue = list(responses)
    client = Client(Config(host="epp.example", clid="EXAMPLE", password=password, **opts), fake)
    return client, fake


def local(tag):
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def parse(xml):
    return ET.fromstring(xml)


def all_local(root, name):
    return [e for e in root.iter() if local(e.tag) == name]


def first_local(root, name):
    for e in root.iter():
        if local(e.tag) == name:
            return e
    return None


def text_of(root, name):
    e = first_local(root, name)
    return e.text if e is not None else None


# --------------------------------------------------------------------------
# Session / login
# --------------------------------------------------------------------------
print("session: connect + login (services from greeting)")
client, fake = make_client([GREETING, OK()])
greeting = client.connect()
check("greeting parsed", greeting.is_greeting())
check("greeting objURIs", "urn:ietf:params:xml:ns:domain-1.0" in greeting.service_obj_uris())
client.login()
login_frame = parse(fake.written[0])
check("login clID", text_of(login_frame, "clID") == "EXAMPLE")
check("login pw", text_of(login_frame, "pw") == "secret")
check("login version 1.0", text_of(login_frame, "version") == "1.0")
check("login advertises domain objURI", any(
    e.text == Namespaces.DOMAIN for e in all_local(login_frame, "objURI")))
check("login advertises balance extURI", any(
    e.text == EXT_BALANCE for e in all_local(login_frame, "extURI")))
check("login does not advertise the epp base URI", all(
    e.text != Namespaces.EPP for e in all_local(login_frame, "objURI")))

print("session: namespace discovery from the greeting")
client, _ = make_client([GREETING])
client.connect()
check("registry extension discovered", client.registry_ext_uri() == EXT_REGISTRY)
check("balance extension discovered", client.registry_balance_uri() == EXT_BALANCE)

# Discovery must key on the last segment and nothing else: a registry's URI can be any string, and
# the only part of it this library is entitled to assume is the extension's name.
_odd = GREETING.replace(EXT_REGISTRY, "https://epp.other.example/xml/schemas/registry-1.2").replace(
    EXT_BALANCE, "urn:example:other:balance")
client, _ = make_client([_odd])
client.connect()
check("a differently-shaped registry URI is found",
      client.registry_ext_uri() == "https://epp.other.example/xml/schemas/registry-1.2")
check("a non-http registry URI is found too", client.registry_balance_uri() == "urn:example:other:balance")

# RFC extensions are skipped by prefix, and this is the case that makes it necessary: fee-1.0 is an
# IETF extension whose last segment would match a search for an extension named "fee".
_fee_only = GREETING.replace(
    "<extURI>%s</extURI><extURI>%s</extURI>" % (EXT_REGISTRY, EXT_BALANCE),
    "<extURI>urn:ietf:params:xml:ns:epp:fee-1.0</extURI>")
client, _ = make_client([_fee_only])
client.connect()
check("a registry advertising no extension of its own reports none", client.registry_ext_uri() is None)
check("and no balance extension either", client.registry_balance_uri() is None)

# Absence must be REPORTED, not guessed around. Sending an invented URI would not be rejected — an
# extension the server does not recognise is ignored — so the licence would silently not be set.
try:
    client.require_registry_ext_uri("domain:create with a licence")
    _msg = None
except ConfigException as exc:
    _msg = str(exc)
check("asking for a missing extension raises ConfigException", _msg is not None)
check("and the message says what was wanted", _msg is not None and "domain:create with a licence" in _msg)
check("and lists what the server did advertise",
      _msg is not None and "urn:ietf:params:xml:ns:epp:fee-1.0" in _msg)

try:
    client.balance()
    _bal_msg = None
except ConfigException as exc:
    _bal_msg = str(exc)
check("balance() refuses when the server offers no balance extension", _bal_msg is not None)

# The config override exists for a registry that names its extension something discovery cannot
# guess. It must win outright — including over a greeting that advertises a different URI.
client, _ = make_client([GREETING], registry_ext_uri="urn:example:custom:registry",
                        registry_balance_uri="urn:example:custom:balance")
client.connect()
check("a configured registry URI overrides the greeting", client.registry_ext_uri() == "urn:example:custom:registry")
check("a configured balance URI overrides the greeting",
      client.registry_balance_uri() == "urn:example:custom:balance")

# Before connect() there is no greeting. Discovery must return None rather than fail, so that a
# caller who set the URIs in config can work without ever reading one.
client, _ = make_client([])
check("no greeting read yet discovers nothing", client.registry_ext_uri() is None)

# The prefix a call site asks for must survive serialization. ElementTree names an unknown namespace
# `ns0` unless told otherwise, and a frame full of ns0/ns1 is legal XML that nobody can read in a log
# — which is where these frames are looked at when something has gone wrong.
client, fake = make_client([GREETING, OK(1000)])
client.connect()
client.balance()
check("a discovered namespace keeps the prefix the caller asked for",
      'xmlns:balance="%s"' % EXT_BALANCE in fake.written[0] and "<balance:info" in fake.written[0])

print("session: password rotation via newPW")
client, fake = make_client([GREETING, OK()])
client.connect()
client.login("new-secret-1")
check("login carries newPW", text_of(parse(fake.written[0]), "newPW") == "new-secret-1")

print("clTRID format: prefix-timestamp-pid-counter")
client, fake = make_client([GREETING, OK(), OK()])
client.connect()
client.domain.check(["example1.com.ua"])
client.domain.check(["example2.com.ua"])
t1 = parse(fake.written[0]).find(".//{urn:ietf:params:xml:ns:epp-1.0}clTRID").text
t2 = parse(fake.written[1]).find(".//{urn:ietf:params:xml:ns:epp-1.0}clTRID").text
import re as _re
check("clTRID shape PYTHON-SDK-<ts>-<pid>-0001", bool(_re.match(r"^PYTHON-SDK-\d{14}-\d+-0001$", t1)))
check("clTRID counter increments", t2.endswith("-0002"))
check("clTRID pid segment stable across a session", t1.split("-")[-2] == t2.split("-")[-2])

# --------------------------------------------------------------------------
# Domain
# --------------------------------------------------------------------------
print("domain: check / info / create")
client, fake = make_client([GREETING, OK(), OK(), OK()])
client.connect()
client.domain.check(["example3.com.ua", "y.com.ua"])
dc = parse(fake.written[0])
check("domain:check has 2 names", len(all_local(dc, "name")) == 2)
check("domain:check element is in domain-1.0 ns",
      any(e.tag == "{%s}check" % Namespaces.DOMAIN for e in dc.iter()))

client.domain.info("example3.com.ua", "authpw", hosts="all")
di = parse(fake.written[1])
check("domain:info hosts attr", first_local(di, "name").get("hosts") == "all")
check("domain:info authInfo pw", text_of(di, "pw") == "authpw")

client.domain.create("example3.com.ua", years=1, registrant="REG1",
                     # "tech" as a LIST: RFC 5731 allows repeated <domain:contact type=...> and the registry
                       # parses a list per role. A plain .items() loop stringified it into ONE element.
                       contacts={"admin": "ADM1", "tech": ["TEC1", "TEC2"]},
                     nameservers=["ns1.example.net", "ns2.example.net"], auth_info="secret1",
                     license="TM-1", sec_dns={"ds_data": [
                         {"key_tag": 12345, "alg": 8, "digest_type": 2, "digest": "AB" * 32}]})
cr = parse(fake.written[2])
check("create period unit=y", first_local(cr, "period").get("unit") == "y")
check("create 2 hostObj", len(all_local(cr, "hostObj")) == 2)
# admin + BOTH tech handles: a list per role becomes one element each, never a stringified list.
check("create 3 contacts (admin + both tech handles)", len(all_local(cr, "contact")) == 3)
check("second tech handle is a real element", any(e.text == "TEC2" for e in all_local(cr, "contact"))
      and not any("[" in (e.text or "") for e in all_local(cr, "contact")))
check("create authInfo pw", text_of(cr, "pw") == "secret1")
check("create secDNS keyTag", text_of(cr, "keyTag") == "12345")
check("create licence in the registry extension", text_of(cr, "license") == "TM-1")

print("domain: create/update with inline glue (hostAttr)")
client, fake = make_client([GREETING, OK(), OK()])
client.connect()
client.domain.create("glue.com.ua", years=1, registrant="REG1", nameservers=[
    {"name": "ns1.glue.com.ua", "addresses": ["192.0.2.1", "2001:db8::1"]},
    {"name": "ns2.glue.com.ua", "addresses": ["192.0.2.2"]},
])
g = parse(fake.written[0])
check("glue hostAttr x2", len(all_local(g, "hostAttr")) == 2)
check("glue hostName", all_local(g, "hostName")[0].text == "ns1.glue.com.ua")
addrs = all_local(g, "hostAddr")
check("glue v4 addr tagged ip=v4", addrs[0].text == "192.0.2.1" and addrs[0].get("ip") == "v4")
check("glue v6 addr tagged ip=v6", addrs[1].text == "2001:db8::1" and addrs[1].get("ip") == "v6")
check("glue emits no hostObj", len(all_local(g, "hostObj")) == 0)

# A nameserver may be added to an existing domain with its glue, too.
client.domain.update("glue.com.ua", add={"ns": [{"name": "ns3.glue.com.ua", "addresses": ["192.0.2.3"]}]})
check("glue on update add", text_of(parse(fake.written[1]), "hostName") == "ns3.glue.com.ua")

# RFC 5731 makes <domain:ns> a choice, so a mixture is refused here rather than at the registry.
mixed = None
try:
    client.domain.create("mix.com.ua", nameservers=[
        "ns1.mix.com.ua", {"name": "ns2.mix.com.ua", "addresses": ["192.0.2.9"]}])
except ValidationException as exc:
    mixed = str(exc)
check("mixed hostObj + hostAttr refused",
      mixed is not None and "all names or all name-with-glue" in mixed)

print("domain: create without authInfo still emits an empty <pw/>")
client, fake = make_client([GREETING, OK()])
client.connect()
client.domain.create("noauth.com.ua", years=1, registrant="REG1",
                     contacts={"admin": "A1", "tech": "T1"}, nameservers=["ns1.example.net"])
na = parse(fake.written[0])
pw = first_local(na, "pw")
check("authInfo-less create has a <pw> element", pw is not None)
check("authInfo-less create <pw> is empty", (pw.text or "") == "")

print("domain: create with empty secDNS emits no childless secDNS:create")
client, fake = make_client([GREETING, OK()])
client.connect()
client.domain.create("nosec.com.ua", years=1, registrant="REG1",
                     contacts={"admin": "A1", "tech": "T1"}, nameservers=["ns1.example.net"], sec_dns={})
check("empty secDNS -> no secDNS:create", first_local(parse(fake.written[0]), "create") is not None
      and len([e for e in parse(fake.written[0]).iter() if e.tag == "{%s}create" % Namespaces.SECDNS]) == 0)

print("domain: update deltas + secDNS + restore")
client, fake = make_client([GREETING, OK(), OK()])
client.connect()
client.domain.update("example3.com.ua",
                     add={"ns": ["ns3.example.net"], "statuses": ["clientHold"]},
                     rem={"statuses": ["clientHold"]},
                     chg={"registrant": "REG9", "auth_info": "newpw12345"},
                     sec_dns={"add": {"ds_data": [{"key_tag": 22, "alg": 8, "digest_type": 2, "digest": "bb" * 32}]},
                              "rem_all": True, "max_sig_life": 1209600})
up = parse(fake.written[0])
check("update add block present", first_local(up, "add") is not None)
check("update chg registrant", text_of(up, "registrant") == "REG9")
check("update secDNS rem all=true", any(local(e.tag) == "all" and e.text == "true" for e in up.iter()))
check("update secDNS add keyTag=22", text_of(up, "keyTag") == "22")
check("update secDNS maxSigLife", text_of(up, "maxSigLife") == "1209600")

client.domain.restore("example3.com.ua")
rs = parse(fake.written[1])
check("restore rgp op=request", first_local(rs, "restore").get("op") == "request")

print("domain: renew / delete / transfer")
client, fake = make_client([GREETING, OK(), OK(), OK()])
client.connect()
client.domain.renew("example3.com.ua", "2027-01-15", 2)
rn = parse(fake.written[0])
check("renew curExpDate", text_of(rn, "curExpDate") == "2027-01-15")
check("renew period 2", text_of(rn, "period") == "2")

# The value that reaches a caller's hands is <exDate>, an xs:dateTime; the value the wire wants is
# <curExpDate>, an xs:date. Passing the first straight to renew() is the obvious thing to write, and
# before this it produced a 2105 whose message mentions neither element.
_c, _f = make_client([GREETING, OK(), OK(), OK()])
_c.connect()
_c.domain.renew("example3.com.ua", "2027-01-15T09:15:00.0Z", 1)
check("renew accepts the exDate timestamp and sends the date",
      text_of(parse(_f.written[0]), "curExpDate") == "2027-01-15")
_c.domain.renew("example3.com.ua", "2027-01-15T23:30:00.0Z", 1)
check("and takes the date the server wrote, never a local-timezone shift of it",
      text_of(parse(_f.written[1]), "curExpDate") == "2027-01-15")
_c.domain.renew("example3.com.ua", "not-a-date", 1)
check("an unrecognised value goes to the server unchanged",
      text_of(parse(_f.written[2]), "curExpDate") == "not-a-date")

client.domain.delete("example3.com.ua")
check("delete has name", text_of(parse(fake.written[1]), "name") == "example3.com.ua")
client.domain.transfer("request", "example3.com.ua", "pw", 1)
tr = parse(fake.written[2])
check("transfer op=request", first_local(tr, "transfer").get("op") == "request")
check("transfer authInfo pw", text_of(tr, "pw") == "pw")

# --------------------------------------------------------------------------
# Contact
# --------------------------------------------------------------------------
print("contact: create (int+loc postalInfo + disclose)")
client, fake = make_client([GREETING, OK()])
client.connect()
client.contact.create("CID1", postal_infos=[
    {"type": "int", "name": "Test Person", "street": ["1 A St"], "city": "Kyiv", "cc": "UA"},
    {"type": "loc", "name": "Тест Особа", "city": "Київ", "cc": "UA"}],
    email="contact@example.com", auth_info="pw",
    disclose={"flag": False, "addr": ["int"], "voice": True, "email": True})
cc = parse(fake.written[0])
check("contact 2 postalInfo blocks", len(all_local(cc, "postalInfo")) == 2)
check("contact int name", any(local(e.tag) == "name" and e.text == "Test Person" for e in cc.iter()))
check("contact loc Cyrillic name preserved", any(
    local(e.tag) == "name" and e.text == "Тест Особа" for e in cc.iter()))
check("contact disclose flag=0", first_local(cc, "disclose").get("flag") == "0")

print("contact: the reserved id asks the registry to mint the handle")
CRE_DATA = ('<?xml version="1.0"?><epp xmlns="urn:ietf:params:xml:ns:epp-1.0"><response>'
            '<result code="1000"><msg>Command completed successfully</msg></result>'
            '<resData><contact:creData xmlns:contact="urn:ietf:params:xml:ns:contact-1.0">'
            '<contact:id>C0000042-EXAMPLE</contact:id><contact:crDate>2026-08-16T10:00:00.0Z</contact:crDate>'
            '</contact:creData></resData><trID><svTRID>SRV-1</svTRID></trID></response></epp>')
client, fake = make_client([GREETING, CRE_DATA])
client.connect()
minted = client.contact.create_auto(name="ACME", city="Kyiv", cc="UA", email="contact@example.com")
check("reserved id sent verbatim", text_of(parse(fake.written[0]), "id") == "autonic")
check("reserved id constant", Contact.AUTO_ID == "autonic")
# The minted handle arrives in creData and nowhere else, so object_name() must read the id — not
# the person's postal name, which also sits under a <name> element in a contact response.
check("minted handle read back from creData", minted.object_name() == "C0000042-EXAMPLE")

print("contact: create without email raises ValueError")
client, fake = make_client([GREETING])
client.connect()
try:
    client.contact.create("CID2", name="X", city="Kyiv", cc="UA")
    check("empty email raises", False)
except ValueError:
    check("empty email raises ValueError", True)

print("contact: which postal fields can be CLEARED is the schema's decision, not ours")
# contact-1.0.xsd: optPostalLineType (org, street, sp) and pcType have no minLength, so those clear
# by being sent empty. postalLineType (name, city) has minLength 1 and ccType is exactly two
# characters, so an empty one of those is schema-invalid — and an invalid frame comes back as a bare
# 2001 that names no element, the least useful error in EPP.
client, fake = make_client([GREETING, OK(), OK()])
client.connect()


def _refuses(fn):
    try:
        fn()
        return None
    except ValidationException as exc:
        return exc


_no_addr = _refuses(lambda: client.contact.update(
    "C-1", chg={"postal_info": {"type": "loc", "name": "Ivan", "sp": ""}}))
check("clearing sp WITHOUT the required parts of <addr> is refused here, not by the server", _no_addr is not None)
check("and the message names the part that is missing", _no_addr is not None and "city" in str(_no_addr))

_empty_name = _refuses(lambda: client.contact.update(
    "C-1", chg={"postal_info": {"type": "loc", "name": "", "city": "Lviv", "cc": "UA"}}))
check("a name cannot be cleared at all — there is no empty postalLineType", _empty_name is not None)

# The whole point of the guard is that the CORRECT call still works and still clears.
client.contact.update(
    "C-1", chg={"postal_info": {"type": "loc", "name": "Ivan", "sp": "", "city": "Lviv", "cc": "UA"}})
_sent = parse(fake.written[0])
check("sp goes out as an empty element, which is what clears it",
      [e for e in _sent.iter() if local(e.tag) == "sp"][0].text in (None, ""))
check("and the required parts travel with it",
      text_of(_sent, "city") == "Lviv" and text_of(_sent, "cc") == "UA")

# THIS USED TO ASSERT THE OPPOSITE — "clearing org alone sends no <addr> and needs no city" — and it
# was a documented way to destroy an address. Against a registry that REPLACES the block rather than
# merging it, a chg carrying only <contact:org/> answers 1000 and leaves the contact with NO
# postalInfo at all.
_org_alone = _refuses(lambda: client.contact.update("C-1", chg={"postal_info": {"type": "loc", "org": ""}}))
check("clearing org WITHOUT the rest of the block is refused", _org_alone is not None)

# The BUILDER reaches the same code, and nothing checked that it did. A guard that only covers the
# raw call leaves the more convenient path — the one the manual leads with — able to do the damage.
_via_builder = _refuses(lambda: client.contact.update_builder("C-1")
                        .change_international_address(city="Lviv", country_code="UA", org="")
                        .send())
check("and the builder is held to the same rule, not just the raw call", _via_builder is not None)

client.contact.update(
    "C-1", chg={"postal_info": {"type": "loc", "name": "Ivan", "org": "", "city": "Lviv", "cc": "UA"}})
_org_only = parse(fake.written[1])
check("the complete form clears org AND carries the address",
      len([e for e in _org_only.iter() if local(e.tag) == "org"]) == 1
      and text_of(_org_only, "city") == "Lviv"
      and text_of(_org_only, "name") == "Ivan")
# Present-and-EMPTY is the removal; the element existing is only half of it. An <org> carrying a
# value would set an organisation rather than take one away.
check("and that element is empty, which is what removes the organisation",
      [e for e in _org_only.iter() if local(e.tag) == "org"][0].text in (None, ""))

# The other half of the mechanism: absent means "leave it alone". A phantom clear would wipe an
# organisation the caller never mentioned.
client, fake = make_client([GREETING, OK()])
client.connect()
client.contact.update("C-1", chg={"postal_info": {"type": "loc", "name": "Ivan", "city": "Lviv", "cc": "UA"}})
check("no org element when the caller never mentioned it",
      not [e for e in parse(fake.written[0]).iter() if local(e.tag) == "org"])

# On a create there is nothing to remove, so an empty org is simply not an element.
client, fake = make_client([GREETING, OK()])
client.connect()
client.contact.create("C-1", postal_infos=[
    {"type": "int", "name": "Test Person", "org": "", "city": "Kyiv", "cc": "UA"}],
    email="contact@example.com", auth_info="pw")
check("create never emits an empty org",
      not [e for e in parse(fake.written[0]).iter() if local(e.tag) == "org"])

print("contact: update collapses multiple statuses into one add/rem block")
client, fake = make_client([GREETING, OK()])
client.connect()
client.contact.update("CID1",
                      add_statuses=["clientUpdateProhibited", "clientDeleteProhibited"],
                      rem_statuses=["clientTransferProhibited"],
                      chg={"email": "new-contact@example.com"})
cu = parse(fake.written[0])
check("contact update single add block", len(all_local(cu, "add")) == 1)
check("contact update 2 statuses in add", len([e for e in all_local(cu, "status")
      if e.get("s") in ("clientUpdateProhibited", "clientDeleteProhibited")]) == 2)
check("contact update chg email", any(local(e.tag) == "email" and e.text == "new-contact@example.com" for e in cu.iter()))

print("contact: check / info / delete / transfer")
client, fake = make_client([GREETING, OK(), OK(), OK(), OK()])
client.connect()
client.contact.check(["C1", "C2"])
check("contact:check 2 ids", len(all_local(parse(fake.written[0]), "id")) == 2)
client.contact.info("C1", "pw")
check("contact:info authInfo", text_of(parse(fake.written[1]), "pw") == "pw")
client.contact.delete("C1")
check("contact:delete id", text_of(parse(fake.written[2]), "id") == "C1")
client.contact.transfer("request", "C1", "pw")
check("contact:transfer op", first_local(parse(fake.written[3]), "transfer").get("op") == "request")

# --------------------------------------------------------------------------
# Host
# --------------------------------------------------------------------------
print("host: create v4+v6 auto-detect / update / delete-force")
client, fake = make_client([GREETING, OK(), OK(), OK()])
client.connect()
client.host.create("ns1.example.net", ["192.0.2.1", "2001:db8::1"])
hc = parse(fake.written[0])
addrs = all_local(hc, "addr")
check("host v4 detected", any(a.text == "192.0.2.1" and a.get("ip") == "v4" for a in addrs))
check("host v6 detected", any(a.text == "2001:db8::1" and a.get("ip") == "v6" for a in addrs))
client.host.update("ns1.example.net", add_addresses=["192.0.2.9"], rem_statuses=["clientUpdateProhibited"])
hu = parse(fake.written[1])
check("host update add block", first_local(hu, "add") is not None)
# RENAME IS REFUSED, not emitted. The server has no chg field for hosts and reads only add/rem, so
# a <host:chg> is discarded without comment: an address change in the same frame would succeed, the
# rename would not, and the caller would be told 1000.
rename_refused = False
try:
    client.host.update("ns1.example.net", new_name="ns2.example.net")
except Exception as exc:  # noqa: BLE001 - the SDK's own ConfigException
    rename_refused = "rename is not supported" in str(exc)
check("host rename is refused up front", rename_refused)
client.host.delete("ns1.example.net", force=True)
check("host delete force registry:deleteNS", first_local(parse(fake.written[2]), "deleteNS") is not None)

# --------------------------------------------------------------------------
# Poll + balance
# --------------------------------------------------------------------------
print("poll: request / ack")
client, fake = make_client([GREETING, OK(), OK()])
client.connect()
client.poll.request()
check("poll op=req", first_local(parse(fake.written[0]), "poll").get("op") == "req")
client.poll.ack("42")
pa = parse(fake.written[1])
check("poll op=ack", first_local(pa, "poll").get("op") == "ack")
check("poll msgID", first_local(pa, "poll").get("msgID") == "42")

print("balance: info")
client, fake = make_client([GREETING, OK()])
client.connect()
client.balance()
check("balance:info element in balance-1.0 ns",
      any(e.tag == "{%s}info" % EXT_BALANCE for e in parse(fake.written[0]).iter()))

# --------------------------------------------------------------------------
# XML escaping
# --------------------------------------------------------------------------
print("frame: XML escaping (special chars + Cyrillic, single-escaped)")
client, fake = make_client([GREETING, OK()])
client.connect()
client.contact.create("C&<1", name="A & B <Ltd>", city="Львів", cc="UA", email='a"b@example.com')
raw = fake.written[0]
check("ampersand escaped once", "&amp;" in raw and "&amp;amp;" not in raw)
check("angle brackets escaped", "&lt;Ltd&gt;" in raw)
check("Cyrillic preserved", "Львів" in raw)
# The escaped frame must still parse back cleanly.
esc = parse(raw)
check("escaped id round-trips", text_of(esc, "id") == "C&<1")

# --------------------------------------------------------------------------
# Response parsing
# --------------------------------------------------------------------------
print("response: result code / message / lang / trIDs")
from epptools import Response
r = Response.from_xml(OK(1000, "Команду виконано успішно", "uk"))
check("code 1000", r.code() == 1000)
check("isSuccess", r.is_success())
check("message text", r.message() == "Команду виконано успішно")
check("messageLang uk", r.message_lang() == "uk")
check("svTRID", r.sv_trid() == "SRV-1")
check("clTRID", r.cl_trid() == "C1")

print("response: availability (domain:check)")
avail_xml = (
    '<?xml version="1.0"?><epp xmlns="urn:ietf:params:xml:ns:epp-1.0"><response>'
    '<result code="1000"><msg>ok</msg></result><resData>'
    '<domain:chkData xmlns:domain="urn:ietf:params:xml:ns:domain-1.0">'
    '<domain:cd><domain:name avail="1">free.com.ua</domain:name></domain:cd>'
    '<domain:cd><domain:name avail="0">taken.com.ua</domain:name></domain:cd>'
    "</domain:chkData></resData><trID><svTRID>SRV-2</svTRID></trID></response></epp>"
)
av = Response.from_xml(avail_xml).availability()
check("avail free=True", av.get("free.com.ua") is True)
check("avail taken=False", av.get("taken.com.ua") is False)

print("response: balance / prices / licence / statuses")
info_xml = (
    '<?xml version="1.0"?><epp xmlns="urn:ietf:params:xml:ns:epp-1.0"><response>'
    '<result code="1000"><msg>ok</msg></result><resData>'
    '<domain:infData xmlns:domain="urn:ietf:params:xml:ns:domain-1.0">'
    "<domain:name>example3.com.ua</domain:name><domain:status s=\"ok\"/>"
    "<domain:exDate>2027-01-01T00:00:00Z</domain:exDate></domain:infData></resData>"
    '<extension><registry:infData xmlns:registry="http://registry.example/epp/registry-1.0">'
    "<registry:license>TM-777</registry:license>"
    '<registry:priceData channel="7">'
    '<registry:price operation="renewal" currency="UAH">180.00</registry:price></registry:priceData>'
    "<registry:registrar>EXAMPLE</registry:registrar>"
    "</registry:infData></extension><trID><svTRID>SRV-3</svTRID></trID></response></epp>"
)
ri = Response.from_xml(info_xml)
check("value exDate", ri.value("exDate") == "2027-01-01T00:00:00Z")
check("statuses ok", ri.statuses() == ["ok"])
check("license", ri.license() == "TM-777")
check("prices renewal value", ri.prices().get("renewal", {}).get("value") == "180.00")
check("prices renewal currency", ri.prices().get("renewal", {}).get("currency") == "UAH")
# The prices belong to a channel; without its id they cannot be matched to a catalogue row, and a
# domain kept on an older channel prices differently from a new registration in the same zone.
check("price_channel reads the channel the prices belong to", ri.price_channel() == "7")
# sponsor() is the account; this is the handle the registry itself publishes as the registrar.
check("registrar_of_record reads the registry-side handle", ri.registrar_of_record() == "EXAMPLE")
plain_info = Response.from_xml(
    '<?xml version="1.0"?><epp xmlns="urn:ietf:params:xml:ns:epp-1.0"><response>'
    '<result code="1000"><msg>ok</msg></result><resData>'
    '<domain:infData xmlns:domain="urn:ietf:params:xml:ns:domain-1.0">'
    "<domain:name>plain.com.ua</domain:name></domain:infData></resData>"
    "<trID><svTRID>SRV-4</svTRID></trID></response></epp>"
)
check("price_channel is None when no price data came back", plain_info.price_channel() is None)
check("registrar_of_record is None when the registry sent none",
      plain_info.registrar_of_record() is None)

bal_xml = (
    '<?xml version="1.0"?><epp xmlns="urn:ietf:params:xml:ns:epp-1.0"><response>'
    '<result code="1000"><msg>ok</msg></result><resData>'
    '<balance:infData xmlns:balance="http://registry.example/epp/balance-1.0">'
    "<balance:creditLimit>1000.00</balance:creditLimit><balance:balance>250.50</balance:balance>"
    "<balance:availableCredit>1250.50</balance:availableCredit></balance:infData></resData>"
    "<trID><svTRID>SRV-4</svTRID></trID></response></epp>"
)
b = Response.from_xml(bal_xml).balance()
check("balance creditLimit", b["creditLimit"] == "1000.00")
check("balance availableCredit", b["availableCredit"] == "1250.50")
check("non-balance response -> balance None", Response.from_xml(OK()).balance() is None)

print("response: secDNS read-back (nested keyData not leaked into keyRecords)")
sec_xml = (
    '<?xml version="1.0"?><epp xmlns="urn:ietf:params:xml:ns:epp-1.0"><response>'
    '<result code="1000"><msg>ok</msg></result>'
    '<extension><secDNS:infData xmlns:secDNS="urn:ietf:params:xml:ns:secDNS-1.1">'
    "<secDNS:dsData><secDNS:keyTag>12345</secDNS:keyTag><secDNS:alg>13</secDNS:alg>"
    "<secDNS:digestType>2</secDNS:digestType><secDNS:digest>ABCDEF0123</secDNS:digest>"
    "<secDNS:keyData><secDNS:flags>256</secDNS:flags><secDNS:protocol>3</secDNS:protocol>"
    "<secDNS:alg>13</secDNS:alg><secDNS:pubKey>nested</secDNS:pubKey></secDNS:keyData></secDNS:dsData>"
    "<secDNS:keyData><secDNS:flags>257</secDNS:flags><secDNS:protocol>3</secDNS:protocol>"
    "<secDNS:alg>13</secDNS:alg><secDNS:pubKey>toplevel</secDNS:pubKey></secDNS:keyData>"
    "</secDNS:infData></extension><trID><svTRID>SRV-5</svTRID></trID></response></epp>"
)
rs = Response.from_xml(sec_xml)
check("dsRecords count 1", len(rs.ds_records()) == 1)
check("dsRecords keyTag", rs.ds_records()[0]["keyTag"] == 12345)
check("keyRecords only top-level", len(rs.key_records()) == 1 and rs.key_records()[0]["pubKey"] == "toplevel")
check("isSigned", rs.is_signed() is True)

print("response: poll message id/count/text + trStatus")
poll_xml = (
    '<?xml version="1.0"?><epp xmlns="urn:ietf:params:xml:ns:epp-1.0"><response>'
    '<result code="1301"><msg>ack to dequeue</msg></result>'
    '<msgQ count="3" id="42"><qDate>2026-07-04T00:00:00Z</qDate><msg lang="uk">Домен example3.com.ua продовжено</msg></msgQ>'
    '<resData><domain:trnData xmlns:domain="urn:ietf:params:xml:ns:domain-1.0">'
    "<domain:name>example3.com.ua</domain:name><domain:trStatus>pending</domain:trStatus></domain:trnData></resData>"
    "<trID><svTRID>SRV-6</svTRID></trID></response></epp>"
)
rp = Response.from_xml(poll_xml)
check("poll messageId", rp.message_id() == "42")
check("poll messageCount", rp.message_count() == 3)
check("poll result message is the result msg, not the queue msg", rp.message() == "ack to dequeue")
check("transferStatus pending", rp.transfer_status() == "pending")

print("response: panData — the outcome of an offline operation")
# How a deferred command reports back: you send domain:create, get 1001 + an svTRID, and the answer
# arrives later as a poll message. The <result code="1301"> means "here is a message", NOT "it
# worked" — paResult is the only thing that says that, and reading the code instead makes every
# poll answer look like a success.
check("no panData on a trnData notice", rp.pending_action_data() is None)

pan_xml = (
    '<?xml version="1.0"?><epp xmlns="urn:ietf:params:xml:ns:epp-1.0"><response>'
    '<result code="1301"><msg>ack to dequeue</msg></result>'
    '<msgQ count="1" id="11"><qDate>1970-01-01T00:00:12Z</qDate><msg>Domain registered</msg></msgQ>'
    '<resData><domain:panData xmlns:domain="urn:ietf:params:xml:ns:domain-1.0">'
    '<domain:name paResult="1">example.com.ua</domain:name>'
    "<domain:paTRID><clTRID>my-create-1</clTRID>"
    "<svTRID>SRV-19700101000000-1-00042</svTRID></domain:paTRID>"
    "<domain:paDate>1970-01-01T00:00:12Z</domain:paDate>"
    "</domain:panData></resData>"
    "<trID><svTRID>SRV-9</svTRID></trID></response></epp>"
)
pan = Response.from_xml(pan_xml).pending_action_data()
check("panData object", pan["object"] == "example.com.ua")
check("panData success", pan["success"] is True)
# The id of the ORIGINAL command: how a client knows WHICH pending operation this answers. Poll is
# a queue — it is not necessarily the most recent one.
check("panData original svTRID", pan["svTRID"] == "SRV-19700101000000-1-00042")
check("panData original clTRID", pan["clTRID"] == "my-create-1")
check("panData paDate", pan["date"] == "1970-01-01T00:00:12Z")
check(
    "panData failure",
    Response.from_xml(pan_xml.replace('paResult="1"', 'paResult="0"')).pending_action_data()["success"] is False,
)

# contact:panData too — matched by local name, so binding to domain-1.0 would return None on a
# contact transfer.
contact_pan = (
    '<?xml version="1.0"?><epp xmlns="urn:ietf:params:xml:ns:epp-1.0"><response>'
    '<result code="1301"><msg>ack to dequeue</msg></result>'
    '<msgQ count="1" id="12"><qDate>1970-01-01T00:00:12Z</qDate><msg>Contact transferred</msg></msgQ>'
    '<resData><contact:panData xmlns:contact="urn:ietf:params:xml:ns:contact-1.0">'
    '<contact:id paResult="true">CH-151</contact:id>'
    "<contact:paTRID><clTRID>my-xfer-1</clTRID><svTRID>SRV-19700101000000-1-00043</svTRID></contact:paTRID>"
    "</contact:panData></resData>"
    "<trID><svTRID>SRV-9</svTRID></trID></response></epp>"
)
cpan = Response.from_xml(contact_pan).pending_action_data()
check("contact panData id", cpan["object"] == "CH-151")
check('paResult="true" is success too', cpan["success"] is True)
check("panData without paDate is None, not empty", cpan["date"] is None)

print("response: errorReasons + code getters")
err_xml = (
    '<?xml version="1.0"?><epp xmlns="urn:ietf:params:xml:ns:epp-1.0"><response>'
    '<result code="2306"><msg>policy</msg><extValue><value/><reason>bad NS count</reason></extValue></result>'
    "<trID><svTRID>SRV-7</svTRID></trID></response></epp>"
)
re7 = Response.from_xml(err_xml)
check("code 2306", re7.code() == 2306)
check("not success", not re7.is_success())
check("errorReasons", re7.error_reasons() == ["bad NS count"])

# --------------------------------------------------------------------------
# Error handling + config guards
# --------------------------------------------------------------------------
print("errors: CommandException raised on >=2000, silenced by throw_on_failure(False)")
client, fake = make_client([GREETING, OK(2302, "exists")])
client.connect()
try:
    client.domain.create("dup.com.ua", years=1, registrant="R", contacts={"admin": "A", "tech": "T"},
                         nameservers=["ns1.example.net"])
    check("2302 raises", False)
except CommandException as exc:
    check("2302 raises CommandException", exc.epp_code == 2302)

client, fake = make_client([GREETING, OK(2303, "nope")])
client.connect()
client.throw_on_failure(False)
resp = client.domain.info("missing.com.ua")
check("throw_on_failure(False) returns response", resp.code() == 2303)

print("errors: login failure raises AuthenticationException")
client, fake = make_client([GREETING, OK(2200, "bad login")])
client.connect()
try:
    client.login()
    check("login 2200 raises", False)
except AuthenticationException as exc:
    check("login 2200 raises AuthenticationException", exc.epp_code == 2200)

print("config guards: empty host / clID / password fail fast")
try:
    Client(Config(host="", clid="x", password="y")).connect()
    check("empty host raises", False)
except ConfigException:
    check("empty host -> ConfigException", True)

client, fake = make_client([GREETING])
client.connect()
client._config.password = ""
try:
    client.login()
    check("empty password raises", False)
except ConfigException:
    check("empty password -> ConfigException", True)
check("no login frame sent on config failure", fake.written == [])

# --------------------------------------------------------------------------
# RFC 8748 fee: request building + response parsing (mirrors the PHP SDK offline suite)
# --------------------------------------------------------------------------
from epptools.response import Response

print("fee: check request + create agreement (frame building)")
client, fake = make_client([GREETING, OK()])
client.connect()
client.domain.check(["prem.com.ua"], fee={"create": 1, "renew": 2})
fc = parse(fake.written[0])
check("fee:check present", first_local(fc, "check") is not None
      and any(local(e.tag) == "check" and e.tag.startswith("{urn:ietf:params:xml:ns:epp:fee-1.0}") for e in fc.iter()))
create_cmds = [e for e in all_local(fc, "command") if e.get("name") == "create"]
check("fee:command create", len(create_cmds) == 1)
renew_cmds = [e for e in all_local(fc, "command") if e.get("name") == "renew"]
check("fee:period years for renew", renew_cmds and first_local(renew_cmds[0], "period").text == "2")

client, fake = make_client([GREETING, OK()])
client.connect()
client.domain.create("prem.com.ua", years=1, registrant="C1",
                     contacts={"admin": "C1", "tech": "C2"}, nameservers=["ns1.example.net"],
                     fee={"amount": "500.00", "currency": "UAH"})
fcr = parse(fake.written[0])
fee_create = [e for e in fcr.iter() if e.tag == "{urn:ietf:params:xml:ns:epp:fee-1.0}create"]
check("fee:create agreement present", len(fee_create) == 1)
check("fee:create fee amount", fee_create and text_of(fee_create[0], "fee") == "500.00")
check("fee:create currency", fee_create and text_of(fee_create[0], "currency") == "UAH")

print("fee: Response.fees() + charged_fee() (response parsing)")
fee_chk_xml = (
    '<?xml version="1.0"?><epp xmlns="urn:ietf:params:xml:ns:epp-1.0"><response>'
    '<result code="1000"><msg>ok</msg></result>'
    '<resData><domain:chkData xmlns:domain="urn:ietf:params:xml:ns:domain-1.0">'
    '<domain:cd><domain:name avail="1">prem.com.ua</domain:name></domain:cd></domain:chkData></resData>'
    '<extension><fee:chkData xmlns:fee="urn:ietf:params:xml:ns:epp:fee-1.0">'
    '<fee:cd><fee:objID>prem.com.ua</fee:objID>'
    '<fee:command name="create"><fee:period unit="y">1</fee:period><fee:fee>500.00</fee:fee></fee:command>'
    '<fee:command name="renew"><fee:period unit="y">1</fee:period><fee:fee>450.00</fee:fee></fee:command>'
    '</fee:cd></fee:chkData></extension><trID><svTRID>SRV-F1</svTRID></trID></response></epp>'
)
fees = Response.from_xml(fee_chk_xml).fees()
check("fees() has the checked name", "prem.com.ua" in fees)
check("fees() create price", fees.get("prem.com.ua", {}).get("commands", {}).get("create", {}).get("fee") == "500.00")
check("fees() renew price", fees.get("prem.com.ua", {}).get("commands", {}).get("renew", {}).get("fee") == "450.00")

fee_cre_xml = (
    '<?xml version="1.0"?><epp xmlns="urn:ietf:params:xml:ns:epp-1.0"><response>'
    '<result code="1000"><msg>ok</msg></result>'
    '<resData><domain:creData xmlns:domain="urn:ietf:params:xml:ns:domain-1.0"><domain:name>prem.com.ua</domain:name>'
    '<domain:crDate>2026-06-15T00:00:00Z</domain:crDate><domain:exDate>2027-06-15T00:00:00Z</domain:exDate></domain:creData></resData>'
    '<extension><fee:creData xmlns:fee="urn:ietf:params:xml:ns:epp:fee-1.0">'
    '<fee:currency>UAH</fee:currency><fee:fee>500.00</fee:fee></fee:creData></extension>'
    '<trID><svTRID>SRV-F2</svTRID></trID></response></epp>'
)
charged = Response.from_xml(fee_cre_xml).charged_fee()
check("charged_fee() currency", charged is not None and charged["currency"] == "UAH")
check("charged_fee() amount", charged is not None and charged["fee"] == "500.00")

# --------------------------------------------------------------------------
# DNSSEC key spellings, empty blocks, privacy flags, frames, transport, config repr
# --------------------------------------------------------------------------
print("secDNS: the RFC camelCase spelling is accepted, a misspelling is refused")
client, fake = make_client([GREETING, OK(), OK()])
client.connect()
# 'dsData' is the RFC 5910 spelling (and the one the PHP/Node SDKs take). Reading only snake_case
# dropped the whole <secDNS:create> block and registered the domain UNSIGNED behind a 1000.
client.domain.create("camel.com.ua", years=1, registrant="C1", nameservers=["ns1.example.net"],
                     sec_dns={"maxSigLife": 604800,
                              "dsData": [{"keyTag": 999, "alg": 8, "digestType": 2, "digest": "AA"}]})
cam = parse(fake.written[0])
sec_create = [e for e in cam.iter() if e.tag == "{%s}create" % Namespaces.SECDNS]
check("camelCase sec_dns emits secDNS:create", len(sec_create) == 1)
check("camelCase keyTag carried", text_of(cam, "keyTag") == "999")
check("camelCase maxSigLife carried", text_of(cam, "maxSigLife") == "604800")

try:
    client.domain.create("typo.com.ua", years=1, registrant="C1", sec_dns={"ds_dat": []})
    check("misspelt sec_dns key raises", False)
except ValueError:
    check("misspelt sec_dns key raises ValueError", True)

print("secDNS: an empty sec_dns mapping emits no childless secDNS:update")
client, fake = make_client([GREETING, OK()])
client.connect()
client.domain.update("nosec.com.ua", sec_dns={}, chg={"registrant": "C9"})
esx = parse(fake.written[0])
check("empty sec_dns -> no secDNS:update",
      len([e for e in esx.iter() if e.tag == "{%s}update" % Namespaces.SECDNS]) == 0)
check("the rest of the update still went out", text_of(esx, "registrant") == "C9")

print("contact: disclose flag '0' means HIDE (a non-empty string is truthy in Python)")
client, fake = make_client([GREETING, OK()])
client.connect()
client.contact.create("CID9", name="X", city="Kyiv", cc="UA", email="contact@example.com",
                      disclose={"flag": "0", "voice": "0", "email": True})
disc = first_local(parse(fake.written[0]), "disclose")
check("disclose flag='0' emits flag=\"0\"", disc.get("flag") == "0")
check("disclose voice='0' discloses nothing", all(local(e.tag) != "voice" for e in disc))
check("disclose email True still emitted", any(local(e.tag) == "email" for e in disc))

print("frame: to_xml() is idempotent (exactly one clTRID, always last)")
from epptools import Frame

idem = Frame.command("T-1")
idem.ns(idem.verb("check"), Namespaces.DOMAIN, "domain:check")
first_xml = idem.to_xml()
second_xml = idem.to_xml()
check("a second to_xml() returns the same frame", first_xml == second_xml)
cmd = first_local(parse(second_xml), "command")
check("exactly one clTRID", len([e for e in cmd if local(e.tag) == "clTRID"]) == 1)
check("clTRID is the last child of <command>", local(list(cmd)[-1].tag) == "clTRID")
check("prefixes still the conventional ones", "<domain:check" in second_xml and "xmlns=" in second_xml)
# Serializing must not leave OUR prefixes in ElementTree's interpreter-global table, where they
# would change (or break) how the host application serializes its own documents.
_ns_map = getattr(ET, "_namespace_map", {})
check("no global prefix registration leaks out", _ns_map.get(Namespaces.DOMAIN) != "domain")

print("response: a DOCTYPE is refused before parsing (entity expansion)")
from epptools.exceptions import ConnectionException

try:
    Response.from_xml('<?xml version="1.0"?><!DOCTYPE epp [<!ENTITY a "b">]><epp/>')
    check("DOCTYPE refused", False)
except ConnectionException:
    check("DOCTYPE refused before ET.fromstring()", True)

print("config: repr() never leaks the password or the key passphrase")
cfg_repr = repr(Config(host="h", clid="c", password="s3cret!", client_key_passphrase="k3y!"))
check("password absent from repr()", "s3cret!" not in cfg_repr)
check("client_key_passphrase absent from repr()", "k3y!" not in cfg_repr)
check("repr() still shows the host", "'h'" in cfg_repr)

print("logging: authInfo masked even when the element carries attributes")
client, _ = make_client([])
masked = client._redact('<pw>topsecret</pw><domain:pw roid="D1-EXAMPLE">auth123</domain:pw><domain:name>keep.ua</domain:name>')
check("bare <pw> masked", "topsecret" not in masked)
check("<domain:pw> with attributes masked", "auth123" not in masked)
check("non-secret kept", "keep.ua" in masked)

print("transport: a failed read/write is terminal (no off-by-one over the next command)")
from epptools.transport import Connection


class _BrokenSocket:
    """Fails every transfer the way a half-closed TLS socket does."""

    def sendall(self, payload):
        raise OSError("broken pipe")

    def recv(self, n):
        return b""

    def close(self):
        pass


conn = Connection(Config(host="h", clid="c", password="secret"))
conn._sock = _BrokenSocket()
try:
    conn.read_frame()
    check("a closed read raises", False)
except ConnectionException:
    check("a closed read raises ConnectionException", True)
check("the connection is no longer open", conn.is_open() is False)
try:
    # Before the terminal flag this simply raised "Not connected"; on a socket that had NOT been
    # dropped it would have returned the PREVIOUS command's response.
    conn.read_frame()
    check("the next read raises", False)
except ConnectionException as exc:
    check("the next read reports the original failure", "no longer usable" in str(exc))

conn2 = Connection(Config(host="h", clid="c", password="secret"))
conn2._sock = _BrokenSocket()
try:
    conn2.write_frame("<epp/>")
    check("a failed write raises", False)
except ConnectionException:
    check("a failed write raises ConnectionException", True)
check("a failed write is terminal too", conn2.is_open() is False)

# --------------------------------------------------------------------------
print("fee: one operation can be priced at several periods in a single command")
# A price table is one round trip, not five. The registry prices every <fee:command> separately.
_fc, _ff = make_client([GREETING, OK(), OK()])
_fc.connect()
_fc.domain.check(["example1.com.ua"], fee={"create": [1, 2, 5], "renew": 1}, currency="UAH")
_fx = _ff.written[0]
check("every period becomes its own fee:command", _fx.count("<fee:command") == 4)
check("three of them are the same operation", _fx.count('name="create"') == 3)
check("and the periods keep the order asked",
      _re.findall(r'<fee:period unit="y">(\d+)<', _fx) == ["1", "2", "5", "1"])
check("a named currency is carried", "<fee:currency>UAH</fee:currency>" in _fx)
_cap_threw = False
try:
    _fc.domain.check(["example1.com.ua"], fee={"create": [1] * 21})
except ValidationException:
    _cap_threw = True
# The registry refuses a 21st entry; refusing locally names it instead of spending a call.
check("a query past the registry cap is refused before it is sent", _cap_threw)

_FEE_REPLY = (
    '<?xml version="1.0"?><epp xmlns="urn:ietf:params:xml:ns:epp-1.0"><response>'
    '<result code="1000"><msg>ok</msg></result><resData>'
    '<domain:chkData xmlns:domain="urn:ietf:params:xml:ns:domain-1.0">'
    '<domain:cd><domain:name avail="1">example1.com.ua</domain:name></domain:cd></domain:chkData></resData>'
    '<extension><fee:chkData xmlns:fee="urn:ietf:params:xml:ns:epp:fee-1.0">'
    "<fee:currency>UAH</fee:currency>"
    '<fee:cd avail="1"><fee:objID>example1.com.ua</fee:objID>'
    '<fee:command name="create"><fee:period unit="y">1</fee:period><fee:fee>100.00</fee:fee></fee:command>'
    '<fee:command name="create"><fee:period unit="y">2</fee:period><fee:fee>190.00</fee:fee></fee:command>'
    '<fee:command name="create"><fee:period unit="y">5</fee:period><fee:fee>450.00</fee:fee></fee:command>'
    '<fee:command name="renew"><fee:period unit="y">1</fee:period><fee:fee>90.00</fee:fee></fee:command>'
    "</fee:cd></fee:chkData></extension><trID><svTRID>X</svTRID></trID></response></epp>"
)
_fr = Response.from_xml(_FEE_REPLY)
# Keyed by operation alone, three create quotes would collapse to one.
check("every quote survives the parse", len(_fr.fees()["example1.com.ua"]["periods"]) == 4)
check("fee_for() reads one period exactly", _fr.fee_for("example1.com.ua", "create", 5) == "450.00")
check("and a period nobody asked for is None", _fr.fee_for("example1.com.ua", "create", 7) is None)
check("the commands map still answers for the first period",
      _fr.fees()["example1.com.ua"]["commands"]["create"]["fee"] == "100.00")

print("login: only 2200 means the credentials are wrong")
# A server refuses <login> for several reasons, and they need opposite responses. Calling them all
# an authentication failure sends the reader to rotate a password that was never the problem.


def _refuse(code):
    return ('<?xml version="1.0"?><epp xmlns="urn:ietf:params:xml:ns:epp-1.0"><response>'
            '<result code="%d"><msg>refused</msg></result>'
            "<trID><clTRID>C1</clTRID><svTRID>X</svTRID></trID></response></epp>" % code)


def _login_error(code):
    client, _ = make_client([GREETING, _refuse(code)])
    client.connect()
    try:
        client.login()
        return None
    except EppException as exc:
        return exc


check("2200 is an AuthenticationException", isinstance(_login_error(2200), AuthenticationException))
# The session cap: the answer is to reconnect, not to change the password.
check("2502 (session limit) is a SessionError", isinstance(_login_error(2502), SessionError))
check("2501 (server closing) is a SessionError", isinstance(_login_error(2501), SessionError))
check("2307 is not an auth failure", not isinstance(_login_error(2307), AuthenticationException))

print("poll drain: a refusal is not an empty queue, and an async handler is refused")
# Inferring emptiness from "no <msgQ>" makes a refused poll look exactly like a drained queue.
_rc, _rf = make_client([GREETING, ('<?xml version="1.0"?><epp xmlns="urn:ietf:params:xml:ns:epp-1.0">'
                                   '<response><result code="2201"><msg>Authorization error</msg></result>'
                                   "<trID><clTRID>C1</clTRID><svTRID>X</svTRID></trID></response></epp>")])
_rc.connect()
_rc.throw_on_failure(False)
_handled = []
_raised = None
try:
    _rc.poll.drain(lambda n: _handled.append(n))
except CommandException as exc:
    _raised = exc
check("a refused poll raises rather than reporting an empty queue", _raised is not None)
check("and the handler was never called", _handled == [])


async def _async_handler(notice):  # noqa: D401 - a handler this loop cannot await
    return None


_ac2, _ = make_client([GREETING])
_ac2.connect()
_async_refused = False
try:
    _ac2.poll.drain(_async_handler)
except ValidationException:
    _async_refused = True
# An async handler returns a coroutine immediately, so every notice would be acked before any of
# them had been processed — the exact loss this method exists to prevent, and silently.
check("an async handler is refused rather than acking unprocessed notices", _async_refused)

print("authInfo: clearing is not the same as emptying")
# After a leak this is the only operation that helps. An empty <pw/> stores the empty string, which
# the holder can still present — the domain stays exactly as movable as it was.
_ac, _af = make_client([GREETING, OK(), OK(), OK()])
_ac.connect()
_ac.domain.update_builder("example3.com.ua").clear_auth_info().send()
check("clear_auth_info() emits <domain:null/>", "<domain:null />" in _af.written[0]
      or "<domain:null/>" in _af.written[0])
check("and no <pw> element at all", "<domain:pw>" not in _af.written[0])
_ac.domain.update("example3.com.ua", chg={"auth_info": "N3w-Pw"})
check("an ordinary change still emits <pw>", "<domain:pw>N3w-Pw</domain:pw>" in _af.written[1])
_both_threw = False
try:
    _ac.domain.update("example3.com.ua", chg={"auth_info": "a", "clear_auth_info": True})
except ValidationException:
    _both_threw = True
# The schema has one choice: a password, or nothing. Half-applying either would be worse.
check("setting and clearing at once is refused, not half-applied", _both_threw)
# RFC 5733 has no nullable form for a contact, so the SDK must not offer one.
from epptools.builders import ContactUpdateBuilder as _CUB
check("contact.update has no clear_auth_info", not hasattr(_CUB, "clear_auth_info"))

print("poll drain: a notice is acknowledged only after it has been handled")
# An ack DELETES the notice at the registry. A loop that acks first and processes second loses every
# notice whose processing fails, with nothing left to retry from.


def _notice(msg_id, text):
    return (
        '<?xml version="1.0"?><epp xmlns="urn:ietf:params:xml:ns:epp-1.0"><response>'
        '<result code="1301"><msg>Command completed successfully; ack to dequeue</msg></result>'
        '<msgQ count="2" id="%s"><qDate>2026-08-16T09:00:00Z</qDate><msg>%s</msg></msgQ>'
        "<trID><clTRID>C1</clTRID><svTRID>SRV-1</svTRID></trID></response></epp>" % (msg_id, text)
    )


_EMPTY_QUEUE = (
    '<?xml version="1.0"?><epp xmlns="urn:ietf:params:xml:ns:epp-1.0"><response>'
    '<result code="1300"><msg>Command completed successfully; no messages</msg></result>'
    "<trID><clTRID>C1</clTRID><svTRID>SRV-1</svTRID></trID></response></epp>"
)

_pc, _pf = make_client([GREETING, _notice("11", "first"), OK(), _notice("12", "second"), OK(), _EMPTY_QUEUE])
_pc.connect()
_seen = []
_count = _pc.poll.drain(lambda n: _seen.append(n.queue_message()))
check("drain returns how many notices were handled", _count == 2)
check("and hands the NOTICE text to the callback, not the result banner", _seen == ["first", "second"])
_acked = [m.group(1) for m in (_re.search(r'msgID="(\d+)"', s) for s in _pf.written) if m]
check("each notice is acked exactly once, in order", _acked == ["11", "12"])
check("it stops on the empty queue rather than looping", len(_pf.written) == 5)

# The property that matters: a failing handler must NOT destroy the notice.
_fc, _ff = make_client([GREETING, _notice("21", "boom"), OK(), _EMPTY_QUEUE])
_fc.connect()


def _boom(notice):
    raise RuntimeError("handler failed")


_threw = False
try:
    _fc.poll.drain(_boom)
except RuntimeError as exc:
    _threw = str(exc) == "handler failed"
check("a failing handler surfaces its own exception", _threw)
check("and the notice is NOT acked, so nothing is lost",
      not any("msgID=" in s for s in _ff.written))

# A queue that fills faster than it drains would otherwise never let the call return.
_lc, _lf = make_client([GREETING, _notice("31", "a"), OK(), _notice("32", "b"), OK(), _notice("33", "c"), OK()])
_lc.connect()
check("a limit stops the drain early", _lc.poll.drain(lambda n: None, 2) == 2)

print("builders: the fluent form and the keyword form are the same command")
# The whole design rests on send() being a thin façade over the ordinary method. Proved by comparing
# the FRAMES, not the option dicts: equal options could still be assembled into a different frame,
# and it is the frame the registry sees. clTRID is stripped — it is unique per command.
_CLTRID_SUB = __import__("re").compile(r"<clTRID>[^<]*</clTRID>")


def _frame_of(call):
    client, fake = make_client([GREETING, OK(), OK(), OK()])
    client.connect()
    call(client)
    return _CLTRID_SUB.sub("", fake.written[0] if fake.written else "")


def _same_frame(label, via_builder, via_kwargs):
    check(label, _frame_of(via_builder) == _frame_of(via_kwargs))


_same_frame(
    "domain:create built step by step matches the keyword call exactly",
    lambda c: (c.domain.create_builder("example3.com.ua").years(2).registrant("acme-01")
               .admin_contact("acme-01").tech_contact("acme-ns1").tech_contact("acme-ns2")
               .nameserver("ns1.acme.example").nameserver("ns2.acme.example")
               .auth_info("D0main-Pw").license("TM-1")
               .ds_record(12345, 8, 2, "AB" * 32).max_sig_life(604800)
               .max_fee("180.00", "UAH").send()),
    lambda c: c.domain.create(
        "example3.com.ua", years=2, registrant="acme-01",
        contacts={"admin": ["acme-01"], "tech": ["acme-ns1", "acme-ns2"]},
        nameservers=["ns1.acme.example", "ns2.acme.example"],
        auth_info="D0main-Pw", license="TM-1",
        sec_dns={"ds_data": [{"key_tag": 12345, "alg": 8, "digest_type": 2, "digest": "AB" * 32}],
                 "max_sig_life": 604800},
        fee={"amount": "180.00", "currency": "UAH"}),
)
_same_frame(
    "domain:create with inline glue matches the keyword call exactly",
    lambda c: (c.domain.create_builder("glue.com.ua").years(1).registrant("acme-01")
               .nameserver_with_glue("ns1.glue.com.ua", "192.0.2.1", "2001:db8::1")
               .nameserver_with_glue("ns2.glue.com.ua", "192.0.2.2")
               .send()),
    lambda c: c.domain.create(
        "glue.com.ua", years=1, registrant="acme-01", nameservers=[
            {"name": "ns1.glue.com.ua", "addresses": ["192.0.2.1", "2001:db8::1"]},
            {"name": "ns2.glue.com.ua", "addresses": ["192.0.2.2"]},
        ]),
)
_same_frame(
    "domain:update delta lands in the same add/rem/chg blocks",
    lambda c: (c.domain.update_builder("example3.com.ua")
               .add_nameserver("ns3.acme.example").rem_nameserver("ns1.acme.example")
               .add_status("clientHold").rem_status("clientTransferProhibited")
               .add_contact("tech", "acme-ns9")
               .change_registrant("acme-02").change_auth_info("N3w-Pw").send()),
    lambda c: c.domain.update(
        "example3.com.ua",
        add={"ns": ["ns3.acme.example"], "statuses": ["clientHold"], "contacts": {"tech": ["acme-ns9"]}},
        rem={"ns": ["ns1.acme.example"], "statuses": ["clientTransferProhibited"]},
        chg={"registrant": "acme-02", "auth_info": "N3w-Pw"}),
)
_same_frame(
    "contact:create with both postal forms matches the keyword call",
    lambda c: (c.contact.create_builder("acme-01", "billing@acme.example")
               .international_address(name="ACME LLC", city="Kyiv", country_code="UA",
                                      street=["1 Main St"], org="ACME LLC", postal_code="01001")
               .localized_address(name="ТОВ АКМЕ", city="Київ", country_code="UA")
               .voice("+380.441234567").auth_info("C0ntact-Pw").withhold("voice", "email").send()),
    lambda c: c.contact.create(
        "acme-01", email="billing@acme.example",
        postal_infos=[
            {"type": "int", "name": "ACME LLC", "city": "Kyiv", "cc": "UA",
             "street": ["1 Main St"], "org": "ACME LLC", "pc": "01001"},
            {"type": "loc", "name": "ТОВ АКМЕ", "city": "Київ", "cc": "UA"},
        ],
        voice="+380.441234567", auth_info="C0ntact-Pw",
        disclose={"flag": False, "voice": True, "email": True}),
)
_same_frame(
    "contact:update assembles the same chg block, statuses and disclosure",
    lambda c: (c.contact.update_builder("acme-01")
               .change_email("new@acme.example").change_voice("+380.441234567").change_fax("")
               .change_international_address(name="ACME LLC", city="Lviv", country_code="UA",
                                             org="", postal_code="79000")
               .change_auth_info("N3w-C0ntact-Pw").withhold("voice", "email")
               .add_status("clientUpdateProhibited").rem_status("clientDeleteProhibited").send()),
    lambda c: c.contact.update(
        "acme-01",
        chg={
            "email": "new@acme.example", "voice": "+380.441234567", "fax": "",
            "postal_info": {"type": "int", "name": "ACME LLC", "city": "Lviv", "cc": "UA",
                            "org": "", "pc": "79000"},
            "auth_info": "N3w-C0ntact-Pw",
            "disclose": {"flag": False, "voice": True, "email": True},
        },
        add_statuses=["clientUpdateProhibited"],
        rem_statuses=["clientDeleteProhibited"]),
)
_same_frame(
    "host:update addresses and statuses match the keyword call",
    lambda c: (c.host.update_builder("ns1.acme.example")
               .add_address("192.0.2.10").add_address("2001:db8::10")
               .rem_address("192.0.2.9").add_status("clientUpdateProhibited").send()),
    lambda c: c.host.update("ns1.acme.example",
                            add_addresses=["192.0.2.10", "2001:db8::10"],
                            rem_addresses=["192.0.2.9"],
                            add_statuses=["clientUpdateProhibited"]),
)

_bc, _bf = make_client([GREETING, OK(), OK()])
_bc.connect()
_pending = _bc.domain.create_builder("example3.com.ua").years(1).registrant("C1")
check("building sends nothing", _bf.written == [])
check("to_options() shows what would be sent",
      _pending.to_options() == {"years": 1, "registrant": "C1"})
_pending.send()
_re_sent = False
try:
    _pending.send()
except ValidationException:
    _re_sent = True
# Sending twice is two registrations and two charges, and the second is never what was meant.
check("a builder refuses to be sent twice", _re_sent)

print("errors: a class exists where the right next step differs")
# Every one of these needs a different response from the caller — top up, pick another name, clear a
# status, reconnect — which is the only reason they are separate classes.


def _err_for(code):
    client, _ = make_client([GREETING,
                             '<?xml version="1.0"?><epp xmlns="urn:ietf:params:xml:ns:epp-1.0">'
                             '<response><result code="%d"><msg>refused</msg>'
                             '<extValue><value><domain:name '
                             'xmlns:domain="urn:ietf:params:xml:ns:domain-1.0">taken.com.ua'
                             "</domain:name></value>"
                             '<reason lang="en">Already registered</reason></extValue></result>'
                             "<trID><svTRID>X</svTRID></trID></response></epp>" % code])
    client.connect()
    try:
        client.domain.check(["taken.com.ua"])
        return None
    except CommandException as exc:
        return exc


check("2104 is InsufficientFundsError", isinstance(_err_for(2104), InsufficientFundsError))
check("2202 is AuthorizationError", isinstance(_err_for(2202), AuthorizationError))
check("2302 is ObjectExistsError", isinstance(_err_for(2302), ObjectExistsError))
check("2303 is ObjectDoesNotExistError", isinstance(_err_for(2303), ObjectDoesNotExistError))
check("2305 is ObjectStatusError", isinstance(_err_for(2305), ObjectStatusError))
check("2308 is PolicyError", isinstance(_err_for(2308), PolicyError))
check("2502 is SessionError", isinstance(_err_for(2502), SessionError))
check("2005 stays a plain CommandException", type(_err_for(2005)) is CommandException)
check("every one is still a CommandException", isinstance(_err_for(2302), CommandException))
# Retrying a 2302 cannot make the name free; retrying a 2104 cannot pay for it.
check("only the transient ones are retryable",
      _err_for(2400).is_retryable() and _err_for(2502).is_retryable()
      and not _err_for(2302).is_retryable() and not _err_for(2104).is_retryable())
_exists = _err_for(2302)
check("the message names WHICH object was refused", str(_exists).endswith("('taken.com.ua')"))
check("subject() returns it too", _exists.subject() == "taken.com.ua")
check("reasons() carries the registry's extra detail", "Already registered" in _exists.reasons())

print("transact: a reply carrying someone else's clTRID is refused")
# The failure this prevents is silent and expensive: with a desynchronised stream, renew("b")
# returns 1000 carrying a's exDate. The registrar books b as renewed, and both are billed.


class _NoEchoTransport(FakeTransport):
    """Replays fixtures verbatim, so a deliberately WRONG clTRID survives to the client."""

    def read_frame(self):
        if not self.queue:
            raise RuntimeError("FakeTransport: no queued response")
        return self.queue.pop(0)


_wrong = (
    '<?xml version="1.0"?><epp xmlns="urn:ietf:params:xml:ns:epp-1.0"><response>'
    '<result code="1000"><msg>ok</msg></result>'
    "<trID><clTRID>SOMEONE-ELSES-TRID</clTRID><svTRID>SRV-9</svTRID></trID></response></epp>"
)
_fake = _NoEchoTransport()
_fake.queue = [GREETING, _wrong]
_c = Client(Config(host="h", clid="c", password="secret"), _fake)
_c.connect()
_err = None
try:
    _c.domain.check(["example1.com.ua"])
except ConnectionException as exc:
    _err = exc
check("a mismatched clTRID raises ConnectionException", _err is not None)
check("and the message names both transaction ids",
      _err is not None and "SOMEONE-ELSES-TRID" in str(_err) and "PYTHON-SDK-" in str(_err))
check("and the connection is closed, not left usable", _fake.is_open() is False)


# A server that clamps a caller-supplied clTRID to the schema's 3..64 characters is answering
# correctly, and must not be mistaken for a desynchronised stream.
class _ClampingTransport(FakeTransport):
    def read_frame(self):
        frame = self.queue.pop(0)
        if not self.written:
            return frame
        sent = _CLTRID.search(self.written[-1])
        if sent is None:
            return frame
        return _CLTRID.sub("<clTRID>%s</clTRID>" % sent.group(1)[:64], frame, count=1)


_fake = _ClampingTransport()
_fake.queue = [GREETING, OK()]
_c = Client(Config(host="h", clid="c", password="secret", cltrid_prefix="X" * 70), _fake)
_c.connect()
_clamped_ok = True
try:
    _c.domain.check(["example1.com.ua"])
except ConnectionException:
    _clamped_ok = False
check("a clTRID clamped to 64 characters by the server is accepted", _clamped_ok)

print("extValue: a relocated RFC 9038 payload keeps its content")
# A container has no character data of its own, so `text` is empty and the children must survive by
# NAME — otherwise the relocated figures are silently dropped.
_ev = Response.from_xml(
    '<?xml version="1.0"?><epp xmlns="urn:ietf:params:xml:ns:epp-1.0"><response>'
    '<result code="2005"><msg>err</msg><extValue><value>'
    '<balance:infData xmlns:balance="http://registry.example/epp/balance-1.0">'
    "<balance:balance>120.00</balance:balance><balance:creditLimit>500.00</balance:creditLimit>"
    '</balance:infData></value><reason lang="en">unhandled namespace</reason></extValue></result>'
    "<trID><svTRID>X</svTRID></trID></response></epp>"
).ext_values()[0]
check("a container carries no text of its own", _ev["text"] == "")
check("and its children survive by name",
      _ev["values"] == {"balance": "120.00", "creditLimit": "500.00"})
check("the element and its namespace are reported",
      _ev["element"] == "infData"
      and _ev["namespace"] == "http://registry.example/epp/balance-1.0")
check("the payload can be re-parsed from xml", "120.00" in _ev["xml"])

# The ordinary case must not regress: a leaf still answers with its value.
_leaf = Response.from_xml(
    '<?xml version="1.0"?><epp xmlns="urn:ietf:params:xml:ns:epp-1.0"><response>'
    '<result code="2005"><msg>err</msg><extValue><value>'
    '<domain:name xmlns:domain="urn:ietf:params:xml:ns:domain-1.0">bad..name</domain:name></value>'
    '<reason lang="en">Invalid label</reason></extValue></result>'
    "<trID><svTRID>X</svTRID></trID></response></epp>"
).ext_values()[0]
check("a leaf still reports which value was rejected", _leaf["text"] == "bad..name")
check("and has no children", _leaf["values"] == {})
check("the reason and its language come through",
      _leaf["reason"] == "Invalid label" and _leaf["lang"] == "en")

print("RFC 8807: the sentinel goes only in the element whose value was relocated")
# The sentinel means "the real value is in the matching loginSec element". Putting it in an element
# whose value was NOT relocated points the server at something that is not there — which is what a
# frame-wide flag did to every rotation across the 16-character boundary.
_LOGINSEC_GREETING = GREETING.replace(
    "</svcExtension>", "<extURI>%s</extURI></svcExtension>" % Namespaces.LOGINSEC
)
_SENTINEL = Namespaces.LOGINSEC_SENTINEL
_LONG = "a" * 40


def _login_frame(password, new_password):
    client, fake = make_client([_LOGINSEC_GREETING, OK()], password)
    client.connect()
    client.login(new_password)
    return parse(fake.written[0])


def _login_child(root, name):
    login = first_local(root, "login")
    for child in list(login):
        if local(child.tag) == name:
            return child.text
    return None


# Short -> long: only newPW moves. pw must stay LITERAL, or the server is told to look in an
# extension element that was never emitted and the login is rejected.
_f = _login_frame("short1", _LONG)
check("rotating short -> long keeps <pw> literal", _login_child(_f, "pw") == "short1")
check("and marks only <newPW> with the sentinel", _login_child(_f, "newPW") == _SENTINEL)
check("the new password travels in loginSec:newPW",
      any(e.text == _LONG for e in all_local(_f, "newPW")))
check("and no loginSec:pw is emitted for a short current password",
      len(all_local(_f, "pw")) == 1)

# Long -> short: the mirror image. newPW must stay literal, or the account's new password becomes
# the sentinel string itself.
_f = _login_frame(_LONG, "short2")
check("rotating long -> short marks <pw> with the sentinel", _login_child(_f, "pw") == _SENTINEL)
check("and keeps <newPW> literal", _login_child(_f, "newPW") == "short2")
check("the current password travels in loginSec:pw",
      any(e.text == _LONG for e in all_local(_f, "pw")))
check("and no loginSec:newPW is emitted for a short new password",
      len(all_local(_f, "newPW")) == 1)

# Long -> long: both relocate.
_f = _login_frame(_LONG, "b" * 40)
check("long -> long relocates both",
      _login_child(_f, "pw") == _SENTINEL and _login_child(_f, "newPW") == _SENTINEL)
check("and both loginSec values are present",
      len(all_local(_f, "pw")) == 2 and len(all_local(_f, "newPW")) == 2)

# Short -> short: neither value is relocated, so neither loginSec password element appears — even
# though the block itself does, to take part in the extension.
_f = _login_frame("short1", "short2")
check("short -> short relocates neither password",
      len(all_local(_f, "pw")) == 1 and len(all_local(_f, "newPW")) == 1)
check("and both passwords stay literal",
      _login_child(_f, "pw") == "short1" and _login_child(_f, "newPW") == "short2")


# Opting out removes the block outright, so a caller who wants the pre-8807 frame can have it — but
# a password that cannot fit in <pw> still travels in the extension, since there is nowhere else for
# it to go and dropping it would send the wrong password rather than none.
def _opt_out_frame(password, new_password):
    client, fake = make_client([_LOGINSEC_GREETING, OK()], password, login_security=False)
    client.connect()
    client.login(new_password)
    return parse(fake.written[0])


_f = _opt_out_frame("short1", "short2")
check("opting out sends no loginSec block for short passwords", len(all_local(_f, "loginSec")) == 0)
_f = _opt_out_frame(_LONG, None)
check("opting out cannot suppress a password that does not fit <pw>",
      len(all_local(_f, "loginSec")) == 1)

print("login: a short password takes part in the extension without travelling in it")
# Participation and relocation are separate decisions. The block goes out so the server will return
# its security events — it sends those only to a client that sent the block — while the password
# itself stays in <pw>, because it fits there and the sentinel would point at nothing.
client, fake = make_client([_LOGINSEC_GREETING, OK()])
client.connect()
client.login()
_f = parse(fake.written[0])
check("the block is sent so the server will answer with its events",
      len(all_local(_f, "loginSec")) == 1)
check("but the password is NOT relocated into it", len(all_local(_f, "pw")) == 1)
check("the userAgent names app, tech and os", len(all_local(_f, "app")) == 1
      and len(all_local(_f, "tech")) == 1 and len(all_local(_f, "os")) == 1)

print("login: the server's security events are readable")
EVENT_REPLY = ('<?xml version="1.0"?><epp xmlns="urn:ietf:params:xml:ns:epp-1.0"><response>'
               '<result code="1000"><msg>Command completed successfully</msg></result>'
               '<extension><loginSec:loginSecData xmlns:loginSec="%s">'
               '<loginSec:event type="certificate" level="warning" exDate="2026-09-15T00:00:00Z">'
               'Your client certificate expires in 30 day(s).</loginSec:event>'
               '<loginSec:event type="cipher" name="AES128-SHA" level="warning">Weak cipher suite.'
               '</loginSec:event></loginSec:loginSecData></extension>'
               '<trID><svTRID>SRV-1</svTRID></trID></response></epp>' % Namespaces.LOGINSEC)
_ev_client, _ = make_client([_LOGINSEC_GREETING, EVENT_REPLY])
_ev_client.connect()
_events = _ev_client.login().security_events()
check("both events are read", len(_events) == 2)
check("the certificate event keeps its expiry date", _events[0]["exDate"] == "2026-09-15T00:00:00Z")
check("the certificate event keeps its level", _events[0]["level"] == "warning")
check("the event text is the human sentence", "expires in 30 day(s)" in _events[0]["text"])
check("the cipher event keeps the suite name", _events[1]["name"] == "AES128-SHA")
check("a healthy login reports no events", client.greeting.security_events() == [])

# --------------------------------------------------------------------------
print("response accessors read every object the registry answers with")
# One fixture per object type, mirroring the PHP and node suites element for element. These are what
# a customer reaches for first, and the failure they produce is silent: an accessor that finds the
# wrong element returns a plausible-looking string.


def _inf_data(inner):
    return (
        '<?xml version="1.0"?><epp xmlns="urn:ietf:params:xml:ns:epp-1.0"><response>'
        '<result code="1000"><msg>ok</msg></result><resData>' + inner +
        "</resData><trID><svTRID>X</svTRID></trID></response></epp>"
    )


_dom = Response.from_xml(_inf_data(
    '<domain:infData xmlns:domain="urn:ietf:params:xml:ns:domain-1.0">'
    "<domain:name>example.com.ua</domain:name><domain:registrant>c-reg</domain:registrant>"
    '<domain:contact type="admin">c-admin</domain:contact>'
    '<domain:contact type="tech">c-t1</domain:contact><domain:contact type="tech">c-t2</domain:contact>'
    '<domain:contact type="billing">c-bill</domain:contact>'
    "<domain:ns><domain:hostAttr><domain:hostName>NS1.Example.NET</domain:hostName>"
    '<domain:hostAddr ip="v4">192.0.2.1</domain:hostAddr>'
    "<domain:hostAddr>198.51.100.7</domain:hostAddr></domain:hostAttr></domain:ns>"
    "<domain:host>ns1.example.com.ua</domain:host>"
    "<domain:authInfo><domain:pw>auth-1</domain:pw></domain:authInfo></domain:infData>"
))
check("role contacts are addressable one role at a time", _dom.tech_contacts() == ["c-t1", "c-t2"])
check("and admin/billing are separate",
      _dom.admin_contacts() == ["c-admin"] and _dom.billing_contacts() == ["c-bill"])
# Registries disagree on `tech` vs `Tech`; an exact match reports "no technical contact" for a
# domain that has two.
check("a role is matched case-insensitively", _dom.contacts_for("TECH") == ["c-t1", "c-t2"])
check("a role nobody holds is an empty list, not an error", _dom.contacts_for("reseller") == [])
check("all_contacts() includes the registrant", "c-reg" in _dom.all_contacts())
check("subordinate hosts are listed (they block a delete)",
      _dom.subordinate_hosts() == ["ns1.example.com.ua"])
_glue = _dom.nameserver_addresses()
check("inline glue is keyed by nameserver, not flattened", list(_glue) == ["ns1.example.net"])
check("and an addr with no @ip defaults to v4",
      _glue["ns1.example.net"][1] == {"ip": "198.51.100.7", "version": "v4"})
# The bug this pins: a document-wide addr search made a DOMAIN look like a well-addressed host.
check("host_addresses() stays empty on a domain", _dom.host_addresses() == [])
check("auth_info() surfaces the transfer secret", _dom.auth_info() == "auth-1")

_ct = Response.from_xml(_inf_data(
    '<contact:infData xmlns:contact="urn:ietf:params:xml:ns:contact-1.0">'
    "<contact:id>c-reg</contact:id>"
    '<contact:postalInfo type="int"><contact:name>Ivan Petrenko</contact:name>'
    "<contact:addr><contact:street>1 Main St</contact:street><contact:city>Kyiv</contact:city>"
    "<contact:cc>UA</contact:cc></contact:addr></contact:postalInfo>"
    '<contact:postalInfo type="loc"><contact:name>Іван</contact:name>'
    "<contact:addr><contact:city>Київ</contact:city>"
    "<contact:cc>UA</contact:cc></contact:addr></contact:postalInfo>"
    "<contact:fax>+380.441234568</contact:fax>"
    '<contact:disclose flag="0"><contact:email/></contact:disclose></contact:infData>'
))
# object_name() searched the whole document for <name> and found the person, so contact:info
# answered with a full name where the caller asked for the handle — and 2303 on the next command.
check("object_name() on a contact is the HANDLE, not the postal name", _ct.object_name() == "c-reg")
check("both postal forms are kept apart", _ct.postal_info()["loc"]["name"] == "Іван")
check("the international form stays available for printing anywhere",
      _ct.postal_info()["int"]["city"] == "Kyiv")
check("a missing postal part is empty, never None", _ct.postal_info()["loc"]["pc"] == "")
check("fax is read", _ct.fax() == "+380.441234568")
check("disclose keeps the flag with the list",
      _ct.disclose() == {"flag": False, "elements": ["email"]})
check("a contact addr container is not read as glue", _ct.host_addresses() == [])

_host = Response.from_xml(_inf_data(
    '<host:infData xmlns:host="urn:ietf:params:xml:ns:host-1.0">'
    "<host:name>ns1.example.com.ua</host:name>"
    '<host:addr ip="v6">2001:db8::53</host:addr><host:addr>203.0.113.9</host:addr></host:infData>'
))
check("a host object reports its own glue", _host.host_addresses() == [
    {"ip": "2001:db8::53", "version": "v6"},
    {"ip": "203.0.113.9", "version": "v4"},
])

_trn = Response.from_xml(_inf_data(
    '<domain:trnData xmlns:domain="urn:ietf:params:xml:ns:domain-1.0">'
    "<domain:name>example.com.ua</domain:name><domain:trStatus>pending</domain:trStatus>"
    "<domain:reID>ACME</domain:reID><domain:acID>EXAMPLE</domain:acID>"
    "<domain:acDate>2026-08-21T09:00:00Z</domain:acDate></domain:trnData>"
))
# transfer_status() says a transfer is pending without saying whose, or by when it auto-approves.
check("a transfer notice carries the counterparty and the deadline",
      _trn.transfer()["requested_by"] == "ACME"
      and _trn.transfer()["act_by"] == "2026-08-21T09:00:00Z")

_chk = Response.from_xml(
    '<?xml version="1.0"?><epp xmlns="urn:ietf:params:xml:ns:epp-1.0"><response>'
    '<result code="1000"><msg>ok</msg></result><resData>'
    '<domain:chkData xmlns:domain="urn:ietf:params:xml:ns:domain-1.0">'
    '<domain:cd><domain:name avail="1">free.com.ua</domain:name></domain:cd>'
    '<domain:cd><domain:name avail="0">taken.com.ua</domain:name>'
    "<domain:reason>In use</domain:reason></domain:cd>"
    "</domain:chkData></resData><extension>"
    '<fee:chkData xmlns:fee="urn:ietf:params:xml:ns:epp:fee-1.0"><fee:currency>UAH</fee:currency>'
    '<fee:cd avail="1"><fee:objID>free.com.ua</fee:objID><fee:class>premium</fee:class>'
    '<fee:command name="create"><fee:period unit="y">1</fee:period><fee:fee>5000.00</fee:fee>'
    "</fee:command></fee:cd></fee:chkData></extension>"
    "<trID><svTRID>X</svTRID></trID></response></epp>"
)
# `a or b` on ElementTree is a trap: a leaf element is falsy, so a <name> with no children was
# discarded in favour of a missing <id> and every name read as "no reason given".
check("an unavailable name reports why", _chk.unavailable_reason("taken.com.ua") == "In use")
check("an available name has no reason", _chk.unavailable_reason("free.com.ua") is None)
check("a name nobody asked about is None, not a false reason",
      _chk.unavailable_reason("other.com.ua") is None)
# Charging a premium at the standard price is a loss taken silently on every such registration.
check("a premium name is flagged",
      _chk.is_premium("free.com.ua") is True and _chk.fee_class("free.com.ua") == "premium")

# --------------------------------------------------------------------------
# PLAIN WORDS AND EPP'S ABBREVIATIONS BUILD THE SAME FRAME.
#
# The value of an alias is that it is not a second code path, so this compares the BYTES rather than
# checking that the plain word "works" - the only claim that stays true when the frame builder
# changes. It also pins precedence: a codebase migrating one call at a time passes both spellings for
# a while, and the plain word has to win, because that is what it is moving to.
print()
print("update vocabulary: plain words and EPP abbreviations")

_base = {"add": {"ns": ["ns1.plain.ua"], "statuses": ["clientHold"]}, "sec_dns": {"max_sig_life": 604800}}

client, fake = make_client([GREETING, OK()])
client.connect()
client.domain.update("plain.ua", rem={"ns": ["ns9.plain.ua"]}, chg={"registrant": "C-1"}, **_base)
_short = fake.written[0]

client, fake = make_client([GREETING, OK()])
client.connect()
client.domain.update("plain.ua", remove={"ns": ["ns9.plain.ua"]}, change={"registrant": "C-1"}, **_base)
_plain = fake.written[0]

check("domain.update remove=/change= build the same frame as rem=/chg=", _short == _plain)

client, fake = make_client([GREETING, OK()])
client.connect()
client.domain.update(
    "plain.ua",
    rem={"ns": ["ns-ignored.plain.ua"]}, remove={"ns": ["ns9.plain.ua"]},
    chg={"registrant": "C-IGNORED"}, change={"registrant": "C-1"},
    **_base
)
check("when both spellings are given, the plain word is the one that reaches the wire", fake.written[0] == _plain)

client, fake = make_client([GREETING, OK()])
client.connect()
client.domain.update("plain.ua", sec_dns={"remove_all": True})
check("domain.update sec_dns remove_all reaches the wire", "secDNS:all" in fake.written[0])

client, fake = make_client([GREETING, OK()])
client.connect()
client.contact.update("C-1", rem_statuses=["clientDeleteProhibited"], chg={"email": "contact@example.com"})
_c_short = fake.written[0]
client, fake = make_client([GREETING, OK()])
client.connect()
client.contact.update("C-1", remove_statuses=["clientDeleteProhibited"], change={"email": "contact@example.com"})
check("contact.update remove_statuses=/change= build the same frame", _c_short == fake.written[0])

client, fake = make_client([GREETING, OK()])
client.connect()
client.host.update("ns1.plain.ua", rem_addresses=["192.0.2.9"], rem_statuses=["clientUpdateProhibited"])
_h_short = fake.written[0]
client, fake = make_client([GREETING, OK()])
client.connect()
client.host.update("ns1.plain.ua", remove_addresses=["192.0.2.9"], remove_statuses=["clientUpdateProhibited"])
check("host.update remove_addresses=/remove_statuses= build the same frame", _h_short == fake.written[0])

# The alias must not become a hole in the check that catches a misspelled DNSSEC key.
_refused = None
try:
    client, fake = make_client([GREETING, OK()])
    client.connect()
    client.domain.update("plain.ua", sec_dns={"removes": True})
except Exception as _e:  # noqa: BLE001 - the type is the SDK's own, checked by message elsewhere
    _refused = _e
check("a near-miss spelling is still refused, not silently dropped", _refused is not None)


# --------------------------------------------------------------------------
print()
print("%d passed, %d failed" % (_passed, _failed))
sys.exit(1 if _failed else 0)


