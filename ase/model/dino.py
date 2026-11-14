"""Tamed dino records, in the same shape DinoDump writes."""

import math

from ..core.props import indexed
from ..core.save import STAT_COUNT


def ancestors(p, name):
    out = []
    for a in p.get(name) or []:
        if isinstance(a, dict):
            out.append({"male": a.get("MaleName", ""), "male_id1": a.get("MaleDinoID1", 0),
                        "male_id2": a.get("MaleDinoID2", 0), "female": a.get("FemaleName", ""),
                        "female_id1": a.get("FemaleDinoID1", 0), "female_id2": a.get("FemaleDinoID2", 0)})
    return out


def decode_dino(save, idx, p, status, map_name, save_name):
    cls, loc, _ = save.objects[idx]
    id1, id2 = p.get("DinoID1", 0), p.get("DinoID2", 0)
    base = status.get("BaseCharacterLevel", 1)
    extra = status.get("ExtraCharacterLevel", 0)
    ineff = status.get("TamedIneffectivenessModifier", 0.0)
    rec = {
        "id1": id1, "id2": id2, "id64": str((id1 << 32) | id2),
        "class": save.class_paths.get(cls, cls),
        "name": p.get("TamedName", ""),
        "female": bool(p.get("bIsFemale", False)),
        "tribe": p.get("TribeName", ""), "tribe_id": p.get("TargetingTeam", 0),
        "tamer": p.get("TamerString", ""), "owner": p.get("OwningPlayerName", ""),
        "imprinter": p.get("ImprinterName", ""),
        "mutations_paternal": p.get("RandomMutationsMale", 0),
        "mutations_maternal": p.get("RandomMutationsFemale", 0),
        "baby_age": p.get("BabyAge", 1.0),
        "level": base + extra, "level_wild": base,
        "imprint": status.get("DinoImprintingQuality", 0.0),
        "taming_effectiveness": 1.0 / (1.0 + ineff),
        "wild_levels": indexed(status, "NumberOfLevelUpPointsApplied", STAT_COUNT),
        "tamed_levels": indexed(status, "NumberOfLevelUpPointsAppliedTamed", STAT_COUNT),
        "colors": indexed(p, "ColorSetIndices", 6),
        "neutered": bool(p.get("bNeutered", False)),
        "clone": bool(p.get("bIsCloneDino", False)),
        "tamed_on_server": (p.get("TamedOnServerName") or "").strip(),
        "uploaded_from_server": (p.get("UploadedFromServerName") or "").strip(),
        "creation_time": p.get("OriginalCreationTime", 0.0),
        # some dinos fell out of the world and carry NaN/inf coordinates
        "location": [round(c) for c in loc] if loc and all(math.isfinite(c) for c in loc) else None,
        "ancestors_maternal": ancestors(p, "DinoAncestors"),
        "ancestors_paternal": ancestors(p, "DinoAncestorsMale"),
        "source": "world", "map": map_name, "save": save_name,
    }
    if "GestationEggNumberOfLevelUpPointsApplied" in p or "GestationEggColorSetIndices" in p:
        rec["gestation"] = {
            "wild_levels": indexed(p, "GestationEggNumberOfLevelUpPointsApplied", STAT_COUNT),
            "colors": indexed(p, "GestationEggColorSetIndices", 6),
            "mutations_maternal": p.get("GestationEggRandomMutationsFemale", 0),
            "mutations_paternal": p.get("GestationEggRandomMutationsMale", 0),
            "taming_effectiveness": 1.0 / (1.0 + p.get("GestationEggTamedIneffectivenessModifier", 0.0)),
        }
    return rec
