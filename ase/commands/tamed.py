"""ase tamed: the arkextract.py command, unchanged behavior and output."""
import json
import multiprocessing as mp
import time
import zipfile
from pathlib import Path

from ..compare import compare
from ..extract import EXTRACTOR, extract_map
from ..saves import find_saves

NAME = "tamed"
ALIASES = ["extract"]
GROUP = "Extract"
HELP = "Tamed dinos, cryopods, eggs and pregnancies -> <save>.extract.zip (was arkextract.py)"


def add_arguments(ap):
    ap.add_argument("saves", nargs="+", help=".ark files, official save .zips, or folders of them")
    ap.add_argument("--out", default="extracts", help="where extracts go (default: ./extracts)")
    ap.add_argument("--jobs", type=int, default=4,
                    help="maps processed at once (default 4; each needs roughly 2x the .ark size in RAM)")
    ap.add_argument("--compare", metavar="DUMP", help="a DinoDump zip/folder to check the first map against")


def run(args):
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    saves = find_saves(args.saves)
    todo, redo = [], 0
    for s in saves:
        ex = out_dir / f"{s.stem}.extract.zip"
        if not ex.exists():
            todo.append(s)
            continue
        try:
            with zipfile.ZipFile(ex) as z:
                meta = json.loads(z.read("meta.json"))
            current = meta.get("extractor") == EXTRACTOR
        except Exception:
            current = False
        if not current:
            todo.append(s)
            redo += 1
    skipped = len(saves) - len(todo)
    print(f"{len(saves)} save(s), {skipped} already extracted, {len(todo)} to do "
          f"({redo} redone: made by an older version) -> {out_dir}")
    t0 = time.time()
    if len(todo) <= 1 or args.jobs <= 1:
        for s in todo:
            print(extract_map((s, out_dir, True)), flush=True)
    else:
        with mp.Pool(min(args.jobs, len(todo))) as pool:
            for line in pool.imap_unordered(extract_map, [(s, out_dir, False) for s in todo]):
                print(line, flush=True)
    print(f"done in {time.time() - t0:.0f}s")
    if args.compare and saves:
        compare(out_dir / f"{saves[0].stem}.extract.zip", args.compare)
