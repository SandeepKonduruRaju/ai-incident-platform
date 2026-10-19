"""Shared fixtures. Integration fixtures start real Kafka and PostgreSQL containers (once per run)
and skip the test cleanly when Docker is not available, like @Testcontainers(disabledWithoutDocker = true)."""

import asyncio
import socket
import time
import uuid
from pathlib import Path

import pytest
from aiokafka.admin import AIOKafkaAdminClient, NewTopic

KAFKA_IMAGE = "apache/kafka:4.1.0"  # same image as incident-service/compose.yaml
POSTGRES_IMAGE = "pgvector/pgvector:pg18-trixie"  # same image as compose: PostgreSQL 18 + pgvector
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _docker_available() -> bool:
    try:
        import docker

        docker.from_env().ping()
        return True
    except Exception:
        return False


@pytest.fixture(scope="session")
def docker_required():
    if not _docker_available():
        pytest.skip("Docker is not available")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def kafka_bootstrap(docker_required) -> str:
    """A single-node KRaft broker from the official apache/kafka image.

    testcontainers' KafkaContainer only supports Confluent images, so this configures the Apache one
    directly. Kafka tells clients which address to use ("advertised listener"), so we pick the host
    port up front and advertise exactly that.
    """
    from testcontainers.core.container import DockerContainer

    port = _free_port()
    container = (
        DockerContainer(KAFKA_IMAGE)
        .with_bind_ports(9092, port)
        .with_envs(
            KAFKA_NODE_ID="1",
            KAFKA_PROCESS_ROLES="broker,controller",
            KAFKA_LISTENERS="PLAINTEXT://:9092,CONTROLLER://:9093",
            KAFKA_ADVERTISED_LISTENERS=f"PLAINTEXT://127.0.0.1:{port}",
            KAFKA_LISTENER_SECURITY_PROTOCOL_MAP="CONTROLLER:PLAINTEXT,PLAINTEXT:PLAINTEXT",
            KAFKA_CONTROLLER_LISTENER_NAMES="CONTROLLER",
            KAFKA_CONTROLLER_QUORUM_VOTERS="1@localhost:9093",
            KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR="1",
            KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR="1",
            KAFKA_TRANSACTION_STATE_LOG_MIN_ISR="1",
            KAFKA_GROUP_INITIAL_REBALANCE_DELAY_MS="0",  # join groups immediately (faster tests)
            KAFKA_AUTO_CREATE_TOPICS_ENABLE="false",  # as in compose: topics must be created
        )
    )
    container.start()
    bootstrap = f"127.0.0.1:{port}"
    try:
        asyncio.run(_wait_for_kafka(bootstrap))
        yield bootstrap
    finally:
        container.stop()


async def _wait_for_kafka(bootstrap: str, timeout: float = 90) -> None:
    deadline = time.monotonic() + timeout
    while True:
        admin = AIOKafkaAdminClient(bootstrap_servers=bootstrap)
        try:
            await admin.start()
            await admin.list_topics()
            return
        except Exception:
            if time.monotonic() > deadline:
                raise
            await asyncio.sleep(1)
        finally:
            await admin.close()


@pytest.fixture(scope="session")
def database_url(docker_required) -> str:
    """PostgreSQL with the worker's Alembic migrations applied (the real ones, like Flyway in the Java tests)."""
    from alembic import command
    from alembic.config import Config
    from testcontainers.community.postgres import PostgresContainer

    with PostgresContainer(POSTGRES_IMAGE, driver="asyncpg") as postgres:
        url = postgres.get_connection_url()
        config = Config(str(PROJECT_ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
        config.attributes["database_url"] = url
        config.attributes["configure_logging"] = False
        command.upgrade(config, "head")
        yield url


@pytest.fixture
async def engine(database_url):
    from sqlalchemy import text

    from app.db import create_engine

    engine = create_engine(database_url)
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE worker.processed_events, worker.investigations"))
    yield engine
    await engine.dispose()


@pytest.fixture
async def topics(kafka_bootstrap) -> tuple[str, str]:
    """A fresh topic + DLQ per test (3 partitions, like compose), so tests never see each other's messages."""
    suffix = uuid.uuid4().hex[:8]
    topic, dlq = f"incident-events-{suffix}", f"incident-events-{suffix}.DLQ"
    admin = AIOKafkaAdminClient(bootstrap_servers=kafka_bootstrap)
    await admin.start()
    try:
        await admin.create_topics([NewTopic(t, num_partitions=3, replication_factor=1) for t in (topic, dlq)])
    finally:
        await admin.close()
    return topic, dlq
