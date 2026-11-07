"""Scanning: bring the database in step with the folder. New and changed
images are read (and their media extracted), gone ones are forgotten.
Top level only: the library is one folder."""
from __future__ import annotations

import json
import logging
import os
import shutil
from typing import Any

from ..jobs.runner import Job
from ..tools import iso as isotool
from . import media
from .db import Library, disc_key_for, now_iso

log = logging.getLogger("scan")


def list_files(library: Library) -> list[tuple[str, int, float]]:
    """(name, size, mtime) of every .iso/.cso in the folder."""
    out = []
    try:
        names = os.listdir(library.library_dir)
    except FileNotFoundError:
        raise RuntimeError(f"library folder {library.library_dir} does not exist") from None
    except PermissionError:
        raise RuntimeError(f"library folder {library.library_dir} is not readable") from None
    except OSError as exc:
        raise RuntimeError(f"library folder {library.library_dir} cannot be read: {exc}") from None
    for name in sorted(names):
        if name.startswith(".") or isotool.image_format(name) is None:
            continue
        full = os.path.join(library.library_dir, name)
        try:
            if not os.path.isfile(full):
                continue
            st = os.stat(full)
        except FileNotFoundError:
            continue
        except PermissionError:
            out.append((name, 0, 0.0))
            continue
        except OSError as exc:
            raise RuntimeError(f"cannot stat {name}: {exc}") from None
        out.append((name, st.st_size, st.st_mtime))
    return out


def read_image(library: Library, path: str, size: int, mtime: float,
               stamp: str, image_id: int | None) -> int:
    """Read one image into the database; an unreadable one gets a row with
    status error, so the UI can show it."""
    full = os.path.join(library.library_dir, path)
    fields: dict[str, Any] = {
        "path": path, "size": size, "mtime": mtime,
        "format": isotool.image_format(path) or "iso", "status": "ok",
        "error": None, "disc_id": None, "disc_key": None, "disc_id_source": "none",
        "identifier": None, "umd_data": "{}", "title": None, "volume_id": None, "iso_size": None,
        "sfo": "{}", "media": "{}", "media_extracted": 0,
        # A changed file is another dump; what pspdb said about the old bytes is gone.
        "pspdb_status": None, "pspdb_title": None, "pspdb_identifier": None, "pspdb_file": None,
    }
    canonical = None
    try:
        info = isotool.read_info(full)
        if not info.has_psp_game:
            fields["status"] = "error"
            fields["error"] = "no PSP_GAME directory: not a PSP disc"
        canonical = info.canonical_id
        fields.update({
            "disc_id": info.disc_id, "disc_id_source": info.disc_id_source,
            "identifier": info.identifier, "umd_data": json.dumps(info.umd_data),
            "title": info.title, "volume_id": info.volume_id, "iso_size": info.iso_size,
            "sfo": json.dumps(info.sfo, ensure_ascii=False),
            "media": json.dumps(info.media),
        })
    except isotool.DiscError as exc:
        fields["status"] = "error"
        fields["error"] = str(exc)
    except OSError as exc:
        fields["status"] = "error"
        fields["error"] = f"cannot read: {exc}"
    fields["disc_key"] = disc_key_for(canonical, path)
    image_id = library.upsert(fields, image_id, stamp)
    if fields["status"] == "ok":
        media.extract(library, image_id)
    else:
        shutil.rmtree(os.path.join(library.media_dir, str(image_id)), ignore_errors=True)
    return image_id


def scan(library: Library, job: Job | None = None) -> dict[str, Any]:
    """Scan the library folder and reconcile image rows."""
    files = list_files(library)
    known = library.known_files()
    on_disk = {path for path, _, _ in files}
    added = changed = removed = unchanged = 0
    stamp = now_iso()
    total = len(files) + len(set(known) - on_disk)
    done = 0
    if job:
        job.set_progress(0, total, f"{len(files)} images in {library.library_dir}")
    for path, size, mtime in files:
        old = known.get(path)
        if old and old["size"] == size and abs(old["mtime"] - mtime) < 1e-6:
            unchanged += 1
            library.touch(old["id"], stamp)
        else:
            if job:
                job.log(("changed: " if old else "new: ") + path)
            read_image(library, path, size, mtime, stamp, old["id"] if old else None)
            if old:
                changed += 1
            else:
                added += 1
        done += 1
        if job:
            job.set_progress(done, total, path)
    for path in sorted(set(known) - on_disk):
        if job:
            job.log("gone: " + path)
        library.forget(known[path]["id"])
        removed += 1
        done += 1
        if job:
            job.set_progress(done, total, path)
    result = {"added": added, "changed": changed, "removed": removed, "unchanged": unchanged}
    log.info("scan: %s", result)
    if job:
        job.log(f"done: {result}")
    return result
