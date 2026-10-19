from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import partial

from fastapi import FastAPI, Request, Response

from app.config import get_settings
from app.consumer import IncidentEventConsumer
from app.db import create_engine
from app.internal_api import require_internal_token_configured
from app.internal_api import router as internal_router
from app.investigator import build_deps, build_retriever, load_models, make_investigate
from app.llm import build_llm
from app.logging_context import configure_logging
from app.processing import process_event


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup before `yield`, shutdown after it (like @PostConstruct / @PreDestroy for the whole app)."""
    settings = get_settings()
    configure_logging(settings.log_level)
    require_internal_token_configured(settings)  # fails fast: never serve /internal/* unprotected
    llm = build_llm(settings)  # fails fast: LLM_PROVIDER=anthropic without ANTHROPIC_API_KEY stops startup here
    engine = create_engine(settings.database_url)
    app.state.engine = engine  # used by the internal read API
    embedder, reranker = await load_models(settings)
    deps = build_deps(settings, engine, llm, build_retriever(engine, embedder, reranker, settings))
    consumer = IncidentEventConsumer(settings, processor=partial(process_event, engine, make_investigate(deps, settings)))
    app.state.consumer = consumer
    app.state.consumer_enabled = settings.consumer_enabled
    if settings.consumer_enabled:
        await consumer.start()  # returns immediately; the loop runs as a background task
    try:
        yield
    finally:
        await consumer.stop()  # graceful: cancel the task and wait for it to close the Kafka clients
        await engine.dispose()


app = FastAPI(title="investigation-worker", lifespan=lifespan)
app.include_router(internal_router)  # /internal/v1/*, every route requires X-Internal-Token; /health stays public


@app.get("/health")
def health(request: Request, response: Response) -> dict[str, str]:
    consumer: IncidentEventConsumer | None = getattr(request.app.state, "consumer", None)
    if not getattr(request.app.state, "consumer_enabled", True):
        return {"status": "ok", "consumer": "disabled"}
    if consumer is None or not consumer.is_alive:
        # 503 makes the Docker healthcheck (and a Kubernetes probe) notice a dead consumer.
        response.status_code = 503
        return {"status": "unavailable", "consumer": consumer.state if consumer else "not started"}
    reason = getattr(consumer, "unhealthy_reason", None)
    if reason:
        # Alive but useless: e.g. a bad ANTHROPIC_API_KEY makes every investigation stay PENDING.
        response.status_code = 503
        return {"status": "unavailable", "consumer": consumer.state, "reason": reason}
    return {"status": "ok", "consumer": consumer.state}
