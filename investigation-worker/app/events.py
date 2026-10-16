"""Event models mirroring the Java records IncidentCreatedEvent and IncidentCreatedPayload.

Field names are camelCase on purpose so they match the JSON the Java service writes.
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

# Same names as the Java enums (Jackson writes enums as their names).
IncidentSeverity = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
IncidentStatus = Literal["OPEN", "INVESTIGATING", "MITIGATED", "RESOLVED"]


class _Event(BaseModel):
    # extra="ignore": unknown fields are dropped, so the producer can add fields without breaking us.
    # frozen=True: immutable, like a Java record.
    model_config = ConfigDict(extra="ignore", frozen=True)


class IncidentCreatedPayload(_Event):
    incidentId: UUID
    title: str
    description: str | None = None
    severity: IncidentSeverity
    status: IncidentStatus
    affectedService: str | None = None
    createdAt: datetime


class IncidentCreatedEvent(_Event):
    eventId: UUID
    eventType: str
    schemaVersion: int
    occurredAt: datetime
    tenantId: str
    requestId: str | None = None
    payload: IncidentCreatedPayload
