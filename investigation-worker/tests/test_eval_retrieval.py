import pytest

from app.eval_retrieval import is_relevant, score

GOLDEN = {
    "logs": ["LOG-acme-db_pool_exhausted-001"],
    "metrics": ["MET-acme-db_pool_exhausted"],
    "runbooks": ["RB-acme-db_pool_exhausted"],
    "incidents": ["INC-acme-db_pool_exhausted-1"],
}


def test_log_windows_match_by_scenario_prefix():
    assert is_relevant("log", "LOG-acme-db_pool_exhausted-payment-service", GOLDEN, "acme", "db_pool_exhausted")
    assert not is_relevant("log", "LOG-acme-noise-payment-service", GOLDEN, "acme", "db_pool_exhausted")


def test_score_hit_mrr_relevant_count_and_types():
    results = [
        ("log", "LOG-acme-noise-payment-service"),
        ("runbook", "RB-acme-db_pool_exhausted"),
        ("runbook", "RB-acme-db_pool_exhausted"),
        ("metric", "MET-acme-db_pool_exhausted"),
    ]
    metrics = score(results, GOLDEN, "acme", "db_pool_exhausted")
    assert metrics.hit == 1
    assert metrics.reciprocal_rank == pytest.approx(0.5)
    assert metrics.relevant == 3
    assert metrics.types == 2


def test_score_without_relevant_results():
    metrics = score([("log", "LOG-acme-noise-x")], GOLDEN, "acme", "db_pool_exhausted")
    assert (metrics.hit, metrics.reciprocal_rank, metrics.relevant, metrics.types) == (0, 0.0, 0, 0)
