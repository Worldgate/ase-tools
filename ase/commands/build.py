"""ase build: extracts and/or plugin dumps -> deduped dino dataset with genealogy + SQLite."""
from .. import build

GROUP = "Build"
HELP = "Extracts/plugin dumps -> one record per dino, genealogy, SQLite (was dinodump_build.py)"
PASSTHROUGH = True


def run(argv):
    build.main(argv)
