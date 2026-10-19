"""Split evidence documents into chunks: the units we embed, store in worker.chunks and later retrieve.

Why chunk at all? One vector per whole runbook averages "symptoms", "diagnosis" and "mitigation" into
one blurry point; one vector per section matches a question about mitigation much more precisely.
Too small is bad too: a single log line has little context. So the size depends on the source type:

    runbook   one chunk per "## " section, with the runbook title prepended (context for the section)
    log       windows of up to LOG_WINDOW_SIZE lines per tenant + service + scenario
    metric    one chunk per summary (already short and self-contained)
    incident  one chunk per past incident (title + root cause + fix belong together)

Chunk ids are uuid5(namespace, "tenant:source_id:chunk_index"): the same input always gives the same
id, so re-ingesting updates rows (ON CONFLICT (id)) instead of duplicating them.
"""

import re
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

# Fixed namespace for chunk ids. Never change it: every existing id would change with it.
CHUNK_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://github.com/SandeepKonduruRaju/ai-incident-platform/chunks")

LOG_WINDOW_SIZE = 10

_SECTION_HEADING = re.compile(r"^## +(.+?)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class Chunk:
    tenant_id: str
    source_type: str  # log | metric | runbook | incident (matches the CHECK constraint)
    service: str | None
    source_id: str
    chunk_index: int
    ts: datetime | None
    content: str

    @property
    def id(self) -> uuid.UUID:
        return chunk_id(self.tenant_id, self.source_id, self.chunk_index)


def chunk_id(tenant_id: str, source_id: str, chunk_index: int) -> uuid.UUID:
    return uuid.uuid5(CHUNK_NAMESPACE, f"{tenant_id}:{source_id}:{chunk_index}")


def _parse_ts(value: str | None) -> datetime | None:
    # The synthetic data uses "2026-09-01T00:25:12Z"; fromisoformat accepts the "Z" since Python 3.11.
    return datetime.fromisoformat(value) if value else None


# ---------------------------------------------------------------- runbooks


def _runbook_sections(markdown: str) -> list[tuple[str, str]]:
    """(section name, body) pairs. Text before the first "## " (minus the "# " title line) is "Overview"."""
    headings = list(_SECTION_HEADING.finditer(markdown))
    preamble_end = headings[0].start() if headings else len(markdown)
    preamble = "\n".join(line for line in markdown[:preamble_end].splitlines() if not line.startswith("# "))

    sections = [("Overview", preamble.strip())]
    for i, heading in enumerate(headings):
        body_end = headings[i + 1].start() if i + 1 < len(headings) else len(markdown)
        sections.append((heading.group(1), markdown[heading.end() : body_end].strip()))
    return [(name, body) for name, body in sections if body]  # skip empty sections


def chunk_runbook(doc: dict) -> list[Chunk]:
    return [
        Chunk(
            tenant_id=doc["tenant_id"],
            source_type="runbook",
            service=doc.get("service"),
            source_id=doc["source_id"],
            chunk_index=index,
            ts=None,
            # The title makes each section self-describing: "Mitigation" alone does not say of what.
            content=f"{doc['title']} — {name}\n{body}",
        )
        for index, (name, body) in enumerate(_runbook_sections(doc["content"]))
    ]


# ---------------------------------------------------------------- logs


def _log_scenario(log: dict) -> str:
    """'LOG-acme-db_pool_exhausted-003' -> 'db_pool_exhausted'; 'LOG-acme-noise-0034' -> 'noise'."""
    prefix = f"LOG-{log['tenant_id']}-"
    return log["source_id"].removeprefix(prefix).rsplit("-", 1)[0]


def chunk_logs(logs: list[dict], window_size: int = LOG_WINDOW_SIZE) -> list[Chunk]:
    """Group lines by (tenant, service, scenario), sort each group by time and cut it into windows.

    One window becomes one chunk with source_id 'LOG-<tenant>-<scenario>-<service>' and
    chunk_index = window number. It starts with the golden ids' prefix 'LOG-<tenant>-<scenario>-',
    so evaluation can map a retrieved window back to its scenario.
    """
    groups: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for log in logs:
        groups[(log["tenant_id"], log["service"], _log_scenario(log))].append(log)

    chunks: list[Chunk] = []
    for (tenant, service, scenario), lines in sorted(groups.items()):
        lines.sort(key=lambda line: (line["ts"], line["source_id"]))
        for index, start in enumerate(range(0, len(lines), window_size)):
            window = lines[start : start + window_size]
            body = "\n".join(f"{line['ts']} {line['level']} {line['message']}" for line in window)
            chunks.append(
                Chunk(
                    tenant_id=tenant,
                    source_type="log",
                    service=service,
                    source_id=f"LOG-{tenant}-{scenario}-{service}",
                    chunk_index=index,
                    ts=_parse_ts(window[0]["ts"]),  # the window's first line
                    content=f"Logs from {service}:\n{body}",
                )
            )
    return chunks


# ---------------------------------------------------------------- metrics and incidents


def chunk_metric(doc: dict) -> list[Chunk]:
    return [
        Chunk(
            tenant_id=doc["tenant_id"],
            source_type="metric",
            service=doc.get("service"),
            source_id=doc["source_id"],
            chunk_index=0,
            ts=_parse_ts(doc.get("ts")),
            content=doc["summary"],
        )
    ]


def chunk_incident(doc: dict) -> list[Chunk]:
    return [
        Chunk(
            tenant_id=doc["tenant_id"],
            source_type="incident",
            service=doc.get("service"),
            source_id=doc["source_id"],
            chunk_index=0,
            ts=_parse_ts(doc.get("ts")),
            content=f"Past incident: {doc['title']}\nRoot cause: {doc['root_cause']}\nFix: {doc['fix']}",
        )
    ]


def chunk_dataset(
    *,
    runbooks: list[dict] = (),
    logs: list[dict] = (),
    metrics: list[dict] = (),
    incidents: list[dict] = (),
) -> list[Chunk]:
    chunks: list[Chunk] = []
    for doc in runbooks:
        chunks.extend(chunk_runbook(doc))
    chunks.extend(chunk_logs(list(logs)))
    for doc in metrics:
        chunks.extend(chunk_metric(doc))
    for doc in incidents:
        chunks.extend(chunk_incident(doc))
    return chunks
