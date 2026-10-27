"""GET /internal/v1/investigations against real PostgreSQL (skipped without Docker).

The app runs in-process through httpx2's ASGITransport, on the test's own event loop (so the async
engine is usable); the lifespan does not run, so no Kafka consumer or models are started.
"""

import uuid
from typing import Any

import httpx2
import pytest
from sqlalchemy import text

from app.config import Settings, get_settings
from app.embedding import FakeEmbedder
from app.events import IncidentCreatedPayload
from app.ingest import ingest
from app.investigations import Usage, claim, create_pending, save_completed, save_failed
from app.main import app
from app.retrieval import load_eval_incident

pytestmark = pytest.mark.integration

TOKEN = "test-only-internal-token"
ALLOWED_KEYS = {
    "incidentId", "status", "result", "citations", "model", "promptVersion", "attempts",
    "createdAt", "startedAt", "completedAt", "failureReason",
}


@pytest.fixture
async def client(engine, database_url):
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE worker.chunks"))
    await ingest(engine, FakeEmbedder())  # acme + globex
    app.state.engine = engine
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, database_url=database_url, internal_api_token=TOKEN
    )
    try:
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://worker") as http:
            yield http
    finally:
        app.dependency_overrides.clear()
        del app.state.engine


async def _chunks(engine, tenant: str, n: int) -> list[Any]:
    async with engine.connect() as conn:
        return (
            await conn.execute(
                text(
                    "SELECT id, source_type, source_id, content FROM worker.chunks "
                    "WHERE tenant_id = :t ORDER BY source_type, source_id, chunk_index LIMIT :n"
                ),
                {"t": tenant, "n": n},
            )
        ).all()


def _evidence(chunks) -> list[dict[str, str]]:
    return [
        {"label": f"C{i}", "chunk_id": str(c.id), "source_type": c.source_type, "source_id": c.source_id}
        for i, c in enumerate(chunks, start=1)
    ]


RESULT = {
    "root_cause": {"text": "Connection pool exhausted [C1]", "citations": ["C1"]},
    "contributing_factors": [],
    "remediation": [{"text": "Kill idle sessions", "citations": ["C2"]}],
    "confidence": "medium",
    "summary": "Pool exhaustion, see also [C1].",
}


async def _completed(engine, tenant: str, incident: IncidentCreatedPayload, evidence, result=RESULT):
    ref = await claim(engine, await create_pending(engine, tenant_id=tenant, incident=incident, request_id="t"))
    await save_completed(
        engine, ref, result=result, evidence=evidence,
        usage=Usage(model="fake-llm", input_tokens=10, output_tokens=5, llm_latency_ms=3),
        attempts=1, prompt_version="v1",
    )
    return ref


def _get(client, tenant: str, incident_id, token: str | None = TOKEN, **headers):
    if token is not None:
        headers["X-Internal-Token"] = token
    return client.get(
        "/internal/v1/investigations", params={"tenantId": tenant, "incidentId": str(incident_id)}, headers=headers
    )


async def test_completed_investigation_with_resolved_citations(client, engine):
    incident = load_eval_incident("acme", scenario="db_pool_exhausted")
    chunks = await _chunks(engine, "acme", 3)  # C3 is evidence but never cited
    await _completed(engine, "acme", incident, _evidence(chunks))

    response = await _get(client, "acme", incident.incidentId)

    assert response.status_code == 200
    body = response.json()
    assert (body["status"], body["model"], body["promptVersion"], body["attempts"]) == ("COMPLETED", "fake-llm", "v1", 1)
    assert body["result"] == RESULT
    assert [c["label"] for c in body["citations"]] == ["C1", "C2"]  # only labels used in the result
    first = body["citations"][0]
    assert (first["sourceType"], first["sourceId"]) == (chunks[0].source_type, chunks[0].source_id)
    assert first["snippet"] == chunks[0].content  # the whole chunk: the UI previews and expands it
    assert body["completedAt"] and body["createdAt"] and body["failureReason"] is None


async def test_response_contains_only_whitelisted_fields(client, engine):
    incident = load_eval_incident("acme", scenario="memory_leak")
    await _completed(engine, "acme", incident, _evidence(await _chunks(engine, "acme", 2)))

    body = (await _get(client, "acme", incident.incidentId)).json()

    assert set(body) == ALLOWED_KEYS
    raw = str(body).lower()
    for secret_ish in ("run_count", "request_id", "raw_output", "prompt\":", "system_prompt", "api_key", "token", TOKEN):
        assert secret_ish not in raw


async def test_other_tenant_gets_404_for_the_same_incident(client, engine):
    incident = load_eval_incident("acme", scenario="dns_failure")
    await _completed(engine, "acme", incident, _evidence(await _chunks(engine, "acme", 2)))

    assert (await _get(client, "acme", incident.incidentId)).status_code == 200
    response = await _get(client, "globex", incident.incidentId)
    assert response.status_code == 404


async def test_snippets_are_only_looked_up_in_the_same_tenant(client, engine):
    incident = load_eval_incident("acme", scenario="bad_deploy")
    globex_chunk = (await _chunks(engine, "globex", 1))[0]
    await _completed(engine, "acme", incident, _evidence([globex_chunk]))  # a (corrupt) cross-tenant reference

    body = (await _get(client, "acme", incident.incidentId)).json()

    assert body["citations"][0]["snippet"] is None  # never another tenant's text


async def test_unknown_incident_is_404(client):
    response = await _get(client, "acme", uuid.uuid4())
    assert response.status_code == 404


async def test_missing_or_wrong_token_is_401_and_health_stays_public(client):
    incident_id = uuid.uuid4()
    assert (await _get(client, "acme", incident_id, token=None)).status_code == 401
    assert (await _get(client, "acme", incident_id, token="wrong-token")).status_code == 401
    assert (await _get(client, "acme", incident_id, token=TOKEN[:-1])).status_code == 401
    assert (await client.get("/health")).status_code != 401


async def test_latest_investigation_wins(client, engine):
    incident = load_eval_incident("globex", scenario="db_pool_exhausted")
    evidence = _evidence(await _chunks(engine, "globex", 2))
    await _completed(engine, "globex", incident, evidence)
    newest = await claim(engine, await create_pending(engine, tenant_id="globex", incident=incident, request_id="t2"))

    body = (await _get(client, "globex", incident.incidentId)).json()

    assert body["status"] == "RUNNING" and body["result"] is None
    assert newest is not None and body["startedAt"] is not None


async def test_failed_investigation_has_a_short_reason_and_no_result(client, engine):
    incident = load_eval_incident("acme", scenario="slow_downstream")
    ref = await claim(engine, await create_pending(engine, tenant_id="acme", incident=incident, request_id="t"))
    await save_failed(
        engine, ref, reason="invalid LLM output after 2 attempts: bad\nsecond line with details",
        evidence=_evidence(await _chunks(engine, "acme", 2)), usage=Usage(), attempts=2, prompt_version="v1",
    )

    body = (await _get(client, "acme", incident.incidentId)).json()

    assert (body["status"], body["result"], body["citations"]) == ("FAILED", None, [])
    assert body["failureReason"] == "invalid LLM output after 2 attempts: bad"


async def test_invalid_incident_id_is_422(client):
    response = await client.get(
        "/internal/v1/investigations", params={"tenantId": "acme", "incidentId": "nope"},
        headers={"X-Internal-Token": TOKEN},
    )
    assert response.status_code == 422
