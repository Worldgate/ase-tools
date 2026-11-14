"""ase m2j: the whole map as JSON lines, one object per line (ark-tools `mapToJson`)."""
from ..saves import open_save
from .dump import write_objects

NAME = "m2j"
ALIASES = ["mapToJson"]
GROUP = "Converting"
HELP = "Whole save -> JSON lines, every object fully decoded (ark-tools: m2j)"


def add_arguments(ap):
    ap.add_argument("save", help=".ark or official save .zip")
    ap.add_argument("out", help="output .jsonl file")
    ap.add_argument("--limit", type=int, help="stop after N objects")


def run(args):
    save, _, _ = open_save(args.save)
    n = write_objects(save, range(len(save.objects)), args.out, args.limit)
    print(f"{n:,} objects -> {args.out}")
