"""The shelf: every .iso and .cso in one folder, published as catalog.json
and media/ in the data folder. Rebuilt at start, on Rebuild, and when a check
finds the folder changed; a file
that did not change is not read again, and its SHA-256 is kept across restarts."""
import hashlib
import json
import logging
import os
import re
import shutil
import threading
import time

from . import catalog, disc

log = logging.getLogger("shelf")
FIELDS = {"ICON0.PNG": "icon", "PIC1.PNG": "screenshots", "ICON1.PMF": "video", "SND0.AT3": "sound"}


class Shelf:
    def __init__(self, discs_dir: str, data_dir: str):
        self.discs_dir, self.data_dir = discs_dir, data_dir
        self.media_dir = os.path.join(data_dir, "media")
        os.makedirs(self.media_dir, exist_ok=True)
        self.items: list[dict] = []   # one per file, what the pages show
        self.status = "starting"
        self.progress: tuple[int, int] | None = None   # files read and in all, while reading
        self._hashes = _load(os.path.join(data_dir, "hashes.json"))
        self._wake = threading.Event()
        self._force = False

    def disc(self, disc_id: str) -> dict | None:
        """The file the catalog lists for this id."""
        return next((i for i in self.items if i.get("id") == disc_id and not ("error" in i or "duplicate" in i)), None)

    def rebuild(self) -> None:
        self._force = True
        self._wake.set()

    def run(self, interval: float) -> None:
        while True:
            try:
                self.refresh()
            except Exception as exc:
                self.status = f"failed: {exc}"
                log.exception("refresh failed")
            self._wake.wait(interval)
            self._wake.clear()

    def refresh(self) -> None:
        files = self._files()
        known = {(i["file"], i["size"], i["mtime"]): i for i in self.items}
        if not self._force and set(known) == {(f["file"], f["size"], f["mtime"]) for f in files}:
            return
        if self._force:
            known, self._force = {}, False
        # First what every disc is, a few kilobytes each, so the whole shelf
        # is listed at once; then, one disc at a time, its media and its
        # SHA-256, the slow part, after which it is in the catalog.
        items = []
        for n, file in enumerate(files):
            self.progress = (n, len(files))
            self.status = f"listing {file['file']}"
            items.append(known.get((file["file"], file["size"], file["mtime"])) or self._identify(file))
        self._list(items, final=False)
        todo = [i for i in items if "app" not in i and "error" not in i]
        shown = time.monotonic()
        for n, item in enumerate(todo):
            self.progress = (n, len(todo))
            self._complete(item)
            if time.monotonic() - shown > 10:
                self._list(items, final=False)
                shown = time.monotonic()
        listed = self._list(items, final=True)
        self.progress = None
        self.status = f"{listed} discs listed, {time.strftime('%H:%M')}"
        log.info("%d files, %d discs listed", len(items), listed)

    def _list(self, items: list[dict], final: bool) -> int:
        # Two files of one disc: the one listed is the highest version, a
        # release before a beta, demo or promo, then the newer file.
        listed = {}
        for item in sorted(items, key=_preference):
            item.pop("duplicate", None)
            if "id" in item and "error" not in item:
                if item["id"] in listed:
                    item["duplicate"] = listed[item["id"]]["file"]
                else:
                    listed[item["id"]] = item
        apps = [i["app"] for i in sorted(listed.values(), key=lambda i: i["id"]) if "app" in i]
        catalog.distinct(apps)
        self._publish(apps, items, final)
        self.items = sorted(items, key=lambda i: (i.get("title") or i["file"]).casefold())
        return len(listed)

    def _files(self) -> list[dict]:
        out = []
        for entry in sorted(os.scandir(self.discs_dir), key=lambda e: e.name):
            fmt = os.path.splitext(entry.name)[1][1:].lower()
            if fmt in ("iso", "cso") and entry.is_file() and not entry.name.startswith("."):
                stat = entry.stat()
                out.append({"file": entry.name, "format": fmt, "size": stat.st_size, "mtime": stat.st_mtime})
        return out

    def _identify(self, file: dict) -> dict:
        item = dict(file)
        try:
            found = disc.read(os.path.join(self.discs_dir, file["file"]), media=False)
            item.update(id=found.id, title=found.title, region=found.region, version=found.version, media={})
            # Known from an earlier run, the same bytes: hash and pictures are
            # on disk already, and the disc is in the catalog at once.
            cached = self._hashes.get(file["file"])
            folder = os.path.join(self.media_dir, self._media_key(item))
            if cached and cached[:2] == [file["size"], file["mtime"]] and os.path.isdir(folder):
                item["media_key"], item["sha256"] = self._media_key(item), cached[2]
                item["media"] = self._paths(item["media_key"], [n.upper() for n in os.listdir(folder)])
                item["app"] = catalog.app(found, item, item["media"])
        except disc.DiscError as exc:
            item["error"] = str(exc)
        except Exception as exc:
            item["error"] = f"not a readable disc image ({exc or type(exc).__name__})"
        if "error" in item:
            log.warning("%s: %s", file["file"], item["error"])
        return item

    def _complete(self, item: dict) -> None:
        try:
            self.status = f"reading {item['file']}"
            found = disc.read(os.path.join(self.discs_dir, item["file"]))
            item["media"] = self._media(item, found.media)
            item["sha256"] = self._sha256(item)
            item["app"] = catalog.app(found, item, item["media"])
        except Exception as exc:
            item["error"] = str(exc) or type(exc).__name__
            log.warning("%s: %s", item["file"], item["error"])

    def _sha256(self, file: dict) -> str:
        cached = self._hashes.get(file["file"])
        if cached and cached[:2] == [file["size"], file["mtime"]]:
            return cached[2]
        self.status = f"hashing {file['file']}"
        digest = hashlib.sha256()
        with open(os.path.join(self.discs_dir, file["file"]), "rb") as f:
            while chunk := f.read(4 << 20):
                digest.update(chunk)
        self._hashes[file["file"]] = [file["size"], file["mtime"], digest.hexdigest()]
        _save(os.path.join(self.data_dir, "hashes.json"), self._hashes)
        return digest.hexdigest()

    @staticmethod
    def _media_key(item: dict) -> str:
        """Named after the file as it is, so a new dump gets new names and no
        client shows a stale picture."""
        return hashlib.sha1(f"{item['file']}|{item['size']}|{item['mtime']}".encode()).hexdigest()[:16]

    def _media(self, item: dict, media: dict[str, bytes]) -> dict:
        """The disc's media under media/<key>/."""
        key = item["media_key"] = self._media_key(item)
        folder = os.path.join(self.media_dir, key)
        os.makedirs(folder, exist_ok=True)
        for name, data in media.items():
            with open(os.path.join(folder, name.lower()), "wb") as f:
                f.write(data)
        return self._paths(key, list(media))

    @staticmethod
    def _paths(key: str, names: list[str]) -> dict:
        out = {}
        for name in names:
            if name in FIELDS:
                path = f"media/{key}/{name.lower()}"
                out[FIELDS[name]] = [path] if FIELDS[name] == "screenshots" else path
        return out

    def _publish(self, apps: list[dict], items: list[dict], final: bool) -> None:
        _save(os.path.join(self.data_dir, "catalog.json"), catalog.document(apps, time.time()), compact=True)
        if not final:
            return
        # What is gone from the folder is forgotten.
        self._hashes = {i["file"]: self._hashes[i["file"]] for i in items if i["file"] in self._hashes}
        _save(os.path.join(self.data_dir, "hashes.json"), self._hashes)
        used = {i["media_key"] for i in items if "media_key" in i}
        for name in os.listdir(self.media_dir):
            if name not in used:
                shutil.rmtree(os.path.join(self.media_dir, name), ignore_errors=True)


_UNFINISHED = re.compile(r"\((?:beta|demo|promo|proto|prototype|kiosk|test|sample)\b", re.I)


def _preference(item: dict) -> tuple:
    version = tuple(int(n) for n in re.findall(r"\d+", item.get("version", "")))
    return (tuple(-n for n in version), bool(_UNFINISHED.search(item["file"])), -item["mtime"])


def _load(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save(path: str, value, compact: bool = False) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, separators=(",", ":") if compact else None)
    os.replace(tmp, path)
