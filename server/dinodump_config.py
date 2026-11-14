# dinodump_config.py — settings for dinodump_build.py
# ---------------------------------------------------------------------------
# Keep this file next to dinodump_build.py. Anything given on the command
# line overrides what's here. Paths are Linux-style; ~ is expanded.

# --- where things are ------------------------------------------------------

# Folder holding all the plugin's dump folders (searched recursively for
# dinos.jsonl / pods.jsonl). Used when you run the builder with no folders.
DUMPS_DIR = "~/dinodump/dumps"

# Where the finished dataset goes.
OUT_DIR = "~/dinodump/out"

# --- naming the source of each save ----------------------------------------

# Dump folders (or their parent folder) named like
#   "OC-PVE-Official-TheIsland97 (2023-09-30)"
# give the server name and save date. This is the pattern that reads them:
# group 1 = server name, group 2 = date (YYYY-MM-DD). A same-day suffix
# like "(2020-12-02-2)" is allowed; same-day snapshots sort by that number.
FOLDER_NAME_PATTERN = r"^(.*?)\s*\((\d{4}-\d{2}-\d{2})(?:-\d+)?\)\s*$"

# A source.json inside a dump folder always wins over the folder name:
#   {"server": "OC-PVE-Official-TheIsland97", "date": "2023-09-30"}

# --- performance -----------------------------------------------------------

# Processes used to decode cryopods. None = number of CPU cores minus one.
WORKERS = None

# --- what gets written -----------------------------------------------------

# One JSON file per dino under OUT_DIR/dinos/<origin server>/<species>/<bucket>/
WRITE_DINO_FILES = True

# Indentation of the per-dino files. 1 = readable, None = compact (smaller).
DINO_FILE_INDENT = 1

# How many trailing digits of the dino ID pick its sub-folder.
# 2 -> 100 folders per species. Raise to 3 for huge species folders.
BUCKET_DIGITS = 2

# Folder name used when a dino has no origin server recorded.
UNKNOWN_SERVER_FOLDER = "_Unknown"

# --- privacy (for public releases) ------------------------------------------

# Replace tamer / owner / imprinter names and player IDs with stable
# stand-ins ("Player-1a2b3c4d"). The same person always gets the same one.
ANONYMIZE_PLAYERS = False

# Same for tribe names (tribe IDs are kept either way).
ANONYMIZE_TRIBES = False

# --- classifying records ----------------------------------------------------

# Checked in order against the lower-cased class path; first match wins.
# Anything that matches nothing is a "creature".
CATEGORY_RULES = [
    ("bee", ["bee_queen", "/bee/"]),
    ("vehicle", ["raft", "motorboat"]),
]

# Categories left out of breeding checks (level/point rule).
# They're still in the dataset.
SKIP_BREEDING_CHECKS = {"bee", "vehicle", "wild"}

# --- mutation counters -------------------------------------------------------

# Counters above this are flagged "huge" (wrapped / exploited);
# below 0 are flagged "negative".
MUTATION_COUNTER_NORMAL_MAX = 255
