from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Typed configuration read from environment variables (like @ConfigurationProperties).

    Env var names are the field names in any case, e.g. KAFKA_BOOTSTRAP_SERVERS.
    """

    kafka_bootstrap_servers: str = "localhost:9092"
    kafka_topic: str = "incident-events"
    kafka_group_id: str = "investigation-worker"
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    # Built once and reused, like a singleton bean.
    return Settings()
