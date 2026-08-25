"""EPP result codes (RFC 5730 section 3). Branch on ``Response.code`` /
``CommandException.epp_code`` with these instead of bare numbers::

    if e.epp_code == ResultCode.OBJECT_EXISTS: ...
"""


class ResultCode:
    # 1xxx — success
    SUCCESS = 1000
    SUCCESS_PENDING = 1001            # action queued; resolved later via poll
    SUCCESS_NO_MESSAGES = 1300        # poll: queue empty
    SUCCESS_ACK_TO_DEQUEUE = 1301     # poll: a message is waiting
    SUCCESS_END_SESSION = 1500        # logout

    # 2000-2099 — protocol / syntax
    UNKNOWN_COMMAND = 2000
    COMMAND_SYNTAX_ERROR = 2001
    COMMAND_USE_ERROR = 2002          # e.g. already logged in
    REQUIRED_PARAMETER_MISSING = 2003
    PARAMETER_VALUE_RANGE_ERROR = 2004
    PARAMETER_VALUE_SYNTAX_ERROR = 2005

    # 2100-2199 — unimplemented / usage / billing
    UNIMPLEMENTED_PROTOCOL_VERSION = 2100  # login <version> must be 1.0
    UNIMPLEMENTED_COMMAND = 2101
    UNIMPLEMENTED_OPTION = 2102            # e.g. an unsupported login <lang>
    UNIMPLEMENTED_EXTENSION = 2103         # extension not supported here
    BILLING_FAILURE = 2104                 # insufficient funds
    NOT_ELIGIBLE_FOR_RENEWAL = 2105
    NOT_ELIGIBLE_FOR_TRANSFER = 2106

    # 2200-2299 — security
    AUTHENTICATION_ERROR = 2200            # bad login
    AUTHORIZATION_ERROR = 2201
    INVALID_AUTHORIZATION = 2202           # wrong authInfo

    # 2300-2399 — object lifecycle
    OBJECT_PENDING_TRANSFER = 2300
    OBJECT_NOT_PENDING_TRANSFER = 2301
    OBJECT_EXISTS = 2302
    OBJECT_DOES_NOT_EXIST = 2303
    OBJECT_STATUS_PROHIBITS_OPERATION = 2304
    OBJECT_ASSOCIATION_PROHIBITS_OPERATION = 2305
    PARAMETER_VALUE_POLICY_ERROR = 2306
    UNIMPLEMENTED_OBJECT_SERVICE = 2307
    DATA_MANAGEMENT_POLICY_VIOLATION = 2308

    # 2400+ — server
    COMMAND_FAILED = 2400
    COMMAND_FAILED_SERVER_CLOSING = 2500
    AUTHENTICATION_SERVER_CLOSING = 2501
    SESSION_LIMIT_EXCEEDED_SERVER_CLOSING = 2502
