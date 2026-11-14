# Qowyn ark-tools: complete feature map

This is an inventory of everything Qowyn's **ark-tools** (Java CLI) and the **ark-savegame-toolkit** library it is built on can do. It is the checklist for recreating them in Python on top of our own v11-capable reader.

Source: `github.com/Qowyn/ark-tools` (`App.java`, `*Commands.java`, `data/*.java`) and `github.com/Qowyn/ark-savegame-toolkit`. Both are MIT licensed (Copyright 2016 Roland Firmont). Porting is allowed as long as we keep the copyright and license notice. See [Licensing](#licensing).

**Why a port is needed:** ark-tools stops at the older ASE save versions. It can't read the final v11 format (the 64-byte header extension, four out-of-line sections, and section-indexed CustomItemDatas pointers), and it loads the whole save into memory. That breaks on multi-GB saves. `arkextract.py` already handles v5–v11 and streams. This port puts the ark-tools feature set on top of that.

Status key: ✅ done in our tools · 🟡 partial · ⬜ not started

---

## 1. Global options (apply to every command)

| Option | What it does | Port notes |
|---|---|---|
| `--parallel`, `-p` | Process files on multiple threads | ✅ Our extractor already runs saves in parallel |
| `--thread-count N` | Thread count for parallel tasks | Map to a `--workers` option |
| `--mmap`, `-m` | Memory-map the input file | Use `mmap` in the reader; we already stream |
| `--pretty-printing` | Indented JSON output | Trivial |
| `--stopwatch`, `-s` | Time each phase | Add per-phase timing to the logger |
| `--quiet`, `-q` / `--verbose`, `-v` | Less output / stack traces on corrupt files | Map to logging levels |
| `--lang X` | Load translated names (`ark_data_<lang>.json`) | Low priority |
| `--help`, `-h` | Context help | argparse gives this for free |

---

## 2. Creature lists (category "Creatures")

| Command | Args | Description | Status |
|---|---|---|---|
| `creatures` | SAVE DIR | All creatures, one JSON file per class + `classes.json` index | 🟡 We decode wild dinos, but the pre-scan skips them on purpose |
| `tamed` | SAVE DIR | Tamed creatures only | ✅ `arkextract.py` (plus pods, eggs, pregnancies, which ark-tools never had) |
| `wild` | SAVE DIR | Wild creatures only | ⬜ Easy once wild decoding is switched back on |

**Options:**
- `--include-untameable`: include untameable high-level dinos
- `--statistics`: wrap each list in a statistics block (count, level min/max/avg)
- `--without-index`: skip `classes.json`
- `--clean`: delete old `.json` files in the target directory first
- `--write-all-fields`: write every field, not only the defaults
- `--inventory summary|long`: include each creature's inventory

**Creature fields ark-tools writes** (`data/Creature.java`):
`type, location, myInventoryComponent, id, tamed, team, playerId, female, colorSetIndices, femaleAncestors, maleAncestors, tamedAtTime, tamedTime, tribe, tamer, ownerName, name, imprinter, baseLevel, wildLevels, extraLevel, tamedLevels, allowLevelUps, experience, imprintingQuality, wildRandomScale, isWakingTame, isSleeping, requiredTameAffinity, currentTameAffinity, tamingEffectivness, tamedFollowTarget, tamingTeamID, tamedOnServerName, uploadedFromServerName, tamedAggressionLevel, matingProgress, lastEnterStasisTime`

Our DinoDump/arkextract record already covers more than this: mutation counters, cryopod contents, parent IDs, and the two-part dino ID. Use this list to check we haven't dropped anything ark-tools had.

---

## 3. Players and tribes (category "Players")

| Command | Args | Description | Status |
|---|---|---|---|
| `players` | SAVE DIR | One JSON per player profile | 🟡 `arkfindme.py` reads player data (both `.arkprofile` and embedded) but only to search |
| `tribes` | SAVE DIR | One JSON per tribe, with its dinos, structures, and items | 🟡 `arkitems.py` does per-tribe counts only |
| `cluster` | CLUSTER_DIR OUT_DIR | Everything players uploaded to the cluster (dinos, items, characters) | ⬜ |

**`players` options:**
- `--no-privacy`: include SteamID and IP (off by default, and should stay off by default for us)
- `--naming steamid|playerid`: file naming
- `--inventory summary|long`, `--positions`, `--max-age SECONDS`, `--write-all-fields`

**`tribes` options:**
- `--items`, `--inventory`, `--creatures`, `--structures`, each `summary|long`
- `--bases`: group a tribe's stuff into named bases, using a bases definition
- `--tribeless`: put tribeless players into a synthetic "tribeless" tribe
- `--non-players`: also write a `non-players.json` for NPC factions
- `--write-all-fields`

**Player fields:** `id, steamId, savedNetworkAddress, playerName, tribeId, playerDataVersion, spawnDayNumber, spawnDayTime, isFemale, bodyColors, overrideHeadHairColor, overrideFacialHairColor, headHairIndex, facialHairIndex, playerCharacterName, rawBoneModifiers, playerSpawnRegionIndex, totalEngramPoints, engramBlueprints, numberOfLevelUpPointsApplied, currentStatusValues, percentageOfHeadHairGrowth, percentageOfFacialHairGrowth, myInventoryComponent, location, characterLevel, experiencePoints, lastHypothermalCharacterInsulationValue, lastHyperthermalCharacterInsulationValue`

**Tribe fields:** `name, ownerPlayerId, ownerPlayerName, tribeId, memberNames, memberIds, tribeAdminNames, tribeAdminIds, membersRankGroups, setGovernment, tribeGovernPINCode, tribeGovernDinoOwnership, tribeGovernStructureOwnership, tribeGovernDinoTaming, tribeGovernDinoUnclaimAdminOnly, tribeLog, logIndex, tribeRankGroups`

**Structure fields:** `id, type, location, myInventoryComponent, containerActivated, owningPlayerId, owningPlayerName, linkedStructures, placedOnFloorStructure, ownerName, boxName, bedName, maxHealth, health, targetingTeam`

**Item fields:** `canEquip, canSlot, isEngram, isBlueprint, canRemove, canRemoveFromCluster, isHidden, type, blueprintGeneratedClass, quantity, customName, customDescription, durability, rating, quality, itemStatValues, itemColors, preSkinItemColors, eggColors, eggLevelups, crafterCharacterName, crafterTribeName, craftedSkillBonus, uploadOffset`

**Inventory fields:** `inventoryItems, equippedItems, itemSlots, lastInventoryRefreshTime`

**Dropped item fields:** `type, location, myItem, droppedByName, targetingTeam, originalCreationTime, initialLifeSpan, lifeSpanLeft`

> The tribe log (`tribeLog`) is in that list. If it survives in our saves, it's a goldmine for the genealogy site: tame, kill, and trade events with timestamps.

---

## 4. Converting (file ↔ JSON, both directions)

| Command | Converts | Status |
|---|---|---|
| `m2j` / `mapToJson` | `.ark` → JSON (full object dump) | ⬜ Top priority. It's the "dump everything" mode |
| `p2j` / `profileToJson` | `.arkprofile` → JSON | ⬜ |
| `t2j` / `tribeToJson` | `.arktribe` → JSON | ⬜ |
| `c2j` / `cloudToJson` | cluster/cloud upload file → JSON | ⬜ |
| `l2j` / `localProfileToJson` | `LocalPlayer.arkprofile` → JSON | ⬜ |
| `s2j` / `savToJson` | `.sav` (GVAS) → JSON | 🟡 We decoded an export-gun `.sav` by hand once |
| `j2m`, `j2p`, `j2t`, `j2c`, `j2l`, `j2s` | JSON → each format | ⬜ Writing is a separate, harder milestone |

Option: `--allow-broken-file` reads as much of a truncated or corrupt file as possible. We already have per-object error isolation, so this matches what we do.

---

## 5. Debug

| Command | Args | Description | Status |
|---|---|---|---|
| `classes` | SAVE [OUT] | Every class in the save with object counts | 🟡 `arkcensus.py` does this for species only |
| `dump` | SAVE CLASS [OUT] | Every object of one class, fully decoded | ⬜ Becomes the generic property dump |
| `sizes` | SAVE [OUT] | Class name and byte size of every object | ⬜ Handy for finding what bloats a save |

Options: `--without-dupes`, `--with-names` (friendly names instead of class names).

---

## 6. Editing (writes saves)

| Command | Args | Description | Status |
|---|---|---|---|
| `feed` | SAVE NEW_SAVE | Max food on every tame and reset their time so they don't starve | ⬜ |
| `export` | SAVE JSON | Export one object plus everything attached to it (components, referenced objects). By `--creature NAME`, `--dinoid ID`, `--object INDEX`, or `--class CLASS`. Flags: `--without-references`, `--without-components` | ⬜ This is "revive a dino from a backup" |
| `import` | SAVE JSON NEW_SAVE | Put exported objects into another save | ⬜ |
| `modify` | INPUT MODIFICATION OUTPUT | Apply a scripted edit file (e.g. delete operations). `--file-format map\|tribe\|profile\|cluster\|localprofile`, `--require-empty` | ⬜ |

These need a **writer** for the v11 format, which nobody has. It's the hardest part of the port and can come last. `export` without `import` is still useful on its own, since it gives a complete JSON bundle of one dino or base.

---

## 7. Database output

| Command | Description | Status |
|---|---|---|
| `db DRIVER SAVE URI [CLUSTER_DIR]` | Read the save, all players, tribes, and cluster data, and send it to a driver | 🟡 `dinodump_build.py` writes SQLite for dinos |
| `db-drivers` | List drivers and their parameters | ⬜ |

The only built-in driver is **JSON**, which writes to a file or **POSTs to an http(s) URL**. It takes per-type field lists (`creatureFields`, `inventoryFields`, `itemFields`, `droppedItemFields`, `playerFields`, `structureFields`, `tribeFields`) and `writeEmpty`. Options: `--config FILE`, `--param KEY=VALUE`.

That POST-to-URL driver is basically the "push to the website API" idea, built in.

---

## 8. Settings and data

| Command | Description | Status |
|---|---|---|
| `latlon` | Export the per-map lat/lon calculator (UE coordinates → in-game GPS) | ⬜ Needed for any map view |
| `update-data` | Download `ark_data.json` (class → friendly name tables) and translations | ⬜ We'll ship our own name table instead |
| `version` | Show version | Trivial |

---

## 9. Library features (ark-savegame-toolkit) worth noting

- Readers and writers for: `ArkSavegame` (.ark), `ArkProfile`, `ArkTribe`, `ArkCloudInventory` (cluster), `ArkLocalProfile`, `ArkSavFile` (GVAS .sav)
- **HibernationEntry**: objects stored in the hibernation section (dinos in stasis away from players). We need to confirm our reader catches these in every save version.
- Name table handling (`NameCollector`, `NameContainer`, `NameSizeCalculator`), which is needed for writing
- Full Unreal property and struct type coverage under `properties/`, `structs/`, and `arrays/`, our reference for any property type we haven't hit yet
- Binary ↔ JSON round-trip (`JsonFormat`, `BinaryFormat`)

---

## Licensing

ark-tools and ark-savegame-toolkit are MIT licensed. If we port code (rather than reimplement from the documented format), keep `Copyright (c) 2016 Roland Firmont` and the MIT notice in a `THIRD_PARTY_LICENSES` file. Our own v11 work is original and not affected.
