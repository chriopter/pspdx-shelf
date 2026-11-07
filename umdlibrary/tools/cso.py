"""CSO (CISO): a compressed ISO, read-only, as a file-like object.

    0x00  magic       b"CISO"
    0x04  u32         header size
    0x08  u64         total uncompressed bytes
    0x10  u32         block size
    0x14  u8          version
    0x15  u8          index alignment shift
    0x16  2 bytes     reserved
    0x18  u32 x (total // block + 1) index entries

Entry & 0x7fffffff, shifted left by the alignment, is the byte offset of the
block; the top bit set means the block is stored raw, otherwise it is a raw
zlib deflate stream (no header) that ends where the next block starts.

CsoFile has seek/read/tell so pycdlib can open it, keeps an LRU of
decompressed blocks and never reads more than a block at a time from disk,
so a 4 GB image costs nothing but its index. The tests hold a small writer,
pack(), so a synthetic ISO can be packed and read back."""
from __future__ import annotations

import io
import struct
import zlib
from collections import OrderedDict
from typing import BinaryIO

MAGIC = b"CISO"
HEADER = struct.Struct("<4sIQIBB2s")
RAW_FLAG = 0x80000000


class CsoError(ValueError):
    """Not a CSO, or one that ends before its index says it does."""


class CsoFile(io.RawIOBase):
    """A read-only, seekable view of the ISO inside a CSO."""

    def __init__(self, fp: BinaryIO, cache_blocks: int = 64):
        self._fp = fp
        self._pos = 0
        self._cache: OrderedDict[int, bytes] = OrderedDict()
        self._cache_blocks = cache_blocks
        fp.seek(0, io.SEEK_END)
        self.file_size = fp.tell()
        fp.seek(0)
        head = fp.read(HEADER.size)
        if len(head) < HEADER.size:
            raise CsoError("too short for a CSO header")
        magic, header_size, total, block, version, align, _ = HEADER.unpack(head)
        if magic == b"ZISO":
            raise CsoError("ZISO (LZ4) images are not supported")
        if magic != MAGIC:
            raise CsoError("bad magic, not a CSO")
        if version > 1:
            raise CsoError(f"CSO version {version} is not supported")
        if block == 0 or block & (block - 1) or block > 1 << 20:
            raise CsoError(f"implausible block size {block}")
        if total == 0:
            raise CsoError("CSO says it holds 0 bytes")
        self.total = total
        self.block_size = block
        self.align = align
        self.version = version
        count = (total + block - 1) // block + 1
        index_start = header_size if header_size >= HEADER.size else HEADER.size
        fp.seek(index_start)
        raw = fp.read(count * 4)
        if len(raw) < count * 4:
            raise CsoError(f"truncated: index needs {count * 4} bytes, "
                           f"the file has {len(raw)} after the header")
        self._index = struct.unpack(f"<{count}I", raw)
        # A quick sanity check on the first block so a truncated file is
        # refused at open, not at the first read pycdlib makes.
        self._block(0)

    # -- file-like -----------------------------------------------------------
    def readable(self) -> bool:
        """Return True: CSO streams are readable."""
        return True

    def seekable(self) -> bool:
        """Return True: CSO streams are seekable."""
        return True

    def tell(self) -> int:
        """Return the uncompressed stream position."""
        return self._pos

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        """Move to a position in the uncompressed stream."""
        if whence == io.SEEK_SET:
            new = offset
        elif whence == io.SEEK_CUR:
            new = self._pos + offset
        elif whence == io.SEEK_END:
            new = self.total + offset
        else:
            raise ValueError(f"bad whence {whence}")
        if new < 0:
            raise ValueError("negative seek position")
        self._pos = new
        return new

    def read(self, size: int = -1) -> bytes:
        """Read bytes from the uncompressed stream."""
        if size is None or size < 0:
            size = self.total - self._pos
        end = min(self._pos + size, self.total)
        if end <= self._pos:
            return b""
        out = bytearray()
        pos = self._pos
        while pos < end:
            block_no, inner = divmod(pos, self.block_size)
            chunk = self._block(block_no)
            take = min(len(chunk) - inner, end - pos)
            out += chunk[inner:inner + take]
            pos += take
        self._pos = pos
        return bytes(out)

    def readinto(self, b) -> int:  # pragma: no cover - RawIOBase plumbing
        """Read bytes into a writable buffer."""
        data = self.read(len(b))
        b[:len(data)] = data
        return len(data)

    def close(self) -> None:
        """Close the CSO and its underlying file."""
        if not self.closed:
            self._fp.close()
        super().close()

    # -- blocks --------------------------------------------------------------
    def _block(self, n: int) -> bytes:
        cached = self._cache.get(n)
        if cached is not None:
            self._cache.move_to_end(n)
            return cached
        if n >= len(self._index) - 1:
            raise CsoError(f"block {n} is past the end of the index")
        entry, nxt = self._index[n], self._index[n + 1]
        start = (entry & 0x7FFFFFFF) << self.align
        end = (nxt & 0x7FFFFFFF) << self.align
        if end < start or end > self.file_size:
            raise CsoError(f"truncated: block {n} would end at {end}, "
                           f"the file has {self.file_size} bytes")
        self._fp.seek(start)
        raw = self._fp.read(end - start)
        if len(raw) != end - start:
            raise CsoError(f"truncated: block {n} short read")
        if entry & RAW_FLAG:
            data = raw
        else:
            try:
                data = zlib.decompress(raw, -15)
            except zlib.error as exc:
                raise CsoError(f"block {n}: bad deflate stream ({exc})") from exc
        expected = min(self.block_size, self.total - n * self.block_size)
        if len(data) != expected:
            raise CsoError(f"block {n}: {len(data)} bytes, expected {expected}")
        self._cache[n] = data
        if len(self._cache) > self._cache_blocks:
            self._cache.popitem(last=False)
        return data


def uncompressed_size(fp: BinaryIO) -> int:
    """The size of the ISO inside a CSO, from the header alone."""
    fp.seek(0)
    head = fp.read(HEADER.size)
    if len(head) < HEADER.size or head[:4] != MAGIC:
        raise CsoError("not a CSO")
    return HEADER.unpack(head)[2]


def pack(iso: bytes, block_size: int = 2048, level: int = 9, align: int = 0) -> bytes:
    """A CSO holding iso. Blocks that do not shrink are stored raw, as
    ciso does. Written for the tests, but a real CSO all the same."""
    count = (len(iso) + block_size - 1) // block_size
    index = []
    blobs = []
    offset = HEADER.size + (count + 1) * 4
    for i in range(count):
        chunk = iso[i * block_size:(i + 1) * block_size]
        comp = zlib.compressobj(level, zlib.DEFLATED, -15)
        packed = comp.compress(chunk) + comp.flush()
        pad = (-offset) % (1 << align)
        offset += pad
        blobs.append(b"\x00" * pad)
        if len(packed) >= len(chunk):
            index.append((offset >> align) | RAW_FLAG)
            blobs.append(chunk)
            offset += len(chunk)
        else:
            index.append(offset >> align)
            blobs.append(packed)
            offset += len(packed)
    pad = (-offset) % (1 << align)
    blobs.append(b"\x00" * pad)
    offset += pad
    index.append(offset >> align)
    header = HEADER.pack(MAGIC, HEADER.size, len(iso), block_size, 1, align, b"\x00\x00")
    return header + struct.pack(f"<{count + 1}I", *index) + b"".join(blobs)


def main(argv: list[str] | None = None) -> int:
    """python -m umdlibrary.tools.cso IMAGE.cso [--extract OUT.iso]: print
    the header, or unpack the whole ISO to a file, block by block."""
    import argparse
    import sys
    parser = argparse.ArgumentParser(description="inspect or unpack a CSO")
    parser.add_argument("file")
    parser.add_argument("--extract", metavar="OUT.iso", help="write the ISO inside to this file")
    args = parser.parse_args(argv)
    try:
        cso = CsoFile(open(args.file, "rb"))
    except (CsoError, OSError) as exc:
        print(f"{args.file}: {exc}", file=sys.stderr)
        return 1
    with cso:
        print(f"version      {cso.version}")
        print(f"block size   {cso.block_size}")
        print(f"align shift  {cso.align}")
        print(f"iso size     {cso.total}")
        print(f"file size    {cso.file_size}")
        print(f"ratio        {cso.file_size / cso.total:.1%}")
        if args.extract:
            with open(args.extract, "wb") as out:
                pos = 0
                while pos < cso.total:
                    chunk = cso.read(1 << 20)
                    if not chunk:
                        break
                    out.write(chunk)
                    pos += len(chunk)
            print(f"wrote        {args.extract} ({pos} bytes)")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
