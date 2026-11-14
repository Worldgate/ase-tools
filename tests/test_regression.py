"""Regression: `ase tamed` must write exactly what scripts/arkextract.py writes.

Builds the synthetic v9 and v11 saves, runs both extractors, and compares every
member of the two .extract.zip files (meta.json minus the timing field).
Also checks the extras: pods decode, creatures/wild, classes, dump, info.

Run from the repo root:  python tests/test_regression.py
"""
import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
import fixture  # noqa: E402


def run(*cmd, cwd):
    r = subprocess.run([sys.executable, *map(str, cmd)], cwd=cwd, capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"FAILED: {' '.join(map(str, cmd))}\n{r.stdout}\n{r.stderr}")
    return r.stdout


def members(path):
    with zipfile.ZipFile(path) as z:
        out = {n: z.read(n) for n in z.namelist()}
    meta = json.loads(out["meta.json"])
    meta.pop("seconds", None)
    out["meta.json"] = json.dumps(meta, sort_keys=True).encode()
    return out


def main():
    ok = True
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for v in (9, 11):
            (tmp / f"fixture_v{v}.ark").write_bytes(fixture.build(v))
        saves = [tmp / "fixture_v9.ark", tmp / "fixture_v11.ark"]
        run(ROOT / "scripts" / "arkextract.py", *saves, "--out", tmp / "old", "--jobs", "1", cwd=tmp)
        run(ROOT / "ase.py", "tamed", *saves, "--out", tmp / "new", "--jobs", "1", cwd=tmp)
        for s in saves:
            a = members(tmp / "old" / f"{s.stem}.extract.zip")
            b = members(tmp / "new" / f"{s.stem}.extract.zip")
            same = a.keys() == b.keys() and all(a[k] == b[k] for k in a)
            ok &= same
            print(f"{'PASS' if same else 'FAIL'}  tamed output identical to arkextract.py: {s.name}")
            if not same:
                for k in sorted(a.keys() | b.keys()):
                    if a.get(k) != b.get(k):
                        print(f"      differs: {k}")

        # pods: the cryopodded Rex must decode with its own ID and stats
        run(ROOT / "ase.py", "pods", tmp / "new", "--out", tmp / "pods", cwd=tmp)
        for v in (9, 11):
            recs = [json.loads(l) for l in (tmp / "pods" / f"fixture_v{v}.pod_dinos.jsonl").read_text().splitlines()]
            good = len(recs) == 2 and all(r["id1"] == 777 and r["id2"] == 888 and r["name"] == "Podded Rex"
                                          and r["level"]["wild"] == 26 for r in recs)
            ok &= good
            print(f"{'PASS' if good else 'FAIL'}  pods: 2 podded Rexes decoded from v{v} (ids, name, level)")

        # build: extracts feed the dataset builder directly
        run(ROOT / "ase.py", "build", tmp / "new" / "fixture_v11.extract.zip", "-o", tmp / "built",
            "--workers", "1", cwd=tmp)
        import sqlite3
        db = sqlite3.connect(tmp / "built" / "dinodump.sqlite")
        n = db.execute("select count(*) from dinos").fetchone()[0]
        good = n >= 2
        ok &= good
        print(f"{'PASS' if good else 'FAIL'}  build reads .extract.zip directly ({n} unique dinos in SQLite)")

        # creatures / wild
        run(ROOT / "ase.py", "creatures", saves[1], "--out", tmp / "cr", cwd=tmp)
        recs = [json.loads(l) for l in (tmp / "cr" / "fixture_v11.creatures.jsonl").read_text().splitlines()]
        good = sorted(r["tamed"] for r in recs) == [False, True]
        ok &= good
        print(f"{'PASS' if good else 'FAIL'}  creatures: 1 tamed + 1 wild")

        out = run(ROOT / "ase.py", "classes", saves[1], cwd=tmp)
        good = "PrimalItem_WeaponEmptyCryopod_C,2" in out
        ok &= good
        print(f"{'PASS' if good else 'FAIL'}  classes counts objects")

        run(ROOT / "ase.py", "dump", saves[1], "StorageBox_Small_C", tmp / "box.jsonl", cwd=tmp)
        box = json.loads((tmp / "box.jsonl").read_text())
        good = box["properties"].get("BoxName") == "loot"
        ok &= good
        print(f"{'PASS' if good else 'FAIL'}  dump decodes a structure's properties")

        out = run(ROOT / "ase.py", "info", saves[1], cwd=tmp)
        good = "version       11" in out and "2 used" in out and "hibernation   empty" in out
        ok &= good
        print(f"{'PASS' if good else 'FAIL'}  info reads v11 header, sections and hibernation")
    print("\nALL PASSED" if ok else "\nSOME FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
