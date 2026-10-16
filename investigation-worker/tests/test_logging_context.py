import asyncio
import logging

from app.consumer import decode_headers
from app.logging_context import install_context_fields, log_context, request_id_var


def test_context_is_set_inside_and_cleared_after():
    with log_context(request_id="req-1", tenant_id="acme", event_id="evt-1"):
        assert request_id_var.get() == "req-1"
        with log_context(request_id="req-2", tenant_id="acme", event_id="evt-2"):
            assert request_id_var.get() == "req-2"
        assert request_id_var.get() == "req-1"  # inner block restored the outer value
    assert request_id_var.get() is None


def test_every_log_record_gets_the_context_fields(caplog):
    install_context_fields()
    caplog.set_level(logging.INFO)

    with log_context(request_id="req-1", tenant_id="acme", event_id="evt-1"):
        logging.getLogger("test").info("inside")
    logging.getLogger("test").info("outside")

    inside, outside = caplog.records
    assert (inside.request_id, inside.tenant_id, inside.event_id) == ("req-1", "acme", "evt-1")
    assert (outside.request_id, outside.tenant_id, outside.event_id) == ("-", "-", "-")


async def test_concurrent_tasks_do_not_see_each_others_context():
    async def handle(request_id: str) -> str | None:
        with log_context(request_id=request_id, tenant_id=None, event_id=None):
            await asyncio.sleep(0.01)  # let the other task run in between
            return request_id_var.get()

    assert await asyncio.gather(handle("a"), handle("b")) == ["a", "b"]


def test_decode_headers():
    assert decode_headers([("requestId", b"req-1"), ("empty", None)]) == {"requestId": "req-1"}
    assert decode_headers(None) == {}
