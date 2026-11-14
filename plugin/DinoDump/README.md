# DinoDump — ARK: Survival Evolved Server API plugin

Dumps tamed dinos (stats, mutations, colors, ancestry, server origin fields)
and cryopods from whatever save the server has loaded. Built for API 3.5x on
the final ASE build (358.24).

## 1. Build it (once)

1. Install **Visual Studio 2026 Community** with the
   **"Desktop development with C++"** workload.
2. Open `DinoDump.sln`. At the top, set the configuration to **Release** / **x64**.
3. **Build → Build Solution.**
4. The finished plugin lands in `Package\DinoDump\` (DinoDump.dll,
   DinoDump.pdb, PluginInfo.json).

The `ArkApiSDK` folder is the API's headers and `ArkApi.lib`, copied from
ServersHub/Framework-ArkServerApi (MIT license, included). They're version
3.55; the plugin looks up every field by name on the running server, so a
3.56 server is fine.

## 2. Install it

1. **Stop the server.**
2. Copy the whole `Package\DinoDump` folder into
   `ShooterGame\Binaries\Win64\ArkApi\Plugins\` so you end up with
   `...\ArkApi\Plugins\DinoDump\DinoDump.dll`.
3. In `ShooterGame\Binaries\Win64\config.json` (the API's own config), set
   `"SaveWorldBeforePluginReload": false`. Otherwise copying a new DLL in
   while the server runs makes the API **save the world** before reloading.
4. Start the server. The API log should show `Loaded plugin DinoDump`, and
   the plugin log (`ArkApi\Plugins\DinoDump\logs` or the main API log) shows
   a line saying whether every field it needs was found.

## 3. Use it

In game, after `enablecheats <adminpassword>`, prefix commands with `cheat`.
Over RCON, send them as-is.

| Command | What it does |
|---|---|
| `cheat dinodump.check` | Lists any game fields/functions missing on this build. |
| `cheat dinodump.probe 3` | **Start here.** Writes EVERY engine property of 3 tamed dinos (bred ones first), 1 wild dino, and 3 cryopods, one JSON file each. |
| `cheat dinodump.all` | Full dump: every tamed dino and every cryopod. Add `wild` to include wild dinos. |
| `cheat dinodump.podtest 3` | **Experimental.** Unpacks 3 cryopods with the game's own code, dumps the dino, deletes it. Throwaway saves only. |

The server freezes while a dump runs. That's expected on a dump server;
don't run it on a live server with players.

Output folder: `ShooterGame\Binaries\Win64\ArkApi\Plugins\DinoDump\`

- `probe_<map>_<time>\` — probe files
- `podtest_<map>_<time>\` — podtest files
- `dumps\<map>_<time>\`
  - `dinos.jsonl` — one dino per line
  - `pods.jsonl` — one pod per line; each byte array points into `pods.bin`
    by offset and length
  - `pods.bin` — raw creature data from inside the pods
  - `run.json` — counts, timings, missing fields. Written **last**, so if it
    exists the dump finished.

### What's in a dino record (`dinos.jsonl`, format `dinodump-raw-v2`)

The same fields as the in-game dino export, plus what the site needs.
Empty text fields are left out.

- **Identity:** `id1`, `id2`, `id64`, `class`, `name_tag`, `species`, `name`,
  `female`, `neutered` (only when true)
- **People:** `tamer`, `owner_name`, `owner_player_id`, `imprinter`,
  `imprinter_player_id` (ARK player IDs, not Steam IDs), `tribe`, `tribe_id`
- **Breeding:** `mutations_maternal`, `mutations_paternal` (raw stored
  values, can be huge or negative), `baby_age`
- **Levels and stats:** `level`, `level_wild`, `imprint`,
  `taming_effectiveness`, `wild_levels[12]`, `tamed_levels[12]`, `max_stats[12]`
- **Colors:** `colors[6]` (color IDs)
- **Origin:** `tamed_on_server`, `uploaded_from_server`,
  `latest_uploaded_from_server`, `previous_uploaded_from_server`,
  `creation_time` (server uptime seconds, not a date)
- **Location:** `location[x,y,z]`
- **Ancestry:** `ancestors_maternal`, `ancestors_paternal`, oldest first. The
  **last** entry of each line is the dino's own parents. Names include the
  level (e.g. `Shadowmane - Lvl 484`).

Stat order: health, stamina, torpidity, oxygen, food, water, temperature,
weight, melee, speed, fortitude, crafting.

## 4. Unattended mode (for the batch runner)

Add to the server's launch options:

- `-DinoDumpAuto` — run the full dump once the server is ready
- `-DinoDumpDelay=60` — seconds to wait after "ready" first (default 60)
- `-DinoDumpWild` — include wild dinos
- `-DinoDumpExit` — kill the server when done, **without saving**
- `-DinoDumpSource="NA-PVE-Official-TheIsland429 (2023-09-30)"` — name the
  dump folder after the save it came from (and write `source.json`), so the
  builder knows the server and date. If that folder already exists, a
  `_rerun_<time>` folder is made instead of overwriting.
- `-DinoDumpOut="D:\DinoDump\dumps"` — put dump folders here instead of
  inside the plugin folder (lets many server installs share one dumps folder)

## Safety notes

- Nothing in the plugin saves the world. `-DinoDumpExit` kills the process
  outright so shutdown can't save either.
- Every field is checked by name before it's read, and each dino and pod is
  read inside a crash guard. A bad one is counted as failed and skipped
  instead of taking the server down.
- `podtest` really spawns dinos (then deletes them). Only use it on copies.
