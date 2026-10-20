from functools import lru_cache
from typing import Literal

from pydantic import SecretStr, field_validator, model_validator
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

    # --- LLM investigation (section 2.6) ---
    # "fake" (default): canned answers, no network, no key, no cost. "anthropic": the real Claude API.
    llm_provider: Literal["fake", "anthropic"] = "fake"
    # SecretStr: printing the settings shows '**********'; only the LLM client calls get_secret_value().
    anthropic_api_key: SecretStr | None = None
    llm_model: str = "claude-haiku-5-5"
    # Room for adaptive thinking (Haiku 5.5 thinks by default and thinking counts toward max_tokens) plus
    # the JSON answer. Hitting the cap is treated as invalid output (repair path), never parsed.
    llm_max_tokens: int = 4096
    # Haiku 5.5 thinks adaptively; effort is the lever for how much (default there: medium).
    llm_effort: Literal["low", "medium", "high"] = "low"
    llm_timeout_seconds: float = 45.0
    llm_max_retries: int = 3  # attempts per LLM call for TRANSIENT errors (timeouts, 429, 5xx)
    # Whole investigation (retrieval + every LLM call + retries). Must stay well below the Kafka poll
    # interval, or the broker would kick the consumer out while the investigation is still running.
    investigation_time_budget_seconds: float = 120.0
    evidence_max_chars: int = 1500  # per evidence chunk in the prompt

    # --- Evaluation (section 2.8) ---
    # LLM-as-judge model for python -m app.eval_investigation. Default: the same Haiku as the investigator
    # (cheap, but same-model judging is biased towards its own answers; the report says so).
    judge_model: str = "claude-haiku-5-5"

    # --- Internal API (section 2.7) ---
    # Shared secret that incident-service sends in X-Internal-Token. No default: the app refuses to
    # start without it, so the internal endpoint can never be left open by accident.
    internal_api_token: SecretStr | None = None

    log_level: str = "INFO"

    @field_validator("anthropic_api_key", "internal_api_token", mode="before")
    @classmethod
    def _blank_secret_is_no_secret(cls, value: object) -> object:
        # compose passes VAR="" when the host has none: treat that as "not set".
        return None if isinstance(value, str) and not value.strip() else value

    @model_validator(mode="after")
    def _time_budget_fits_poll_interval(self) -> "Settings":
        if self.investigation_time_budget_seconds * 1000 > self.kafka_max_poll_interval_ms / 2:
            raise ValueError(
                "INVESTIGATION_TIME_BUDGET_SECONDS must be at most half of KAFKA_MAX_POLL_INTERVAL_MS "
                "(the consumer would be removed from the group mid-investigation)"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    # Built once and reused, like a singleton bean.
    return Settings()
