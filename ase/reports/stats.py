r"""
arkstats.py - server lifespan and activity stats across every extract, for posting.

Usage:  python arkstats.py [extracts folder]
Writes  server_stats.csv  (one row per save) next to the extracts folder and prints summaries:
  - lifespan (game_time in days) per map, PvP vs PvE, region
  - pods, tames, eggs, pregnancies, and per-day rates
  - top 10 lists
Reads only meta.json from each extract, so it is quick. Standard library only.

Note: game_time is how long the server's world was running (in seconds), so it is
"days the server was up", which is close to but not exactly calendar days.
"""

import csv
import json
import re
import statistics
import sys
import zipfile
from collections import defaultdict
from pathlib import Path


def parse_name(save):
    """'EU-PVP-Official-Valguero544 (2023-09-30)' -> region, mode, map label, server number."""
    s = save.upper()
    region = next((r for r in ("NA", "EU", "OC", "ASIA", "SA") if s.startswith(r + "-")
                   or f"-{r}-" in s), "?")
    mode = "PvP" if "PVP" in s else "PvE" if "PVE" in s else "?"
    legacy = "LEGACY" in s
    m = re.search(r"Official-([A-Za-z]+?)(\d+)", save) or re.search(r"-([A-Za-z]+?)(\d*)[ _(]", save)
    label, num = (m.group(1), m.group(2)) if m else ("?", "")
    return region, mode, legacy, label, num


def main():
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd() / "extracts"
    rows = []
    for f in sorted(folder.rglob("*.extract.zip")):
        try:
            with zipfile.ZipFile(f) as z:
                m = json.loads(z.read("meta.json"))
        except Exception:
            continue
        region, mode, legacy, label, num = parse_name(m["save"])
        days = (m.get("game_time") or 0) / 86400
        pods = m.get("cryopods", 0)
        tamed = m.get("tamed_world_dinos", 0)
        rows.append({
            "save": m["save"], "map": m.get("map", ""), "label": label, "server": num,
            "region": region, "mode": mode, "legacy": legacy,
            "days_up": round(days, 1), "save_count": m.get("save_count", 0),
            "objects": m.get("objects", 0), "tamed_world": tamed, "pods": pods,
            "all_dinos": pods + tamed, "eggs": m.get("fertilized_eggs", 0),
            "pregnant_flag": m.get("pregnant", 0), "babies": m.get("babies", 0),
            "pod_gb": round(m.get("pod_bytes", 0) / 1_073_741_824, 2),
            "dinos_per_day": round((pods + tamed) / days, 1) if days > 1 else 0,
            "objects_per_day": round(m.get("objects", 0) / days) if days > 1 else 0,
        })
    if not rows:
        print(f"no extracts in {folder}")
        return

    out = folder.parent / "server_stats.csv"
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    def summary(title, key):
        groups = defaultdict(list)
        for r in rows:
            groups[key(r)].append(r)
        print(f"\n== {title}")
        print(f"{'':<22}{'servers':>8}{'avg days':>10}{'max days':>10}{'avg dinos':>11}"
              f"{'dinos/day':>11}{'total dinos':>14}")
        for g, rs in sorted(groups.items(), key=lambda kv: -sum(r["all_dinos"] for r in kv[1])):
            d = [r["days_up"] for r in rs]
            dinos = [r["all_dinos"] for r in rs]
            rate = [r["dinos_per_day"] for r in rs if r["dinos_per_day"]]
            print(f"{str(g):<22}{len(rs):>8}{statistics.mean(d):>10.0f}{max(d):>10.0f}"
                  f"{statistics.mean(dinos):>11,.0f}{(statistics.mean(rate) if rate else 0):>11.0f}"
                  f"{sum(dinos):>14,}")

    def top(title, field, n=10, fmt="{:,}"):
        print(f"\n== Top {n}: {title}")
        for i, r in enumerate(sorted(rows, key=lambda r: r[field], reverse=True)[:n], 1):
            print(f"{i:>3}. {fmt.format(r[field]):>12}  {r['save']}")

    print(f"{len(rows)} servers.  Total dinos: {sum(r['all_dinos'] for r in rows):,} "
          f"({sum(r['pods'] for r in rows):,} in pods, {sum(r['tamed_world'] for r in rows):,} out in the world)"
          f"   Eggs: {sum(r['eggs'] for r in rows):,}")
    summary("PvP vs PvE", lambda r: r["mode"] + (" (legacy)" if r["legacy"] else ""))
    summary("By map", lambda r: r["map"])
    summary("By region", lambda r: r["region"])
    top("most dinos (pods + world)", "all_dinos")
    top("longest running (days up)", "days_up", fmt="{:,.0f} d")
    top("fastest filling (dinos per day)", "dinos_per_day", fmt="{:,.0f}/d")
    top("most fertilized eggs at shutdown", "eggs")
    top("most objects (bases, items, everything)", "objects")
    print(f"\nFull table: {out}")


if __name__ == "__main__":
    main()
