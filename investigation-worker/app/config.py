from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed configuration read from environment variables (like @ConfigurationProperties).

    Env var names are the field names in any case, e.g. KAFKA_BOOTSTRAP_SERVERS. A local .env file
    is read too (copy .env.example); real environment variables win over it.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Kafka ---
    kafka_bootstrap_servers: str = "localhost:9092"
    kafka_topic: str = "incident-events"
    kafka_group_id: str = "investigation-worker"
    kafka_dlq_topic: str = "incident-events.DLQ"
    # If we don't ask Kafka for the next message within this time, the broker assumes we are stuck,
    # removes us from the group and gives our partitions to another consumer (which then redoes our
    # in-flight message). Today processing takes milliseconds; once it calls an LLM it can take tens
    # of seconds per message, so this must stay well above the slowest expected processing time.
    kafka_max_poll_interval_ms: int = 300_000
    # Lets tests and local tools run the API without starting the consumer.
    consumer_enabled: bool = True

    # --- Database --- (no default on purpose: it contains a password, so the app fails fast without it)
    database_url: str

    # --- Retries for transient errors (exponential backoff with full jitter) ---
    retry_max_attempts: int = 5
    retry_base_delay_seconds: float = 0.5
    retry_max_delay_seconds: float = 10.0

    # --- Embeddings (retrieval) ---
    # Changing the model means re-ingesting everything: vectors from different models are not comparable,
    # and the column is vector(384), so the model must produce 384 dimensions.
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    # Where the ONNX model files are stored. None = fastembed's default (FASTEMBED_CACHE_PATH or the temp dir).
    # The Docker image downloads the model into a fixed directory at build time and sets this to it.
    embedding_cache_dir: str | None = None
    # Prepended to search queries only (documents are embedded without it). The bge-*-v1.5 model card
    # recommends it for short-query -> passage retrieval; empty string = off.
    embedding_query_instruction: str = "Represent this sentence for searching relevant passages: "

    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    # Built once and reused, like a singleton bean.
    return Settings()
