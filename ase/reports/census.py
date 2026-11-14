r"""
arkcensus.py - population census of every tamed dino across all extracts.

Usage:  python arkcensus.py [extracts folder] [--jobs N] [--top N]
        python arkcensus.py extracts --jobs 24

Counts per species: out in the world, in cryopods, total, female/male, how many
servers had at least one, PvP vs PvE, the highest level seen (and its name/server),
plus fertilized eggs by species. Reads dinos.jsonl, pods.jsonl and eggs.jsonl from
each extract (never the big pods.bin). Writes dino_census.csv next to the extracts folder.

Species come from the blueprint class (e.g. Rex_Character_BP -> Rex). Pods whose class
is missing (Zomdodos, event dinos) fall back to the "(Species)" part of the pod's name line.
Counts are per save file: a dino uploaded and seen in two saves counts twice.
"""

import collections
import csv
import json
import multiprocessing as mp
import re
import sys
import zipfile
from pathlib import Path

# the real level is the one the game appends: "<custom name> - Lvl 450 (Species)".
# Players put "Lvl" in names too ("Giga 421Lvl 1285 - Lvl 450 ..."), so use the LAST match.
LVL = re.compile(r"Lvl\s+(\d+)")
PAREN = re.compile(r"\(([^()]*)\)\s*$")


def species_from_class(path):
    """'/Game/.../Rex_Character_BP.Rex_Character_BP_C' or "Blueprint'/Game/...Rex_Character_BP'" -> 'Rex'."""
    if not path:
        return ""
    s = path.rstrip("'").rsplit(".", 1)[-1]
    s = s.rsplit("/", 1)[-1]
    if s.endswith("_C"):
        s = s[:-2]
    # keep variants apart: Ankylo_Character_BP_Aberrant -> "Ankylo (Aberrant)"
    m = re.match(r"(.+?)_Character_BP_?(.*)$", s)
    if m:
        base, variant = m.group(1), m.group(2).strip("_")
        return f"{base} ({variant})" if variant else base
    return s


def egg_species(cls):
    m = re.search(r"Egg_(.+?)_Fertilized", cls)
    return m.group(1) if m else cls


def mode_of(save):
    s = save.upper()
    return "PvP" if "PVP" in s else "PvE" if "PVE" in s else "?"


def new_bucket():
    return {"world": 0, "pods": 0, "female": 0, "male": 0, "servers": set(),
            "pvp": 0, "pve": 0, "best": (0, "", "")}


def tally(path):
    """Count one extract. Returns (save, {species: counts}, {egg species: n})."""
    sp = collections.defaultdict(new_bucket)
    eggs = collections.Counter()
    try:
        z = zipfile.ZipFile(path)
        meta = json.loads(z.read("meta.json"))
    except Exception as e:
        return str(path), None, None, f"{type(e).__name__}: {e}"
    save = meta.get("save", Path(path).stem)
    mode = mode_of(save)

    def add(name, where, female, level, label):
        b = sp[name]
        b[where] += 1
        if female is True:
            b["female"] += 1
        elif female is False:
            b["male"] += 1
        b["servers"].add(save)
        if mode == "PvP":
            b["pvp"] += 1
        elif mode == "PvE":
            b["pve"] += 1
        if level and level > b["best"][0]:
            b["best"] = (level, label, save)

    with z:
        if "dinos.jsonl" in z.namelist():
            with z.open("dinos.jsonl") as f:
                for line in f:
                    try:
                        d = json.loads(line)
                    except ValueError:
                        continue
                    name = species_from_class(d.get("class", "")) or "?"
                    add(name, "world", d.get("female"), d.get("level") or 0, d.get("name") or "")
        if "pods.jsonl" in z.namelist():
            with z.open("pods.jsonl") as f:
                for line in f:
                    try:
                        p = json.loads(line)
                    except ValueError:
                        continue
                    for cd in p.get("custom_data") or []:
                        if cd.get("name") != "Dino":
                            continue
                        strings = cd.get("strings") or []
                        title = strings[1] if len(strings) > 1 else ""
                        name = ""
                        for c in cd.get("classes") or []:
                            name = species_from_class(c)
                            if name:
                                break
                        if not name:
                            m = PAREN.search(title)
                            name = (m.group(1).strip() if m else "") or "?"
                        g = strings[4].upper() if len(strings) > 4 else ""
                        female = True if g == "FEMALE" else False if g == "MALE" else None
                        lv = LVL.findall(title)
                        add(name, "pods", female, int(lv[-1]) if lv else 0, title)
        if "eggs.jsonl" in z.namelist():
            with z.open("eggs.jsonl") as f:
                for line in f:
                    try:
                        eggs[egg_species(json.loads(line).get("class", ""))] += 1
                    except ValueError:
                        continue
    return save, dict(sp), eggs, None


def main():
    args = sys.argv[1:]
    jobs, top = 8, 40
    if "--jobs" in args:
        i = args.index("--jobs"); jobs = int(args[i + 1]); del args[i:i + 2]
    if "--top" in args:
        i = args.index("--top"); top = int(args[i + 1]); del args[i:i + 2]
    folder = Path(args[0]) if args else Path.cwd() / "extracts"
    files = sorted(folder.rglob("*.extract.zip"))
    if not files:
        print(f"no extracts in {folder}")
        return
    print(f"counting {len(files)} extracts with {jobs} jobs ...", flush=True)

    total = collections.defaultdict(new_bucket)
    eggs = collections.Counter()
    done = 0
    with mp.Pool(min(jobs, len(files))) as pool:
        for save, sp, eg, err in pool.imap_unordered(tally, files):
            done += 1
            if err:
                print(f"  skipped {save}: {err}")
                continue
            for name, b in sp.items():
                t = total[name]
                for k in ("world", "pods", "female", "male", "pvp", "pve"):
                    t[k] += b[k]
                t["servers"] |= b["servers"]
                if b["best"][0] > t["best"][0]:
                    t["best"] = b["best"]
            eggs.update(eg)
            if done % 100 == 0:
                print(f"  {done}/{len(files)}", flush=True)

    eggs_ci = collections.Counter()  # egg items spell some species differently (Milkglider vs MilkGlider)
    for k, v in eggs.items():
        eggs_ci[k.lower()] += v
    rows = []
    for name, t in total.items():
        rows.append({"species": name, "total": t["world"] + t["pods"], "in_pods": t["pods"],
                     "in_world": t["world"], "female": t["female"], "male": t["male"],
                     "servers": len(t["servers"]), "pvp": t["pvp"], "pve": t["pve"],
                     "eggs": eggs_ci.get(name.lower(), 0), "max_level": t["best"][0],
                     "max_level_name": t["best"][1], "max_level_server": t["best"][2]})
    rows.sort(key=lambda r: r["total"], reverse=True)

    out = folder.parent / "dino_census.csv"
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    grand = sum(r["total"] for r in rows)
    pods = sum(r["in_pods"] for r in rows)
    print(f"\n{grand:,} tamed dinos across {len(files)} saves, {len(rows)} species "
          f"({pods:,} in pods, {grand - pods:,} in the world), {sum(eggs.values()):,} fertilized eggs")
    print(f"\n{'#':>3}  {'species':<28}{'total':>11}{'share':>7}{'pods':>11}{'world':>9}"
          f"{'F%':>5}{'servers':>8}{'max lvl':>8}")
    for i, r in enumerate(rows[:top], 1):
        fm = r["female"] + r["male"]
        fpct = f"{100 * r['female'] / fm:.0f}" if fm else "-"
        print(f"{i:>3}  {r['species'][:27]:<28}{r['total']:>11,}{100 * r['total'] / grand:>6.1f}%"
              f"{r['in_pods']:>11,}{r['in_world']:>9,}{fpct:>5}{r['servers']:>8}{r['max_level']:>8}")
    print("\nTop fertilized eggs by species:")
    for name, n in eggs.most_common(10):
        print(f"  {n:>9,}  {name}")
    rare = [r for r in rows if r["total"] <= 5]
    if rare:
        print(f"\nRarest ({len(rare)} species with 5 or fewer): " +
              ", ".join(f"{r['species']} {r['total']}" for r in sorted(rare, key=lambda r: r['total'])[:20]))
    print(f"\nFull table: {out}")


if __name__ == "__main__":
    mp.freeze_support()
    main()
