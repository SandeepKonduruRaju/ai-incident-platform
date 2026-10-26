#!/usr/bin/env python3
"""Bumps k8s/overlays/gitops/kustomization.yaml to a new commit (sections 3.7/3.8; run by CI's gitops-bump job).

    python scripts/gitops-bump.py --sha <40-char commit sha>

- incident-service, investigation-worker and frontend: ALWAYS set to the commit SHA (every built commit is deployed).
- investigation-worker-ingest (the image of the worker-ingest Job) and the Job's synthetic-data-sha256
  annotation: changed ONLY when investigation-worker/data/synthetic changed. Argo CD re-runs the Job only when
  its spec changes, so an image bump without new data no longer triggers a 10-20 minute re-ingest. When the
  data does change, the Job re-runs with the image of this commit, which contains the new data.

The data hash comes from git's blob ids (git ls-tree), so it is the same on Windows and Linux whatever the
line endings of the checkout. Standard library only.
"""

import argparse
import hashlib
import re
import subprocess
import sys
from pathlib import Path

DATA_DIR = "investigation-worker/data/synthetic"
OVERLAY = Path("k8s/overlays/gitops/kustomization.yaml")
APP_IMAGES = ("incident-service", "investigation-worker", "frontend")
INGEST_IMAGE = "investigation-worker-ingest"
HASH_KEY = "incident-platform/synthetic-data-sha256"
_SHA = re.compile(r"[0-9a-f]{40}")


def data_hash(rev: str = "HEAD") -> str:
    """First 16 hex chars of the sha256 of `git ls-tree -r <rev> -- <data dir>` (modes, blob ids, paths)."""
    listing = subprocess.run(["git", "ls-tree", "-r", rev, "--", DATA_DIR], capture_output=True, check=True).stdout
    if not listing.strip():
        raise SystemExit(f"no files under {DATA_DIR} at {rev}")
    return hashlib.sha256(listing).hexdigest()[:16]


def set_tag(text: str, image: str, sha: str) -> str:
    """newTag of the images entry `- name: <image>` (exact name: investigation-worker != ...-ingest)."""
    pattern = re.compile(rf"(- name: {re.escape(image)}\r?\n[ \t]+newName: [^\r\n]+\r?\n[ \t]+newTag: )[0-9a-f]{{40}}")
    new_text, count = pattern.subn(lambda m: m.group(1) + sha, text)
    if count != 1:
        raise SystemExit(f"expected exactly one images entry for {image!r} with a 40-char newTag, found {count}")
    return new_text


def current_data_hash(text: str) -> str:
    match = re.search(rf'{re.escape(HASH_KEY)}: "([0-9a-f]{{16}})"', text)
    if not match:
        raise SystemExit(f"annotation {HASH_KEY} not found in {OVERLAY}")
    return match.group(1)


def bump(text: str, sha: str, new_data_hash: str) -> tuple[str, bool]:
    """(new text, whether the ingest image and data hash were bumped too)."""
    for image in APP_IMAGES:
        text = set_tag(text, image, sha)
    old_hash = current_data_hash(text)
    if old_hash == new_data_hash:
        return text, False
    text = set_tag(text, INGEST_IMAGE, sha)
    text = text.replace(f'{HASH_KEY}: "{old_hash}"', f'{HASH_KEY}: "{new_data_hash}"')
    return text, True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sha", required=True, help="full commit SHA the images were built from")
    parser.add_argument("--file", type=Path, default=OVERLAY)
    parser.add_argument("--rev", default="HEAD", help="git revision whose synthetic data is deployed")
    parser.add_argument("--data-hash", help="override the computed data hash (tests)")
    args = parser.parse_args(argv)
    if not _SHA.fullmatch(args.sha):
        parser.error("--sha must be a full 40-character lowercase commit SHA")

    with open(args.file, encoding="utf-8", newline="") as f:  # keep the file's line endings
        text = f.read()
    new_hash = args.data_hash or data_hash(args.rev)
    text, ingest_bumped = bump(text, args.sha, new_hash)
    with open(args.file, "w", encoding="utf-8", newline="") as f:
        f.write(text)

    print(f"app images -> {args.sha}")
    if ingest_bumped:
        print(f"synthetic data changed (hash {new_hash}): worker-ingest image -> {args.sha}, the Job will re-run")
    else:
        print(f"synthetic data unchanged (hash {new_hash}): worker-ingest left as is, the Job will not re-run")
    return 0


if __name__ == "__main__":
    sys.exit(main())
