"""ase missing: Saves without extracts, and why. Runs ase/reports/missing.py with its own options."""
import runpy
import sys

NAME = "missing"
GROUP = "Reports"
HELP = "Saves without extracts, and why"
PASSTHROUGH = True


def run(argv):
    old = sys.argv
    sys.argv = ["ase missing"] + list(argv)
    try:
        runpy.run_module("ase.reports.missing", run_name="__main__")
    finally:
        sys.argv = old
