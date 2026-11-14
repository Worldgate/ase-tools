# ARK: Survival Evolved save format v11 — what changed from v9

Worked out in October 2026 against official ASE saves from the 2023-09-30 shutdown
(ScorchedEarth, Gen2, Aberration, Fjordur, Valguero — up to 5 GB files), and verified
byte-for-byte against output from a server-side ArkApi plugin (DinoDump) on Gen2:
90,382 / 90,382 custom-data items identical, including all cryopod byte arrays.

Reference implementation: `arkextract.py` (Python, standard library only).

Everything not listed here is unchanged from v9 (Qowyn's ark-savegame-toolkit is correct for it):
name table, object table, property block, every property type, struct and array encoding.

---

## 1. Header

v9:
```
int16  version            (9)
int32  binaryDataOffset
int32  unknown (0)
int32  nameTableOffset
int32  propertiesBlockOffset
float  gameTime
int32  saveCount
...    sublevel list, embedded data, data-file object map, object table
```

v11: **64 bytes inserted directly after the version**, then the v9 header unchanged:
```
int16  version            (11)
4 x {
  int64  sectionOffset    absolute file offset
  int64  sectionSize      0 = unused (offset then points at end of file)
}
int32  binaryDataOffset   ... rest exactly as v9
```
The sections hold out-of-line custom data (see 2). They are laid out back to back
at the end of the file. One section holds at most ~2 GB (2^31 bytes); a map whose
custom data exceeds that continues in section 1, then 2, then 3.
Seen: Gen2 = 1 section (1.17 GB); Aberration233 = 2 (2.15 GB + 264 MB);
Valguero544 = 2 (2.15 GB + 1.88 GB).

Also seen, harmless: the binaryData -> nameTable gap grew from 16 bytes (v9) to 48+ bytes.

## 2. CustomItemDatas (cryopods, hoversails, starting notes, dermis, eggs' incubator data, ...)

In v9 an item's `CustomItemDatas` (ArrayProperty of StructProperty `CustomItemData`)
contains the full data inline as normal properties.

In v11 the property payload is a **small pointer**, not a property list:

```
int32  entryCount
entryCount x {
  uint8   always 2
  uint8   section           index into the 4 header sections (0, or 1+ past 2 GB)
  int64   offset            relative to that section's start
  int32   0                 (one bee hive on Aberration233 had 1; meaning unknown)
  int32   classCount
  classCount x object reference:
      int32 type
      type 1 -> name (int32 nameTableIndex, int32 instance)
      type 0 -> int32 objectId   (-1 = none; Zomdodo pods use this)
}
```
Typical sizes: 34 bytes (1 entry, 1 class by name), 22 (1 entry, 0 classes).
Bee hives sometimes carry a few extra trailing bytes after the entries; skip them.

NOTE: an earlier reading of this as `int16 flag` gave 2 for section 0 and 258 for
section 1 — 258 is just bytes `02 01`. The second byte is the section.

## 3. Out-of-line record (at sections[section].offset + offset)

Strings here are inline FStrings (int32 length incl. null; negative = UTF-16), not name-table refs.

```
string    customDataName       "Dino", "HoverSailData", "InitData", "Snapshot", "IncubatorData", ...
int32 n;  n x string           strings     (cryopod: [objectName, "Name - Lvl X (Species)", "s,t,a,t,s,", "", "MALE"/"FEMALE"])
int32 n;  n x float            floats      (cryopod: 25 values — stats etc.)
int32 n;  n x string           names       (cryopod: 6 color names)
int32 n;  n x { int32 len; len bytes }   byte arrays (cryopod: [dino object blob, status component blob])
int32 n;  n x double           doubles
```
`classes` come from the pointer (section 2), not the record. `objects` were always empty.
Records end exactly where the next begins.

Cryopod byte arrays are the dino and its status component serialized as a small
self-contained object/property archive (names inline). Decoding those is not covered here.

## 4. Things that bit us in real official saves

- NaN / inf coordinates on some creatures (fell out of the world). Don't round/serialize blindly.
- Corrupt-looking spots exist; bound every count/length by the bytes actually remaining,
  cap a single property at ~64 MB (largest real one is ~20 KB), cap record list counts
  (~10,000 is far above anything real). Unbounded reads turn garbage into multi-GB lists.
- A creature is "tamed" if TargetingTeam >= 50000 and it has DinoID1. Skip wild ones with a
  cheap size-skipping pass before fully decoding — it is most of the runtime on big maps.
- Dino fields: wild/tamed points = status component NumberOfLevelUpPointsApplied[0..11] /
  NumberOfLevelUpPointsAppliedTamed[0..11]; level = BaseCharacterLevel + ExtraCharacterLevel;
  taming effectiveness = 1 / (1 + TamedIneffectivenessModifier); colors = ColorSetIndices[0..5];
  ancestry = DinoAncestors (maternal) / DinoAncestorsMale (paternal), arrays of
  {MaleName, MaleDinoID1, MaleDinoID2, FemaleName, FemaleDinoID1, FemaleDinoID2}.
- Fertilized eggs keep genetics as normal item properties: EggNumberOfLevelUpPointsApplied,
  EggColorSetIndices, EggRandomMutationsFemale/Male, EggDinoAncestors(Male).
- Pregnant mothers: GestationEgg* properties on the dino (may persist after birth — unverified).
- `UploadedFromServerName` often has a leading newline.
