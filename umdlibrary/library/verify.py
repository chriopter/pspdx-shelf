"""Verify against pspdb (github.com/ryp/pspdb), a hash inventory of PSP
media: every *-ingest.json under catalog/iso/<version>/ names one dump by
SHA-256 and size. An image whose hash and size match is a known dump; one
that does not is unknown, which says nothing more than that. The records
come from a checkout on disk; nothing is fetched."""
from __future__ import annotations

import json
import logging
import os
from typing import Any

from ..jobs.runner import Job
from .db import Library

log = logging.getLogger("verify")

SUFFIX = "-ingest.json"


def records_dir(pspdb_dir: str) -> str | None:
    """Where the iso records are, given the repository root, its catalog
    directory, or the iso directory itself."""
    for candidate in (os.path.join(pspdb_dir, "catalog", "iso"), os.path.join(pspdb_dir, "iso"), pspdb_dir):
        if os.path.isdir(candidate) and any(
                os.path.isdir(os.path.join(candidate, d)) for d in os.listdir(candidate)):
            return candidate
    return None


def load_records(pspdb_dir: str) -> dict[str, dict[str, Any]]:
    """sha256 -> {size, title, identifier, file} for every iso record."""
    where = records_dir(pspdb_dir)
    if where is None:
        raise RuntimeError(f"no pspdb catalog/iso directory under {pspdb_dir}")
    out: dict[str, dict[str, Any]] = {}
    for version in sorted(os.listdir(where)):
        folder = os.path.join(where, version)
        if not os.path.isdir(folder):
            continue
        for name in sorted(os.listdir(folder)):
            if not name.endswith(SUFFIX):
                continue
            path = os.path.join(folder, name)
            try:
                with open(path, encoding="utf-8") as f:
                    record = json.load(f)
            except (OSError, ValueError) as exc:
                log.warning("pspdb record %s: %s", path, exc)
                continue
            sha = str(record.get("sha256") or name[:-len(SUFFIX)]).lower()
            meta = record.get("metadata") or {}
            out[sha] = {"size": record.get("size_bytes"), "title": meta.get("title"),
                        "identifier": meta.get("identifier"), "disc_id": meta.get("disc_id"),
                        "file": os.path.relpath(path, where)}
    return out


def verify(library: Library, pspdb_dir: str, job: Job | None = None) -> dict[str, Any]:
    """Verify hashed images against a local pspdb checkout."""
    if not pspdb_dir:
        raise RuntimeError("pspdb_dir is not set; point it at a checkout of ryp/pspdb in Settings")
    records = load_records(pspdb_dir)
    if job:
        job.log(f"{len(records)} pspdb iso records under {records_dir(pspdb_dir)}")
    rows = [r for r in library.all() if r["status"] == "ok"]
    known = unknown = waiting = 0
    if job:
        job.set_progress(0, len(rows), f"{len(rows)} images")
    for i, row in enumerate(rows):
        if not row["sha256"]:
            waiting += 1
            if job:
                job.log(f"{row['name']}: waiting for a hash")
        else:
            hit = records.get(row["sha256"])
            if hit and (hit["size"] in (None, row["size"])):
                known += 1
                library.set_pspdb(row["id"], "known", hit["title"], hit["identifier"], hit["file"])
                if job:
                    job.log(f"{row['name']}: known dump, {hit['identifier']} {hit['title']}")
            else:
                unknown += 1
                library.set_pspdb(row["id"], "unknown")
                if job:
                    job.log(f"{row['name']}: unknown"
                            + (" (hash matches but the size differs)" if hit else ""))
        if job:
            job.set_progress(i + 1, len(rows), row["name"])
    result = {"records": len(records), "known": known, "unknown": unknown, "waiting_for_hash": waiting}
    log.info("verify: %s", result)
    return result
