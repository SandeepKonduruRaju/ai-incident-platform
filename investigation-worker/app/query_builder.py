"""Turn an incident into one search spec per evidence type (pure: no I/O, easy to unit test).

Logs and metrics are only useful if they come from the affected service around the time of the
incident, so they get a service filter and a time window. Runbooks and past incidents are timeless
knowledge, often written for another service, so they are searched without those filters.
"""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.events import IncidentCreatedPayload

DEFAULT_WINDOW_BEFORE = timedelta(hours=2)
DEFAULT_WINDOW_AFTER = timedelta(minutes=30)

# Words of 3+ letters/digits, keeping inner dots, dashes and underscores ("orders-db", "v4.1.2", "db_pool").
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*[A-Za-z0-9]")


@dataclass(frozen=True)
class QuerySpec:
    source_type: str                # log | metric | runbook | incident
    text: str                       # for the embedding (natural language)
    keyword_query: str              # for websearch_to_tsquery (OR of the words)
    service: str | None = None
    time_from: datetime | None = None
    time_to: datetime | None = None


def incident_text(incident: IncidentCreatedPayload) -> str:
    return "\n".join(part for part in (incident.title, incident.description) if part)


def to_keyword_query(text: str) -> str:
    """'HikariPool timeouts on orders-db' -> 'HikariPool or timeouts or on or orders-db'.

    websearch_to_tsquery ANDs plain words, so a whole incident description would match almost nothing.
    OR-ing them lets ts_rank score chunks by how many (stemmed) words they share. Stop words like "on"
    are dropped by PostgreSQL's 'english' config. Duplicates are removed, first occurrence wins.
    """
    tokens = dict.fromkeys(token.lower() for token in _TOKEN.findall(text) if token.lower() != "or")
    return " or ".join(tokens)


def build_queries(
    incident: IncidentCreatedPayload,
    *,
    window_before: timedelta = DEFAULT_WINDOW_BEFORE,
    window_after: timedelta = DEFAULT_WINDOW_AFTER,
) -> list[QuerySpec]:
    text = incident_text(incident)
    keywords = to_keyword_query(text)
    time_from = incident.createdAt - window_before
    time_to = incident.createdAt + window_after
    service = incident.affectedService  # None when the reporter did not know: then no service filter

    return [
        QuerySpec("log", text, keywords, service=service, time_from=time_from, time_to=time_to),
        QuerySpec("metric", text, keywords, service=service, time_from=time_from, time_to=time_to),
        QuerySpec("runbook", text, keywords),
        QuerySpec("incident", text, keywords),
    ]
