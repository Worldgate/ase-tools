"""ase items: Plain item stacks and placed structures per save, optional --tribe. Runs ase/reports/items.py with its own options."""
import runpy
import sys

NAME = "items"
GROUP = "Reports"
HELP = "Plain item stacks and placed structures per save, optional --tribe"
PASSTHROUGH = True


def run(argv):
    old = sys.argv
    sys.argv = ["ase items"] + list(argv)
    try:
        runpy.run_module("ase.reports.items", run_name="__main__")
    finally:
        sys.argv = old
