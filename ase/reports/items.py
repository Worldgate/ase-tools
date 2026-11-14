r"""
arkitems.py - count plain item stacks and placed structures in an ASE save, optionally for one tribe.

Usage:  python arkitems.py SAVE [--tribe ID_OR_NAME] [--top N]
        python arkitems.py "EU-PVE-Official-TheIsland347 (2023-09-30).zip"
        python arkitems.py "EU-PVE-Official-TheIsland347 (2023-09-30).zip" --tribe 1621542646
        python arkitems.py "...zip" --tribe "you are my sunshine"

SAVE is a .ark or an official save .zip. Needs arkextract.py in the same folder. Read-only.

"Plain" items = no custom data (not pods/eggs/notes), not blueprints or engrams, and no quality stats
(not armor/weapons/saddles with ItemStatValues). These are the things that just stack:
resources, consumables, structure items (walls, foundations as items), ammo, etc.
Writes <save>_items.csv and <save>_structures.csv next to the save.
"""

import collections
import csv
import struct
import sys
import time
import zipfile
from pathlib import Path

from .. import compat as X


def light_props(save, idx):
    """Size-skipping pass returning simple values: ints, bools, object ids, strings we care about."""
    d = save.data
    r = X.Buf(d, save.prop_off + save.objects[idx][2])
    out = {}
    while True:
        pname = save.name(r)
        if pname == "None":
            return out
        ptype = save.name(r)
        size = r.i32(); r.i32()
        if size < 0 or size > X.MAX_PROPERTY or r.o + size > len(d):
            raise ValueError("bad property size")
        if ptype == "BoolProperty":
            out[pname] = d[r.o] != 0
            r.o += 1
            continue
        if ptype in ("ByteProperty", "StructProperty", "ArrayProperty"):
            save.name(r)
        elif ptype == "MapProperty":
            save.name(r); save.name(r)
        if size == 4 and ptype in ("IntProperty", "UInt32Property"):
            out.setdefault(pname, struct.unpack_from("<i", d, r.o)[0])
        elif ptype == "ObjectProperty" and size >= 8:
            kind = struct.unpack_from("<i", d, r.o)[0]
            if kind == 0:
                out.setdefault(pname, ("obj", struct.unpack_from("<i", d, r.o + 4)[0]))
        elif ptype == "StrProperty" and pname in ("TribeName", "OwnerName"):
            rr = X.Buf(d, r.o)
            out[pname] = rr.s()
        else:
            out.setdefault(pname, True)   # presence only
        r.o += size


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return
    tribe_arg, top = None, 60
    if "--tribe" in args:
        i = args.index("--tribe"); tribe_arg = args[i + 1]; del args[i:i + 2]
    if "--top" in args:
        i = args.index("--top"); top = int(args[i + 1]); del args[i:i + 2]
    src = Path(args[0])
    t0 = time.time()
    if src.suffix.lower() == ".zip":
        with zipfile.ZipFile(src) as z:
            data = z.read(next(n for n in z.namelist() if n.lower().endswith(".ark")))
    else:
        data = src.read_bytes()
    save = X.Save(data)
    print(f"{src.name}: v{save.version}, {len(save.objects):,} objects")

    # pass 1: anything with a team (structures, dinos, players) -> its inventory component -> team
    inv_team, team_name = {}, {}
    structures = collections.defaultdict(collections.Counter)   # team -> class -> count
    items = []
    errors = 0
    for idx, (cls, loc, poff) in enumerate(save.objects):
        try:
            p = light_props(save, idx)
        except Exception:
            errors += 1
            continue
        if cls.startswith("PrimalItem"):
            items.append((cls, p))
            continue
        team = p.get("TargetingTeam")
        if team is None:
            continue
        if p.get("TribeName"):
            team_name.setdefault(team, p["TribeName"])
        inv = p.get("MyInventoryComponent")
        if isinstance(inv, tuple):
            inv_team[inv[1]] = team
        # placed structures: have a team, not creatures/players/components
        if not ("_Character_BP" in cls or cls.startswith("PlayerPawn") or "Component" in cls
                or cls.startswith("PrimalInventory") or "Buff" in cls):
            structures[team][cls] += 1

    # which teams count?
    want = None
    if tribe_arg:
        if tribe_arg.lstrip("-").isdigit():
            want = {int(tribe_arg)}
        else:
            want = {t for t, n in team_name.items() if n.lower() == tribe_arg.lower()}
        if not want:
            print(f"no tribe matching {tribe_arg!r}. Some tribes on this map:")
            for t, n in list(team_name.items())[:20]:
                print(f"  {t}  {n}")
            return
        print("tribe: " + ", ".join(f"{t} ({team_name.get(t, '?')})" for t in want))

    # pass 2: items -> inventory -> team
    plain = collections.Counter()
    plain_stacks = collections.Counter()
    other = collections.Counter()
    unowned = 0
    for cls, p in items:
        inv = p.get("OwnerInventory")
        team = inv_team.get(inv[1]) if isinstance(inv, tuple) else None
        if want is not None and team not in want:
            continue
        if team is None:
            unowned += 1
        if p.get("bIsEngram") or p.get("bIsBlueprint") or p.get("bIsInitialItem"):
            other["blueprints/engrams/initial"] += 1
            continue
        if "CustomItemDatas" in p:
            other["custom data (pods, eggs, notes)"] += 1
            continue
        if "ItemStatValues" in p or "ItemQualityIndex" in p or \
                cls.startswith(("PrimalItemArmor_", "PrimalItem_Weapon", "PrimalItemCostume_", "PrimalItemSkin_")):
            other["gear with stats (armor, weapons, saddles)"] += 1
            continue
        qty = p.get("ItemQuantity", 1) or 1
        plain[cls] += qty
        plain_stacks[cls] += 1

    struct_total = collections.Counter()
    for team, c in structures.items():
        if want is None or team in want:
            struct_total.update(c)

    def short(c):
        return c.replace("PrimalItemResource_", "").replace("PrimalItemStructure_", "[item] ") \
                .replace("PrimalItemConsumable_", "").replace("PrimalItemAmmo_", "[ammo] ") \
                .replace("PrimalItem_", "").removesuffix("_C")

    print(f"\nPLAIN ITEMS (stackable, no custom data / stats): {sum(plain.values()):,} total in "
          f"{sum(plain_stacks.values()):,} stacks, {len(plain)} kinds")
    for c, n in plain.most_common(top):
        print(f"  {n:>14,}  {short(c):<45} ({plain_stacks[c]:,} stacks)")
    print("\nNot counted above:")
    for k, n in other.most_common():
        print(f"  {n:>14,}  {k}")
    if want is None and unowned:
        print(f"  ({unowned:,} items whose owner couldn't be matched to a team: dropped items, bags, etc.)")

    print(f"\nPLACED STRUCTURES: {sum(struct_total.values()):,} total, {len(struct_total)} kinds")
    for c, n in struct_total.most_common(min(top, 40)):
        print(f"  {n:>14,}  {short(c)}")

    stem = src.stem + (f"_tribe{'-'.join(map(str, sorted(want)))}" if want else "")
    with open(src.with_name(stem + "_items.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh); w.writerow(["item_class", "total_quantity", "stacks"])
        for c, n in plain.most_common():
            w.writerow([c, n, plain_stacks[c]])
    with open(src.with_name(stem + "_structures.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh); w.writerow(["structure_class", "count"])
        for c, n in struct_total.most_common():
            w.writerow([c, n])
    print(f"\nwrote {stem}_items.csv and {stem}_structures.csv  ({time.time() - t0:.0f}s, {errors} unreadable objects)")


if __name__ == "__main__":
    main()
