"""The investigation result: the one and only definition of what the LLM must return.

The same Pydantic models (1) generate the JSON schema sent to the API (structured outputs) and
(2) validate the answer afterwards. One source of truth: the prompt, the API constraint and our
validation cannot drift apart.
"""

from copy import deepcopy
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

# Keywords the structured-outputs API does not support (it ignores or rejects them). We strip them
# from the schema we SEND; Pydantic still enforces them when we validate the answer.
_UNSUPPORTED_KEYWORDS = {"minLength", "maxLength", "minItems", "maxItems", "minimum", "maximum", "pattern"}


class _Strict(BaseModel):
    # extra="forbid": an unexpected field is an error (and becomes additionalProperties: false in the schema).
    model_config = ConfigDict(extra="forbid")


class Finding(_Strict):
    text: NonEmptyText
    citations: list[NonEmptyText] = Field(min_length=1, description='Evidence labels, e.g. ["C1", "C3"]')


class InvestigationResult(_Strict):
    root_cause: Finding | None
    contributing_factors: list[Finding]
    remediation: list[Finding]
    confidence: Literal["high", "medium", "low"]
    summary: str

    @model_validator(mode="after")
    def _no_root_cause_means_low_confidence(self) -> "InvestigationResult":
        if self.root_cause is None and self.confidence != "low":
            raise ValueError('confidence must be "low" when root_cause is null')
        return self

    def all_citations(self) -> list[str]:
        findings = [self.root_cause, *self.contributing_factors, *self.remediation]
        return [label for finding in findings if finding is not None for label in finding.citations]


def _strip_unsupported(node: Any) -> Any:
    if isinstance(node, dict):
        return {key: _strip_unsupported(value) for key, value in node.items() if key not in _UNSUPPORTED_KEYWORDS}
    if isinstance(node, list):
        return [_strip_unsupported(value) for value in node]
    return node


def result_json_schema() -> dict[str, Any]:
    """JSON schema for the API's structured output, generated from InvestigationResult."""
    return _strip_unsupported(deepcopy(InvestigationResult.model_json_schema()))


INSUFFICIENT_EVIDENCE_RESULT = InvestigationResult(
    root_cause=None,
    contributing_factors=[],
    remediation=[],
    confidence="low",
    summary="insufficient evidence",
)
