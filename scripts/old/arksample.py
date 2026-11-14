r"""
arksample.py - cut a small sample out of a big ASE .ark (v9/v11) to send for decoding.

Usage:  python arksample.py "C:\path\Gen2.ark"            (300 pods, 50 tames)
        python arksample.py "C:\path\Gen2.ark" 500 100    (500 pods, 100 tames)

Writes  <map>_sample.zip  next to the .ark containing sample.json with:
  - the save's name table (needed to read everything else)
  - raw property bytes of N filled cryopods
  - raw property bytes of N tamed world dinos + their status component objects
Read-only: the .ark is never modified. Standard library only.
"""

import base64
import json
import struct
import sys
import zipfile
from pathlib import Path


def main(path, max_pods=300, max_tames=50):
    path = Path(path)
    print(f"Reading {path.name} ...")
    data = path.read_bytes()
    o = 0

    def i32():
        nonlocal o
        v = struct.unpack_from("<i", data, o)[0]; o += 4; return v

    def s():
        nonlocal o
        n = i32()
        if n == 0:
            return ""
        if n < 0:
            b = data[o:o - n * 2]; o += -n * 2
            return b.decode("utf-16le", "replace").rstrip("\0")
        b = data[o:o + n]; o += n
        return b.decode("latin1", "replace").rstrip("\0")

    ver = struct.unpack_from("<h", data, 0)[0]; o = 2
    sections = []
    if ver >= 11:
        sections = [struct.unpack_from("<qq", data, 2 + 16 * i) for i in range(4)]
        o += 64
    i32(); i32(); name_off = i32(); prop_off = i32(); o += 8
    for _ in range(i32()):
        s()
    i32(); i32()
    save = o
    o = name_off
    names = [s() for _ in range(i32())]
    o = save

    def name():
        idx = i32(); inst = i32()
        base = names[idx - 1]
        return base if inst == 0 else f"{base}_{inst - 1}"

    print("Scanning object table ...")
    objs = []  # (index, class, propoffset)
    count = i32()
    for idx in range(count):
        o += 16
        cls = name(); i32()
        for _ in range(i32()):
            name()
        i32(); i32()
        if i32():
            o += 24
        poff = i32(); i32()
        objs.append((cls, poff))

    def prop_block(poff):
        """Return (raw bytes, dict of simple values) for one object's property block."""
        nonlocal o
        start = o = prop_off + poff
        vals = {}
        while True:
            pname = name()
            if pname == "None":
                break
            ptype = name()
            size = i32(); i32()
            if ptype == "BoolProperty":
                vals[pname] = data[o] != 0
                o += 1
                continue
            if ptype in ("ByteProperty", "StructProperty", "ArrayProperty"):
                name()
            elif ptype == "MapProperty":
                name(); name()
            if size == 4 and ptype == "IntProperty":
                vals[pname] = struct.unpack_from("<i", data, o)[0]
            if ptype == "ObjectProperty" and size == 8:
                kind, ref = struct.unpack_from("<ii", data, o)
                if kind == 0:
                    vals[pname] = ("obj", ref)
            if pname == "CustomItemDatas":
                vals["_pod_size"] = size
            o += size
        return data[start:o], vals

    print("Collecting pods and tames ...")
    pods, tames = [], []
    for idx, (cls, poff) in enumerate(objs):
        is_pod = "Cryopod" in cls and cls.startswith("PrimalItem")
        is_dino = cls.endswith("_Character_BP_C")
        if not (is_pod and len(pods) < max_pods) and not (is_dino and len(tames) < max_tames):
            continue
        raw, vals = prop_block(poff)
        if is_pod:
            # v11 pods may hold no dino bytes themselves, so sample them regardless
            pods.append({"index": idx, "class": cls,
                         "pod_data_size": vals.get("_pod_size", 0),
                         "props_b64": base64.b64encode(raw).decode()})
        elif is_dino and vals.get("TargetingTeam", 0) >= 50000:
            entry = {"index": idx, "class": cls,
                     "props_b64": base64.b64encode(raw).decode()}
            ref = vals.get("MyCharacterStatusComponent")
            if ref and 0 <= ref[1] < len(objs):
                scls, spoff = objs[ref[1]]
                sraw, _ = prop_block(spoff)
                entry["status"] = {"index": ref[1], "class": scls,
                                   "props_b64": base64.b64encode(sraw).decode()}
            tames.append(entry)
        if len(pods) >= max_pods and len(tames) >= max_tames:
            break

    # v11 extra sections: keep the first few MB of each so their format can be decoded
    sect_out = []
    for off, sz in sections:
        take = min(sz, 4 * 1_048_576)
        sect_out.append({"offset": off, "size": sz,
                         "head_b64": base64.b64encode(data[off:off + take]).decode() if take > 0 else ""})
        if sz:
            print(f"  section at {off:,}: {sz:,} bytes (sampling {take:,})")

    out = {
        "source": path.name, "version": ver, "objects": count,
        "names": names, "pods": pods, "tames": tames, "sections": sect_out,
    }
    zpath = path.with_name(path.stem + "_sample.zip")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("sample.json", json.dumps(out))
    linked = sum(1 for t in tames if "status" in t)
    with_data = sum(1 for p in pods if p["pod_data_size"] > 1000)
    print(f"\n{len(pods)} pods sampled ({with_data} carry dino bytes in the item itself), "
          f"{len(tames)} tames ({linked} with status component)")
    print(f"Wrote {zpath}  ({zpath.stat().st_size / 1_048_576:.1f} MB)")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Usage: python arksample.py "path\\to\\Map.ark" [pods] [tames]')
        sys.exit(1)
    args = [int(a) for a in sys.argv[2:4]]
    main(sys.argv[1], *args)
