r"""
arkheader.py - dump the header of an ASE .ark save so v9 and v12 can be compared.

Usage:  python arkheader.py "Z:\ScorchedEarth_P.ark"

Prints the raw first 128 bytes, then tries Qowyn's v9 header layout.
If the layout doesn't fit (v10+), it says where it stopped making sense,
so the raw bytes show what moved. Standard library only.
"""

import struct
import sys

V9_FIELDS = [
    ("binaryDataOffset", "<i"),
    ("unknownInt", "<i"),
    ("nameTableOffset", "<i"),
    ("propertiesBlockOffset", "<i"),
    ("gameTime", "<f"),
    ("saveCount", "<i"),
]


def hexdump(data, start=0, length=128):
    for row in range(start, start + length, 16):
        chunk = data[row:row + 16]
        hx = " ".join(f"{b:02x}" for b in chunk)
        txt = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        print(f"  {row:08x}  {hx:<47}  {txt}")


def main(path):
    if path.lower().endswith(".zip"):
        import zipfile
        with zipfile.ZipFile(path) as z:
            member = next(n for n in z.namelist() if n.lower().endswith(".ark"))
            data = z.read(member)
        path = f"{path} -> {member}"
    else:
        with open(path, "rb") as f:
            data = f.read()
    size = len(data)
    print(f"File: {path}")
    print(f"Size: {size:,} bytes\n")

    print("First 128 bytes:")
    hexdump(data)
    print()

    if data[:16] == b"SQLite format 3\x00":
        print("This is an ASA (SQLite) save, not ASE.")
        return

    o = 0
    version = struct.unpack_from("<h", data, o)[0]
    o += 2
    print(f"version               {version}")

    # v11+: four (int64 offset, int64 size) sections inserted after version.
    # Seen on ScorchedEarth: section 1 = small block at end of file, 2-4 empty.
    sections = []
    if version >= 11:
        print("\nv11 extra sections (offset, size):")
        for i in range(4):
            off, sz = struct.unpack_from("<qq", data, o)
            sections.append((off, sz))
            end_note = "  (ends at EOF)" if off + sz == size else ""
            print(f"  section {i + 1}: offset {off:,}  size {sz:,}{end_note}  @0x{o:x}")
            o += 16
        print()

    for name, fmt in V9_FIELDS:
        val = struct.unpack_from(fmt, data, o)[0]
        note = ""
        if "Offset" in name:
            note = "  ok (inside file)" if 0 < val < size else "  ** outside file - layout changed here? **"
        print(f"{name:<22}{val}{note}  @0x{o:x}")
        o += struct.calcsize(fmt)

    # data file (sublevel) name list - a length-prefixed string list in v9
    try:
        count = struct.unpack_from("<i", data, o)[0]
        print(f"\ndataFiles count       {count}  @0x{o:x}")
        if not 0 <= count < 1000:
            print("  ** not a sane count - header layout differs from v9 before this point **")
            return
        o += 4
        names = []
        for _ in range(count):
            n = struct.unpack_from("<i", data, o)[0]
            o += 4
            if n < 0:
                s = data[o:o - n * 2].decode("utf-16le", "replace")
                o += -n * 2
            else:
                s = data[o:o + n].decode("latin1", "replace")
                o += n
            names.append(s.rstrip("\0"))
        print("  sublevels: " + ", ".join(names))
        print(f"  list ends @0x{o:x}")
        print("\nBytes right after the sublevel list:")
        hexdump(data, o - (o % 16), 64)
    except Exception as e:
        print(f"  ** parse failed at 0x{o:x}: {e} **")
        return

    # region between binaryDataOffset and nameTableOffset (16 bytes in v9)
    bin_off = struct.unpack_from("<i", data, 2 + 64 * (version >= 11))[0]
    name_off = struct.unpack_from("<i", data, 10 + 64 * (version >= 11))[0]
    gap = name_off - bin_off
    print(f"\nbinaryData -> nameTable gap: {gap} bytes")
    if 0 < gap <= 256:
        hexdump(data, bin_off, gap)

    for i, (off, sz) in enumerate(sections):
        if sz > 0 and 0 <= off < size:
            print(f"\nSection {i + 1} contents (first {min(sz, 256)} of {sz:,} bytes):")
            hexdump(data, off, min(sz, 256))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print('Usage: python arkheader.py "path\\to\\Map.ark"')
        sys.exit(1)
    main(sys.argv[1])
