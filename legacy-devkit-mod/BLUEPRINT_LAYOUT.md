# DinoDump — Blueprint Layout (ASE DevKit)

What this mod does: when triggered, it walks every tamed dino (and every
cryopod) on the server and prints one short line of JSON per item into the
server log. `dinodump_parse.py` turns those lines into per-dino files and a
database. `dinodump_batch.py` runs it across all your saves unattended.

Node and variable names below are from memory of the ASE DevKit. When a name
doesn't show up exactly, search the right-click menu (with "Context
Sensitive" unticked) for the key word — e.g. "Ancestor", "Mutation",
"Imprint". Fix the name here once you find it, and the rest still holds.

---

## 0. Mod skeleton

1. Create the mod folder in the DevKit like any mod (Content/Mods/DinoDump).
2. Make a **PrimalGameData** child for the mod (the mod's data asset).
3. Make an **Actor** Blueprint called `DinoDumper`.
4. In the mod's PrimalGameData, add `DinoDumper` to
   **Server Extra World Singleton Actor Classes**.
   That spawns exactly one DinoDumper on the server when the map loads.

Everything below lives inside `DinoDumper`.

---

## 1. Variables on DinoDumper

| Name            | Type                         | Purpose                              |
|-----------------|------------------------------|--------------------------------------|
| `Queue`         | Array of PrimalDinoCharacter | dinos waiting to be dumped           |
| `PodQueue`      | Array of PrimalItem          | cryopods waiting to be dumped        |
| `BatchSize`     | Int = 25                     | how many per tick (keeps server alive)|
| `CountDinos`    | Int                          | totals for the END line              |
| `CountAnc`      | Int                          |                                      |
| `CountPods`     | Int                          |                                      |
| `bRunning`      | Bool                         | stops double runs                    |
| `bAutoMode`     | Bool                         | set when started by the batch runner |

---

## 2. Triggers (two ways in, same dump)

**Auto mode (for the 400 GB batch)**
```
Event BeginPlay
 → Has Authority? (server only)
 → Delay 90 seconds            (let the save finish loading)
 → read option "DinoDumpAuto"  (see note)
 → if true: set bAutoMode = true → call StartDump
```
Note: the batch runner passes `?DinoDumpAuto=1` on the server's launch
line. ARK has Blueprint nodes for reading server options (look for
"Get Int Option" / "Get String Option" / "Has Option"). If none of them
can see a URL option, the fallback is to build a second copy of the mod
where BeginPlay always calls StartDump — your dump server is a dedicated
install anyway.

**Command mode (manual, for testing)**
```
Admin types:  cheat ScriptCommand dinodump
 → the mod's ScriptCommand event fires with the text "dinodump"
 → if text == "dinodump": call StartDump
```
Search for "ScriptCommand" in the event list to find the hook. If it's
awkward, any trigger works (an admin-only item, a key) — it only has to
call StartDump.

---

## 3. StartDump (custom event)

```
StartDump
 → if bRunning: return
 → set bRunning = true, zero the counters
 → Emit:  DINODUMP|RUN|{"map":"<level name>","ver":"1"}
 → Get All Actors Of Class (PrimalDinoCharacter) → filter → Queue
       keep only tamed dinos: "Is Tamed" (or TargetingTeam >= 50000)
 → Collect cryopods into PodQueue (section 6)
 → Set Timer by Event: DumpTick, every 0.05 s, looping
```

---

## 4. DumpTick (custom event, runs on the timer)

```
DumpTick
 → repeat BatchSize times:
     if Queue not empty: pop one → DumpDino(it)
     else if PodQueue not empty: pop one → DumpPod(it)
     else: FinishDump, stop
```

---

## 5. DumpDino (function, input: Dino)

Get the dino's **status component** (MyCharacterStatusComponent) once
and reuse it.

**5a. The main line (D)** — build one string with Append nodes:

```
DINODUMP|D|{"id1":…,"id2":…,"cls":"…","species":"…","name":"…", … }
```

| Key         | Where it comes from                                        |
|-------------|------------------------------------------------------------|
| `id1`,`id2` | Dino → **DinoID1**, **DinoID2** (the hidden ID halves)     |
| `cls`       | Get Class → Get Object Name (e.g. Rex_Character_BP_C)      |
| `species`   | Dino → **DescriptiveName**                                 |
| `name`      | Dino → **TamedName**                                       |
| `female`    | Dino → **bIsFemale** (write 1 or 0)                        |
| `tribe_id`  | Dino → **TargetingTeam**                                   |
| `tribe`     | Dino → **TribeName**                                       |
| `tamer`     | Dino → **TamerString**                                     |
| `imprinter` | Dino → **ImprinterName**                                   |
| `server`    | Dino → **TamedOnServerName**                               |
| `neutered`  | Dino → **bNeutered** (1/0)                                 |
| `baby`      | Dino → **bIsBaby** (1/0)                                   |
| `baby_age`  | Dino → **BabyAge** (0–1)                                   |
| `lvl_base`  | Status → **BaseCharacterLevel**                            |
| `lvl_extra` | Status → **ExtraCharacterLevel**                           |
| `imprint`   | Status → **DinoImprintingQuality** (0–1)                   |
| `te`        | Dino → **TamingEffectiveness** / TamedIneffectivenessModifier |
| `mut_f`     | Dino → **RandomMutationsFemale**                           |
| `mut_m`     | Dino → **RandomMutationsMale**                             |
| `colors`    | Dino → **ColorSetIndices** (6 bytes) → `[a,b,c,d,e,f]`     |
| `wild`      | Status → **NumberOfLevelUpPointsApplied** (12) → `[…]`     |
| `tamed`     | Status → **NumberOfLevelUpPointsAppliedTamed** (12) → `[…]`|
| `max`       | Status → **MaxStatusValues** (12) → `[…]`                  |
| `x`,`y`,`z` | Get Actor Location                                         |
| `tamed_time`| Dino → **TamedTimeStamp**                                  |
| `cryo`      | 0 for live dinos (1 if it came out of a pod, section 6)    |

Rules for building the string:
- Text values go inside quotes. **Escape them first:** Replace `\` with
  `\\`, then Replace `"` with `\"`. Player-typed names will break the
  line otherwise.
- Numbers go in bare (no quotes). Bools as 1/0.
- Arrays: For Each → Append value + "," → trim the last comma → wrap in [ ].
- If a field can't be found, leave it out. The parser keeps whatever is
  there and stores the raw line too.

**5b. Ancestry lines (A)** — one line per entry, so lines stay short:

```
For Each entry in Dino → DinoAncestors        (line = "F")
For Each entry in Dino → DinoAncestorsMale    (line = "M")
  Emit: DINODUMP|A|{"id1":…,"id2":…,"line":"F","i":<loop index>,
                    "mn":"<MaleName>","m1":<MaleDinoID1>,"m2":<MaleDinoID2>,
                    "fn":"<FemaleName>","f1":<FemaleDinoID1>,"f2":<FemaleDinoID2>}
```
`id1`/`id2` here are the dino being dumped, so the parser knows whose
ancestry it is. Each ancestry entry is a struct; Break it to get the six
fields.

Add 1 to CountDinos, and the number of A lines to CountAnc.

---

## 6. Cryopods

**Collecting them (in StartDump):**
```
For each actor class: PrimalStructureItemContainer, PrimalCharacter
  Get All Actors Of Class → each actor → MyInventoryComponent
    → InventoryItems + EquippedItems
    → keep items whose class name contains "Cryopod" (or "SoulTrap" for mods)
    → add to PodQueue
```
(Containers cover boxes, fridges, vaults and death bags; characters cover
players and dinos carrying pods.)

**DumpPod — start simple (raw mode):**
```
Emit: DINODUMP|C|{"cls":"<item class>","owner":"<container or character name>",
                  "strings":[…],"floats":[…]}
```
taken from the item's **CustomItemDatas** array (CustomDataStrings and
CustomDataFloats). The parser saves these as-is in cryopods_raw.jsonl.
Check them on the test map to see what they hold.

**DumpPod — full mode (if raw mode isn't enough):** deploy the pod's
creature at a spot far off the map, run DumpDino on it with `cryo` = 1
and `"in":"<container name>"` added, then destroy it. This only runs on
a throwaway copy of the save that never gets saved, so nothing is lost.
Do raw mode first; only build this if you need it.

---

## 7. FinishDump

```
FinishDump
 → Clear the timer
 → Emit: DINODUMP|END|{"dinos":CountDinos,"anc":CountAnc,"pods":CountPods}
 → set bRunning = false
 → if bAutoMode: Delay 10 s → Execute Console Command "DoExit"
```
Do **not** call SaveWorld anywhere. The batch runner watches for the END
line and kills the server itself if DoExit doesn't work.

---

## 8. Emit (function, input: Text)

One place for output, so you only have to fix it once. Test these in
order on the test map and keep the first one that lands in
`ShooterGame/Saved/Logs/ShooterGame.log`:

1. **Print String** with "Print to Log" ticked (may be stripped from
   shipping servers — test it)
2. An ARK-specific log or server-log node, if the DevKit has one
   (search "Log")
3. A server chat broadcast (chat is written to the log when the server
   runs with `-servergamelog`; the batch runner already passes it)

The parser looks for `DINODUMP|` anywhere in a line, so timestamps and
prefixes the log adds are fine.

---

## 9. Test map checklist (do this before the 400 GB)

Set up in a small save:
- two tamed parents, bred, plus their baby (ancestry), then breed the
  baby once more (grandparent ancestry)
- one dino with a mutation
- one dino with a name containing a quote mark: `Big "Red"`
- one dino in a cryopod in a box, one in a cryopod in your inventory
- one dino you uploaded and downloaded, if easy

Then check:
1. `DINODUMP|` lines show up in ShooterGame.log at all (section 8)
2. Run the parser → open `out/report.txt`: 0 bad lines, END present
3. Open the grandchild's file → `ancestry` lists the expected names
4. `parents` in the baby's file shows the right mother and father.
   If it's the grandparents instead, open dinodump_parse.py and change
   `PARENT_ENTRY = "last"` to `"first"`
5. `cryopods_raw.jsonl` — see what the pod data holds; decide whether
   full mode (section 6) is needed
