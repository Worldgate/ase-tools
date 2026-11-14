r"""
arkfindme.py - find every save that has a character for a Steam ID (and optionally a name).

Usage:  python arkfindme.py STEAMID64 FOLDER [FOLDER ...] [--name Mavrick --name Theseus] [--jobs N]
        python arkfindme.py 76561198012345678 D:\OfficialSaves
        python arkfindme.py 76561198012345678 D:\OfficialSaves --name Mavrick --name Theseus --jobs 16

Searches .zip saves and loose .ark files. Two kinds of save:
  - older ones keep each character as <SteamID64>.arkprofile -> only the zip's file list is read (instant)
  - the last months keep players INSIDE the .ark -> if a zip has no .arkprofile files at all, the .ark
    is streamed (never unpacked to disk) and searched for the Steam ID as text (how ARK stores it)
With --name it also counts those names (in the profile, or in the .ark). In the .ark a name hit can also
be a dino you tamed/imprinted - still proof you were there.
Writes findme.csv in the current folder. Read-only.
"""

import csv
import multiprocessing as mp
import re
import sys
import zipfile
from pathlib import Path

CHUNK = 64 * 1024 * 1024


def patterns(text):
    return [text.encode("utf-8"), text.encode("utf-16le")]


def stream_count(f, pats):
    """Count each pattern in a file object, reading in chunks with overlap (low RAM)."""
    counts = [0] * len(pats)
    keep = max(len(p) for p in pats) - 1
    tail = b""
    while True:
        data = f.read(CHUNK)
        if not data:
            break
        buf = tail + data
        for i, p in enumerate(pats):
            # only count matches that END inside the new data, so overlap isn't double-counted
            start = 0
            while True:
                j = buf.find(p, start)
                if j < 0:
                    break
                if j + len(p) > len(tail):
                    counts[i] += 1
                start = j + 1
        tail = buf[-keep:] if keep else b""
    return counts


def hits(z, c, names, tribes):
    sid = c[0] + c[1]
    name_hits = {nm: c[2 + 2 * k] + c[3 + 2 * k] for k, nm in enumerate(names)}
    if not sid and not any(name_hits.values()):
        return None
    # a loose .ark is named after the map (TheIsland.ark), so show its folder as the save name
    save = z.stem if z.suffix.lower() == ".zip" else f"{z.parent.name}/{z.name}"
    return {"save": save, "folder": str(z.parent),
            "found_in": "inside .ark" if sid else "inside .ark (name only)",
            "steam_id_hits": sid,
            "names_found": " ".join(f"{nm}x{n}" for nm, n in name_hits.items() if n),
            "tribe_files_in_save": tribes}


def check(job):
    z, steam, names = job
    if z.suffix.lower() == ".ark":          # loose .ark file
        pats = patterns(steam) + [q for nm in names for q in patterns(nm)]
        try:
            with open(z, "rb") as f:
                c = stream_count(f, pats)
        except OSError as e:
            return {"save": z.stem, "folder": str(z.parent), "found_in": f"ERROR {type(e).__name__}",
                    "steam_id_hits": 0, "names_found": "", "tribe_files_in_save": 0}
        return hits(z, c, names, 0)
    try:
        with zipfile.ZipFile(z) as zf:
            members = zf.namelist()
            profiles = [m for m in members if m.lower().endswith(".arkprofile")]
            tribes = sum(m.lower().endswith(".arktribe") for m in members)
            mine = [m for m in profiles if Path(m).name == f"{steam}.arkprofile"]
            if profiles:
                if not mine:
                    return None
                data = zf.read(mine[0])
                found = [nm for nm in names if any(p in data for p in patterns(nm))]
                return {"save": z.stem, "folder": str(z.parent), "found_in": "profile file",
                        "steam_id_hits": 1, "names_found": " ".join(found), "tribe_files_in_save": tribes}
            arks = [m for m in members if m.lower().endswith(".ark")]
            if not arks:
                return None
            pats = patterns(steam)
            for nm in names:
                pats += patterns(nm)
            with zf.open(max(arks, key=lambda m: zf.getinfo(m).file_size)) as f:
                c = stream_count(f, pats)
            return hits(z, c, names, tribes)
    except (zipfile.BadZipFile, OSError, EOFError) as e:
        return {"save": z.stem, "folder": str(z.parent), "found_in": f"ERROR {type(e).__name__}",
                "steam_id_hits": 0, "names_found": "", "tribe_files_in_save": 0}


def main():
    args = sys.argv[1:]
    names, jobs = [], 8
    while "--name" in args:
        i = args.index("--name"); names.append(args[i + 1]); del args[i:i + 2]
    if "--jobs" in args:
        i = args.index("--jobs"); jobs = int(args[i + 1]); del args[i:i + 2]
    if len(args) < 2 or not re.fullmatch(r"\d{17}", args[0]):
        print(__doc__)
        return
    steam, folders = args[0], args[1:]
    zips = sorted(f for d in folders for f in Path(d).rglob("*")
                  if f.is_file() and (f.suffix.lower() == ".ark" or
                                      (f.suffix.lower() == ".zip" and not f.name.endswith(".extract.zip"))))
    print(f"checking {len(zips):,} saves (.zip and .ark) for {steam} with {jobs} jobs "
          f"(zips without .arkprofile files get their .ark searched - slower) ...", flush=True)
    rows = []
    with mp.Pool(max(1, min(jobs, len(zips)))) as pool:
        for n, r in enumerate(pool.imap_unordered(check, [(z, steam, names) for z in zips]), 1):
            if r:
                rows.append(r)
                print(f"  {r['found_in']:<24} {r['save']}"
                      + (f"   names: {r['names_found']}" if r["names_found"] else ""), flush=True)
            if n % 100 == 0:
                print(f"  ... {n:,}/{len(zips):,}", flush=True)
    rows.sort(key=lambda r: r["save"])
    out = Path("findme.csv")
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["save", "folder", "found_in", "steam_id_hits",
                                           "names_found", "tribe_files_in_save"])
        w.writeheader()
        w.writerows(rows)
    sid = sum(1 for r in rows if r["steam_id_hits"])
    print(f"\n{sid} saves have your Steam ID, {len(rows) - sid} more mention only your names. List: {out.resolve()}")


if __name__ == "__main__":
    mp.freeze_support()
    main()
