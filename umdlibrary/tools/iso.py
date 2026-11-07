"""One UMD image on disk, read through pycdlib: what the disc says about
itself (PARAM.SFO, UMD_DATA.BIN, the volume id) and the media files under
PSP_GAME. Nothing here writes. A CSO is opened through cso.CsoFile so
pycdlib never knows the difference."""
from __future__ import annotations

import dataclasses
import io
import os
import re
from typing import BinaryIO, Iterator

import pycdlib
import pycdlib.pycdlibexception

from . import cso, sfo

MEDIA_FILES = ("ICON0.PNG", "ICON1.PMF", "PIC0.PNG", "PIC1.PNG", "SND0.AT3")
MEDIA_LIMIT = 64 * 1024 * 1024  # a media file larger than this is left alone
SFO_LIMIT = 1024 * 1024

DISC_ID_RE = re.compile(r"^([A-Z]{4})[-_]?(\d{5})$")
UMD_DATA_KEYS = ("identifier", "umd_uid", "type_code", "media_code")

# The disc id prefix says where the disc was sold. Enough for the UI; a disc
# whose prefix is not here is "unknown", never a guess.
REGION_PREFIXES = {
    "EU": ("ULES", "UCES", "NPEH", "NPEG", "NPEZ", "NPEX"),
    "US": ("ULUS", "UCUS", "NPUH", "NPUG", "NPUZ", "NPUX", "UCAS"),
    "JP": ("ULJS", "UCJS", "ULJM", "NPJH", "NPJG", "UCJB", "UCJM", "NPJJ", "ULJP"),
    "AS": ("ULAS", "UCAS", "NPHH", "NPHG", "UCKS"),
    "KR": ("UCKS", "NPHZ"),
}
_PREFIX_TO_REGION = {}
for _region, _prefixes in REGION_PREFIXES.items():
    for _prefix in _prefixes:
        _PREFIX_TO_REGION.setdefault(_prefix, _region)


def region_of(disc_id: str | None) -> str:
    """Return the coarse PSP sales region for a disc id."""
    if not disc_id or len(disc_id) < 4:
        return "unknown"
    return _PREFIX_TO_REGION.get(disc_id[:4].upper(), "unknown")


def canonical_id(text: str | None) -> str | None:
    """ULUS10404, ulus-10404 -> ULUS-10404: the id as URLs and file names
    carry it. None for anything else."""
    if not text:
        return None
    found = DISC_ID_RE.match(text.strip().upper())
    return f"{found.group(1)}-{found.group(2)}" if found else None


def parse_umd_data(raw: bytes) -> dict[str, str]:
    """UMD_DATA.BIN: <identifier>|<umd_uid>|<type_code>|<media_code>, e.g.
    ULUS-10404|05FC10F031E498EA|0001|G, padded after. A video UMD writes a
    title as identifier and V as media code; the fields are kept as they
    are and the caller decides what is a disc id."""
    text = raw.decode("ascii", "replace").split("\x00", 1)[0]
    parts = [p.strip() for p in text.split("|")]
    return {key: value for key, value in zip(UMD_DATA_KEYS, parts) if value}


class DiscError(Exception):
    """The file cannot be read as a PSP disc. The message says why."""


@dataclasses.dataclass
class DiscInfo:
    """Parsed facts from one PSP image."""
    format: str                      # iso | cso
    image_size: int                  # bytes on disk
    iso_size: int                    # bytes of the ISO (same for iso)
    volume_id: str
    disc_id: str | None              # the SFO's DISC_ID as written, ULUS10404
    umd_data: dict[str, str]         # identifier, umd_uid, type_code, media_code
    canonical_id: str | None         # ULUS-10404, from UMD_DATA.BIN or the SFO
    disc_id_source: str              # umd_data | sfo | volume | none
    title: str | None
    sfo: dict[str, str | int]
    media: dict[str, int]            # ICON0.PNG -> size, only what exists
    has_psp_game: bool

    @property
    def identifier(self) -> str | None:
        """Return the UMD_DATA identifier field."""
        return self.umd_data.get("identifier")

    @property
    def region(self) -> str:
        """Return the image region derived from its canonical id."""
        return region_of(self.canonical_id) if self.disc_id_source in ("umd_data", "sfo") else "unknown"


def image_format(path: str) -> str | None:
    """Return iso or cso based on filename extension."""
    ext = os.path.splitext(path)[1].lower()
    return {".iso": "iso", ".cso": "cso"}.get(ext)


def _open_stream(path: str) -> tuple[BinaryIO, str, int]:
    """(file-like, format, iso size) for an image; raises DiscError."""
    fmt = image_format(path)
    if fmt is None:
        raise DiscError("not an .iso or .cso")
    raw = open(path, "rb")
    try:
        if fmt == "cso":
            stream: BinaryIO = cso.CsoFile(raw)
            return stream, fmt, stream.total
        raw.seek(0, io.SEEK_END)
        size = raw.tell()
        raw.seek(0)
        return raw, fmt, size
    except cso.CsoError as exc:
        raw.close()
        raise DiscError(f"CSO: {exc}") from exc
    except Exception:
        raw.close()
        raise


def _name(child) -> str:
    """The plain, upper-case name of a directory record: no ;1, no case."""
    return child.file_identifier().decode("ascii", "replace").split(";", 1)[0].upper()


class Disc:
    """A context manager over one image; reads names case-insensitively so
    a disc mastered with lower-case Joliet names still yields its files."""

    def __init__(self, path: str):
        self.path = path
        self.stream, self.format, self.iso_size = _open_stream(path)
        self.image_size = os.path.getsize(path)
        self.iso = pycdlib.PyCdlib()
        try:
            self.iso.open_fp(self.stream)
        except pycdlib.pycdlibexception.PyCdlibException as exc:
            self.stream.close()
            raise DiscError(f"not an ISO 9660 image: {exc}") from exc
        except cso.CsoError as exc:
            self.stream.close()
            raise DiscError(f"CSO: {exc}") from exc
        except Exception as exc:  # pycdlib raises plain errors on junk too
            self.stream.close()
            raise DiscError(f"cannot read the image: {exc}") from exc

    def __enter__(self) -> "Disc":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        """Close the ISO reader and underlying stream."""
        try:
            self.iso.close()
        finally:
            self.stream.close()

    # -- directory access ----------------------------------------------------
    def _children(self, iso_path: str):
        try:
            return [c for c in self.iso.list_children(iso_path=iso_path)
                    if not c.is_dot() and not c.is_dotdot()]
        except pycdlib.pycdlibexception.PyCdlibException:
            return []

    def _lookup(self, *parts: str):
        """The directory record at /parts, matched case-insensitively."""
        path = "/"
        record = None
        for i, part in enumerate(parts):
            found = None
            for child in self._children(path):
                if _name(child) == part.upper():
                    found = child
                    break
            if found is None:
                return None
            record = found
            ident = found.file_identifier().decode("ascii", "replace")
            path = (path.rstrip("/") + "/" + ident)
            if i < len(parts) - 1 and not found.is_dir():
                return None
        return record, path

    def _open(self, *parts: str):
        hit = self._lookup(*parts)
        if hit is None or hit[0].is_dir():
            return None
        return self.iso.open_file_from_iso(iso_path=hit[1]), hit[0].get_data_length()

    def read_file(self, *parts: str, limit: int = SFO_LIMIT) -> bytes | None:
        """Read a file from the ISO by path parts, up to limit bytes."""
        opened = self._open(*parts)
        if opened is None:
            return None
        handle, length = opened
        with handle as f:
            return f.read(min(length, limit))

    def has_dir(self, *parts: str) -> bool:
        """Return whether a directory exists in the ISO."""
        hit = self._lookup(*parts)
        return bool(hit) and hit[0].is_dir()

    def media_files(self) -> dict[str, int]:
        """Return PSP_GAME media file names and byte lengths."""
        out = {}
        for child in self._children("/PSP_GAME"):
            name = _name(child)
            if name in MEDIA_FILES and not child.is_dir():
                out[name] = child.get_data_length()
        return out

    def iter_file(self, *parts: str, chunk: int = 1 << 20) -> Iterator[bytes]:
        """Yield chunks from a file in the ISO."""
        opened = self._open(*parts)
        if opened is None:
            return
        handle, length = opened
        with handle as f:
            left = length
            while left > 0:
                data = f.read(min(chunk, left))
                if not data:
                    break
                left -= len(data)
                yield data

    def extract(self, name: str, dest: str) -> int:
        """Copy PSP_GAME/name to dest by streaming; returns the bytes written.
        Writes to dest.part first so a broken run leaves no half file."""
        part = dest + ".part"
        written = 0
        with open(part, "wb") as out:
            for chunk in self.iter_file("PSP_GAME", name):
                out.write(chunk)
                written += len(chunk)
        os.replace(part, dest)
        return written

    # -- what the disc says ----------------------------------------------------
    def volume_id(self) -> str:
        """Return the ISO primary volume identifier."""
        raw = self.iso.pvd.volume_identifier
        return raw.decode("ascii", "replace").strip("\x00 ")

    def info(self) -> DiscInfo:
        """Return parsed PSP metadata for this image."""
        has_psp_game = self.has_dir("PSP_GAME")
        values: dict[str, str | int] = {}
        if has_psp_game:
            raw = self.read_file("PSP_GAME", "PARAM.SFO")
            if raw:
                try:
                    values = sfo.parse(raw)
                except sfo.SfoError as exc:
                    values = {"_error": f"PARAM.SFO: {exc}"}
        raw_umd = self.read_file("UMD_DATA.BIN", limit=256)
        umd_data = parse_umd_data(raw_umd) if raw_umd else {}
        sfo_id = values.get("DISC_ID")
        sfo_id = str(sfo_id).strip() if isinstance(sfo_id, str) and str(sfo_id).strip() else None
        canonical, source = canonical_id(umd_data.get("identifier")), "umd_data"
        if canonical is None:
            canonical, source = canonical_id(sfo_id), "sfo"
        volume = self.volume_id()
        if canonical is None:
            canonical, source = (volume, "volume") if volume else (None, "none")
        title = values.get("TITLE")
        title = str(title).strip() if isinstance(title, str) and title.strip() else None
        return DiscInfo(
            format=self.format,
            image_size=self.image_size,
            iso_size=self.iso_size,
            volume_id=volume,
            disc_id=sfo_id,
            umd_data=umd_data,
            canonical_id=canonical,
            disc_id_source=source,
            title=title,
            sfo=values,
            media=self.media_files() if has_psp_game else {},
            has_psp_game=has_psp_game,
        )


def read_info(path: str) -> DiscInfo:
    """Open and read one image's PSP metadata."""
    with Disc(path) as disc:
        try:
            return disc.info()
        except cso.CsoError as exc:
            raise DiscError(f"CSO: {exc}") from exc


def extract_media(path: str, dest_dir: str) -> dict[str, int]:
    """Every media file under PSP_GAME copied into dest_dir, name -> size.
    Files past MEDIA_LIMIT are skipped, and reported with a negative size."""
    os.makedirs(dest_dir, exist_ok=True)
    out = {}
    with Disc(path) as disc:
        try:
            for name, size in disc.media_files().items():
                if size > MEDIA_LIMIT:
                    out[name] = -size
                    continue
                out[name] = disc.extract(name, os.path.join(dest_dir, name))
        except cso.CsoError as exc:
            raise DiscError(f"CSO: {exc}") from exc
    return out


def main(argv: list[str] | None = None) -> int:
    """python -m umdlibrary.tools.iso IMAGE.iso|.cso [--media DIR]: print
    what the disc says about itself, and copy its media files to DIR."""
    import argparse
    import sys
    parser = argparse.ArgumentParser(description="read a PSP UMD image")
    parser.add_argument("file")
    parser.add_argument("--media", metavar="DIR", help="extract PSP_GAME media files here")
    args = parser.parse_args(argv)
    try:
        info = read_info(args.file)
    except (DiscError, OSError) as exc:
        print(f"{args.file}: {exc}", file=sys.stderr)
        return 1
    print(f"format          {info.format}")
    print(f"image size      {info.image_size}")
    print(f"iso size        {info.iso_size}")
    print(f"volume id       {info.volume_id!r}")
    print(f"disc id         {info.canonical_id} (from {info.disc_id_source}); SFO DISC_ID {info.disc_id!r}")
    for key in UMD_DATA_KEYS:
        print(f"  {key:14} {info.umd_data.get(key)!r}")
    print(f"region          {info.region}")
    print(f"title           {info.title!r}")
    print(f"PSP_GAME        {'yes' if info.has_psp_game else 'no'}")
    for key, value in sorted(info.sfo.items()):
        print(f"  {key:14} {value!r}")
    for name, size in sorted(info.media.items()):
        print(f"  {name:14} {size} bytes")
    if args.media:
        for name, size in extract_media(args.file, args.media).items():
            print(f"wrote {args.media}/{name} ({size} bytes)")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
