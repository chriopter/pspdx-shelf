#!/usr/bin/env python3
"""Pins shelf/genres/ to another commit of libretro-database:

    tools/update-genres.py [commit]      the newest commit of the file without one

Downloads the PSP genre list at that commit, checks it parses, and writes it
and pin.json with its SHA-256. Nothing else changes; the diff is the review."""
import hashlib
import json
import os
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
HERE = os.path.join(os.path.dirname(__file__), "..", "shelf", "genres")
with open(os.path.join(HERE, "pin.json"), encoding="utf-8") as f:
    pin = json.load(f)
repo = pin["source"].removeprefix("https://github.com/")
path = urllib.parse.quote(pin["path"])


def get(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as r:
        return r.read()


commit = sys.argv[1] if len(sys.argv) > 1 else json.loads(
    get(f"https://api.github.com/repos/{repo}/commits?path={path}&per_page=1"))[0]["sha"]
raw = get(f"https://raw.githubusercontent.com/{repo}/{commit}/{path}")

from shelf.genre import parse  # noqa: E402 -- after the path is set
found = parse(raw.decode("utf-8"))
if len(found) < 1000:
    sys.exit(f"only {len(found)} genres at {commit}: not taking it")
with open(os.path.join(HERE, os.path.basename(pin["path"])), "wb") as f:
    f.write(raw)
pin.update(commit=commit, sha256=hashlib.sha256(raw).hexdigest())
with open(os.path.join(HERE, "pin.json"), "w", encoding="utf-8") as f:
    json.dump(pin, f, indent=2)
    f.write("\n")
print(f"{len(found)} genres at {commit}")
