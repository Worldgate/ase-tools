"""ase rank: Rank extracts by pods, tames and eggs. Runs ase/reports/rank.py with its own options."""
import runpy
import sys

NAME = "rank"
GROUP = "Reports"
HELP = "Rank extracts by pods, tames and eggs"
PASSTHROUGH = True


def run(argv):
    old = sys.argv
    sys.argv = ["ase rank"] + list(argv)
    try:
        runpy.run_module("ase.reports.rank", run_name="__main__")
    finally:
        sys.argv = old
