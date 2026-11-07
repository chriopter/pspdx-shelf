import struct

import pytest

from umdlibrary.tools import sfo


def test_round_trip():
    values = {"TITLE": "Test Game", "DISC_ID": "ULES-01234", "PARENTAL_LEVEL": 3,
              "CATEGORY": "UG", "BOOTABLE": 1, "REGION": 32768, "TITLE_JP": "テスト"}
    data = sfo.build(values)
    assert data[:4] == sfo.MAGIC
    assert sfo.parse(data) == values


def test_layout_matches_the_format():
    data = sfo.build({"A": "x", "B": 7})
    magic, version, key_start, data_start, count = sfo.HEADER.unpack_from(data)
    assert (magic, version, count) == (sfo.MAGIC, 0x0101, 2)
    assert key_start == sfo.HEADER.size + 2 * sfo.ENTRY.size
    assert data_start % 4 == 0 and data_start > key_start
    key_off, fmt, length, max_len, data_off = sfo.ENTRY.unpack_from(data, sfo.HEADER.size)
    assert (fmt, length, max_len) == (sfo.FMT_UTF8, 2, 4)
    key_off, fmt, length, max_len, data_off = sfo.ENTRY.unpack_from(data, sfo.HEADER.size + sfo.ENTRY.size)
    assert (fmt, length, max_len) == (sfo.FMT_UINT32, 4, 4)
    assert struct.unpack_from("<I", data, data_start + data_off)[0] == 7


def test_utf8_special_without_terminator():
    # Format 0x0004: the bytes are the string, no terminator counted.
    raw = b"hello"
    header = sfo.HEADER.pack(sfo.MAGIC, 0x0101, sfo.HEADER.size + sfo.ENTRY.size,
                             sfo.HEADER.size + sfo.ENTRY.size + 4, 1)
    entry = sfo.ENTRY.pack(0, sfo.FMT_UTF8_SPECIAL, 5, 8, 0)
    data = header + entry + b"KEY\x00" + raw + b"\x00" * 3
    assert sfo.parse(data) == {"KEY": "hello"}


@pytest.mark.parametrize("data, message", [
    (b"", "too short"),
    (b"\x00PSX" + b"\x00" * 16, "bad magic"),
    (sfo.build({"A": "x"})[:24], "outside"),
])
def test_broken(data, message):
    with pytest.raises(sfo.SfoError, match=message):
        sfo.parse(data)


def test_unknown_format_and_bad_uint():
    data = bytearray(sfo.build({"A": 1}))
    off = sfo.HEADER.size + 2
    struct.pack_into("<H", data, off, 0x0104)
    with pytest.raises(sfo.SfoError, match="unknown data format"):
        sfo.parse(bytes(data))
    data = bytearray(sfo.build({"A": 1}))
    struct.pack_into("<I", data, sfo.HEADER.size + 4, 3)   # length 3 for a uint32
    with pytest.raises(sfo.SfoError, match="uint32 with length"):
        sfo.parse(bytes(data))


def test_cli(tmp_path, capsys):
    path = tmp_path / "PARAM.SFO"
    path.write_bytes(sfo.build({"TITLE": "Game", "BOOTABLE": 1}))
    assert sfo.main([str(path)]) == 0
    out = capsys.readouterr().out
    assert "TITLE" in out and "'Game'" in out and "BOOTABLE" in out
    (tmp_path / "junk").write_bytes(b"nope")
    assert sfo.main([str(tmp_path / "junk")]) == 1
