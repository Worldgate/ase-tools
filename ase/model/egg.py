"""Fertilized egg records."""

from ..core.props import indexed
from ..core.save import STAT_COUNT
from .dino import ancestors


def item_ids(p):
    iid = p.get("ItemId") or {}
    return iid.get("ItemID1"), iid.get("ItemID2")


def decode_egg(save, idx, p):
    cls = save.objects[idx][0]
    id1, id2 = item_ids(p)
    return {
        "class": cls, "item_id1": id1, "item_id2": id2,
        "wild_levels": indexed(p, "EggNumberOfLevelUpPointsApplied", STAT_COUNT),
        "colors": indexed(p, "EggColorSetIndices", 6),
        "mutations_maternal": p.get("EggRandomMutationsFemale", 0),
        "mutations_paternal": p.get("EggRandomMutationsMale", 0),
        "gender_override": p.get("EggGenderOverride", 0),
        "taming_effectiveness": 1.0 / (1.0 + p.get("EggTamedIneffectivenessModifier", 0.0)),
        "ancestors_maternal": ancestors(p, "EggDinoAncestors"),
        "ancestors_paternal": ancestors(p, "EggDinoAncestorsMale"),
    }
