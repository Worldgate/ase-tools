"""ase versions: scan a collection and pick small sample saves from every format era.

Reads only the first few bytes of each save (inside zips too), so it runs over
the whole collection in seconds. Use it to find test saves for decoding work.
"""
import collections
import csv
import re
import struct
import zipfile
from pathlib import Path

from ..saves import find_saves

GROUP = "Tools"
HELP = "Save format version of every save; smallest samples per version (finds test saves)"

DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def add_arguments(ap):
    ap.add_argument("folders", nargs="+", help="folders (or files) to scan")
    ap.add_argument("--pick", type=int, default=3, help="smallest saves to suggest per version (default 3)")
    ap.add_argument("--csv", help="also write every save's version to this CSV")


def peek(src):
    """(version, .ark size, has .arkprofile files, has .arktribe files, map) without reading the whole save."""
    src = Path(src)
    if src.suffix.lower() == ".zip":
        with zipfile.ZipFile(src) as z:
            infos = z.infolist()
            ark = next((i for i in infos if i.filename.lower().endswith(".ark")), None)
            if ark is None:
                return None
            with z.open(ark) as f:
                head = f.read(2)
            profiles = any(i.filename.lower().endswith(".arkprofile") for i in infos)
            tribes = any(i.filename.lower().endswith(".arktribe") for i in infos)
            return struct.unpack("<h", head)[0], ark.file_size, profiles, tribes, Path(ark.filename).stem
    with open(src, "rb") as f:
        head = f.read(2)
    folder = src.parent
    profiles = any(folder.glob("*.arkprofile"))
    tribes = any(folder.glob("*.arktribe"))
    return struct.unpack("<h", head)[0], src.stat().st_size, profiles, tribes, src.stem


def run(args):
    rows, bad = [], 0
    for s in find_saves(args.folders):
        try:
            info = peek(s)
        except Exception:
            info = None
        if info is None:
            bad += 1
            continue
        v, size, prof, trib, map_name = info
        m = DATE_RE.search(s.name)
        rows.append({"version": v, "size": size, "date": m.group(1) if m else "",
                     "map": map_name, "profiles": prof, "tribes": trib, "path": str(s)})
    by_v = collections.defaultdict(list)
    for r in rows:
        by_v[r["version"]].append(r)
    print(f"{len(rows):,} saves scanned{f', {bad} unreadable' if bad else ''}\n")
    print(f"{'ver':>3}  {'saves':>6}  {'dates':<23}  {'separate profiles/tribes'}")
    for v in sorted(by_v):
        rs = by_v[v]
        dates = sorted(r["date"] for r in rs if r["date"])
        span = f"{dates[0]} .. {dates[-1]}" if dates else "?"
        sep = sum(r["profiles"] or r["tribes"] for r in rs)
        print(f"{v:>3}  {len(rs):>6,}  {span:<23}  {sep:,} of {len(rs):,}")
    print(f"\nSmallest {args.pick} per version (good test samples):")
    for v in sorted(by_v):
        print(f"  v{v}:")
        for r in sorted(by_v[v], key=lambda r: r["size"])[:args.pick]:
            extra = " +profiles" if r["profiles"] else ""
            print(f"    {r['size'] / 1_048_576:8.1f} MB  {r['map']:<16} {r['date'] or '':<10}{extra}  {r['path']}")
    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["version"])
            w.writeheader()
            w.writerows(sorted(rows, key=lambda r: (r["version"], r["size"])))
        print(f"\nevery save -> {args.csv}")
