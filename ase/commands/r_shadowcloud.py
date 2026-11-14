"""ase shadowcloud: Show the contents of a ShadowCloud mod storage .sav. Runs ase/reports/shadowcloud_read.py with its own options."""
import runpy
import sys

NAME = "shadowcloud"
GROUP = "Tools"
HELP = "Show the contents of a ShadowCloud mod storage .sav"
PASSTHROUGH = True


def run(argv):
    old = sys.argv
    sys.argv = ["ase shadowcloud"] + list(argv)
    try:
        runpy.run_module("ase.reports.shadowcloud_read", run_name="__main__")
    finally:
        sys.argv = old
