import uuid
from datetime import UTC, datetime, timedelta

from app.events import IncidentCreatedPayload
from app.query_builder import build_queries, incident_text, to_keyword_query

CREATED = datetime(2026, 9, 11, 1, 9, tzinfo=UTC)


def _incident(**overrides) -> IncidentCreatedPayload:
    fields = {
        "incidentId": uuid.uuid4(),
        "title": "inventory-service requests timing out",
        "description": "Timeouts talking to ledger-db.",
        "severity": "HIGH",
        "status": "OPEN",
        "affectedService": "inventory-service",
        "createdAt": CREATED,
    } | overrides
    return IncidentCreatedPayload(**fields)


def test_one_spec_per_evidence_type():
    assert [spec.source_type for spec in build_queries(_incident())] == ["log", "metric", "runbook", "incident"]


def test_every_spec_uses_title_and_description():
    for spec in build_queries(_incident()):
        assert spec.text == "inventory-service requests timing out\nTimeouts talking to ledger-db."


def test_logs_and_metrics_get_service_and_default_time_window():
    log, metric, _, _ = build_queries(_incident())
    for spec in (log, metric):
        assert spec.service == "inventory-service"
        assert spec.time_from == CREATED - timedelta(hours=2)
        assert spec.time_to == CREATED + timedelta(minutes=30)


def test_runbooks_and_past_incidents_have_no_service_or_time_filter():
    _, _, runbook, incident = build_queries(_incident())
    for spec in (runbook, incident):
        assert (spec.service, spec.time_from, spec.time_to) == (None, None, None)


def test_window_is_configurable():
    log = build_queries(_incident(), window_before=timedelta(minutes=15), window_after=timedelta(minutes=5))[0]
    assert (log.time_from, log.time_to) == (CREATED - timedelta(minutes=15), CREATED + timedelta(minutes=5))


def test_unknown_affected_service_means_no_service_filter():
    log = build_queries(_incident(affectedService=None))[0]
    assert log.service is None
    assert log.time_from is not None  # the time window still applies


def test_missing_description_uses_the_title_only():
    assert incident_text(_incident(description=None)) == "inventory-service requests timing out"


def test_keyword_query_ors_the_words_and_keeps_technical_tokens():
    query = to_keyword_query("HikariPool timeouts on orders-db v4.1.2, HikariPool again!")
    assert query == "hikaripool or timeouts or on or orders-db or v4.1.2 or again"


def test_keyword_query_drops_the_operator_word_or_and_single_letters():
    assert to_keyword_query("cache or a DB") == "cache or db"
    assert to_keyword_query("a b") == ""
