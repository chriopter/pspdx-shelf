"""One disc image, .iso or .cso: its id and title from UMD_DATA.BIN and
PARAM.SFO, and the pictures, film and sound under PSP_GAME."""
import dataclasses
import re

import pycdlib

from . import cso, sfo

MEDIA = ("ICON0.PNG", "PIC1.PNG", "ICON1.PMF", "SND0.AT3")
MEDIA_LIMIT = 16 << 20
REGIONS = {"ULES": "EU", "UCES": "EU", "ULUS": "US", "UCUS": "US", "ULJS": "JP", "UCJS": "JP",
           "ULJM": "JP", "NPJH": "JP", "ULAS": "AS", "UCAS": "AS", "UCKS": "KR"}
DISC_ID = re.compile(r"([A-Z]{4})-?(\d{5})")


class DiscError(Exception):
    """A readable image that is not a PSP game disc. Broken images raise what their reader raises."""


@dataclasses.dataclass
class Disc:
    id: str            # ULUS-10404
    title: str
    version: str       # DISC_VERSION, 1.00
    media: dict[str, bytes]

    @property
    def region(self) -> str:
        return REGIONS.get(self.id[:4], "")


def disc_id(text) -> str | None:
    found = DISC_ID.fullmatch(str(text or "").strip().upper())
    return f"{found[1]}-{found[2]}" if found else None


def read(path: str, media: bool = True) -> Disc:
    """Without media only a few kilobytes are read: what a list needs at once."""
    stream = open(path, "rb")
    iso = pycdlib.PyCdlib()
    try:
        if path.lower().endswith(".cso"):
            stream = cso.CsoFile(stream)
        iso.open_fp(stream)
        files = {}  # UMD_DATA.BIN, PSP_GAME/PARAM.SFO, ... -> (ISO path, length)
        for folder in ("/", "/PSP_GAME/"):
            for child in _children(iso, folder):
                ident = child.file_identifier().decode("ascii", "replace")
                files[folder[1:] + ident.split(";")[0].upper()] = (folder + ident, child.get_data_length())

        def content(name, limit=1 << 20):
            if name not in files or files[name][1] > limit:
                return None
            with iso.open_file_from_iso(iso_path=files[name][0]) as f:
                return f.read()

        param = content("PSP_GAME/PARAM.SFO")
        if param is None:
            raise DiscError("no PSP_GAME/PARAM.SFO")
        values = sfo.parse(param)
        umd_data = (content("UMD_DATA.BIN") or b"").decode("ascii", "replace").split("|")[0]
        key = disc_id(umd_data) or disc_id(values.get("DISC_ID"))
        if not key:
            raise DiscError("no disc id")
        found = {name: data for name in MEDIA if media and (data := content("PSP_GAME/" + name, MEDIA_LIMIT))}
        return Disc(key, " ".join(str(values.get("TITLE") or "").split()) or key,
                    str(values.get("DISC_VERSION") or "1.00"), found)
    finally:
        try:
            iso.close()
        except pycdlib.pycdlibexception.PyCdlibException:
            pass
        stream.close()


def _children(iso, folder):
    try:
        return [c for c in iso.list_children(iso_path=folder.rstrip("/") or "/") if c.is_file()]
    except pycdlib.pycdlibexception.PyCdlibException:
        return []
