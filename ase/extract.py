"""Extract one map: tamed dinos, pods, eggs and pregnancies -> <save>.extract.zip.
This is arkextract.py's core, moved unchanged. Output is identical to arkextract.py 4."""

import base64
import json
import os
import time
import traceback
import zipfile
from pathlib import Path

from .core.customdata import pod_entries_v11, pod_entries_v9
from .core.props import props_to_dict, clean_json
from .core.save import Save
from .model.dino import decode_dino
from .model.egg import decode_egg, item_ids

# bump when output changes; extracts made by an older version are redone automatically.
# Kept identical to arkextract.py so existing extracts are not redone.
EXTRACTOR = "arkextract.py 4"


def note_error(kinds, examples, where, cls, e):
    """Group errors by what failed (numbers stripped) and keep a few full examples."""
    import re as _re
    msg = f"{where}: {type(e).__name__}: {e}"
    key = _re.sub(r"\d+", "#", f"{where} {cls.split('_C')[0][:40]}: {type(e).__name__}: {e}")[:160]
    kinds[key] = kinds.get(key, 0) + 1
    if len(examples) < 10:
        examples.append(f"{cls}: {msg}"[:300])


def extract_map(job):
    """Never raises: one bad map is reported and the batch carries on."""
    src, out_dir, verbose = job
    try:
        return _extract_map(src, out_dir, verbose)
    except Exception as e:
        tmp = Path(out_dir) / f"{Path(src).stem}.extract.zip.partial"
        try:
            tmp.unlink()
        except OSError:
            pass
        log = Path(out_dir) / "errors.log"
        with open(log, "a", encoding="utf-8") as f:
            f.write(f"=== {Path(src).name}\n{traceback.format_exc()}\n")
        return f"{Path(src).stem}: FAILED ({type(e).__name__}: {e}) - details in errors.log, will retry next run"


def _extract_map(src, out_dir, verbose=False):
    t0 = time.time()
    src = Path(src)
    try:
        if src.suffix.lower() == ".zip":
            with zipfile.ZipFile(src) as z:
                member = next(n for n in z.namelist() if n.lower().endswith(".ark"))
                data = z.read(member)
            map_name = Path(member).stem
        else:
            data = src.read_bytes()
            map_name = src.stem
        save_name = src.stem
        out_path = Path(out_dir) / f"{save_name}.extract.zip"
        print(f"  started {save_name} ({len(data) / 1_073_741_824:.1f} GB)", flush=True)
        save = Save(data)
    except StopIteration:
        raise ValueError("zip has no .ark file inside") from None
    except Exception as e:
        # re-raise so extract_map logs it to errors.log like any other failure
        raise ValueError(f"cannot read save: {type(e).__name__}: {e}") from e

    dinos, dinos_raw, eggs, pods = [], [], [], []
    errors = pointer_extra = section_fallbacks = 0
    err_kinds, err_examples = {}, []
    total = len(save.objects)
    for idx, (cls, loc, poff) in enumerate(save.objects):
        if verbose and idx and idx % 250_000 == 0:
            print(f"    {idx:,} / {total:,} objects  {len(dinos):,} tamed  {len(pods):,} items  "
                  f"{errors} errors  ({time.time() - t0:.0f}s)", flush=True)
        is_creature = cls.endswith("_Character_BP_C") or "_Character_BP_" in cls
        is_item = cls.startswith("PrimalItem")
        if not (is_creature or is_item):
            continue
        is_egg = is_item and "_Fertilized" in cls and "Egg" in cls
        # quick pass first: most creatures are wild and most items carry nothing we keep
        try:
            qnames, qints, qcid = save.quick(idx)
        except Exception as e:
            errors += 1
            note_error(err_kinds, err_examples, "props", cls, e)
            continue
        if is_creature and (qints.get("TargetingTeam", 0) < 50000 or "DinoID1" not in qnames):
            continue
        if is_item and not is_egg and "CustomItemDatas" not in qnames:
            continue
        try:
            raw, plist = save.prop_block(idx)
        except Exception as e:
            errors += 1
            note_error(err_kinds, err_examples, "props", cls, e)
            continue
        try:
            p = props_to_dict(plist)

            if is_creature:
                if p.get("TargetingTeam", 0) < 50000 or "DinoID1" not in p:
                    continue
                status, sraw = {}, b""
                ref = p.get("MyCharacterStatusComponent")
                if isinstance(ref, dict) and "id" in ref and 0 <= ref["id"] < len(save.objects):
                    try:
                        sraw, slist = save.prop_block(ref["id"])
                        status = props_to_dict(slist)
                    except Exception as e:
                        errors += 1
                        note_error(err_kinds, err_examples, "status", cls, e)
                rec = decode_dino(save, idx, p, status, map_name, save_name)
                dinos.append(rec)
                dinos_raw.append({"id1": rec["id1"], "id2": rec["id2"], "class": cls,
                                  "props_b64": base64.b64encode(raw).decode(),
                                  "status_class": save.objects[ref["id"]][0] if sraw else None,
                                  "status_b64": base64.b64encode(sraw).decode()})
                continue

            # items
            if is_egg:
                egg = decode_egg(save, idx, p)
                egg["props_b64"] = base64.b64encode(raw).decode()
                eggs.append(egg)
            if "CustomItemDatas" not in p:
                continue
            id1, id2 = item_ids(p)
            try:
                if save.version >= 11:
                    cid = qcid
                    entries, extra, fb = pod_entries_v11(save, cid)
                    pointer_extra += extra
                    section_fallbacks += fb
                    entries = [(rec, [data[o:o + n] for o, n in arrs]) for rec, arrs in entries]
                else:
                    entries = pod_entries_v9(save, p.get("CustomItemDatas"))
            except Exception as e:
                errors += 1
                note_error(err_kinds, err_examples, "custom data", cls, e)
                continue
            if entries:
                pods.append({"class": cls, "item_id1": id1, "item_id2": id2, "entries": entries})
        except Exception as e:  # one damaged object never stops the map
            errors += 1
            note_error(err_kinds, err_examples, "decode", cls, e)

    # ---- write the extract
    tmp = out_path.with_name(out_path.name + ".partial")
    pod_bytes = 0
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        with z.open("pods.bin", "w", force_zip64=True) as bf:
            jl = []
            for pod in pods:
                cds = []
                for rec, arrays in pod["entries"]:
                    ba = []
                    for b in arrays:
                        bf.write(b)
                        ba.append({"offset": pod_bytes, "length": len(b)})
                        pod_bytes += len(b)
                    cds.append({"name": rec["name"], "strings": rec["strings"],
                                "floats": rec["floats"], "doubles": rec["doubles"],
                                "names": rec["names"], "classes": rec["classes"],
                                "objects": [], "byte_arrays": ba})
                jl.append(json.dumps({"class": pod["class"], "item_id1": pod["item_id1"],
                                      "item_id2": pod["item_id2"], "custom_data": cds}))
        z.writestr("pods.jsonl", "\n".join(jl) + "\n" if jl else "")
        z.writestr("dinos.jsonl", "".join(json.dumps(clean_json(d), ensure_ascii=False) + "\n" for d in dinos))
        z.writestr("dinos_raw.jsonl", "".join(json.dumps(d) + "\n" for d in dinos_raw))
        z.writestr("eggs.jsonl", "".join(json.dumps(clean_json(e), ensure_ascii=False) + "\n" for e in eggs))
        z.writestr("names.json", json.dumps(save.names))
        n_cryo = sum(1 for p in pods if "Cryopod" in p["class"])
        meta = {"save": save_name, "map": map_name, "source_file": src.name,
                "version": save.version, "save_count": save.save_count, "game_time": save.game_time,
                "objects": len(save.objects), "tamed_world_dinos": len(dinos),
                "babies": sum(1 for d in dinos if d["baby_age"] < 1),
                "pregnant": sum(1 for d in dinos if "gestation" in d),
                "items_with_custom_data": len(pods), "cryopods": n_cryo, "pod_bytes": pod_bytes,
                "fertilized_eggs": len(eggs), "errors": errors, "pointer_extra": pointer_extra,
                "section_fallbacks": section_fallbacks,
                "error_kinds": dict(sorted(err_kinds.items(), key=lambda kv: -kv[1])[:20]),
                "error_examples": err_examples,
                "data_sections": [s for s in save.sections if s[1]],
                "extractor": EXTRACTOR, "seconds": round(time.time() - t0, 1)}
        z.writestr("meta.json", json.dumps(meta, indent=1))
    os.replace(tmp, out_path)
    if verbose and err_kinds:
        print("  errors by kind:", flush=True)
        for k, n in sorted(err_kinds.items(), key=lambda kv: -kv[1])[:10]:
            print(f"    {n:>7,}  {k}", flush=True)
    if verbose:
        print(f"  section fallbacks: {section_fallbacks:,}   data sections: "
              f"{[s for s in save.sections if s[1]]}", flush=True)
    return (f"{save_name}: v{save.version}  {len(dinos):,} tamed  {n_cryo:,} pods  "
            f"{len(eggs):,} eggs  {meta['pregnant']} pregnant  {errors} errors  "
            f"({meta['seconds']}s)")
