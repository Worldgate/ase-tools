"""ase dumpzip: Zip DinoDump plugin output, named after each server's save. Runs ase/reports/dumpzip.py with its own options."""
import runpy
import sys

NAME = "dumpzip"
GROUP = "Tools"
HELP = "Zip DinoDump plugin output, named after each server's save"
PASSTHROUGH = True


def run(argv):
    old = sys.argv
    sys.argv = ["ase dumpzip"] + list(argv)
    try:
        runpy.run_module("ase.reports.dumpzip", run_name="__main__")
    finally:
        sys.argv = old
