"""Internal, service-to-service read API: incident-service asks for the investigation of an incident.

    GET /internal/v1/investigations?tenantId=acme&incidentId=<uuid>     header X-Internal-Token: <secret>

Each service owns its data: incident-service never reads the worker schema, it calls this endpoint.
The caller is trusted to pass the tenant from the user's verified JWT; the tenant is still in every
WHERE clause here, so a wrong tenant can only ever produce a 404.

Only whitelisted fields leave the service (InvestigationView): never prompts, raw LLM output or keys.
"""

import hmac
import logging
import re
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import Settings, get_settings
from app.db import investigations
from app.logging_context import request_id_var, tenant_id_var, value_context

log = logging.getLogger(__name__)

TOKEN_HEADER = "X-Internal-Token"
# The citation's evidence text: the whole chunk (chunks are ~1,000 characters at most), so the UI can show a
# word-boundary preview with "Show more". Cutting here at 200 characters split words with no ellipsis and left
# nothing to expand. The cap only guards against an unexpectedly huge chunk.
SNIPPET_CHARS = 4000
FAILURE_REASON_CHARS = 300
_INLINE_LABEL = re.compile(r"\[(C\d+)\]")
_SAFE_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")  # same rule as incident-service's RequestIdFilter


class _CamelModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CitationView(_CamelModel):
    label: str
    sourceType: str
    sourceId: str
    snippet: str | None  # None if the chunk is gone (e.g. re-ingested data)


class InvestigationView(_CamelModel):
    incidentId: UUID
    status: Literal["PENDING", "RUNNING", "COMPLETED", "FAILED"]
    result: dict[str, Any] | None  # InvestigationResult as stored (snake_case keys, see app/schemas.py)
    citations: list[CitationView]
    model: str | None
    promptVersion: str | None
    attempts: int
    createdAt: datetime
    startedAt: datetime | None
    completedAt: datetime | None
    failureReason: str | None


def verify_internal_token(
    x_internal_token: Annotated[str | None, Header()] = None,
    settings: Settings = Depends(get_settings),
) -> None:
    expected = settings.internal_api_token
    if expected is None:  # startup already refuses this; defence in depth
        raise HTTPException(status_code=503, detail="internal API not configured")
    # compare_digest: constant time, so response timing does not leak how many characters matched.
    if x_internal_token is None or not hmac.compare_digest(
        x_internal_token.encode(), expected.get_secret_value().encode()
    ):
        raise HTTPException(status_code=401, detail="missing or invalid internal token")


def require_internal_token_configured(settings: Settings) -> None:
    """Called at startup: refuse to run with the internal endpoint unprotected."""
    if settings.internal_api_token is None:
        raise RuntimeError("INTERNAL_API_TOKEN is not set: refusing to start the internal API unprotected")


router = APIRouter(prefix="/internal/v1", dependencies=[Depends(verify_internal_token)])


# ---------------------------------------------------------------- queries (tenant in every WHERE)


async def latest_investigation(engine: AsyncEngine, tenant_id: str, incident_id: UUID) -> dict[str, Any] | None:
    query = (
        select(investigations)
        .where(
            investigations.c.tenant_id == tenant_id,
            investigations.c.incident_id == incident_id,
            # A superseded request was never run: the incident's investigation is the newer request's row.
            investigations.c.status != "SUPERSEDED",
        )
        .order_by(investigations.c.created_at.desc(), investigations.c.id.desc())
        .limit(1)
    )
    async with engine.connect() as conn:
        row = (await conn.execute(query)).first()
    return dict(row._mapping) if row is not None else None


async def chunk_snippets(engine: AsyncEngine, tenant_id: str, chunk_ids: list[UUID]) -> dict[UUID, str]:
    if not chunk_ids:
        return {}
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT id, left(content, :n) AS snippet FROM worker.chunks "
                "WHERE tenant_id = :tenant AND id = ANY(:ids)"
            ),
            {"n": SNIPPET_CHARS, "tenant": tenant_id, "ids": chunk_ids},
        )
        return {row.id: row.snippet for row in rows}


# ---------------------------------------------------------------- mapping (pure)


def labels_used(result: dict[str, Any] | None) -> list[str]:
    """Labels cited in the result (citation lists and inline [C#]), in first-use order."""
    if not result:
        return []
    findings = [result.get("root_cause"), *result.get("contributing_factors", []), *result.get("remediation", [])]
    labels: list[str] = []
    for finding in filter(None, findings):
        labels += finding.get("citations", []) + _INLINE_LABEL.findall(finding.get("text", ""))
    labels += _INLINE_LABEL.findall(result.get("summary", ""))
    return list(dict.fromkeys(labels))


def short_reason(reason: str | None) -> str | None:
    if reason is None:
        return None
    first_line = reason.strip().splitlines()[0] if reason.strip() else ""
    return first_line[:FAILURE_REASON_CHARS]


def to_view(row: dict[str, Any], snippets: dict[UUID, str]) -> InvestigationView:
    evidence = {item["label"]: item for item in row["evidence"] or []}
    citations = [
        CitationView(
            label=label,
            sourceType=evidence[label]["source_type"],
            sourceId=evidence[label]["source_id"],
            snippet=snippets.get(UUID(evidence[label]["chunk_id"])),
        )
        for label in labels_used(row["result"])
        if label in evidence
    ]
    return InvestigationView(
        incidentId=row["incident_id"],
        status=row["status"],
        result=row["result"],
        citations=citations,
        model=row["model"],
        promptVersion=row["prompt_version"],
        attempts=row["attempts"],
        createdAt=row["created_at"],
        startedAt=row["started_at"],
        completedAt=row["completed_at"],
        failureReason=short_reason(row["failure_reason"]),
    )


# ---------------------------------------------------------------- endpoint


@router.get("/investigations", response_model=InvestigationView)
async def get_investigation(
    request: Request,
    tenant_id: Annotated[str, Query(alias="tenantId", min_length=1, max_length=64)],
    incident_id: Annotated[UUID, Query(alias="incidentId")],
    x_request_id: Annotated[str | None, Header()] = None,
) -> InvestigationView:
    request_id = x_request_id if x_request_id and _SAFE_REQUEST_ID.fullmatch(x_request_id) else None
    with value_context(request_id_var, request_id), value_context(tenant_id_var, tenant_id):
        engine: AsyncEngine = request.app.state.engine
        row = await latest_investigation(engine, tenant_id, incident_id)
        if row is None:
            log.info("no investigation for incident %s", incident_id)
            raise HTTPException(status_code=404, detail="no investigation for this incident")
        evidence_ids = [UUID(item["chunk_id"]) for item in row["evidence"] or []]
        view = to_view(row, await chunk_snippets(engine, tenant_id, evidence_ids))
        log.info("investigation for incident %s: %s", incident_id, view.status)
        return view
