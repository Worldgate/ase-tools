# ARK: Survival Evolved save format (.ark), versions 5–11

Everything this project knows about the ASE map save format, in one place: what each byte means, how sure we are, and how it was checked.

[V11_FORMAT.md](V11_FORMAT.md) is the original short note on just the v9 → v11 changes. This document is the full picture and supersedes it where they differ.

**Reference implementation:** `scripts/arkextract.py` (standard library Python, reads v5–v11).
**Older-version reference:** Qowyn's [ark-savegame-toolkit](https://github.com/Qowyn/ark-savegame-toolkit) (MIT), which is correct for v5–v9 and stops there.

## How this was verified

- **Test data:** official ASE saves from the 2023-09-30 shutdown (The Island, Scorched Earth, Aberration, Gen2, Fjordur, Valguero, Ragnarok and more, up to ~5 GB per file), plus older monthly and legacy saves going back to June 2015. 1,782 official saves were extracted with zero unreadable files.
- **Ground truth:** a server-side ArkServerApi plugin (`plugin/DinoDump`) that asks the running game for the same data. Because the game decodes its own save, matching the plugin means the reader is right.
- **Result on Gen2:** 90,382 of 90,382 custom-data items (cryopods, hoversails, etc.) were byte-identical, including every cryopod byte array. World dinos matched field for field on levels, stats, colors, taming effectiveness, mutations, imprint, tribe, location, and both ancestry lines.
- **Same map, two versions:** a Scorched Earth map saved as both v9 and v11 gave identical dinos, eggs, and custom-data items through both code paths.

Confidence markers used below:
- ✅ **verified**: checked against the plugin or across versions on real saves
- 🟢 **works**: read correctly on every real save so far, not independently cross-checked
- 🟡 **assumed**: taken from Qowyn's toolkit, or only tested on synthetic files
- ❓ **unknown**: seen, not understood

---

## 0. Conventions

- Little-endian throughout.
- **FString:** `int32 length` then bytes. Length includes the null terminator. Positive = UTF-8/ASCII. Negative = UTF-16LE with `-length` characters. `0` = empty string.
- **Name** (v6+): `int32 index, int32 instance`. `index` is **1-based** into the name table. `instance` 0 means the bare name; `instance N` means `name_(N-1)`. ✅
- **Name** (v5): written inline as an FString (there is no name table). 🟡
- **Object reference:** `int32 kind`, then `kind 0 → int32 objectIndex` (‑1 = none), `kind 1 → Name`. ✅

---

## 1. File layout

```
header
  version, [v11 section table], offsets, gameTime, saveCount
sublevel list
embedded data
data-file object map
object table                    ← one entry per object
...
hibernation data                ← at hibernationOffset (v7+)
name table                      ← at nameTableOffset (v6+)
property block                  ← at propertiesBlockOffset; each object's properties
[v11 out-of-line sections]      ← custom item data, up to 4 × ~2 GB, at the end of the file
```

Read order: header → name table (seek to it) → back to the sublevel list → embedded data → data-file map → object table → properties on demand.

---

## 2. Header

| Field | Type | Versions | Notes |
|---|---|---|---|
| version | int16 | all | 5–11 supported. v10 never seen. |
| section table | 4 × (int64 offset, int64 size) | **v11 only** | 64 bytes inserted right after `version`. See §8. ✅ |
| hibernationOffset | int32 | v7+ | Qowyn calls it this. Our notes called it `binaryDataOffset`. 🟡 |
| shouldBeZero | int32 | v7+ | Always 0. 🟢 |
| nameTableOffset | int32 | v6+ | ✅ |
| propertiesBlockOffset | int32 | v6+ | Object property offsets are relative to this. ✅ |
| gameTime | float32 | all | In-game seconds. 🟢 |
| saveCount | int32 | v9+ | 🟢 |

Status per version:
- **v9, v11:** ✅ verified on real saves
- **v6–v8:** 🟡 synthetic tests only
- **v5:** 🟡 untested (inline names, no name table)

Seen and harmless: the gap between `hibernationOffset` and `nameTableOffset` is 16 bytes on v9 and 48+ on v11. See §7.

---

## 3. Sublevel list ("data files")

```
int32 count
count × FString   sublevel name
```
🟢 Read and kept, not used for anything yet.

## 4. Embedded data

```
int32 count
count × {
  FString path
  int32 parts
  parts × {
    int32 blobs
    blobs × { int32 n; n × int32 }
  }
}
```
Empty on almost every map. **Ragnarok uses it.** Until this was parsed, every Ragnarok save failed to open. ✅ Contents are skipped, not decoded.

## 5. Data-file object map

```
int32 count
count × {
  int32 levelIndex
  int32 n
  n × FString   object name
}
```
Also non-empty on Ragnarok. 🟢 Skipped.

---

## 6. Object table

```
int32 objectCount
objectCount × {
  byte[16]  guid
  Name      className
  int32     isItem          (bool)
  int32     nameCount
  nameCount × Name          object's names; [0] is its own, the rest are its owner chain
  int32     fromDataFile    (bool)
  int32     dataFileIndex
  int32     hasLocation     (bool)
  if hasLocation: 6 × float32   x, y, z, pitch, yaw, roll
  int32     propertiesOffset    relative to propertiesBlockOffset
  int32     shouldBeZero
}
```
✅ The object's index in this table is its **object ID**. Object references (`kind 0`) point here, e.g. a dino's `MyCharacterStatusComponent`.

Minimum entry size is 40 bytes, which the reader uses as a sanity check on `objectCount`.

## 7. Hibernation section (v7+) ❓

At `hibernationOffset`. **`arkextract.py` does not read this section.** Qowyn's layout, for reference:

```
v8+: 4 × int32 unknown
(if position == nameTableOffset → no hibernation data, stop)
int32 unknown1, int32 unknown2
int32 classCount;  classCount × FString
int32 indexCount;  indexCount × int32          (must equal classCount)
int32 entryCount;  entryCount × {
  float x, y, z
  uint8  unknown
  float  unknown
  int32 len; len bytes   → its own small name table
  int32 len; len bytes   → its own object table + properties
  int32 unknown
  int32 classIndex
}
```

What we know:
- On v9 the gap before the name table is exactly 16 bytes. That's the four v8+ ints and nothing else, so **v9 saves had no hibernated objects.**
- On v11 the gap is 48+ bytes, so **something is there.** It's small (tens of bytes), so it's probably an empty header rather than real objects.
- Plugin cross-checks found no dinos missing from the extract that the game itself had. That suggests nothing important hides here on official PC saves.

**To do:** parse it with Qowyn's layout on a v11 save and confirm it's empty. If hibernated objects ever turn up (console-style saves, some private servers), they hold dinos and need to be read.

---

## 8. Name table (v6+)

At `nameTableOffset`:
```
int32 count
count × FString
```
✅ Names starting with `BlueprintGeneratedClass ` hold full blueprint paths. Map the short class name (`Raptor_Character_BP_C`) to its full path through them.

---

## 9. Properties

Each object's property list starts at `propertiesBlockOffset + propertiesOffset` and ends at a property named `None`.

```
Name   name           ("None" = end of list)
Name   type
int32  size           bytes of the value (not counting the extra header fields below)
int32  index          static-array index: Colors[0..5], stats[0..11]
...    type-specific header
...    value (size bytes)
```

| Type | Extra header | Value |
|---|---|---|
| IntProperty, UInt32, Int16, UInt16, Int8, Int64, UInt64, Float, Double | none | fixed-size number |
| BoolProperty | none | **1 byte after the header**, and `size` is 0 ✅ |
| StrProperty | none | FString |
| NameProperty | none | Name |
| ObjectProperty | none | object reference (§0) |
| ByteProperty | Name enumType | `None` → 1 byte; otherwise a Name (enum value) |
| StructProperty | Name structType | native struct (below) or a nested property list ending in `None` |
| ArrayProperty | Name innerType | int32 count, then elements |
| MapProperty | Name keyType, Name valueType | not decoded (kept as raw base64) |

**Native structs** (raw values, not property lists):

| Struct | Layout |
|---|---|
| Vector, Rotator | 3 × float |
| Vector2D | 2 × float |
| Quat, LinearColor | 4 × float |
| Color | 4 × uint8 |
| IntPoint | 2 × int32 |
| Guid | 16 bytes |
| UniqueNetIdRepl | int32 unknown + FString (seen in cryopod blobs) |
| ItemNetID | 2 × uint32 (seen in cryopod blobs) |

Everything else is a nested property list.

**Arrays:**
- Numbers and bools: packed values.
- `ByteProperty` arrays: raw bytes.
- `Str`/`Name`/`Object` arrays: one element after another.
- **Struct arrays in ARK saves have no UE4 per-array struct header.** Each element is just a property list ending in `None`. 🟢 The reader also handles arrays of bare Vectors (12 bytes each) and Quats/LinearColors (16 bytes each) by element size.

**Safety rules** (all learned from real damaged saves):
- Cap any single property at 64 MB. The largest real one is about 20 KB, a v9 cryopod.
- Bound every count by the bytes remaining. Garbage counts otherwise turn into multi-GB lists.
- Decode each object inside its own try/except. One bad object never stops the map.
- Coordinates can be NaN or inf (dinos that fell out of the world). Write them as `null`.

---

## 10. Custom item data (cryopods and friends)

`CustomItemDatas` is an ArrayProperty of StructProperty `CustomItemData` on items. It's used by cryopods, soul traps, hoversails, the starting note, dermis, incubators, and more.

### v9 and earlier: inline ✅
A normal struct array. Each element holds:
`CustomDataName, CustomDataStrings, CustomDataFloats, CustomDataNames, CustomDataDoubles{Doubles}, CustomDataClasses, CustomDataBytes{ByteArrays[{Bytes}]}`

### v11: pointer + out-of-line record ✅

The property value becomes a small pointer:
```
int32 entryCount
entryCount × {
  uint8  2                  always 2
  uint8  section            which of the 4 header sections (0, or 1+ past 2 GB)
  int64  offset             relative to that section's start
  int32  0                  one bee hive on Aberration233 had 1; meaning unknown ❓
  int32  classCount
  classCount × object reference   (Zomdodo pods use kind 0 with -1)
}
```
Typical sizes are 34 bytes (1 entry, 1 class by name) and 22 bytes (1 entry, 0 classes). Bee hives sometimes add a few trailing bytes; skip them.

> **The section byte.** An early reading treated bytes 1–2 as one `int16 flag`, which gave 2 for section 0 and 258 for section 1. 258 is just bytes `02 01`. Confirmed on EU-PVP-Official-Aberration233: 175,758 pods in section 0, 3,725 in section 1.

**Sections** (header §2): up to 4 × (offset, size), laid back to back at the end of the file, each at most ~2 GB (2³¹ bytes). They exist because one block hit the 32-bit limit. Unused sections have size 0. Examples:
- Gen2: 1 section (1.17 GB)
- Aberration233: 2 sections (2.15 GB + 264 MB)
- Valguero544: 2 sections (2.15 GB + 1.88 GB)

**The record** at `sections[section].offset + offset`, with inline FStrings (not name-table references):
```
FString  customDataName        "Dino", "HoverSailData", "InitData", "Snapshot", "IncubatorData", ...
int32 n; n × FString           strings
int32 n; n × float32           floats
int32 n; n × FString           names
int32 n; n × { int32 len; len bytes }   byte arrays
int32 n; n × float64           doubles
```
Classes come from the pointer, not the record. The `objects` list was always empty. Records end exactly where the next begins. Validation: a record starts with a short printable name, 1–128 characters.

### What a cryopod record holds ✅
- **strings:** `[objectName, "Name - Lvl X (Species)", "s,t,a,t,s,", "", "MALE"/"FEMALE"]`. The level in the display name is user-editable text. The real level is the **last** `Lvl N` before `(Species)`.
- **floats:** 25 values (stats and related)
- **names:** 6 color names
- **byte arrays:**
  - **[0]:** the dino and its status component as a mini save (§11)
  - **[1]:** the equipped saddle as one property list, or empty. Official pods carry about 5 KB here.

---

## 11. Cryopod mini save (byte array 0) ✅

A self-contained object archive with **inline FString names** (no name table). Decoder: `server/dinodump_decode.py`, validated field for field against the game's own unpacking.

```
int32 objectCount            (sanity: 0 < n < 1000)
objectCount × object header  (same fields as §6, but names are FStrings)
then each object's property list at its propertiesOffset (relative to the blob start)
```
Properties use the §9 encoding with FString names. That makes a podded dino exactly as decodable as a world dino, including its original two-part ID and full ancestry.

> **Open gap:** `arkextract.py` stores these blobs raw in `pods.bin` but doesn't decode them yet. About 32 million pods across the collection are waiting on this.

---

## 12. Field reference: dinos ✅

A creature counts as **tamed** when `TargetingTeam >= 50000` and it has `DinoID1`. Skip wild ones with a cheap pass that skims property sizes before decoding anything. That's most of the runtime on big maps, and skipping makes extraction about 7x faster.

| Field | Where |
|---|---|
| Permanent ID | `DinoID1`, `DinoID2` → `id64 = (id1 << 32) \| id2`. Survives pods, uploads, and transfers. Clones get new IDs. |
| Name | `TamedName` |
| Sex | `bIsFemale`. Maewing always reads female; species at 0% or 100% female are genderless. |
| Tribe | `TribeName`, `TargetingTeam` (tribe ID) |
| People | `TamerString`, `OwningPlayerName`, `ImprinterName` |
| Mutations | `RandomMutationsFemale` (maternal), `RandomMutationsMale` (paternal). Can be negative from the overflow exploit; flagged, not treated as corruption. |
| Wild points | status component `NumberOfLevelUpPointsApplied[0..11]` |
| Tamed points | status component `NumberOfLevelUpPointsAppliedTamed[0..11]` |
| Level | status `BaseCharacterLevel + ExtraCharacterLevel` |
| Taming effectiveness | `1 / (1 + TamedIneffectivenessModifier)` (status component) |
| Imprint | status `DinoImprintingQuality` |
| Colors | `ColorSetIndices[0..5]` |
| Baby | `BabyAge` < 1 |
| Flags | `bNeutered`, `bIsCloneDino` |
| Servers | `TamedOnServerName`. `UploadedFromServerName` is a **newline-separated transfer history** and often starts with a newline. |
| Created | `OriginalCreationTime` |
| Ancestry | `DinoAncestors` (maternal), `DinoAncestorsMale` (paternal). Each is an array of `{MaleName, MaleDinoID1, MaleDinoID2, FemaleName, FemaleDinoID1, FemaleDinoID2}`. **Capped at 15 generations per side;** the last entry is the immediate parents. Deeper lineage has to be chained across saves. |
| Status component | `MyCharacterStatusComponent` → object ID |

**Stat sanity checks:** wild points sum to `baseLevel − 1`, and tamed points equal the tamed level. Exceptions: **beehive queens** (never meant to level) and **clones**.

**Pregnancy:** `GestationEgg*` properties on the mother (`GestationEggNumberOfLevelUpPointsApplied`, `GestationEggColorSetIndices`, `GestationEggRandomMutationsFemale/Male`, `GestationEggTamedIneffectivenessModifier`). ❓ They may stay on the mother after the birth.

## 13. Field reference: fertilized eggs ✅

Item classes containing `_Fertilized` and `Egg`. Genetics are normal item properties:
`EggNumberOfLevelUpPointsApplied[0..11], EggColorSetIndices[0..5], EggRandomMutationsFemale/Male, EggGenderOverride, EggTamedIneffectivenessModifier, EggDinoAncestors, EggDinoAncestorsMale`. Item identity is `ItemId {ItemID1, ItemID2}`.

---

## 14. Players and tribes 🟡

- **Older saves** keep each character as `<SteamID64>.arkprofile` and each tribe as `<id>.arktribe` next to the `.ark`. Their format is Qowyn's (`ArkProfile`, `ArkTribe`) and is not re-verified here.
- **The final months of official saves have no profile or tribe files.** Player and tribe data is **inside the `.ark`**. `arkfindme.py` finds a player there by searching for the Steam ID text (UTF-8 and UTF-16). Which objects hold it, and how, is ❓ **not decoded yet.** It's needed for ark-tools' `players` and `tribes` commands.

## 15. ShadowCloud mod storage boxes (`ShadowCloud/*.sav`) 🟢

These are ARK SaveGame files with inline names and **no GVAS header**. Reader: `scripts/shadowcloud_read.py`.

- `SaveGame_Shadow_Stored_Items_C` → `Stored_Data` array. Each element has:
  - `Item_Data_8_611C418F4BE8E99221B4529CFF78310A`: StructProperty ItemNetInfo, 95 fields, including full CustomItemDatas and egg genetics
  - `Saved_Durability_7_A40378474A1061E5C5DFD6855D66BC22` (double)
  - `Saved_Spoil_Time_6_725E72C148CD7C522E310F80E42B2158` (double)
- Array-of-struct elements have **no UE4 array header**.
- ObjectProperty here is a **plain FString path**.
- Box list: `SaveGame_Shadow_Used_Inventories_C` / `Array_Used` (StrProperty array).
- Mod-made pods had byte array 1 **empty**. Official pods carry about 5 KB there. ❓ Untested whether the game accepts either one in the other's place.

---

## 16. Open questions

| # | Question | Why it matters |
|---|---|---|
| 1 | Is the v11 hibernation section ever non-empty? | It could hold dinos on some saves |
| 2 | Where do embedded players and tribes live in late saves? | `players` / `tribes` parity |
| 3 | The `int32` after the pointer offset: 0 everywhere, 1 on one bee hive | Completeness |
| 4 | Meaning of each of the 25 cryopod floats | Pod stats without decoding the blob |
| 5 | MapProperty encoding | Not seen on dinos; might matter for structures |
| 6 | v5 and v6–8 on real files | Oldest 2015 saves |
| 7 | Do `GestationEgg*` fields survive the birth? | Avoid phantom pregnancies |
| 8 | Writing v11 | Needed for import/feed/modify, plus re-import into a live server |
