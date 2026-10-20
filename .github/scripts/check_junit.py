"""Summarise JUnit XML results in the GitHub job summary and fail on silently skipped tests.

Both services skip their Testcontainers tests when Docker is missing (`disabledWithoutDocker`, the
`docker_required` fixture). That is right on a laptop, but in CI a skipped integration test would look
green while testing nothing. This script makes CI prove they ran:

    --require-passed X   at least one test whose classname contains X must have passed
    --allow-skip REGEX   skips are allowed only if their message matches one of these patterns

    python .github/scripts/check_junit.py incident-service/target/surefire-reports \
        --title "incident-service" --require-passed IncidentApiIntegrationTest

Standard library only, so it runs on the bare runner Python in every job.
"""

import argparse
import os
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Case:
    classname: str
    name: str
    outcome: str   # passed | failed | error | skipped
    message: str
    seconds: float


def _outcome(element: ET.Element) -> tuple[str, str]:
    for tag, outcome in (("failure", "failed"), ("error", "error"), ("skipped", "skipped")):
        child = element.find(tag)
        if child is not None:
            return outcome, (child.get("message") or child.text or "").strip()
    return "passed", ""


def read_cases(paths: list[Path]) -> list[Case]:
    files = [f for p in paths for f in (sorted(p.glob("*.xml")) if p.is_dir() else [p])]
    cases = []
    for file in files:
        for element in ET.parse(file).getroot().iter("testcase"):
            outcome, message = _outcome(element)
            cases.append(Case(element.get("classname", ""), element.get("name", ""), outcome, message,
                              float(element.get("time") or 0)))
    return cases


def problems(cases: list[Case], require_passed: list[str], allow_skip: list[str]) -> list[str]:
    found = []
    if not cases:
        found.append("no test results found")
    for needle in require_passed:
        if not any(c.outcome == "passed" and needle in c.classname for c in cases):
            found.append(f"no passed test in a class matching '{needle}' (skipped or not run?)")
    for c in cases:
        if c.outcome == "skipped" and not any(re.search(p, c.message) for p in allow_skip):
            found.append(f"unexpected skip: {c.classname}.{c.name}: {c.message[:150]}")
    return found


def summary(title: str, cases: list[Case], found: list[str]) -> str:
    counts = Counter(c.outcome for c in cases)
    total_seconds = sum(c.seconds for c in cases)
    lines = [
        f"### {'✅' if not found and not counts['failed'] + counts['error'] else '❌'} {title}",
        "",
        "| tests | passed | failed | errors | skipped | time |",
        "|---|---|---|---|---|---|",
        f"| {len(cases)} | {counts['passed']} | {counts['failed']} | {counts['error']} | {counts['skipped']} | {total_seconds:.0f} s |",
    ]
    failing = [c for c in cases if c.outcome in ("failed", "error")]
    if failing:
        lines += ["", "**Failed:**"] + [f"- `{c.classname}.{c.name}`: {c.message[:200]}" for c in failing[:20]]
    skipped = [c for c in cases if c.outcome == "skipped"]
    if skipped:
        lines += ["", "**Skipped:**"] + [f"- `{c.classname}.{c.name}`: {c.message[:150]}" for c in skipped]
    if found:
        lines += ["", "**CI check failed:**"] + [f"- {p}" for p in found]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("paths", nargs="+", type=Path, help="JUnit XML files or directories of them")
    parser.add_argument("--title", default="Tests")
    parser.add_argument("--require-passed", action="append", default=[])
    parser.add_argument("--allow-skip", action="append", default=[])
    args = parser.parse_args(argv)

    cases = read_cases(args.paths)
    found = problems(cases, args.require_passed, args.allow_skip)
    text = summary(args.title, cases, found)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows consoles default to cp1252
    print(text)
    if step_summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(step_summary, "a", encoding="utf-8") as f:
            f.write(text)
    failed = any(c.outcome in ("failed", "error") for c in cases)
    return 1 if found or failed else 0


if __name__ == "__main__":
    sys.exit(main())
