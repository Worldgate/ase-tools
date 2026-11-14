r"""
arkrank.py - rank extracted maps by cryopods (or another count) using each extract's meta.json.

Usage:  python arkrank.py [extracts folder] [--by cryopods|tamed_world_dinos|fertilized_eggs|pregnant|pod_bytes] [--top N]
        python arkrank.py extracts
        python arkrank.py extracts --by tamed_world_dinos --top 30
Read-only and fast (only meta.json is read from each zip).
"""

import json
import sys
import zipfile
from pathlib import Path


def mode(name):
    n = name.upper()
    if "PVP" in n:
        return "PvP"
    if "PVE" in n:
        return "PvE"
    return "?"


def main():
    args = sys.argv[1:]
    by, top = "cryopods", 25
    if "--by" in args:
        i = args.index("--by"); by = args[i + 1]; del args[i:i + 2]
    if "--top" in args:
        i = args.index("--top"); top = int(args[i + 1]); del args[i:i + 2]
    folder = Path(args[0]) if args else Path(__file__).resolve().parent / "extracts"
    rows = []
    for f in sorted(folder.rglob("*.extract.zip")):
        try:
            with zipfile.ZipFile(f) as z:
                m = json.loads(z.read("meta.json"))
        except Exception:
            continue
        rows.append(m)
    if not rows:
        print(f"no extracts found in {folder}")
        return
    rows.sort(key=lambda m: m.get(by, 0), reverse=True)
    print(f"{len(rows)} extracts in {folder}, ranked by {by}\n")
    print(f"{'#':>3}  {'mode':<4} {'pods':>9} {'tamed':>7} {'eggs':>7} {'preg':>5} {'pod GB':>7}  save")
    for i, m in enumerate(rows[:top], 1):
        print(f"{i:>3}  {mode(m['save']):<4} {m.get('cryopods', 0):>9,} {m.get('tamed_world_dinos', 0):>7,} "
              f"{m.get('fertilized_eggs', 0):>7,} {m.get('pregnant', 0):>5,} "
              f"{m.get('pod_bytes', 0) / 1_073_741_824:>7.2f}  {m['save']}")
    for label in ("PvP", "PvE"):
        sub = [m for m in rows if mode(m["save"]) == label]
        if sub:
            pods = sum(m.get("cryopods", 0) for m in sub)
            print(f"\n{label}: {len(sub)} maps, {pods:,} pods total, {pods // len(sub):,} average per map")
    total = sum(m.get("cryopods", 0) for m in rows) + sum(m.get("tamed_world_dinos", 0) for m in rows)
    print(f"\nall maps: {total:,} dinos (pods + tamed in the world)")


if __name__ == "__main__":
    main()
