"""Shared by `creatures`, `wild` (and tamed-only listing): JSON lines + per-class statistics."""
import collections
import json
from pathlib import Path

from ..core.props import clean_json
from ..model.creatures import iter_creatures
from ..saves import find_saves, open_save


def add_arguments(ap):
    ap.add_argument("saves", nargs="+", help=".ark files, official save .zips, or folders of them")
    ap.add_argument("--out", default="creatures", help="output folder (default: ./creatures)")


def run_list(args, want, suffix):
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for src in find_saves(args.saves):
        save, map_name, save_name = open_save(src)
        errors = []
        stats = collections.defaultdict(lambda: {"count": 0, "tamed": 0, "min": None, "max": None, "sum": 0})
        path = out / f"{save_name}.{suffix}.jsonl"
        with open(path, "w", encoding="utf-8") as f:
            for rec in iter_creatures(save, want, map_name, save_name, errors):
                f.write(json.dumps(clean_json(rec), ensure_ascii=False) + "\n")
                s = stats[rec["class"].rsplit(".", 1)[-1]]
                lvl = rec["level"]
                s["count"] += 1
                s["tamed"] += rec["tamed"]
                s["sum"] += lvl
                s["min"] = lvl if s["min"] is None else min(s["min"], lvl)
                s["max"] = lvl if s["max"] is None else max(s["max"], lvl)
        summary = {cls: {"count": s["count"], "tamed": s["tamed"], "level_min": s["min"],
                         "level_max": s["max"], "level_avg": round(s["sum"] / s["count"], 1)}
                   for cls, s in sorted(stats.items(), key=lambda kv: -kv[1]["count"])}
        (out / f"{save_name}.{suffix}.classes.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
        total = sum(s["count"] for s in stats.values())
        print(f"{save_name}: {total:,} {suffix} creatures in {len(stats):,} classes"
              f"{f', {len(errors)} errors' if errors else ''} -> {path}")
