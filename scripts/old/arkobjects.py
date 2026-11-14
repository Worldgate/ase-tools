r"""
arkobjects.py - walk the object list of an ASE .ark (v9 or v11) and count classes.

Usage:  python arkobjects.py "Z:\ScorchedEarth_P.ark"

Proves whether the object table parses with Qowyn's v9 rules plus the v11 header
change. Standard library only.
"""

import collections
import struct
import sys


class Reader:
    def __init__(self, data):
        self.d = data
        self.o = 0

    def i16(self):
        v = struct.unpack_from("<h", self.d, self.o)[0]; self.o += 2; return v

    def i32(self):
        v = struct.unpack_from("<i", self.d, self.o)[0]; self.o += 4; return v

    def i64(self):
        v = struct.unpack_from("<q", self.d, self.o)[0]; self.o += 8; return v

    def f32(self):
        v = struct.unpack_from("<f", self.d, self.o)[0]; self.o += 4; return v

    def s(self):
        n = self.i32()
        if n == 0:
            return ""
        if n < 0:
            b = self.d[self.o:self.o - n * 2]; self.o += -n * 2
            return b.decode("utf-16le", "replace").rstrip("\0")
        b = self.d[self.o:self.o + n]; self.o += n
        return b.decode("latin1", "replace").rstrip("\0")


def main(path):
    """Header + object table pass."""
    data = open(path, "rb").read()
    r = Reader(data)
    ver = r.i16()
    sections = []
    if ver >= 11:
        sections = [(r.i64(), r.i64()) for _ in range(4)]
    bin_off = r.i32(); r.i32()
    name_off = r.i32(); prop_off = r.i32()
    game_time = r.f32(); save_count = r.i32()
    sublevels = [r.s() for _ in range(r.i32())]

    # embedded data (normally 0 on these maps)
    for _ in range(r.i32()):
        r.s()
        for _ in range(r.i32()):
            for _ in range(r.i32()):
                r.o += r.i32() * 4
    # data file object map
    for _ in range(r.i32()):
        r.i32()
        for _ in range(r.i32()):
            r.s()

    # name table
    save_o = r.o
    r.o = name_off
    names = [r.s() for _ in range(r.i32())]
    r.o = save_o

    def name():
        idx = r.i32(); inst = r.i32()
        base = names[idx - 1] if 0 < idx <= len(names) else f"<bad name {idx}>"
        return base if inst == 0 else f"{base}_{inst - 1}"

    count = r.i32()
    print(f"File: {path}")
    print(f"version {ver}, objects {count:,}, name table {len(names):,} entries, "
          f"saveCount {save_count}, sublevels {len(sublevels)}")

    classes = collections.Counter()
    bad = 0
    first_bad = None
    prop_offsets = []
    for i in range(count):
        start = r.o
        r.o += 16  # GUID
        cls = name()
        is_item = r.i32()
        for _ in range(r.i32()):
            name()
        r.i32()  # fromDataFile
        r.i32()  # dataFileIndex
        if r.i32():
            r.o += 24  # location + rotation
        poff = r.i32()
        unk = r.i32()
        prop_offsets.append(poff)
        if cls.startswith("<bad") or is_item not in (0, 1) or unk != 0:
            bad += 1
            if first_bad is None:
                first_bad = (i, start, cls, is_item, unk)
        classes[cls] += 1

    print(f"object list ended @0x{r.o:x} (properties block starts @0x{prop_off:x})")
    print(f"suspicious objects: {bad}" + (f", first at #{first_bad[0]} @0x{first_bad[1]:x}: {first_bad[2:]}" if first_bad else ""))

    dinos = {c: n for c, n in classes.items() if c.endswith("_Character_BP_C") or "_Character_BP" in c}
    pods = sum(n for c, n in classes.items() if "Cryopod" in c or "Cryo" in c and "Item" in c)
    print(f"\nclasses: {len(classes):,} distinct")
    print(f"creature-class objects: {sum(dinos.values()):,}   cryopod items: {pods:,}")
    print("\nTop 25 classes:")
    for c, n in classes.most_common(25):
        print(f"  {n:>7,}  {c}")




# ---------------------------------------------------------------------------
# property walker (size-based, so unknown value formats are skipped not misread)
def walk_properties(path):
    data = open(path, "rb").read()
    r = Reader(data)
    ver = r.i16()
    if ver >= 11:
        r.o += 64
    r.i32(); r.i32(); name_off = r.i32(); prop_off = r.i32(); r.f32(); r.i32()
    for _ in range(r.i32()):
        r.s()
    r.i32(); r.i32()  # embedded + object map (0 on these maps)
    save = r.o
    r.o = name_off
    names = [r.s() for _ in range(r.i32())]
    r.o = save

    def name():
        idx = r.i32(); inst = r.i32()
        base = names[idx - 1] if 0 < idx <= len(names) else None
        if base is None:
            raise ValueError(f"bad name index {idx}")
        return base if inst == 0 else f"{base}_{inst - 1}"

    objs = []
    for _ in range(r.i32()):
        r.o += 16
        cls = name(); r.i32()
        for _ in range(r.i32()):
            name()
        r.i32(); r.i32()
        if r.i32():
            r.o += 24
        poff = r.i32(); r.i32()
        objs.append((cls, poff))

    types = collections.Counter()
    ok = fail = 0
    first_fail = None
    tamed = collections.Counter()
    t_adult = t_baby = t_dead = 0
    baby_classes = collections.Counter()
    dead_classes = collections.Counter()
    pods_total = pods_filled = 0
    pod_bytes = 0
    for cls, poff in objs:
        r.o = prop_off + poff
        props = {}
        is_creature = cls.endswith("_Character_BP_C")
        is_pod = "Cryopod" in cls and cls.startswith("PrimalItem")
        try:
            for _ in range(5000):
                pname = name()
                if pname == "None":
                    break
                ptype = name()
                size = r.i32(); r.i32()  # size, index
                types[ptype] += 1
                if ptype == "BoolProperty":
                    if is_creature:
                        props[pname] = data[r.o] != 0
                    r.o += 1
                    continue
                if ptype in ("ByteProperty", "StructProperty", "ArrayProperty"):
                    name()  # enum / struct type / inner type
                elif ptype == "MapProperty":
                    name(); name()
                if is_creature and size == 4:
                    if ptype == "IntProperty":
                        props[pname] = struct.unpack_from("<i", data, r.o)[0]
                    elif ptype == "FloatProperty":
                        props[pname] = struct.unpack_from("<f", data, r.o)[0]
                if is_pod and pname == "CustomItemDatas":
                    props["_pod_size"] = size
                r.o += size
            else:
                raise ValueError("no None terminator")
            ok += 1
        except Exception as e:
            fail += 1
            if first_fail is None:
                first_fail = (cls, poff, str(e))
        if is_pod:
            pods_total += 1
            # an empty pod has no (or a tiny) CustomItemDatas; a filled one holds the dino bytes
            if props.get("_pod_size", 0) > 1000:
                pods_filled += 1
                pod_bytes += props["_pod_size"]
        if is_creature and props.get("TargetingTeam", 0) >= 50000:
            tamed[cls] += 1
            if props.get("bIsDead"):
                t_dead += 1
                dead_classes[cls] += 1
            elif props.get("bIsBaby") or props.get("BabyAge", 1.0) < 1.0:
                t_baby += 1
                baby_classes[cls] += 1
            else:
                t_adult += 1

    print(f"\n{path}")
    print(f"property blocks: {ok:,} parsed cleanly, {fail:,} failed")
    if first_fail:
        print(f"  first failure: {first_fail}")
    print("property types seen: " + ", ".join(f"{t} {n:,}" for t, n in types.most_common()))
    print(f"tamed creatures (TargetingTeam >= 50000): {sum(tamed.values()):,}")
    for c, n in tamed.most_common(8):
        print(f"  {n:>5,}  {c}")
    print(f"\n  adults {t_adult:,}   babies {t_baby:,}   dead {t_dead:,}")
    if baby_classes:
        print("  babies by species: " + ", ".join(f"{c.replace('_Character_BP_C', '')} {n}" for c, n in baby_classes.most_common(10)))
    if dead_classes:
        print("  dead by species:   " + ", ".join(f"{c.replace('_Character_BP_C', '')} {n}" for c, n in dead_classes.most_common(10)))
    print(f"\ncryopods: {pods_total:,} total, {pods_filled:,} filled (have dino data), "
          f"{pods_total - pods_filled:,} empty")
    print(f"  filled pod data: {pod_bytes:,} bytes")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print('Usage: python arkobjects.py "path\\to\\Map.ark"')
        sys.exit(1)
    main(sys.argv[1])
    walk_properties(sys.argv[1])
