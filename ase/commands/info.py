"""ase info: what's in a save's header, without decoding objects."""
import collections
import struct

from ..saves import read_save_bytes
from ..core.save import Save

GROUP = "Debug"
HELP = "Header, version, sections, object counts, hibernation check"


def add_arguments(ap):
    ap.add_argument("save", help=".ark or official save .zip")


def hibernation_report(save):
    """The reader skips the hibernation section; say whether anything is in it."""
    data = save.data
    if save.version < 7:
        return "n/a (v7+ only)"
    r_off = 2 + (64 if save.version >= 11 else 0)
    hib_off = struct.unpack_from("<i", data, r_off)[0]
    gap = save.name_off - hib_off
    if save.version >= 8 and gap == 16:
        return f"empty (16 bytes at {hib_off})"
    head = data[hib_off:hib_off + min(gap, 64)].hex(" ")
    return f"{gap} bytes at {hib_off} - NOT empty, worth a look: {head}"


def run(args):
    data, map_name, save_name = read_save_bytes(args.save)
    s = Save(data)
    classes = collections.Counter(c for c, _, _ in s.objects)
    creatures = sum(n for c, n in classes.items() if c.endswith("_Character_BP_C") or "_Character_BP_" in c)
    items = sum(n for c, n in classes.items() if c.startswith("PrimalItem"))
    print(f"save          {save_name}")
    print(f"map           {map_name}")
    print(f"size          {len(data):,} bytes")
    print(f"version       {s.version}")
    print(f"game time     {s.game_time:,.0f} s   save count {s.save_count}")
    print(f"name table    {len(s.names):,} names at {s.name_off:,}" if s.names is not None else "name table    none (v5: inline names)")
    print(f"properties at {s.prop_off:,}")
    print(f"sublevels     {len(s.sublevels)}")
    print(f"embedded data {len(s.embedded)} entries" + (" (Ragnarok-style)" if s.embedded else ""))
    print(f"data-file map {s.data_file_map} levels")
    if s.version >= 11:
        used = [(o, n) for o, n in s.sections if n]
        print(f"sections      {len(used)} used: " + ", ".join(f"{n / 1_073_741_824:.2f} GB at {o:,}" for o, n in used))
    print(f"hibernation   {hibernation_report(s)}")
    print(f"objects       {len(s.objects):,}  ({creatures:,} creatures, {items:,} items, {len(classes):,} classes)")
