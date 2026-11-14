"""ase wild: Wild creatures with levels, stats, colors and location (ark-tools: wild)"""
from . import _creaturelist

GROUP = "Creatures"
HELP = "Wild creatures with levels, stats, colors and location (ark-tools: wild)"
add_arguments = _creaturelist.add_arguments


def run(args):
    _creaturelist.run_list(args, "wild", "wild")
