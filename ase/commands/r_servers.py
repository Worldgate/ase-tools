"""ase servers: Every server named by any dino; coverage and naming checks. Runs ase/reports/servers.py with its own options."""
import runpy
import sys

NAME = "servers"
GROUP = "Reports"
HELP = "Every server named by any dino; coverage and naming checks"
PASSTHROUGH = True


def run(argv):
    old = sys.argv
    sys.argv = ["ase servers"] + list(argv)
    try:
        runpy.run_module("ase.reports.servers", run_name="__main__")
    finally:
        sys.argv = old
