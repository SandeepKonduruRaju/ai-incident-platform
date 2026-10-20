"""The investigation workflow as a LangGraph state machine.

    retrieve ──(no evidence)──────────────────────────────────────────► save_insufficient
       │ (budget exceeded) ───────────────────────────────────────────► save_failed
       ▼
    analyse ──► validate ──(valid)────────────────────────────────────► save
       │           │ (invalid, attempts < 2) ──► repair ──► validate
       │           └ (invalid, attempts = 2) ─────────────────────────► save_failed
       └ (LLM permanently failed / retries exhausted / budget) ───────► save_failed

Nodes return PARTIAL state updates; LangGraph merges them. The routing functions and validate_output
are pure, so every branch is unit-testable without a database or an LLM. The attempts counter is the
real bound on LLM calls; recursion_limit is only a backstop against a wiring bug.

LLMConfigError (bad key / model id) is NOT handled here: it propagates out of the graph, because it is
the worker's fault, not this incident's (the caller puts the investigation back to PENDING).
"""

import asyncio
import logging
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, Protocol, TypedDict
from uuid import UUID

from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from app.errors import PermanentLLMError, TransientLLMError
from app.events import IncidentCreatedPayload
from app.investigations import InvestigationRef, Usage
from app.llm import LLM, LLMResponse
from app.logging_context import investigation_id_var, node_var, value_context
from app.prompt import PROMPT_VERSION, SYSTEM_PROMPT, build_repair_message, build_user_message
from app.retrieval import EvidenceItem, label_map
from app.retry import backoff_delay
from app.schemas import INSUFFICIENT_EVIDENCE_RESULT, InvestigationResult, result_json_schema

log = logging.getLogger(__name__)

MAX_OUTPUT_ATTEMPTS = 2  # first answer + one repair
RECURSION_LIMIT = 12  # longest legal path is 6 steps (retrieve, analyse, validate, repair, validate, save)
_INLINE_LABEL = re.compile(r"\[(C\d+)\]")


class InvestigationState(TypedDict, total=False):
    tenant_id: str
    investigation_id: UUID
    ref: InvestigationRef            # id + run_count: the fencing token for the final save
    incident: IncidentCreatedPayload
    evidence: list[EvidenceItem]
    label_map: dict[str, UUID]
    user_message: str
    raw_output: str | None
    stop_reason: str | None
    result: dict[str, Any] | None    # the validated InvestigationResult as JSON
    error: str | None                # why the last LLM output was invalid (fed back by repair)
    fatal: str | None                # unrecoverable for this run: goes straight to save_failed
    attempts: int                    # LLM outputs produced in this run (analyse = 1, repair = 2)
    usage: Usage
    deadline: float                  # monotonic clock value at which the time budget runs out
    outcome: str                     # COMPLETED | FAILED, set by the save nodes


class InvestigationStore(Protocol):
    async def save_completed(self, ref: InvestigationRef, **values: Any) -> bool: ...

    async def save_failed(self, ref: InvestigationRef, **values: Any) -> bool: ...


Retriever = Callable[[str, IncidentCreatedPayload], Awaitable[list[EvidenceItem]]]


@dataclass(frozen=True)
class GraphDeps:
    retrieve: Retriever
    llm: LLM
    store: InvestigationStore
    evidence_max_chars: int = 1500
    llm_max_retries: int = 3
    retry_base_delay_seconds: float = 0.5
    retry_max_delay_seconds: float = 10.0
    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
    schema: dict[str, Any] = field(default_factory=result_json_schema)


# ---------------------------------------------------------------- pure functions


def validate_output(raw: str | None, stop_reason: str | None, labels: dict[str, UUID]) -> tuple[dict[str, Any] | None, str | None]:
    """(result, None) if the output is usable, else (None, error message for the repair prompt). Pure."""
    if stop_reason == "max_tokens":
        return None, "the answer was cut off at max_tokens (incomplete JSON); answer more briefly"
    if stop_reason == "refusal":
        return None, "the model declined to answer"
    if stop_reason not in (None, "end_turn"):
        return None, f"unexpected stop_reason {stop_reason!r}"
    try:
        result = InvestigationResult.model_validate_json(raw or "")
    except ValidationError as exc:
        details = "; ".join(f"{'.'.join(str(p) for p in e['loc']) or 'output'}: {e['msg']}" for e in exc.errors())
        return None, f"schema validation failed: {details}"

    texts = [result.summary] + [
        finding.text
        for finding in (result.root_cause, *result.contributing_factors, *result.remediation)
        if finding is not None
    ]
    cited = set(result.all_citations()) | {label for text in texts for label in _INLINE_LABEL.findall(text)}
    unknown = sorted(cited - set(labels), key=lambda label: (len(label), label))
    if unknown:
        valid = ", ".join(sorted(labels, key=lambda label: (len(label), label)))
        return None, f"unknown citation label(s) {', '.join(unknown)}; valid labels are: {valid}"
    return result.model_dump(mode="json"), None


def route_after_retrieve(state: InvestigationState) -> str:
    if state.get("fatal"):
        return "save_failed"
    return "analyse" if state.get("evidence") else "save_insufficient"


def route_after_llm(state: InvestigationState) -> str:
    return "save_failed" if state.get("fatal") else "validate"


def route_after_validate(state: InvestigationState) -> str:
    if state.get("result") is not None:
        return "save"
    if state.get("attempts", 0) < MAX_OUTPUT_ATTEMPTS:
        return "repair"
    return "save_failed"


def evidence_json(items: list[EvidenceItem]) -> list[dict[str, Any]]:
    return [
        {"label": i.label, "chunk_id": str(i.chunk_id), "source_type": i.source_type, "source_id": i.source_id}
        for i in items
    ]


def _add_usage(usage: Usage, response: LLMResponse) -> Usage:
    return Usage(
        model=response.model,
        input_tokens=usage.input_tokens + response.input_tokens,
        output_tokens=usage.output_tokens + response.output_tokens,
        llm_latency_ms=usage.llm_latency_ms + response.latency_ms,
    )


# ---------------------------------------------------------------- graph


def _logged(name: str, node: Callable[[InvestigationState], Awaitable[dict[str, Any]]]):
    """Puts the node name into the logging context (node=... in every log line of that node)."""

    @wraps(node)
    async def wrapper(state: InvestigationState) -> dict[str, Any]:
        with value_context(node_var, name):
            log.debug("enter")
            return await node(state)

    return wrapper


def build_graph(deps: GraphDeps):
    async def call_llm(state: InvestigationState, user: str) -> dict[str, Any]:
        """One LLM output, retrying TRANSIENT errors with backoff inside the time budget."""
        attempt_number = state.get("attempts", 0) + 1
        usage = state.get("usage", Usage())
        for try_number in range(1, deps.llm_max_retries + 1):
            remaining = state["deadline"] - deps.clock()
            if remaining <= 0:
                return {"fatal": "time budget exceeded"}
            try:
                async with asyncio.timeout(remaining):
                    response = await deps.llm.generate(SYSTEM_PROMPT, user, deps.schema)
            except TimeoutError:
                return {"fatal": "time budget exceeded"}
            except PermanentLLMError as exc:
                log.error("LLM rejected the request: %s", exc)
                return {"fatal": f"LLM rejected the request: {exc}"}
            except TransientLLMError as exc:
                if try_number == deps.llm_max_retries:
                    log.error("LLM unavailable after %d tries: %s", try_number, exc)
                    return {"fatal": f"LLM unavailable after {try_number} tries: {exc}"}
                delay = exc.retry_after or backoff_delay(
                    try_number, deps.retry_base_delay_seconds, deps.retry_max_delay_seconds
                )
                if delay >= state["deadline"] - deps.clock():
                    return {"fatal": "time budget exceeded"}
                log.warning("transient LLM error (try %d/%d): %s; retrying in %.2fs", try_number, deps.llm_max_retries, exc, delay)
                await deps.sleep(delay)
                continue
            log.info(
                "LLM output attempt=%d model=%s input_tokens=%d output_tokens=%d latency_ms=%d stop_reason=%s",
                attempt_number, response.model, response.input_tokens, response.output_tokens,
                response.latency_ms, response.stop_reason,
            )
            return {
                "raw_output": response.text,
                "stop_reason": response.stop_reason,
                "attempts": attempt_number,
                "usage": _add_usage(usage, response),
            }
        raise AssertionError("unreachable")

    async def retrieve(state: InvestigationState) -> dict[str, Any]:
        evidence = await deps.retrieve(state["tenant_id"], state["incident"])
        if deps.clock() >= state["deadline"]:
            return {"evidence": evidence, "label_map": label_map(evidence), "fatal": "time budget exceeded"}
        log.info("retrieved %d evidence item(s)", len(evidence))
        return {
            "evidence": evidence,
            "label_map": label_map(evidence),
            "user_message": build_user_message(state["incident"], evidence, deps.evidence_max_chars),
        }

    async def analyse(state: InvestigationState) -> dict[str, Any]:
        return await call_llm(state, state["user_message"])

    async def validate(state: InvestigationState) -> dict[str, Any]:
        result, error = validate_output(state.get("raw_output"), state.get("stop_reason"), state["label_map"])
        if error:
            log.warning("invalid LLM output (attempt %d): %s", state.get("attempts", 0), error)
        return {"result": result, "error": error}

    async def repair(state: InvestigationState) -> dict[str, Any]:
        user = state["user_message"] + build_repair_message(state.get("raw_output") or "", state.get("error") or "")
        return await call_llm(state, user)

    def common(state: InvestigationState) -> dict[str, Any]:
        return {
            "evidence": evidence_json(state.get("evidence", [])),
            "usage": state.get("usage", Usage()),
            "attempts": state.get("attempts", 0),
        }

    async def save(state: InvestigationState) -> dict[str, Any]:
        saved = await deps.store.save_completed(
            state["ref"], result=state["result"], prompt_version=PROMPT_VERSION, **common(state)
        )
        _log_saved(saved, "COMPLETED")
        return {"outcome": "COMPLETED"}

    async def save_insufficient(state: InvestigationState) -> dict[str, Any]:
        # No evidence: answering would only invite a hallucination, so the LLM is not called at all.
        saved = await deps.store.save_completed(
            state["ref"], result=INSUFFICIENT_EVIDENCE_RESULT.model_dump(mode="json"),
            prompt_version=PROMPT_VERSION, **common(state),
        )
        _log_saved(saved, "COMPLETED (insufficient evidence)")
        return {"outcome": "COMPLETED", "result": INSUFFICIENT_EVIDENCE_RESULT.model_dump(mode="json")}

    async def save_failed(state: InvestigationState) -> dict[str, Any]:
        reason = state.get("fatal") or f"invalid LLM output after {state.get('attempts', 0)} attempts: {state.get('error')}"
        saved = await deps.store.save_failed(state["ref"], reason=reason, prompt_version=PROMPT_VERSION, **common(state))
        _log_saved(saved, f"FAILED ({reason})")
        return {"outcome": "FAILED", "fatal": reason}

    builder = StateGraph(InvestigationState)
    for name, node in (
        ("retrieve", retrieve),
        ("analyse", analyse),
        ("validate", validate),
        ("repair", repair),
        ("save", save),
        ("save_insufficient", save_insufficient),
        ("save_failed", save_failed),
    ):
        builder.add_node(name, _logged(name, node))
    builder.add_edge(START, "retrieve")
    builder.add_conditional_edges("retrieve", route_after_retrieve, ["analyse", "save_insufficient", "save_failed"])
    builder.add_conditional_edges("analyse", route_after_llm, ["validate", "save_failed"])
    builder.add_conditional_edges("repair", route_after_llm, ["validate", "save_failed"])
    builder.add_conditional_edges("validate", route_after_validate, ["save", "repair", "save_failed"])
    for terminal in ("save", "save_insufficient", "save_failed"):
        builder.add_edge(terminal, END)
    return builder.compile()


def _log_saved(saved: bool, what: str) -> None:
    if saved:
        log.info("investigation saved: %s", what)
    else:
        log.warning("not saved (%s): a newer run owns this investigation", what)


async def run_investigation(
    deps: GraphDeps,
    ref: InvestigationRef,
    incident: IncidentCreatedPayload,
    *,
    time_budget_seconds: float,
    graph=None,
) -> InvestigationState:
    graph = graph or build_graph(deps)
    initial: InvestigationState = {
        "tenant_id": ref.tenant_id,
        "investigation_id": ref.id,
        "ref": ref,
        "incident": incident,
        "attempts": 0,
        "usage": Usage(),
        "deadline": deps.clock() + time_budget_seconds,
    }
    with value_context(investigation_id_var, str(ref.id)):
        return await graph.ainvoke(initial, config={"recursion_limit": RECURSION_LIMIT})
