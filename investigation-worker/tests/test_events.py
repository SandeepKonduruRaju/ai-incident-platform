import json
from datetime import datetime, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.events import IncidentCreatedEvent

# A real event written by incident-service to "incident-events" (description set to null for this test).
# Note occurredAt has 9 fractional digits (Java Instant); Python datetime keeps only 6.
SAMPLE_EVENT = """
{
  "eventId": "c51c3b96-ecd8-465b-960b-5284fcf8e231",
  "eventType": "IncidentCreated",
  "schemaVersion": 1,
  "occurredAt": "2026-10-16T16:51:50.641109500Z",
  "tenantId": "acme",
  "requestId": "live-test-1",
  "payload": {
    "incidentId": "1cd4a481-5a9b-42cd-97c1-844f974321f3",
    "title": "Checkout API 500 errors",
    "description": null,
    "severity": "HIGH",
    "status": "OPEN",
    "affectedService": "payment-service",
    "createdAt": "2026-10-16T16:51:50.524628Z"
  }
}
"""


def test_parses_real_event():
    event = IncidentCreatedEvent.model_validate_json(SAMPLE_EVENT)

    assert event.eventId == UUID("c51c3b96-ecd8-465b-960b-5284fcf8e231")
    assert event.eventType == "IncidentCreated"
    assert event.schemaVersion == 1
    assert event.occurredAt == datetime(2026, 10, 16, 16, 51, 50, 641109, tzinfo=timezone.utc)
    assert event.tenantId == "acme"
    assert event.requestId == "live-test-1"
    assert event.payload.incidentId == UUID("1cd4a481-5a9b-42cd-97c1-844f974321f3")
    assert event.payload.description is None
    assert event.payload.severity == "HIGH"
    assert event.payload.status == "OPEN"
    assert event.payload.affectedService == "payment-service"
    assert event.payload.createdAt.tzinfo is not None


def test_ignores_unknown_fields():
    data = json.loads(SAMPLE_EVENT)
    data["newEnvelopeField"] = "added in a later schema version"
    data["payload"]["priorityScore"] = 42

    event = IncidentCreatedEvent.model_validate_json(json.dumps(data))

    assert event.tenantId == "acme"
    assert not hasattr(event, "newEnvelopeField")


def test_missing_event_id_is_rejected():
    data = json.loads(SAMPLE_EVENT)
    del data["eventId"]

    with pytest.raises(ValidationError) as error:
        IncidentCreatedEvent.model_validate_json(json.dumps(data))

    assert error.value.errors()[0]["loc"] == ("eventId",)
