"""retrieve_evidence end to end with FakeEmbedder + FakeReranker on a real PostgreSQL + pgvector container
(skipped without Docker). The real-model version is in test_search_relevance.py."""

import json
import uuid

import pytest
from sqlalchemy import text

import app.retrieval as retrieval
from app.embedding import FakeEmbedder
from app.events import IncidentCreatedPayload
from app.ingest import DEFAULT_DATA_DIR, ingest
from app.rerank import FakeReranker
from app.retrieval import TenantIsolationError, label_map, load_eval_incident, retrieve_evidence

pytestmark = pytest.mark.integration


@pytest.fixture
async def both_tenants(engine):
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE worker.chunks"))
    await ingest(engine, FakeEmbedder())
    return engine


def _eval_incidents() -> list[dict]:
    return json.loads((DEFAULT_DATA_DIR / "eval_incidents.json").read_text(encoding="utf-8"))


async def test_every_item_belongs_to_the_requested_tenant(both_tenants):
    for case in _eval_incidents():
        incident = IncidentCreatedPayload.model_validate(case["incident"])
        for tenant in ("acme", "globex"):  # also the "wrong" tenant: an acme incident searched as globex
            items = await retrieve_evidence(
                both_tenants, FakeEmbedder(), FakeReranker(), tenant_id=tenant, incident=incident
            )
            assert items
            assert {item.tenant_id for item in items} == {tenant}


async def test_incident_text_copied_from_a_globex_chunk_still_returns_only_acme(both_tenants):
    async with both_tenants.connect() as conn:
        globex_runbook = (
            await conn.execute(
                text("SELECT content FROM worker.chunks WHERE tenant_id = 'globex' AND source_type = 'runbook' LIMIT 1")
            )
        ).scalar_one()
    incident = load_eval_incident("acme", scenario="db_pool_exhausted").model_copy(
        update={"title": globex_runbook, "description": None}
    )

    items = await retrieve_evidence(both_tenants, FakeEmbedder(), FakeReranker(), tenant_id="acme", incident=incident)

    assert {item.tenant_id for item in items} == {"acme"}


async def test_items_are_labelled_unique_and_capped(both_tenants):
    incident = load_eval_incident("globex", scenario="db_pool_exhausted")
    items = await retrieve_evidence(
        both_tenants, FakeEmbedder(), FakeReranker(), tenant_id="globex", incident=incident, final_k=6
    )

    assert [item.label for item in items] == [f"C{n}" for n in range(1, len(items) + 1)]
    assert len(items) == 6
    assert len({item.chunk_id for item in items}) == len(items)
    assert label_map(items) == {item.label: item.chunk_id for item in items}
    scores = [item.rerank_score for item in items]
    assert scores == sorted(scores, reverse=True)
    assert all(item.rrf_score > 0 for item in items)


async def test_logs_and_metrics_come_from_the_affected_service_and_time_window(both_tenants):
    incident = load_eval_incident("globex", scenario="db_pool_exhausted")
    items = await retrieve_evidence(
        both_tenants, FakeEmbedder(), FakeReranker(), tenant_id="globex", incident=incident, final_k=20, retrieve_k=50
    )
    timed = [item for item in items if item.source_type in ("log", "metric")]
    assert timed
    for item in timed:
        assert item.service == "inventory-service"
        assert incident.createdAt - retrieval.DEFAULT_WINDOW_BEFORE <= item.ts < incident.createdAt + retrieval.DEFAULT_WINDOW_AFTER


@pytest.mark.parametrize(("retrieve_k", "final_k"), [(0, 6), (51, 6), (20, 0), (20, 21)])
async def test_k_out_of_range_raises_before_any_query(both_tenants, retrieve_k, final_k):
    incident = load_eval_incident("acme", scenario="db_pool_exhausted")
    with pytest.raises(ValueError):
        await retrieve_evidence(
            both_tenants, FakeEmbedder(), FakeReranker(), tenant_id="acme", incident=incident,
            retrieve_k=retrieve_k, final_k=final_k,
        )


async def test_a_search_that_leaks_another_tenant_fails_loudly(both_tenants, monkeypatch):
    """Defence in depth: if a future change broke the SQL tenant filter, the pipeline must raise."""
    real_search = retrieval.search_chunks

    async def leaking_search(engine, **kwargs):
        rows = await real_search(engine, **kwargs)
        return rows + [{**rows[0], "chunk_id": uuid.uuid4(), "tenant_id": "globex"}] if rows else rows

    monkeypatch.setattr(retrieval, "search_chunks", leaking_search)
    incident = load_eval_incident("acme", scenario="db_pool_exhausted")

    with pytest.raises(TenantIsolationError):
        await retrieve_evidence(both_tenants, FakeEmbedder(), FakeReranker(), tenant_id="acme", incident=incident)


def test_cli_loader_refuses_another_tenants_incident():
    globex_incident_id = next(c["incident"]["incidentId"] for c in _eval_incidents() if c["tenantId"] == "globex")
    with pytest.raises(SystemExit):
        load_eval_incident("acme", incident_id=globex_incident_id)
