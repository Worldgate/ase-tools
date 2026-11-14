"""ase census: Species population across extracts -> dino_census.csv. Runs ase/reports/census.py with its own options."""
import runpy
import sys

NAME = "census"
GROUP = "Reports"
HELP = "Species population across extracts -> dino_census.csv"
PASSTHROUGH = True


def run(argv):
    old = sys.argv
    sys.argv = ["ase census"] + list(argv)
    try:
        runpy.run_module("ase.reports.census", run_name="__main__")
    finally:
        sys.argv = old
