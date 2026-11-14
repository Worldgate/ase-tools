"""
dumpzip.py - package DinoDump output to match each server's source save.

For every C:\asmdata\Servers\Server*:
  1. Reads the one .zip in ShooterGame\Saved\SavedArks (the official save it came from)
  2. Takes the newest folder in ...\ArkApi\Plugins\DinoDump\dumps
  3. Zips that folder's CONTENTS to C:\asmdata\OfficialDinoDumps\<same name>.zip
  4. Verifies the zip, then deletes the dump folder

Skips (and keeps the dump) if: no/multiple source zips, no dump folder,
or the output zip already exists. Standard library only - no pip installs.
"""

import re
import shutil
import sys
import zipfile
from pathlib import Path

# ---- settings -------------------------------------------------------------
SERVERS_DIR = Path(r"C:\asmdata\Servers")
OUT_DIR = Path(r"C:\asmdata\OfficialDinoDumps")
SAVEDARKS = Path(r"ShooterGame\Saved\SavedArks")
DUMPS = Path(r"ShooterGame\Binaries\Win64\ArkApi\Plugins\DinoDump\dumps")
# ---------------------------------------------------------------------------


def server_sort_key(p: Path):
    m = re.search(r"(\d+)$", p.name)
    return (int(m.group(1)) if m else 0, p.name)


def process(server: Path):
    # 1. source save zip
    saved = server / SAVEDARKS
    zips = sorted(saved.glob("*.zip")) if saved.is_dir() else []
    if not zips:
        return "SKIP", "no .zip in SavedArks"
    if len(zips) > 1:
        return "SKIP", f"{len(zips)} zips in SavedArks, expected 1"
    src_zip = zips[0]

    # 2. newest dump folder (any map name)
    dumps = server / DUMPS
    folders = [d for d in dumps.iterdir() if d.is_dir()] if dumps.is_dir() else []
    if not folders:
        return "SKIP", "no dump folder"
    dump = max(folders, key=lambda d: d.stat().st_mtime)

    # 3. output
    out = OUT_DIR / src_zip.name
    if out.exists():
        return "SKIP", f"'{out.name}' already exists (kept {dump.name})"

    files = [f for f in dump.rglob("*") if f.is_file()]
    if not files:
        return "SKIP", f"{dump.name} is empty"

    tmp = out.with_name(out.name + ".partial")
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for f in files:
                z.write(f, f.relative_to(dump))  # contents at zip root

        # 4. verify before deleting anything
        with zipfile.ZipFile(tmp) as z:
            bad = z.testzip()
            count = len(z.namelist())
        if bad is not None:
            raise RuntimeError(f"corrupt entry in zip: {bad}")
        if count != len(files):
            raise RuntimeError(f"zip has {count} files, folder has {len(files)}")

        tmp.rename(out)
    except Exception as e:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        return "ERROR", f"{dump.name}: {e} (dump kept)"

    try:
        shutil.rmtree(dump)
    except Exception as e:
        return "OK", f"{dump.name} -> {out.name} ({len(files)} files) BUT delete failed: {e}"

    size_mb = out.stat().st_size / 1_048_576
    return "OK", f"{dump.name} -> {out.name} ({len(files)} files, {size_mb:.1f} MB)"


def main():
    if not SERVERS_DIR.is_dir():
        print(f"Servers folder not found: {SERVERS_DIR}")
        return
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    servers = sorted(
        (d for d in SERVERS_DIR.iterdir() if d.is_dir() and d.name.lower().startswith("server")),
        key=server_sort_key,
    )

    results = {"OK": 0, "SKIP": 0, "ERROR": 0}
    for server in servers:
        print(f"{server.name}: working...", end="\r", flush=True)
        status, msg = process(server)
        results[status] += 1
        print(f"{server.name:<10} {status:<5} {msg}")

    print()
    print(f"Done: {results['OK']} zipped, {results['SKIP']} skipped, {results['ERROR']} errors")
    print(f"Output: {OUT_DIR}")


if __name__ == "__main__":
    try:
        main()
    finally:
        if sys.stdin and sys.stdin.isatty():
            input("\nPress Enter to close...")
