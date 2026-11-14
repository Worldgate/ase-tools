#!/usr/bin/env python3
"""
dinodump_batch.py — run DinoDump across your whole save collection, unattended.

For every save zip (e.g. "NA-PVE-Official-TheIsland429 (2023-09-30).zip"):
  1. waits for a free server slot and enough free RAM
  2. unpacks the map save (.ark, plus profile/tribe files) into that slot
  3. starts the server with  -DinoDumpAuto -DinoDumpExit
     -DinoDumpSource="<zip name>"  -DinoDumpOut="<DUMPS_DIR>"
  4. the plugin dumps into DUMPS_DIR\\<zip name>\\ and shuts the server down
  5. checks run.json, records the result, cleans the slot, takes the next zip

The zip's name becomes the dump folder's name, so the builder knows which
official server and date every dino was found on. Nothing to rename by hand.

Safe to stop (Ctrl+C) and restart: finished saves are skipped. Your zips are
only ever read.

Usage (Windows, Python 3.8+, standard library only):
    python dinodump_batch.py --dry-run      show the plan, touch nothing
    python dinodump_batch.py                run it
    python dinodump_batch.py --retry        also redo saves that failed before
    python dinodump_batch.py --limit 3      only start 3 saves (for testing)
    python dinodump_batch.py --slots 1      use only the first N slots

Settings live in batch_config.py next to this file.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import batch_config as C  # noqa: E402

BACKUP_RE = re.compile(r"_\d{2}\.\d{2}\.\d{4}_\d{2}\.\d{2}\.\d{2}$")
GB = 1024 ** 3


def log(msg: str):
    print(f"[{datetime.now().strftime('%m-%d %H:%M:%S')}] {msg}", flush=True)


# ---------------------------------------------------------------------------
# system
# ---------------------------------------------------------------------------

def free_ram_gb():
    """Available physical RAM in GB (Windows). None if it can't be read."""
    if os.name != "nt":
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemAvailable:"):
                        return int(line.split()[1]) / (1024 ** 2)
        except OSError:
            return None
        return None

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
    st = MEMORYSTATUSEX()
    st.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
        return None
    return st.ullAvailPhys / GB


def notify(text: str):
    if not getattr(C, "NTFY_URL", ""):
        return
    try:
        req = urllib.request.Request(C.NTFY_URL, data=text.encode("utf-8"), method="POST",
                                     headers={"Title": "DinoDump batch"})
        urllib.request.urlopen(req, timeout=15).read()
    except Exception as e:  # noqa: BLE001
        log(f"(notification failed: {e})")


# ---------------------------------------------------------------------------
# state (resume-safe)
# ---------------------------------------------------------------------------

class State:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.Lock()
        self.data = {"saves": {}}
        if path.is_file():
            try:
                self.data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                path.rename(path.with_suffix(".broken.json"))
                log("state file was unreadable; kept a copy as .broken.json and started fresh")

    def get(self, label):
        return self.data["saves"].get(label)

    def set(self, label, entry):
        with self.lock:
            self.data["saves"][label] = entry
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, indent=1), encoding="utf-8")
            os.replace(tmp, self.path)


# ---------------------------------------------------------------------------
# jobs
# ---------------------------------------------------------------------------

def peek_zip(z: Path):
    """(map_name, ark_entry, ark_size_bytes, profile_entries) or None."""
    try:
        with zipfile.ZipFile(z) as zf:
            infos = zf.infolist()
    except (zipfile.BadZipFile, OSError):
        return None
    arks = [i for i in infos if i.filename.lower().endswith(".ark") and not i.is_dir()]
    if not arks:
        return None
    main = [i for i in arks if not BACKUP_RE.search(Path(i.filename).stem)] or arks
    best = max(main, key=lambda i: i.file_size)
    map_name = BACKUP_RE.sub("", Path(best.filename).stem)
    profiles = [i.filename for i in infos
                if i.filename.lower().endswith((".arkprofile", ".arktribe")) and not i.is_dir()]
    return map_name, best.filename, best.file_size, profiles


def ram_needed_gb(map_name: str, ark_bytes: int) -> float:
    base = C.MAP_BASE_RAM_GB.get(map_name, C.MAP_BASE_RAM_GB.get("default", 8))
    return base + C.RAM_GB_PER_SAVE_GB * ark_bytes / GB


def build_jobs(state: State, retry: bool):
    zips = sorted(Path(C.ZIPS_DIR).rglob("*.zip"))
    jobs, skipped = [], {"done": 0, "failed_before": 0, "filtered": 0, "no_ark": 0}
    dumps = Path(C.DUMPS_DIR)
    for z in zips:
        label = z.stem
        if any(s.lower() in label.lower() for s in C.SKIP_NAMES):
            skipped["filtered"] += 1
            continue
        prev = state.get(label)
        if (dumps / label / "run.json").is_file() or (prev and prev.get("status") == "ok"):
            skipped["done"] += 1
            continue
        if prev and not retry:
            skipped["failed_before"] += 1
            continue
        info = peek_zip(z)
        if not info:
            skipped["no_ark"] += 1
            state.set(label, {"status": "no_ark_in_zip", "zip": str(z)})
            continue
        map_name, entry, size, profiles = info
        if C.ONLY_MAPS and map_name not in C.ONLY_MAPS:
            skipped["filtered"] += 1
            continue
        jobs.append({"label": label, "zip": z, "map": map_name, "ark_entry": entry,
                     "ark_bytes": size, "profiles": profiles,
                     "ram_gb": ram_needed_gb(map_name, size)})
    if C.ORDER == "size_desc":
        jobs.sort(key=lambda j: -j["ark_bytes"])
    elif C.ORDER == "size_asc":
        jobs.sort(key=lambda j: j["ark_bytes"])
    return jobs, skipped


# ---------------------------------------------------------------------------
# running one save in one slot
# ---------------------------------------------------------------------------

def save_dir(slot) -> Path:
    return Path(slot["server_dir"]) / "ShooterGame" / "Saved" / C.SAVE_SUBDIR


def server_exe(slot) -> Path:
    return Path(slot["server_dir"]) / "ShooterGame" / "Binaries" / "Win64" / "ShooterGameServer.exe"


def server_log(slot) -> Path:
    return Path(slot["server_dir"]) / "ShooterGame" / "Saved" / "Logs" / "ShooterGame.log"


def prepare_slot(slot, job):
    d = save_dir(slot)
    if d.name != C.SAVE_SUBDIR or len(d.parts) < 4:
        raise RuntimeError(f"refusing to wipe unexpected folder {d}")
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    with zipfile.ZipFile(job["zip"]) as zf:
        with zf.open(job["ark_entry"]) as src, open(d / f"{job['map']}.ark", "wb") as dst:
            shutil.copyfileobj(src, dst, length=16 * 1024 * 1024)
        if C.UNPACK_PROFILES:
            for name in job["profiles"]:
                with zf.open(name) as src, open(d / Path(name).name, "wb") as dst:
                    shutil.copyfileobj(src, dst)


def command_line(slot, job) -> str:
    # Built as one string on purpose: the plugin reads -DinoDumpSource="..." verbatim.
    url = (f"{job['map']}?listen?SessionName=DinoDump-{slot['name']}"
           f"?Port={slot['port']}?QueryPort={slot['query_port']}"
           f"?RCONEnabled=True?RCONPort={slot['rcon_port']}?ServerAdminPassword={C.ADMIN_PASSWORD}"
           f"?AltSaveDirectoryName={C.SAVE_SUBDIR}?MaxPlayers=1?AutoSavePeriodMinutes=9999")
    out = str(Path(C.DUMPS_DIR)).rstrip("\\/")
    flags = (f'-DinoDumpAuto -DinoDumpExit -DinoDumpDelay={C.DUMP_DELAY_SECONDS} '
             f'-DinoDumpSource="{job["label"]}" -DinoDumpOut="{out}"')
    if C.INCLUDE_WILD:
        flags += " -DinoDumpWild"
    return f'"{server_exe(slot)}" {url} {C.EXTRA_ARGS} {flags}'


def run_job(slot, job, state: State, stop: threading.Event):
    label = job["label"]
    started = time.time()
    entry = {"zip": str(job["zip"]), "map": job["map"], "ark_gb": round(job["ark_bytes"] / GB, 2),
             "slot": slot["name"], "started": datetime.now().isoformat(timespec="seconds")}
    proc = None
    try:
        log(f"[{slot['name']}] start  {label}  ({job['map']}, {entry['ark_gb']} GB save)")
        prepare_slot(slot, job)
        unpack_s = round(time.time() - started)
        try:
            server_log(slot).unlink()
        except OSError:
            pass
        timeout_s = 60 * (C.TIMEOUT_BASE_MINUTES + C.TIMEOUT_MINUTES_PER_GB * job["ark_bytes"] / GB)
        proc = subprocess.Popen(command_line(slot, job), cwd=str(server_exe(slot).parent),
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        status = None
        while status is None:
            if stop.is_set():
                proc.kill()
                status = "stopped_by_you"
            elif proc.poll() is not None:
                status = "exited"
            elif time.time() - started > timeout_s:
                proc.kill()
                status = "timeout"
            else:
                time.sleep(5)
        proc.wait()

        run_json = Path(C.DUMPS_DIR) / label / "run.json"
        if run_json.is_file():
            run = json.loads(run_json.read_text(encoding="utf-8"))
            counts = run.get("counts", {})
            entry["counts"] = {k: counts.get(k) for k in ("tamed_dinos", "pods", "dinos_failed", "pods_failed")}
            empty = not counts.get("tamed_dinos") and not counts.get("pods")
            entry["status"] = "empty_check_save_path" if empty else "ok"
        else:
            entry["status"] = {"exited": "server_exited_without_dump"}.get(status, status)
        entry["unpack_seconds"] = unpack_s
    except Exception as e:  # noqa: BLE001
        entry["status"] = f"error: {type(e).__name__}: {e}"
        if proc and proc.poll() is None:
            proc.kill()
    finally:
        entry["seconds"] = round(time.time() - started)
        # keep the server log for anything that didn't go cleanly
        if entry.get("status") != "ok" and server_log(slot).is_file():
            logs = Path(C.DUMPS_DIR) / "_failed_logs"
            logs.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(server_log(slot), logs / f"{label}.log")
            except OSError:
                pass
        try:
            shutil.rmtree(save_dir(slot))
        except OSError:
            pass
        state.set(label, entry)
        mins = entry["seconds"] / 60
        extra = f"  {entry.get('counts')}" if entry.get("counts") else ""
        log(f"[{slot['name']}] {entry['status']:<10} {label}  ({mins:.0f} min){extra}")
    return entry


# ---------------------------------------------------------------------------
# scheduler
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Run DinoDump over all save zips.")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--retry", action="store_true", help="also redo saves that failed before")
    ap.add_argument("--limit", type=int, default=0, help="only start this many saves")
    ap.add_argument("--slots", type=int, default=0, help="only use the first N slots")
    args = ap.parse_args()

    slots = C.SLOTS[: args.slots] if args.slots else list(C.SLOTS)
    Path(C.DUMPS_DIR).mkdir(parents=True, exist_ok=True)
    state = State(Path(C.DUMPS_DIR) / "batch_state.json")
    jobs, skipped = build_jobs(state, args.retry)
    if args.limit:
        jobs = jobs[: args.limit]

    total_gb = sum(j["ark_bytes"] for j in jobs) / GB
    log(f"{len(jobs)} saves to do ({total_gb:.0f} GB of .ark), {len(slots)} slots. "
        f"Skipped: {skipped['done']} done, {skipped['failed_before']} failed before "
        f"(use --retry), {skipped['filtered']} filtered out, {skipped['no_ark']} without a .ark")
    by_map = {}
    for j in jobs:
        by_map[j["map"]] = by_map.get(j["map"], 0) + 1
    for m, n in sorted(by_map.items(), key=lambda kv: -kv[1]):
        log(f"    {n:>5}  {m}")

    if args.dry_run:
        for j in jobs[:20]:
            log(f"  would run: {j['label']}  ({j['map']}, {j['ark_bytes'] / GB:.2f} GB, ~{j['ram_gb']:.0f} GB RAM)")
        if len(jobs) > 20:
            log(f"  ... and {len(jobs) - 20} more")
        if jobs:
            log("  example launch line:")
            log("    " + command_line(slots[0], jobs[0]))
        return

    for s in slots:
        if not server_exe(s).is_file():
            sys.exit(f"Slot {s['name']}: server not found at {server_exe(s)}")

    stop = threading.Event()
    free_slots = list(slots)
    running = {}          # slot name -> (thread, job)
    reserved_gb = 0.0     # RAM promised to servers that are still loading
    results = []
    lock = threading.Lock()
    t0 = time.time()

    def worker(slot, job):
        res = run_job(slot, job, state, stop)
        with lock:
            results.append(res)

    pending = list(jobs)
    try:
        while pending or running:
            # collect finished slots
            for name, (th, job) in list(running.items()):
                if not th.is_alive():
                    del running[name]
                    reserved_gb -= job["ram_gb"]
                    free_slots.append(next(s for s in slots if s["name"] == name))
            # start new work while there's a slot and RAM
            while pending and free_slots:
                free = free_ram_gb()
                avail = None if free is None else free - C.RAM_RESERVE_GB - max(0.0, reserved_gb * 0.5)
                pick = None
                for j in pending:
                    if avail is None or j["ram_gb"] <= avail or not running:
                        pick = j
                        break
                if not pick:
                    break
                pending.remove(pick)
                slot = free_slots.pop(0)
                th = threading.Thread(target=worker, args=(slot, pick), daemon=True)
                running[slot["name"]] = (th, pick)
                reserved_gb += pick["ram_gb"]
                th.start()
                time.sleep(20)  # let it start allocating before judging free RAM again
            time.sleep(5)
    except KeyboardInterrupt:
        log("Stopping: killing running servers (their saves will be redone next run)...")
        stop.set()
        for th, _ in running.values():
            th.join(timeout=60)

    ok = sum(1 for r in results if r.get("status") == "ok")
    bad = [r for r in results if r.get("status") != "ok"]
    hours = (time.time() - t0) / 3600
    summary = f"Batch finished in {hours:.1f} h: {ok} ok, {len(bad)} not ok."
    if bad:
        summary += " Not ok: " + ", ".join(f"{Path(r['zip']).stem} ({r.get('status')})" for r in bad[:15])
        if len(bad) > 15:
            summary += f" ... +{len(bad) - 15} more"
    log(summary)
    log(f"Details per save: {Path(C.DUMPS_DIR) / 'batch_state.json'}")
    notify(summary)


if __name__ == "__main__":
    main()
