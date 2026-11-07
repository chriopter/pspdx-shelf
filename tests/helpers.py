"""Synthetic discs for the tests: a PARAM.SFO from the writer, a tiny valid
PNG, an ISO 9660 image built with pycdlib, and the CSO packer, so the whole
pipeline runs without a real UMD."""
from __future__ import annotations

import io
import os
import struct
import zlib

import pycdlib

from umdlibrary.tools import cso as csotool
from umdlibrary.tools import sfo as sfotool


def make_png(width: int = 144, height: int = 80, color=(40, 80, 200)) -> bytes:
    """A real PNG: one IHDR, one IDAT, one IEND."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))
    row = b"\x00" + bytes(color) * width
    raw = row * height
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b""))


def make_sfo(title="Test Game", disc_id="ULES-01234", **extra) -> bytes:
    """A PARAM.SFO as a UMD carries it: DISC_ID without the dash."""
    values = {"TITLE": title, "DISC_ID": disc_id.replace("-", "") if disc_id else None,
              "DISC_VERSION": "1.02", "CATEGORY": "UG",
              "PARENTAL_LEVEL": 3, "PSP_SYSTEM_VER": "3.52", "REGION": 32768, "BOOTABLE": 1,
              "DISC_NUMBER": 1, "DISC_TOTAL": 1, "APP_VER": "1.00"}
    values.update(extra)
    values = {k: v for k, v in values.items() if v is not None}
    return sfotool.build(values)


def make_iso(title="Test Game", disc_id="ULES-01234", *, psp_game=True, umd_data=True,
             media=("ICON0.PNG", "PIC1.PNG"), sfo_extra=None, vol_ident="ULES01234",
             pad_bytes=0, sfo_bytes: bytes | None = None, umd_uid="05FC10F031E498EA",
             umd_line: str | None = None) -> bytes:
    """A PSP-shaped ISO. media names which PSP_GAME files exist; PMF and AT3
    get placeholder bytes with the right magic."""
    iso = pycdlib.PyCdlib()
    iso.new(interchange_level=1, vol_ident=vol_ident)
    if psp_game:
        iso.add_directory("/PSP_GAME")
        sfo = sfo_bytes if sfo_bytes is not None else make_sfo(title, disc_id, **(sfo_extra or {}))
        iso.add_fp(io.BytesIO(sfo), len(sfo), "/PSP_GAME/PARAM.SFO;1")
        blobs = {"ICON0.PNG": make_png(), "PIC1.PNG": make_png(480, 272, (200, 40, 40)),
                 "PIC0.PNG": make_png(310, 180, (40, 200, 40)),
                 "ICON1.PMF": b"PSMF0013" + b"\x00" * 300, "SND0.AT3": b"RIFF" + b"\x00" * 300}
        for name in media:
            data = blobs[name]
            iso.add_fp(io.BytesIO(data), len(data), f"/PSP_GAME/{name};1")
    if umd_data and (disc_id or umd_line):
        line = umd_line if umd_line is not None else f"{disc_id}|{umd_uid}|0001|G"
        data = line.encode() + b"   " + b"\x00" * 100
        iso.add_fp(io.BytesIO(data), len(data), "/UMD_DATA.BIN;1")
    if pad_bytes:
        pad = io.BytesIO(os.urandom(min(pad_bytes, 1 << 20)) * ((pad_bytes + (1 << 20) - 1) // (1 << 20)))
        iso.add_fp(pad, pad_bytes, "/PAD.BIN;1")
    out = io.BytesIO()
    iso.write_fp(out)
    iso.close()
    return out.getvalue()


def make_cso(iso: bytes, block_size: int = 2048, align: int = 0) -> bytes:
    return csotool.pack(iso, block_size=block_size, align=align)


def write(path: str, data: bytes, mtime: float | None = None) -> str:
    with open(path, "wb") as f:
        f.write(data)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path
