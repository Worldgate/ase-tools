"""ase creatures: All creatures, tamed and wild, plus per-class level stats (ark-tools: creatures)"""
from . import _creaturelist

GROUP = "Creatures"
HELP = "All creatures, tamed and wild, plus per-class level stats (ark-tools: creatures)"
add_arguments = _creaturelist.add_arguments


def run(args):
    _creaturelist.run_list(args, "all", "creatures")
