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
