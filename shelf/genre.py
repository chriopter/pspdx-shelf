"""A disc's genre by its id, from libretro-database's list for the PSP.

The list is checked in under genres/, pinned to one commit of
libretro-database by genres/pin.json, which also holds its SHA-256: the shelf
reads that file and nothing from the network, and a file that is not the
pinned one is refused. tools/update-genres.py takes a newer commit.
The list is libretro's, under CC BY-SA 4.0."""
import hashlib
import json
import os
import re

HERE = os.path.join(os.path.dirname(__file__), "genres")
with open(os.path.join(HERE, "pin.json"), encoding="utf-8") as f:
    PIN = json.load(f)
FILE = os.path.join(HERE, os.path.basename(PIN["path"]))

# game ( ... serial "ULUS-10080" genre "Adventure" ... )
ENTRY = re.compile(r'game \((.*?)\n\)', re.S)
FIELD = re.compile(r'^\s*(serial|genre) "([^"]*)"', re.M)


def parse(text: str) -> dict[str, str]:
    """Disc id -> genre, for every entry that has both."""
    genres = {}
    for entry in ENTRY.finditer(text):
        fields = dict(FIELD.findall(entry[1]))
        if fields.get("serial") and fields.get("genre"):
            genres[fields["serial"].upper()] = fields["genre"]
    return genres


def load() -> dict[str, str]:
    with open(FILE, "rb") as f:
        raw = f.read()
    if hashlib.sha256(raw).hexdigest() != PIN["sha256"]:
        raise RuntimeError(f"{FILE} is not the pinned file")
    return parse(raw.decode("utf-8"))


GENRES = load()


def of(disc_id: str) -> str | None:
    return GENRES.get((disc_id or "").upper())
