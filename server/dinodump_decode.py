#!/usr/bin/env python3
"""
dinodump_decode.py — decode the creature data packed inside ARK: Survival
Evolved cryopods (and the game's own GetDinoData output), offline.

The bytes use ARK's save-object format: a list of objects (the dino, its
status component, ...) each followed by a property list of
(name, type, size, index, value) entries ending in "None".

Use as a library:
    from dinodump_decode import decode_blob
    objects = decode_blob(raw_bytes)

Or from the command line:
    python dinodump_decode.py blob.bin              # dump one blob as JSON
    python dinodump_decode.py --b64 <base64 text>   # same, from base64

Standard library only.
"""
from __future__ import annotations

import base64
import json
import struct
import sys


class Reader:
    def __init__(self, data: bytes, pos: int = 0):
        self.d = data
        self.p = pos

    def need(self, n: int):
        if self.p + n > len(self.d):
            raise ValueError(f"read past end at {self.p} (+{n} of {len(self.d)})")

    def i8(self):
        self.need(1); v = struct.unpack_from("<b", self.d, self.p)[0]; self.p += 1; return v

    def u8(self):
        self.need(1); v = self.d[self.p]; self.p += 1; return v

    def i16(self):
        self.need(2); v = struct.unpack_from("<h", self.d, self.p)[0]; self.p += 2; return v

    def u16(self):
        self.need(2); v = struct.unpack_from("<H", self.d, self.p)[0]; self.p += 2; return v

    def i32(self):
        self.need(4); v = struct.unpack_from("<i", self.d, self.p)[0]; self.p += 4; return v

    def u32(self):
        self.need(4); v = struct.unpack_from("<I", self.d, self.p)[0]; self.p += 4; return v

    def i64(self):
        self.need(8); v = struct.unpack_from("<q", self.d, self.p)[0]; self.p += 8; return v

    def u64(self):
        self.need(8); v = struct.unpack_from("<Q", self.d, self.p)[0]; self.p += 8; return v

    def f32(self):
        self.need(4); v = struct.unpack_from("<f", self.d, self.p)[0]; self.p += 4; return v

    def f64(self):
        self.need(8); v = struct.unpack_from("<d", self.d, self.p)[0]; self.p += 8; return v

    def raw(self, n: int) -> bytes:
        self.need(n); v = self.d[self.p:self.p + n]; self.p += n; return v

    def fstring(self) -> str:
        n = self.i32()
        if n == 0:
            return ""
        if n < 0:  # UTF-16
            b = self.raw(-n * 2)
            return b[:-2].decode("utf-16-le", "replace")
        if n > 10_000_000:
            raise ValueError(f"absurd string length {n} at {self.p - 4}")
        b = self.raw(n)
        return b[:-1].decode("utf-8", "replace")


# structs stored as raw fixed-size values rather than property lists
NATIVE_STRUCTS = {
    "Vector": lambda r: [r.f32(), r.f32(), r.f32()],
    "Rotator": lambda r: [r.f32(), r.f32(), r.f32()],
    "Vector2D": lambda r: [r.f32(), r.f32()],
    "Quat": lambda r: [r.f32(), r.f32(), r.f32(), r.f32()],
    "Color": lambda r: [r.u8(), r.u8(), r.u8(), r.u8()],
    "LinearColor": lambda r: [r.f32(), r.f32(), r.f32(), r.f32()],
    "UniqueNetIdRepl": lambda r: (lambda unk: r.fstring())(r.i32()),
    "Guid": lambda r: r.raw(16).hex(),
    "IntPoint": lambda r: [r.i32(), r.i32()],
    "ItemNetID": lambda r: [r.u32(), r.u32()],
}


def read_object_ref(r: Reader):
    kind = r.i32()
    if kind == 0:
        return {"object_index": r.i32()}
    if kind == 1:
        return {"path": r.fstring()}
    return {"kind": kind}


def read_simple(r: Reader, typ: str, size: int):
    if typ == "IntProperty": return r.i32()
    if typ == "UInt32Property": return r.u32()
    if typ == "Int64Property": return r.i64()
    if typ == "UInt64Property": return r.u64()
    if typ == "Int16Property": return r.i16()
    if typ == "UInt16Property": return r.u16()
    if typ == "Int8Property": return r.i8()
    if typ == "FloatProperty": return r.f32()
    if typ == "DoubleProperty": return r.f64()
    if typ == "StrProperty": return r.fstring()
    if typ == "NameProperty": return r.fstring()
    if typ == "ObjectProperty": return read_object_ref(r)
    return None


def read_properties(r: Reader, end: int | None = None, depth: int = 0) -> list[dict]:
    """Property list until 'None'. Each entry: {name, type, index, value}."""
    props = []
    while True:
        if end is not None and r.p >= end:
            break
        name = r.fstring()
        if name == "None" or name == "":
            break
        typ = r.fstring()
        size = r.i32()
        index = r.i32()
        entry = {"name": name, "type": typ, "index": index}

        if typ == "BoolProperty":
            entry["value"] = bool(r.u8())
            props.append(entry)
            continue

        if typ == "ByteProperty":
            enum = r.fstring()
            start = r.p
            entry["value"] = r.u8() if enum == "None" else r.fstring()
            if enum != "None":
                entry["enum"] = enum
            r.p = start + size
            props.append(entry)
            continue

        if typ == "StructProperty":
            stype = r.fstring()
            start = r.p
            entry["struct"] = stype
            try:
                if stype in NATIVE_STRUCTS:
                    entry["value"] = NATIVE_STRUCTS[stype](r)
                else:
                    entry["value"] = props_to_dict(read_properties(r, start + size, depth + 1))
            except Exception as e:  # noqa: BLE001
                entry["error"] = str(e)
            r.p = start + size
            props.append(entry)
            continue

        if typ == "ArrayProperty":
            inner = r.fstring()
            start = r.p
            entry["inner"] = inner
            try:
                count = r.i32()
                items = []
                if inner == "StructProperty":
                    # elements are property lists (ARK cryopod / save format)
                    for _ in range(count):
                        items.append(props_to_dict(read_properties(r, start + size, depth + 1)))
                elif inner == "ByteProperty":
                    items = list(r.raw(count)) if size - 4 == count else r.raw(size - 4).hex()
                elif inner == "BoolProperty":
                    items = [bool(r.u8()) for _ in range(count)]
                else:
                    for _ in range(count):
                        items.append(read_simple(r, inner, 0))
                entry["value"] = items
            except Exception as e:  # noqa: BLE001
                entry["error"] = str(e)
            r.p = start + size
            props.append(entry)
            continue

        start = r.p
        try:
            v = read_simple(r, typ, size)
            if v is None and typ not in ("ObjectProperty",):
                entry["raw_hex"] = r.raw(size).hex()
            else:
                entry["value"] = v
        except Exception as e:  # noqa: BLE001
            entry["error"] = str(e)
        r.p = start + size
        props.append(entry)
    return props


def props_to_dict(props: list[dict]) -> dict:
    """Flatten a property list to {name: value} (static arrays become lists)."""
    out: dict = {}
    for p in props:
        v = p.get("value", p.get("raw_hex"))
        if p["name"] in out and isinstance(out[p["name"]], dict) and out[p["name"]].get("__array__"):
            out[p["name"]]["items"][p["index"]] = v
        elif p["index"] > 0 or p["name"] in out:
            prev = out.get(p["name"])
            arr = prev if isinstance(prev, dict) and prev.get("__array__") else {"__array__": True, "items": {0: prev} if p["name"] in out else {}}
            arr["items"][p["index"]] = v
            out[p["name"]] = arr
        else:
            out[p["name"]] = v
    for k, v in list(out.items()):
        if isinstance(v, dict) and v.get("__array__"):
            n = max(v["items"]) + 1
            out[k] = [v["items"].get(i) for i in range(n)]
    return out


def decode_blob(data: bytes) -> list[dict]:
    """Decode one packed object list. Returns [{class, names, location, properties}]."""
    r = Reader(data)
    count = r.i32()
    if not (0 < count < 1000):
        raise ValueError(f"unexpected object count {count}")
    headers = []
    for _ in range(count):
        guid = r.raw(16).hex()
        cls = r.fstring()
        is_item = r.u32()
        n_names = r.i32()
        names = [r.fstring() for _ in range(n_names)]
        from_data_file = r.u32()
        data_file_index = r.i32()
        has_loc = r.u32()
        loc = [r.f32() for _ in range(6)] if has_loc else None
        props_offset = r.i32()
        _zero = r.i32()
        headers.append({"guid": guid, "class": cls, "is_item": bool(is_item), "names": names,
                        "location": loc, "props_offset": props_offset,
                        "from_data_file": from_data_file, "data_file_index": data_file_index})
    objects = []
    for h in headers:
        pr = Reader(data, h["props_offset"])
        try:
            props = read_properties(pr)
            h["properties"] = props_to_dict(props)
        except Exception as e:  # noqa: BLE001
            h["properties"] = {}
            h["error"] = str(e)
        objects.append(h)
    return objects


def decode_item(data: bytes) -> dict:
    """Decode the second byte block of a cryopod: the dino's equipped saddle,
    stored as a single property list (no object header). Empty if no saddle."""
    if not data:
        return {}
    return props_to_dict(read_properties(Reader(data)))


def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "--b64":
        data = base64.b64decode(sys.argv[2])
    elif len(sys.argv) == 2:
        data = open(sys.argv[1], "rb").read()
    else:
        sys.exit(__doc__)
    print(json.dumps(decode_blob(data), indent=1, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
