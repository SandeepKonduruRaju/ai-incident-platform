"""LLM layer without network: SDK error mapping, FakeLLM, the factory's fail-fast."""

import json

import anthropic
import httpx2
import pytest
from pydantic import SecretStr

from app.config import Settings
from app.errors import ErrorCategory, LLMConfigError, PermanentLLMError, TransientLLMError, classify
from app.llm import AnthropicLLM, FakeLLM, LLMResponse, build_llm, default_fake_answer, map_api_error

REQUEST = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


def _status_error(cls, status: int, headers: dict[str, str] | None = None, error_type: str = "api_error"):
    body = {"type": "error", "error": {"type": error_type, "message": "test"}}
    response = httpx2.Response(status, request=REQUEST, headers=headers or {}, json=body)
    return cls("test", response=response, body=body)


# ---------------------------------------------------------------- error mapping


@pytest.mark.parametrize(
    "exc",
    [
        _status_error(anthropic.AuthenticationError, 401, error_type="authentication_error"),
        _status_error(anthropic.PermissionDeniedError, 403, error_type="permission_error"),
        _status_error(anthropic.NotFoundError, 404, error_type="not_found_error"),
    ],
)
def test_auth_and_config_errors_are_llm_config_errors(exc):
    mapped = map_api_error(exc)
    assert isinstance(mapped, LLMConfigError)
    # The message tells the operator what to fix (the key or the model id).
    assert "ANTHROPIC_API_KEY" in str(mapped) or "LLM_MODEL" in str(mapped)


def test_rate_limit_is_transient_and_keeps_retry_after():
    mapped = map_api_error(_status_error(anthropic.RateLimitError, 429, {"retry-after": "7"}, "rate_limit_error"))
    assert isinstance(mapped, TransientLLMError)
    assert mapped.retry_after == 7.0
    no_header = map_api_error(_status_error(anthropic.RateLimitError, 429, error_type="rate_limit_error"))
    assert no_header.retry_after is None


@pytest.mark.parametrize(
    "exc",
    [
        _status_error(anthropic.InternalServerError, 500),
        _status_error(anthropic.OverloadedError, 529, error_type="overloaded_error"),
        _status_error(anthropic.ServiceUnavailableError, 503),
        anthropic.APITimeoutError(request=REQUEST),
        anthropic.APIConnectionError(request=REQUEST),
    ],
)
def test_server_and_network_errors_are_transient(exc):
    mapped = map_api_error(exc)
    assert isinstance(mapped, TransientLLMError)
    assert classify(mapped) is ErrorCategory.TRANSIENT


@pytest.mark.parametrize(
    "exc",
    [
        _status_error(anthropic.BadRequestError, 400, error_type="invalid_request_error"),
        _status_error(anthropic.RequestTooLargeError, 413, error_type="request_too_large"),
    ],
)
def test_bad_request_is_permanent(exc):
    mapped = map_api_error(exc)
    assert isinstance(mapped, PermanentLLMError)
    assert classify(mapped) is ErrorCategory.PERMANENT


# ---------------------------------------------------------------- FakeLLM


async def test_fake_llm_returns_queued_items_in_order_and_records_calls():
    canned = LLMResponse("{}", 1, 2, 3, "m", "max_tokens")
    llm = FakeLLM([canned, "text answer", TransientLLMError("503")])

    assert await llm.generate("sys", "user-1", {}) is canned
    second = await llm.generate("sys", "user-2", {"type": "object"})
    assert (second.text, second.stop_reason, second.model) == ("text answer", "end_turn", "fake-llm")
    with pytest.raises(TransientLLMError):
        await llm.generate("sys", "user-3", {})

    assert [call["user"] for call in llm.calls] == ["user-1", "user-2", "user-3"]
    assert llm.calls[1]["schema"] == {"type": "object"}


async def test_fake_llm_default_answer_cites_the_given_evidence():
    llm = FakeLLM()
    response = await llm.generate("sys", "<evidence>\n[C1] (log, svc, t)\nx\n\n[C2] (runbook, svc, t)\ny\n</evidence>", {})
    data = json.loads(response.text)
    assert data["root_cause"]["citations"] == ["C1"]
    assert data["contributing_factors"][0]["citations"] == ["C2"]


def test_fake_default_answer_without_evidence_has_no_root_cause():
    data = json.loads(default_fake_answer("no evidence here"))
    assert (data["root_cause"], data["confidence"]) == (None, "low")


# ---------------------------------------------------------------- factory


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, database_url="postgresql+asyncpg://u:p@h/db", **overrides)


def test_factory_defaults_to_fake():
    assert isinstance(build_llm(_settings()), FakeLLM)


def test_factory_fails_fast_without_key():
    with pytest.raises(LLMConfigError, match="ANTHROPIC_API_KEY is not set"):
        build_llm(_settings(llm_provider="anthropic"))
    with pytest.raises(LLMConfigError):
        build_llm(_settings(llm_provider="anthropic", anthropic_api_key="   "))  # blank = not set


def test_factory_builds_anthropic_without_any_network_call():
    llm = build_llm(_settings(llm_provider="anthropic", anthropic_api_key="sk-ant-test-not-real"))
    assert isinstance(llm, AnthropicLLM)


def test_api_key_is_never_shown_by_the_settings():
    settings = _settings(anthropic_api_key=SecretStr("sk-ant-test-not-real"))
    assert "sk-ant-test-not-real" not in repr(settings)
    assert "sk-ant-test-not-real" not in str(settings.model_dump())


def test_time_budget_must_stay_below_the_poll_interval():
    with pytest.raises(ValueError, match="INVESTIGATION_TIME_BUDGET_SECONDS"):
        _settings(investigation_time_budget_seconds=200, kafka_max_poll_interval_ms=300_000)
