r"""
arkservers.py - every server name mentioned anywhere in your extracts, checked against
the saves you actually have, to spot servers that are missing or were erased.

Usage:  python arkservers.py [extracts folder] [--deep] [--jobs N]
        python arkservers.py extracts                (fast: world dinos only)
        python arkservers.py extracts --deep --jobs 24   (also scans every cryopod's bytes)

Sources of server names:
  - your saves themselves (each extract = one server you have)
  - world dinos: tamed_on_server, uploaded_from_server
  - --deep: TamedOnServerName / UploadedFromServerName inside every cryopod's dino bytes
            (much slower: reads all of pods.bin, but covers ~97% of all dinos)

Writes servers.csv next to the extracts folder:
  server, have_save, matched_save, tamed_on (count), uploaded_from (count), seen_in_saves (count)
Servers you DON'T have a save for are the interesting ones: transferred-from, closed, merged or erased.
"""

import collections
import csv
import json
import multiprocessing as mp
import re
import sys
import zipfile
from pathlib import Path

FIELD = re.compile(rb"(TamedOnServerName|UploadedFromServerName)\x00")
SERVERISH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _\-\.]{3,79}$")
DATE = re.compile(r"\s*\(\d{4}-\d{2}-\d{2}\)\s*$|_\d{4}-\d{2}-\d{2}$")


def parts(name):
    """A server field can hold a newline-separated transfer history; return each name."""
    out = []
    for p in (name or "").replace("\r", "\n").split("\n"):
        p = p.strip().strip("\x00").strip()
        if p and SERVERISH.match(p):
            out.append(p)
    return out


def save_to_server(save):
    """'EU-PVP-Official-Valguero544 (2023-09-30)' -> 'EU-PVP-Official-Valguero544'."""
    return DATE.sub("", save).strip()


def read_fstring_near(buf, start, window=96):
    """Value of the StrProperty right after a field name: name, 'StrProperty', size, index, FString.
    Returns the list of server names in it (transfer histories hold several, newline-separated)."""
    end = min(len(buf) - 4, start + window)
    i = start
    while i < end:
        n = int.from_bytes(buf[i:i + 4], "little", signed=True)
        if 2 <= n <= 4096 and i + 4 + n <= len(buf) and buf[i + 3 + n] == 0:
            try:
                txt = buf[i + 4:i + 3 + n].decode("ascii")
            except UnicodeDecodeError:
                txt = ""
            if txt and txt not in ("StrProperty", "TamedOnServerName", "UploadedFromServerName"):
                found = [p for p in parts(txt) if "-" in p or "_" in p]
                if found:
                    return found
        i += 1
    return None


def scan(job):
    path, deep = job
    tamed, uploaded = collections.Counter(), collections.Counter()
    try:
        z = zipfile.ZipFile(path)
        meta = json.loads(z.read("meta.json"))
    except Exception as e:
        return str(path), None, None, None, f"{type(e).__name__}: {e}"
    save = meta.get("save", Path(path).stem)
    with z:
        names = z.namelist()
        if "dinos.jsonl" in names:
            with z.open("dinos.jsonl") as f:
                for line in f:
                    try:
                        d = json.loads(line)
                    except ValueError:
                        continue
                    for s in parts(d.get("tamed_on_server")):
                        tamed[s] += 1
                    for s in parts(d.get("uploaded_from_server")):
                        uploaded[s] += 1
        if deep and "pods.bin" in names:
            chunk, overlap = 64 * 1024 * 1024, 256
            with z.open("pods.bin") as f:
                tail = b""
                while True:
                    data = f.read(chunk)
                    if not data:
                        break
                    buf = tail + data
                    limit = len(buf) - overlap if len(data) == chunk else len(buf)
                    for m in FIELD.finditer(buf):
                        if m.start() >= limit:
                            break
                        vals = read_fstring_near(buf, m.end())
                        for val in vals or ():
                            (tamed if m.group(1) == b"TamedOnServerName" else uploaded)[val] += 1
                    tail = buf[limit:] if len(data) == chunk else b""
    return save, save_to_server(save), tamed, uploaded, None


def main():
    args = sys.argv[1:]
    deep = "--deep" in args
    if deep:
        args.remove("--deep")
    jobs = 8
    if "--jobs" in args:
        i = args.index("--jobs"); jobs = int(args[i + 1]); del args[i:i + 2]
    folder = Path(args[0]) if args else Path(__file__).resolve().parent / "extracts"
    files = sorted(folder.rglob("*.extract.zip"))
    if not files:
        print(f"no extracts in {folder}")
        return
    print(f"scanning {len(files)} extracts ({'deep: world dinos + pod bytes' if deep else 'world dinos only'}) "
          f"with {jobs} jobs ...", flush=True)

    have = {}                       # server name -> save name
    tamed, uploaded = collections.Counter(), collections.Counter()
    seen_in = collections.defaultdict(set)
    identity = []                   # (save, file server name, most common tamed_on, its share, dinos counted)
    done = 0
    with mp.Pool(min(jobs, len(files))) as pool:
        for save, server, t, u, err in pool.imap_unordered(scan, [(f, deep) for f in files]):
            done += 1
            if err:
                print(f"  skipped {save}: {err}")
                continue
            have[server] = save
            # does any dino here know this server by a LEGACY- name the file doesn't have?
            lname = "legacy-" + server.lower()
            legacy_hint = (not server.lower().startswith("legacy-")) and \
                any(k.lower() == lname for k in list(t) + list(u))
            if t:
                top, n = t.most_common(1)[0]
                identity.append((save, server, top, n / sum(t.values()), sum(t.values()), legacy_hint))
            else:
                identity.append((save, server, "", 0.0, 0, legacy_hint))
            tamed.update(t)
            uploaded.update(u)
            for s in set(t) | set(u):
                seen_in[s].add(save)
            if done % 100 == 0:
                print(f"  {done}/{len(files)}", flush=True)

    # match mentioned names to saves: exact, case-insensitive, or legacy rename (LEGACY- prefix)
    lower = {k.lower(): k for k in have}

    def match(name):
        if name in have:
            return have[name]
        k = name.lower()
        for cand in (k, "legacy-" + k, k.replace("legacy-", "", 1)):
            if cand in lower:
                return have[lower[cand]]
        return ""

    mentioned = set(tamed) | set(uploaded)
    rows = []
    for name in sorted(mentioned | set(have)):
        m = have.get(name) or match(name)
        rows.append({"server": name, "have_save": "yes" if m else "NO", "matched_save": m,
                     "tamed_on": tamed.get(name, 0), "uploaded_from": uploaded.get(name, 0),
                     "seen_in_saves": len(seen_in.get(name, ()))})
    out = folder.parent / "servers.csv"
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    missing = [r for r in rows if r["have_save"] == "NO"]
    missing.sort(key=lambda r: r["tamed_on"] + r["uploaded_from"], reverse=True)
    print(f"\n{len(have)} servers you have saves for, {len(mentioned)} server names mentioned by dinos")
    print(f"{len(missing)} mentioned servers with NO save:\n")
    print(f"{'tamed on':>10} {'uploaded':>10} {'in saves':>9}  server")
    for r in missing[:60]:
        print(f"{r['tamed_on']:>10,} {r['uploaded_from']:>10,} {r['seen_in_saves']:>9}  {r['server']}")
    if len(missing) > 60:
        print(f"  ... {len(missing) - 60} more in servers.csv")
    # coverage: of every server known to have existed, how many you have a save for
    # a renamed legacy server appears under both names but is one server: group by the save it matched
    uniq = {}
    for r in rows:
        uniq.setdefault(r["matched_save"] or r["server"], r)
    known = len(uniq)
    got = sum(1 for r in uniq.values() if r["have_save"] == "yes")
    print(f"\nCOVERAGE: {got:,} of {known:,} known servers archived ({100 * got / known:.1f}%)")
    maps = collections.defaultdict(lambda: [0, 0])
    for r in uniq.values():
        m = re.search(r"(TheIsland|TheCenter|ScorchedEarth|Ragnarok|Aberration|Extinction|Valguero|"
                      r"GenOne|GenTwo|Genesis|CrystalIsles|LostIsland|Fjordur|Gen2|Gen1)", r["server"], re.I)
        key = m.group(1) if m else "other"
        key = {"Genesis": "GenOne", "Gen1": "GenOne", "Gen2": "GenTwo"}.get(key, key)
        maps[key][0] += 1
        maps[key][1] += r["have_save"] == "yes"
    print(f"{'map':<16}{'known':>7}{'have':>7}{'missing':>9}{'coverage':>10}")
    for k, (n, h) in sorted(maps.items(), key=lambda kv: -kv[1][0]):
        print(f"{k:<16}{n:>7}{h:>7}{n - h:>9}{100 * h / n:>9.0f}%")
    # naming check: does each file's name match the server its own dinos say they were tamed on?
    def same(a, b):
        a, b = a.lower(), b.lower()
        return a == b or a == "legacy-" + b or b == "legacy-" + a
    name_rows, mism = [], 0
    dup_files = collections.Counter(s for _, s, *_ in identity)
    for save, server, top, share, n, legacy_hint in sorted(identity):
        ok = same(server, top) if top else None
        flag = "ok" if ok else ("no dinos" if top == "" else "CHECK")
        if legacy_hint or (top.lower().startswith("legacy-") and not server.lower().startswith("legacy-")):
            flag = "ADD LEGACY- PREFIX" + ("" if ok else " (and CHECK)")
        if dup_files[server] > 1:
            flag += " +DUPLICATE NAME"
        if flag != "ok":
            mism += 1
        name_rows.append({"save_file": save, "file_says": server, "dinos_say": top,
                          "share": f"{share:.0%}", "dinos_counted": n, "status": flag})
    nout = folder.parent / "naming_check.csv"
    with open(nout, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(name_rows[0]))
        w.writeheader()
        w.writerows(name_rows)
    bad = [r for r in name_rows if r["status"] not in ("ok", "no dinos")]
    print(f"\nNAMING: {len(bad)} saves whose file name doesn't match what their own dinos say (or duplicate names)")
    for r in bad[:25]:
        print(f"  {r['status']:<24} file: {r['file_says']:<44} dinos: {r['dinos_say']} ({r['share']} of {r['dinos_counted']})")
    if len(bad) > 25:
        print(f"  ... {len(bad) - 25} more in naming_check.csv")
    print(f"Naming table: {nout}")
    never = [r for r in rows if r["have_save"] == "yes" and not (r["tamed_on"] or r["uploaded_from"])]
    print(f"\n{len(never)} of your servers are never mentioned by any dino (tamed elsewhere or not scanned)")
    print(f"Full table: {out}")


if __name__ == "__main__":
    mp.freeze_support()
    main()
