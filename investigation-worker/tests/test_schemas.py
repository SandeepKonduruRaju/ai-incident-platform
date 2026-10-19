import json

import pytest
from pydantic import ValidationError

from app.schemas import INSUFFICIENT_EVIDENCE_RESULT, Finding, InvestigationResult, result_json_schema


def _valid() -> dict:
    return {
        "root_cause": {"text": "Pool exhausted [C1]", "citations": ["C1"]},
        "contributing_factors": [{"text": "Slow queries [C2]", "citations": ["C2"]}],
        "remediation": [{"text": "Kill idle transactions [C3]", "citations": ["C3"]}],
        "confidence": "high",
        "summary": "The pool was exhausted [C1].",
    }


def test_valid_result_parses():
    result = InvestigationResult.model_validate(_valid())
    assert result.all_citations() == ["C1", "C2", "C3"]


def test_extra_field_is_rejected():
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        InvestigationResult.model_validate(_valid() | {"severity": "high"})
    with pytest.raises(ValidationError):
        Finding.model_validate({"text": "x", "citations": ["C1"], "source": "C1"})


def test_finding_without_citation_is_rejected():
    data = _valid()
    data["root_cause"]["citations"] = []
    with pytest.raises(ValidationError, match="at least 1 item"):
        InvestigationResult.model_validate(data)


def test_finding_text_must_not_be_blank():
    data = _valid()
    data["root_cause"]["text"] = "   "
    with pytest.raises(ValidationError):
        InvestigationResult.model_validate(data)


def test_no_root_cause_requires_low_confidence():
    data = _valid() | {"root_cause": None, "confidence": "medium"}
    with pytest.raises(ValidationError, match='confidence must be "low"'):
        InvestigationResult.model_validate(data)
    InvestigationResult.model_validate(data | {"confidence": "low"})  # fine


def test_unknown_confidence_value_is_rejected():
    with pytest.raises(ValidationError):
        InvestigationResult.model_validate(_valid() | {"confidence": "certain"})


def test_json_schema_is_generated_from_the_model_and_api_compatible():
    schema = result_json_schema()
    assert schema["additionalProperties"] is False
    assert schema["$defs"]["Finding"]["additionalProperties"] is False
    assert set(schema["required"]) == {"root_cause", "contributing_factors", "remediation", "confidence", "summary"}
    assert schema["properties"]["confidence"]["enum"] == ["high", "medium", "low"]
    # Constraints the structured-outputs API does not support are stripped (Pydantic still enforces them).
    text = json.dumps(schema)
    assert "minLength" not in text and "minItems" not in text


def test_insufficient_evidence_result_is_itself_valid():
    assert INSUFFICIENT_EVIDENCE_RESULT.root_cause is None
    assert INSUFFICIENT_EVIDENCE_RESULT.confidence == "low"
    InvestigationResult.model_validate(INSUFFICIENT_EVIDENCE_RESULT.model_dump())
