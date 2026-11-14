r"""
arkmissing.py - find saves that have no extract yet, and why.

Usage:  python arkmissing.py SAVES_FOLDER [SAVES_FOLDER ...] --extracts EXTRACTS_FOLDER
        python arkmissing.py .\Aberration_P .\incoming --extracts .\extracts
        python arkmissing.py D:\OfficialSaves --extracts D:\OfficialSaves\extracts

For every save (.ark or .zip) it reports one of:
  duplicate name  - another save with the same file name exists; both map to ONE extract
  no .ark inside  - the zip doesn't contain a save file
  failed          - listed in errors.log (shows the error)
  partial         - a .partial file exists (run was interrupted mid-write)
  not run yet     - none of the above; just hasn't been processed
Writes missing.txt next to the extracts folder.
"""

import collections
import sys
import zipfile
from pathlib import Path


def main():
    args = sys.argv[1:]
    if "--extracts" not in args or len(args) < 3:
        print(__doc__)
        return
    i = args.index("--extracts")
    extracts = Path(args[i + 1])
    del args[i:i + 2]
    saves = []
    for a in args:
        p = Path(a)
        if p.is_dir():
            saves += [f for f in p.rglob("*") if f.suffix.lower() in (".ark", ".zip")
                      and not f.name.endswith(".extract.zip") and extracts not in f.parents]
        elif p.exists():
            saves.append(p)

    done = {f.name[:-len(".extract.zip")] for f in extracts.glob("*.extract.zip")}
    partial = {f.name[:-len(".extract.zip.partial")] for f in extracts.glob("*.extract.zip.partial")}
    failed = {}
    log = extracts / "errors.log"
    if log.exists():
        cur = None
        for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("=== "):
                cur = Path(line[4:].strip()).stem
            elif cur and line.strip() and not line.startswith(" ") and "Error" in line:
                failed[cur] = line.strip()[:200]

    by_stem = collections.defaultdict(list)
    for s in saves:
        by_stem[s.stem].append(s)

    report = collections.defaultdict(list)
    for stem, files in sorted(by_stem.items()):
        if len(files) > 1:
            report["duplicate name"].append(f"{stem}  ({len(files)} files: " +
                                            "; ".join(str(f.parent) for f in files) + ")")
        if stem in done:
            continue
        f = files[0]
        reason = None
        if f.suffix.lower() == ".zip":
            try:
                with zipfile.ZipFile(f) as z:
                    if not any(n.lower().endswith(".ark") for n in z.namelist()):
                        reason = "no .ark inside"
            except zipfile.BadZipFile:
                reason = "not a valid zip"
        if reason is None and stem in failed:
            reason = "failed"
        if reason is None and stem in partial:
            reason = "partial"
        report[reason or "not run yet"].append(
            f"{f}" + (f"   -> {failed[stem]}" if reason == "failed" else ""))

    dup_extra = sum(len(v) - 1 for v in by_stem.values() if len(v) > 1)
    print(f"{len(saves)} save files, {len(by_stem)} unique names, {len(done)} extracts")
    print(f"  {dup_extra} files share a name with another file (only one extract each)")
    lines = []
    for reason in ("duplicate name", "no .ark inside", "not a valid zip", "failed", "partial", "not run yet"):
        items = report.get(reason, [])
        if not items:
            continue
        print(f"\n{reason}: {len(items)}")
        lines.append(f"== {reason}: {len(items)}")
        for it in items[:15]:
            print(f"  {it}")
        if len(items) > 15:
            print(f"  ... {len(items) - 15} more in missing.txt")
        lines += [f"  {it}" for it in items]
    out = extracts.parent / "missing.txt"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nFull list: {out}")


if __name__ == "__main__":
    main()
