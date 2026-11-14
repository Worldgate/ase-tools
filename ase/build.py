"""
dinodump_build.py
-----------------
Turns DinoDump plugin output, or arkextract extracts, into the finished dataset.
(ase-tools package version of server/dinodump_build.py: same output, and it also
reads <save>.extract.zip files made by `ase tamed` / arkextract.py directly.)

Input: one or more dump folders written by the plugin, or .extract.zip files
(ArkApi\\Plugins\\DinoDump\\dumps\\<map>_<time>\\), each holding
    run.json      dinos.jsonl      pods.jsonl      pods.bin
and optionally a source.json saying where the save came from:
    {"server": "OC-PVE-Official-TheIsland97", "date": "2023-09-30"}
(without it the folder name is used, or --server/--date on the command line).

Output (in --out, default dinodump_out):
    dinos/<origin server>/<species>/<bucket>/<id64>.json   one file per dino
    master.jsonl.gz      every dino, one per line
    ghosts.jsonl.gz      ancestors that never turned up as a dino of their own
    skiffs.jsonl         hover skiffs found in item storage
    dinodump.sqlite      everything, for the website / queries
    report.txt           what happened, what looked odd

What it does:
  * live dinos and cryopodded dinos become one record format (dinodump-v1);
    pods are decoded from pods.bin with dinodump_decode.py
  * the same dino seen in many saves becomes ONE record, keeping the newest
    copy, with every sighting listed in seen_in
  * parents come from the last ancestry entry; children are worked out from
    everyone who lists this dino as a parent
  * every record is tagged: creature / bee / vehicle (rafts, boats)
  * flags oddities: wild points that don't add up to level-1, mutation
    counters that are negative or huge

Usage:
    python3 dinodump_build.py                      # uses DUMPS_DIR / OUT_DIR from dinodump_config.py
    python3 dinodump_build.py DUMP_FOLDER [...] -o OUT
    python3 dinodump_build.py --scan ~/dinodump/dumps -o ~/dinodump/out
    options: --server NAME --date YYYY-MM-DD   (for a single dump folder)
             --anonymize                       replace player names/IDs
             --no-files                        skip the per-dino files
             --workers N                       pod decoding processes

Settings live in dinodump_config.py (next to this script); command-line
options override them. Python 3.8+, standard library only. Needs
dinodump_decode.py next to it.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import time
import zipfile
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from .core.cryopod import decode_blob, decode_item


def _load_config():
    """dinodump_config.py from the current folder, if there is one."""
    import importlib.util
    path = Path.cwd() / "dinodump_config.py"
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location("dinodump_config", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


CFG = _load_config()


def cfg(name, default):
    return getattr(CFG, name, default) if CFG else default

FORMAT = "dinodump-v1"
STATS = ["health", "stamina", "torpidity", "oxygen", "food", "water",
         "temperature", "weight", "melee", "speed", "fortitude", "crafting"]
LVL_RE = re.compile(r"^(.*?)\s*-\s*Lvl\s+(\d+)\s*$")
LABEL_RE = re.compile(r"^(.*?)\s*-\s*Lvl\s+(\d+)\s*\((.*)\)\s*$")
FOLDER_RE = re.compile(cfg("FOLDER_NAME_PATTERN", r"^(.*?)\s*\((\d{4}-\d{2}-\d{2})(?:-\d+)?\)\s*$"))
UNKNOWN = cfg("UNKNOWN_SERVER_FOLDER", "_Unknown")
CATEGORY_RULES = cfg("CATEGORY_RULES", [("bee", ["bee_queen", "/bee/"]), ("vehicle", ["raft", "motorboat"])])
SKIP_BREEDING = set(cfg("SKIP_BREEDING_CHECKS", {"bee", "vehicle", "wild"}))
COUNTER_MAX = cfg("MUTATION_COUNTER_NORMAL_MAX", 255)


# ===========================================================================
# small helpers
# ===========================================================================

def clean(s) -> str:
    return s.strip() if isinstance(s, str) else ""


def arr(v, n: int, default=0) -> list:
    """Static arrays come back as a list with gaps, a single value, or nothing."""
    if v is None:
        out = []
    elif isinstance(v, list):
        out = list(v)
    else:
        out = [v]
    out = out[:n] + [None] * (n - len(out))
    return [default if x is None else x for x in out]


def id64(a, b):
    try:
        a, b = int(a) & 0xFFFFFFFF, int(b) & 0xFFFFFFFF
    except (TypeError, ValueError):
        return None
    if a == 0 and b == 0:
        return None
    return str((a << 32) | b)


def export_class(path: str) -> str:
    """Blueprint'/Game/X/Y.Y'  ->  /Game/X/Y.Y_C"""
    p = clean(path)
    if p.startswith("Blueprint'") and p.endswith("'"):
        return p[len("Blueprint'"):-1] + "_C"
    return p


def split_level(name: str):
    m = LVL_RE.match(clean(name))
    if m:
        return m.group(1), int(m.group(2))
    return clean(name), None


def counter_state(v) -> str | None:
    if v is None:
        return None
    if v < 0:
        return "negative"
    if v > COUNTER_MAX:
        return "huge"
    return "normal"


def safe_part(s: str, fallback: str = None) -> str:
    fallback = fallback or UNKNOWN
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", clean(s)).strip(" .")
    return (s or fallback)[:120]


def category_of(cls: str) -> str:
    c = cls.lower()
    for name, needles in CATEGORY_RULES:
        if any(n in c for n in needles):
            return name
    return "creature"


def r1(x):
    return round(x, 4) if isinstance(x, float) else x


# ===========================================================================
# building one canonical record
# ===========================================================================

def ancestry_line(entries: list, plugin_style: bool) -> list:
    """Stored oldest-first, last = parents. Output gen 1 = parents."""
    out = []
    n = len(entries)
    for i, e in enumerate(entries):
        if plugin_style:
            mn, m1, m2 = e.get("male"), e.get("male_id1"), e.get("male_id2")
            fn, f1, f2 = e.get("female"), e.get("female_id1"), e.get("female_id2")
        else:
            mn, m1, m2 = e.get("MaleName"), e.get("MaleDinoID1"), e.get("MaleDinoID2")
            fn, f1, f2 = e.get("FemaleName"), e.get("FemaleDinoID1"), e.get("FemaleDinoID2")
        mname, mlvl = split_level(mn or "")
        fname, flvl = split_level(fn or "")
        out.append({
            "gen": n - i,
            "male": {"id64": id64(m1, m2), "name": mname, "level": mlvl},
            "female": {"id64": id64(f1, f2), "name": fname, "level": flvl},
        })
    out.reverse()  # gen 1 (parents) first
    return out


def finish_record(r: dict) -> dict:
    """Shared tail: stats, parents, flags, category."""
    wild, tamed, vals = r.pop("_wild"), r.pop("_tamed"), r.pop("_max")
    stats = {}
    for i, name in enumerate(STATS):
        w, t, v = wild[i], tamed[i], vals[i]
        if (w or t or v):
            stats[name] = {"wild": w, "tamed": t, "value": r1(float(v)) if v is not None else None}
    r["stats"] = stats

    base, extra = r["level"]["wild"], r["level"]["tamed"]
    flags = []
    if r["category"] not in SKIP_BREEDING and base is not None and base - 1 != sum(wild):
        flags.append("wild_points_dont_match_level")
    if r["category"] not in SKIP_BREEDING and extra is not None and extra != sum(tamed):
        flags.append("tamed_points_dont_match_level")
    st = r["mutations"]
    st["counter_state"] = "normal"
    for k in ("maternal", "paternal"):
        s = counter_state(st.get(k))
        if s in ("negative", "huge"):
            st["counter_state"] = s
            flags.append(f"mutation_counter_{s}")
    r["flags"] = sorted(set(flags))

    mat, pat = r["ancestry"]["maternal_line"], r["ancestry"]["paternal_line"]
    last = (mat or pat or [None])[0]
    r["parents"] = None if not last else {"mother": last["female"], "father": last["male"]}
    return r


def from_live(d: dict) -> dict:
    """Plugin dino line (v0.1 or v0.2+ keys) -> canonical record."""
    cls = d.get("class") or export_class(d.get("blueprint", ""))
    base = d.get("level_wild", d.get("level_base"))
    extra = d.get("level_extra")
    if extra is None and d.get("level") is not None and base is not None:
        extra = d["level"] - base
    sex = d.get("female")
    r = {
        "format": FORMAT,
        "id64": d.get("id64") or id64(d.get("id1"), d.get("id2")),
        "id1": d.get("id1"), "id2": d.get("id2"),
        "species": clean(d.get("species")),
        "class": cls,
        "category": category_of(cls),
        "name": clean(d.get("name")),
        "sex": None if sex is None else ("F" if sex else "M"),
        "neutered": bool(d.get("neutered")),
        "level": {"total": (base or 0) + (extra or 0) if base is not None else d.get("level"),
                  "wild": base, "tamed": extra},
        "imprint": r1(d.get("imprint")),
        "taming_effectiveness": r1(d.get("taming_effectiveness")),
        "colors": arr(d.get("colors"), 6),
        "mutations": {"maternal": d.get("mutations_maternal"), "paternal": d.get("mutations_paternal")},
        "people": {
            "tribe": clean(d.get("tribe")), "tribe_id": d.get("tribe_id", d.get("team")),
            "tamer": clean(d.get("tamer")), "owner": clean(d.get("owner_name")),
            "owner_player_id": d.get("owner_player_id") or None,
            "imprinter": clean(d.get("imprinter")),
            "imprinter_player_id": (str(d["imprinter_player_id"]) if d.get("imprinter_player_id") not in (None, 0, "0") else None),
        },
        "origin": {
            "tamed_on_server": clean(d.get("tamed_on_server")) or None,
            "uploaded_from_server": clean(d.get("uploaded_from_server")) or None,
            "latest_uploaded_from_server": clean(d.get("latest_uploaded_from_server")) or None,
            "previous_uploaded_from_server": clean(d.get("previous_uploaded_from_server")) or None,
            "creation_time": d.get("creation_time"),
        },
        "ancestry": {
            "maternal_line": ancestry_line(d.get("ancestors_maternal") or [], True),
            "paternal_line": ancestry_line(d.get("ancestors_paternal") or [], True),
        },
        "saddle": None,
        "_wild": arr(d.get("wild_levels"), 12),
        "_tamed": arr(d.get("tamed_levels"), 12),
        "_max": arr(d.get("max_stats"), 12, None),
    }
    if d.get("wild"):
        r["category"] = "wild"
    return finish_record(r)


def from_pod(objs: list, label: str, cls_path: str, saddle: dict | None) -> dict:
    """Decoded pod objects -> canonical record."""
    p = objs[0]["properties"]
    sc = next((o["properties"] for o in objs[1:] if "StatusComponent" in o["class"]), {})
    m = LABEL_RE.match(clean(label))
    species = m.group(3) if m else ""
    cls = export_class(cls_path) if cls_path else objs[0]["class"]
    base = sc.get("BaseCharacterLevel") or 1          # unsaved = default 1
    extra = sc.get("ExtraCharacterLevel") or 0
    tim = sc.get("TamedIneffectivenessModifier") or 0.0
    r = {
        "format": FORMAT,
        "id64": id64(p.get("DinoID1"), p.get("DinoID2")),
        "id1": p.get("DinoID1"), "id2": p.get("DinoID2"),
        "species": species,
        "class": cls,
        "category": category_of(cls),
        "name": clean(p.get("TamedName")),
        "sex": "F" if p.get("bIsFemale") else "M",
        "neutered": bool(p.get("bNeutered")),
        "level": {"total": base + extra, "wild": base, "tamed": extra},
        "imprint": r1(sc.get("DinoImprintingQuality") or 0.0),
        "taming_effectiveness": r1(1.0 / (1.0 + tim)),
        "colors": arr(p.get("ColorSetIndices"), 6),
        "mutations": {"maternal": p.get("RandomMutationsFemale") or 0, "paternal": p.get("RandomMutationsMale") or 0},
        "people": {
            "tribe": clean(p.get("TribeName")), "tribe_id": p.get("TargetingTeam"),
            "tamer": clean(p.get("TamerString")), "owner": clean(p.get("OwningPlayerName")),
            "owner_player_id": p.get("OwningPlayerID") or None,
            "imprinter": clean(p.get("ImprinterName")),
            "imprinter_player_id": str(p["ImprinterPlayerDataID"]) if p.get("ImprinterPlayerDataID") else None,
        },
        "origin": {
            "tamed_on_server": clean(p.get("TamedOnServerName")) or None,
            "uploaded_from_server": clean(p.get("UploadedFromServerName")) or None,
            "latest_uploaded_from_server": clean(p.get("LatestUploadedFromServerName")) or None,
            "previous_uploaded_from_server": clean(p.get("PreviousUploadedFromServerName")) or None,
            "creation_time": None,
        },
        "ancestry": {
            "maternal_line": ancestry_line(p.get("DinoAncestors") or [], False),
            "paternal_line": ancestry_line(p.get("DinoAncestorsMale") or [], False),
        },
        "saddle": saddle,
        "_wild": arr(sc.get("NumberOfLevelUpPointsApplied"), 12),
        "_tamed": arr(sc.get("NumberOfLevelUpPointsAppliedTamed"), 12),
        "_max": arr(sc.get("MaxStatusValues"), 12, None),
    }
    return finish_record(r)


def saddle_summary(it: dict) -> dict | None:
    if not it:
        return None
    arch = it.get("ItemArchetype")
    path = arch.get("path", "") if isinstance(arch, dict) else ""
    t = path.split(".")[-1].replace("PrimalItemArmor_", "").replace("_C", "") if path else None
    return {"type": t, "quality": it.get("ItemQualityIndex"), "rating": r1(it.get("ItemRating")),
            "crafter": clean(it.get("CrafterCharacterName")) or None,
            "crafter_tribe": clean(it.get("CrafterTribeName")) or None}


# ===========================================================================
# reading a dump folder
# ===========================================================================

# ---------------------------------------------------------------------------
# a "source" is a plugin dump folder or an .extract.zip; both hold
# dinos.jsonl, pods.jsonl and pods.bin


def is_extract(src: Path) -> bool:
    return src.is_file() and src.name.lower().endswith(".extract.zip")


def source_name(src: Path) -> str:
    """Folder name, or the save name an extract was made from."""
    return src.name[:-len(".extract.zip")] if is_extract(src) else src.name


def has_member(src: Path, name: str) -> bool:
    if is_extract(src):
        with zipfile.ZipFile(src) as z:
            return name in z.namelist()
    return (src / name).is_file()


def read_json_member(src: Path, name: str) -> dict:
    try:
        if is_extract(src):
            with zipfile.ZipFile(src) as z:
                return json.loads(z.read(name).decode("utf-8-sig"))
        return json.loads((src / name).read_text(encoding="utf-8-sig"))
    except (OSError, KeyError, json.JSONDecodeError):
        return {}


def member_lines(src: Path, name: str):
    """Yield text lines of dinos.jsonl / pods.jsonl from a folder or extract."""
    if is_extract(src):
        with zipfile.ZipFile(src) as z:
            if name not in z.namelist():
                return
            with z.open(name) as f:
                for raw in f:
                    yield raw.decode("utf-8-sig")
        return
    path = src / name
    if path.is_file():
        with open(path, encoding="utf-8-sig") as f:
            yield from f


class BinReader:
    """Random reads from pods.bin. Offsets only go forward in pods.jsonl order,
    so reading a compressed zip member stays a single pass."""

    def __init__(self, src: Path):
        self.zip = self.fh = None
        self.size = 0
        if is_extract(src):
            self.zip = zipfile.ZipFile(src)
            if "pods.bin" in self.zip.namelist():
                self.size = self.zip.getinfo("pods.bin").file_size
                self.fh = self.zip.open("pods.bin")
        elif (src / "pods.bin").is_file():
            self.size = (src / "pods.bin").stat().st_size
            self.fh = open(src / "pods.bin", "rb") if self.size else None

    def read(self, off, ln):
        if self.fh is None or off + ln > self.size:
            return None
        if self.fh.tell() != off:
            self.fh.seek(off)
        return self.fh.read(ln)

    def close(self):
        if self.fh:
            self.fh.close()
        if self.zip:
            self.zip.close()


def source_of(folder: Path, cli_server, cli_date) -> dict:
    src = {"server": None, "date": None, "map": None, "dump": source_name(folder)}
    run = read_json_member(folder, "run.json")
    if is_extract(folder):
        # an extract is complete by construction; meta.json knows the map
        meta = read_json_member(folder, "meta.json")
        run = {"map": meta.get("map"), "complete": True}
    src["map"] = run.get("map")
    if has_member(folder, "source.json"):
        try:
            s = read_json_member(folder, "source.json")
            src["server"], src["date"] = s.get("server"), s.get("date")
            # written by the plugin's -DinoDumpSource: "Server (YYYY-MM-DD)"
            if s.get("label") and not src["server"]:
                m = FOLDER_RE.match(s["label"])
                if m:
                    src["server"], src["date"] = m.group(1), m.group(2)
                else:
                    src["server"] = s["label"]
        except (OSError, json.JSONDecodeError):
            pass
    if not src["server"]:
        for name in (source_name(folder), folder.parent.name):
            m = FOLDER_RE.match(name)
            if m:
                src["server"], src["date"] = m.group(1), m.group(2)
                break
    if cli_server:
        src["server"] = cli_server
    if cli_date:
        src["date"] = cli_date
    if not src["server"]:
        src["server"] = clean(run.get("session")) or source_name(folder)
    if not src["date"]:
        src["date"] = (run.get("started") or "")[:10] or None
    src["complete"] = bool(run)
    return src


def decode_pod_line(args):
    """Worker: one pods.jsonl line + its bytes -> ('dino', rec, where) / ('skiff', ...) / ('error', msg)."""
    line, blobs = args
    try:
        p = json.loads(line)
    except json.JSONDecodeError as e:
        return ("error", f"bad pods.jsonl line: {e}", None)
    owner = p.get("owner") or {}
    where = {
        "where": "cryopod",
        "container": (owner.get("blueprint") or "").split(".")[-1].rstrip("'") or None,
        "container_team": owner.get("team"),
        "location": [round(x) for x in owner["location"]] if owner.get("location") else None,
    }
    dino_cd = next((c for c in p.get("custom_data", []) if c.get("name") == "Dino"), None)
    if not dino_cd:
        names = [c.get("name") for c in p.get("custom_data", [])]
        if "HoverSailData" in names:
            return ("skiff", {"item_id1": p.get("item_id1"), "item_id2": p.get("item_id2"),
                              "team": owner.get("team"), "container": where["container"],
                              "location": where["location"]}, None)
        return ("other", names, None)
    if not blobs or blobs[0] is None:
        return ("error", "pod bytes missing (pods.bin cut short?)", None)
    try:
        objs = decode_blob(blobs[0])
        bad = [o.get("error") for o in objs if o.get("error")]
        if bad:
            return ("error", bad[0], None)
        saddle = None
        if len(blobs) > 1 and blobs[1]:
            try:
                saddle = saddle_summary(decode_item(blobs[1]))
            except Exception:  # noqa: BLE001
                saddle = {"error": "could not decode saddle"}
        strings = dino_cd.get("strings") or []
        classes = dino_cd.get("classes") or []
        rec = from_pod(objs, strings[1] if len(strings) > 1 else "", classes[0] if classes else "", saddle)
        return ("dino", rec, where)
    except Exception as e:  # noqa: BLE001
        return ("error", f"{type(e).__name__}: {e}", None)


def iter_pod_jobs(folder: Path, stats: Counter):
    if not has_member(folder, "pods.jsonl"):
        return
    bins = BinReader(folder)
    try:
        for line in member_lines(folder, "pods.jsonl"):
            line = line.strip()
            if not line:
                continue
            blobs = []
            try:
                p = json.loads(line)
                cd = next((c for c in p.get("custom_data", []) if c.get("name") == "Dino"), None)
                for ba in (cd or {}).get("byte_arrays", []):
                    blobs.append(bins.read(ba["offset"], ba["length"]))
            except (json.JSONDecodeError, KeyError):
                pass
            if blobs and blobs[0] is None:
                stats["pods_beyond_bin"] += 1
                continue
            yield (line, blobs)
    finally:
        bins.close()


# ===========================================================================
# the database
# ===========================================================================

SCHEMA = """
PRAGMA journal_mode=OFF;
PRAGMA synchronous=OFF;
CREATE TABLE IF NOT EXISTS dinos (
  id64 TEXT PRIMARY KEY, rank TEXT, species TEXT, category TEXT, name TEXT,
  origin_server TEXT, tribe TEXT, tribe_id INTEGER, level INTEGER,
  mother_id TEXT, father_id TEXT, record TEXT);
CREATE TABLE IF NOT EXISTS sightings (
  id64 TEXT, server TEXT, date TEXT, map TEXT, dump TEXT, place TEXT,
  container TEXT, location TEXT, tribe TEXT, name TEXT);
CREATE TABLE IF NOT EXISTS stats (
  id64 TEXT, stat TEXT, wild INTEGER, tamed INTEGER, value REAL);
CREATE TABLE IF NOT EXISTS ancestry (
  id64 TEXT, line TEXT, gen INTEGER,
  male_id TEXT, male_name TEXT, male_level INTEGER,
  female_id TEXT, female_name TEXT, female_level INTEGER);
CREATE TABLE IF NOT EXISTS skiffs (
  server TEXT, date TEXT, item_id1 INTEGER, item_id2 INTEGER, team INTEGER, container TEXT, location TEXT);
CREATE TABLE IF NOT EXISTS dumps (dump TEXT, server TEXT, date TEXT, map TEXT, live INTEGER, pods INTEGER, failed INTEGER);
CREATE TABLE IF NOT EXISTS records (id64 TEXT PRIMARY KEY, record TEXT);
"""

INDEXES = """
CREATE INDEX IF NOT EXISTS ix_sight ON sightings(id64);
CREATE INDEX IF NOT EXISTS ix_mother ON dinos(mother_id);
CREATE INDEX IF NOT EXISTS ix_father ON dinos(father_id);
CREATE INDEX IF NOT EXISTS ix_species ON dinos(species);
CREATE INDEX IF NOT EXISTS ix_origin ON dinos(origin_server);
CREATE INDEX IF NOT EXISTS ix_tribe ON dinos(tribe_id);
CREATE INDEX IF NOT EXISTS ix_stats ON stats(stat, wild);
CREATE INDEX IF NOT EXISTS ix_stats_id ON stats(id64);
CREATE INDEX IF NOT EXISTS ix_anc_m ON ancestry(male_id);
CREATE INDEX IF NOT EXISTS ix_anc_f ON ancestry(female_id);
CREATE INDEX IF NOT EXISTS ix_anc_id ON ancestry(id64);
"""

UPSERT = """
INSERT INTO dinos (id64, rank, species, category, name, origin_server, tribe, tribe_id, level, mother_id, father_id, record)
VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
ON CONFLICT(id64) DO UPDATE SET
  rank=excluded.rank, species=excluded.species, category=excluded.category, name=excluded.name,
  origin_server=excluded.origin_server, tribe=excluded.tribe, tribe_id=excluded.tribe_id, level=excluded.level,
  mother_id=excluded.mother_id, father_id=excluded.father_id, record=excluded.record
WHERE excluded.rank >= dinos.rank
"""


class Anon:
    """Stable stand-ins for player names and IDs (same input -> same output)."""

    def __init__(self, enabled: bool, tribes: bool = False):
        self.on = enabled
        self.tribes = tribes

    def tribe(self, s):
        if not self.tribes or not s:
            return s
        return "Tribe-" + hashlib.sha1(("t:" + s).encode()).hexdigest()[:8]

    def name(self, s):
        if not self.on or not s:
            return s
        return "Player-" + hashlib.sha1(("n:" + s).encode()).hexdigest()[:8]

    def pid(self, v):
        if not self.on or v in (None, ""):
            return v
        return "P" + hashlib.sha1(("i:" + str(v)).encode()).hexdigest()[:10]


TRIBE_NAMES: dict = {}   # tribe_id -> name, learned from live dinos (pods don't store the name)


def store(db, rec: dict, src: dict, order: int, where: dict, anon: Anon):
    if not rec.get("id64"):
        return False
    ppl = rec["people"]
    tid = ppl.get("tribe_id")
    if ppl.get("tribe") and tid:
        TRIBE_NAMES[tid] = ppl["tribe"]
    elif not ppl.get("tribe") and tid in TRIBE_NAMES:
        ppl["tribe"] = TRIBE_NAMES[tid]
        ppl["tribe_name_from"] = "matched_by_tribe_id"
    for k in ("tamer", "owner", "imprinter"):
        ppl[k] = anon.name(ppl.get(k))
    ppl["tribe"] = anon.tribe(ppl.get("tribe"))
    for k in ("owner_player_id", "imprinter_player_id"):
        ppl[k] = anon.pid(ppl.get(k))
    rank = f"{src['date'] or '0000-00-00'}|{order:06d}"
    par = rec.get("parents") or {}
    db.execute(UPSERT, (rec["id64"], rank, rec["species"], rec["category"], rec["name"],
                        rec["origin"]["tamed_on_server"], ppl["tribe"], ppl["tribe_id"], rec["level"]["total"],
                        (par.get("mother") or {}).get("id64"), (par.get("father") or {}).get("id64"),
                        json.dumps(rec, ensure_ascii=False, separators=(",", ":"))))
    db.execute("INSERT INTO sightings VALUES (?,?,?,?,?,?,?,?,?,?)",
               (rec["id64"], src["server"], src["date"], src["map"], src["dump"], where.get("where"),
                where.get("container"), json.dumps(where.get("location")), ppl["tribe"], rec["name"]))
    return True


# ===========================================================================
# main passes
# ===========================================================================

def ingest(folders, out: Path, args, report: list):
    db_path = out / "dinodump.sqlite"
    if db_path.exists():
        db_path.unlink()
    db = sqlite3.connect(db_path)
    db.executescript(SCHEMA)
    anon = Anon(args.anonymize, args.anonymize_tribes)
    totals = Counter()
    errors = Counter()

    pool = ProcessPoolExecutor(max_workers=args.workers) if args.workers > 1 else None
    try:
        for order, folder in enumerate(folders):
            src = source_of(folder, args.server, args.date)
            t0 = time.time()
            c = Counter()
            # live dinos
            for line in member_lines(folder, "dinos.jsonl"):
                if not line.strip():
                    continue
                try:
                    d = json.loads(line)
                    rec = from_live(d)
                    loc = d.get("location")
                    where = {"where": "wild" if d.get("wild") else "live",
                             "location": [round(x) for x in loc] if loc else None}
                    if store(db, rec, src, order, where, anon):
                        c["live"] += 1
                    else:
                        c["live_no_id"] += 1
                except Exception as e:  # noqa: BLE001
                    c["live_failed"] += 1
                    errors[f"live: {type(e).__name__}: {e}"[:120]] += 1
            # pods
            jobs = iter_pod_jobs(folder, c)
            results = pool.map(decode_pod_line, jobs, chunksize=256) if pool else map(decode_pod_line, jobs)
            for kind, val, where in results:
                if kind == "dino":
                    if store(db, val, src, order, where, anon):
                        c["pods"] += 1
                elif kind == "skiff":
                    c["skiffs"] += 1
                    db.execute("INSERT INTO skiffs VALUES (?,?,?,?,?,?,?)",
                               (src["server"], src["date"], val["item_id1"], val["item_id2"], val["team"],
                                val["container"], json.dumps(val["location"])))
                elif kind == "other":
                    c["other_items"] += 1
                else:
                    c["pods_failed"] += 1
                    errors[f"pod: {val}"[:120]] += 1
            db.execute("INSERT INTO dumps VALUES (?,?,?,?,?,?,?)",
                       (source_name(folder), src["server"], src["date"], src["map"], c["live"], c["pods"],
                        c["live_failed"] + c["pods_failed"]))
            db.commit()
            totals.update(c)
            report.append(f"  {source_name(folder)}: server={src['server']!r} date={src['date']} map={src['map']} "
                          f"live={c['live']} pods={c['pods']} skiffs={c['skiffs']} "
                          f"failed={c['live_failed'] + c['pods_failed']} beyond_bin={c['pods_beyond_bin']} "
                          f"({time.time() - t0:.1f}s){'' if src['complete'] else '  [no run.json: dump may be incomplete]'}")
            print(report[-1], flush=True)
    finally:
        if pool:
            pool.shutdown()
    return db, totals, errors


def finalize(db, out: Path, args, report: list):
    """Second pass: stats/ancestry tables, children, sightings, files."""
    db.executescript(INDEXES)
    cur = db.cursor()
    write_files = not args.no_files
    dino_dir = out / "dinos"
    if dino_dir.exists():
        shutil.rmtree(dino_dir)

    counts = Counter()
    flags = Counter()
    origins = Counter()
    ids = set(r[0] for r in db.execute("SELECT id64 FROM dinos"))

    master = gzip.open(out / "master.jsonl.gz", "wt", encoding="utf-8")
    reader = db.cursor()
    reader.execute("SELECT id64, record FROM dinos ORDER BY origin_server, species, id64")
    n_rows = 0
    for id_, rec_json in reader:
        n_rows += 1
        rec = json.loads(rec_json)
        kids = cur.execute("SELECT id64, name, species FROM dinos WHERE mother_id=? OR father_id=?",
                           (id_, id_)).fetchall()
        rec["children"] = [{"id64": k[0], "name": k[1], "species": k[2]} for k in kids]
        sights = cur.execute("SELECT server, date, map, place, container, location, tribe, name FROM sightings "
                             "WHERE id64=? ORDER BY date, dump", (id_,)).fetchall()
        rec["seen_in"] = [{"server": s[0], "date": s[1], "map": s[2], "where": s[3], "container": s[4],
                           "location": json.loads(s[5]) if s[5] else None, "tribe_then": s[6], "name_then": s[7]}
                          for s in sights]
        for line in ("maternal_line", "paternal_line"):
            for e in rec["ancestry"][line]:
                for side in ("male", "female"):
                    e[side]["in_dataset"] = e[side]["id64"] in ids
        for sname, s in rec["stats"].items():
            cur.execute("INSERT INTO stats VALUES (?,?,?,?,?)", (id_, sname, s["wild"], s["tamed"], s["value"]))
        for line, key in (("maternal", "maternal_line"), ("paternal", "paternal_line")):
            for e in rec["ancestry"][key]:
                cur.execute("INSERT INTO ancestry VALUES (?,?,?,?,?,?,?,?,?)",
                            (id_, line, e["gen"], e["male"]["id64"], e["male"]["name"], e["male"]["level"],
                             e["female"]["id64"], e["female"]["name"], e["female"]["level"]))
        cur.execute("INSERT INTO records VALUES (?,?)", (id_, json.dumps(rec, ensure_ascii=False)))
        if n_rows % 100000 == 0:
            print(f"  finalized {n_rows} dinos", flush=True)

        counts[rec["category"]] += 1
        flags.update(rec["flags"])
        origins[rec["origin"]["tamed_on_server"] or UNKNOWN] += 1
        text = json.dumps(rec, ensure_ascii=False)
        master.write(text + "\n")
        if write_files:
            d = dino_dir / safe_part(rec["origin"]["tamed_on_server"]) / safe_part(rec["species"] or rec["category"]) / id_[-args.bucket_digits:].zfill(args.bucket_digits)
            d.mkdir(parents=True, exist_ok=True)
            (d / f"{id_}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=args.indent), encoding="utf-8")
    master.close()
    db.commit()

    # ghosts: ancestors never seen as a dino of their own
    ghosts = {}
    for row in db.execute("SELECT id64, male_id, male_name, male_level, female_id, female_name, female_level FROM ancestry"):
        child = row[0]
        for gid, gname, glvl, sex in ((row[1], row[2], row[3], "M"), (row[4], row[5], row[6], "F")):
            if gid and gid not in ids:
                g = ghosts.setdefault(gid, {"id64": gid, "sex": sex, "names": set(), "levels": set(), "ancestor_of": 0})
                if gname:
                    g["names"].add(gname)
                if glvl is not None:
                    g["levels"].add(glvl)
                g["ancestor_of"] += 1
    with gzip.open(out / "ghosts.jsonl.gz", "wt", encoding="utf-8") as f:
        for g in ghosts.values():
            g["names"], g["levels"] = sorted(g["names"]), sorted(g["levels"])
            f.write(json.dumps(g, ensure_ascii=False) + "\n")

    with open(out / "skiffs.jsonl", "w", encoding="utf-8") as f:
        for r in db.execute("SELECT server, date, item_id1, item_id2, team, container, location FROM skiffs"):
            f.write(json.dumps({"server": r[0], "date": r[1], "item_id1": r[2], "item_id2": r[3], "team": r[4],
                                "container": r[5], "location": json.loads(r[6]) if r[6] else None}) + "\n")

    multi = db.execute("SELECT COUNT(*) FROM (SELECT id64 FROM sightings GROUP BY id64 HAVING COUNT(*) > 1)").fetchone()[0]
    # the staged copy isn't needed once the final records exist
    db.execute("UPDATE dinos SET record=NULL")
    db.commit()
    db.execute("VACUUM")
    report += ["", f"Unique dinos: {n_rows}   (seen in more than one save: {multi})",
               f"Ghost ancestors: {len(ghosts)}",
               "By category: " + ", ".join(f"{k} {v}" for k, v in counts.most_common()),
               "Flags: " + (", ".join(f"{k} {v}" for k, v in flags.most_common()) or "none"),
               "", "Top origin servers:"]
    report += [f"  {v:>8}  {k}" for k, v in origins.most_common(25)]
    species = Counter(r[0] for r in db.execute("SELECT species FROM dinos"))
    report += ["", "Top species:"] + [f"  {v:>8}  {k}" for k, v in species.most_common(25)]


def main(argv=None):
    ap = argparse.ArgumentParser(prog="ase build",
                                 description="Build the dino dataset from plugin dump folders and/or .extract.zip files.")
    workers = cfg("WORKERS", None) or max(1, (os.cpu_count() or 2) - 1)
    ap.add_argument("folders", nargs="*",
                    help="dump folders or .extract.zip files (default: everything under DUMPS_DIR in the config)")
    ap.add_argument("--scan", help="a folder containing many dump folders and/or extracts (default: DUMPS_DIR)")
    ap.add_argument("-o", "--out", default=os.path.expanduser(cfg("OUT_DIR", "dinodump_out")))
    ap.add_argument("--server", help="origin server name for the save (single dump)")
    ap.add_argument("--date", help="save date YYYY-MM-DD (single dump)")
    ap.add_argument("--anonymize", action="store_true", default=cfg("ANONYMIZE_PLAYERS", False),
                    help="replace player names and IDs with stand-ins")
    ap.add_argument("--anonymize-tribes", action="store_true", default=cfg("ANONYMIZE_TRIBES", False),
                    help="replace tribe names with stand-ins")
    ap.add_argument("--no-files", action="store_true", default=not cfg("WRITE_DINO_FILES", True),
                    help="skip writing one file per dino")
    ap.add_argument("--workers", type=int, default=workers, help="pod decoding processes")
    args = ap.parse_args(argv)
    args.indent = cfg("DINO_FILE_INDENT", 1)
    args.bucket_digits = max(1, int(cfg("BUCKET_DIGITS", 2)))
    if not args.folders and not args.scan:
        args.scan = os.path.expanduser(cfg("DUMPS_DIR", "")) or None

    folders = [Path(f) for f in args.folders]
    if args.scan:
        folders += sorted(p.parent for p in Path(args.scan).rglob("pods.jsonl"))
        folders += sorted(p.parent for p in Path(args.scan).rglob("dinos.jsonl") if p.parent not in folders)
        folders += sorted(Path(args.scan).rglob("*.extract.zip"))
    folders = [f for i, f in enumerate(folders) if (f.is_dir() or is_extract(f)) and f not in folders[:i]]
    if not folders:
        sys.exit("No dumps given (folders containing dinos.jsonl / pods.jsonl, or .extract.zip files).")
    if (args.server or args.date) and len(folders) > 1:
        sys.exit("--server/--date only make sense with one dump folder; use source.json files for many.")

    # oldest saves first, so newer copies of a dino win
    folders.sort(key=lambda f: (source_of(f, None, None)["date"] or "", source_name(f)))

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    report = [f"DinoDump build — {time.strftime('%Y-%m-%d %H:%M:%S')}", "", "Dumps:"]
    t0 = time.time()
    db, totals, errors = ingest(folders, out, args, report)
    finalize(db, out, args, report)
    db.close()
    report.insert(3, f"Total: live {totals['live']}, pods {totals['pods']}, skiffs {totals['skiffs']}, "
                     f"failed {totals['live_failed'] + totals['pods_failed']}, "
                     f"pods past end of pods.bin {totals['pods_beyond_bin']}, in {time.time() - t0:.1f}s")
    if errors:
        report += ["", "Errors (most common):"] + [f"  {v:>6}  {k}" for k, v in errors.most_common(20)]
    (out / "report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    print("\n".join(r for r in report if r.startswith(("Total:", "Unique dinos", "Ghost", "By category", "Flags"))))
    print(f"\nDone. Output in {out.resolve()}  (full summary in report.txt)")


if __name__ == "__main__":
    main()
