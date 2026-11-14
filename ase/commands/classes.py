"""ase classes: every class in the save with its object count (ark-tools `classes`)."""
import collections
import csv
import sys

from ..saves import open_save

GROUP = "Debug"
HELP = "Every class in a save with object counts (ark-tools: classes)"


def add_arguments(ap):
    ap.add_argument("save", help=".ark or official save .zip")
    ap.add_argument("out", nargs="?", help="CSV file to write (default: print)")


def run(args):
    save, _, _ = open_save(args.save)
    counts = collections.Counter(c for c, _, _ in save.objects)
    rows = [(cls, n, save.class_paths.get(cls, "")) for cls, n in counts.most_common()]
    if args.out:
        with open(args.out, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["class", "count", "blueprint"])
            w.writerows(rows)
        print(f"{len(rows):,} classes -> {args.out}")
    else:
        w = csv.writer(sys.stdout)
        w.writerow(["class", "count", "blueprint"])
        w.writerows(rows)
