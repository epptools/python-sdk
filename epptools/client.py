"""EPP client for the Registry service. Open a connection, log in, then reach the object
commands through the resource properties — ``client.domain``, ``.contact``, ``.host``,
``.poll``. Each command returns a :class:`Response`. By default any EPP error code (>= 2000)
is raised as a :class:`CommandException`; call ``throw_on_failure(False)`` to inspect codes
yourself instead.

    client = Client(Config(host="epp.registry.example", clid="your-clid", password="..."))
    client.connect()
    client.login()
    avail = client.domain.check(["example.com.ua"]).availability()
    client.logout()
    client.disconnect()
"""

from __future__ import annotations

import os
import platform
import re
import time
from functools import cached_property
from typing import List, Optional, Union

from . import namespaces as ns
from .commands import Contact, Domain, Host, Poll
from .config import Config
from .exceptions import (
    AuthenticationException,
    CommandException,
    ConfigException,
    ConnectionException,
    command_exception_for,
)
from ._version import __version__
from .frame import Frame
from .response import Response
from .result_code import ResultCode
from .transport import Connection, Transport

# Bounds of the RFC 5730 <pw> / <newPW> schema type (epp:pwType, minLength 6 / maxLength 16).
# The login frame is always schema-validated, so anything outside this range is rejected as an
# opaque 2001 with no hint about which field was wrong.
PW_MIN = 6
PW_MAX = 16

# Maximum password length when the server supports the Login Security extension (RFC 8807),
# which carries the password outside the 16-character <pw> element. Applies only when the
# server's <greeting> advertises the extension; otherwise PW_MAX applies.
PW_MAX_LOGINSEC = 128

try:  # Optional logging via the standard library; any logging.Logger works.
    import logging

    _Logger = logging.Logger
except ImportError:  # pragma: no cover
    _Logger = object  # type: ignore

# Matches <pw> and <newPW> in any namespace prefix, including <loginSec:pw>. The opening tag may
# carry attributes (``<domain:pw roid="D1-EXAMPLE">``), so the pattern accepts anything up to '>':
# every such element is masked whatever attributes it carries.
_REDACT = re.compile(
    r"(<(?:[\w.-]+:)?(?:pw|newPW)(?:\s[^>]*)?>)(.*?)(</(?:[\w.-]+:)?(?:pw|newPW)\s*>)", re.S)

# The clTRID this client put on the wire, and the characters the schema's trIDStringType excludes.
_CLTRID_RE = re.compile(r"<clTRID>([^<]*)</clTRID>")
_CONTROL_RE = re.compile(r"[\x00-\x1F\x7F]")


class Client:
    def __init__(self, config: Config, connection: Optional[Transport] = None,
                 logger: "Optional[_Logger]" = None) -> None:
        self._config = config
        self._connection: Transport = connection if connection is not None else Connection(config)
        self._logger = logger
        self._greeting: Optional[Response] = None
        self._logged_in = False
        self._throw = True
        self._trid_counter = 0
        # Per-process component of the client transaction id (clTRID): ids from one process
        # share a stable middle segment and stay unique across concurrent processes.
        self._process_token = str(os.getpid())

    @classmethod
    def connect_and_login(cls, config: Config) -> "Client":
        client = cls(config)
        client.connect()
        client.login()
        return client

    def throw_on_failure(self, throw: bool = True) -> "Client":
        """Toggle automatic CommandException raising on EPP error codes."""
        self._throw = throw
        return self

    def set_logger(self, logger: "Optional[_Logger]") -> "Client":
        """Attach (or clear) a logger; passwords/authInfo are masked before logging."""
        self._logger = logger
        return self

    def __enter__(self) -> "Client":
        return self

    def __exit__(self, *exc) -> None:
        self.disconnect()

    def __del__(self) -> None:
        try:
            self._connection.close()
        except Exception:  # pragma: no cover — never raise from a finaliser
            pass

    # --- session ---------------------------------------------------------------

    def connect(self) -> Response:
        """Open the TLS socket and read the unsolicited <greeting>."""
        if self._config.host == "":
            raise ConfigException("Config: host must not be empty")
        if not self._connection.is_open():
            self._connection.open()
        raw = self._connection.read_frame()
        self._log_debug("EPP << greeting", raw)
        self._greeting = Response.from_xml(raw)
        return self._greeting

    @property
    def greeting(self) -> Optional[Response]:
        return self._greeting

    def hello(self) -> Response:
        """Send <hello>; the server replies with a fresh <greeting>."""
        self._connection.write_frame(
            '<?xml version="1.0" encoding="UTF-8"?><epp xmlns="%s"><hello/></epp>' % ns.EPP
        )
        self._greeting = Response.from_xml(self._connection.read_frame())
        return self._greeting

    def login(self, new_password: Optional[str] = None) -> Response:
        """Authenticate. Advertises exactly the services the greeting offered (never rejected
        for an unsupported service) unless Config.obj_uris / ext_uris override them.

        Pass ``new_password`` to rotate the EPP password during login (RFC 5730 <newPW>)."""
        if self._config.clid == "" or self._config.password == "":
            raise ConfigException(
                "login requires a non-empty clID and password (clID %s, password %s) — check your config"
                % ("set" if self._config.clid else "EMPTY", "set" if self._config.password else "EMPTY")
            )
        # Bounds that hold for every server are checked before connecting, so a misconfigured
        # password never opens a socket. Whether a password longer than PW_MAX is usable depends on
        # the server advertising RFC 8807, so that check happens once the greeting has been read.
        for value, label in ((self._config.password, "Config.password"), (new_password, "the new password")):
            if value is None:
                continue
            if not (PW_MIN <= len(value) <= PW_MAX_LOGINSEC):
                raise ConfigException(
                    "%s must be %d-%d characters long (got %d)"
                    % (label, PW_MIN, PW_MAX_LOGINSEC, len(value))
                )
        if self._greeting is None:
            self.connect()

        greeting_obj = self._greeting.service_obj_uris() if self._greeting else []
        greeting_ext = self._greeting.service_ext_uris() if self._greeting else []
        obj_uris = self._config.obj_uris or (greeting_obj or ns.DEFAULT_OBJ_URIS)
        ext_uris = self._config.ext_uris if self._config.ext_uris is not None else (greeting_ext or ns.DEFAULT_EXT_URIS)
        # The epp-1.0 base URI is not an object service and is never listed in <login>.
        obj_uris = [u for u in obj_uris if u != ns.EPP]

        # Two separate decisions about the Login Security extension (RFC 8807), both needing the
        # server to advertise it: whether to TAKE PART (see Config.login_security — that is what
        # makes the server's security events come back) and whether a password has to TRAVEL in it,
        # which is forced only by one longer than the 16 characters the base <pw> element allows.
        loginsec_available = ns.LOGINSEC in ext_uris
        for value, label in ((self._config.password, "Config.password"), (new_password, "the new password")):
            if value is not None and len(value) > PW_MAX and not loginsec_available:
                raise ConfigException(
                    "%s is %d characters, but this server does not advertise %s — the EPP <pw> "
                    "schema type allows at most %d, so the server would answer a bare 2001"
                    % (label, len(value), ns.LOGINSEC, PW_MAX)
                )
        # Decided PER ELEMENT, not once for the frame. The sentinel means "the real value is in the
        # matching loginSec element", so putting it in an element whose value was NOT relocated
        # points the server at something that is not there and the login is refused. Rotation
        # across the 16-character boundary is exactly that case: changing a short password to a
        # long one relocates newPW only, and a frame-wide decision would send
        # <pw>[LOGIN-SECURITY]</pw> with no <loginSec:pw> beside it.
        relocate_pw = loginsec_available and len(self._config.password) > PW_MAX
        relocate_new_pw = (
            loginsec_available and new_password is not None and len(new_password) > PW_MAX
        )
        # The block is also sent when nothing has to be relocated, because that is what makes the
        # server's security events reach you: it returns them only to a client that took part in
        # the extension, since announcing a URI proves nothing. Config.login_security turns this
        # off; a relocated password still sends the block, having no other way to travel.
        use_loginsec = relocate_pw or relocate_new_pw or (
            loginsec_available and self._config.login_security
        )

        frame = self.frame()
        login = frame.verb("login")
        frame.epp(login, "clID", self._config.clid)
        frame.epp(login, "pw", ns.LOGINSEC_SENTINEL if relocate_pw else self._config.password)
        if new_password is not None:
            frame.epp(login, "newPW", ns.LOGINSEC_SENTINEL if relocate_new_pw else new_password)
        options = frame.epp(login, "options")
        frame.epp(options, "version", "1.0")
        frame.epp(options, "lang", self._config.lang)
        svcs = frame.epp(login, "svcs")
        for uri in obj_uris:
            frame.epp(svcs, "objURI", uri)
        if ext_uris:
            svc_ext = frame.epp(svcs, "svcExtension")
            for uri in ext_uris:
                frame.epp(svc_ext, "extURI", uri)
        if use_loginsec:
            # <extension> is a sibling of <login> within <command>. The password travels in
            # <loginSec:pw>; the <pw> element above carries the sentinel that points at it.
            ext = frame.extension()
            block = frame.ns(ext, ns.LOGINSEC, "loginSec:loginSec")
            ua = frame.ns(block, ns.LOGINSEC, "loginSec:userAgent")
            # app, tech and os in that order — the schema's userAgentType is a sequence, and a
            # registry support desk asked "which client, on what" answers both from one login.
            frame.ns(ua, ns.LOGINSEC, "loginSec:app", "EppTools Python SDK %s" % __version__)
            frame.ns(ua, ns.LOGINSEC, "loginSec:tech", "Python %s" % platform.python_version())
            frame.ns(ua, ns.LOGINSEC, "loginSec:os", platform.system() or "unknown")
            if relocate_pw:
                frame.ns(block, ns.LOGINSEC, "loginSec:pw", self._config.password)
            if relocate_new_pw:
                frame.ns(block, ns.LOGINSEC, "loginSec:newPW", new_password)

        response = self._transact(frame.to_xml())
        if response.code() != 1000:
            message = "Login failed (EPP %d): %s" % (
                response.code(), response.message() or "no message")
            # Only 2200 means the credentials are wrong. A login can also be refused because the
            # account is at its session limit (2502), because the server is closing (2501), because
            # a service in <svcs> is not offered (2307), because this connection is already logged
            # in (2002), or over the protocol version (2100) — each with its own class and its own
            # remedy. Calling them all an authentication failure sends the reader to rotate a
            # password that was never the problem, and hides that the answer is to reconnect.
            if response.code() == ResultCode.AUTHENTICATION_ERROR:
                raise AuthenticationException(response.code(), message, response)
            raise command_exception_for(response.code(), message, response)
        self._logged_in = True
        return response

    def logout(self) -> Response:
        frame = self.frame()
        frame.verb("logout")
        response = self._transact(frame.to_xml())  # 1500; the server then closes the link
        self._logged_in = False
        return response

    def disconnect(self) -> None:
        self._connection.close()
        self._logged_in = False

    def is_connected(self) -> bool:
        return self._connection.is_open()

    def is_logged_in(self) -> bool:
        return self._logged_in

    # --- resource handlers -----------------------------------------------------

    @cached_property
    def domain(self) -> Domain:
        return Domain(self)

    @cached_property
    def contact(self) -> Contact:
        return Contact(self)

    @cached_property
    def host(self) -> Host:
        return Host(self)

    @cached_property
    def poll(self) -> Poll:
        return Poll(self)

    # --- the registry's own extensions -----------------------------------------

    def _advertised_ext(self) -> List[str]:
        return self._greeting.service_ext_uris() if self._greeting else []

    def registry_ext_uri(self) -> Optional[str]:
        """The namespace this registry uses for its own object extensions, or ``None``.

        Configured value first, otherwise read out of the greeting.
        """
        if self._config.registry_ext_uri is not None:
            return self._config.registry_ext_uri
        return ns.registry_extension(self._advertised_ext())

    def registry_balance_uri(self) -> Optional[str]:
        """The namespace this registry uses for account balance, or ``None``."""
        if self._config.registry_balance_uri is not None:
            return self._config.registry_balance_uri
        return ns.registry_balance(self._advertised_ext())

    def require_registry_ext_uri(self, what: str) -> str:
        """The registry extension namespace, or an explanation of why there isn't one.

        Callers that MUST have it use this rather than :meth:`registry_ext_uri`, because the
        alternative to failing here is failing invisibly: an extension sent under a namespace the
        server does not recognise is ignored, not rejected, so the command succeeds with the licence
        quietly missing.
        """
        uri = self.registry_ext_uri()
        if uri is not None:
            return uri
        raise ConfigException(
            "%s needs the registry's own EPP extension, and %s does not advertise one. "
            "It offered: %s. If this registry does support it under a name discovery cannot guess, "
            "set registry_ext_uri in Config."
            % (what, self._config.host, ", ".join(self._advertised_ext()) or "(no greeting read yet)")
        )

    def balance(self) -> Response:
        """Query the registrar account balance (creditLimit / balance / availableCredit).

        Not an RFC command — it exists only where a registry defines it, which is why the namespace
        is discovered rather than assumed.
        """
        uri = self.registry_balance_uri()
        if uri is None:
            raise ConfigException(
                "%s advertises no account-balance EPP extension. It offered: %s. If this registry "
                "does support one under a name discovery cannot guess, set registry_balance_uri in "
                "Config."
                % (self._config.host, ", ".join(self._advertised_ext()) or "(no greeting read yet)")
            )
        frame = self.frame()
        frame.ns(frame.verb("info"), uri, "balance:info")
        return self.request(frame)

    # --- low-level -------------------------------------------------------------

    def frame(self) -> Frame:
        """A new command frame with an auto-generated clTRID already stamped."""
        return Frame.command(self._next_cltrid())

    def request(self, frame: Union[Frame, str]) -> Response:
        """Send a frame (a :class:`Frame` or raw XML string) and return the parsed response.
        Raises CommandException on an EPP error code unless throw_on_failure(False) is set."""
        xml = frame.to_xml() if isinstance(frame, Frame) else frame
        response = self._transact(xml)
        if self._throw and not response.is_success():
            # The message names the SUBJECT when the registry identified one. On a command carrying
            # five names, "EPP 2302: Object exists" leaves the reader to work out which of the five,
            # and the answer is sitting in <extValue> unread.
            subject = None
            for ext in response.ext_values():
                if ext.get("text"):
                    subject = ext["text"]
                    break
            message = "EPP %d: %s" % (response.code(), response.message() or "command failed")
            if subject is not None:
                message += " ('%s')" % subject
            raise command_exception_for(response.code(), message, response)
        return response

    # --- internals -------------------------------------------------------------

    def _transact(self, xml: str) -> Response:
        if not self._connection.is_open():
            raise ConnectionException("Not connected — call connect() first")
        self._log_debug("EPP >> request", self._redact(xml))
        self._connection.write_frame(xml)
        raw = self._connection.read_frame()
        self._log_debug("EPP << response", self._redact(raw))
        response = Response.from_xml(raw)
        self._assert_belongs_to_this_command(xml, response)
        if self._logger is not None:
            level = "info" if response.is_success() else "warning"
            getattr(self._logger, level)(
                "EPP result %d (svTRID=%s clTRID=%s)",
                response.code(), response.sv_trid(), response.cl_trid(),
            )
        return response

    def _assert_belongs_to_this_command(self, xml: str, response: Response) -> None:
        """Verify the reply echoes the clTRID this command sent.

        Every command carries a clTRID and the server echoes it back. Checking it turns a
        desynchronised stream — a stray unsolicited frame, or two commands in flight at once — from
        a silent mix-up into a loud failure. Without it, a reply belonging to the previous command
        is indistinguishable from this one's, and for a renew or a create that means booking the
        wrong domain as done: ``renew('b')`` returns 1000 carrying a's exDate, and both are billed.

        The connection is closed, not just reported: once the offsets disagree, every later frame on
        this stream is suspect too.

        Compared against the CLAMPED form of what was sent: epp-1.0's trIDStringType is 3..64
        characters, so a server that echoes a caller-supplied clTRID legitimately returns a
        truncated or padded value. Raw equality would reject those valid replies — the check must
        catch a WRONG transaction, not a normalised one.
        """
        sent = _CLTRID_RE.search(xml)
        if sent is None:
            return
        echoed = response.cl_trid()
        if not echoed:
            return
        sent_trid = sent.group(1)
        clean = _CONTROL_RE.sub("", sent_trid).strip()[:64]
        expected = clean if len(clean) >= 3 else clean.ljust(3, "-")
        if echoed != sent_trid and echoed != expected:
            self._connection.close()
            raise ConnectionException(
                "Response does not belong to this command (sent clTRID %s, received %s) — "
                "the connection was desynchronised and has been closed." % (sent_trid, echoed)
            )

    def _log_debug(self, msg: str, frame: str) -> None:
        if self._logger is not None:
            self._logger.debug("%s %s", msg, frame)

    @staticmethod
    def _redact(xml: str) -> str:
        """Mask passwords / authInfo (any namespace) before a frame is logged."""
        return _REDACT.sub(r"\1***\3", xml)

    def _next_cltrid(self) -> str:
        self._trid_counter += 1
        # A client transaction id that is easy to correlate in logs: prefix, a UTC timestamp,
        # the per-process token and a monotonic counter.
        return "%s-%s-%s-%04d" % (
            self._config.cltrid_prefix,
            time.strftime("%Y%m%d%H%M%S", time.gmtime()),
            self._process_token,
            self._trid_counter,
        )


