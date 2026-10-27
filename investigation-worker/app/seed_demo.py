"""DEV-ONLY demo seed for tenant "demo" (not a migration; never run by the services or the tests).

    python -m app.seed_demo --dry-run                     # what it would do; writes nothing
    python -m app.seed_demo                               # ingest the demo evidence, report the 8 incidents
    python -m app.seed_demo --skip-ingest --api-url http://localhost:8080

Steps:
  1. ingest the "demo" evidence (app.demo_data) through app.ingest.ingest_dataset, with log and metric times anchored
     to now (needs DATABASE_URL, like python -m app.ingest);
  2. get a dev token for tenant "demo" (role RESPONDER) from POST /api/v1/dev/token (incident-service "dev" profile);
  3. report each incident through the public API, POST /api/v1/incidents, unless one with the same title already
     exists in tenant "demo" (idempotent: a re-run skips them). Each POST also carries a fixed Idempotency-Key per
     scenario, so even a request whose answer got lost cannot create a duplicate;
  4. set the target status with PATCH /api/v1/incidents/{id}/status (new incidents start OPEN).
Creating an incident starts its investigation, so ingest first. Prints ids and titles, never the token.
"""

import argparse
import asyncio
import contextlib
import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from app.demo_data import DEMO_INCIDENTS, TENANT, DemoIncident, build_dataset

DEFAULT_API_URL = "http://localhost:8080"
SEED_SUBJECT = "demo-seed"
PAGE_SIZE = 100  # the API's maximum
IDEMPOTENCY_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://github.com/SandeepKonduruRaju/ai-incident-platform/demo-seed")


class SeedError(Exception):
    """An API call failed; the message has the status and the problem title, never a header or token."""


class Http(Protocol):
    def request(
        self, method: str, path: str, *, body: dict | None = None, token: str | None = None, headers: dict[str, str] | None = None
    ) -> Any: ...


class UrllibHttp:
    """JSON over HTTP with the standard library (no extra dependency for a dev script)."""

    def __init__(self, base_url: str, timeout: float = 15.0):
        self._base = base_url.rstrip("/")
        self._timeout = timeout

    def request(
        self, method: str, path: str, *, body: dict | None = None, token: str | None = None, headers: dict[str, str] | None = None
    ) -> Any:
        all_headers = {"Accept": "application/json", **(headers or {})}
        if token:
            all_headers["Authorization"] = f"Bearer {token}"
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            all_headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self._base + path, data=data, method=method, headers=all_headers)
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as response:  # noqa: S310 - http(s) URL from the CLI
                raw = response.read()
        except urllib.error.HTTPError as exc:
            title = ""
            with contextlib.suppress(ValueError):
                title = json.loads(exc.read() or b"{}").get("title", "")
            raise SeedError(f"{method} {path} -> HTTP {exc.code} {title}".strip()) from None
        except (urllib.error.URLError, TimeoutError) as exc:
            raise SeedError(f"{method} {path} -> cannot reach {self._base}: {exc}") from None
        return json.loads(raw) if raw else None


@dataclass(frozen=True)
class SeedResult:
    created: list[tuple[str, str]]  # (id, title)
    skipped: list[tuple[str, str]]
    planned: list[str]  # dry run: titles it would create


def incident_payload(incident: DemoIncident) -> dict[str, str]:
    """The POST /api/v1/incidents body (CreateIncidentRequest)."""
    return {
        "title": incident.title,
        "description": incident.description,
        "severity": incident.severity,
        "affectedService": incident.service,
    }


def idempotency_key(incident: DemoIncident) -> str:
    """Fixed per scenario: the same demo incident always sends the same key."""
    return str(uuid.uuid5(IDEMPOTENCY_NAMESPACE, f"{TENANT}:{incident.scenario}"))


def dev_token(http: Http) -> str:
    response = http.request("POST", "/api/v1/dev/token", body={"subject": SEED_SUBJECT, "tenantId": TENANT, "roles": ["RESPONDER"]})
    return response["accessToken"]


def existing_titles(http: Http, token: str) -> dict[str, str]:
    """{title: id} of every incident of tenant "demo" (all pages)."""
    titles: dict[str, str] = {}
    page = 0
    while True:
        result = http.request("GET", f"/api/v1/incidents?page={page}&size={PAGE_SIZE}", token=token)
        for item in result["items"]:
            titles.setdefault(item["title"], item["id"])
        page += 1
        if page >= result["totalPages"]:
            return titles


def seed_incidents(http: Http, *, dry_run: bool = False, out: Callable[[str], None] = print) -> SeedResult:
    """Report the demo incidents that do not exist yet and set their status (or, with dry_run, only say so)."""
    created: list[tuple[str, str]] = []
    skipped: list[tuple[str, str]] = []
    planned: list[str] = []
    try:
        token = dev_token(http)
        existing = existing_titles(http, token)
    except SeedError as exc:
        if not dry_run:
            raise
        out(f"(could not check existing incidents: {exc}; showing the full plan)")
        token, existing = "", {}

    for incident in DEMO_INCIDENTS:
        label = f"{incident.title}  [{incident.severity}, {incident.service}, -> {incident.status}]"
        if incident.title in existing:
            skipped.append((existing[incident.title], incident.title))
            out(f"skip     {existing[incident.title]}  {incident.title} (already exists)")
            continue
        if dry_run:
            planned.append(incident.title)
            out(f"would create  {label}")
            continue
        response = http.request(
            "POST",
            "/api/v1/incidents",
            body=incident_payload(incident),
            token=token,
            headers={"Idempotency-Key": idempotency_key(incident)},
        )
        incident_id = response["id"]
        if incident.status != "OPEN":
            http.request("PATCH", f"/api/v1/incidents/{incident_id}/status", body={"status": incident.status}, token=token)
        created.append((incident_id, incident.title))
        out(f"created  {incident_id}  {label}")
    return SeedResult(created, skipped, planned)


async def ingest_demo_evidence(anchor: datetime) -> dict[tuple[str, str], int]:
    from app.config import get_settings
    from app.db import create_engine
    from app.embedding import FastEmbedEmbedder
    from app.ingest import ingest_dataset

    settings = get_settings()
    embedder = FastEmbedEmbedder(settings.embedding_model, settings.embedding_cache_dir)
    engine = create_engine(settings.database_url)
    try:
        return dict(await ingest_dataset(engine, embedder, build_dataset(anchor)))
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DEV-ONLY: seed tenant 'demo' with evidence and 8 incidents.")
    parser.add_argument(
        "--api-url",
        default=os.environ.get("DEMO_API_URL", DEFAULT_API_URL),
        help=f"incident-service base URL (default {DEFAULT_API_URL}, or DEMO_API_URL)",
    )
    parser.add_argument("--dry-run", action="store_true", help="print what would happen; write nothing")
    parser.add_argument("--skip-ingest", action="store_true", help="do not (re-)ingest the demo evidence")
    args = parser.parse_args(argv)

    anchor = datetime.now(UTC)
    dataset = build_dataset(anchor)
    counts = {kind: len(docs) for kind, docs in dataset.items()}
    if args.dry_run:
        print(
            f"would ingest evidence for tenant '{TENANT}' anchored at {anchor:%Y-%m-%d %H:%M} UTC: {counts}"
            + (" (skipped: --skip-ingest)" if args.skip_ingest else "")
        )
    elif not args.skip_ingest:
        chunks = asyncio.run(ingest_demo_evidence(anchor))
        print(f"ingested {sum(chunks.values())} chunks for tenant '{TENANT}' (documents: {counts})")

    try:
        result = seed_incidents(UrllibHttp(args.api_url), dry_run=args.dry_run)
    except SeedError as exc:
        print(f"seed failed: {exc}", file=sys.stderr)
        return 1
    if args.dry_run:
        print(f"dry run: would create {len(result.planned)}, skip {len(result.skipped)}; nothing was written")
    else:
        print(f"done: created {len(result.created)}, skipped {len(result.skipped)} (already existed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
