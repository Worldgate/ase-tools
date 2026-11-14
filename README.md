# ase-tools

Python tools for reading **ARK: Survival Evolved** save files, including the final **v11** save format that no other public tool reads.

Built to archive and analyze ~400GB of official ASE server saves (2015–2023): every tame, every cryopod, every egg, and every bloodline.

## Quick start

Python 3.8+, standard library only. Nothing to install. Run it from the repo folder:

```
python ase.py                                   list every command
python ase.py tamed SAVES... --out extracts     tamed dinos, pods, eggs -> <save>.extract.zip
python ase.py pods extracts --out pods          decode the dino inside every cryopod
python ase.py build --scan extracts -o dataset  one record per dino, genealogy, SQLite
python ase.py info SAVE                         header, version, sections, counts
python ase.py classes SAVE                      every class with counts
python ase.py dump SAVE Rex_Character_BP_C      every object of a class, fully decoded
python ase.py wild SAVE / creatures SAVE        wild / all creatures
python ase.py m2j SAVE out.jsonl                the whole save as JSON lines
```

`SAVE` can be a `.ark`, an official save `.zip`, or a folder of them. `tamed` writes the same files `arkextract.py` did, with the same version tag, so existing extracts are not redone.

## What works today

- **Reads ASE saves v5 through v11 directly, with no server.** It was verified byte for byte against the DinoDump server plugin: 90,382 of 90,382 items matched on Gen2.
- **Cryopods decoded into real dinos:** permanent ID, stats, colors, mutations, and ancestry.
- **Dataset builder:** one record per dino across thousands of saves, with parents, children, ghost ancestors, anomaly flags, per-dino JSON, and SQLite.
- **ark-tools commands:** `tamed`, `wild`, `creatures`, `classes`, `dump`, `sizes`, and `m2j`, with more on the way. See [docs/PARITY.md](docs/PARITY.md).
- **Reports:** species census, server coverage, activity stats, rankings, missing saves, item counts, finding a player across saves, and ShadowCloud boxes.

## Repo layout

| Folder | What's in it |
|---|---|
| `ase/` | **The toolkit.** `core/` (save reader, v11 sections, cryopod decoder), `model/` (dino, egg, creature records), `commands/` (one file per command, picked up automatically), `reports/`, `extract.py`, `build.py` |
| `ase.py` | Run any command: `python ase.py <command>` |
| `tests/` | Synthetic v9/v11 save builder and the regression test |
| `scripts/` | The original standalone scripts, kept as the reference the package is tested against: `arkextract.py` (the v5–v11 reader) plus `arkcensus`, `arkservers`, `arkstats`, `arkrank`, `arkmissing`, `arkitems`, `arkfindme`, `shadowcloud_read`, `sort_saves`, `dumpzip` |
| `scripts/research/` | `arkheader.py` and `arkprobe.py`, the diagnostics that cracked v11 |
| `scripts/old/` | Early one-off tools superseded by `arkextract.py` (kept for reference) |
| `server/` | The plugin pipeline: `dinodump_batch.py` (multi-slot runner), `batch_config.py`, `dinodump_build.py` + `dinodump_config.py` (dedupe, genealogy, SQLite), `dinodump_decode.py` (cryopod bytes) |
| `plugin/DinoDump/` | The C++ ArkServerApi plugin. `ArkApiSDK/` inside it is the API's headers and `ArkApi.lib` (MIT, GameServersHub/Michidu) |
| `legacy-devkit-mod/` | The first approach, a DevKit mod that printed to the server log. Replaced by the plugin |
| `docs/` | `V11_FORMAT.md` (the format spec), `HANDOFF.md` (state of the project as of Oct 2026), the ark-tools feature map, and the architecture plan |

`scripts/` and `server/` are the October 2026 originals, unchanged. `ase/` is the modular version of the same code. It is tested to produce identical output.

## Progress

<!-- STATUS:START -->
### ark-tools parity

**Overall:** `██████░░░░░░░░░░░░░░`  32% (30 commands: 7 done, 5 partial, 18 planned)

| Category | Progress | Commands |
|---|---|---|
| Creatures | `████████████████████` 100% | ✅&nbsp;`creatures` ✅&nbsp;`tamed` ✅&nbsp;`wild` |
| Players | `███████░░░░░░░░░░░░░`  33% | 🟡&nbsp;`players` 🟡&nbsp;`tribes` ⬜&nbsp;`cluster` |
| Converting | `██░░░░░░░░░░░░░░░░░░`   8% | 🟡&nbsp;`m2j` ⬜&nbsp;`p2j` ⬜&nbsp;`t2j` ⬜&nbsp;`c2j` ⬜&nbsp;`l2j` 🟡&nbsp;`s2j` ⬜&nbsp;`j2m` ⬜&nbsp;`j2p` ⬜&nbsp;`j2t` ⬜&nbsp;`j2c` ⬜&nbsp;`j2l` ⬜&nbsp;`j2s` |
| Debug | `████████████████████` 100% | ✅&nbsp;`classes` ✅&nbsp;`dump` ✅&nbsp;`sizes` |
| Editing | `░░░░░░░░░░░░░░░░░░░░`   0% | ⬜&nbsp;`feed` ⬜&nbsp;`export` ⬜&nbsp;`import` ⬜&nbsp;`modify` |
| DB | `█████░░░░░░░░░░░░░░░`  25% | 🟡&nbsp;`db` ⬜&nbsp;`db-drivers` |
| Settings & Update | `███████░░░░░░░░░░░░░`  33% | ⬜&nbsp;`latlon` ⬜&nbsp;`update-data` ✅&nbsp;`version` |

### Beyond ark-tools

**Overall:** `████████████░░░░░░░░`  59% (9 done, 1 partial, 6 planned)

- ✅ pods / eggs / pregnancies
- ✅ v11 save format
- ✅ cross-save dedupe
- ✅ genealogy graph
- ✅ anomaly flags
- ✅ server coverage
- ✅ species census
- ✅ find player across saves
- ✅ pod dinos fully decoded (32M pods)
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
- [docs/PARITY.md](docs/PARITY.md): ase-tools vs ark-tools, command by command: what we match, what they can do that we can't, and the reverse
- [docs/ark-tools-feature-map.md](docs/ark-tools-feature-map.md): every ark-tools command and option, with port status
- [docs/architecture.md](docs/architecture.md): module layout, build order, and new features

## What's not in this repo

No save files and no dumps. They're huge and they're Wildcard's data. Personal settings (Steam IDs, character names, paths) go in `config.local.toml`, which is gitignored.

## Credits

Format knowledge for older save versions comes from Qowyn's [ark-tools](https://github.com/Qowyn/ark-tools) and [ark-savegame-toolkit](https://github.com/Qowyn/ark-savegame-toolkit) (MIT). The v11 decoding was reverse engineered from scratch for this project.
