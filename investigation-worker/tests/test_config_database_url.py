"""DATABASE_URL or its parts (section 3.6: on ECS the RDS password is injected on its own)."""

import pytest
from pydantic import ValidationError

from app.config import Settings


def test_database_url_wins_when_set():
    settings = Settings(database_url="postgresql+asyncpg://u:p@h:5432/d", db_host="ignored")
    assert settings.database_url == "postgresql+asyncpg://u:p@h:5432/d"


def test_url_is_built_from_parts_with_the_password_url_encoded():
    settings = Settings(
        _env_file=None, db_host="db.internal", db_name="incident_platform", db_username="incident_app",
        db_password="p#ss:w/rd%!", db_ssl="require",
    )
    assert settings.database_url == (
        "postgresql+asyncpg://incident_app:p%23ss%3Aw%2Frd%25%21@db.internal:5432/incident_platform?ssl=require"
    )


def test_missing_url_and_parts_fails_fast(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValidationError, match="DATABASE_URL"):
        Settings(_env_file=None, db_host="db.internal")
