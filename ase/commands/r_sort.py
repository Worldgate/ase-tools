"""ase sort: Sort official save zips into per-map folders. Runs ase/reports/sort_saves.py with its own options."""
import runpy
import sys

NAME = "sort"
GROUP = "Tools"
HELP = "Sort official save zips into per-map folders"
PASSTHROUGH = True


def run(argv):
    old = sys.argv
    sys.argv = ["ase sort"] + list(argv)
    try:
        runpy.run_module("ase.reports.sort_saves", run_name="__main__")
    finally:
        sys.argv = old
