"""Metrics and a span around every LLM call (section 3.4), as a wrapper: the graph and the LLM clients
stay unaware of observability.

Span "llm.generate" attributes: model, prompt version, token counts, stop reason, latency.
Never the prompt, the evidence or the answer text.
"""

import time
from dataclasses import dataclass
from typing import Any

from opentelemetry.trace import SpanKind, Status, StatusCode

from app.errors import LLMConfigError, PermanentLLMError, TransientLLMError
from app.llm import LLM, LLMResponse
from app.metrics import LLM_ERRORS, record_llm_usage
from app.tracing import tracer


def error_kind(exc: Exception) -> str | None:
    if isinstance(exc, LLMConfigError):
        return "config"
    if isinstance(exc, TransientLLMError):
        return exc.kind
    if isinstance(exc, PermanentLLMError):
        return "rejected"
    return None


@dataclass(frozen=True)
class ObservedLLM:
    inner: LLM
    model: str                  # configured model id: the label when the call fails before any response
    prompt_version: str
    price_in_per_m: float       # USD per million input tokens (0 for the fake provider)
    price_out_per_m: float

    async def generate(self, system: str, user: str, schema: dict[str, Any]) -> LLMResponse:
        with tracer.start_as_current_span("llm.generate", kind=SpanKind.CLIENT, record_exception=False) as span:
            span.set_attribute("gen_ai.request.model", self.model)
            span.set_attribute("prompt_version", self.prompt_version)
            started = time.perf_counter()
            try:
                response = await self.inner.generate(system, user, schema)
            except Exception as exc:
                kind = error_kind(exc)
                if kind:
                    LLM_ERRORS.labels(self.model, kind).inc()
                # The exception type only: SDK messages can echo request details.
                span.set_status(Status(StatusCode.ERROR, type(exc).__name__))
                span.set_attribute("error.type", type(exc).__name__)
                raise
            seconds = time.perf_counter() - started
            cost = (response.input_tokens * self.price_in_per_m + response.output_tokens * self.price_out_per_m) / 1_000_000
            record_llm_usage(response.model, response.input_tokens, response.output_tokens, cost, seconds)
            span.set_attribute("gen_ai.response.model", response.model)
            span.set_attribute("gen_ai.usage.input_tokens", response.input_tokens)
            span.set_attribute("gen_ai.usage.output_tokens", response.output_tokens)
            span.set_attribute("gen_ai.response.finish_reason", response.stop_reason or "none")
            span.set_attribute("llm.cost_usd", cost)
            return response
