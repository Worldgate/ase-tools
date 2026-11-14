# Architecture plan

Goal: turn the pile of working scripts into one modular Python toolkit. One reader at the bottom, one object model above it, and commands that are plug-in modules. Adding a report or exporter means dropping in one file, never touching the reader.

## Layers

```
┌──────────────────────────────────────────────────────────┐
│  CLI / menu  (ase <command> ...  ·  later: retro TUI)    │
├──────────────────────────────────────────────────────────┤
│  commands/   one module per command, auto-discovered     │
│    tamed  wild  creatures  players  tribes  cluster      │
│    classes  dump  sizes  m2j  census  servers  findme ...│
├──────────────────────────────────────────────────────────┤
│  exporters/  json · jsonl · sqlite · csv · http(POST)    │
│              asb-export · spawn-string                   │
├──────────────────────────────────────────────────────────┤
│  model/      Creature  Player  Tribe  Structure  Item    │
│              Inventory  Egg  Pod  (typed views on        │
│              GameObjects, field lists like ark-tools)    │
├──────────────────────────────────────────────────────────┤
│  core/       reader: header v5–v11, name table, objects, │
│              properties, out-of-line sections, embedded  │
│              data, hibernation, cryopod blobs            │
│              formats: .ark .arkprofile .arktribe cloud   │
│              .sav                                         │
└──────────────────────────────────────────────────────────┘
```

### core/ (the reader)
Source: today's `arkextract.py` and `dinodump_decode.py`, split up.

- `core/archive.py`: the binary reader primitives
- `core/header.py`: save versions 5–11, including the v11 64-byte extension and the four section pointers
- `core/names.py`: name table
- `core/objects.py`: object table, lazy property decoding
- `core/properties/`: one file per Unreal property type
- `core/sections.py`: out-of-line sections, using the section-index byte in each pointer to pick the 2GB section
- `core/embedded.py`: embedded data and the data-file object map (the Ragnarok fix)
- `core/cryopod.py`: decoding the CustomItemDatas byte arrays
- `core/formats/`: profile, tribe, cloud, and `.sav` readers

Rules for core:
- **Streaming and lazy.** Headers and the object table load up front, but properties only decode when someone asks. That keeps the ~7x pre-scan speedup for every command, not just dinos.
- **Per-object error isolation stays.** A bad object becomes an error record. It never kills the run.
- **Sanity caps stay.** Count and size limits protect against corrupt saves causing runaway memory use.
- **Read-only.** Writing gets its own `core/writer/` later, with round-trip tests.

### model/
Typed wrappers like ark-tools' `data/` classes. Each one declares its fields in one table, so `--fields` and `--write-all-fields` work the same everywhere. The canonical dino record from `dinodump_build.py` (two-part ID, parents, mutations, origin server) lives here and is the one schema that exporters, the database, and the website all share.

### commands/
Each command is a module with a small interface:

```python
NAME = "tamed"
HELP = "Tamed creatures, pods, eggs and pregnancies"

def add_arguments(parser): ...
def run(args, ctx): ...      # ctx gives the reader, config, logger, exporter
```

The CLI discovers anything in `commands/` (and later a user plugin folder) automatically. That's the "main script + modules + config" layout.

### exporters/
- `json`: one file per record, or per class (ark-tools style)
- `jsonl`: one line per record, best for 100M+ dinos
- `sqlite`: what `dinodump_build.py` does today
- `http`: POST to an API (ark-tools' JSON driver did this)
- `asb`: ARK Smart Breeding import format
- `spawnstring`: SuperCryoStorage-style paste strings (once that format is decoded)

### config
One `ase.toml` with paths, cache layout (`CACHE_ASE/PVP`, `CACHE_ASE/PVE`, branch folders), worker counts, and caps. Personal stuff like Steam IDs and character names goes in `config.local.toml`, which is gitignored.

## Where today's scripts land

| Script | Becomes |
|---|---|
| `arkextract.py` | `core/*` + `commands/tamed.py` |
| `arkprobe.py` | `tools/probe.py` (dev tool, kept for format research) |
| `dinodump_decode.py` | `core/cryopod.py` |
| `dinodump_build.py` | `model/dino.py` + `commands/build.py` + `exporters/sqlite.py` |
| `dinodump_batch.py` | `server/batch.py` (the plugin path stays as a fallback and verifier) |
| `sort_saves.py` | `commands/sort.py` |
| `dumpzip.py` | `server/dumpzip.py` |
| `arkcensus.py` | `commands/census.py` |
| `arkservers.py` | `commands/servers.py` |
| `arkstats.py` / `arkrank.py` / `arkmissing.py` | `commands/stats.py`, `rank.py`, `missing.py` |
| `arkitems.py` | `commands/items.py` |
| `arkfindme.py` | `commands/findme.py` (IDs from config.local) |
| DinoDump C++ plugin | `plugin/` (its own build) |

## Build order

1. **Restructure without changing behavior.** Move the code into `core/` and `commands/`, and keep `tamed` output byte-identical to today. The 90,382-item match is the regression test.
2. **Generic dump:** `classes`, `sizes`, `dump CLASS`, `m2j`. Once these exist, everything else is just picking fields.
3. **ark-tools parity on reading:** `creatures`/`wild`, `players`, `tribes` (with structures, items, and tribe log), `cluster`, profile and tribe files.
4. **Exporters:** jsonl, http, asb.
5. **Writing** (hardest, last): `export` → `import`, `feed`, `modify`.

## New concepts beyond ark-tools

What ark-tools never had, and this project already does or plans to:

- **Pods, eggs, and pregnancies as first-class records.** ark-tools ignored cryopod contents completely.
- **Cross-save identity and dedupe.** The same dino is tracked by its two-part ID across 1,900+ saves and years of snapshots.
- **Genealogy graph.** Parents, children, and "ghost" ancestors who only exist as a name in a descendant's record.
- **Anomaly flags.** Corrupt mutation counters and level math that doesn't add up.
- **Dupe detection.** One dino ID alive on two servers in the same snapshot.
- **Server coverage.** Every server name ever referenced, measured against the saves you actually have.
- **Lineage of trades.** Follow a dino's imprinter, tamer, and tribe changes across snapshots to see where traded dinos ended up.
- **Recover.** Rebuild a zapped dino from its history as an export bundle, with anti-dupe guards (the original must be gone, one use only, ownership check, audit log).
- **Cross-game bridge.** The same record schema for ASA (via its SQLite saves), so the database and website don't care which game the data came from.
- **Public API.** `api.<site>/v1/ase/...` serving records in an ASB-importable format.
