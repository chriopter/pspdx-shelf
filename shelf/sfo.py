"""PARAM.SFO, the key/value table on every PSP disc.

    0x00  b"\\0PSF", u32 version, u32 key table, u32 data table, u32 count
    0x14  count entries: u16 key offset, u16 format, u32 length, u32 max, u32 data offset

Format 0x0004 and 0x0204 are UTF-8 strings, 0x0404 a u32."""
import struct

HEADER = struct.Struct("<4sIIII")
ENTRY = struct.Struct("<HHIII")


class SfoError(ValueError):
    pass


def parse(data: bytes) -> dict[str, str | int]:
    if len(data) < HEADER.size:
        raise SfoError("too short")
    magic, _, key_start, data_start, count = HEADER.unpack_from(data)
    if magic != b"\x00PSF":
        raise SfoError("not a PARAM.SFO")
    if HEADER.size + count * ENTRY.size > len(data):
        raise SfoError("entries outside the file")
    out: dict[str, str | int] = {}
    for i in range(count):
        key_off, fmt, length, _, data_off = ENTRY.unpack_from(data, HEADER.size + i * ENTRY.size)
        key_end = data.find(b"\x00", key_start + key_off)
        start = data_start + data_off
        if key_end < 0 or start + length > len(data):
            raise SfoError(f"entry {i} outside the file")
        key = data[key_start + key_off:key_end].decode("utf-8", "replace")
        raw = data[start:start + length]
        if fmt == 0x0404 and length == 4:
            out[key] = struct.unpack("<I", raw)[0]
        elif fmt in (0x0004, 0x0204):
            out[key] = raw.split(b"\x00", 1)[0].decode("utf-8", "replace")
    return out
