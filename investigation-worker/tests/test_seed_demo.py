"""The demo seed and data, without Docker or the live stack: payloads, anchored evidence, idempotency, dry run.

FakeApi stands in for incident-service (dev token, list with pages, create with Idempotency-Key, status PATCH).
"""

import re
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.chunking import chunk_dataset
from app.demo_data import DEMO_INCIDENTS, TENANT, build_dataset
from app.query_builder import DEFAULT_WINDOW_AFTER, DEFAULT_WINDOW_BEFORE
from app.seed_demo import SeedError, idempotency_key, incident_payload, seed_incidents

TOKEN = "fake-token-must-never-be-printed"
ANCHOR = datetime(2026, 10, 27, 14, 0, tzinfo=UTC)


class FakeApi:
    def __init__(self, existing: list[str] = (), page_size: int = 100, reachable: bool = True):
        self.incidents: dict[str, dict] = {}
        self.by_key: dict[str, str] = {}
        self.calls: list[tuple[str, str]] = []
        self.page_size = page_size
        self.reachable = reachable
        for title in existing:
            self._add({"title": title})

    def _add(self, body: dict) -> dict:
        incident = {"id": str(uuid.uuid4()), "status": "OPEN", **body}
        self.incidents[incident["id"]] = incident
        return incident

    def request(self, method, path, *, body=None, token=None, headers=None):
        self.calls.append((method, path))
        if not self.reachable:
            raise SeedError(f"{method} {path} -> cannot reach the API")
        if path == "/api/v1/dev/token":
            assert body == {"subject": "demo-seed", "tenantId": TENANT, "roles": ["RESPONDER"]}
            return {"accessToken": TOKEN, "tokenType": "Bearer", "expiresIn": 3600}
        assert token == TOKEN
        if method == "GET":
            page = int(re.search(r"page=(\d+)", path).group(1))
            items = list(self.incidents.values())
            chunk = items[page * self.page_size : (page + 1) * self.page_size]
            return {"items": chunk, "totalPages": max(1, -(-len(items) // self.page_size))}
        if method == "POST":
            key = headers["Idempotency-Key"]
            if key in self.by_key:
                return self.incidents[self.by_key[key]]
            incident = self._add(body)
            self.by_key[key] = incident["id"]
            return incident
        if method == "PATCH":
            incident_id = path.split("/")[4]
            self.incidents[incident_id]["status"] = body["status"]
            return self.incidents[incident_id]
        raise AssertionError(f"unexpected {method} {path}")

    def writes(self) -> list[tuple[str, str]]:
        return [call for call in self.calls if call[0] in ("POST", "PATCH") and call[1] != "/api/v1/dev/token"]


# ---------------------------------------------------------------- incidents and payloads


def test_eight_realistic_incidents_with_mixed_severities_statuses_and_services():
    assert len(DEMO_INCIDENTS) == 8
    assert {i.severity for i in DEMO_INCIDENTS} == {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
    assert {i.status for i in DEMO_INCIDENTS} == {"OPEN", "INVESTIGATING", "MITIGATED", "RESOLVED"}
    assert len({i.service for i in DEMO_INCIDENTS}) == 8  # one service per scenario: log searches never mix
    assert len({i.title for i in DEMO_INCIDENTS}) == 8
    for incident in DEMO_INCIDENTS:
        assert incident.title[0].isupper() or incident.title.split()[0].islower()  # sentence case (or a service name)
        assert not re.search(r"\b(test|e2e)\b", f"{incident.title} {incident.description}", re.IGNORECASE)
        assert len(incident.title) <= 255 and len(incident.description) <= 2000  # the API's limits


def test_payload_matches_create_incident_request():
    incident = DEMO_INCIDENTS[0]
    assert incident_payload(incident) == {
        "title": "Payment requests failing after configuration deploy",
        "description": incident.description,
        "severity": "CRITICAL",
        "affectedService": "payment-service",
    }


def test_idempotency_keys_are_fixed_per_scenario_and_distinct():
    keys = [idempotency_key(i) for i in DEMO_INCIDENTS]
    assert keys == [idempotency_key(i) for i in DEMO_INCIDENTS]
    assert len(set(keys)) == 8


# ---------------------------------------------------------------- evidence


def test_evidence_is_anchored_inside_each_incidents_retrieval_window():
    dataset = build_dataset(ANCHOR)
    assert all(doc["tenant_id"] == TENANT for docs in dataset.values() for doc in docs)
    # The seed reports the incidents right after ingesting: createdAt is about ANCHOR.
    window_from, window_to = ANCHOR - DEFAULT_WINDOW_BEFORE, ANCHOR + DEFAULT_WINDOW_AFTER
    for incident in DEMO_INCIDENTS:
        timed = [d for d in dataset["logs"] + dataset["metrics"] if d["service"] == incident.service]
        assert timed, incident.scenario
        for doc in timed:
            assert window_from <= datetime.fromisoformat(doc["ts"]) <= window_to, doc["source_id"]


def test_the_confident_scenario_has_strong_evidence_and_the_abstaining_one_has_none():
    dataset = build_dataset(ANCHOR)
    pool_logs = [d["message"] for d in dataset["logs"] if d["service"] == "payment-service"]
    assert any("maximum-pool-size: 40 -> 10" in m for m in pool_logs)
    assert any("Connection is not available" in m for m in pool_logs)
    assert any(d["service"] == "payment-service" for d in dataset["runbooks"])
    assert any(d["service"] == "payment-service" for d in dataset["incidents"])

    checkout = [d for d in dataset["logs"] if d["service"] == "checkout-api"]
    assert checkout and all(d["level"] == "INFO" for d in checkout)  # healthy traffic only
    assert not any(d["service"] == "checkout-api" for d in dataset["runbooks"] + dataset["incidents"])


def test_evidence_goes_through_the_normal_chunking():
    chunks = chunk_dataset(**build_dataset(ANCHOR))
    types = {c.source_type for c in chunks}
    assert types == {"log", "metric", "runbook", "incident"}
    assert all(c.tenant_id == TENANT for c in chunks)
    # Deterministic ids: re-seeding later updates the same rows (with new timestamps) instead of duplicating them.
    later = chunk_dataset(**build_dataset(ANCHOR + timedelta(days=3)))
    assert {c.id for c in chunks} == {c.id for c in later}


# ---------------------------------------------------------------- seeding


def test_seed_creates_the_incidents_sets_statuses_and_never_prints_the_token():
    api, lines = FakeApi(), []
    result = seed_incidents(api, out=lines.append)

    assert len(result.created) == 8 and result.skipped == []
    statuses = {i["title"]: i["status"] for i in api.incidents.values()}
    assert statuses == {i.title: i.status for i in DEMO_INCIDENTS}
    patches = [c for c in api.calls if c[0] == "PATCH"]
    assert len(patches) == sum(1 for i in DEMO_INCIDENTS if i.status != "OPEN")  # OPEN needs no PATCH
    output = "\n".join(lines)
    assert TOKEN not in output
    for incident_id, title in result.created:
        assert incident_id in output and title in output


def test_seed_is_idempotent_and_skips_existing_titles():
    api = FakeApi()
    seed_incidents(api, out=lambda _: None)
    writes_after_first = len(api.writes())

    result = seed_incidents(api, out=lambda _: None)

    assert result.created == [] and len(result.skipped) == 8
    assert len(api.writes()) == writes_after_first  # the second run wrote nothing
    assert len(api.incidents) == 8


def test_existing_titles_are_found_on_any_page():
    first = DEMO_INCIDENTS[0].title
    api = FakeApi(existing=[f"Older incident {n}" for n in range(5)] + [first], page_size=2)

    result = seed_incidents(api, out=lambda _: None)

    assert [title for _, title in result.skipped] == [first]
    assert len(result.created) == 7


def test_dry_run_writes_nothing():
    api, lines = FakeApi(existing=[DEMO_INCIDENTS[1].title]), []

    result = seed_incidents(api, dry_run=True, out=lines.append)

    assert api.writes() == []
    assert len(result.planned) == 7 and len(result.skipped) == 1
    assert sum(line.startswith("would create") for line in lines) == 7
    assert TOKEN not in "\n".join(lines)


def test_dry_run_without_the_api_still_prints_the_plan_but_a_real_run_fails():
    lines: list[str] = []
    result = seed_incidents(FakeApi(reachable=False), dry_run=True, out=lines.append)
    assert len(result.planned) == 8
    assert "could not check existing incidents" in lines[0]

    with pytest.raises(SeedError):
        seed_incidents(FakeApi(reachable=False), out=lambda _: None)
