"""SHA-256 of image files, streamed in 4 MB pieces so a 4 GB image never
sits in memory, cached by path, size and mtime so a rescan costs nothing."""
from __future__ import annotations

import hashlib
from typing import Any

from ..jobs.runner import Job
from .db import Library, human_size

CHUNK = 4 * 1024 * 1024


def hash_image(library: Library, image_id: int, job: Job | None = None) -> str | None:
    """Hash one image, using the cache when the file bytes are known."""
    row = library.get(image_id)
    if row is None:
        return None
    path, size, mtime = row["path"], row["size"], row["mtime"]
    digest = library.cached_hash(path, size, mtime)
    if digest is None:
        h = hashlib.sha256()
        done = 0
        with open(row["abs_path"], "rb") as f:
            while True:
                chunk = f.read(CHUNK)
                if not chunk:
                    break
                h.update(chunk)
                done += len(chunk)
                if job:
                    job.set_progress(done, size, f"{path}: {human_size(done)} of {human_size(size)}")
        digest = h.hexdigest()
    library.set_hash(image_id, path, size, mtime, digest)
    return digest


def hash_missing(library: Library, job: Job | None = None) -> dict[str, Any]:
    """Hash every readable image that does not yet have SHA-256."""
    rows = [r for r in library.all() if r["sha256"] is None and r["status"] == "ok"]
    hashed = 0
    for i, row in enumerate(rows):
        if job:
            job.log(f"[{i + 1}/{len(rows)}] hashing {row['path']} ({row['size_human']})")
        digest = hash_image(library, row["id"], job)
        if job:
            job.log(f"{row['path']}: {digest}")
        hashed += 1
    if job:
        job.set_progress(1, 1, f"{hashed} hashed")
    return {"hashed": hashed}
