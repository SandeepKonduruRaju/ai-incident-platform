from datetime import UTC, datetime

from app.chunking import chunk_dataset, chunk_id, chunk_incident, chunk_logs, chunk_metric, chunk_runbook

RUNBOOK = {
    "source_id": "RB-acme-db_pool_exhausted",
    "tenant_id": "acme",
    "source_type": "runbook",
    "service": "payment-service",
    "title": "Database connection pool exhausted (payment-service)",
    "content": (
        "# Runbook: payment-service database connection pool exhausted\n\n"
        "Owner: #acme-oncall\n\n"
        "## Symptoms\n- Pool at maximum.\n\n"
        "## Empty section\n\n"
        "## Diagnosis\n1. Count sessions.\n2. Check locks.\n\n"
        "## Mitigation\n- Kill idle transactions.\n"
    ),
}


def _log(tenant, scenario, index, service, ts, message="m"):
    return {
        "source_id": f"LOG-{tenant}-{scenario}-{index:03d}",
        "tenant_id": tenant,
        "source_type": "log",
        "service": service,
        "ts": ts,
        "level": "INFO",
        "message": message,
    }


# ---------------------------------------------------------------- runbooks


def test_runbook_is_split_by_level_two_headings_and_empty_sections_are_skipped():
    chunks = chunk_runbook(RUNBOOK)
    sections = [chunk.content.split("\n", 1)[0].split(" — ", 1)[1] for chunk in chunks]
    assert sections == ["Overview", "Symptoms", "Diagnosis", "Mitigation"]
    assert [chunk.chunk_index for chunk in chunks] == [0, 1, 2, 3]


def test_runbook_title_is_prepended_to_every_chunk():
    for chunk in chunk_runbook(RUNBOOK):
        assert chunk.content.startswith(f"{RUNBOOK['title']} — ")


def test_runbook_chunk_body_stays_inside_its_section():
    diagnosis = chunk_runbook(RUNBOOK)[2]
    assert diagnosis.content == f"{RUNBOOK['title']} — Diagnosis\n1. Count sessions.\n2. Check locks."


def test_runbook_overview_drops_the_h1_line():
    overview = chunk_runbook(RUNBOOK)[0]
    assert "# Runbook:" not in overview.content
    assert "Owner: #acme-oncall" in overview.content


def test_runbook_chunks_carry_metadata():
    for chunk in chunk_runbook(RUNBOOK):
        assert (chunk.tenant_id, chunk.source_type, chunk.service, chunk.source_id, chunk.ts) == (
            "acme",
            "runbook",
            "payment-service",
            "RB-acme-db_pool_exhausted",
            None,
        )


# ---------------------------------------------------------------- ids


def test_ids_are_deterministic_and_depend_on_tenant_source_and_index():
    first = [chunk.id for chunk in chunk_runbook(RUNBOOK)]
    second = [chunk.id for chunk in chunk_runbook(RUNBOOK)]
    assert first == second
    assert len(set(first)) == len(first)
    assert first[1] == chunk_id("acme", "RB-acme-db_pool_exhausted", 1)
    # The same source_id and index under another tenant is a different row.
    assert chunk_id("globex", "RB-acme-db_pool_exhausted", 1) != first[1]


# ---------------------------------------------------------------- logs


def test_logs_are_windowed_per_tenant_service_and_scenario():
    logs = [_log("acme", "noise", i, "payment-service", f"2026-09-01T00:{i:02d}:00Z") for i in range(23)]
    logs += [_log("acme", "db_pool_exhausted", i, "payment-service", f"2026-09-02T00:{i:02d}:00Z") for i in range(3)]
    logs += [_log("globex", "noise", i, "payment-service", f"2026-09-01T00:{i:02d}:00Z") for i in range(2)]

    chunks = chunk_logs(logs, window_size=10)
    lines_per_window: dict[str, list[int]] = {}
    for chunk in chunks:
        # Every line after the "Logs from <service>:" header is one log line.
        lines_per_window.setdefault(chunk.source_id, []).append(chunk.content.count("\n"))

    assert lines_per_window == {
        "LOG-acme-db_pool_exhausted-payment-service": [3],
        "LOG-acme-noise-payment-service": [10, 10, 3],
        "LOG-globex-noise-payment-service": [2],
    }
    assert {chunk.source_type for chunk in chunks} == {"log"}


def test_log_window_is_sorted_by_time_and_takes_the_first_timestamp():
    logs = [
        _log("acme", "bad_deploy", 2, "checkout-api", "2026-09-03T10:05:00Z", "second"),
        _log("acme", "bad_deploy", 1, "checkout-api", "2026-09-03T10:00:00Z", "first"),
    ]
    [chunk] = chunk_logs(logs)
    assert chunk.content == (
        "Logs from checkout-api:\n2026-09-03T10:00:00Z INFO first\n2026-09-03T10:05:00Z INFO second"
    )
    assert chunk.ts == datetime(2026, 9, 3, 10, 0, tzinfo=UTC)
    assert (chunk.tenant_id, chunk.service, chunk.chunk_index) == ("acme", "checkout-api", 0)


def test_different_services_in_the_same_scenario_are_separate_windows():
    logs = [
        _log("acme", "noise", 1, "auth-service", "2026-09-01T00:00:00Z"),
        _log("acme", "noise", 2, "checkout-api", "2026-09-01T00:01:00Z"),
    ]
    assert sorted(chunk.source_id for chunk in chunk_logs(logs)) == [
        "LOG-acme-noise-auth-service",
        "LOG-acme-noise-checkout-api",
    ]


# ---------------------------------------------------------------- metrics, incidents, dataset


def test_metric_and_incident_are_one_chunk_each():
    metric = {
        "source_id": "MET-acme-x",
        "tenant_id": "acme",
        "service": "checkout-api",
        "ts": "2026-09-12T06:27:00Z",
        "summary": "p99 latency up",
    }
    incident = {
        "source_id": "INC-acme-x-1",
        "tenant_id": "acme",
        "service": "checkout-api",
        "ts": "2025-08-24T00:00:00Z",
        "title": "T",
        "root_cause": "R",
        "fix": "F",
    }

    [m] = chunk_metric(metric)
    [i] = chunk_incident(incident)
    assert (m.source_type, m.chunk_index, m.content) == ("metric", 0, "p99 latency up")
    assert m.ts == datetime(2026, 9, 12, 6, 27, tzinfo=UTC)
    assert (i.source_type, i.chunk_index) == ("incident", 0)
    assert i.content == "Past incident: T\nRoot cause: R\nFix: F"


def test_chunking_the_real_synthetic_data_gives_unique_ids_and_all_types():
    from app.ingest import load_dataset

    chunks = chunk_dataset(**load_dataset())
    assert len({chunk.id for chunk in chunks}) == len(chunks)
    assert {chunk.source_type for chunk in chunks} == {"runbook", "log", "metric", "incident"}
    assert all(chunk.content.strip() for chunk in chunks)
