#!/usr/bin/env python3
"""Run ase-tools from the repo root without installing:  python ase.py <command> ..."""
import multiprocessing as mp
import sys

from ase.cli import main

if __name__ == "__main__":
    mp.freeze_support()
    sys.exit(main())
