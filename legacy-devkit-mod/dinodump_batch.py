#!/usr/bin/env python3
"""
dinodump_batch.py
-----------------
Runs the DinoDump mod across every saved map you have, unattended.

For each .ark save it finds:
  1. copies the save (plus its .arktribe / .arkprofile files) into a
     throwaway work folder the dump server loads from
  2. starts the dedicated server on that map with the DinoDump mod and
     ?DinoDumpAuto=1
  3. watches the server log for the mod's END line, then lets the
     server exit (or kills it)
  4. copies the log to your output folder and records it in manifest.json

It's safe to stop and restart: saves already done are skipped.
Your original saves are only ever read, never written.

Usage:
  python dinodump_batch.py --dry-run     list what it would do, change nothing
  python dinodump_batch.py               run everything
  python dinodump_batch.py --retry-failed
  python dinodump_batch.py --limit 3     only do the next 3 (good for testing)

Then:
  python dinodump_parse.py <OUT_LOGS>

Python 3.8+, standard library only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# ===========================================================================
# CONFIG — edit these
# ===========================================================================

# The dedicated server you'll dump with (a separate install is best).
SERVER_EXE = r"C:\ARKDump\ShooterGame\Binaries\Win64\ShooterGameServer.exe"

# Where all your saved maps live. Searched recursively for *.ark files.
SAVES_ROOT = r"D:\ArkSaves"

# Where logs + manifest.json get collected.
OUT_LOGS = r"D:\DinoDump\logs"

# The folder name the server loads saves from (AltSaveDirectoryName).
ALT_SAVE_NAME = "DinoDump"

# The folder the server actually reads that save from. With
# AltSaveDirectoryName this is normally ShooterGame\Saved\<ALT_SAVE_NAME>.
# If the first test run reports 0 dinos, the server didn't find the save
# here: look for where it created a fresh <Map>.ark and put that folder here.
WORK_SAVE_DIR = r"C:\ARKDump\ShooterGame\Saved\DinoDump"

# The server's log file.
SERVER_LOG = r"C:\ARKDump\ShooterGame\Saved\Logs\ShooterGame.log"

# Your DinoDump mod's ID (the folder number under ShooterGame\Content\Mods).
DUMPER_MOD_ID = "0000000000"

# Mod maps need their own mod loaded too. Map name (the .ark file name)
# -> mod ID(s), comma separated. Official maps don't need an entry.
# Also add any dino mods a save used, or those dinos won't load.
MAP_MODS = {
    # "SomeModMap": "123456789",
}
# Mods to load for EVERY save (e.g. dino mods you always played with).
ALWAYS_MODS = ""

# Auto-backup saves look like TheIsland_10.10.2019_19.53.10.ark.
# There can be hundreds per map; skip them unless you want every snapshot.
INCLUDE_BACKUPS = False

# Give up on a save after this long. Big saves can take 30-40+ minutes just
# to load, so the limit grows with file size:
#   TIMEOUT_BASE_MINUTES + TIMEOUT_MINUTES_PER_GB x (save size in GB)
# e.g. a 9 GB save gets 30 + 10*9 = 120 minutes.
TIMEOUT_BASE_MINUTES = 30
TIMEOUT_MINUTES_PER_GB = 10

# After the END line, wait this long for the server to exit before killing it.
EXIT_GRACE_SECONDS = 90

EXTRA_ARGS = ["-server", "-log", "-servergamelog", "-NoBattlEye"]

# ===========================================================================

BACKUP_RE = re.compile(r"^(.*?)_\d{2}\.\d{2}\.\d{4}_\d{2}\.\d{2}\.\d{2}$")
END_MARK = b"DINODUMP|END|"


def log(msg: str):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def map_name_of(ark: Path) -> tuple[str, bool]:
    m = BACKUP_RE.match(ark.stem)
    return (m.group(1), True) if m else (ark.stem, False)


def key_of(ark: Path) -> str:
    st = ark.stat()
    return f"{ark.resolve()}|{st.st_size}|{int(st.st_mtime)}"


def find_saves(root: Path, skip_dirs: list[Path]) -> list[Path]:
    saves = []
    skip = [d.resolve() for d in skip_dirs]
    for p in root.rglob("*.ark"):
        try:
            rp = p.resolve()
        except OSError:
            continue
        if any(s == rp or s in rp.parents for s in skip):
            continue
        if not p.is_file() or p.stat().st_size < 1024:
            continue
        _, is_backup = map_name_of(p)
        if is_backup and not INCLUDE_BACKUPS:
            continue
        saves.append(p)
    return sorted(saves)


def load_manifest(path: Path) -> dict:
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            bak = path.with_suffix(".broken.json")
            shutil.copy2(path, bak)
            log(f"manifest was unreadable; saved a copy as {bak.name} and starting fresh")
    return {"runs": []}


def save_manifest(path: Path, data: dict):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def prepare_work_dir(ark: Path, map_name: str):
    work = Path(WORK_SAVE_DIR)
    if work.name != ALT_SAVE_NAME:
        sys.exit(f"Safety stop: WORK_SAVE_DIR must end in '{ALT_SAVE_NAME}' (it gets wiped each run).")
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    shutil.copy2(ark, work / f"{map_name}.ark")
    for pattern in ("*.arktribe", "*.arkprofile"):
        for f in ark.parent.glob(pattern):
            shutil.copy2(f, work / f.name)


def build_command(map_name: str) -> list[str]:
    mods = [m for m in [DUMPER_MOD_ID, ALWAYS_MODS, MAP_MODS.get(map_name, "")] if m]
    url = (
        f"{map_name}?listen?SessionName=DinoDump?MaxPlayers=1"
        f"?AltSaveDirectoryName={ALT_SAVE_NAME}"
        f"?ServerAdminPassword=dinodump"
        f"?AutoSavePeriodMinutes=9999"
        f"?GameModIds={','.join(mods)}"
        f"?DinoDumpAuto=1"
    )
    return [SERVER_EXE, url] + EXTRA_ARGS


def run_one(ark: Path, map_name: str, out_logs: Path, n: int) -> dict:
    prepare_work_dir(ark, map_name)
    server_log = Path(SERVER_LOG)
    if server_log.exists():
        try:
            server_log.unlink()
        except OSError:
            log("couldn't delete old server log (is a server still running?)")

    cmd = build_command(map_name)
    timeout_min = TIMEOUT_BASE_MINUTES + TIMEOUT_MINUTES_PER_GB * ark.stat().st_size / 1e9
    log(f"  timeout for this save: {timeout_min:.0f} min")
    started = time.time()
    proc = subprocess.Popen(cmd, cwd=str(Path(SERVER_EXE).parent),
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    status, saw_end, end_time, pos = "timeout", False, None, 0

    while True:
        time.sleep(5)
        if server_log.exists():
            try:
                with server_log.open("rb") as f:
                    f.seek(max(0, pos - len(END_MARK)))
                    chunk = f.read()
                    pos = f.tell()
                if END_MARK in chunk and not saw_end:
                    saw_end, end_time = True, time.time()
                    log("  dump finished, waiting for server to exit")
            except OSError:
                pass

        if proc.poll() is not None:
            status = "ok" if saw_end else "exited_early"
            break
        if saw_end and time.time() - end_time > EXIT_GRACE_SECONDS:
            proc.kill()
            proc.wait()
            status = "ok"
            break
        if time.time() - started > timeout_min * 60:
            proc.kill()
            proc.wait()
            status = "timeout"
            break

    time.sleep(2)
    h = hashlib.sha1(str(ark.resolve()).encode()).hexdigest()[:8]
    log_name = f"{n:05d}_{re.sub(r'[^A-Za-z0-9_.-]', '_', map_name)}_{h}.log"
    if server_log.exists():
        shutil.copy2(server_log, out_logs / log_name)
    else:
        log_name = None
        status = "no_log"

    st = ark.stat()
    return {
        "key": key_of(ark),
        "source": str(ark),
        "map": map_name,
        "save_mtime": st.st_mtime,
        "save_size": st.st_size,
        "log": log_name,
        "status": status,
        "seconds": round(time.time() - started),
        "finished": datetime.now().isoformat(timespec="seconds"),
    }


def main():
    ap = argparse.ArgumentParser(description="Run the DinoDump mod across all saved maps.")
    ap.add_argument("--dry-run", action="store_true", help="list what would run, change nothing")
    ap.add_argument("--retry-failed", action="store_true", help="re-run saves that failed before")
    ap.add_argument("--limit", type=int, default=0, help="only run this many saves")
    args = ap.parse_args()

    out_logs = Path(OUT_LOGS)
    man_path = out_logs / "manifest.json"
    manifest = load_manifest(man_path)
    done = {r["key"]: r for r in manifest["runs"]}

    saves = find_saves(Path(SAVES_ROOT), [Path(WORK_SAVE_DIR), out_logs])
    todo = []
    for ark in saves:
        prev = done.get(key_of(ark))
        if prev and (prev["status"] == "ok" or not args.retry_failed):
            continue
        todo.append(ark)
    if args.limit:
        todo = todo[: args.limit]

    total_gb = sum(a.stat().st_size for a in todo) / 1e9
    log(f"found {len(saves)} saves, {len(todo)} to do ({total_gb:.1f} GB)")

    if args.dry_run:
        for ark in todo:
            m, b = map_name_of(ark)
            mods = MAP_MODS.get(m, "")
            log(f"  {m:<20} {'(backup) ' if b else ''}{ark}  {('mods: ' + mods) if mods else ''}")
        return

    if not Path(SERVER_EXE).is_file():
        sys.exit(f"Server not found: {SERVER_EXE}")
    out_logs.mkdir(parents=True, exist_ok=True)

    n = len(manifest["runs"])
    for i, ark in enumerate(todo, 1):
        map_name, _ = map_name_of(ark)
        log(f"[{i}/{len(todo)}] {map_name}  <- {ark}")
        try:
            entry = run_one(ark, map_name, out_logs, n)
        except KeyboardInterrupt:
            log("stopped by you; progress so far is saved")
            break
        except Exception as e:  # keep going on one bad save
            entry = {"key": key_of(ark), "source": str(ark), "map": map_name,
                     "status": f"error: {e}", "log": None,
                     "finished": datetime.now().isoformat(timespec="seconds")}
        n += 1
        manifest["runs"] = [r for r in manifest["runs"] if r["key"] != entry["key"]] + [entry]
        save_manifest(man_path, manifest)
        log(f"  -> {entry['status']}  ({entry.get('seconds', '?')}s)")

    bad = [r for r in manifest["runs"] if r["status"] != "ok"]
    log(f"done. {len(manifest['runs']) - len(bad)} ok, {len(bad)} not ok "
        f"(see manifest.json; rerun with --retry-failed)")


if __name__ == "__main__":
    main()
