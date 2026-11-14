# ase-tools

Python tools for reading **ARK: Survival Evolved** save files, including the final **v11** save format that no other public tool reads.

Built to archive and analyze ~400GB of official ASE server saves (2015–2023): every tame, every cryopod, every egg, and every bloodline.

## What works today

- **`arkextract.py`** reads ASE saves from version 5 through 11 directly, with no server needed. It extracts tamed dinos, cryopodded dinos, fertilized eggs, and pregnancies. It was verified byte for byte against the DinoDump server plugin: 90,382 of 90,382 items matched.
- **DinoDump**, an ArkServerApi plugin, dumps the same data from a running server. It's the reference used to verify the reader.
- **Builder:** dedupes dinos across saves by their permanent two-part ID, builds parent, child, and ancestor links, flags anomalies, and writes per-dino JSON plus SQLite.
- **Analysis tools:** species census, server coverage, activity stats, rankings, missing-save reports, item counts, and finding a player across saves.

## Where it's going

A modular toolkit with the full feature set of Qowyn's ark-tools, rebuilt in Python on a v11-capable reader, plus a lot ark-tools never had.

- [docs/ark-tools-feature-map.md](docs/ark-tools-feature-map.md): every ark-tools command and option, with port status
- [docs/architecture.md](docs/architecture.md): module layout, build order, and new features

## What's not in this repo

No save files and no dumps. They're huge and they're Wildcard's data. Personal settings (Steam IDs, character names, paths) go in `config.local.toml`, which is gitignored.

## Credits

Format knowledge for older save versions comes from Qowyn's [ark-tools](https://github.com/Qowyn/ark-tools) and [ark-savegame-toolkit](https://github.com/Qowyn/ark-savegame-toolkit) (MIT). The v11 decoding was reverse engineered from scratch for this project.
