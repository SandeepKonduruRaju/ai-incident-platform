import json

import pytest
from pydantic import ValidationError
from sqlalchemy import exc as sa_exc

from app.consumer import parse_event
from app.errors import ErrorCategory, TransientError, UnsupportedEventError, classify


def _validation_error() -> ValidationError:
    try:
        parse_event(b'{"eventType": "IncidentCreated", "schemaVersion": 1}')
    except ValidationError as error:
        return error
    raise AssertionError("expected a ValidationError")


@pytest.mark.parametrize(
    "error",
    [
        json.JSONDecodeError("bad", "{", 0),
        UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte"),
        UnsupportedEventError("unsupported schemaVersion 2"),
        sa_exc.IntegrityError("INSERT", {}, Exception("duplicate key")),
        sa_exc.DataError("INSERT", {}, Exception("value too long")),
    ],
    ids=lambda e: type(e).__name__,
)
def test_permanent_errors(error):
    assert classify(error) is ErrorCategory.PERMANENT


def test_validation_error_is_permanent():
    assert classify(_validation_error()) is ErrorCategory.PERMANENT


@pytest.mark.parametrize(
    "error",
    [
        sa_exc.OperationalError("SELECT 1", {}, ConnectionError("connection refused")),
        sa_exc.InterfaceError("SELECT 1", {}, Exception("connection is closed")),
        ConnectionRefusedError(),
        TimeoutError(),
        TransientError("injected"),
        RuntimeError("unexpected bug"),  # unknown: retried (bounded), then dead-lettered
    ],
    ids=lambda e: type(e).__name__,
)
def test_transient_errors(error):
    assert classify(error) is ErrorCategory.TRANSIENT


class TestParseEvent:
    VALID = {
        "eventId": "c51c3b96-ecd8-465b-960b-5284fcf8e231",
        "eventType": "IncidentCreated",
        "schemaVersion": 1,
        "occurredAt": "2026-10-16T16:51:50.641109500Z",
        "tenantId": "acme",
        "payload": {
            "incidentId": "1cd4a481-5a9b-42cd-97c1-844f974321f3",
            "title": "Checkout down",
            "severity": "HIGH",
            "status": "OPEN",
            "createdAt": "2026-10-16T16:51:50.524628Z",
        },
    }

    def test_valid_event(self):
        event = parse_event(json.dumps(self.VALID).encode())
        assert event.tenantId == "acme"
        assert event.requestId is None

    def test_invalid_json(self):
        with pytest.raises(json.JSONDecodeError):
            parse_event(b"{not json")

    def test_json_that_is_not_an_object(self):
        with pytest.raises(UnsupportedEventError):
            parse_event(b"[1, 2]")

    def test_unsupported_event_type(self):
        with pytest.raises(UnsupportedEventError, match="eventType"):
            parse_event(json.dumps({**self.VALID, "eventType": "IncidentDeleted"}).encode())

    def test_unsupported_schema_version(self):
        with pytest.raises(UnsupportedEventError, match="schemaVersion"):
            parse_event(json.dumps({**self.VALID, "schemaVersion": 2}).encode())

    def test_empty_value(self):
        with pytest.raises(UnsupportedEventError):
            parse_event(None)
