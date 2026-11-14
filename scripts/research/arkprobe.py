r"""
arkprobe.py - work out how v11 cryopod pointers address the data sections on maps
whose custom data is split into more than one section (over 2GB of pod data).

Usage:  python arkprobe.py "EU-PVP-Official-Aberration233 (2023-09-30).zip"
Needs arkextract.py in the same folder. Read-only. Prints a short report to paste back.
"""

import collections
import struct
import sys
import time
from pathlib import Path

import arkextract as X


def pointer_entries(save, start, size):
    """Raw fields of each pointer entry, without interpreting them."""
    d = save.data
    p = X.Buf(d, start)
    out = []
    for _ in range(p.count(26)):
        e = {"at": p.o}
        e["flag"] = p.i16()
        e["off64"] = p.i64()
        e["x"] = p.i32()
        ncl = p.count(8)
        e["ncl"] = ncl
        for _ in range(ncl):
            if p.i32() == 1:
                p.o += 8
            else:
                p.o += 4
        out.append(e)
    return out, p.o - start


def try_read(save, at, end):
    if not X.looks_like_record(save.data, at):
        return None
    try:
        rec, arrays = X.read_record(save.data, at, end)
    except Exception:
        return None
    return rec


def main(path):
    t0 = time.time()
    path = Path(path)
    if path.suffix.lower() == ".zip":
        import zipfile
        with zipfile.ZipFile(path) as z:
            data = z.read(next(n for n in z.namelist() if n.lower().endswith(".ark")))
    else:
        data = path.read_bytes()
    save = X.Save(data)
    secs = [(b, s) for b, s in save.sections]
    print(f"{path.name}: v{save.version}, sections {[(b, s) for b, s in secs if s]}")
    s0 = secs[0][0]
    end_all = max(b + s for b, s in secs)

    flags, xs, his, ncls, sizes = (collections.Counter() for _ in range(5))
    hyp = collections.Counter()
    any_section = collections.Counter()
    fail_samples, x_samples = [], []
    total = 0
    for idx, (cls, loc, poff) in enumerate(save.objects):
        if not cls.startswith("PrimalItem"):
            continue
        r = X.Buf(data, save.prop_off + poff)
        cid = None
        try:
            while True:
                pn = save.name(r)
                if pn == "None":
                    break
                pt = save.name(r); sz = r.i32(); r.i32()
                if pt == "BoolProperty":
                    r.o += 1
                    continue
                if pt in ("ByteProperty", "StructProperty", "ArrayProperty"):
                    save.name(r)
                elif pt == "MapProperty":
                    save.name(r); save.name(r)
                if pn == "CustomItemDatas":
                    cid = (r.o, sz)
                r.o += sz
        except Exception:
            continue
        if not cid:
            continue
        try:
            entries, used = pointer_entries(save, *cid)
        except Exception:
            continue
        sizes[(cid[1], used)] += 1
        for e in entries:
            total += 1
            flags[e["flag"]] += 1
            xs[e["x"]] += 1
            his[e["off64"] >> 32] += 1
            ncls[e["ncl"]] += 1
            off, x, lo, hi = e["off64"], e["x"], e["off64"] & 0xFFFFFFFF, e["off64"] >> 32
            cands = {
                "A section=x, offset=off64": (secs[x][0] + off, secs[x][0] + secs[x][1]) if 0 <= x < 4 else None,
                "B continuous from section 1": (s0 + off, end_all),
                "C section=high dword, offset=low dword": (secs[hi][0] + lo, secs[hi][0] + secs[hi][1]) if 0 <= hi < 4 else None,
                "D section=flag-2": (secs[e["flag"] - 2][0] + off, secs[e["flag"] - 2][0] + secs[e["flag"] - 2][1])
                if 0 <= e["flag"] - 2 < 4 else None,
            }
            ok_any = False
            for name, c in cands.items():
                if c and try_read(save, c[0], c[1]) is not None:
                    hyp[name] += 1
                    ok_any = True
            for si, (b, s) in enumerate(secs):
                if s and off < s and try_read(save, b + off, b + s) is not None:
                    any_section[si] += 1
            if x != 0 and len(x_samples) < 8:
                x_samples.append((cls, e["flag"], off, x, e["ncl"], data[e["at"]:e["at"] + 30].hex(" ")))
            if not ok_any and len(fail_samples) < 8:
                fail_samples.append((cls, e["flag"], off, x, e["ncl"], data[e["at"]:e["at"] + 30].hex(" ")))

    print(f"\npointer entries: {total:,}   ({time.time() - t0:.0f}s)")
    print(f"flag values:      {flags.most_common(6)}")
    print(f"x field values:   {xs.most_common(6)}")
    print(f"off64 high dword: {his.most_common(6)}")
    print(f"class counts:     {ncls.most_common(6)}")
    print(f"(pointer size, bytes understood): {sizes.most_common(6)}")
    print("\nentries that read as a valid record under each layout:")
    for name in ("A section=x, offset=off64", "B continuous from section 1",
                 "C section=high dword, offset=low dword", "D section=flag-2"):
        print(f"  {hyp[name]:>9,} / {total:,}  {name}")
    print(f"valid record found at off64 inside section #: {dict(any_section)}")
    if x_samples:
        print("\nsamples with x != 0  (class, flag, off64, x, nclasses, first 30 bytes):")
        for s in x_samples:
            print("  ", s)
    if fail_samples:
        print("\nsamples no layout explains:")
        for s in fail_samples:
            print("  ", s)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print('Usage: python arkprobe.py "<save .zip or .ark>"')
        sys.exit(1)
    main(sys.argv[1])
