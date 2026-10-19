"""Per-message logging context: the Python version of SLF4J's MDC.

A ContextVar is like a ThreadLocal, but it also works with asyncio: every asyncio Task gets its own
copy, so two messages processed in different tasks can never see each other's requestId.
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
tenant_id_var: ContextVar[str | None] = ContextVar("tenant_id", default=None)
event_id_var: ContextVar[str | None] = ContextVar("event_id", default=None)
investigation_id_var: ContextVar[str | None] = ContextVar("investigation_id", default=None)
node_var: ContextVar[str | None] = ContextVar("node", default=None)  # current LangGraph node

LOG_FORMAT = (
    "%(asctime)s %(levelname)-5s [requestId=%(request_id)s tenantId=%(tenant_id)s "
    "eventId=%(event_id)s investigationId=%(investigation_id)s node=%(node)s] %(name)s : %(message)s"
)

_original_factory = logging.getLogRecordFactory()


def _record_factory(*args, **kwargs) -> logging.LogRecord:
    # Runs for EVERY log record (ours and libraries'), so the format string can always use these fields.
    record = _original_factory(*args, **kwargs)
    record.request_id = request_id_var.get() or "-"
    record.tenant_id = tenant_id_var.get() or "-"
    record.event_id = event_id_var.get() or "-"
    record.investigation_id = investigation_id_var.get() or "-"
    record.node = node_var.get() or "-"
    return record


def install_context_fields() -> None:
    logging.setLogRecordFactory(_record_factory)


def configure_logging(level: str) -> None:
    install_context_fields()
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())


@contextmanager
def log_context(*, request_id: str | None, tenant_id: str | None, event_id: str | None) -> Iterator[None]:
    """Set the context for the duration of a block, then restore the previous values (like MDC.remove)."""
    tokens = [
        (request_id_var, request_id_var.set(request_id)),
        (tenant_id_var, tenant_id_var.set(tenant_id)),
        (event_id_var, event_id_var.set(event_id)),
    ]
    try:
        yield
    finally:
        for var, token in reversed(tokens):
            var.reset(token)


@contextmanager
def value_context(var: ContextVar[str | None], value: str | None) -> Iterator[None]:
    """Set one context field for a block (investigation id, graph node), then restore it."""
    token = var.set(value)
    try:
        yield
    finally:
        var.reset(token)
