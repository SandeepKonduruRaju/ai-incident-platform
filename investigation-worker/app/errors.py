"""Error classification: decides between "retry" and "dead-letter now"."""

import json
from enum import StrEnum

from pydantic import ValidationError
from sqlalchemy import exc as sa_exc


class ErrorCategory(StrEnum):
    # Retrying can never help (the message itself is bad): dead-letter immediately.
    PERMANENT = "PERMANENT"
    # Might succeed later (database restarting, network blip): retry with backoff, then dead-letter.
    TRANSIENT = "TRANSIENT"


class UnsupportedEventError(Exception):
    """Valid JSON, but an eventType or schemaVersion this worker does not handle."""


class TransientError(Exception):
    """Raise to mark a failure as retryable explicitly."""


class PermanentError(Exception):
    """Raise to mark a failure as NOT retryable explicitly (retrying sends the same bad request again)."""


class TransientLLMError(TransientError):
    """LLM call failed in a way that may succeed later: timeout, 429, 5xx, overloaded, connection lost."""

    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after  # seconds, from the retry-after header when the API sent one


class PermanentLLMError(PermanentError):
    """LLM rejected this request (400, 413, 422): the same prompt will be rejected again."""


class LLMConfigError(Exception):
    """401/403/404/missing credentials: the WORKER is misconfigured (bad key, wrong model id), not this
    incident. Must never mark an incident FAILED; it leaves it PENDING and makes /health report 503."""


_PERMANENT = (
    PermanentError,
    json.JSONDecodeError,  # not JSON at all
    UnicodeDecodeError,  # not even text
    ValidationError,  # JSON, but not a valid event (missing/wrong fields)
    UnsupportedEventError,
    sa_exc.IntegrityError,  # violates a constraint: the same data will fail the same way
    sa_exc.DataError,  # value the database rejects (too long, wrong type)
)

_TRANSIENT = (
    TransientError,
    sa_exc.OperationalError,  # connection refused/lost, server shutting down
    sa_exc.InterfaceError,  # driver-level connection problem
    OSError,  # includes ConnectionError and TimeoutError
)


def classify(exc: BaseException) -> ErrorCategory:
    if isinstance(exc, _PERMANENT):
        return ErrorCategory.PERMANENT
    if isinstance(exc, _TRANSIENT):
        return ErrorCategory.TRANSIENT
    if isinstance(exc, sa_exc.DBAPIError) and exc.connection_invalidated:
        return ErrorCategory.TRANSIENT
    # Unknown errors (bugs, unexpected states): retry a few times, then dead-letter. Retries are
    # bounded and the DLQ keeps the message, so guessing "transient" never loses data.
    return ErrorCategory.TRANSIENT
