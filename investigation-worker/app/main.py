from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import partial

from fastapi import FastAPI, Request, Response

from app.config import get_settings
from app.consumer import IncidentEventConsumer
from app.db import create_engine
from app.logging_context import configure_logging
from app.processing import create_investigation


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup before `yield`, shutdown after it (like @PostConstruct / @PreDestroy for the whole app)."""
    settings = get_settings()
    configure_logging(settings.log_level)
    engine = create_engine(settings.database_url)
    consumer = IncidentEventConsumer(settings, processor=partial(create_investigation, engine))
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


@app.get("/health")
def health(request: Request, response: Response) -> dict[str, str]:
    consumer: IncidentEventConsumer | None = getattr(request.app.state, "consumer", None)
    if not getattr(request.app.state, "consumer_enabled", True):
        return {"status": "ok", "consumer": "disabled"}
    if consumer is None or not consumer.is_alive:
        # 503 makes the Docker healthcheck (and a Kubernetes probe) notice a dead consumer.
        response.status_code = 503
        return {"status": "unavailable", "consumer": consumer.state if consumer else "not started"}
    return {"status": "ok", "consumer": consumer.state}
