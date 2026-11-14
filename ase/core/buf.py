"""Low-level binary reader shared by every ASE format reader."""

import struct

# largest real property seen is ~20KB (a v9 cryopod); anything near this is corruption
MAX_PROPERTY = 64 * 1024 * 1024


class Buf:
    __slots__ = ("d", "o")

    def __init__(self, d, o=0):
        self.d = d
        self.o = o

    def unpack(self, fmt):
        v = struct.unpack_from(fmt, self.d, self.o)
        self.o += struct.calcsize(fmt)
        return v

    def i16(self):
        return self.unpack("<h")[0]

    def i32(self):
        return self.unpack("<i")[0]

    def i64(self):
        return self.unpack("<q")[0]

    def count(self, min_each=1, end=None):
        """Read a list length and refuse impossible ones (corrupt data would
        otherwise make the reader loop billions of times)."""
        n = self.i32()
        room = (len(self.d) if end is None else end) - self.o
        if n < 0 or n * min_each > room:
            raise ValueError(f"impossible count {n} at {self.o - 4}")
        return n

    def s(self):
        n = self.i32()
        if n == 0:
            return ""
        if abs(n) * (2 if n < 0 else 1) > len(self.d) - self.o:
            raise ValueError(f"impossible string length {n} at {self.o - 4}")
        if n < 0:
            b = self.d[self.o:self.o - n * 2]; self.o += -n * 2
            return b.decode("utf-16le", "replace").rstrip("\0")
        b = self.d[self.o:self.o + n]; self.o += n
        return b.decode("utf-8", "replace").rstrip("\0")
