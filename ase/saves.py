"""Finding and opening save files (.ark, or official save .zips holding one)."""
import zipfile
from pathlib import Path

from .core.save import Save


def find_saves(args):
    """Expand files and folders into a sorted list of .ark / .zip saves."""
    out = []
    for a in args:
        p = Path(a)
        if p.is_dir():
            out += sorted(f for f in p.rglob("*") if f.suffix.lower() in (".ark", ".zip")
                          and not f.name.endswith(".extract.zip"))
        elif p.exists():
            out.append(p)
        else:
            print(f"not found: {a}")
    return out


def read_save_bytes(src):
    """(bytes, map name, save name) for a .ark or a zip containing one."""
    src = Path(src)
    if src.suffix.lower() == ".zip":
        with zipfile.ZipFile(src) as z:
            member = next((n for n in z.namelist() if n.lower().endswith(".ark")), None)
            if member is None:
                raise ValueError(f"{src.name}: zip has no .ark file inside")
            data = z.read(member)
        return data, Path(member).stem, src.stem
    return src.read_bytes(), src.stem, src.stem


def open_save(src):
    """(Save, map name, save name)."""
    data, map_name, save_name = read_save_bytes(src)
    return Save(data), map_name, save_name
