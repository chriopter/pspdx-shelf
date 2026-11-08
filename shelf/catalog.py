"""A disc as a catalog-v1 app, checked against the PSPDX schema."""
import datetime
import json
import os
import re

import jsonschema

SCHEMA_URL = "https://chriopter.github.io/pspdx/schema/catalog-v1.json"
# PSPDX makes an app's id from its source's host, so the source is the same
# whichever way the shelf is reached: at home, through a VPN, from outside.
SOURCE = "https://pspdx-shelf.local"
# The downloads are where the catalog was fetched from: written with this,
# and the address of each request put in when the catalog is served.
BASE = "http://pspdx-shelf.base"
with open(os.path.join(os.path.dirname(__file__), "catalog-v1.json"), encoding="utf-8") as f:
    SCHEMA = json.load(f)
# Without its format checker (rfc3339-validator, rfc3986-validator) jsonschema
# would let any date-time and uri through.
VALIDATOR = jsonschema.Draft202012Validator(SCHEMA, format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER)


def stamp(seconds: float) -> str:
    return datetime.datetime.fromtimestamp(seconds, datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def size(n: int) -> str:
    return f"{n / 1e9:.1f} GB" if n >= 1e9 else f"{n / 1e6:.0f} MB"


def app(disc, file: dict, media: dict) -> dict:
    """disc from disc.read(), file {format, size, mtime, sha256}, media the
    catalog's media object. Raises ValueError where the schema says no."""
    # PSPDX makes an app's id from the host and the name, so the name tells
    # the EU disc from the US one; it also gives the schema its letter.
    suffix = f" ({disc.region})" if disc.region else f" {disc.id}"
    name = disc.title[:40 - len(suffix)].strip() + suffix
    entry = {
        "source": f"{SOURCE}/discs/{disc.id}",
        "name": name,
        "type": "iso",
        "category": "game",
        # Not in the schema, which lets a list carry its own fields: the
        # discs of one game, sold in several regions, share it.
        "game": " ".join(disc.title.replace("™", "").replace("®", "").casefold().split()),
        "summary": ", ".join(filter(None, (disc.id, disc.region, size(file["size"])))),
        "releases": [{
            "tag": disc.version,
            "published_at": stamp(file["mtime"]),
            "url": f"{BASE}/discs/{disc.id}.{file['format']}",
            "size": file["size"],
            "sha256": file["sha256"],
        }],
    }
    if media:
        entry["media"] = media
    found = problems(document([entry], file["mtime"]))
    if found:
        raise ValueError(found[0])
    return entry


def distinct(apps: list[dict]) -> None:
    """PSPDX makes an app's id from the host and the name, letters and
    digits only, so two discs of one title and region would be one app to
    it: of those, the first keeps its name and the rest say their disc id."""
    taken = set()
    for app in apps:
        key = re.sub(r"[^a-z0-9]", "", app["name"].lower())
        if key in taken:
            disc_id = app["summary"].split(",")[0]
            app["name"] = f"{app['name'].rsplit(' (', 1)[0][:40 - len(disc_id) - 3].strip()} ({disc_id})"
        taken.add(re.sub(r"[^a-z0-9]", "", app["name"].lower()))


def document(apps: list[dict], generated: float) -> dict:
    return {"schema": SCHEMA_URL, "generated_at": stamp(generated), "apps": sorted(apps, key=lambda a: a["name"].casefold())}


def problems(doc: dict) -> list[str]:
    return [f"{e.json_path}: {e.message}" for e in VALIDATOR.iter_errors(doc)]


def served(text: bytes, base: str) -> bytes:
    """The catalog as it is served to a request that came by base."""
    return text.replace(BASE.encode(), base.rstrip("/").encode())
