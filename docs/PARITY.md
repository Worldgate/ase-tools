# ase-tools vs Qowyn's ark-tools

Side by side: what ark-tools could do, what `python ase.py` does today, and what's still missing. The progress bars in the README come from `status.json`. This page has the detail behind them.

## Command by command

| ark-tools | ase-tools | Status | Notes |
|---|---|---|---|
| `tamed` | `tamed` (alias `extract`) | ✅ | Also pods, eggs, and pregnancies, which ark-tools never had. Output is byte-identical to `arkextract.py`. |
| `wild` | `wild` | ✅ | JSON lines plus a per-class level summary |
| `creatures` | `creatures` | ✅ | Same. `--inventory`, `--include-untameable`, and `--write-all-fields` aren't there yet |
| `players` | (none) | 🟡 | `findme` can locate a player. Late saves keep players *inside* the .ark, and that's not decoded yet |
| `tribes` | (none) | 🟡 | `items --tribe` counts a tribe's items and structures. No tribe info or logs yet |
| `cluster` | (none) | ⬜ | Cluster upload files |
| `m2j` | `m2j` | 🟡 | Every object fully decoded to JSON lines. **Read-only**: it can't be turned back into a .ark |
| `p2j` `t2j` `c2j` `l2j` | (none) | ⬜ | Profile, tribe, cloud, and local profile files |
| `s2j` | `shadowcloud` | 🟡 | Reads ShadowCloud mod `.sav` boxes only, not GVAS `.sav` in general |
| `j2m` `j2p` `j2t` `j2c` `j2l` `j2s` | (none) | ⬜ | Needs a writer. See "Writing" below |
| `classes` | `classes` | ✅ | CSV, with blueprint paths |
| `dump` | `dump` | ✅ | `--contains` matches partial class names |
| `sizes` | `sizes` | ✅ | Bytes per class and average |
| `feed` | (none) | ⬜ | Needs a writer |
| `export` | (none) | ⬜ | Reading half is easy, writing half needs a writer |
| `import` | (none) | ⬜ | Needs a writer |
| `modify` | (none) | ⬜ | Needs a writer |
| `db` | `build` | 🟡 | SQLite plus per-dino files. No HTTP POST driver yet |
| `db-drivers` | (none) | ⬜ | |
| `latlon` | (none) | ⬜ | Map coordinates → in-game GPS |
| `update-data` | (none) | ⬜ | Friendly species and item names. We'll ship our own table |
| `version` | `version` | ✅ | |

## What ark-tools can do that we can't (yet)

1. **Write saves.** Every `j2*` converter, `feed`, `import`, and `modify`. Nobody has a v11 writer. It's the biggest single piece left, and it's also what ShadowCloud re-imports and "recover a zapped dino" would need.
2. **Players and tribes.** For older saves, that means the `.arkprofile` and `.arktribe` readers. For the final months, the player and tribe data is inside the .ark itself, and we haven't worked out where.
3. **Cluster, cloud, and local profile files.**
4. **Inventories.** ark-tools can list each creature's, player's, and structure's inventory (`--inventory summary|long`).
5. **Bases, tribeless players, and non-player factions** (`tribes --bases --tribeless --non-players`).
6. **Map coordinates** (`latlon`).
7. **Friendly names** (`update-data`, `--with-names`, `--lang`).
8. **The hibernation section.** ark-tools reads it. We check that it's empty (`ase info`) but don't decode entries.
9. **MapProperty values.** We keep them as raw bytes.

## What we can do that ark-tools can't

- **Read v10/v11 saves**: the final official format, with its out-of-line custom-data sections.
- **Multi-GB saves**: a quick pass skims property sizes and skips wild dinos and plain items, about 7x faster. ark-tools loads everything.
- **Cryopods as real dinos**: `pods` decodes the dino inside every pod with its permanent ID, stats, colors, mutations, and ancestry.
- **Eggs and pregnancies**: genetics included.
- **Cross-save identity**: `build` merges a dino's sightings across thousands of saves into one record, keeping the newest copy.
- **Genealogy**: parents, children, and ghost ancestors.
- **Anomaly flags**: wild points that don't add up, and mutation-counter overflows.
- **A ground-truth check**: `tamed --compare` checks a map against the DinoDump plugin's dump.
- **Damaged saves**: per-object error isolation and size caps. One bad object never kills a map.
- **Reports**: census, server coverage and naming checks, activity, rankings, and missing saves.
- **ShadowCloud mod storage boxes.**

## Tests

`python tests/test_regression.py` builds small synthetic v9 and v11 saves (`tests/fixture.py`) and checks:
- `ase tamed` output is **byte-identical** to `scripts/arkextract.py` on both versions.
- `pods` decodes the podded dinos, including one in v11 section 1.
- `build` reads `.extract.zip` files directly. Its SQLite output matches `server/dinodump_build.py` on the same data.
- `creatures`, `classes`, `dump`, and `info` work.

The real-save check (90,382/90,382 against DinoDump on Gen2) was done with `arkextract.py`. Since `ase tamed` produces identical output, it carries over.
