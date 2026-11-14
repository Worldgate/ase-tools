"""Walk every creature in a save (tamed, wild, or both) as records."""
from ..core.props import props_to_dict
from .dino import decode_dino

TAMED_TEAM = 50000  # TargetingTeam at or above this = a tribe


def is_creature_class(cls):
    return cls.endswith("_Character_BP_C") or "_Character_BP_" in cls


WILD_FIELDS = ("id1", "id2", "id64", "class", "female", "level", "level_wild", "wild_levels",
               "colors", "location", "baby_age", "map", "save")


def iter_creatures(save, want, map_name, save_name, errors=None):
    """want: 'tamed', 'wild' or 'all'. Yields records shaped like extract dinos;
    wild ones carry only the fields that mean something for a wild dino."""
    for idx, (cls, _loc, _poff) in enumerate(save.objects):
        if not is_creature_class(cls):
            continue
        try:
            qnames, qints, _ = save.quick(idx)
            tamed = qints.get("TargetingTeam", 0) >= TAMED_TEAM and "DinoID1" in qnames
            if (want == "tamed" and not tamed) or (want == "wild" and tamed):
                continue
            _raw, plist = save.prop_block(idx)
            p = props_to_dict(plist)
            status = {}
            ref = p.get("MyCharacterStatusComponent")
            if isinstance(ref, dict) and "id" in ref and 0 <= ref["id"] < len(save.objects):
                status = props_to_dict(save.prop_block(ref["id"])[1])
            rec = decode_dino(save, idx, p, status, map_name, save_name)
            if not tamed:
                rec = {k: rec[k] for k in WILD_FIELDS}
                rec["source"] = "wild"
            rec["tamed"] = tamed
            yield rec
        except Exception as e:  # one damaged object never stops the map
            if errors is not None:
                errors.append(f"{cls}: {type(e).__name__}: {e}")
