"""The database: one SQLite file that remembers what each image in the
folder said, its hash, and every rename. Rows come out as plain dicts with
a few derived fields (region, media on disk, duplicates)."""
from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import sqlite3
from typing import Any, Callable, Iterator

from ..tools import iso as isotool
from ..tools import lang
from . import group

SCHEMA = """
CREATE TABLE IF NOT EXISTS images (
    id INTEGER PRIMARY KEY,
    path TEXT UNIQUE NOT NULL,
    size INTEGER NOT NULL,
    mtime REAL NOT NULL,
    format TEXT NOT NULL,
    status TEXT NOT NULL,
    error TEXT,
    disc_id TEXT,
    disc_key TEXT,
    disc_id_source TEXT,
    identifier TEXT,
    umd_data TEXT NOT NULL DEFAULT '{}',
    pspdb_status TEXT,
    pspdb_title TEXT,
    pspdb_identifier TEXT,
    pspdb_file TEXT,
    title TEXT,
    volume_id TEXT,
    iso_size INTEGER,
    sfo TEXT NOT NULL DEFAULT '{}',
    media TEXT NOT NULL DEFAULT '{}',
    media_extracted INTEGER NOT NULL DEFAULT 0,
    sha256 TEXT,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS images_disc_key ON images(disc_key);
CREATE TABLE IF NOT EXISTS hashes (
    path TEXT NOT NULL,
    size INTEGER NOT NULL,
    mtime REAL NOT NULL,
    sha256 TEXT NOT NULL,
    PRIMARY KEY (path, size, mtime)
);
CREATE TABLE IF NOT EXISTS renames (
    id INTEGER PRIMARY KEY,
    at TEXT NOT NULL,
    old_path TEXT NOT NULL,
    new_path TEXT NOT NULL,
    ok INTEGER NOT NULL,
    error TEXT
);
"""


def now_iso() -> str:
    """Return the current UTC timestamp in catalog-friendly form."""
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def disc_key_for(disc_id: str | None, path: str) -> str:
    """The id as it appears in URLs: ULUS-10404 when the disc has an id,
    else the volume id in ASCII letters, digits, . _ - only, else
    NOID-<8 hex> from the path."""
    if disc_id:
        key = isotool.canonical_id(disc_id) or re.sub(r"[^A-Za-z0-9_.-]", "", disc_id).strip(".")[:32]
        if key:
            return key.upper()
    return "NOID-" + hashlib.sha1(path.encode("utf-8", "surrogateescape")).hexdigest()[:8].upper()


def human_size(n: int | None) -> str:
    """Format a byte count for display."""
    if n is None:
        return "?"
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.1f} GB"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.0f} MB"
    return f"{n / 1000:.0f} kB"


class Library:
    """SQLite-backed view of the library folder and extracted media."""

    def __init__(self, db_path: str, library_dir: str, media_dir: str,
                 language_overrides: Callable[[], dict[str, list[str]]] | None = None):
        self.db_path = db_path
        self.library_dir = library_dir
        self.media_dir = media_dir
        # disc id -> codes, from the settings; read live so a change shows at once.
        self.language_overrides = language_overrides or (lambda: {})
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        os.makedirs(media_dir, exist_ok=True)
        with self.db() as con:
            con.executescript(SCHEMA)

    @contextlib.contextmanager
    def db(self) -> Iterator[sqlite3.Connection]:
        """Open a SQLite connection for the current thread."""
        try:
            con = sqlite3.connect(self.db_path, timeout=30)
            con.row_factory = sqlite3.Row
        except sqlite3.Error as exc:
            raise RuntimeError(f"database cannot be opened: {exc}") from None
        try:
            try:
                con.execute("PRAGMA journal_mode=WAL")
            except sqlite3.DatabaseError as exc:
                raise RuntimeError(f"database is not usable: {exc}") from None
            yield con
            try:
                con.commit()
            except sqlite3.DatabaseError as exc:
                con.rollback()
                raise RuntimeError(f"database write failed: {exc}") from None
        except sqlite3.DatabaseError as exc:
            con.rollback()
            raise RuntimeError(f"database error: {exc}") from None
        finally:
            con.close()

    # -- rows ----------------------------------------------------------------
    def _row(self, r: sqlite3.Row) -> dict[str, Any]:
        d = dict(r)
        d["sfo"] = json.loads(d["sfo"])
        d["media"] = json.loads(d["media"])
        d["umd_data"] = json.loads(d["umd_data"])
        d["region"] = (isotool.region_of(d["disc_key"])
                       if d["disc_id_source"] in ("umd_data", "sfo") else "unknown")
        d["abs_path"] = os.path.join(self.library_dir, d["path"])
        d["name"] = os.path.basename(d["path"])
        d["size_human"] = human_size(d["size"])
        d["media_dir"] = os.path.join(self.media_dir, str(d["id"]))
        d["has_media"] = {name: bool(d["media_extracted"]) and name in d["media"]
                          and os.path.exists(os.path.join(d["media_dir"], name))
                          for name in isotool.MEDIA_FILES}
        d["has_mp4"] = os.path.exists(os.path.join(d["media_dir"], "ICON1.mp4"))
        d["mtime_iso"] = dt.datetime.fromtimestamp(d["mtime"], dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        overrides = self.language_overrides()
        override = overrides.get(d["disc_key"]) or overrides.get((d["disc_id"] or "").upper())
        d["languages"] = lang.languages_of(d["sfo"], d["region"], override)
        d["languages_from"] = ("override" if override else "sfo" if lang.from_sfo(d["sfo"])
                               else "region" if d["languages"] else "none")
        d["game_key"] = group.game_key(d["title"] or os.path.splitext(d["name"])[0])
        return d

    def all(self) -> list[dict[str, Any]]:
        """Return all image rows with derived fields for UI and catalog use."""
        with self.db() as con:
            rows = [self._row(r) for r in con.execute(
                "SELECT * FROM images ORDER BY disc_key, mtime DESC, path")]
        # A disc id that appears twice is flagged on both rows; the newest
        # file is the primary one, the one the catalog and /umd/<id> serve.
        seen: dict[str, int] = {}
        for row in rows:
            seen[row["disc_key"]] = seen.get(row["disc_key"], 0) + 1
        primaries: set[str] = set()
        for row in rows:
            row["duplicate"] = seen[row["disc_key"]] > 1
            row["primary"] = row["disc_key"] not in primaries
            primaries.add(row["disc_key"])
        return rows

    def get(self, image_id: int) -> dict[str, Any] | None:
        """Return one image row by id, or None."""
        for row in self.all():
            if row["id"] == image_id:
                return row
        return None

    def by_key(self, disc_key: str) -> dict[str, Any] | None:
        """The primary image for a disc key: the newest by mtime."""
        for row in self.all():
            if row["disc_key"] == disc_key and row["primary"]:
                return row
        return None

    def games(self) -> list[dict[str, Any]]:
        """Return images grouped into games."""
        return group.games(self.all())

    def counts(self) -> dict[str, int]:
        """Return library summary counters."""
        rows = self.all()
        return {
            "images": len(rows),
            "games": len({r["game_key"] for r in rows}),
            "ok": sum(r["status"] == "ok" for r in rows),
            "errors": sum(r["status"] != "ok" for r in rows),
            "unhashed": sum(r["sha256"] is None and r["status"] == "ok" for r in rows),
            "duplicates": sum(r["duplicate"] for r in rows),
            "known_dumps": sum(r["pspdb_status"] == "known" for r in rows),
            "unknown_dumps": sum(r["pspdb_status"] == "unknown" for r in rows),
            "no_media": sum(r["status"] == "ok" and not r["has_media"]["ICON0.PNG"] for r in rows),
        }

    def known_files(self) -> dict[str, dict[str, Any]]:
        """Return known file metadata keyed by relative path."""
        with self.db() as con:
            return {r["path"]: dict(r) for r in con.execute(
                "SELECT id, path, size, mtime FROM images")}

    def touch(self, image_id: int, stamp: str) -> None:
        """Update the last-seen timestamp for an image."""
        with self.db() as con:
            con.execute("UPDATE images SET last_seen=? WHERE id=?", (stamp, image_id))

    def upsert(self, fields: dict[str, Any], image_id: int | None, stamp: str) -> int:
        """Insert or replace the columns in fields; the cached hash for these
        very bytes, if there is one, comes along."""
        with self.db() as con:
            cached = con.execute("SELECT sha256 FROM hashes WHERE path=? AND size=? AND mtime=?",
                                 (fields["path"], fields["size"], fields["mtime"])).fetchone()
            fields = dict(fields, sha256=cached["sha256"] if cached else None, last_seen=stamp)
            if image_id is None:
                fields["first_seen"] = stamp
                cols = ", ".join(fields)
                marks = ", ".join("?" * len(fields))
                cur = con.execute(f"INSERT INTO images ({cols}) VALUES ({marks})", tuple(fields.values()))
                return int(cur.lastrowid)
            sets = ", ".join(f"{k}=?" for k in fields)
            con.execute(f"UPDATE images SET {sets} WHERE id=?", (*fields.values(), image_id))
            return image_id

    def forget(self, image_id: int) -> None:
        """Remove an image row and its extracted media."""
        with self.db() as con:
            con.execute("DELETE FROM images WHERE id=?", (image_id,))
        shutil.rmtree(os.path.join(self.media_dir, str(image_id)), ignore_errors=True)

    def set_pspdb(self, image_id: int, status: str | None, title: str | None = None,
                  identifier: str | None = None, file: str | None = None) -> None:
        """Store pspdb verification status for one image."""
        with self.db() as con:
            con.execute("UPDATE images SET pspdb_status=?, pspdb_title=?, pspdb_identifier=?, pspdb_file=? "
                        "WHERE id=?", (status, title, identifier, file, image_id))

    def set_media(self, image_id: int, media: dict[str, int]) -> None:
        """Store extracted media metadata for one image."""
        with self.db() as con:
            con.execute("UPDATE images SET media=?, media_extracted=1 WHERE id=?",
                        (json.dumps(media), image_id))

    # -- hashes --------------------------------------------------------------
    def cached_hash(self, path: str, size: int, mtime: float) -> str | None:
        """Return a cached SHA-256 for these file bytes, if present."""
        with self.db() as con:
            r = con.execute("SELECT sha256 FROM hashes WHERE path=? AND size=? AND mtime=?",
                            (path, size, mtime)).fetchone()
        return r["sha256"] if r else None

    def set_hash(self, image_id: int, path: str, size: int, mtime: float, digest: str) -> None:
        """Store a SHA-256 in the hash cache and image row atomically."""
        with self.db() as con:
            con.execute("INSERT OR REPLACE INTO hashes (path, size, mtime, sha256) VALUES (?,?,?,?)",
                        (path, size, mtime, digest))
            con.execute("UPDATE images SET sha256=? WHERE id=?", (digest, image_id))

    # -- renames (the database following the file) ----------------------------
    def move(self, image_id: int, new_path: str) -> None:
        """Move an image row and its cached hash to a new relative path."""
        with self.db() as con:
            row = con.execute("SELECT path, size, mtime FROM images WHERE id=?", (image_id,)).fetchone()
            if row is None:
                return
            con.execute("UPDATE images SET path=? WHERE id=?", (new_path, image_id))
            con.execute("UPDATE OR REPLACE hashes SET path=? WHERE path=? AND size=? AND mtime=?",
                        (new_path, row["path"], row["size"], row["mtime"]))
            # A disc with no id is keyed by its path; keep it findable.
            con.execute("UPDATE images SET disc_key=? WHERE id=? AND disc_key LIKE 'NOID-%'",
                        (disc_key_for(None, new_path), image_id))

    def record_rename(self, old_path: str, new_path: str, ok: bool, error: str | None = None) -> None:
        """Append one rename attempt to history."""
        with self.db() as con:
            con.execute("INSERT INTO renames (at, old_path, new_path, ok, error) VALUES (?,?,?,?,?)",
                        (now_iso(), old_path, new_path, int(ok), error))

    def rename_history(self, limit: int = 100) -> list[dict[str, Any]]:
        """Return recent rename attempts, newest first."""
        with self.db() as con:
            return [dict(r) for r in con.execute(
                "SELECT * FROM renames ORDER BY id DESC LIMIT ?", (limit,))]
