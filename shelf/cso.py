"""CSO (CISO), a compressed ISO, read as a seekable file so pycdlib can open it.

    0x00  b"CISO", u32 header size, u64 ISO size, u32 block size, u8 version, u8 align, 2 reserved
    0x18  u32 index per block, plus one for the end

An entry's low 31 bits, shifted by align, are where its block starts; the top
bit set means stored raw, otherwise raw deflate up to the next entry."""
import functools
import io
import struct
import zlib

HEADER = struct.Struct("<4sIQIBB2s")


class CsoError(ValueError):
    pass


class CsoFile(io.RawIOBase):
    def __init__(self, fp):
        self._fp = fp
        self._pos = 0
        magic, _, self.size, self.block, _, self.align, _ = HEADER.unpack(fp.read(HEADER.size).ljust(HEADER.size))
        if magic != b"CISO":
            raise CsoError("not a CSO")
        if not self.size or not self.block or self.block & (self.block - 1):
            raise CsoError("bad header")
        count = -(-self.size // self.block) + 1
        raw = fp.read(count * 4)
        if len(raw) < count * 4:
            raise CsoError("index cut short")
        self._index = struct.unpack(f"<{count}I", raw)
        self._read_block = functools.lru_cache(maxsize=16)(self._read_block)

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self._pos

    def seek(self, offset, whence=io.SEEK_SET):
        self._pos = {io.SEEK_SET: 0, io.SEEK_CUR: self._pos, io.SEEK_END: self.size}[whence] + offset
        return self._pos

    def read(self, n=-1):
        end = self.size if n is None or n < 0 else min(self._pos + n, self.size)
        out = bytearray()
        while self._pos < end:
            number, skip = divmod(self._pos, self.block)
            chunk = self._read_block(number)[skip:min(self.block, skip + end - self._pos)]
            out += chunk
            self._pos += len(chunk)
        return bytes(out)

    def readinto(self, buffer):
        data = self.read(len(buffer))
        buffer[:len(data)] = data
        return len(data)

    def close(self):
        self._fp.close()
        super().close()

    def _read_block(self, number):
        entry, following = self._index[number], self._index[number + 1]
        start, end = (entry & 0x7FFFFFFF) << self.align, (following & 0x7FFFFFFF) << self.align
        self._fp.seek(start)
        raw = self._fp.read(end - start)
        try:
            data = raw if entry & 0x80000000 else zlib.decompressobj(-15).decompress(raw)
        except zlib.error as exc:
            raise CsoError(f"block {number}: {exc}") from None
        if len(data) < min(self.block, self.size - number * self.block):
            raise CsoError(f"block {number} cut short")
        return data
