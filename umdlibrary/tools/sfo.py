"""PARAM.SFO: the small key/value table every PSP disc and EBOOT carries.

Layout (all little endian):

    0x00  magic  b"\\0PSF"
    0x04  u32    version (0x0101)
    0x08  u32    key table start
    0x0c  u32    data table start
    0x10  u32    entry count
    0x14  entries, 16 bytes each:
          u16 key offset (into the key table)
          u16 data format: 0x0004 utf8 without terminator, 0x0204 utf8,
                           0x0404 uint32
          u32 data length (bytes in use)
          u32 data max length (bytes reserved)
          u32 data offset (into the data table)

A parser and a writer; the writer exists so the tests can build discs
without a real PSP, but it is a faithful one and lives here with the
parser because the two describe one format."""
from __future__ import annotations

import struct

MAGIC = b"\x00PSF"
FMT_UTF8_SPECIAL = 0x0004
FMT_UTF8 = 0x0204
FMT_UINT32 = 0x0404

HEADER = struct.Struct("<4sIIII")
ENTRY = struct.Struct("<HHIII")

# The keys a UMD's PARAM.SFO usually holds, in the order the UI shows them.
KNOWN_KEYS = (
    "TITLE", "DISC_ID", "DISC_VERSION", "DISC_NUMBER", "DISC_TOTAL",
    "CATEGORY", "PARENTAL_LEVEL", "PSP_SYSTEM_VER", "REGION", "BOOTABLE",
    "APP_VER", "USE_USB", "ATTRIBUTE", "HRKGMP_VER", "MEMSIZE",
)


class SfoError(ValueError):
    """The bytes are not a PARAM.SFO, or a broken one."""


def parse(data: bytes) -> dict[str, str | int]:
    """The key/value pairs of a PARAM.SFO. Strings come back as str, uint32
    entries as int. Raises SfoError for anything that is not an SFO."""
    if len(data) < HEADER.size:
        raise SfoError("too short for a PARAM.SFO header")
    magic, version, key_start, data_start, count = HEADER.unpack_from(data, 0)
    if magic != MAGIC:
        raise SfoError("bad magic, not a PARAM.SFO")
    if version >> 8 != 0x01:
        raise SfoError(f"unknown PARAM.SFO version 0x{version:04x}")
    if count > 4096:
        raise SfoError(f"implausible entry count {count}")
    table_end = HEADER.size + count * ENTRY.size
    if table_end > len(data) or key_start > len(data) or data_start > len(data):
        raise SfoError("PARAM.SFO tables point outside the file")
    out: dict[str, str | int] = {}
    for i in range(count):
        key_off, fmt, length, max_len, data_off = ENTRY.unpack_from(
            data, HEADER.size + i * ENTRY.size)
        key_pos = key_start + key_off
        key_end = data.find(b"\x00", key_pos)
        if key_end < 0 or key_pos >= len(data):
            raise SfoError(f"entry {i}: key offset outside the file")
        key = data[key_pos:key_end].decode("utf-8", "replace")
        start = data_start + data_off
        if start + length > len(data) or length > max_len:
            raise SfoError(f"entry {i} ({key}): data outside the file")
        raw = data[start:start + length]
        if fmt == FMT_UINT32:
            if length != 4:
                raise SfoError(f"entry {i} ({key}): uint32 with length {length}")
            out[key] = struct.unpack("<I", raw)[0]
        elif fmt in (FMT_UTF8, FMT_UTF8_SPECIAL):
            out[key] = raw.split(b"\x00", 1)[0].decode("utf-8", "replace")
        else:
            raise SfoError(f"entry {i} ({key}): unknown data format 0x{fmt:04x}")
    return out


def build(values: dict[str, str | int]) -> bytes:
    """A PARAM.SFO holding values, keys sorted as the PSP writes them.
    Strings are stored as 0x0204 with a terminator, ints as 0x0404."""
    keys = sorted(values)
    key_blob = bytearray()
    data_blob = bytearray()
    entries = []
    for key in keys:
        value = values[key]
        key_off = len(key_blob)
        key_blob += key.encode("utf-8") + b"\x00"
        data_off = len(data_blob)
        if isinstance(value, int):
            raw = struct.pack("<I", value)
            fmt, length, max_len = FMT_UINT32, 4, 4
        else:
            raw = value.encode("utf-8") + b"\x00"
            fmt, length = FMT_UTF8, len(raw)
            max_len = (length + 3) // 4 * 4
        data_blob += raw + b"\x00" * (max_len - length)
        entries.append(ENTRY.pack(key_off, fmt, length, max_len, data_off))
    key_start = HEADER.size + len(entries) * ENTRY.size
    # The key table is padded to 4 bytes before the data table starts.
    pad = (-len(key_blob)) % 4
    data_start = key_start + len(key_blob) + pad
    header = HEADER.pack(MAGIC, 0x0101, key_start, data_start, len(entries))
    return header + b"".join(entries) + bytes(key_blob) + b"\x00" * pad + bytes(data_blob)


def main(argv: list[str] | None = None) -> int:
    """python -m umdlibrary.tools.sfo PARAM.SFO: print every field."""
    import argparse
    import sys
    parser = argparse.ArgumentParser(description="print the fields of a PARAM.SFO")
    parser.add_argument("file")
    args = parser.parse_args(argv)
    with open(args.file, "rb") as f:
        data = f.read()
    try:
        values = parse(data)
    except SfoError as exc:
        print(f"{args.file}: {exc}", file=sys.stderr)
        return 1
    for key in sorted(values, key=lambda k: (k not in KNOWN_KEYS, KNOWN_KEYS.index(k) if k in KNOWN_KEYS else k)):
        print(f"{key:16} {values[key]!r}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
