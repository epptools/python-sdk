"""EppTools — EPP SDK for Python.

A small, dependency-free client for the Registry EPP service — standard RFC 5730-5734
EPP over TLS on port 700. Speaks the wire protocol directly (no framework, no server code).

    from epptools import Client, Config

    client = Client(Config(host="epp.registry.example", clid="your-clid", password="your-secret"))
    client.connect()
    client.login()
    print(client.domain.check(["example.com.ua"]).availability())
    client.logout()
    client.disconnect()
"""

from . import namespaces as Namespaces
from .client import Client
from .commands import Contact, Domain, Host, Poll
from .config import Config
from .exceptions import (
    AuthenticationException,
    AuthorizationError,
    CommandException,
    ConfigException,
    ConnectionException,
    EppException,
    InsufficientFundsError,
    ObjectDoesNotExistError,
    ObjectExistsError,
    ObjectStatusError,
    PolicyError,
    SessionError,
    ValidationException,
)
from .frame import Frame
from .response import Response
from .result_code import ResultCode
from .transport import Connection, Transport

from ._version import __version__   # noqa: F401  (re-exported; declared in _version.py)

__all__ = [
    "Client",
    "Config",
    "Frame",
    "Response",
    "ResultCode",
    "Namespaces",
    "Transport",
    "Connection",
    "Domain",
    "Contact",
    "Host",
    "Poll",
    "EppException",
    "ConnectionException",
    "ConfigException",
    "CommandException",
    "AuthenticationException",
    "AuthorizationError",
    "InsufficientFundsError",
    "ObjectDoesNotExistError",
    "ObjectExistsError",
    "ObjectStatusError",
    "PolicyError",
    "SessionError",
    "ValidationException",
    "__version__",
]



