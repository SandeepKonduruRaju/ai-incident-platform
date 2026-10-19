"""Pure parts of the internal read API (no database)."""

import pytest
from pydantic import SecretStr

from app.config import Settings
from app.internal_api import (
    FAILURE_REASON_CHARS,
    labels_used,
    require_internal_token_configured,
    short_reason,
)


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, database_url="postgresql+asyncpg://u:p@h/db", **overrides)


def test_labels_used_collects_citations_and_inline_labels_in_first_use_order():
    result = {
        "root_cause": {"text": "Pool exhausted [C2]", "citations": ["C2", "C1"]},
        "contributing_factors": [{"text": "Slow queries", "citations": ["C3"]}],
        "remediation": [{"text": "Kill sessions [C4]", "citations": ["C1"]}],
        "confidence": "high",
        "summary": "See [C5] and [C2].",
    }
    assert labels_used(result) == ["C2", "C1", "C3", "C4", "C5"]


def test_labels_used_without_result():
    assert labels_used(None) == []
    assert labels_used({"root_cause": None, "contributing_factors": [], "remediation": [], "summary": "x"}) == []


def test_short_reason_keeps_the_first_line_only_and_truncates():
    assert short_reason(None) is None
    assert short_reason("time budget exceeded") == "time budget exceeded"
    assert short_reason("first line\nTraceback (most recent call last):\n  File ...") == "first line"
    assert len(short_reason("x" * 1000)) == FAILURE_REASON_CHARS


def test_startup_refuses_without_internal_token():
    with pytest.raises(RuntimeError, match="INTERNAL_API_TOKEN is not set"):
        require_internal_token_configured(_settings())
    with pytest.raises(RuntimeError):
        require_internal_token_configured(_settings(internal_api_token="   "))  # blank = not set
    require_internal_token_configured(_settings(internal_api_token="dev-token"))  # fine


def test_internal_token_is_a_secret():
    settings = _settings(internal_api_token="dev-only-secret-value")
    assert isinstance(settings.internal_api_token, SecretStr)
    assert "dev-only-secret-value" not in repr(settings)
