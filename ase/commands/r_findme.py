"""ase findme: Find every save with a character for a Steam ID / names. Runs ase/reports/findme.py with its own options."""
import runpy
import sys

NAME = "findme"
GROUP = "Reports"
HELP = "Find every save with a character for a Steam ID / names"
PASSTHROUGH = True


def run(argv):
    old = sys.argv
    sys.argv = ["ase findme"] + list(argv)
    try:
        runpy.run_module("ase.reports.findme", run_name="__main__")
    finally:
        sys.argv = old
