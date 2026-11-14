#!/usr/bin/env python3
"""
sort_saves.py — sort ARK save zips into folders by map name.

Looks inside each .zip (without unpacking), finds the map save (.ark),
and moves the zip into a folder named after the map:

    NA-PVE-Official-TheIsland429.zip   (contains TheIsland.ark)
      ->  sorted/TheIsland/NA-PVE-Official-TheIsland429.zip

Usage:
    python3 sort_saves.py SOURCE_FOLDER [DEST_FOLDER]           # dry run: shows what it would do
    python3 sort_saves.py SOURCE_FOLDER [DEST_FOLDER] --go      # actually move the files

DEST_FOLDER defaults to SOURCE_FOLDER/sorted. Subfolders of SOURCE are
searched too. Nothing is ever overwritten; clashes are reported and skipped.
A log of every decision is written to DEST_FOLDER/sort_log.csv.

Rules for picking the map name when a zip holds several .ark files:
  - auto-backups (TheIsland_12.06.2023_04.15.33.ark) are ignored
  - of what's left, the biggest .ark wins
Zips with no .ark, or that can't be read, go to DEST/_unsorted/ (with --go).

Standard library only.
"""
from __future__ import annotations

import csv
import re
import shutil
import sys
import zipfile
from pathlib import Path

BACKUP_RE = re.compile(r"_\d{2}\.\d{2}\.\d{4}_\d{2}\.\d{2}\.\d{2}$")


def map_name_in(zpath: Path):
    """Return (map_name, ark_entry_name, ark_size, note) for a zip."""
    try:
        with zipfile.ZipFile(zpath) as z:
            arks = [i for i in z.infolist() if i.filename.lower().endswith(".ark") and not i.is_dir()]
    except (zipfile.BadZipFile, OSError) as e:
        return None, None, None, f"unreadable: {e}"
    if not arks:
        return None, None, None, "no .ark inside"
    main = [i for i in arks if not BACKUP_RE.search(Path(i.filename).stem)]
    pool = main or arks
    best = max(pool, key=lambda i: i.file_size)
    stem = Path(best.filename).stem
    if not main:
        stem = BACKUP_RE.sub("", stem)  # only backups inside: use the map part of the name
    note = "" if len(pool) == 1 else f"{len(pool)} map saves inside, picked the biggest"
    return stem, best.filename, best.file_size, note


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    go = "--go" in sys.argv
    if not args:
        sys.exit(__doc__)
    src = Path(args[0]).expanduser()
    dest = Path(args[1]).expanduser() if len(args) > 1 else src / "sorted"
    if not src.is_dir():
        sys.exit(f"not a folder: {src}")

    zips = sorted(p for p in src.rglob("*.zip") if dest not in p.parents)
    if not zips:
        sys.exit("no .zip files found")

    rows, counts = [], {}
    for z in zips:
        name, entry, size, note = map_name_in(z)
        folder = dest / (name if name else "_unsorted")
        target = folder / z.name
        if target.exists():
            action = "skipped: already exists at destination"
        elif go:
            folder.mkdir(parents=True, exist_ok=True)
            shutil.move(str(z), str(target))
            action = "moved"
        else:
            action = "would move"
        counts[name or "_unsorted"] = counts.get(name or "_unsorted", 0) + 1
        rows.append([z.name, name or "", entry or "", size or "", action, note, str(z)])
        print(f"{action:<12} {z.name}  ->  {folder.name}/" + (f"   ({note})" if note else ""))

    print("\nPer map:")
    for k, v in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {v:>5}  {k}")
    if go:
        dest.mkdir(parents=True, exist_ok=True)
        with open(dest / "sort_log.csv", "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if f.tell() == 0:
                w.writerow(["zip", "map", "ark_inside", "ark_size_bytes", "action", "note", "original_path"])
            w.writerows(rows)
        print(f"\nLog: {dest / 'sort_log.csv'}")
    else:
        print("\nDry run only. Add --go to actually move the files.")


if __name__ == "__main__":
    main()
