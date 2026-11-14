"""CustomItemDatas: cryopods, soul traps, hoversails, notes...
v9 keeps them inline; v11 keeps a small pointer into one of four out-of-line sections."""

import base64
import struct

from .buf import Buf, MAX_PROPERTY


def class_to_blueprint(name):
    path = name.split(" ", 1)[1] if " " in name else name
    if path.endswith("_C"):
        path = path[:-2]
    return f"Blueprint'{path}'"


# real records hold ~25 floats, 6 colors, 2 byte arrays; these caps only stop garbage
RECORD_MAX_LIST = 10_000
RECORD_MAX_ARRAYS = 64


def read_record(data, off, end=None):
    """v11 out-of-line custom-data record (verified against DinoDump on Gen2).
    `end` = end of the section it lives in; nothing may be read past it."""
    end = len(data) if end is None else end
    r = Buf(data, off)

    def cnt(min_each, cap):
        n = r.count(min_each, end)
        if n > cap:
            raise ValueError(f"record count {n} over cap {cap} at {r.o - 4}")
        return n

    rec = {"name": r.s()}
    rec["strings"] = [r.s() for _ in range(cnt(4, RECORD_MAX_LIST))]
    n = cnt(4, RECORD_MAX_LIST)
    rec["floats"] = list(struct.unpack_from(f"<{n}f", data, r.o)); r.o += 4 * n
    rec["names"] = [r.s() for _ in range(cnt(4, RECORD_MAX_LIST))]
    arrays = []
    for _ in range(cnt(4, RECORD_MAX_ARRAYS)):
        ln = cnt(1, MAX_PROPERTY)
        arrays.append((r.o, ln))
        r.o += ln
    n = cnt(8, RECORD_MAX_LIST)
    rec["doubles"] = list(struct.unpack_from(f"<{n}d", data, r.o)); r.o += 8 * n
    if r.o > end:
        raise ValueError("record runs past its section")
    return rec, arrays


def looks_like_record(data, at):
    """A custom-data record starts with a short readable name ("Dino", "Snapshot", ...)."""
    if at < 0 or at + 8 > len(data):
        return False
    n = struct.unpack_from("<i", data, at)[0]
    if not 1 <= n <= 128 or at + 4 + n > len(data):
        return False
    s = data[at + 4:at + 3 + n]
    return data[at + 3 + n] == 0 and all(32 <= c < 127 for c in s)


def locate_record(save, off, sec):
    """v11 splits out-of-line data into 2GB sections; byte 2 of each pointer entry names which.
    (Confirmed on EU-PVP-Official-Aberration233: 175,758 pods in section 0, 3,725 in section 1.)
    Returns (absolute offset, used_fallback, section end)."""
    secs = save.sections
    if 0 <= sec < len(secs) and off < secs[sec][1] and looks_like_record(save.data, secs[sec][0] + off):
        return secs[sec][0] + off, False, secs[sec][0] + secs[sec][1]
    raise ValueError(f"no record at offset {off} in section {sec}")


def pod_entries_v11(save, raw_cid):
    """Decode the small pointer struct a v11 item keeps in CustomItemDatas."""
    data = save.data
    p = Buf(data, raw_cid[0])
    entries, extra, fallback = [], False, 0
    for _ in range(p.count(26)):
        p.o += 1               # always 2
        sec = data[p.o]; p.o += 1   # section number: 0, or 1+ once a map passes 2GB of custom data
        off = p.i64()
        p.i32()                # 0 (one bee hive on Aberration233 had 1)
        classes = []
        for _ in range(p.count(8)):
            if p.i32() == 1:
                classes.append(class_to_blueprint(save.name(p)))
            else:
                oid = p.i32()
                classes.append("" if oid == -1 else f"object:{oid}")
        at, fb, sec_end = locate_record(save, off, sec)
        fallback += fb
        rec, arrays = read_record(data, at, sec_end)
        rec["classes"] = classes
        entries.append((rec, arrays))
    if p.o != raw_cid[0] + raw_cid[1]:
        extra = True  # e.g. bee hives carry a few extra bytes; record itself still read
    return entries, extra, fallback


def pod_entries_v9(save, cid_list):
    """v9 keeps the whole CustomItemData inline. Mapped from the generic decoder;
    checked against v11 output of the same items where possible."""
    entries = []
    for cd in cid_list or []:
        if not isinstance(cd, dict):
            continue
        rec = {"name": cd.get("CustomDataName", ""),
               "strings": cd.get("CustomDataStrings") or [],
               "floats": cd.get("CustomDataFloats") or [],
               "names": cd.get("CustomDataNames") or [],
               "doubles": (cd.get("CustomDataDoubles") or {}).get("Doubles") or []
               if isinstance(cd.get("CustomDataDoubles"), dict) else cd.get("CustomDataDoubles") or [],
               "classes": [class_to_blueprint(c["path"]) if isinstance(c, dict) and "path" in c else ""
                           for c in cd.get("CustomDataClasses") or []]}
        arrays = []
        cbytes = cd.get("CustomDataBytes") or {}
        for ba in (cbytes.get("ByteArrays") or []) if isinstance(cbytes, dict) else []:
            b = ba.get("Bytes") if isinstance(ba, dict) else None
            if isinstance(b, str):
                arrays.append(base64.b64decode(b))
            elif isinstance(b, list):
                arrays.append(bytes(b))
        entries.append((rec, arrays))
    return entries
