"""Immutable connection settings for an EPP session.

EPP is strict RFC EPP over TLS, conventionally on port 700. Many registries need NO client
certificate; the optional ``client_cert`` / ``client_key`` / ``client_key_passphrase`` are for the
ones that require mutual TLS. When ``obj_uris`` / ``ext_uris`` are left ``None`` the client logs in
advertising exactly the services the server greeting offers, so it is never rejected for an
unsupported service.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Any, Dict, List, Optional

from .exceptions import ConfigException


@dataclass
class Config:
    host: str
    clid: str
    #: The EPP password. Excluded from ``repr()``: a dataclass prints its fields in cleartext, so a
    #: single ``logging.debug("%r", cfg)``, traceback-with-locals or test dump would expose it.
    password: str = field(repr=False)
    port: int = 700
    lang: str = "en"
    connect_timeout: float = 10.0
    read_timeout: float = 30.0
    verify_peer: bool = True
    verify_peer_name: bool = True
    #: CA bundle that signs the SERVER certificate (private-CA / self-signed endpoint).
    ca_file: Optional[str] = None
    #: Your (registrar) client certificate — only when mutual TLS is required. PEM path.
    client_cert: Optional[str] = None
    #: Your client private key. PEM path. May be omitted when bundled in ``client_cert``.
    client_key: Optional[str] = None
    #: Passphrase for an encrypted client private key, if any. Kept out of ``repr()`` too.
    client_key_passphrase: Optional[str] = field(default=None, repr=False)
    #: Override the login objURIs; ``None`` = use the greeting's.
    obj_uris: Optional[List[str]] = None
    #: Override the login extURIs; ``None`` = use the greeting's.
    ext_uris: Optional[List[str]] = None
    #: Prefix for auto-generated client transaction ids (clTRID).
    cltrid_prefix: str = "PYTHON-SDK"
    #: Override the registry's own extension namespace. ``None`` — the normal case — discovers it
    #: from the ``<greeting>``.
    #:
    #: WHEN YOU NEED THIS. Discovery matches the last segment of an advertised URI
    #: (``.../registry-1.0``, ``.../balance-1.0``), which is the convention registries follow but not
    #: a rule anybody enforces. A registry that names its extension something else is served by
    #: setting the URI here — the library then sends exactly this and asks the greeting nothing.
    #:
    #: A wrong value is not a validation error, it is silence: an extension sent under a namespace
    #: the server does not recognise is not rejected, it is IGNORED, so the licence or the price is
    #: simply absent from what comes back and nothing anywhere says why.
    registry_ext_uri: Optional[str] = None
    #: Override for the account-balance extension namespace; ``None`` discovers it from the greeting.
    registry_balance_uri: Optional[str] = None
    #: Take part in the Login Security extension (RFC 8807) when the server offers it.
    #:
    #: A server returns its security events — a client certificate about to expire, an obsolete
    #: TLS version, a weak cipher suite — only to a client that SENT the extension block, because
    #: announcing a URI is not evidence of supporting it. So a client that never sends the block
    #: never hears the warning, and the first sign of trouble is the day the certificate stops
    #: working. Read what came back with :meth:`Response.security_events`.
    #:
    #: Set False to stay off the extension. It is then used only where it is unavoidable — a
    #: password longer than the 16 characters the base ``<pw>`` element can carry.
    login_security: bool = True

    @classmethod
    def from_dict(cls, values: Dict[str, Any]) -> "Config":
        """Build a Config from a plain dict (keys match the field names)."""
        allowed = {f.name for f in fields(cls)}
        unknown = set(values) - allowed
        if unknown:
            raise ConfigException("Config.from_dict: unknown keys: " + ", ".join(sorted(unknown)))
        return cls(**values)


