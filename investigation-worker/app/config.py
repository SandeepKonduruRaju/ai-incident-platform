from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.embedding import BGE_QUERY_INSTRUCTION


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
    embedding_query_instruction: str = BGE_QUERY_INSTRUCTION

    # --- Hybrid retrieval (section 2.5) ---
    # Cross-encoder that re-orders the fused candidates. Baked into the Docker image like the embedding model.
    reranker_model: str = "Xenova/ms-marco-MiniLM-L-6-v2"
    # Logs and metrics are searched in [createdAt - before, createdAt + after) for the affected service.
    retrieval_window_before_minutes: int = 120
    retrieval_window_after_minutes: int = 30
    retrieval_retrieve_k: int = 20   # candidates per retriever, and how many fused candidates get reranked
    retrieval_final_k: int = 6       # evidence items handed to the LLM
    # Max chunks per source type in the final selection; unused slots go to the next best chunks.
    # Env var as JSON, e.g. RETRIEVAL_SOURCE_CAPS='{"log": 3, "runbook": 2, "incident": 1, "metric": 2}'
    retrieval_source_caps: dict[str, int] = {"log": 3, "runbook": 2, "incident": 1, "metric": 2}

    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    # Built once and reused, like a singleton bean.
    return Settings()
