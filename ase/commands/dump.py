"""ase dump: every object of a class, fully decoded, as JSON lines (ark-tools `dump`)."""
import json
import sys

from ..core.props import clean_json, props_to_dict
from ..saves import open_save

GROUP = "Debug"
HELP = "Every object of a class, fully decoded, as JSON lines (ark-tools: dump)"


def add_arguments(ap):
    ap.add_argument("save", help=".ark or official save .zip")
    ap.add_argument("cls", metavar="CLASS", help="class name, e.g. Raptor_Character_BP_C")
    ap.add_argument("out", nargs="?", help="file to write (default: print)")
    ap.add_argument("--contains", action="store_true", help="match every class containing CLASS")
    ap.add_argument("--limit", type=int, help="stop after N objects")


def object_record(save, idx):
    cls, loc, _ = save.objects[idx]
    rec = {"index": idx, "class": cls, "location": list(loc) if loc else None}
    try:
        rec["properties"] = props_to_dict(save.prop_block(idx)[1])
    except Exception as e:
        rec["error"] = f"{type(e).__name__}: {e}"
    return clean_json(rec)


def write_objects(save, indices, out, limit=None):
    f = open(out, "w", encoding="utf-8") if out else sys.stdout
    n = 0
    try:
        for idx in indices:
            f.write(json.dumps(object_record(save, idx), ensure_ascii=False, default=str) + "\n")
            n += 1
            if limit and n >= limit:
                break
    finally:
        if out:
            f.close()
    return n


def run(args):
    save, _, _ = open_save(args.save)
    want = args.cls
    hits = [i for i, (c, _, _) in enumerate(save.objects)
            if (want in c if args.contains else c == want)]
    n = write_objects(save, hits, args.out, args.limit)
    if args.out:
        print(f"{n:,} objects -> {args.out}")
