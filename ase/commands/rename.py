"""ase rename: give downloaded official saves readable names.

    nitradoeu250.newofficialtheisland1.zip  ->  EU-PVP-Official-TheIsland1 (2023-08-30).zip

The list is the download page's links, pasted into a text file as-is:
    <a href="https://arkfiles.com/pc/2023-08-30/nitradoeu250.newofficialtheisland1.zip">EU-PVP-Official-TheIsland1</a><br>
The server name comes from the link text, the date from the link's folder.

Dry run by default: prints what it would do. Add --go to do it.
Never overwrites. Writes rename_log.csv in DEST so every name can be put back (ase rename --undo DEST --go).
"""
import csv
import datetime
import html
import re
import shutil
import zipfile
from collections import defaultdict
from pathlib import Path

GROUP = "Tools"
HELP = "Rename downloaded saves (nitradoeu250...zip) to 'Server (date).zip' from the download list"

LINK_RE = re.compile(r'href\s*=\s*"([^"]+)"[^>]*>\s*([^<]+?)\s*</a>', re.I)
DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
BROWSER_COPY_RE = re.compile(r"^(.*?)(?: \(\d+\))?(\.zip)$", re.I)  # "x (1).zip" -> "x.zip"
BAD_CHARS = re.compile(r'[<>:"/\\|?*]')


def add_arguments(ap):
    ap.add_argument("source", nargs="?", help="folder with the downloaded zips (subfolders are searched too)")
    ap.add_argument("listfile", nargs="?", help="text file with the download links pasted in")
    ap.add_argument("dest", nargs="?", help="folder the renamed zips go to")
    ap.add_argument("--go", action="store_true", help="actually do it (default: dry run)")
    ap.add_argument("--copy", action="store_true", help="copy instead of move (keeps the originals)")
    ap.add_argument("--undo", metavar="DEST", help="put files back using DEST/rename_log.csv (dry run unless --go)")


def parse_list(path):
    """{file name (lowercase): [(server, date), ...]}"""
    text = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    out = defaultdict(list)
    for url, label in LINK_RE.findall(text):
        url, label = html.unescape(url), html.unescape(label).strip()
        fname = url.rstrip("/").rsplit("/", 1)[-1]
        m = DATE_RE.search(url)
        entry = (label, m.group(1) if m else None)
        if entry not in out[fname.lower()]:
            out[fname.lower()].append(entry)
    return out


def ark_date(path):
    """Date of the .ark inside the zip (when the server last saved it)."""
    try:
        with zipfile.ZipFile(path) as z:
            ark = next((i for i in z.infolist() if i.filename.lower().endswith(".ark")), None)
            if ark:
                return datetime.date(*ark.date_time[:3])
    except (zipfile.BadZipFile, OSError, ValueError):
        pass
    return None


def pick(entries, path):
    """Choose (server, date) when the same file name was downloaded for several months."""
    if len(entries) == 1:
        return entries[0], None
    # a date in the folder path wins (e.g. downloads kept in ...\2023-08-30\)
    for part in reversed(path.parts[:-1]):
        m = DATE_RE.search(part)
        if m:
            hit = [e for e in entries if e[1] == m.group(1)]
            if len(hit) == 1:
                return hit[0], None
    # otherwise the month the .ark was saved closest before
    d = ark_date(path)
    dated = [e for e in entries if e[1]]
    if d and dated:
        best = min(dated, key=lambda e: abs((datetime.date.fromisoformat(e[1]) - d).days))
        return best, f"picked by save date {d} from {len(entries)} months"
    return None, f"in the list {len(entries)} times ({', '.join(e[1] or '?' for e in entries)}), can't tell which"


def target_name(dest, server, date, taken):
    base = BAD_CHARS.sub("_", server)
    name = f"{base} ({date}).zip" if date else f"{base}.zip"
    n = 2
    while name.lower() in taken or (dest / name).exists():
        name = f"{base} ({date}-{n}).zip" if date else f"{base}-{n}.zip"
        n += 1
    taken.add(name.lower())
    return name


def run(args):
    if args.undo:
        return undo(Path(args.undo), args.go)
    if not (args.source and args.listfile and args.dest):
        print("usage: ase rename SOURCE LISTFILE DEST [--go] [--copy]   or   ase rename --undo DEST [--go]")
        return 2
    dest = Path(args.dest)
    names = parse_list(args.listfile)
    if not names:
        print("No links found in the list file. Paste the <a href=...>Server</a> lines in as-is.")
        return 1
    src = Path(args.source)
    zips = sorted(p for p in src.rglob("*") if p.is_file() and p.suffix.lower() == ".zip"
                  and dest.resolve() not in p.resolve().parents)
    plan, skipped, taken = [], [], set()
    for p in zips:
        key = BROWSER_COPY_RE.sub(r"\1\2", p.name).lower()
        entries = names.get(key)
        if not entries:
            skipped.append((p, "not in the list"))
            continue
        choice, note = pick(entries, p)
        if choice is None:
            skipped.append((p, note))
            continue
        server, date = choice
        if not date:
            d = ark_date(p)
            date = d.isoformat() if d else None
            note = f"no date in link, used save date {date}" if date else "no date anywhere"
        new = target_name(dest, server, date, taken)
        plan.append((p, dest / new, note))

    mode = "copy" if args.copy else "move"
    print(f"{len(names):,} files in the list, {len(zips):,} zips found, "
          f"{len(plan):,} to {mode}, {len(skipped):,} skipped\n")
    for old, new, note in plan:
        print(f"  {old.name}  ->  {new.name}{f'   ({note})' if note else ''}")
    if skipped:
        print("\nSkipped:")
        for p, why in skipped:
            print(f"  {p.name}: {why}")
    if not args.go:
        print(f"\nDry run, nothing changed. Add --go to {mode} the files.")
        return 0

    dest.mkdir(parents=True, exist_ok=True)
    log = dest / "rename_log.csv"
    new_log = not log.exists()
    with open(log, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new_log:
            w.writerow(["original", "renamed", "mode"])
        for old, new, _ in plan:
            if new.exists():  # appeared since planning; never overwrite
                print(f"  exists, skipped: {new.name}")
                continue
            if args.copy:
                shutil.copy2(old, new)
            else:
                shutil.move(str(old), str(new))
            w.writerow([str(old.resolve()), str(new.resolve()), mode])
            f.flush()
    print(f"\nDone. {len(plan):,} files -> {dest}   (log: {log}; undo with --undo)")
    return 0


def undo(dest, go):
    log = dest / "rename_log.csv"
    if not log.exists():
        print(f"No {log} to undo from.")
        return 1
    with open(log, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    todo = [r for r in rows if Path(r["renamed"]).exists()]
    for r in todo:
        action = "delete copy" if r["mode"] == "copy" else "move back"
        print(f"  {Path(r['renamed']).name}  ->  {action}: {r['original']}")
    if not go:
        print(f"\nDry run: {len(todo):,} files would be put back. Add --go to do it.")
        return 0
    for r in todo:
        new, old = Path(r["renamed"]), Path(r["original"])
        if r["mode"] == "copy":
            if old.exists():
                new.unlink()
            continue
        if old.exists():
            print(f"  original name taken, left alone: {new.name}")
            continue
        old.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(new), str(old))
    log.rename(log.with_suffix(".undone.csv"))
    print(f"Put back {len(todo):,} files.")
    return 0
