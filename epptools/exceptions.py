"""Exception hierarchy raised by the SDK.

Catch :class:`EppException` to handle any failure. Catch a subclass when a particular failure needs
a different response from your code — which is the rule this hierarchy follows: a class exists
where the right next step differs, and nowhere else.

===========================  ==================================================================
:class:`ConfigException`     this client is set up wrong — every call fails until it is fixed
:class:`ValidationException` this call's arguments are wrong — the next call can be fine
:class:`ConnectionException` transport: TLS, timeout, framing
:class:`CommandException`    the registry refused (>= 2000); see its subclasses
===========================  ==================================================================
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:  # pragma: no cover
    from .response import Response


class EppException(RuntimeError):
    """Base class for every exception thrown by the SDK."""


class ConnectionException(EppException):
    """A transport-level problem (connect/read/write/TLS/framing)."""


class ConfigException(EppException, ValueError):
    """The client itself is misconfigured: no host, no credentials, a password this server cannot
    carry. Every call will fail the same way until the deployment changes.

    Distinct from :class:`ValidationException` because the two need opposite responses: one is
    answered to whoever made the request, the other is an alert for whoever runs the service.
    Sharing one class would leave a service to guess between them, and guessing wrong reports an
    operator's own misconfiguration to a customer as their mistake.

    Also a :class:`ValueError`, so both instincts work — ``except EppException`` and the
    ``except ValueError`` a Python developer reaches for when an argument is wrong.
    (:class:`json.JSONDecodeError` does the same.)
    """


class ValidationException(EppException, ValueError):
    """A value passed to this call cannot be used, and nothing was sent.

    An unknown option key, a fee amount that is not a decimal, an empty contact role, an operation
    this registry does not implement. The fault is in the arguments of one call — the next call
    with different arguments works. Also a :class:`ValueError`; see :class:`ConfigException`.
    """


class CommandException(EppException):
    """The server answered with an EPP error result code (>= 2000).

    The code and the full parsed response are attached so the caller can branch. Catch a subclass
    when the response should differ:

    ================================  ==========  ==================================================
    :class:`InsufficientFundsError`   2104        top up; every later billable command fails too
    :class:`AuthorizationError`       2201, 2202  not yours, or the wrong authInfo
    :class:`ObjectExistsError`        2302        already registered
    :class:`ObjectDoesNotExistError`  2303        no such name/handle/host
    :class:`ObjectStatusError`        2304, 2305  a status or association is in the way
    :class:`PolicyError`              2306, 2308  the registry's rules refuse this value
    :class:`SessionError`             2500–2502   reconnect and log in again
    :class:`AuthenticationException`  2200        the LOGIN itself failed
    ================================  ==========  ==================================================
    """

    def __init__(self, epp_code: int, message: str, response: "Optional[Response]" = None) -> None:
        super().__init__(message)
        self.epp_code = epp_code
        self.response = response

    def is_retryable(self) -> bool:
        """Whether sending the very same command again could succeed.

        True only for failures about the moment rather than the request. Retrying a 2302 cannot
        make the name free and retrying a 2104 cannot pay for it; a loop that treats every failure
        as transient turns one refusal into a rate-limit ban.
        """
        from .result_code import ResultCode

        return self.epp_code in (
            ResultCode.COMMAND_FAILED,
            ResultCode.COMMAND_FAILED_SERVER_CLOSING,
            ResultCode.AUTHENTICATION_SERVER_CLOSING,
            ResultCode.SESSION_LIMIT_EXCEEDED_SERVER_CLOSING,
        )

    def subject(self) -> Optional[str]:
        """The object the registry objected to, when it said which — the one name in a batch of
        five that was rejected. None when the answer named nothing, which is common."""
        for ext in (self.response.ext_values() if self.response is not None else []):
            text = ext.get("text")
            if text:
                return str(text)
        return None

    def reasons(self) -> List[str]:
        """Extra diagnostic text the registry attached, beyond the one-line message."""
        return self.response.error_reasons() if self.response is not None else []


class AuthenticationException(CommandException):
    """The LOGIN failed (2200) — bad clID or password.

    Distinct from :class:`AuthorizationError`, where the session is fine and one object is out of
    reach."""


class InsufficientFundsError(CommandException):
    """The account cannot pay for this operation (2104).

    Worth its own catch: nothing is wrong with the request, and every later billable command fails
    the same way until the balance is topped up. A batch that treats this like any other error
    grinds through its queue producing identical failures. Stop, alert whoever funds the account,
    resume afterwards."""


class AuthorizationError(CommandException):
    """The object exists, but not for you (2201 / 2202): it belongs to another registrar, or the
    authInfo does not match. Never retry with the same credentials."""


class ObjectExistsError(CommandException):
    """Already registered (2302). Not a fault in your request, and retrying cannot help."""


class ObjectDoesNotExistError(CommandException):
    """No such name, handle or nameserver (2303). Usually a stale identifier or a typo."""


class ObjectStatusError(CommandException):
    """The object's current state forbids the operation (2304 / 2305): a clientHold, a pending
    transfer, a nameserver still used by a domain. Clear what blocks you and the same request
    works."""


class PolicyError(CommandException):
    """The registry's own rules refuse the value (2306 / 2308). The command is well-formed and you
    are allowed to send it; retrying is pointless until the request itself changes."""


class SessionError(CommandException):
    """The server is ending the session (2500 / 2501 / 2502). Reconnect and log in again; the
    command itself may be perfectly good."""


def command_exception_for(
    code: int, message: str, response: "Optional[Response]" = None
) -> CommandException:
    """Build the most specific exception for a result code.

    One place decides, so the mapping cannot drift between the commands that use it.
    """
    from .result_code import ResultCode

    by_code = {
        ResultCode.BILLING_FAILURE: InsufficientFundsError,
        ResultCode.AUTHORIZATION_ERROR: AuthorizationError,
        ResultCode.INVALID_AUTHORIZATION: AuthorizationError,
        ResultCode.OBJECT_EXISTS: ObjectExistsError,
        ResultCode.OBJECT_DOES_NOT_EXIST: ObjectDoesNotExistError,
        ResultCode.OBJECT_STATUS_PROHIBITS_OPERATION: ObjectStatusError,
        ResultCode.OBJECT_ASSOCIATION_PROHIBITS_OPERATION: ObjectStatusError,
        ResultCode.PARAMETER_VALUE_POLICY_ERROR: PolicyError,
        ResultCode.DATA_MANAGEMENT_POLICY_VIOLATION: PolicyError,
        ResultCode.COMMAND_FAILED_SERVER_CLOSING: SessionError,
        ResultCode.AUTHENTICATION_SERVER_CLOSING: SessionError,
        ResultCode.SESSION_LIMIT_EXCEEDED_SERVER_CLOSING: SessionError,
    }
    return by_code.get(code, CommandException)(code, message, response)
