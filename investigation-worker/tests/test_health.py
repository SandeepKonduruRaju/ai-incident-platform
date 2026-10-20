import pytest
from fastapi.testclient import TestClient

from app.main import app

# TestClient(app) without "with" does NOT run the lifespan, so no Kafka or database is needed:
# each test puts what /health looks at into app.state itself.
client = TestClient(app)


class FakeConsumer:
    def __init__(self, alive: bool, state: str):
        self.is_alive = alive
        self.state = state


@pytest.fixture(autouse=True)
def clean_state():
    yield
    for name in ("consumer", "consumer_enabled"):
        if hasattr(app.state, name):
            delattr(app.state, name)


def test_health_is_ok_while_consumer_runs():
    app.state.consumer = FakeConsumer(alive=True, state="running")

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "consumer": "running"}


def test_health_is_503_when_consumer_died():
    app.state.consumer = FakeConsumer(alive=False, state="failed")

    response = client.get("/health")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "consumer": "failed"}


def test_health_is_503_before_startup():
    response = client.get("/health")

    assert response.status_code == 503
    assert response.json()["consumer"] == "not started"


def test_health_is_ok_when_consumer_disabled():
    app.state.consumer_enabled = False

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "consumer": "disabled"}


# /livez is the Kubernetes liveness probe (section 3.5): only a crashed consumer loop fails it.
def test_livez_is_ok_while_the_consumer_runs_or_retries_kafka():
    for state in ("starting", "running"):
        app.state.consumer = FakeConsumer(alive=True, state=state)
        assert client.get("/livez").status_code == 200


def test_livez_is_503_only_when_the_consumer_loop_crashed():
    app.state.consumer = FakeConsumer(alive=False, state="failed")

    assert client.get("/livez").status_code == 503


def test_livez_stays_ok_on_an_llm_config_error_a_restart_cannot_fix():
    consumer = FakeConsumer(alive=True, state="running")
    consumer.unhealthy_reason = "LLM auth/config error"
    app.state.consumer = consumer

    assert client.get("/livez").status_code == 200
    assert client.get("/health").status_code == 503  # readiness still reports it
