"""Wiring: settings -> models, retriever, LLM, store -> a ready-to-run investigation function.

Shared by the FastAPI app (consumer), python -m app.investigate and python -m app.rerun, so all three
run exactly the same graph with the same configuration.
"""

import asyncio
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import Settings
from app.embedding import Embedder, FastEmbedEmbedder
from app.events import IncidentCreatedPayload
from app.graph import GraphDeps, Retriever, build_graph, run_investigation
from app.investigations import InvestigationRef, PostgresInvestigationStore
from app.llm import LLM
from app.processing import Investigate
from app.rerank import FastEmbedReranker, Reranker
from app.retrieval import EvidenceItem, retrieve_evidence


async def load_models(settings: Settings) -> tuple[Embedder, Reranker]:
    """Loading ONNX models is CPU/disk work: off the event loop."""
    embedder = await asyncio.to_thread(FastEmbedEmbedder, settings.embedding_model, settings.embedding_cache_dir)
    reranker = await asyncio.to_thread(FastEmbedReranker, settings.reranker_model, settings.embedding_cache_dir)
    return embedder, reranker


def build_retriever(engine: AsyncEngine, embedder: Embedder, reranker: Reranker, settings: Settings) -> Retriever:
    async def retrieve(tenant_id: str, incident: IncidentCreatedPayload) -> list[EvidenceItem]:
        return await retrieve_evidence(
            engine,
            embedder,
            reranker,
            tenant_id=tenant_id,
            incident=incident,
            retrieve_k=settings.retrieval_retrieve_k,
            final_k=settings.retrieval_final_k,
            caps=settings.retrieval_source_caps,
            window_before=timedelta(minutes=settings.retrieval_window_before_minutes),
            window_after=timedelta(minutes=settings.retrieval_window_after_minutes),
            query_instruction=settings.embedding_query_instruction,
        )

    return retrieve


def build_deps(settings: Settings, engine: AsyncEngine, llm: LLM, retriever: Retriever) -> GraphDeps:
    return GraphDeps(
        retrieve=retriever,
        llm=llm,
        store=PostgresInvestigationStore(engine),
        evidence_max_chars=settings.evidence_max_chars,
        llm_max_retries=settings.llm_max_retries,
        retry_base_delay_seconds=settings.retry_base_delay_seconds,
        retry_max_delay_seconds=settings.retry_max_delay_seconds,
    )


def make_investigate(deps: GraphDeps, settings: Settings) -> Investigate:
    graph = build_graph(deps)  # compiled once, reused for every investigation

    async def investigate(ref: InvestigationRef, incident: IncidentCreatedPayload) -> str:
        state = await run_investigation(
            deps, ref, incident, time_budget_seconds=settings.investigation_time_budget_seconds, graph=graph
        )
        return state["outcome"]

    return investigate
