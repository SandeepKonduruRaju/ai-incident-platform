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


_PERMANENT = (
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
