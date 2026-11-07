"""One disc as PSPDX sees it: the catalog entry, the .pspdx manifest, and
the id the console will derive. Pure functions of a library row and the
settings; build.py writes the files."""
from __future__ import annotations

import datetime as dt
import re
from typing import Any

from ..library.db import human_size
from ..tools import iso as isotool
from .validate import CATALOG_SCHEMA_URL, PSPDX_SCHEMA_URL

NAME_MAX, SUMMARY_MAX, DESCRIPTION_MAX, AUTHOR_MAX = 40, 60, 2500, 60
MEDIA_FIELDS = {          # PSP_GAME file -> (catalog field, file stem, suffix)
    "ICON0.PNG": ("icon", "icon", ".png"),
    "PIC1.PNG": ("screenshots", "picture", ".png"),
    "PIC0.PNG": ("screenshots", "picture0", ".png"),
    "ICON1.PMF": ("video", "film", ".pmf"),
    "SND0.AT3": ("sound", "sound", ".at3"),
}


def _clean(text: str, limit: int, newlines: bool = False) -> str:
    """No control characters (a newline only where allowed), cut at limit."""
    text = "".join(ch if ch == "\n" and newlines or ord(ch) >= 32 else " " for ch in text)
    if not newlines:
        text = " ".join(text.split())
    return text[:limit].rstrip()


def _plain(text: str) -> str:
    """One part of a console id: ASCII letters and digits, lower case."""
    return re.sub(r"[^A-Za-z0-9]", "", text).lower()


def console_id(source: str, name: str) -> str | None:
    """The id PSPDX makes of a non-GitHub source: the host backwards, then
    the name, every part reduced to ASCII letters and digits. A port of the
    reference builder's identity(); None where the rule gives nothing."""
    if not source.startswith("https://"):
        return None
    host = re.split(r"[/?#\\]", source[len("https://"):], maxsplit=1)[0]
    host = host.rsplit("@", 1)[-1].split(":", 1)[0]
    if host[:4].lower() == "www.":
        host = host[4:]
    labels = host.split(".")
    if len(labels) > 1 and not labels[-1]:
        labels.pop()
    labels = [_plain(label) for label in labels[::-1]]
    plain_name = _plain(name)
    if not all(labels) or not plain_name:
        return None
    one = ".".join(labels + [plain_name])
    return None if one.startswith("io.github.") else one


def our_id(disc_key: str) -> str:
    """Return the local PSPDX app id for a disc key."""
    return "local.umd." + disc_key.lower()


def display_name(row: dict[str, Any]) -> str:
    """The list name: the title, at most 40 characters, with a letter or
    digit in it as the schema wants of a non-GitHub source."""
    title = _clean(row.get("title") or "", NAME_MAX) or row["disc_key"]
    if not re.search(r"[A-Za-z0-9]", title):
        title = _clean(f"{title[:NAME_MAX - len(row['disc_key']) - 1]} {row['disc_key']}", NAME_MAX)
    return title


def summary(row: dict[str, Any]) -> str:
    """Return the short catalog summary for one image."""
    return _clean(f"UMD {row['disc_key']}, {row['region']}, {human_size(row['size'])}", SUMMARY_MAX)


def description(row: dict[str, Any]) -> str:
    """Return the multi-line catalog description for one image."""
    sfo = row.get("sfo") or {}
    umd = row.get("umd_data") or {}
    lines = [f"Title: {row.get('title') or '(none)'}",
             f"Disc ID: {row['disc_key']} (from {row.get('disc_id_source')})"
             + (f", UMD {umd['identifier']} uid {umd.get('umd_uid', '?')} type {umd.get('type_code', '?')}"
                f" media {umd.get('media_code', '?')}" if umd.get("identifier") else ""),
             f"Region: {row['region']}",
             f"Languages: {', '.join(row.get('languages') or []) or 'unknown'}"]
    for key in ("DISC_VERSION", "PSP_SYSTEM_VER", "CATEGORY", "PARENTAL_LEVEL",
                "DISC_NUMBER", "DISC_TOTAL", "APP_VER"):
        if key in sfo:
            lines.append(f"{key}: {sfo[key]}")
    lines.append(f"Format: {row['format'].upper()}, {row['size']:,} bytes"
                 + (f", {row['iso_size']:,} bytes uncompressed" if row["format"] == "cso" and row.get("iso_size") else ""))
    lines.append(f"File: {row['name']}")
    lines.append(f"Media: {', '.join(n for n in isotool.MEDIA_FILES if row['has_media'].get(n)) or 'none'}")
    return _clean("\n".join(lines), DESCRIPTION_MAX, newlines=True)


def tags(row: dict[str, Any]) -> list[str]:
    """Return catalog tags for one image."""
    out = ["game", "umd", row["format"]]
    if row["region"] != "unknown":
        out.append(row["region"].lower())
    category = str((row.get("sfo") or {}).get("CATEGORY") or "")
    if category and category.lower() not in out:
        out.append(category.lower())
    seen: list[str] = []
    for tag in out:
        tag = _clean(tag, 24)
        if tag and tag not in seen:
            seen.append(tag)
    return seen[:8]


def published_at(mtime: float) -> str:
    """The file's mtime as the schema writes a date-time; never the epoch
    itself, which the schema refuses."""
    stamp = dt.datetime.fromtimestamp(max(mtime, 1), dt.timezone.utc)
    return stamp.strftime("%Y-%m-%dT%H:%M:%SZ")


def author(row: dict[str, Any], publishers: dict[str, str]) -> str | None:
    """Return the publisher override for one image, if any."""
    for key in (row.get("disc_id"), row.get("disc_key")):
        if key and key.upper() in publishers:
            return _clean(publishers[key.upper()], AUTHOR_MAX)
    return None


def umd_extension(row: dict[str, Any]) -> dict[str, Any]:
    """The umd object: what this service knows beyond the schema. Flat and
    documented in the README; the console ignores it."""
    sfo = row.get("sfo") or {}
    umd = row.get("umd_data") or {}
    return {
        "disc_id": row.get("disc_id"),
        "disc_key": row["disc_key"],
        "identifier": umd.get("identifier"),
        "umd_uid": umd.get("umd_uid"),
        "type_code": umd.get("type_code"),
        "media_code": umd.get("media_code"),
        "title": row.get("title"),
        "disc_version": sfo.get("DISC_VERSION"),
        "psp_system_ver": sfo.get("PSP_SYSTEM_VER"),
        "required_firmware": sfo.get("PSP_SYSTEM_VER"),
        "region": row["region"],
        "languages": list(row.get("languages") or []),
        "languages_from": row.get("languages_from"),
        "parental_level": sfo.get("PARENTAL_LEVEL"),
        "category": sfo.get("CATEGORY"),
        "format": row["format"],
        "file": row["name"],
        "image_size": row["size"],
        "iso_size": row.get("iso_size"),
        "has_media": {name: bool(row["has_media"].get(name)) for name in isotool.MEDIA_FILES},
        "pspdb_status": row.get("pspdb_status"),
        "pspdb_title": row.get("pspdb_title"),
    }


def urls(row: dict[str, Any], public_url: str) -> dict[str, str]:
    """Return public URLs for one image."""
    base = public_url.rstrip("/")
    key = row["disc_key"]
    return {"source": f"{base}/umd/{key}",
            "image": f"{base}/umd/{key}.{row['format']}",
            "manifest": f"{base}/umd/{key}.pspdx"}


def app_entry(row: dict[str, Any], public_url: str, publishers: dict[str, str],
              media_paths: dict[str, str] | None = None) -> dict[str, Any]:
    """The catalog entry for one image. media_paths maps the catalog field
    (icon, screenshots, video, sound) to the served path(s); build.py fills
    it after hashing the files."""
    where = urls(row, public_url)
    entry: dict[str, Any] = {
        "id": our_id(row["disc_key"]),
        "source": where["source"],
        "name": display_name(row),
        "type": "iso",
        "category": "game",
        "tags": tags(row),
        "summary": summary(row),
    }
    who = author(row, publishers)
    if who:
        entry["author"] = who
    entry["description"] = description(row)
    if row.get("languages"):
        entry["languages"] = list(row["languages"])
    entry["releases"] = [{
        "tag": _clean(str((row.get("sfo") or {}).get("DISC_VERSION") or "1.0"), 64) or "1.0",
        "published_at": published_at(row["mtime"]),
        "url": where["image"],
        "size": row["size"],
        "sha256": row.get("sha256") or "0" * 64,
    }]
    if media_paths:
        entry["media"] = media_paths
    entry["umd"] = umd_extension(row)
    return entry


def pspdx_manifest(row: dict[str, Any], public_url: str, publishers: dict[str, str]) -> dict[str, Any]:
    """The per-disc .pspdx: pspdx-v1 allows no extra fields, so the umd
    object stays in the catalog; the release pins the image."""
    where = urls(row, public_url)
    doc: dict[str, Any] = {
        "schema": PSPDX_SCHEMA_URL,
        "source": where["source"],
        "name": display_name(row),
        "type": "iso",
        "category": "game",
        "tags": tags(row),
        "summary": summary(row),
    }
    who = author(row, publishers)
    if who:
        doc["author"] = who
    doc["description"] = description(row)
    if row.get("languages"):
        doc["languages"] = list(row["languages"])
    doc["release"] = {
        "tag": _clean(str((row.get("sfo") or {}).get("DISC_VERSION") or "1.0"), 64) or "1.0",
        "url": where["image"],
        "published_at": published_at(row["mtime"]),
    }
    return doc


def catalog_document(apps: list[dict[str, Any]], generated_at: str) -> dict[str, Any]:
    """Return a complete catalog-v1 document."""
    return {"schema": CATALOG_SCHEMA_URL, "generated_at": generated_at,
            "apps": sorted(apps, key=lambda a: a["id"])}
