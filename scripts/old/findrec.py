r"""
findrec.py - find text inside DinoDump output (a folder or a .zip) and print what's around it.

Usage:  python findrec.py "C:\asmdata\OfficialDinoDumps\<Gen2 dump>.zip" "Boss - Lvl 444"
        python findrec.py "C:\path\to\dump_folder" "Boss - Lvl 444"

Prints the file name and ~3000 characters around the first match in each file.
"""

import sys
import zipfile
from pathlib import Path

BEFORE, AFTER = 1500, 1500


def search(name, data, needle):
    i = data.find(needle)
    if i < 0:
        return False
    start, end = max(0, i - BEFORE), i + len(needle) + AFTER
    text = data[start:end].decode("utf-8", "replace")
    print(f"=== {name}  (match at byte {i:,} of {len(data):,})")
    print(text)
    print()
    return True


def main(target, needle):
    target = Path(target)
    needle_b = needle.encode("utf-8")
    found = 0
    if target.is_file() and target.suffix.lower() == ".zip":
        with zipfile.ZipFile(target) as z:
            for info in z.infolist():
                if not info.is_dir():
                    found += search(info.filename, z.read(info), needle_b)
    elif target.is_dir():
        for f in sorted(target.rglob("*")):
            if f.is_file():
                found += search(str(f.relative_to(target)), f.read_bytes(), needle_b)
    else:
        print(f"Not a folder or .zip: {target}")
        return
    if not found:
        print(f'"{needle}" not found. Files searched:')
        names = (zipfile.ZipFile(target).namelist() if target.suffix.lower() == ".zip"
                 else [str(p.relative_to(target)) for p in target.rglob("*") if p.is_file()])
        for n in names:
            print("  ", n)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print('Usage: python findrec.py "<dump folder or zip>" "text to find"')
        sys.exit(1)
    main(sys.argv[1], sys.argv[2])
