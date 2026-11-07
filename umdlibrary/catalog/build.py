"""Building the catalog: catalog.json, apps/<id>/ media and one .pspdx per
disc into a temporary directory, checked against the vendored schemas, then
swapped into place, so what is served is always a whole, valid build."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import os
import shutil
import tempfile
from typing import Any

from ..jobs.runner import Job
from ..library.db import Library
from . import manifest, validate

log = logging.getLogger("catalog")

CATALOG_DIR = "catalog"       # <out>/catalog/catalog.json, apps/, pspdx/
REPORT = "build.json"


def generated_now() -> str:
    """Return the current UTC generation timestamp."""
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def media_for(row: dict[str, Any], app_id: str) -> tuple[dict[str, Any], list[tuple[str, str]]]:
    """(media field -> served path, [(source file, served path)]) for the
    media files of one image, named by their bytes as the reference builder
    does: a client caches a picture by the name it fetched it under."""
    fields: dict[str, Any] = {}
    copies: list[tuple[str, str]] = []
    for name, (field, stem, suffix) in manifest.MEDIA_FIELDS.items():
        if not row["has_media"].get(name):
            continue
        src = os.path.join(row["media_dir"], name)
        h = hashlib.sha256()
        with open(src, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        served = f"apps/{app_id}/{stem}-{h.hexdigest()[:8]}{suffix}"
        copies.append((src, served))
        if field == "screenshots":
            fields.setdefault("screenshots", []).append(served)
        else:
            fields[field] = served
    return fields, copies


def preview(library: Library, public_url: str, publishers: dict[str, str]) -> dict[str, Any]:
    """The catalog as the next build would write it, without touching disk;
    the Catalog page shows it and says who is waiting for a hash."""
    apps, skipped = [], []
    for row in library.all():
        reason = skip_reason(row)
        if reason:
            skipped.append({"id": row["id"], "name": row["name"], "reason": reason})
            continue
        fields, _ = media_for(row, manifest.our_id(row["disc_key"]))
        apps.append(manifest.app_entry(row, public_url, publishers, fields or None))
    doc = manifest.catalog_document(apps, generated_now())
    return {"catalog": doc, "skipped": skipped, "problems": validate.catalog_problems(doc)}


def skip_reason(row: dict[str, Any]) -> str | None:
    """Return why a row is not publishable, or None."""
    if row["status"] != "ok":
        return f"not readable: {row['error']}"
    if not row["primary"]:
        return "an older duplicate of this disc id; the newest file is listed"
    if not row.get("sha256"):
        return "waiting for a hash"
    return None


def build(library: Library, public_url: str, publishers: dict[str, str],
          out_dir: str, job: Job | None = None) -> dict[str, Any]:
    """Write a complete catalog under <out_dir>/catalog, atomically. Raises
    when the result would not validate; the previous build stays."""
    rows = library.all()
    apps, skipped, copies_all, manifests = [], [], [], {}
    total = len(rows)
    if job:
        job.set_progress(0, total + 2, f"{total} images")
    for i, row in enumerate(rows):
        reason = skip_reason(row)
        if reason:
            skipped.append({"id": row["id"], "name": row["name"], "reason": reason})
            if job:
                job.log(f"skip {row['name']}: {reason}")
        else:
            app_id = manifest.our_id(row["disc_key"])
            fields, copies = media_for(row, app_id)
            apps.append(manifest.app_entry(row, public_url, publishers, fields or None))
            copies_all.extend(copies)
            manifests[row["disc_key"]] = manifest.pspdx_manifest(row, public_url, publishers)
            if job:
                job.log(f"{row['name']} -> {app_id}, {len(copies)} media files")
        if job:
            job.set_progress(i + 1, total + 2, row["name"])
    generated = generated_now()
    doc = manifest.catalog_document(apps, generated)
    problems = validate.catalog_problems(doc)
    for key, m in manifests.items():
        problems += [f"{key}.pspdx {p}" for p in validate.manifest_problems(m)]
    if problems:
        if job:
            for p in problems:
                job.log("schema: " + p)
        raise RuntimeError(f"the catalog does not validate ({len(problems)} problems); "
                           "nothing was published")
    if job:
        job.set_progress(total + 1, total + 2, "writing")
    os.makedirs(out_dir, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix=".catalog-build-", dir=out_dir)
    try:
        for src, served in copies_all:
            dst = os.path.join(tmp, *served.split("/"))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copyfile(src, dst)
        os.makedirs(os.path.join(tmp, "pspdx"), exist_ok=True)
        for key, m in manifests.items():
            with open(os.path.join(tmp, "pspdx", f"{key}.pspdx"), "w", encoding="utf-8") as f:
                json.dump(m, f, indent=2, ensure_ascii=False)
                f.write("\n")
        # Compact separators, as the reference catalog: a PSP holds it in RAM.
        with open(os.path.join(tmp, "catalog.json"), "w", encoding="utf-8") as f:
            f.write(json.dumps(doc, ensure_ascii=False, separators=(",", ":")) + "\n")
        report = {"generated_at": generated, "apps": len(apps), "skipped": skipped,
                  "media_files": len(copies_all), "public_url": public_url,
                  "problems": []}
        with open(os.path.join(tmp, REPORT), "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        target = os.path.join(out_dir, CATALOG_DIR)
        old = target + ".old"
        shutil.rmtree(old, ignore_errors=True)
        if os.path.exists(target):
            os.rename(target, old)
        os.rename(tmp, target)
        shutil.rmtree(old, ignore_errors=True)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    if job:
        job.set_progress(total + 2, total + 2, "published")
        job.log(f"published {len(apps)} apps, {len(copies_all)} media files, "
                f"{len(skipped)} skipped, to {target}")
    log.info("catalog: %d apps published to %s", len(apps), target)
    return report


def published(out_dir: str) -> dict[str, Any] | None:
    """The report of the build that is being served, or None."""
    path = os.path.join(out_dir, CATALOG_DIR, REPORT)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def published_catalog(out_dir: str) -> dict[str, Any] | None:
    """Return the published catalog JSON, or None."""
    path = os.path.join(out_dir, CATALOG_DIR, "catalog.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)
