"""ase stats: Server lifespan/activity from extracts -> server_stats.csv. Runs ase/reports/stats.py with its own options."""
import runpy
import sys

NAME = "stats"
GROUP = "Reports"
HELP = "Server lifespan/activity from extracts -> server_stats.csv"
PASSTHROUGH = True


def run(argv):
    old = sys.argv
    sys.argv = ["ase stats"] + list(argv)
    try:
        runpy.run_module("ase.reports.stats", run_name="__main__")
    finally:
        sys.argv = old
