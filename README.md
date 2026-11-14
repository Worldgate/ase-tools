# ase-tools

Python tools for reading **ARK: Survival Evolved** save files, including the final **v11** save format that no other public tool reads.

Built to archive and analyze ~400GB of official ASE server saves (2015–2023): every tame, every cryopod, every egg, and every bloodline.

## What works today

- **`arkextract.py`** reads ASE saves from version 5 through 11 directly, with no server needed. It extracts tamed dinos, cryopodded dinos, fertilized eggs, and pregnancies. It was verified byte for byte against the DinoDump server plugin: 90,382 of 90,382 items matched.
- **DinoDump**, an ArkServerApi plugin, dumps the same data from a running server. It's the reference used to verify the reader.
- **Builder:** dedupes dinos across saves by their permanent two-part ID, builds parent, child, and ancestor links, flags anomalies, and writes per-dino JSON plus SQLite.
- **Analysis tools:** species census, server coverage, activity stats, rankings, missing-save reports, item counts, and finding a player across saves.

## Repo layout

| Folder | What's in it |
|---|---|
| `scripts/` | The working tools: `arkextract.py` (the v5–v11 reader) plus `arkcensus`, `arkservers`, `arkstats`, `arkrank`, `arkmissing`, `arkitems`, `arkfindme`, `shadowcloud_read`, `sort_saves`, `dumpzip` |
| `scripts/research/` | `arkheader.py` and `arkprobe.py`, the diagnostics that cracked v11 |
| `scripts/old/` | Early one-off tools superseded by `arkextract.py` (kept for reference) |
| `server/` | The plugin pipeline: `dinodump_batch.py` (multi-slot runner), `batch_config.py`, `dinodump_build.py` + `dinodump_config.py` (dedupe, genealogy, SQLite), `dinodump_decode.py` (cryopod bytes) |
| `plugin/DinoDump/` | The C++ ArkServerApi plugin. `ArkApiSDK/` inside it is the API's headers and `ArkApi.lib` (MIT, GameServersHub/Michidu) |
| `legacy-devkit-mod/` | The first approach, a DevKit mod that printed to the server log. Replaced by the plugin |
| `docs/` | `V11_FORMAT.md` (the format spec), `HANDOFF.md` (state of the project as of Oct 2026), the ark-tools feature map, and the architecture plan |

These are the scripts as they ran in Oct 2026, imported unchanged. The modular rewrite in [docs/architecture.md](docs/architecture.md) comes next.

## Progress

<!-- STATUS:START -->
### ark-tools parity

**Overall:** `███░░░░░░░░░░░░░░░░░`  13% (30 commands: 1 done, 6 partial, 23 planned)

| Category | Progress | Commands |
|---|---|---|
| Creatures | `██████████░░░░░░░░░░`  50% | 🟡&nbsp;`creatures` ✅&nbsp;`tamed` ⬜&nbsp;`wild` |
| Players | `███████░░░░░░░░░░░░░`  33% | 🟡&nbsp;`players` 🟡&nbsp;`tribes` ⬜&nbsp;`cluster` |
| Converting | `█░░░░░░░░░░░░░░░░░░░`   4% | ⬜&nbsp;`m2j` ⬜&nbsp;`p2j` ⬜&nbsp;`t2j` ⬜&nbsp;`c2j` ⬜&nbsp;`l2j` 🟡&nbsp;`s2j` ⬜&nbsp;`j2m` ⬜&nbsp;`j2p` ⬜&nbsp;`j2t` ⬜&nbsp;`j2c` ⬜&nbsp;`j2l` ⬜&nbsp;`j2s` |
| Debug | `███░░░░░░░░░░░░░░░░░`  17% | 🟡&nbsp;`classes` ⬜&nbsp;`dump` ⬜&nbsp;`sizes` |
| Editing | `░░░░░░░░░░░░░░░░░░░░`   0% | ⬜&nbsp;`feed` ⬜&nbsp;`export` ⬜&nbsp;`import` ⬜&nbsp;`modify` |
| DB | `█████░░░░░░░░░░░░░░░`  25% | 🟡&nbsp;`db` ⬜&nbsp;`db-drivers` |
| Settings & Update | `░░░░░░░░░░░░░░░░░░░░`   0% | ⬜&nbsp;`latlon` ⬜&nbsp;`update-data` ⬜&nbsp;`version` |

### Beyond ark-tools

**Overall:** `███████████░░░░░░░░░`  56% (8 done, 2 partial, 6 planned)

- ✅ pods / eggs / pregnancies
- ✅ v11 save format
- ✅ cross-save dedupe
- ✅ genealogy graph
- ✅ anomaly flags
- ✅ server coverage
- ✅ species census
- ✅ find player across saves
- 🟡 pod dinos fully decoded (32M pods)
- 🟡 ShadowCloud box reader
- ⬜ dupe detection
- ⬜ recover (zapped dinos)
- ⬜ ASB export
- ⬜ spawn strings
- ⬜ ASA bridge
- ⬜ public API push

✅ done · 🔨 in progress · 🟡 partial (exists in old scripts, not fully ported) · ⬜ planned. In-progress and partial count as half on the bars.
<!-- STATUS:END -->

To update: edit `status.json`, then run `python tools/update_status.py`.

## Where it's going

A modular toolkit with the full feature set of Qowyn's ark-tools, rebuilt in Python on a v11-capable reader, plus a lot ark-tools never had.

- [docs/ASE_SAVE_FORMAT.md](docs/ASE_SAVE_FORMAT.md): the full ASE save format, v5–v11, with what is verified and what is still open
- [docs/ark-tools-feature-map.md](docs/ark-tools-feature-map.md): every ark-tools command and option, with port status
- [docs/architecture.md](docs/architecture.md): module layout, build order, and new features

## What's not in this repo

No save files and no dumps. They're huge and they're Wildcard's data. Personal settings (Steam IDs, character names, paths) go in `config.local.toml`, which is gitignored.

## Credits

Format knowledge for older save versions comes from Qowyn's [ark-tools](https://github.com/Qowyn/ark-tools) and [ark-savegame-toolkit](https://github.com/Qowyn/ark-savegame-toolkit) (MIT). The v11 decoding was reverse engineered from scratch for this project.
