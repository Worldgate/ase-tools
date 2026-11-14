# batch_config.py — settings for dinodump_batch.py (Windows dump box)
# ---------------------------------------------------------------------------
# Keep next to dinodump_batch.py. Use r"..." for Windows paths.

# --- where things are ------------------------------------------------------

# Your sorted save zips (searched recursively), e.g. the output of sort_saves.py:
#   D:\ArkSaves\sorted\TheIsland\NA-PVE-Official-TheIsland429 (2023-09-30).zip
ZIPS_DIR = r"D:\ArkSaves\sorted"

# Where every finished dump folder goes (shared by all slots). One folder per
# zip, named after the zip: "<zip name>\dinos.jsonl, pods.jsonl, pods.bin ..."
DUMPS_DIR = r"D:\DinoDump\dumps"

# --- which saves -----------------------------------------------------------

# Only do these maps (the map name inside the zip, e.g. "TheIsland",
# "Valguero_P", "Aberration_P"). Empty list = all maps.
ONLY_MAPS = ["TheIsland"]

# Skip zips whose name contains any of these (case-insensitive).
SKIP_NAMES = []

# Order of work: "size_desc" (biggest saves first — packs RAM best),
# "size_asc", or "name".
ORDER = "size_desc"

# --- server slots ------------------------------------------------------------

# One entry per server install. Each must be a SEPARATE install folder with
# the ASE dedicated server, the Server API and the DinoDump plugin (v0.5+).
# Ports must not clash between slots on this machine (Port+1 is used too).
SLOTS = [
    {"name": f"S{i + 1}",
     "server_dir": rf"C:\asmdata\Servers\Server{i + 1}",
     "port": 7777 + 2 * i,
     "query_port": 27015 + i,
     "rcon_port": 27030 + i}
    for i in range(10)
]

# The save folder name the servers load from (AltSaveDirectoryName).
# The .ark is unpacked into  <server_dir>\ShooterGame\Saved\<SAVE_SUBDIR>\<Map>.ark
# If a dump comes back with 0 dinos and 0 pods, the server didn't find the save
# there — check where it created a fresh <Map>.ark and adjust.
SAVE_SUBDIR = "DinoDump"

# RCON stays on so you can poke a stuck server by hand; this is its password.
ADMIN_PASSWORD = "change-me-dinodump"

# --- timing -----------------------------------------------------------------

# Seconds the plugin waits after the map is ready before dumping.
DUMP_DELAY_SECONDS = 30

# Give up on a save after BASE + PER_GB x (size of the .ark in GB) minutes.
TIMEOUT_BASE_MINUTES = 30
TIMEOUT_MINUTES_PER_GB = 15

# --- memory -----------------------------------------------------------------

# Rough RAM a server needs: the map's empty cost + this many GB per GB of save.
# Start conservative; the run log records how long each save took so you can tune.
MAP_BASE_RAM_GB = {
    "Ragnarok": 14,
    "default": 8,
}
RAM_GB_PER_SAVE_GB = 12

# Always leave this much RAM free for Windows and everything else.
RAM_RESERVE_GB = 24

# --- extras -----------------------------------------------------------------

# Also unpack .arkprofile / .arktribe files from the zip (player + tribe data).
UNPACK_PROFILES = True

# Include wild dinos in the dumps (much bigger, rarely useful).
INCLUDE_WILD = False

# Optional: get a phone notification when the whole batch finishes, via ntfy
# (https://ntfy.sh or your own ntfy server), e.g. "https://ntfy.sh/my-secret-topic".
NTFY_URL = ""

# Extra server launch options, if you need any.
EXTRA_ARGS = "-server -log -NoBattlEye"
