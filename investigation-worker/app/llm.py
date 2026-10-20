"""LLM access behind a small protocol, so the graph never depends on a vendor SDK directly.

    LLM_PROVIDER=fake       (default) FakeLLM: canned answers, no network, no key, no cost
    LLM_PROVIDER=anthropic  AnthropicLLM: Claude through the official SDK, schema-constrained output

Never log the API key or full prompts: only model, token counts, latency and stop reason.
"""

import json
import logging
import re
import time
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Protocol

import anthropic

from app.config import Settings
from app.errors import LLMConfigError, PermanentLLMError, TransientLLMError

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class LLMResponse:
    text: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    model: str
    stop_reason: str | None  # "end_turn" is the only one we accept; "max_tokens"/"refusal" are invalid output


class LLM(Protocol):
    async def generate(self, system: str, user: str, schema: dict[str, Any]) -> LLMResponse: ...


# ---------------------------------------------------------------- Anthropic


def _retry_after_seconds(exc: anthropic.APIStatusError) -> float | None:
    try:
        return float(exc.response.headers.get("retry-after", ""))
    except ValueError:
        return None


def map_api_error(exc: anthropic.AnthropicError) -> Exception:
    """SDK exception -> our classification. Most specific first (the SDK has one class per status)."""
    if isinstance(exc, (anthropic.AuthenticationError, anthropic.PermissionDeniedError, anthropic.CredentialsError)):
        return LLMConfigError(f"LLM auth/config error ({type(exc).__name__}) — check ANTHROPIC_API_KEY")
    if isinstance(exc, anthropic.NotFoundError):  # unknown model id, or a model this key cannot use
        return LLMConfigError(f"LLM model not found ({type(exc).__name__}) — check LLM_MODEL")
    if isinstance(exc, anthropic.RateLimitError):
        return TransientLLMError("rate limited (429)", retry_after=_retry_after_seconds(exc), kind="rate_limit")
    if isinstance(exc, anthropic.APIConnectionError):  # includes APITimeoutError
        return TransientLLMError(f"{type(exc).__name__}: no response from the API", kind="timeout")
    if isinstance(exc, anthropic.APIStatusError):
        if exc.status_code >= 500 or exc.status_code in (408, 409):  # 500, 503, 529 overloaded, ...
            return TransientLLMError(f"API error {exc.status_code} ({exc.type})")
        return PermanentLLMError(f"API rejected the request: {exc.status_code} ({exc.type})")
    return TransientLLMError(f"unexpected SDK error {type(exc).__name__}")


class AnthropicLLM:
    """Structured outputs (output_config.format = our JSON schema): the API constrains decoding to the
    schema, so the text block is valid JSON of that shape whenever stop_reason is "end_turn".

    No temperature: Claude Haiku 5.5 rejects non-default sampling parameters with a 400.
    max_retries=0: retries are OURS (graph analyse/repair nodes), so they respect the time budget and
    are logged per attempt, instead of hidden SDK retries multiplying the wall-clock time.
    """

    def __init__(self, *, api_key: str, model: str, max_tokens: int, effort: str, timeout_seconds: float):
        self._client = anthropic.AsyncAnthropic(api_key=api_key, timeout=timeout_seconds, max_retries=0)
        self._model = model
        self._max_tokens = max_tokens
        self._effort = effort

    async def generate(self, system: str, user: str, schema: dict[str, Any]) -> LLMResponse:
        started = time.perf_counter()
        try:
            message = await self._client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_config={"effort": self._effort, "format": {"type": "json_schema", "schema": schema}},
            )
        except anthropic.AnthropicError as exc:
            raise map_api_error(exc) from exc
        latency_ms = int((time.perf_counter() - started) * 1000)
        # Read blocks by type: Haiku 5.5 thinks by default, so the first block can be a thinking block.
        text = "".join(block.text for block in message.content if block.type == "text")
        response = LLMResponse(
            text=text,
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
            latency_ms=latency_ms,
            model=message.model,
            stop_reason=message.stop_reason,
        )
        log.info(
            "llm call model=%s input_tokens=%d output_tokens=%d latency_ms=%d stop_reason=%s request_id=%s",
            response.model, response.input_tokens, response.output_tokens, latency_ms,
            response.stop_reason, message._request_id,
        )
        return response


# ---------------------------------------------------------------- Fake

_EVIDENCE_LABEL = re.compile(r"^\[(C\d+)\]", re.MULTILINE)


def default_fake_answer(user: str) -> str:
    """A schema-valid answer that cites the evidence it was given (for local runs without a key)."""
    labels = _EVIDENCE_LABEL.findall(user.split("<evidence>", 1)[-1])
    if not labels:
        result: dict[str, Any] = {
            "root_cause": None,
            "contributing_factors": [],
            "remediation": [],
            "confidence": "low",
            "summary": "FakeLLM: no evidence labels found.",
        }
    else:
        first, rest = labels[0], labels[1:3] or labels[:1]
        result = {
            "root_cause": {"text": f"FakeLLM placeholder root cause based on [{first}].", "citations": [first]},
            "contributing_factors": [
                {"text": f"FakeLLM placeholder factor based on [{label}].", "citations": [label]} for label in rest
            ],
            "remediation": [{"text": f"FakeLLM placeholder: follow the runbook steps in [{first}].", "citations": [first]}],
            "confidence": "low",
            "summary": "FakeLLM canned answer (LLM_PROVIDER=fake): not a real analysis.",
        }
    return json.dumps(result)


@dataclass
class FakeLLM:
    """Returns queued responses in order (str -> a normal response with that text, LLMResponse as is,
    Exception -> raised); when the queue is empty, default_fake_answer. Records every call."""

    responses: Iterable[LLMResponse | str | Exception] = ()
    model: str = "fake-llm"
    calls: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._queue = deque(self.responses)

    async def generate(self, system: str, user: str, schema: dict[str, Any]) -> LLMResponse:
        self.calls.append({"system": system, "user": user, "schema": schema})
        item = self._queue.popleft() if self._queue else default_fake_answer(user)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, LLMResponse):
            return item
        return LLMResponse(
            text=item, input_tokens=len(user) // 4, output_tokens=len(item) // 4,
            latency_ms=1, model=self.model, stop_reason="end_turn",
        )


# ---------------------------------------------------------------- factory


def build_llm(settings: Settings) -> LLM:
    """Fails fast (at startup) when the real provider is selected without a key."""
    if settings.llm_provider == "fake":
        return FakeLLM()
    if settings.anthropic_api_key is None:
        raise LLMConfigError("LLM_PROVIDER=anthropic but ANTHROPIC_API_KEY is not set")
    return AnthropicLLM(
        api_key=settings.anthropic_api_key.get_secret_value(),
        model=settings.llm_model,
        max_tokens=settings.llm_max_tokens,
        effort=settings.llm_effort,
        timeout_seconds=settings.llm_timeout_seconds,
    )
