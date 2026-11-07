import io
import os
import random

import pytest

from umdlibrary.tools import cso

from ..helpers import make_iso


@pytest.fixture(scope="module")
def iso():
    # Compressible sectors and incompressible ones, so both block kinds occur.
    return make_iso(pad_bytes=200 * 1024)


@pytest.mark.parametrize("block, align", [(2048, 0), (8192, 2), (2048, 4)])
def test_round_trip(iso, block, align):
    packed = cso.pack(iso, block_size=block, align=align)
    assert packed[:4] == b"CISO"
    assert cso.uncompressed_size(io.BytesIO(packed)) == len(iso)
    f = cso.CsoFile(io.BytesIO(packed), cache_blocks=4)
    assert f.total == len(iso) and f.block_size == block and f.align == align
    assert f.read() == iso
    # Random seeks, reads across block borders, tell, SEEK_END.
    rnd = random.Random(1)
    for _ in range(200):
        pos = rnd.randrange(len(iso))
        n = rnd.randrange(1, 3 * block)
        f.seek(pos)
        assert f.read(n) == iso[pos:pos + n]
        assert f.tell() == min(pos + n, len(iso))
    f.seek(-10, io.SEEK_END)
    assert f.read() == iso[-10:]
    assert f.read() == b""
    assert len(f._cache) <= 4


def test_raw_and_compressed_blocks_both_occur(iso):
    packed = cso.pack(iso)
    f = cso.CsoFile(io.BytesIO(packed))
    flags = [bool(e & cso.RAW_FLAG) for e in f._index[:-1]]
    assert any(flags) and not all(flags)
    assert len(packed) < len(iso)


def test_truncated(iso):
    packed = cso.pack(iso)
    # Cut inside the index: refused at open.
    with pytest.raises(cso.CsoError, match="truncated"):
        cso.CsoFile(io.BytesIO(packed[:40]))
    # Cut inside the data: the first block still opens, a later one fails.
    cut = cso.CsoFile(io.BytesIO(packed[:len(packed) * 2 // 3]))
    with pytest.raises(cso.CsoError, match="truncated"):
        cut.seek(0)
        cut.read()


def test_corrupt_block(iso):
    packed = bytearray(cso.pack(iso))
    f = cso.CsoFile(io.BytesIO(bytes(packed)))
    entry = f._index[1]
    assert not entry & cso.RAW_FLAG
    start = entry & 0x7FFFFFFF
    packed[start:start + 4] = b"\xff\xff\xff\xff"
    g = cso.CsoFile(io.BytesIO(bytes(packed)))
    g.seek(2048)
    with pytest.raises(cso.CsoError, match="block 1"):
        g.read(10)


@pytest.mark.parametrize("data, message", [
    (b"", "too short"),
    (b"ZISO" + b"\x00" * 20, "ZISO"),
    (b"NOPE" + b"\x00" * 20, "bad magic"),
    (cso.HEADER.pack(b"CISO", 24, 4096, 2048, 2, 0, b"\x00\x00"), "version 2"),
    (cso.HEADER.pack(b"CISO", 24, 4096, 3000, 1, 0, b"\x00\x00"), "block size"),
    (cso.HEADER.pack(b"CISO", 24, 0, 2048, 1, 0, b"\x00\x00"), "0 bytes"),
])
def test_bad_headers(data, message):
    with pytest.raises(cso.CsoError, match=message):
        cso.CsoFile(io.BytesIO(data))


def test_not_a_cso_size():
    with pytest.raises(cso.CsoError):
        cso.uncompressed_size(io.BytesIO(b"junk"))


def test_cli(iso, tmp_path, capsys):
    path = tmp_path / "a.cso"
    path.write_bytes(cso.pack(iso))
    out_iso = tmp_path / "a.iso"
    assert cso.main([str(path), "--extract", str(out_iso)]) == 0
    assert "iso size" in capsys.readouterr().out
    assert out_iso.read_bytes() == iso
    (tmp_path / "bad.cso").write_bytes(b"x")
    assert cso.main([str(tmp_path / "bad.cso")]) == 1
    assert os.path.getsize(path) < len(iso)
