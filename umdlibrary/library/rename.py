"""Renaming images after what the disc says: a pattern, a dry run that
shows every from -> to with its conflicts, and an apply that renames only
what the dry run called clean. Never overwrites, never leaves the folder,
logs every rename, and the database follows the file."""
from __future__ import annotations

import errno
import logging
import os
import re
import string
import unicodedata
from typing import Any

from ..jobs.runner import Job
from .db import Library

log = logging.getLogger("rename")

MAX_NAME = 120
DEFAULT_PATTERN = "{title} [{disc_id}].{ext}"
FIELDS = ("title", "disc_id", "region", "ext", "format", "name", "disc_version", "category")

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_BAD = re.compile(r'[/\\:*?"<>|]')


def safe_filename(stem: str, ext: str) -> str:
    """stem.ext as a FAT-friendly, ASCII file name: no separators, no
    control characters, no reserved characters, at most MAX_NAME characters,
    no trailing dot or space."""
    text = unicodedata.normalize("NFKD", stem).encode("ascii", "ignore").decode("ascii")
    text = _BAD.sub("", _CONTROL.sub(" ", text))
    text = " ".join(text.split())
    text = text.rstrip(". ")
    if not text:
        text = "disc"
    ext = _BAD.sub("", _CONTROL.sub("", ext)).strip(". ").lower() or "iso"
    room = MAX_NAME - len(ext) - 1
    text = text[:room].rstrip(". ")
    return f"{text}.{ext}"


def check_pattern(pattern: str) -> None:
    """Raises ValueError when the pattern names a field that does not exist
    or has no field at all."""
    names = []
    try:
        for _, field, _, _ in string.Formatter().parse(pattern):
            if field is not None:
                names.append(field)
    except ValueError as exc:
        raise ValueError(f"bad pattern: {exc}") from None
    if not names:
        raise ValueError("the pattern has no field, every file would get the same name")
    unknown = [n for n in names if n.split("!")[0].split(":")[0] not in FIELDS]
    if unknown:
        raise ValueError(f"unknown field(s) {', '.join(unknown)}; known: {', '.join(FIELDS)}")


def target_name(row: dict[str, Any], pattern: str) -> str:
    """The file name the pattern gives one image."""
    check_pattern(pattern)
    stem, ext = os.path.splitext(row["name"])
    values = {
        "title": row.get("title") or stem,
        "disc_id": row["disc_key"],
        "region": row.get("region") or "unknown",
        "ext": ext.lstrip(".").lower() or row["format"],
        "format": row["format"],
        "name": stem,
        "disc_version": str(row.get("sfo", {}).get("DISC_VERSION") or "1.00"),
        "category": str(row.get("sfo", {}).get("CATEGORY") or "UG"),
    }
    rendered = pattern.format_map(values)
    if "." in rendered:
        stem, ext = rendered.rsplit(".", 1)
    else:
        stem, ext = rendered, values["ext"]
    return safe_filename(stem, ext)


def plan(library: Library, pattern: str) -> list[dict[str, Any]]:
    """The dry run: one entry per image, with status clean | unchanged |
    conflict | skipped and a reason."""
    check_pattern(pattern)
    rows = library.all()
    entries = []
    targets: dict[str, list[int]] = {}
    for row in rows:
        entry = {"id": row["id"], "from": row["name"], "to": None, "status": "skipped",
                 "reason": "", "disc_id": row["disc_key"], "title": row["title"]}
        if row["status"] != "ok":
            entry["reason"] = f"not readable: {row['error']}"
            entries.append(entry)
            continue
        try:
            entry["to"] = target_name(row, pattern)
        except (KeyError, ValueError, IndexError) as exc:
            entry["reason"] = f"pattern failed: {exc}"
            entries.append(entry)
            continue
        targets.setdefault(entry["to"].lower(), []).append(row["id"])
        entries.append(entry)
    existing = ({n.lower() for n in os.listdir(library.library_dir)}
                if os.path.isdir(library.library_dir) else set())
    for entry in entries:
        if entry["to"] is None:
            continue
        if entry["to"] == entry["from"]:
            entry["status"], entry["reason"] = "unchanged", "already named so"
        elif len(targets[entry["to"].lower()]) > 1:
            entry["status"], entry["reason"] = "conflict", "two images want this name"
        elif entry["to"].lower() in existing and entry["to"].lower() != entry["from"].lower():
            entry["status"], entry["reason"] = "conflict", "a file of this name exists"
        else:
            entry["status"] = "clean"
    return entries


def apply(library: Library, pattern: str, job: Job | None = None,
          only_ids: set[int] | None = None) -> dict[str, Any]:
    """Rename every clean entry of a fresh dry run. The plan is made again
    here so a file that changed since the table was shown is not touched."""
    entries = [e for e in plan(library, pattern) if e["status"] == "clean"]
    if only_ids is not None:
        entries = [e for e in entries if e["id"] in only_ids]
    renamed, failed = [], []
    if job:
        job.set_progress(0, len(entries), f"{len(entries)} to rename")
    folder = os.path.abspath(library.library_dir)
    rows = {r["id"]: r for r in library.all()}
    for i, entry in enumerate(entries):
        src = os.path.join(library.library_dir, entry["from"])
        dst = os.path.join(library.library_dir, entry["to"])
        try:
            row = rows.get(entry["id"])
            if row is None:
                raise FileNotFoundError(errno.ENOENT, "image disappeared from the database", src)
            if os.path.dirname(os.path.abspath(dst)) != folder:
                raise OSError(errno.EINVAL, "target leaves the folder")
            st = os.stat(src)
            if st.st_size != row["size"] or abs(st.st_mtime - row["mtime"]) >= 1e-6:
                raise OSError(errno.EAGAIN, "source changed since the dry run")
            if os.path.lexists(dst):
                raise FileExistsError(errno.EEXIST, "target exists", dst)
            os.rename(src, dst)
        except OSError as exc:
            msg = f"{exc.strerror or exc}" + (" (is the library mounted read-only?)"
                                             if exc.errno in (errno.EROFS, errno.EACCES, errno.EPERM) else "")
            library.record_rename(entry["from"], entry["to"], False, msg)
            log.error("rename %s -> %s failed: %s", entry["from"], entry["to"], msg)
            failed.append({**entry, "error": msg})
            if job:
                job.log(f"FAILED {entry['from']} -> {entry['to']}: {msg}")
        else:
            library.move(entry["id"], entry["to"])
            library.record_rename(entry["from"], entry["to"], True)
            log.info("renamed %s -> %s", entry["from"], entry["to"])
            renamed.append(entry)
            if job:
                job.log(f"{entry['from']} -> {entry['to']}")
        if job:
            job.set_progress(i + 1, len(entries), entry["to"])
    return {"renamed": len(renamed), "failed": len(failed), "failures": failed}
