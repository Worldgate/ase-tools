"""Compare an extract against a DinoDump plugin dump (the ground truth)."""

import json
import zipfile
from pathlib import Path


def close(a, b, rel=1e-6, absol=1e-6):
    try:
        return a == b or abs(a - b) <= max(rel * max(abs(a), abs(b)), absol)
    except TypeError:
        return False


def read_dump(target, member):
    target = Path(target)
    if target.is_file():
        with zipfile.ZipFile(target) as z:
            names = [n for n in z.namelist() if n.endswith(member)]
            return z.read(names[0]) if names else None
    hits = list(target.rglob(member))
    return hits[0].read_bytes() if hits else None


def compare(extract_path, target):
    print(f"\nComparing {Path(extract_path).name} against {Path(target).name}")
    with zipfile.ZipFile(extract_path) as z:
        mine = [json.loads(l) for l in z.read("dinos.jsonl").splitlines() if l.strip()]
        my_pods = [json.loads(l) for l in z.read("pods.jsonl").splitlines() if l.strip()]
        my_bin = z.read("pods.bin")

    # ---- dinos
    raw = read_dump(target, "dinos.jsonl")
    if raw is None:
        print("  no dinos.jsonl in dump")
    else:
        dump = {}
        for l in raw.splitlines():
            if l.strip():
                j = json.loads(l)
                dump[(j.get("id1"), j.get("id2"))] = j
        me = {(d["id1"], d["id2"]): d for d in mine}
        both = me.keys() & dump.keys()
        print(f"\nDINOS  extract {len(me):,}   dump {len(dump):,}   matched {len(both):,}")
        fields = ["female", "tribe", "tribe_id", "mutations_paternal", "mutations_maternal",
                  "baby_age", "level", "level_wild", "imprint", "taming_effectiveness",
                  "wild_levels", "tamed_levels", "colors", "tamed_on_server",
                  "uploaded_from_server", "creation_time", "location", "name",
                  "ancestors_maternal", "ancestors_paternal", "class"]
        bad = {f: 0 for f in fields}
        examples = {}
        missing_keys = set()
        for k in both:
            a, b = me[k], dump[k]
            missing_keys |= set(b) - set(a)
            for f in fields:
                if f not in b:
                    continue
                x, y = a.get(f), b[f]
                if f == "class":
                    ok = str(y).endswith(str(x).rsplit(".", 1)[-1])
                elif f == "location":
                    ok = x is not None and len(x) == len(y) and all(abs(p - q) <= 1.5 for p, q in zip(x, y))
                elif isinstance(y, float) or isinstance(x, float):
                    ok = close(x, y, 1e-5)
                elif isinstance(y, list) and y and isinstance(y[0], dict):
                    ok = len(x) == len(y) and all(
                        all((close(p[kk], q[kk], 0, 0) if isinstance(q[kk], (int, float)) else p[kk] == q[kk])
                            for kk in q if kk in p) for p, q in zip(x, y))
                else:
                    ok = x == y
                if not ok:
                    bad[f] += 1
                    examples.setdefault(f, (k, x, y))
        print("  mismatches: " + (", ".join(f"{f} {n:,}" for f, n in bad.items() if n) or "none"))
        if not any(bad.values()) and both:
            print("  every compared field matches on every matched dino")
        for f, (k, x, y) in list(examples.items())[:8]:
            print(f"    {f} e.g. {k}: extract={str(x)[:120]}  dump={str(y)[:120]}")
        if missing_keys:
            print(f"  dump fields not produced from the save: {sorted(missing_keys)}")
        oe = [me[k] for k in me.keys() - dump.keys()]
        od = [dump[k] for k in dump.keys() - me.keys()]
        print(f"  only in extract: {len(oe):,}   only in dump: {len(od):,}")
        if oe:
            print("    extract-only e.g.: " + ", ".join(
                f"{d['class'].rsplit('.', 1)[-1].replace('_Character_BP_C', '')}"
                f"{' (baby)' if d['baby_age'] < 1 else ''}" for d in oe[:12]))
        if od:
            print("    dump-only e.g.: " + ", ".join(str(d.get("class", "?")).rsplit(".", 1)[-1] for d in od[:12]))

    # ---- pods
    raw = read_dump(target, "pods.jsonl")
    pb = read_dump(target, "pods.bin")
    if raw is None or pb is None:
        print("  no pods.jsonl/pods.bin in dump")
        return
    dump = {}
    for l in raw.splitlines():
        if l.strip():
            j = json.loads(l)
            dump[(j.get("item_id1"), j.get("item_id2"))] = j
    me = {(p["item_id1"], p["item_id2"]): p for p in my_pods}
    both = me.keys() & dump.keys()
    bad = 0
    for k in both:
        a, b = me[k]["custom_data"], dump[k].get("custom_data") or []
        ok = len(a) == len(b)
        for x, y in zip(a, b):
            ok = ok and x["strings"] == y.get("strings", []) and x["names"] == y.get("names", []) \
                and x["classes"] == y.get("classes", []) \
                and len(x["floats"]) == len(y.get("floats", [])) \
                and all(close(p, q) for p, q in zip(x["floats"], y.get("floats", []))) \
                and len(x["doubles"]) == len(y.get("doubles", [])) \
                and all(close(p, q, 1e-7) for p, q in zip(x["doubles"], y.get("doubles", []))) \
                and len(x["byte_arrays"]) == len(y.get("byte_arrays", [])) \
                and all(my_bin[s["offset"]:s["offset"] + s["length"]] == pb[t["offset"]:t["offset"] + t["length"]]
                        for s, t in zip(x["byte_arrays"], y.get("byte_arrays", [])))
        bad += not ok
    only_dump = dump.keys() - me.keys()
    print(f"\nPODS  dump {len(dump):,}   matched {len(both):,}   mismatched {bad:,}   "
          f"only in dump {len(only_dump):,}   "
          f"extra items in extract (eggs, dermis, etc.) {len(me.keys() - dump.keys()):,}")
    if only_dump:
        import collections
        kinds = collections.Counter()
        for k in only_dump:
            j = dump[k]
            cds = j.get("custom_data") or []
            kinds[(j.get("item_name"), tuple(cd.get("name") for cd in cds),
                   sum(a.get("length", 0) for cd in cds for a in cd.get("byte_arrays", [])) > 1000)] += 1
        print("  only in dump, by kind (item, custom data names, has dino bytes):")
        for (item, cdn, has), n in kinds.most_common(15):
            print(f"    {n:>5,}  {item!r}  {list(cdn)}  {'DINO DATA' if has else 'no dino data'}")
        for k in list(only_dump)[:5]:
            j = dump[k]
            cd = (j.get("custom_data") or [{}])[0]
            print(f"    e.g. id {k[0]}/{k[1]}  {j.get('item_name')!r}  strings {cd.get('strings', [])[:3]}  "
                  f"owner {(j.get('owner') or {}).get('object')}")
