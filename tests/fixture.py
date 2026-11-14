"""
Build small synthetic ASE .ark saves (v9 and v11) for regression tests.

They contain one of everything the extractor cares about:
  - a tamed Raptor with a status component, colors, ancestry and a pregnancy
  - a wild Raptor (must be skipped by `tamed`)
  - a cryopod in v11 section 0 and a second one in section 1
    (tests the section byte in the pointer), or inline CustomItemDatas on v9
  - a fertilized egg with genetics
  - a storage box structure

Usage:
    python tests/fixture.py OUT_DIR       writes fixture_v9.ark and fixture_v11.ark
"""
import struct
import sys
from pathlib import Path


def fstr(s):
    if s == "":
        return struct.pack("<i", 0)
    b = s.encode("utf-8") + b"\0"
    return struct.pack("<i", len(b)) + b


class Names:
    def __init__(self):
        self.list, self.index = [], {}

    def ref(self, s):
        if s not in self.index:
            self.list.append(s)
            self.index[s] = len(self.list)  # 1-based
        return struct.pack("<ii", self.index[s], 0)


# ---- property encoders (save format, names from the name table) ------------

class P:
    """Encodes property lists. inline=True writes names as FStrings (cryopod blobs)."""

    def __init__(self, names=None):
        self.names = names

    def n(self, s):
        return fstr(s) if self.names is None else self.names.ref(s)

    def prop(self, name, ptype, value, index=0, extra=b""):
        return self.n(name) + self.n(ptype) + struct.pack("<ii", len(value), index) + extra + value

    def end(self):
        return self.n("None")

    def int(self, name, v, index=0):
        return self.prop(name, "IntProperty", struct.pack("<i", v), index)

    def uint32(self, name, v):
        return self.prop(name, "UInt32Property", struct.pack("<I", v))

    def uint16(self, name, v):
        return self.prop(name, "UInt16Property", struct.pack("<H", v))

    def float(self, name, v):
        return self.prop(name, "FloatProperty", struct.pack("<f", v))

    def double(self, name, v):
        return self.prop(name, "DoubleProperty", struct.pack("<d", v))

    def str(self, name, v):
        return self.prop(name, "StrProperty", fstr(v))

    def namep(self, name, v):
        return self.prop(name, "NameProperty", self.n(v))

    def bool(self, name, v):
        # value byte comes after the header and size is 0
        return self.n(name) + self.n("BoolProperty") + struct.pack("<ii", 0, 0) + bytes([1 if v else 0])

    def byte(self, name, v, index=0):
        return self.prop(name, "ByteProperty", bytes([v]), index, extra=self.n("None"))

    def obj(self, name, oid):
        return self.prop(name, "ObjectProperty", struct.pack("<ii", 0, oid))

    def struct(self, name, stype, body):
        return self.prop(name, "StructProperty", body, extra=self.n(stype))

    def array(self, name, inner, count, body):
        return self.prop(name, "ArrayProperty", struct.pack("<i", count) + body, extra=self.n(inner))


def ancestor(p, male, m1, m2, female, f1, f2):
    return (p.str("MaleName", male) + p.uint32("MaleDinoID1", m1) + p.uint32("MaleDinoID2", m2)
            + p.str("FemaleName", female) + p.uint32("FemaleDinoID1", f1)
            + p.uint32("FemaleDinoID2", f2) + p.end())


def dino_props(p, tamed, status_id, id1, id2, name="", gestation=False):
    out = p.uint32("DinoID1", id1) + p.uint32("DinoID2", id2)
    out += p.int("TargetingTeam", 1234567890 if tamed else 2000)
    if tamed:
        out += p.str("TamedName", name) + p.bool("bIsFemale", True)
        out += p.str("TribeName", "Tribe of Testing") + p.str("TamerString", "Tester")
        out += p.str("OwningPlayerName", "Tester") + p.str("ImprinterName", "Theseus")
        out += p.int("RandomMutationsFemale", 3) + p.int("RandomMutationsMale", 1)
        out += p.float("BabyAge", 1.0)
        out += p.str("TamedOnServerName", "NA-PVE-Official-TheIsland429")
        out += p.str("UploadedFromServerName", "\nEU-PVE-Official-Ragnarok12")
        out += p.double("OriginalCreationTime", 12345.5)
        for i, c in enumerate([12, 0, 44, 3, 7, 55]):
            out += p.byte("ColorSetIndices", c, i)
        anc = ancestor(p, "Dad", 11, 12, "Mom", 21, 22)
        out += p.array("DinoAncestors", "StructProperty", 1, anc)
        anc2 = ancestor(p, "Grandpa", 31, 32, "Grandma", 41, 42) + ancestor(p, "Dad", 11, 12, "Mom2", 51, 52)
        out += p.array("DinoAncestorsMale", "StructProperty", 2, anc2)
        if gestation:
            for i, v in enumerate([10, 0, 5]):
                out += p.byte("GestationEggNumberOfLevelUpPointsApplied", v, i)
            out += p.int("GestationEggRandomMutationsFemale", 2)
            out += p.float("GestationEggTamedIneffectivenessModifier", 0.25)
    out += p.obj("MyCharacterStatusComponent", status_id)
    return out + p.end()


def status_props(p, wild_points, tamed_points, extra):
    out = p.int("BaseCharacterLevel", sum(wild_points) + 1)
    if extra:
        out += p.uint16("ExtraCharacterLevel", extra)
    for i, v in enumerate(wild_points):
        if v:
            out += p.byte("NumberOfLevelUpPointsApplied", v, i)
    for i, v in enumerate(tamed_points):
        if v:
            out += p.byte("NumberOfLevelUpPointsAppliedTamed", v, i)
    out += p.float("TamedIneffectivenessModifier", 0.375)
    out += p.float("DinoImprintingQuality", 0.5)
    return out + p.end()


def pod_blob():
    """Cryopod byte array 0: a mini save with inline names (dino + status component)."""
    p = P(None)
    bodies = [dino_props(p, True, 1, 777, 888, "Podded Rex"),
              status_props(p, [5, 4, 3, 0, 6, 0, 0, 7, 0, 0, 0, 0], [0] * 12, 0)]
    classes = ["Rex_Character_BP_C", "DinoCharacterStatusComponent_BP_Rex_C"]
    hdr_len = 4
    headers = []
    for c in classes:
        h = b"\0" * 16 + fstr(c) + struct.pack("<i", 0) + struct.pack("<i", 1) + fstr(c + "_1")
        h += struct.pack("<iii", 0, 0, 0)
        headers.append(h)
        hdr_len += len(h) + 8
    out, off = struct.pack("<i", len(classes)), hdr_len
    for h, b in zip(headers, bodies):
        out += h + struct.pack("<ii", off, 0)
        off += len(b)
    return out + b"".join(bodies)


def record(name, strings, floats, names, arrays, doubles):
    out = fstr(name)
    out += struct.pack("<i", len(strings)) + b"".join(fstr(s) for s in strings)
    out += struct.pack("<i", len(floats)) + struct.pack(f"<{len(floats)}f", *floats)
    out += struct.pack("<i", len(names)) + b"".join(fstr(s) for s in names)
    out += struct.pack("<i", len(arrays)) + b"".join(struct.pack("<i", len(a)) + a for a in arrays)
    out += struct.pack("<i", len(doubles)) + struct.pack(f"<{len(doubles)}d", *doubles)
    return out


POD_STRINGS = ["Rex_Character_BP_C_1", "Podded Rex - Lvl 26 (Rex)", "1,2,3,", "", "FEMALE"]
POD_FLOATS = [float(i) for i in range(25)]
POD_NAMES = ["Red", "Blue", "None", "None", "Green", "Black"]


def cid_v9(p, blob, saddle):
    ba = (p.array("Bytes", "ByteProperty", len(blob), blob) + p.end()
          + p.array("Bytes", "ByteProperty", len(saddle), saddle) + p.end())
    body = p.namep("CustomDataName", "Dino")
    body += p.array("CustomDataStrings", "StrProperty", len(POD_STRINGS), b"".join(fstr(s) for s in POD_STRINGS))
    body += p.array("CustomDataFloats", "FloatProperty", 25, struct.pack("<25f", *POD_FLOATS))
    body += p.array("CustomDataNames", "NameProperty", 6, b"".join(p.n(s) for s in POD_NAMES))
    body += p.struct("CustomDataDoubles", "CustomItemDoubles",
                     p.array("Doubles", "DoubleProperty", 1, struct.pack("<d", 99.5)) + p.end())
    body += p.array("CustomDataClasses", "ObjectProperty", 1, struct.pack("<i", 1) + p.n(
        "BlueprintGeneratedClass /Game/PrimalEarth/Dinos/Rex/Rex_Character_BP.Rex_Character_BP_C"))
    body += p.struct("CustomDataBytes", "CustomItemByteArrays",
                     p.array("ByteArrays", "StructProperty", 2, ba) + p.end())
    body += p.end()
    return p.array("CustomItemDatas", "StructProperty", 1, body)


def pointer_v11(p, section, offset):
    cls = p.n("BlueprintGeneratedClass /Game/PrimalEarth/Dinos/Rex/Rex_Character_BP.Rex_Character_BP_C")
    entry = bytes([2, section]) + struct.pack("<qii", offset, 0, 1) + struct.pack("<i", 1) + cls
    return p.prop("CustomItemDatas", "ArrayProperty", struct.pack("<i", 1) + entry, extra=p.n("StructProperty"))


def item_id(p, a, b):
    return p.struct("ItemId", "ItemNetID", p.uint32("ItemID1", a) + p.uint32("ItemID2", b) + p.end())


def build(version):
    names = Names()
    p = P(names)
    blob, saddle = pod_blob(), b""
    rec = record("Dino", POD_STRINGS, POD_FLOATS, POD_NAMES, [blob, saddle], [99.5])

    objects = []  # (class, location, props)
    objects.append(("Raptor_Character_BP_C", (100.4, -200.6, 300.0),
                    dino_props(p, True, 1, 1001, 2002, "Speedy", gestation=True)))
    objects.append(("DinoCharacterStatusComponent_BP_Raptor_C", None,
                    status_props(p, [3, 2, 0, 4, 1, 0, 0, 5, 0, 0, 0, 0], [1, 0, 0, 0, 0, 0, 0, 2, 0, 0, 0, 0], 3)))
    objects.append(("Raptor_Character_BP_C", (1.0, 2.0, 3.0), dino_props(p, False, 3, 5, 6)))
    objects.append(("DinoCharacterStatusComponent_BP_Raptor_C", None,
                    status_props(p, [1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0], [0] * 12, 0)))
    sections = []
    for k, (a, b) in enumerate([(70001, 70002), (80001, 80002)]):
        body = item_id(p, a, b)
        if version >= 11:
            body += pointer_v11(p, k, 0)  # each pod's record sits at offset 0 of its own section
            sections.append(rec)
        else:
            body += cid_v9(p, blob, saddle)
        objects.append(("PrimalItem_WeaponEmptyCryopod_C", None, body + p.end()))
    egg = item_id(p, 90001, 90002)
    for i, v in enumerate([4, 0, 6]):
        egg += p.byte("EggNumberOfLevelUpPointsApplied", v, i)
    egg += p.byte("EggColorSetIndices", 9, 0) + p.int("EggRandomMutationsFemale", 1)
    egg += p.array("EggDinoAncestors", "StructProperty", 1, ancestor(p, "A", 1, 2, "B", 3, 4))
    objects.append(("PrimalItemConsumable_Egg_Raptor_Fertilized_C", None, egg + p.end()))
    objects.append(("StorageBox_Small_C", (5.0, 6.0, 7.0), p.str("BoxName", "loot") + p.end()))
    names.ref("BlueprintGeneratedClass /Game/PrimalEarth/Dinos/Raptor/Raptor_Character_BP.Raptor_Character_BP_C")

    # property block
    prop_block, offsets = b"", []
    for _, _, body in objects:
        offsets.append(len(prop_block))
        prop_block += body

    # object table (registers class names, so build before the name table)
    table = struct.pack("<i", len(objects))
    for i, (cls, loc, _) in enumerate(objects):
        table += i.to_bytes(16, "little") + names.ref(cls) + struct.pack("<i", 1 if cls.startswith("PrimalItem") else 0)
        table += struct.pack("<i", 1) + names.ref(f"{cls}_{i}")
        table += struct.pack("<ii", 0, 0)
        if loc:
            table += struct.pack("<i", 1) + struct.pack("<6f", *loc, 0.0, 0.0, 0.0)
        else:
            table += struct.pack("<i", 0)
        table += struct.pack("<ii", offsets[i], 0)

    name_table = struct.pack("<i", len(names.list)) + b"".join(fstr(s) for s in names.list)
    hibernation = b"\0" * 16  # v8+ four unknown ints, no hibernated objects

    header_len = 2 + (64 if version >= 11 else 0) + 4 + 4 + 4 + 4 + 4 + 4
    lists = struct.pack("<iii", 0, 0, 0)  # sublevels, embedded data, data-file map
    hib_off = header_len + len(lists) + len(table)
    name_off = hib_off + len(hibernation)
    prop_off = name_off + len(name_table)
    end = prop_off + len(prop_block)

    head = struct.pack("<h", version)
    if version >= 11:
        secs, pos = [], end
        for s in sections:
            secs.append((pos, len(s)))
            pos += len(s)
        while len(secs) < 4:
            secs.append((pos, 0))
        head += b"".join(struct.pack("<qq", o, n) for o, n in secs)
    head += struct.pack("<iiii", hib_off, 0, name_off, prop_off) + struct.pack("<f", 1000.0) + struct.pack("<i", 42)
    assert len(head) == header_len
    return head + lists + table + hibernation + name_table + prop_block + b"".join(sections)


def main():
    out = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    out.mkdir(parents=True, exist_ok=True)
    for v in (9, 11):
        path = out / f"fixture_v{v}.ark"
        path.write_bytes(build(v))
        print(path)


if __name__ == "__main__":
    main()
