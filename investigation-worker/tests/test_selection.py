from dataclasses import dataclass

import pytest

from app.selection import DEFAULT_SOURCE_CAPS, apply_source_caps, validate_k


@dataclass(frozen=True)
class Chunk:
    name: str
    source_type: str
    rerank_score: float


def _names(chunks) -> list[str]:
    return [chunk.name for chunk in chunks]


def test_logs_cannot_crowd_out_runbooks():
    # Eight log windows score higher than every runbook.
    logs = [Chunk(f"log{i}", "log", 10 - i) for i in range(8)]
    runbooks = [Chunk("rb1", "runbook", 1.0), Chunk("rb2", "runbook", 0.5)]
    incidents = [Chunk("inc1", "incident", 0.4)]
    metrics = [Chunk("met1", "metric", 0.3)]

    selected = apply_source_caps(logs + runbooks + incidents + metrics, DEFAULT_SOURCE_CAPS, final_k=6)

    assert _names(selected) == ["log0", "log1", "log2", "rb1", "rb2", "inc1"]


def test_unused_slots_flow_to_the_next_best_chunks():
    # No metrics and only one runbook: their unused slots go to the best remaining chunks (more logs).
    chunks = [Chunk(f"log{i}", "log", 10 - i) for i in range(6)] + [Chunk("rb1", "runbook", 0.1)]

    selected = apply_source_caps(chunks, DEFAULT_SOURCE_CAPS, final_k=6)

    assert _names(selected) == ["log0", "log1", "log2", "log3", "log4", "rb1"]


def test_result_is_ordered_by_rerank_score():
    chunks = [Chunk("met", "metric", 0.2), Chunk("rb", "runbook", 0.9), Chunk("log", "log", 0.5)]
    assert _names(apply_source_caps(chunks, DEFAULT_SOURCE_CAPS, final_k=3)) == ["rb", "log", "met"]


def test_fewer_chunks_than_final_k_returns_them_all():
    chunks = [Chunk("a", "log", 1.0), Chunk("b", "runbook", 2.0)]
    assert _names(apply_source_caps(chunks, DEFAULT_SOURCE_CAPS, final_k=6)) == ["b", "a"]
    assert apply_source_caps([], DEFAULT_SOURCE_CAPS, final_k=6) == []


def test_type_without_a_cap_only_gets_leftover_slots():
    chunks = [Chunk("x", "email", 9.0), Chunk("log", "log", 1.0)]
    assert _names(apply_source_caps(chunks, {"log": 1}, final_k=1)) == ["log"]
    assert _names(apply_source_caps(chunks, {"log": 1}, final_k=2)) == ["x", "log"]


def test_equal_scores_keep_input_order():
    chunks = [Chunk("first", "log", 1.0), Chunk("second", "log", 1.0)]
    assert _names(apply_source_caps(chunks, DEFAULT_SOURCE_CAPS, final_k=2)) == ["first", "second"]


@pytest.mark.parametrize("final_k", [0, 21, -1])
def test_final_k_out_of_range_raises(final_k):
    with pytest.raises(ValueError, match="final_k"):
        apply_source_caps([], DEFAULT_SOURCE_CAPS, final_k=final_k)


def test_negative_cap_raises():
    with pytest.raises(ValueError, match="caps"):
        apply_source_caps([], {"log": -1}, final_k=3)


@pytest.mark.parametrize(
    ("retrieve_k", "final_k", "message"),
    [(0, 6, "retrieve_k"), (51, 6, "retrieve_k"), (20, 0, "final_k"), (20, 21, "final_k")],
)
def test_validate_k_rejects_out_of_range(retrieve_k, final_k, message):
    with pytest.raises(ValueError, match=message):
        validate_k(retrieve_k=retrieve_k, final_k=final_k)


def test_validate_k_accepts_the_bounds():
    validate_k(retrieve_k=1, final_k=1)
    validate_k(retrieve_k=50, final_k=20)
