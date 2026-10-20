"""Pure parts of the graph: validate_output and the routing functions (no LLM, no database)."""

import json
import uuid

import pytest

from app.graph import (
    MAX_OUTPUT_ATTEMPTS,
    route_after_llm,
    route_after_retrieve,
    route_after_validate,
    validate_output,
)

LABELS = {"C1": uuid.uuid4(), "C2": uuid.uuid4(), "C3": uuid.uuid4()}


def _answer(**overrides) -> str:
    return json.dumps(
        {
            "root_cause": {"text": "Pool exhausted [C1]", "citations": ["C1"]},
            "contributing_factors": [],
            "remediation": [{"text": "Kill idle sessions [C3]", "citations": ["C3"]}],
            "confidence": "medium",
            "summary": "Pool exhaustion [C1].",
        }
        | overrides
    )


# ---------------------------------------------------------------- validate_output


def test_valid_output():
    result, error = validate_output(_answer(), "end_turn", LABELS)
    assert error is None
    assert result["root_cause"]["citations"] == ["C1"]


def test_bad_json():
    result, error = validate_output('{"root_cause": ', "end_turn", LABELS)
    assert result is None
    assert error.startswith("schema validation failed") and "Invalid JSON" in error


def test_schema_violation_names_the_field():
    result, error = validate_output(_answer(confidence="certain"), "end_turn", LABELS)
    assert result is None and "confidence" in error


def test_unknown_citation_in_citations_names_the_bad_label():
    bad = _answer(root_cause={"text": "Pool exhausted", "citations": ["C1", "C9"]})
    result, error = validate_output(bad, "end_turn", LABELS)
    assert result is None
    assert "C9" in error and "valid labels are: C1, C2, C3" in error


def test_unknown_citation_inline_in_text_is_also_caught():
    result, error = validate_output(_answer(summary="See [C7]."), "end_turn", LABELS)
    assert result is None and "C7" in error


def test_max_tokens_stop_reason_is_invalid_even_if_the_text_parses():
    result, error = validate_output(_answer(), "max_tokens", LABELS)
    assert result is None and "max_tokens" in error


def test_refusal_is_invalid():
    result, error = validate_output(_answer(), "refusal", LABELS)
    assert result is None and "declined" in error


def test_no_root_cause_with_high_confidence_is_invalid():
    result, error = validate_output(_answer(root_cause=None, confidence="high"), "end_turn", LABELS)
    assert result is None and "confidence" in error


# ---------------------------------------------------------------- routing


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ({"evidence": ["item"]}, "analyse"),
        ({"evidence": []}, "save_insufficient"),
        ({}, "save_insufficient"),
        ({"evidence": ["item"], "fatal": "time budget exceeded"}, "save_failed"),
    ],
)
def test_route_after_retrieve(state, expected):
    assert route_after_retrieve(state) == expected


@pytest.mark.parametrize(
    ("state", "expected"),
    [({"raw_output": "{}"}, "validate"), ({"fatal": "LLM unavailable"}, "save_failed")],
)
def test_route_after_llm(state, expected):
    assert route_after_llm(state) == expected


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ({"result": {"summary": "ok"}, "attempts": 1}, "save"),
        ({"result": {"summary": "ok"}, "attempts": 2}, "save"),
        ({"result": None, "error": "bad", "attempts": 1}, "repair"),
        ({"result": None, "error": "bad", "attempts": 2}, "save_failed"),
        ({"result": None, "error": "bad", "attempts": 5}, "save_failed"),
    ],
)
def test_route_after_validate_and_the_attempts_bound(state, expected):
    assert route_after_validate(state) == expected


def test_attempts_bound_is_two():
    assert MAX_OUTPUT_ATTEMPTS == 2
