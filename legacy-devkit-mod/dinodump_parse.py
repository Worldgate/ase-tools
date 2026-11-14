#!/usr/bin/env python3
"""
dinodump_parse.py
-----------------
Reads the DinoDump mod's output (server logs, or any file containing
DINODUMP| lines) and builds:

  out/dinos/<Species>/<id64>.json   one file per dino (the master dump)
  out/master.json                   every dino in one file
  out/master.jsonl                  same, one dino per line
  out/ghosts.json                   ancestors that never showed up as a dumped dino
  out/cryopods_raw.jsonl            raw cryopod data, if the mod sent C lines
  out/dinos.sqlite                  database for the website
  out/report.txt                    what happened and what looked wrong

Usage:
  python dinodump_parse.py <logs folder or single log> [-o out] [--manifest manifest.json]

If the logs came from dinodump_batch.py, its manifest.json sits in the logs
folder and is picked up automatically, so every dino is tagged with the
save file it came from.

Python 3.8+, standard library only.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

# Which ancestry entry holds the dino's own parents.
#   "last"  = the final entry in the maternal list (most likely; verify on the test map)
#   "first" = the first entry
#   "none"  = don't work out parents at all
PARENT_ENTRY = "last"

STAT_NAMES = [
    "health", "stamina", "torpidity", "oxygen", "food", "water",
    "temperature", "weight", "melee", "speed", "fortitude", "crafting",
]

SKIP_FILES = {"manifest.json"}

# DINODUMP|<KIND>|{json}  — json runs to the end of the line
LINE_RE = re.compile(rb"DINODUMP\|([A-Z]+)\|(\{.*?\})(?=[ \t]*(?:\r|\n|\x00|$))")


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def u32(v) -> int:
    try:
        return int(float(v)) & 0xFFFFFFFF
    except (TypeError, ValueError):
        return 0


def make_id(a, b):
    """Combine the two hidden ID halves into one 64-bit ID string."""
    a, b = u32(a), u32(b)
    if a == 0 and b == 0:
        return None
    return str((a << 32) | b)


def num(v, default=None):
    if v is None or v == "":
        return default
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    return int(f) if f.is_integer() else f


def flag(v):
    if v is None or v == "":
        return None
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes")
    return bool(v)


def text(v):
    return "" if v is None else str(v)


def species_of(core: dict) -> str:
    s = text(core.get("species")).strip()
    if s:
        return s
    cls = text(core.get("cls")) or "Unknown"
    s = re.sub(r"_C$", "", cls)
    s = re.sub(r"_Character.*$", "", s)
    s = re.sub(r"_BP.*$", "", s)
    return s or "Unknown"


def safe_name(s: str) -> str:
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", s).strip(" .")
    return s or "Unknown"


def iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def pad12(v):
    v = list(v) if isinstance(v, (list, tuple)) else []
    v = v[:12]
    return v + [None] * (12 - len(v))


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def load_manifest(path: Path | None) -> dict:
    """Map log file name -> manifest entry."""
    if not path or not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"warning: couldn't read manifest {path}: {e}", file=sys.stderr)
        return {}
    runs = data.get("runs", []) if isinstance(data, dict) else data
    out = {}
    for r in runs:
        if isinstance(r, dict) and r.get("log"):
            out[Path(r["log"]).name] = r
    return out


def find_inputs(target: Path) -> list[Path]:
    if target.is_file():
        return [target]
    files = []
    for p in sorted(target.rglob("*")):
        if p.is_file() and p.name not in SKIP_FILES and p.suffix.lower() != ".json":
            files.append(p)
    return files


def new_run(path: Path, src: dict, header: dict, order: int) -> dict:
    return {
        "log": path.name,
        "order": order,
        "source": src.get("source") or path.name,
        "map": header.get("map") or src.get("map") or "",
        "save_epoch": float(src.get("save_mtime") or path.stat().st_mtime),
        "header": header,
        "dinos": {},
        "anc": defaultdict(lambda: {"maternal": {}, "paternal": {}}),
        "pods": [],
        "end": None,
    }


def parse_file(path: Path, manifest: dict, report: dict, order_start: int) -> list[dict]:
    src = manifest.get(path.name, {})
    try:
        data = path.read_bytes()
    except OSError as e:
        report["unreadable"].append(f"{path}: {e}")
        return []

    runs, cur, order = [], None, order_start
    for m in LINE_RE.finditer(data):
        kind = m.group(1).decode("ascii", "replace")
        raw = m.group(2).decode("utf-8", "replace")
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            report["bad_lines"] += 1
            if len(report["bad_examples"]) < 25:
                report["bad_examples"].append(f"{path.name}: {raw[:200]}")
            continue
        if not isinstance(obj, dict):
            report["bad_lines"] += 1
            continue

        if kind == "RUN":
            cur = new_run(path, src, obj, order)
            order += 1
            runs.append(cur)
            continue
        if cur is None:  # lines without a RUN header (e.g. log started mid-dump)
            cur = new_run(path, src, {}, order)
            order += 1
            runs.append(cur)
            report["runs_without_header"] += 1

        if kind == "D":
            did = make_id(obj.get("id1"), obj.get("id2"))
            if not did:
                report["no_id_lines"] += 1
                continue
            if did in cur["dinos"]:
                report["dupes_within_run"] += 1
            cur["dinos"][did] = obj
        elif kind == "A":
            did = make_id(obj.get("id1"), obj.get("id2"))
            if not did:
                report["no_id_lines"] += 1
                continue
            line = "paternal" if text(obj.get("line", "F")).upper().startswith("M") else "maternal"
            bucket = cur["anc"][did][line]
            idx = num(obj.get("i"), len(bucket))
            bucket[idx] = obj
        elif kind == "C":
            obj["_source"] = cur["source"]
            obj["_map"] = cur["map"]
            cur["pods"].append(obj)
        elif kind == "END":
            cur["end"] = obj
            cur = None
        else:
            report["unknown_kinds"][kind] += 1

    for r in runs:
        r["file"] = str(path)
    return runs


# ---------------------------------------------------------------------------
# Building records
# ---------------------------------------------------------------------------

def norm_entry(e: dict, idx: int) -> dict:
    return {
        "index": idx,
        "male": {"name": text(e.get("mn")), "id64": make_id(e.get("m1"), e.get("m2"))},
        "female": {"name": text(e.get("fn")), "id64": make_id(e.get("f1"), e.get("f2"))},
    }


def pick_parents(maternal: list, paternal: list):
    if PARENT_ENTRY == "none":
        return None
    line = maternal or paternal
    if not line:
        return None
    e = line[-1] if PARENT_ENTRY == "last" else line[0]
    return {"mother": e["female"], "father": e["male"]}


def build(runs: list[dict], report: dict):
    runs.sort(key=lambda r: (r["save_epoch"], r["order"]))
    state: dict[str, dict] = {}

    for run in runs:
        for did, core in run["dinos"].items():
            st = state.setdefault(did, {
                "core": None, "epoch": -1.0,
                "sightings": [], "anc": {"maternal": [], "paternal": []},
            })
            st["sightings"].append({
                "source": run["source"],
                "map": run["map"],
                "save_time": iso(run["save_epoch"]),
                "x": num(core.get("x")), "y": num(core.get("y")), "z": num(core.get("z")),
                "cryo": bool(flag(core.get("cryo"))),
                "in": core.get("in"),
                "name_then": text(core.get("name")),
                "tribe_then": text(core.get("tribe")),
            })
            if run["save_epoch"] >= st["epoch"]:
                st["core"], st["epoch"] = core, run["save_epoch"]

            anc = run["anc"].get(did)
            if anc:
                for line in ("maternal", "paternal"):
                    entries = [norm_entry(anc[line][k], i)
                               for i, k in enumerate(sorted(anc[line]))]
                    if entries and len(entries) >= len(st["anc"][line]):
                        st["anc"][line] = entries

        # ancestry lines for dinos with no D line in that run
        for did in run["anc"]:
            if did not in run["dinos"]:
                report["anc_without_dino"] += 1

    # parents / children
    parents = {}
    children = defaultdict(list)
    for did, st in state.items():
        p = pick_parents(st["anc"]["maternal"], st["anc"]["paternal"])
        parents[did] = p
        if p:
            for role in ("mother", "father"):
                pid = p[role]["id64"]
                if pid:
                    children[pid].append({
                        "id64": did,
                        "name": text(st["core"].get("name")),
                        "species": species_of(st["core"]),
                    })

    # ghosts: ancestors that never appear as dumped dinos
    ghosts: dict[str, dict] = {}
    for did, st in state.items():
        for line in ("maternal", "paternal"):
            for e in st["anc"][line]:
                for sex, key in (("M", "male"), ("F", "female")):
                    gid = e[key]["id64"]
                    if gid and gid not in state:
                        g = ghosts.setdefault(gid, {"id64": gid, "sex": sex, "names": set(),
                                                   "ancestor_of": set()})
                        if e[key]["name"]:
                            g["names"].add(e[key]["name"])
                        g["ancestor_of"].add(did)
    ghost_list = []
    for gid, g in sorted(ghosts.items()):
        ghost_list.append({
            "id64": gid,
            "sex": g["sex"],
            "names": sorted(g["names"]),
            "ancestor_of": sorted(g["ancestor_of"]),
            "children": children.get(gid, []),
        })

    # final records
    records = []
    for did, st in state.items():
        c = st["core"]
        wild, tamed, mx = pad12(c.get("wild")), pad12(c.get("tamed")), pad12(c.get("max"))
        lb, le = num(c.get("lvl_base")), num(c.get("lvl_extra"))
        female = flag(c.get("female"))
        p = parents[did]
        sightings = sorted(st["sightings"], key=lambda s: s["save_time"])
        rec = {
            "id64": did,
            "id1": u32(c.get("id1")),
            "id2": u32(c.get("id2")),
            "class": text(c.get("cls")),
            "species": species_of(c),
            "name": text(c.get("name")),
            "sex": None if female is None else ("F" if female else "M"),
            "tribe": {"id": num(c.get("tribe_id")), "name": text(c.get("tribe"))},
            "tamer": text(c.get("tamer")),
            "imprinter": text(c.get("imprinter")),
            "tamed_on_server": text(c.get("server")),
            "tamed_time": num(c.get("tamed_time")),
            "neutered": flag(c.get("neutered")),
            "baby": flag(c.get("baby")),
            "baby_age": num(c.get("baby_age")),
            "level": {
                "base": lb, "extra": le,
                "total": (lb or 0) + (le or 0) if (lb is not None or le is not None) else None,
            },
            "imprint": num(c.get("imprint")),
            "taming_effectiveness": num(c.get("te")),
            "mutations": {"maternal": num(c.get("mut_f")), "paternal": num(c.get("mut_m"))},
            "colors": c.get("colors") if isinstance(c.get("colors"), list) else [],
            "stats": {
                n: {"wild": num(wild[i]), "tamed": num(tamed[i]), "max": num(mx[i])}
                for i, n in enumerate(STAT_NAMES)
            },
            "parents": p,
            "children": children.get(did, []),
            "ancestry": {
                "maternal_line": st["anc"]["maternal"],
                "paternal_line": st["anc"]["paternal"],
            },
            "first_seen": sightings[0]["save_time"] if sightings else None,
            "last_seen": sightings[-1]["save_time"] if sightings else None,
            "seen_in": sightings,
            "raw": c,
        }
        records.append(rec)

    records.sort(key=lambda r: (r["species"].lower(), r["id64"]))
    return records, ghost_list


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE dinos (
  id64 TEXT PRIMARY KEY, id1 INTEGER, id2 INTEGER,
  species TEXT, class TEXT, name TEXT, sex TEXT,
  tribe_id INTEGER, tribe TEXT, tamer TEXT, imprinter TEXT, tamed_on_server TEXT,
  level_total INTEGER, imprint REAL, taming_effectiveness REAL,
  mut_maternal INTEGER, mut_paternal INTEGER, neutered INTEGER, baby INTEGER,
  mother_id TEXT, father_id TEXT, colors TEXT,
  first_seen TEXT, last_seen TEXT, json TEXT
);
CREATE TABLE stats (
  id64 TEXT, stat TEXT, stat_index INTEGER,
  wild INTEGER, tamed INTEGER, max_value REAL,
  PRIMARY KEY (id64, stat)
);
CREATE TABLE ancestry (
  id64 TEXT, line TEXT, idx INTEGER,
  male_id TEXT, male_name TEXT, female_id TEXT, female_name TEXT
);
CREATE TABLE sightings (
  id64 TEXT, source TEXT, map TEXT, save_time TEXT,
  x REAL, y REAL, z REAL, cryo INTEGER, container TEXT
);
CREATE TABLE ghosts (id64 TEXT PRIMARY KEY, sex TEXT, names TEXT);
CREATE INDEX ix_dinos_species ON dinos(species);
CREATE INDEX ix_dinos_mother ON dinos(mother_id);
CREATE INDEX ix_dinos_father ON dinos(father_id);
CREATE INDEX ix_stats_stat ON stats(stat, wild);
CREATE INDEX ix_anc_male ON ancestry(male_id);
CREATE INDEX ix_anc_female ON ancestry(female_id);
CREATE INDEX ix_sight_id ON sightings(id64);
"""


def write_sqlite(path: Path, records: list[dict], ghosts: list[dict]):
    if path.exists():
        path.unlink()
    db = sqlite3.connect(path)
    db.executescript(SCHEMA)
    for r in records:
        p = r["parents"] or {}
        db.execute(
            "INSERT INTO dinos VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (r["id64"], r["id1"], r["id2"], r["species"], r["class"], r["name"], r["sex"],
             r["tribe"]["id"], r["tribe"]["name"], r["tamer"], r["imprinter"], r["tamed_on_server"],
             r["level"]["total"], r["imprint"], r["taming_effectiveness"],
             r["mutations"]["maternal"], r["mutations"]["paternal"],
             None if r["neutered"] is None else int(r["neutered"]),
             None if r["baby"] is None else int(r["baby"]),
             (p.get("mother") or {}).get("id64"), (p.get("father") or {}).get("id64"),
             json.dumps(r["colors"]), r["first_seen"], r["last_seen"],
             json.dumps(r, ensure_ascii=False)),
        )
        for i, n in enumerate(STAT_NAMES):
            s = r["stats"][n]
            db.execute("INSERT INTO stats VALUES (?,?,?,?,?,?)",
                       (r["id64"], n, i, s["wild"], s["tamed"], s["max"]))
        for line, key in (("maternal", "maternal_line"), ("paternal", "paternal_line")):
            for e in r["ancestry"][key]:
                db.execute("INSERT INTO ancestry VALUES (?,?,?,?,?,?,?)",
                           (r["id64"], line, e["index"], e["male"]["id64"], e["male"]["name"],
                            e["female"]["id64"], e["female"]["name"]))
        for s in r["seen_in"]:
            db.execute("INSERT INTO sightings VALUES (?,?,?,?,?,?,?,?,?)",
                       (r["id64"], s["source"], s["map"], s["save_time"],
                        s["x"], s["y"], s["z"], int(s["cryo"]),
                        None if s["in"] is None else str(s["in"])))
    for g in ghosts:
        db.execute("INSERT INTO ghosts VALUES (?,?,?)",
                   (g["id64"], g["sex"], json.dumps(g["names"], ensure_ascii=False)))
    db.commit()
    db.close()


def write_outputs(out: Path, records, ghosts, pods, split: bool):
    out.mkdir(parents=True, exist_ok=True)
    dino_dir = out / "dinos"
    if dino_dir.exists():
        shutil.rmtree(dino_dir)
    if split:
        for r in records:
            d = dino_dir / safe_name(r["species"])
            d.mkdir(parents=True, exist_ok=True)
            (d / f"{r['id64']}.json").write_text(
                json.dumps(r, indent=2, ensure_ascii=False), encoding="utf-8")

    with (out / "master.json").open("w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False)
    with (out / "master.jsonl").open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    (out / "ghosts.json").write_text(json.dumps(ghosts, indent=1, ensure_ascii=False), encoding="utf-8")
    with (out / "cryopods_raw.jsonl").open("w", encoding="utf-8") as f:
        for p in pods:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    write_sqlite(out / "dinos.sqlite", records, ghosts)


def write_report(out: Path, report: dict, runs, records, ghosts, pods):
    lines = []
    lines.append(f"DinoDump parse report — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    lines.append(f"Input files read:        {report['files']}")
    lines.append(f"Dump runs found:         {len(runs)}")
    lines.append(f"Unique dinos:            {len(records)}")
    lines.append(f"Ghost ancestors:         {len(ghosts)}")
    lines.append(f"Raw cryopod lines:       {len(pods)}")
    lines.append(f"Bad (unreadable) lines:  {report['bad_lines']}")
    lines.append(f"Lines with no dino ID:   {report['no_id_lines']}")
    lines.append(f"Same dino twice in a run:{report['dupes_within_run']:>5}")
    lines.append(f"Ancestry w/o main line:  {report['anc_without_dino']}")
    lines.append(f"Runs with no RUN header: {report['runs_without_header']}")
    if report["unknown_kinds"]:
        lines.append(f"Unknown line kinds:      {dict(report['unknown_kinds'])}")
    lines.append("")

    no_end = [r for r in runs if r["end"] is None]
    empty = [r for r in runs if not r["dinos"]]
    mismatch = [r for r in runs if r["end"] and num(r["end"].get("dinos")) not in (None, len(r["dinos"]))]
    if no_end:
        lines.append("RUNS THAT NEVER FINISHED (no END line — crashed, timed out, or log cut off):")
        lines += [f"  {r['source']}  ({r['log']})" for r in no_end]
        lines.append("")
    if empty:
        lines.append("RUNS WITH ZERO DINOS (wrong save path? server made a fresh map?):")
        lines += [f"  {r['source']}  ({r['log']})" for r in empty]
        lines.append("")
    if mismatch:
        lines.append("RUNS WHERE THE MOD'S COUNT DOESN'T MATCH LINES READ (lines lost):")
        lines += [f"  {r['source']}: mod said {r['end'].get('dinos')}, read {len(r['dinos'])}" for r in mismatch]
        lines.append("")
    if report["bad_examples"]:
        lines.append("Sample bad lines (usually a name with an unescaped quote):")
        lines += [f"  {b}" for b in report["bad_examples"]]
        lines.append("")
    if report["unreadable"]:
        lines.append("Files that couldn't be read:")
        lines += [f"  {u}" for u in report["unreadable"]]
        lines.append("")

    sp = Counter(r["species"] for r in records)
    lines.append("Dinos per species:")
    for name, n in sp.most_common():
        lines.append(f"  {n:>7}  {name}")
    (out / "report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return lines


# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Turn DinoDump log output into per-dino files and a database.")
    ap.add_argument("input", help="folder of logs (searched recursively) or a single log file")
    ap.add_argument("-o", "--out", default="dinodump_out", help="output folder (default: dinodump_out)")
    ap.add_argument("--manifest", help="manifest.json from dinodump_batch.py (default: <input>/manifest.json)")
    ap.add_argument("--no-split", action="store_true", help="skip the one-file-per-dino folder")
    args = ap.parse_args()

    target = Path(args.input)
    if not target.exists():
        sys.exit(f"not found: {target}")
    man_path = Path(args.manifest) if args.manifest else (target if target.is_dir() else target.parent) / "manifest.json"
    manifest = load_manifest(man_path)

    report = {
        "files": 0, "bad_lines": 0, "bad_examples": [], "no_id_lines": 0,
        "dupes_within_run": 0, "anc_without_dino": 0, "runs_without_header": 0,
        "unknown_kinds": Counter(), "unreadable": [],
    }
    runs = []
    for p in find_inputs(target):
        report["files"] += 1
        runs += parse_file(p, manifest, report, len(runs))

    if not runs:
        sys.exit("No DINODUMP lines found. Check that the mod's output is reaching the log.")

    records, ghosts = build(runs, report)
    pods = [p for r in runs for p in r["pods"]]
    out = Path(args.out)
    write_outputs(out, records, ghosts, pods, split=not args.no_split)
    summary = write_report(out, report, runs, records, ghosts, pods)
    cut = summary.index("Dinos per species:") if "Dinos per species:" in summary else len(summary)
    print("\n".join(summary[:cut]).rstrip())
    print("(full report, including per-species counts, is in report.txt)")
    print(f"\nDone. Output in: {out.resolve()}")


if __name__ == "__main__":
    main()
