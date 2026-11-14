"""The .ark map save: header (v5-v11), name table, object table and the
generic property decoder. See docs/ASE_SAVE_FORMAT.md for the byte layout."""

import base64
import struct

from .buf import Buf, MAX_PROPERTY
from .props import props_to_dict

STAT_COUNT = 12
NATIVE_STRUCTS = {
    "Vector": "<3f", "Rotator": "<3f", "Vector2D": "<2f", "Quat": "<4f",
    "LinearColor": "<4f", "IntPoint": "<2i", "Color": "<4B",
}


class Save:
    """Header, name table and object table of one .ark."""

    def __init__(self, data):
        self.data = data
        r = Buf(data)
        self.version = v = r.i16()
        if not 5 <= v <= 11:
            raise ValueError(f"unsupported save version {v}")
        self.sections = [(r.i64(), r.i64()) for _ in range(4)] if v >= 11 else []
        # header fields by version (Qowyn's ark-savegame-toolkit): v7+ hibernation offset,
        # v6+ name table + properties block, v9+ save count
        if v >= 7:
            r.i32(); r.i32()
        self.name_off = r.i32() if v >= 6 else 0
        self.prop_off = r.i32() if v >= 6 else 0
        self.game_time = r.unpack("<f")[0]
        self.save_count = r.i32() if v >= 9 else 0
        self.sublevels = [r.s() for _ in range(r.count(4))]
        # embedded data (Qowyn: path, parts of blobs of int32s) - empty on most maps, not Ragnarok
        self.embedded = []
        for _ in range(r.count(8)):
            path = r.s()
            total = 0
            for _ in range(r.count(4)):
                for _ in range(r.count(4)):
                    n = r.count(4)
                    r.o += n * 4
                    total += n * 4
            self.embedded.append((path, total))
        # data-file object map: per sublevel, a list of object names
        self.data_file_map = 0
        for _ in range(r.count(8)):
            r.i32()  # level index
            for _ in range(r.count(4)):
                r.s()
            self.data_file_map += 1
        keep = r.o
        if self.name_off:
            r.o = self.name_off
            self.names = [r.s() for _ in range(r.count(4))]
        else:
            self.names = None  # v5: names are written inline as strings
        r.o = keep
        # short class name -> full blueprint path, where the save mentions it
        self.class_paths = {}
        for n in self.names or []:
            if n.startswith("BlueprintGeneratedClass "):
                path = n.split(" ", 1)[1]
                self.class_paths[path.rsplit(".", 1)[-1]] = path
        self.objects = []  # (class, location or None, property offset)
        for _ in range(r.count(40)):
            r.o += 16
            cls = self.name(r)
            r.i32()
            for _ in range(r.count(8)):
                self.name(r)
            r.i32(); r.i32()
            loc = r.unpack("<6f")[:3] if r.i32() else None
            poff = r.i32(); r.i32()
            self.objects.append((cls, loc, poff))

    def name(self, r):
        if self.names is None:
            return r.s()
        idx = r.i32(); inst = r.i32()
        base = self.names[idx - 1]
        return base if inst == 0 else f"{base}_{inst - 1}"

    def quick(self, idx):
        """Fast pass over an object's properties without decoding values: returns
        (property names, small int values, (start, size) of CustomItemDatas or None)."""
        d = self.data
        r = Buf(d, self.prop_off + self.objects[idx][2])
        names, ints, cid = set(), {}, None
        while True:
            pname = self.name(r)
            if pname == "None":
                return names, ints, cid
            ptype = self.name(r)
            size = r.i32(); r.i32()
            if size < 0 or size > MAX_PROPERTY or r.o + size > len(d):
                raise ValueError(f"impossible property size {size} for {pname}")
            names.add(pname)
            if ptype == "BoolProperty":
                r.o += 1
                continue
            if ptype in ("ByteProperty", "StructProperty", "ArrayProperty"):
                self.name(r)
            elif ptype == "MapProperty":
                self.name(r); self.name(r)
            if size == 4 and ptype in ("IntProperty", "UInt32Property"):
                ints[pname] = struct.unpack_from("<i", d, r.o)[0]
            elif pname == "CustomItemDatas":
                cid = (r.o, size)
            r.o += size

    def prop_block(self, idx):
        """(raw bytes, list of (name, index, type, value)) for object #idx."""
        start = self.prop_off + self.objects[idx][2]
        r = Buf(self.data, start)
        props = self.read_props(r)
        return self.data[start:r.o], props

    # -- generic property decoder ------------------------------------------
    def read_props(self, r, end=None):
        out = []
        while end is None or r.o < end:
            pname = self.name(r)
            if pname == "None":
                break
            ptype = self.name(r)
            size = r.i32(); idx = r.i32()
            if size < 0 or size > MAX_PROPERTY or r.o + size > len(self.data):
                raise ValueError(f"impossible property size {size} for {pname}")
            if ptype == "BoolProperty":
                out.append((pname, idx, ptype, self.data[r.o] != 0))
                r.o += 1
                continue
            sub = sub2 = None
            if ptype in ("ByteProperty", "StructProperty", "ArrayProperty"):
                sub = self.name(r)
            elif ptype == "MapProperty":
                sub = self.name(r); sub2 = self.name(r)
            vstart = r.o
            try:
                val = self.read_value(r, ptype, sub, size)
            except Exception:
                val = {"_raw": base64.b64encode(self.data[vstart:vstart + size]).decode()}
            r.o = vstart + size
            out.append((pname, idx, ptype, val))
        return out

    def read_value(self, r, ptype, sub, size):
        d = self.data
        simple = {"IntProperty": "<i", "UInt32Property": "<I", "Int16Property": "<h",
                  "UInt16Property": "<H", "Int8Property": "<b", "Int64Property": "<q",
                  "UInt64Property": "<Q", "FloatProperty": "<f", "DoubleProperty": "<d"}
        if ptype in simple:
            return struct.unpack_from(simple[ptype], d, r.o)[0]
        if ptype == "StrProperty":
            return r.s()
        if ptype == "NameProperty":
            return self.name(r)
        if ptype == "ByteProperty":
            return d[r.o] if sub == "None" else self.name(r)
        if ptype == "ObjectProperty":
            return self.read_ref(r)
        if ptype == "StructProperty":
            return self.read_struct(r, sub, r.o + size)
        if ptype == "ArrayProperty":
            return self.read_array(r, sub, size)
        return {"_raw": base64.b64encode(d[r.o:r.o + size]).decode()}

    def read_ref(self, r):
        kind = r.i32()
        if kind == 0:
            return {"id": r.i32()}
        return {"path": self.name(r)}

    def read_struct(self, r, stype, end):
        if stype in NATIVE_STRUCTS:
            return list(r.unpack(NATIVE_STRUCTS[stype]))
        if stype == "Guid":
            return self.data[r.o:r.o + 16].hex()
        return props_to_dict(self.read_props(r, end))

    def read_array(self, r, inner, size):
        end = r.o + size
        min_each = {"ByteProperty": 1, "BoolProperty": 1, "Int8Property": 1, "Int16Property": 2,
                    "UInt16Property": 2, "IntProperty": 4, "UInt32Property": 4, "FloatProperty": 4,
                    "DoubleProperty": 8, "Int64Property": 8, "UInt64Property": 8, "StrProperty": 4,
                    "NameProperty": 8, "ObjectProperty": 8, "StructProperty": 8}.get(inner, 1)
        n = r.count(min_each, end)
        d = self.data
        if inner == "ByteProperty":
            return base64.b64encode(d[r.o:r.o + n]).decode() if n > 16 else list(d[r.o:r.o + n])
        fmts = {"IntProperty": "i", "UInt32Property": "I", "FloatProperty": "f",
                "DoubleProperty": "d", "UInt16Property": "H", "Int16Property": "h",
                "UInt64Property": "Q", "Int64Property": "q", "Int8Property": "b"}
        if inner in fmts:
            return list(struct.unpack_from(f"<{n}{fmts[inner]}", d, r.o))
        if inner == "BoolProperty":
            return [b != 0 for b in d[r.o:r.o + n]]
        if inner == "StrProperty":
            return [r.s() for _ in range(n)]
        if inner == "NameProperty":
            return [self.name(r) for _ in range(n)]
        if inner == "ObjectProperty":
            return [self.read_ref(r) for _ in range(n)]
        if inner == "StructProperty":
            per = (end - r.o) / n if n else 0
            if per == 12:
                return [list(r.unpack("<3f")) for _ in range(n)]
            if per == 16:
                return [list(r.unpack("<4f")) for _ in range(n)]
            items = []
            for _ in range(n):
                if r.o >= end:
                    break
                items.append(props_to_dict(self.read_props(r, end)))
            return items
        return {"_raw": base64.b64encode(d[r.o:end]).decode()}
