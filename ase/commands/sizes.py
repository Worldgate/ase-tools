"""ase sizes: bytes of property data per class - what makes a save big (ark-tools `sizes`)."""
import collections
import csv
import sys

from ..saves import open_save

GROUP = "Debug"
HELP = "Property bytes per class, biggest first (ark-tools: sizes)"


def add_arguments(ap):
    ap.add_argument("save", help=".ark or official save .zip")
    ap.add_argument("out", nargs="?", help="CSV file to write (default: print)")


def run(args):
    save, _, _ = open_save(args.save)
    # objects' property lists sit back to back; each one ends where the next begins
    order = sorted(range(len(save.objects)), key=lambda i: save.objects[i][2])
    block_end = len(save.data)
    if save.sections:
        starts = [o for o, n in save.sections if n]
        if starts:
            block_end = min(starts)
    total, count = collections.Counter(), collections.Counter()
    for k, i in enumerate(order):
        start = save.objects[i][2]
        end = save.objects[order[k + 1]][2] if k + 1 < len(order) else block_end - save.prop_off
        cls = save.objects[i][0]
        total[cls] += max(0, end - start)
        count[cls] += 1
    rows = [(cls, count[cls], b, round(b / count[cls])) for cls, b in total.most_common()]
    head = ["class", "count", "bytes", "avg_bytes"]
    f = open(args.out, "w", newline="", encoding="utf-8") if args.out else sys.stdout
    w = csv.writer(f)
    w.writerow(head)
    w.writerows(rows)
    if args.out:
        f.close()
        print(f"{len(rows):,} classes, {sum(total.values()):,} bytes -> {args.out}")
