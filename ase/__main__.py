import multiprocessing as mp
import sys

from .cli import main

if __name__ == "__main__":
    mp.freeze_support()
    sys.exit(main())
