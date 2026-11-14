r"""
arkextract.py - pull every tamed dino, cryopod, egg and pregnancy out of ASE .ark saves
with no server, so the original saves can be shelved.

Usage:
  python arkextract.py SAVE [SAVE ...] [--out DIR] [--jobs N] [--compare DUMP]

  SAVE    a .ark file, an official save .zip containing a .ark, or a folder of either
  --out   where extracts go (default: an "extracts" folder next to this script)
  --jobs  maps processed at once (default 4; each needs roughly 2x the .ark size in RAM)
  --compare  a DinoDump zip/folder to check one map against (dinos and pods)

Examples:
  python arkextract.py "EU-PVE-Official-GenTwo1003 (2023-09-30).zip"
  python arkextract.py Gen2.ark --compare "EU-PVE-Official-GenTwo1003 (2023-09-30).zip"
  python arkextract.py D:\OfficialSaves --out D:\Extracts --jobs 16

Each map becomes  <save name>.extract.zip  containing:
  meta.json         map, save name, version, counts
  names.json        the save's name table (needed to re-read raw blocks later)
  dinos.jsonl       tamed world dinos, decoded (DinoDump-style fields + extras)
  dinos_raw.jsonl   the same dinos' raw property blocks (dino + status component), base64
  pods.jsonl/.bin   every item with custom data, in DinoDump's raw format (verified on v11)
  eggs.jsonl        fertilized eggs: decoded genetics + raw property block
Maps that already have an extract are skipped. Saves are only ever read.
Standard library only; runs the same on Windows and Linux.
"""

import base64
import json
import math
import multiprocessing as mp
import traceback
import os
import struct
import sys
import time
import zipfile
from pathlib import Path

STAT_COUNT = 12
# largest real property seen is ~20KB (a v9 cryopod); anything near this is corruption
MAX_PROPERTY = 64 * 1024 * 1024
# bump when output changes; extracts made by an older version are redone automatically
EXTRACTOR = "arkextract.py 4"
NATIVE_STRUCTS = {
    "Vector": "<3f", "Rotator": "<3f", "Vector2D": "<2f", "Quat": "<4f",
    "LinearColor": "<4f", "IntPoint": "<2i", "Color": "<4B",
}


# ---------------------------------------------------------------------------
# low-level reading

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


def props_to_dict(props):
    """Indexed properties (Colors[0..5], stats[0..11]) become {index: value}."""
    out = {}
    for name, idx, _t, val in props:
        if idx == 0 and name not in out:
            out[name] = val
        else:
            cur = out.get(name)
            if not isinstance(cur, dict) or "_idx" not in cur:
                cur = {"_idx": True, 0: cur} if name in out else {"_idx": True}
                out[name] = cur
            cur[idx] = val
    return out


def indexed(p, name, count, default=0):
    v = p.get(name)
    if v is None:
        return [default] * count
    if isinstance(v, dict) and v.get("_idx"):
        return [v.get(i, default) for i in range(count)]
    return [v] + [default] * (count - 1)


def ancestors(p, name):
    out = []
    for a in p.get(name) or []:
        if isinstance(a, dict):
            out.append({"male": a.get("MaleName", ""), "male_id1": a.get("MaleDinoID1", 0),
                        "male_id2": a.get("MaleDinoID2", 0), "female": a.get("FemaleName", ""),
                        "female_id1": a.get("FemaleDinoID1", 0), "female_id2": a.get("FemaleDinoID2", 0)})
    return out


def clean_json(v):
    """Drop the internal _idx markers, and turn NaN/inf (not valid JSON) into null."""
    if isinstance(v, dict):
        return {str(k): clean_json(x) for k, x in v.items() if k != "_idx"}
    if isinstance(v, list):
        return [clean_json(x) for x in v]
    if isinstance(v, float) and not math.isfinite(v):
        return None
    return v


# ---------------------------------------------------------------------------
# dinos, eggs, pods

def decode_dino(save, idx, p, status, map_name, save_name):
    cls, loc, _ = save.objects[idx]
    id1, id2 = p.get("DinoID1", 0), p.get("DinoID2", 0)
    base = status.get("BaseCharacterLevel", 1)
    extra = status.get("ExtraCharacterLevel", 0)
    ineff = status.get("TamedIneffectivenessModifier", 0.0)
    rec = {
        "id1": id1, "id2": id2, "id64": str((id1 << 32) | id2),
        "class": save.class_paths.get(cls, cls),
        "name": p.get("TamedName", ""),
        "female": bool(p.get("bIsFemale", False)),
        "tribe": p.get("TribeName", ""), "tribe_id": p.get("TargetingTeam", 0),
        "tamer": p.get("TamerString", ""), "owner": p.get("OwningPlayerName", ""),
        "imprinter": p.get("ImprinterName", ""),
        "mutations_paternal": p.get("RandomMutationsMale", 0),
        "mutations_maternal": p.get("RandomMutationsFemale", 0),
        "baby_age": p.get("BabyAge", 1.0),
        "level": base + extra, "level_wild": base,
        "imprint": status.get("DinoImprintingQuality", 0.0),
        "taming_effectiveness": 1.0 / (1.0 + ineff),
        "wild_levels": indexed(status, "NumberOfLevelUpPointsApplied", STAT_COUNT),
        "tamed_levels": indexed(status, "NumberOfLevelUpPointsAppliedTamed", STAT_COUNT),
        "colors": indexed(p, "ColorSetIndices", 6),
        "neutered": bool(p.get("bNeutered", False)),
        "clone": bool(p.get("bIsCloneDino", False)),
        "tamed_on_server": (p.get("TamedOnServerName") or "").strip(),
        "uploaded_from_server": (p.get("UploadedFromServerName") or "").strip(),
        "creation_time": p.get("OriginalCreationTime", 0.0),
        # some dinos fell out of the world and carry NaN/inf coordinates
        "location": [round(c) for c in loc] if loc and all(math.isfinite(c) for c in loc) else None,
        "ancestors_maternal": ancestors(p, "DinoAncestors"),
        "ancestors_paternal": ancestors(p, "DinoAncestorsMale"),
        "source": "world", "map": map_name, "save": save_name,
    }
    if "GestationEggNumberOfLevelUpPointsApplied" in p or "GestationEggColorSetIndices" in p:
        rec["gestation"] = {
            "wild_levels": indexed(p, "GestationEggNumberOfLevelUpPointsApplied", STAT_COUNT),
            "colors": indexed(p, "GestationEggColorSetIndices", 6),
            "mutations_maternal": p.get("GestationEggRandomMutationsFemale", 0),
            "mutations_paternal": p.get("GestationEggRandomMutationsMale", 0),
            "taming_effectiveness": 1.0 / (1.0 + p.get("GestationEggTamedIneffectivenessModifier", 0.0)),
        }
    return rec


def item_ids(p):
    iid = p.get("ItemId") or {}
    return iid.get("ItemID1"), iid.get("ItemID2")


def decode_egg(save, idx, p):
    cls = save.objects[idx][0]
    id1, id2 = item_ids(p)
    return {
        "class": cls, "item_id1": id1, "item_id2": id2,
        "wild_levels": indexed(p, "EggNumberOfLevelUpPointsApplied", STAT_COUNT),
        "colors": indexed(p, "EggColorSetIndices", 6),
        "mutations_maternal": p.get("EggRandomMutationsFemale", 0),
        "mutations_paternal": p.get("EggRandomMutationsMale", 0),
        "gender_override": p.get("EggGenderOverride", 0),
        "taming_effectiveness": 1.0 / (1.0 + p.get("EggTamedIneffectivenessModifier", 0.0)),
        "ancestors_maternal": ancestors(p, "EggDinoAncestors"),
        "ancestors_paternal": ancestors(p, "EggDinoAncestorsMale"),
    }


def note_error(kinds, examples, where, cls, e):
    """Group errors by what failed (numbers stripped) and keep a few full examples."""
    import re as _re
    msg = f"{where}: {type(e).__name__}: {e}"
    key = _re.sub(r"\d+", "#", f"{where} {cls.split('_C')[0][:40]}: {type(e).__name__}: {e}")[:160]
    kinds[key] = kinds.get(key, 0) + 1
    if len(examples) < 10:
        examples.append(f"{cls}: {msg}"[:300])


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


# ---------------------------------------------------------------------------
# one map

def extract_map(job):
    """Never raises: one bad map is reported and the batch carries on."""
    src, out_dir, verbose = job
    try:
        return _extract_map(src, out_dir, verbose)
    except Exception as e:
        tmp = Path(out_dir) / f"{Path(src).stem}.extract.zip.partial"
        try:
            tmp.unlink()
        except OSError:
            pass
        log = Path(out_dir) / "errors.log"
        with open(log, "a", encoding="utf-8") as f:
            f.write(f"=== {Path(src).name}\n{traceback.format_exc()}\n")
        return f"{Path(src).stem}: FAILED ({type(e).__name__}: {e}) - details in errors.log, will retry next run"


def _extract_map(src, out_dir, verbose=False):
    t0 = time.time()
    src = Path(src)
    try:
        if src.suffix.lower() == ".zip":
            with zipfile.ZipFile(src) as z:
                member = next(n for n in z.namelist() if n.lower().endswith(".ark"))
                data = z.read(member)
            map_name = Path(member).stem
        else:
            data = src.read_bytes()
            map_name = src.stem
        save_name = src.stem
        out_path = Path(out_dir) / f"{save_name}.extract.zip"
        print(f"  started {save_name} ({len(data) / 1_073_741_824:.1f} GB)", flush=True)
        save = Save(data)
    except StopIteration:
        raise ValueError("zip has no .ark file inside") from None
    except Exception as e:
        # re-raise so extract_map logs it to errors.log like any other failure
        raise ValueError(f"cannot read save: {type(e).__name__}: {e}") from e

    dinos, dinos_raw, eggs, pods = [], [], [], []
    errors = pointer_extra = section_fallbacks = 0
    err_kinds, err_examples = {}, []
    total = len(save.objects)
    for idx, (cls, loc, poff) in enumerate(save.objects):
        if verbose and idx and idx % 250_000 == 0:
            print(f"    {idx:,} / {total:,} objects  {len(dinos):,} tamed  {len(pods):,} items  "
                  f"{errors} errors  ({time.time() - t0:.0f}s)", flush=True)
        is_creature = cls.endswith("_Character_BP_C") or "_Character_BP_" in cls
        is_item = cls.startswith("PrimalItem")
        if not (is_creature or is_item):
            continue
        is_egg = is_item and "_Fertilized" in cls and "Egg" in cls
        # quick pass first: most creatures are wild and most items carry nothing we keep
        try:
            qnames, qints, qcid = save.quick(idx)
        except Exception as e:
            errors += 1
            note_error(err_kinds, err_examples, "props", cls, e)
            continue
        if is_creature and (qints.get("TargetingTeam", 0) < 50000 or "DinoID1" not in qnames):
            continue
        if is_item and not is_egg and "CustomItemDatas" not in qnames:
            continue
        try:
            raw, plist = save.prop_block(idx)
        except Exception as e:
            errors += 1
            note_error(err_kinds, err_examples, "props", cls, e)
            continue
        try:
            p = props_to_dict(plist)

            if is_creature:
                if p.get("TargetingTeam", 0) < 50000 or "DinoID1" not in p:
                    continue
                status, sraw = {}, b""
                ref = p.get("MyCharacterStatusComponent")
                if isinstance(ref, dict) and "id" in ref and 0 <= ref["id"] < len(save.objects):
                    try:
                        sraw, slist = save.prop_block(ref["id"])
                        status = props_to_dict(slist)
                    except Exception as e:
                        errors += 1
                        note_error(err_kinds, err_examples, "status", cls, e)
                rec = decode_dino(save, idx, p, status, map_name, save_name)
                dinos.append(rec)
                dinos_raw.append({"id1": rec["id1"], "id2": rec["id2"], "class": cls,
                                  "props_b64": base64.b64encode(raw).decode(),
                                  "status_class": save.objects[ref["id"]][0] if sraw else None,
                                  "status_b64": base64.b64encode(sraw).decode()})
                continue

            # items
            if is_egg:
                egg = decode_egg(save, idx, p)
                egg["props_b64"] = base64.b64encode(raw).decode()
                eggs.append(egg)
            if "CustomItemDatas" not in p:
                continue
            id1, id2 = item_ids(p)
            try:
                if save.version >= 11:
                    cid = qcid
                    entries, extra, fb = pod_entries_v11(save, cid)
                    pointer_extra += extra
                    section_fallbacks += fb
                    entries = [(rec, [data[o:o + n] for o, n in arrs]) for rec, arrs in entries]
                else:
                    entries = pod_entries_v9(save, p.get("CustomItemDatas"))
            except Exception as e:
                errors += 1
                note_error(err_kinds, err_examples, "custom data", cls, e)
                continue
            if entries:
                pods.append({"class": cls, "item_id1": id1, "item_id2": id2, "entries": entries})
        except Exception as e:  # one damaged object never stops the map
            errors += 1
            note_error(err_kinds, err_examples, "decode", cls, e)

    # ---- write the extract
    tmp = out_path.with_name(out_path.name + ".partial")
    pod_bytes = 0
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        with z.open("pods.bin", "w", force_zip64=True) as bf:
            jl = []
            for pod in pods:
                cds = []
                for rec, arrays in pod["entries"]:
                    ba = []
                    for b in arrays:
                        bf.write(b)
                        ba.append({"offset": pod_bytes, "length": len(b)})
                        pod_bytes += len(b)
                    cds.append({"name": rec["name"], "strings": rec["strings"],
                                "floats": rec["floats"], "doubles": rec["doubles"],
                                "names": rec["names"], "classes": rec["classes"],
                                "objects": [], "byte_arrays": ba})
                jl.append(json.dumps({"class": pod["class"], "item_id1": pod["item_id1"],
                                      "item_id2": pod["item_id2"], "custom_data": cds}))
        z.writestr("pods.jsonl", "\n".join(jl) + "\n" if jl else "")
        z.writestr("dinos.jsonl", "".join(json.dumps(clean_json(d), ensure_ascii=False) + "\n" for d in dinos))
        z.writestr("dinos_raw.jsonl", "".join(json.dumps(d) + "\n" for d in dinos_raw))
        z.writestr("eggs.jsonl", "".join(json.dumps(clean_json(e), ensure_ascii=False) + "\n" for e in eggs))
        z.writestr("names.json", json.dumps(save.names))
        n_cryo = sum(1 for p in pods if "Cryopod" in p["class"])
        meta = {"save": save_name, "map": map_name, "source_file": src.name,
                "version": save.version, "save_count": save.save_count, "game_time": save.game_time,
                "objects": len(save.objects), "tamed_world_dinos": len(dinos),
                "babies": sum(1 for d in dinos if d["baby_age"] < 1),
                "pregnant": sum(1 for d in dinos if "gestation" in d),
                "items_with_custom_data": len(pods), "cryopods": n_cryo, "pod_bytes": pod_bytes,
                "fertilized_eggs": len(eggs), "errors": errors, "pointer_extra": pointer_extra,
                "section_fallbacks": section_fallbacks,
                "error_kinds": dict(sorted(err_kinds.items(), key=lambda kv: -kv[1])[:20]),
                "error_examples": err_examples,
                "data_sections": [s for s in save.sections if s[1]],
                "extractor": EXTRACTOR, "seconds": round(time.time() - t0, 1)}
        z.writestr("meta.json", json.dumps(meta, indent=1))
    os.replace(tmp, out_path)
    if verbose and err_kinds:
        print("  errors by kind:", flush=True)
        for k, n in sorted(err_kinds.items(), key=lambda kv: -kv[1])[:10]:
            print(f"    {n:>7,}  {k}", flush=True)
    if verbose:
        print(f"  section fallbacks: {section_fallbacks:,}   data sections: "
              f"{[s for s in save.sections if s[1]]}", flush=True)
    return (f"{save_name}: v{save.version}  {len(dinos):,} tamed  {n_cryo:,} pods  "
            f"{len(eggs):,} eggs  {meta['pregnant']} pregnant  {errors} errors  "
            f"({meta['seconds']}s)")


# ---------------------------------------------------------------------------
# compare one extract against a DinoDump

def close(a, b, rel=1e-6, absol=1e-6):
    try:
        return a == b or abs(a - b) <= max(rel * max(abs(a), abs(b)), absol)
    except TypeError:
        return False


def read_dump(target, member):
    target = Path(target)
    if target.is_file():
        with zipfile.ZipFile(target) as z:
            names = [n for n in z.namelist() if n.endswith(member)]
            return z.read(names[0]) if names else None
    hits = list(target.rglob(member))
    return hits[0].read_bytes() if hits else None


def compare(extract_path, target):
    print(f"\nComparing {Path(extract_path).name} against {Path(target).name}")
    with zipfile.ZipFile(extract_path) as z:
        mine = [json.loads(l) for l in z.read("dinos.jsonl").splitlines() if l.strip()]
        my_pods = [json.loads(l) for l in z.read("pods.jsonl").splitlines() if l.strip()]
        my_bin = z.read("pods.bin")

    # ---- dinos
    raw = read_dump(target, "dinos.jsonl")
    if raw is None:
        print("  no dinos.jsonl in dump")
    else:
        dump = {}
        for l in raw.splitlines():
            if l.strip():
                j = json.loads(l)
                dump[(j.get("id1"), j.get("id2"))] = j
        me = {(d["id1"], d["id2"]): d for d in mine}
        both = me.keys() & dump.keys()
        print(f"\nDINOS  extract {len(me):,}   dump {len(dump):,}   matched {len(both):,}")
        fields = ["female", "tribe", "tribe_id", "mutations_paternal", "mutations_maternal",
                  "baby_age", "level", "level_wild", "imprint", "taming_effectiveness",
                  "wild_levels", "tamed_levels", "colors", "tamed_on_server",
                  "uploaded_from_server", "creation_time", "location", "name",
                  "ancestors_maternal", "ancestors_paternal", "class"]
        bad = {f: 0 for f in fields}
        examples = {}
        missing_keys = set()
        for k in both:
            a, b = me[k], dump[k]
            missing_keys |= set(b) - set(a)
            for f in fields:
                if f not in b:
                    continue
                x, y = a.get(f), b[f]
                if f == "class":
                    ok = str(y).endswith(str(x).rsplit(".", 1)[-1])
                elif f == "location":
                    ok = x is not None and len(x) == len(y) and all(abs(p - q) <= 1.5 for p, q in zip(x, y))
                elif isinstance(y, float) or isinstance(x, float):
                    ok = close(x, y, 1e-5)
                elif isinstance(y, list) and y and isinstance(y[0], dict):
                    ok = len(x) == len(y) and all(
                        all((close(p[kk], q[kk], 0, 0) if isinstance(q[kk], (int, float)) else p[kk] == q[kk])
                            for kk in q if kk in p) for p, q in zip(x, y))
                else:
                    ok = x == y
                if not ok:
                    bad[f] += 1
                    examples.setdefault(f, (k, x, y))
        print("  mismatches: " + (", ".join(f"{f} {n:,}" for f, n in bad.items() if n) or "none"))
        if not any(bad.values()) and both:
            print("  every compared field matches on every matched dino")
        for f, (k, x, y) in list(examples.items())[:8]:
            print(f"    {f} e.g. {k}: extract={str(x)[:120]}  dump={str(y)[:120]}")
        if missing_keys:
            print(f"  dump fields not produced from the save: {sorted(missing_keys)}")
        oe = [me[k] for k in me.keys() - dump.keys()]
        od = [dump[k] for k in dump.keys() - me.keys()]
        print(f"  only in extract: {len(oe):,}   only in dump: {len(od):,}")
        if oe:
            print("    extract-only e.g.: " + ", ".join(
                f"{d['class'].rsplit('.', 1)[-1].replace('_Character_BP_C', '')}"
                f"{' (baby)' if d['baby_age'] < 1 else ''}" for d in oe[:12]))
        if od:
            print("    dump-only e.g.: " + ", ".join(str(d.get("class", "?")).rsplit(".", 1)[-1] for d in od[:12]))

    # ---- pods
    raw = read_dump(target, "pods.jsonl")
    pb = read_dump(target, "pods.bin")
    if raw is None or pb is None:
        print("  no pods.jsonl/pods.bin in dump")
        return
    dump = {}
    for l in raw.splitlines():
        if l.strip():
            j = json.loads(l)
            dump[(j.get("item_id1"), j.get("item_id2"))] = j
    me = {(p["item_id1"], p["item_id2"]): p for p in my_pods}
    both = me.keys() & dump.keys()
    bad = 0
    for k in both:
        a, b = me[k]["custom_data"], dump[k].get("custom_data") or []
        ok = len(a) == len(b)
        for x, y in zip(a, b):
            ok = ok and x["strings"] == y.get("strings", []) and x["names"] == y.get("names", []) \
                and x["classes"] == y.get("classes", []) \
                and len(x["floats"]) == len(y.get("floats", [])) \
                and all(close(p, q) for p, q in zip(x["floats"], y.get("floats", []))) \
                and len(x["doubles"]) == len(y.get("doubles", [])) \
                and all(close(p, q, 1e-7) for p, q in zip(x["doubles"], y.get("doubles", []))) \
                and len(x["byte_arrays"]) == len(y.get("byte_arrays", [])) \
                and all(my_bin[s["offset"]:s["offset"] + s["length"]] == pb[t["offset"]:t["offset"] + t["length"]]
                        for s, t in zip(x["byte_arrays"], y.get("byte_arrays", [])))
        bad += not ok
    only_dump = dump.keys() - me.keys()
    print(f"\nPODS  dump {len(dump):,}   matched {len(both):,}   mismatched {bad:,}   "
          f"only in dump {len(only_dump):,}   "
          f"extra items in extract (eggs, dermis, etc.) {len(me.keys() - dump.keys()):,}")
    if only_dump:
        import collections
        kinds = collections.Counter()
        for k in only_dump:
            j = dump[k]
            cds = j.get("custom_data") or []
            kinds[(j.get("item_name"), tuple(cd.get("name") for cd in cds),
                   sum(a.get("length", 0) for cd in cds for a in cd.get("byte_arrays", [])) > 1000)] += 1
        print("  only in dump, by kind (item, custom data names, has dino bytes):")
        for (item, cdn, has), n in kinds.most_common(15):
            print(f"    {n:>5,}  {item!r}  {list(cdn)}  {'DINO DATA' if has else 'no dino data'}")
        for k in list(only_dump)[:5]:
            j = dump[k]
            cd = (j.get("custom_data") or [{}])[0]
            print(f"    e.g. id {k[0]}/{k[1]}  {j.get('item_name')!r}  strings {cd.get('strings', [])[:3]}  "
                  f"owner {(j.get('owner') or {}).get('object')}")


# ---------------------------------------------------------------------------

def find_saves(args):
    out = []
    for a in args:
        p = Path(a)
        if p.is_dir():
            out += sorted(f for f in p.rglob("*") if f.suffix.lower() in (".ark", ".zip")
                          and not f.name.endswith(".extract.zip"))
        elif p.exists():
            out.append(p)
        else:
            print(f"not found: {a}")
    return out


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return

    def opt(flag, default=None):
        if flag in args:
            i = args.index(flag)
            v = args[i + 1]
            del args[i:i + 2]
            return v
        return default

    out_dir = Path(opt("--out", Path(__file__).resolve().parent / "extracts"))
    jobs = int(opt("--jobs", 4))
    target = opt("--compare")
    out_dir.mkdir(parents=True, exist_ok=True)
    saves = find_saves(args)
    todo, redo = [], 0
    for s in saves:
        ex = out_dir / f"{s.stem}.extract.zip"
        if not ex.exists():
            todo.append(s)
            continue
        try:
            with zipfile.ZipFile(ex) as z:
                meta = json.loads(z.read("meta.json"))
            current = meta.get("extractor") == EXTRACTOR
        except Exception:
            current = False
        if not current:
            todo.append(s)
            redo += 1
    skipped = len(saves) - len(todo)
    print(f"{len(saves)} save(s), {skipped} already extracted, {len(todo)} to do "
          f"({redo} redone: made by an older version) -> {out_dir}")
    t0 = time.time()
    if len(todo) <= 1 or jobs <= 1:
        for s in todo:
            print(extract_map((s, out_dir, True)), flush=True)
    else:
        with mp.Pool(min(jobs, len(todo))) as pool:
            for line in pool.imap_unordered(extract_map, [(s, out_dir, False) for s in todo]):
                print(line, flush=True)
    print(f"done in {time.time() - t0:.0f}s")
    if target and saves:
        compare(out_dir / f"{saves[0].stem}.extract.zip", target)


if __name__ == "__main__":
    mp.freeze_support()
    main()
