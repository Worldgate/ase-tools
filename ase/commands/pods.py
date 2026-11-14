"""ase pods: decode every cryopodded dino in extracts into full records."""
import json
from collections import Counter
from pathlib import Path

from .. import build

GROUP = "Creatures"
HELP = "Decode the dinos inside cryopods in .extract.zip files -> full records"


def add_arguments(ap):
    ap.add_argument("extracts", nargs="+", help=".extract.zip files or folders of them")
    ap.add_argument("--out", default="pods", help="output folder (default: ./pods)")


def run(args):
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    srcs = []
    for a in args.extracts:
        p = Path(a)
        srcs += sorted(p.rglob("*.extract.zip")) if p.is_dir() else [p]
    for src in srcs:
        name = build.source_name(src)
        stats, kinds, errors = Counter(), Counter(), Counter()
        path = out / f"{name}.pod_dinos.jsonl"
        with open(path, "w", encoding="utf-8") as f:
            for job in build.iter_pod_jobs(src, stats):
                kind, val, where = build.decode_pod_line(job)
                kinds[kind] += 1
                if kind == "dino":
                    val["found"] = where
                    f.write(json.dumps(val, ensure_ascii=False) + "\n")
                elif kind == "error":
                    errors[str(val)[:100]] += 1
        print(f"{name}: {kinds['dino']:,} podded dinos, {kinds['skiff']:,} skiffs, "
              f"{kinds['other']:,} other items, {kinds['error']:,} failed -> {path}")
        for msg, n in errors.most_common(5):
            print(f"    {n:>6,}  {msg}")
