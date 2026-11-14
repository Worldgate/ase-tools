# ARK save toolkit — handoff (Oct 2026)

Goal: turn the scripts below into one coherent system for processing ASE `.ark` saves
(official 2023-09-30 shutdown saves + older monthly/legacy ones), feeding a dino genealogy
database/site, stats, and re-import of tribe items/pods into a live server (ShadowCloud boxes).

User: not a coder; wants finished drop-in files. Runs Windows now (32 threads, 384 GB RAM,
8x10k SAS array), moving the box to Linux (ASE server via arkmanager). DinoDump/ArkApi = Windows only.
Data: ~1,782 official saves extracted (all OK incl. Ragnarok), more monthly sets being downloaded.

## Scripts (all standard-library Python)
| file | role | status |
|---|---|---|
| arkextract.py | MAIN. .ark/.zip/folder -> `<save>.extract.zip` (dinos, dinos_raw, pods.jsonl+bin, eggs, names, meta). Parallel, skip-done, auto-redo on version bump (EXTRACTOR="arkextract.py 4"), errors.log, --compare vs DinoDump | verified |
| arkcensus.py | species population across extracts -> dino_census.csv | works; species = blueprint names (needs display-name map); egg names partly unmatched (Gigant_Gen2 etc) |
| arkservers.py | every server named by dinos (+ --deep scans pod bytes), coverage %, naming_check.csv (file name vs dinos' own server, LEGACY- prefix, duplicates) | works |
| arkstats.py | server lifespan/activity from meta.json -> server_stats.csv | works |
| arkrank.py | rank extracts by pods/tames/eggs | works |
| arkmissing.py | saves without extracts and why (dup name, no .ark, failed, partial) | works |
| arkitems.py | plain item stacks + placed structures per save, optional --tribe | new, light testing |
| arkheader.py / arkprobe.py | diagnostics (header dump / v11 pointer layout test) | done their job |
| dumpzip.py, arkobjects.py, arkpods.py, arksample.py, findrec.py | early/one-off tools | superseded |

## Verified facts
- v11 format: see V11_FORMAT.md. KEY CORRECTION vs that doc: pointer entry = `uint8 2, uint8 section, int64 offset, int32 (0), int32 nclasses, refs` — the second byte IS the section (confirmed on Aberration233: 175,758 in sec 0, 3,725 in sec 1). Sections are 2 GB chunks, back to back.
- Pods: 90,382/90,382 byte-identical vs DinoDump on Gen2 (incl. hoversails; Zomdodo class ref -1 -> '').
- World dinos: TekStrider etc. fields match DinoDump (levels, TE=1/(1+TamedIneffectivenessModifier), colors, ancestry).
- Header: versions 5–11 supported (v6–8 tested synthetically, v5 untested: inline names). Ragnarok uses the
  embedded-data / data-file-object-map header lists (now parsed).
- Robustness: count/size caps (MAX_PROPERTY 64 MB, record caps), per-object try/except, NaN coords -> null,
  quick pre-scan skips wild dinos and plain items (7x faster).
- ShadowCloud mod boxes (`ShadowCloud/*.sav`): ARK SaveGame, inline names, no GVAS header.
  `SaveGame_Shadow_Stored_Items_C` -> `Stored_Data` array; each element = {`Item_Data_8_611C418F4BE8E99221B4529CFF78310A`
  (StructProperty ItemNetInfo, 95 fields incl. full CustomItemDatas + egg genetics), `Saved_Durability_7_A40378474A1061E5C5DFD6855D66BC22`
  (double), `Saved_Spoil_Time_6_725E72C148CD7C522E310F80E42B2158` (double)}. Array-of-struct elements have NO UE4 array header.
  ObjectProperty in these files = plain FString path. Box list: `SaveGame_Shadow_Used_Inventories_C` / `Array_Used` (StrProperty array).
  Mod pods had 2nd byte array EMPTY; official pods have ~5 KB there — untested whether game accepts either.

## Open / next
1. Decode pod byte arrays (dino mini-save) -> full stats/ancestry/tribe for 32M pod dinos (biggest gap).
2. Database (SQLite): one row per dino id, parents as links, raw bytes stay in extracts.
3. ShadowCloud box builder: tribe -> boxes (~100 pods/box to avoid "overflow"), fresh item IDs, spoil/durability fields.
4. Wild dino extraction option (needs original saves).
5. Display-name map for species/eggs; Fork Qowyn toolkit with V11_FORMAT.md (Java).
6. Server ops: arkmanager instance cfg ark_* overrides ini (ServerPVE, OverrideOfficialDifficulty=5, AllowFlyerCarryPvE).

## Gotchas
- Extract name = save file stem; keep `SERVER (YYYY-MM-DD)` naming so months don't collide.
- Maewing gender flag always female (genderless); 0%/100% F = genderless species.
- Pod "Lvl" in names is user text — real level = LAST "Lvl N" before "(Species)".
- UploadedFromServerName = newline-separated transfer history.
