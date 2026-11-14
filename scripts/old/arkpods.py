r"""
arkpods.py - pull every filled cryopod out of an ASE .ark (v9 or v11) with no server,
in DinoDump's raw format, and optionally check the result against an existing DinoDump.

Usage:
  python arkpods.py "Gen2.ark"
      -> writes Gen2_pods.jsonl + Gen2_pods.bin next to the .ark

  python arkpods.py "Gen2.ark" --compare "EU-PVE-Official-GenTwo1003 (2023-09-30).zip"
      -> same, then compares every pod against the DinoDump zip (or folder) by item ID:
         strings, floats, doubles, colors, class, and both byte arrays byte-for-byte

Read-only on the .ark and the dump. Standard library only.

Format notes (worked out from Gen2 / ScorchedEarth, Oct 2026):
  v11 header = v9 header with 4 x (int64 offset, int64 size) inserted after the version.
  v11 pods keep only a small pointer in CustomItemDatas:
      int32 entries; per entry: int16 flag, int64 offset (into section 1),
      int32 (0), int32 nclasses, nclasses x object reference
      (int32 type; type 1 = name(int32 index, int32 instance), type 0 = int32 object id)
  The record at section1 + offset is:
      string customDataName ("Dino"), string[] strings, float[] floats, string[] names (colors),
      bytes[] byteArrays (dino object, status component), double[] doubles
"""

import base64
import hashlib
import json
import struct
import sys
import time
import zipfile
from pathlib import Path


class Buf:
    __slots__ = ("d", "o")

    def __init__(self, d, o=0):
        self.d = d
        self.o = o

    def i16(self):
        v = struct.unpack_from("<h", self.d, self.o)[0]; self.o += 2; return v

    def i32(self):
        v = struct.unpack_from("<i", self.d, self.o)[0]; self.o += 4; return v

    def u32(self):
        v = struct.unpack_from("<I", self.d, self.o)[0]; self.o += 4; return v

    def i64(self):
        v = struct.unpack_from("<q", self.d, self.o)[0]; self.o += 8; return v

    def s(self):
        n = self.i32()
        if n == 0:
            return ""
        if n < 0:
            b = self.d[self.o:self.o - n * 2]; self.o += -n * 2
            return b.decode("utf-16le", "replace").rstrip("\0")
        b = self.d[self.o:self.o + n]; self.o += n
        return b.decode("latin1", "replace").rstrip("\0")


def class_to_blueprint(name):
    """'BlueprintGeneratedClass /Game/X/Rex_Character_BP.Rex_Character_BP_C'
       -> "Blueprint'/Game/X/Rex_Character_BP.Rex_Character_BP'" (DinoDump style)"""
    path = name.split(" ", 1)[1] if " " in name else name
    if path.endswith("_C"):
        path = path[:-2]
    return f"Blueprint'{path}'"


def read_record(data, off):
    """Decode one cryopod custom-data record at absolute offset `off`."""
    r = Buf(data, off)
    rec = {"name": r.s()}
    rec["strings"] = [r.s() for _ in range(r.i32())]
    n = r.i32()
    rec["floats"] = list(struct.unpack_from(f"<{n}f", data, r.o)); r.o += 4 * n
    rec["names"] = [r.s() for _ in range(r.i32())]
    arrays = []
    for _ in range(r.i32()):
        ln = r.i32()
        arrays.append((r.o, ln))
        r.o += ln
    n = r.i32()
    rec["doubles"] = list(struct.unpack_from(f"<{n}d", data, r.o)); r.o += 8 * n
    return rec, arrays, r.o


def extract(ark_path):
    t0 = time.time()
    data = Path(ark_path).read_bytes()
    r = Buf(data)
    ver = r.i16()
    sections = [(r.i64(), r.i64()) for _ in range(4)] if ver >= 11 else []
    r.i32(); r.i32(); name_off = r.i32(); prop_off = r.i32(); r.o += 8
    for _ in range(r.i32()):
        r.s()
    r.i32(); r.i32()
    keep = r.o
    r.o = name_off
    names = [r.s() for _ in range(r.i32())]
    r.o = keep

    def name(b):
        idx = b.i32(); inst = b.i32()
        base = names[idx - 1]
        return base if inst == 0 else f"{base}_{inst - 1}"

    pod_objs = []
    count = r.i32()
    for _ in range(count):
        r.o += 16
        cls = name(r); r.i32()
        for _ in range(r.i32()):
            name(r)
        r.i32(); r.i32()
        if r.i32():
            r.o += 24
        poff = r.i32(); r.i32()
        # any item can carry custom data (cryopods, Tek Hoversails, ...), same as DinoDump
        if cls.startswith("PrimalItem"):
            pod_objs.append((cls, poff))
    print(f"v{ver}, {count:,} objects, {len(pod_objs):,} items  ({time.time() - t0:.0f}s)")

    sec_base = sections[0][0] if sections else None
    pods, problems = [], []
    for cls, poff in pod_objs:
        b = Buf(data, prop_off + poff)
        id1 = id2 = None
        cid = None  # (payload start, size)
        while True:
            pname = name(b)
            if pname == "None":
                break
            ptype = name(b)
            size = b.i32(); b.i32()
            if ptype == "BoolProperty":
                b.o += 1
                continue
            sub = None
            if ptype in ("ByteProperty", "StructProperty", "ArrayProperty"):
                sub = name(b)
            elif ptype == "MapProperty":
                name(b); name(b)
            if pname == "ItemId":
                ib = Buf(data, b.o)
                while True:
                    n2 = name(ib)
                    if n2 == "None":
                        break
                    name(ib); sz2 = ib.i32(); ib.i32()
                    if n2 == "ItemID1":
                        id1 = struct.unpack_from("<I", data, ib.o)[0]
                    elif n2 == "ItemID2":
                        id2 = struct.unpack_from("<I", data, ib.o)[0]
                    ib.o += sz2
            elif pname == "CustomItemDatas":
                cid = (b.o, size)
            b.o += size
        if cid is None:
            continue  # empty pod

        start, size = cid
        if sec_base is None:
            problems.append((id1, id2, "v9 in-item pod data not handled yet"))
            continue
        p = Buf(data, start)
        entries = []
        for _ in range(p.i32()):
            p.i16()   # flag (2)
            off = p.i64()
            p.i32()   # always 0 so far
            classes = []
            for _ in range(p.i32()):
                # class is an object reference: type 1 = by name, type 0 = by object id
                if p.i32() == 1:
                    classes.append(class_to_blueprint(name(p)))
                else:
                    oid = p.i32()
                    classes.append("" if oid == -1 else f"object:{oid}")  # -1 = none
            try:
                rec, arrays, end = read_record(data, sec_base + off)
            except Exception as e:
                problems.append((id1, id2, cls, f"record at {off}: {e}"))
                continue
            rec["classes"] = classes
            rec["objects"] = []
            entries.append({"custom": rec, "arrays": arrays})
        if p.o != start + size:
            problems.append((id1, id2, cls, f"pointer size mismatch ({p.o - start} vs {size})"))
        if entries:
            pods.append({"item_id1": id1, "item_id2": id2, "class": cls, "entries": entries})

    n_pods = sum(1 for p in pods if "Cryopod" in p["class"])
    print(f"{len(pods):,} items with custom data decoded ({n_pods:,} cryopods, "
          f"{len(pods) - n_pods:,} other), {len(problems):,} problems  ({time.time() - t0:.0f}s)")
    for pr in problems[:10]:
        print("  problem:", pr)
    return data, pods


def write_out(ark_path, data, pods):
    ark_path = Path(ark_path)
    jpath = ark_path.with_name(ark_path.stem + "_pods.jsonl")
    bpath = ark_path.with_name(ark_path.stem + "_pods.bin")
    pos = 0
    with open(jpath, "w", encoding="utf-8") as jf, open(bpath, "wb") as bf:
        for pod in pods:
            cds = []
            for e in pod["entries"]:
                ba = []
                for off, ln in e["arrays"]:
                    bf.write(data[off:off + ln])
                    ba.append({"offset": pos, "length": ln})
                    pos += ln
                c = e["custom"]
                cds.append({"name": c["name"], "strings": c["strings"],
                            "floats": c["floats"], "doubles": c["doubles"],
                            "names": c["names"], "classes": c["classes"],
                            "objects": [], "byte_arrays": ba})
            line = {"class": pod["class"], "item_id1": pod["item_id1"],
                    "item_id2": pod["item_id2"], "custom_data": cds}
            jf.write(json.dumps(line) + "\n")
    print(f"Wrote {jpath.name} and {bpath.name} ({pos:,} bytes of pod data)")


def load_dump(target):
    target = Path(target)
    if target.is_file():
        with zipfile.ZipFile(target) as z:
            jl = z.read(next(n for n in z.namelist() if n.endswith("pods.jsonl")))
            pb = z.read(next(n for n in z.namelist() if n.endswith("pods.bin")))
    else:
        jl = next(target.rglob("pods.jsonl")).read_bytes()
        pb = next(target.rglob("pods.bin")).read_bytes()
    dump = {}
    for line in jl.splitlines():
        if line.strip():
            j = json.loads(line)
            dump[(j.get("item_id1"), j.get("item_id2"))] = j
    return dump, pb


def close(a, b, rel):
    return a == b or abs(a - b) <= rel * max(abs(a), abs(b), 1e-30)


def compare(data, pods, target):
    print(f"\nLoading DinoDump from {Path(target).name} ...")
    dump, pb = load_dump(target)
    print(f"{len(dump):,} items in dump, {len(pods):,} from the .ark")
    mine = {(p["item_id1"], p["item_id2"]): p for p in pods}
    both = mine.keys() & dump.keys()
    only_ark = mine.keys() - dump.keys()
    only_dump = dump.keys() - mine.keys()
    bad = {"strings": 0, "floats": 0, "doubles": 0, "names": 0, "classes": 0, "bytes": 0}
    examples = []
    for k in both:
        p, j = mine[k], dump[k]
        jcds = j.get("custom_data") or []
        diffs = []
        if len(jcds) != len(p["entries"]):
            diffs.append("entries")
        for e, jc in zip(p["entries"], jcds):
            c = e["custom"]
            if c["name"] != jc.get("name") or c["strings"] != jc.get("strings", []):
                diffs.append("strings")
            jf_ = jc.get("floats", [])
            if len(c["floats"]) != len(jf_) or not all(close(a, b, 1e-6) for a, b in zip(c["floats"], jf_)):
                diffs.append("floats")
            jd = jc.get("doubles", [])
            if len(c["doubles"]) != len(jd) or not all(close(a, b, 1e-7) for a, b in zip(c["doubles"], jd)):
                diffs.append("doubles")
            if c["names"] != jc.get("names", []):
                diffs.append("names")
            if c["classes"] != jc.get("classes", []):
                diffs.append("classes")
            ja = jc.get("byte_arrays", [])
            if len(ja) != len(e["arrays"]) or any(
                    ln != x["length"] or data[off:off + ln] != pb[x["offset"]:x["offset"] + x["length"]]
                    for (off, ln), x in zip(e["arrays"], ja)):
                diffs.append("bytes")
        diffs = sorted(set(diffs))
        for dname in diffs:
            bad[dname] = bad.get(dname, 0) + 1
        if diffs and len(examples) < 5:
            c0 = p["entries"][0]["custom"]
            ex = (k, p["class"], diffs, c0["strings"][1:2])
            if "classes" in diffs:
                ex += (f"ark={[e['custom']['classes'] for e in p['entries']]}",
                       f"dump={[jc.get('classes') for jc in jcds]}")
            examples.append(ex)
    print(f"\nmatched by item ID: {len(both):,}")
    print(f"  only in .ark (not in dump): {len(only_ark):,}")
    print(f"  only in dump (not in .ark): {len(only_dump):,}")
    print("mismatches: " + ", ".join(f"{k} {v:,}" for k, v in bad.items()))
    if examples:
        print("examples:")
        for e in examples:
            print("  ", e)
    elif both:
        print("Every matched pod is identical, byte arrays included.")
    if only_ark:
        print("  e.g. only in .ark:",
              [(mine[k]["class"], mine[k]["entries"][0]["custom"]["strings"][1:2]) for k in list(only_ark)[:8]])
    if only_dump:
        print(f"\nPods only in the dump (first 15 of {len(only_dump):,}):")
        for k in sorted(only_dump, key=lambda x: (x[0] or 0, x[1] or 0))[:15]:
            j = dump[k]
            cds = j.get("custom_data") or []
            for cd in cds or [{}]:
                arrays = [a.get("length") for a in cd.get("byte_arrays", [])]
                print(f"  id {k[0]}/{k[1]}  item {j.get('item_name')!r}  data {cd.get('name')!r}  "
                      f"strings {cd.get('strings')}  arrays {arrays}  "
                      f"classes {cd.get('classes')}")
        missing_bytes = sum(a.get("length", 0) for k in only_dump
                            for cd in (dump[k].get("custom_data") or [])
                            for a in cd.get("byte_arrays", []))
        print(f"  total byte-array data in these: {missing_bytes:,} bytes")


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(1)
    ark = args[0]
    target = args[args.index("--compare") + 1] if "--compare" in args else None
    data, pods = extract(ark)
    write_out(ark, data, pods)
    if target:
        compare(data, pods, target)


if __name__ == "__main__":
    main()
