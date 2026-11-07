"""Synthetic discs: a PARAM.SFO, an ISO built with pycdlib, a CSO packed from it."""
import io
import os
import struct
import zlib

import pycdlib
import pytest

from shelf.shelf import Shelf


def make_sfo(values: dict) -> bytes:
    keys, data, entries = b"", b"", b""
    for key, value in sorted(values.items()):
        raw = struct.pack("<I", value) if isinstance(value, int) else value.encode() + b"\0"
        fmt = 0x0404 if isinstance(value, int) else 0x0204
        entries += struct.pack("<HHIII", len(keys), fmt, len(raw), len(raw), len(data))
        keys += key.encode() + b"\0"
        data += raw
    key_start = 20 + len(entries)
    return struct.pack("<4sIIII", b"\0PSF", 0x101, key_start, key_start + len(keys), len(values)) + entries + keys + data


def make_iso(title="Test Game", disc_id="ULES-01234", umd_data=True, media=("ICON0.PNG", "PIC1.PNG"),
             version="1.02") -> bytes:
    iso = pycdlib.PyCdlib()
    iso.new(interchange_level=1)
    files = {"/PSP_GAME/PARAM.SFO": make_sfo({"TITLE": title, "DISC_ID": disc_id.replace("-", ""),
                                               "DISC_VERSION": version, "PARENTAL_LEVEL": 3})}
    files.update({f"/PSP_GAME/{name}": name.encode() * 50 for name in media})
    if umd_data:
        files["/UMD_DATA.BIN"] = f"{disc_id}|05FC10F031E498EA|0001|G".encode()
    iso.add_directory("/PSP_GAME")
    for path, data in files.items():
        iso.add_fp(io.BytesIO(data), len(data), path + ";1")
    out = io.BytesIO()
    iso.write_fp(out)
    return out.getvalue()


def make_cso(iso: bytes, block: int = 2048) -> bytes:
    """Blocks that do not shrink are stored raw, as ciso does."""
    blocks = [iso[i:i + block] for i in range(0, len(iso), block)]
    offset = 24 + (len(blocks) + 1) * 4
    index, body = [], b""
    for chunk in blocks:
        packer = zlib.compressobj(9, zlib.DEFLATED, -15)
        packed = packer.compress(chunk) + packer.flush()
        raw = len(packed) >= len(chunk)
        index.append((offset + len(body)) | (0x80000000 if raw else 0))
        body += chunk if raw else packed
    index.append(offset + len(body))
    header = struct.pack("<4sIQIBB2s", b"CISO", 24, len(iso), block, 1, 0, b"\0\0")
    return header + struct.pack(f"<{len(index)}I", *index) + body


def write(path, data: bytes, mtime: float = 1_700_000_000) -> None:
    with open(path, "wb") as f:
        f.write(data)
    os.utime(path, (mtime, mtime))


@pytest.fixture
def shelf(tmp_path):
    (tmp_path / "discs").mkdir()
    return Shelf(str(tmp_path / "discs"), str(tmp_path / "data"), "https://psp.lan")
