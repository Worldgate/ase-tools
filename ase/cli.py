"""`python -m ase <command> ...` - one entry point, commands discovered from ase/commands/.

A command module defines:
    NAME = "tamed"                  (optional; defaults to the file name)
    HELP = "one line"
    GROUP = "Creatures"             (for the help listing)
    def add_arguments(parser): ...
    def run(args): ...              (return an int exit code or None)
Drop a new file into ase/commands/ and it shows up. Nothing else to register.
"""
import argparse
import importlib
import pkgutil
import sys

from . import __version__, commands

GROUP_ORDER = ["Extract", "Creatures", "Players", "Converting", "Debug", "Reports", "Build", "Tools"]


def load_commands():
    found = {}
    for info in pkgutil.iter_modules(commands.__path__):
        if info.name.startswith("_"):
            continue
        mod = importlib.import_module(f"{commands.__name__}.{info.name}")
        name = getattr(mod, "NAME", info.name.replace("_", "-"))
        found[name] = mod
        for alias in getattr(mod, "ALIASES", []):
            found[alias] = mod
    return found


def usage(cmds):
    groups = {}
    for name, mod in cmds.items():
        if name != getattr(mod, "NAME", name):
            continue  # alias
        groups.setdefault(getattr(mod, "GROUP", "Tools"), []).append((name, mod))
    lines = [f"ase-tools {__version__} - read ARK: Survival Evolved saves (v5-v11) without a server", "",
             "usage: python -m ase <command> [options]      (python -m ase <command> -h for details)", ""]
    for g in sorted(groups, key=lambda g: (GROUP_ORDER.index(g) if g in GROUP_ORDER else 99, g)):
        lines.append(f"{g}:")
        for name, mod in sorted(groups[g]):
            aliases = getattr(mod, "ALIASES", [])
            label = name + (f" ({', '.join(aliases)})" if aliases else "")
            lines.append(f"  {label:<22} {getattr(mod, 'HELP', '')}")
        lines.append("")
    return "\n".join(lines)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    cmds = load_commands()
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(usage(cmds))
        return 0
    if argv[0] in ("--version", "version"):
        print(f"ase-tools {__version__}")
        return 0
    name, rest = argv[0], argv[1:]
    mod = cmds.get(name)
    if mod is None:
        print(f"unknown command: {name}\n")
        print(usage(cmds))
        return 2
    if getattr(mod, "PASSTHROUGH", False):
        # wraps an original script that parses sys.argv itself
        return mod.run(rest) or 0
    parser = argparse.ArgumentParser(prog=f"ase {name}", description=getattr(mod, "HELP", None))
    mod.add_arguments(parser)
    args = parser.parse_args(rest)
    return mod.run(args) or 0


if __name__ == "__main__":
    sys.exit(main())
