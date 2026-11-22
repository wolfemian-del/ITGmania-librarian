> **Provenance:** research report by Grok, 2026-11-22. Landed in the repo with the roadmap (2026-11-22). Verified by Muse against the v1.3.0 engine source — accept. Body below is verbatim as delivered; only this header was added.

# Research: #STEPSTYPE values and display labels

**Roadmap theme 3 / dance-labels item**  
**Scope:** research only — no code changes, no branch, no PR.  
**Version basis:** ITGmania v1.3.0 (`8a3bf8884a`).  
**Signed:** Grok  
**Date:** 2026-11-22  

Tags follow the repo convention:  
`[CODE]` — read in source (file + function or array given)  
`[INFERRED]` — reasoned from the code  
`[UNVERIFIED]` — not determined  
`[RAN]` — executed in this environment  

---

## 1. Complete list of #STEPSTYPE values the engine recognizes

The exact strings written in `.sm` / `.ssc` / cache files are the `szName` fields of the static table `g_StepsTypeInfos` in `GameManager.cpp`. The enum order in `GameConstantsAndTypes.h` matches that table 1:1 (asserted by `static_assert(ARRAYLEN(g_StepsTypeInfos) == NUM_StepsType)`). `[CODE: src/GameManager.cpp g_StepsTypeInfos; src/GameConstantsAndTypes.h enum StepsType]`

| Enum constant | String in file (`#STEPSTYPE:…;`) |
|---|---|
| `StepsType_dance_single` | `dance-single` |
| `StepsType_dance_double` | `dance-double` |
| `StepsType_dance_couple` | `dance-couple` |
| `StepsType_dance_solo` | `dance-solo` |
| `StepsType_dance_threepanel` | `dance-threepanel` |
| `StepsType_dance_routine` | `dance-routine` |
| `StepsType_pump_single` | `pump-single` |
| `StepsType_pump_halfdouble` | `pump-halfdouble` |
| `StepsType_pump_double` | `pump-double` |
| `StepsType_pump_couple` | `pump-couple` |
| `StepsType_pump_routine` | `pump-routine` |
| `StepsType_techno_single4` | `techno-single4` |
| `StepsType_techno_single5` | `techno-single5` |
| `StepsType_techno_single8` | `techno-single8` |
| `StepsType_techno_double4` | `techno-double4` |
| `StepsType_techno_double5` | `techno-double5` |
| `StepsType_techno_double8` | `techno-double8` |
| `StepsType_lights_cabinet` | `lights-cabinet` |

That is the complete set the engine’s string→enum mapping knows. There is no separate “deprecated but still parsed” list inside the table: every entry above is a live `StepsType` value. `[CODE]`

**Values the engine may still parse but no longer supports as first-class styles:** none inside `g_StepsTypeInfos`. Older StepMania families that once existed (kb7, ez2, para, beat, popn, maniax, ds3ddx, karaoke, kickbox, etc.) are **absent** from the ITGmania v1.3.0 table. An unrecognized string is stored as the raw string (`m_StepsTypeStr`) and the enum is set to `StepsType_Invalid`; the chart is not silently rewritten to `dance-single`. `[CODE: Steps::TidyUpData in Steps.cpp — “Don't set the StepsType to dance single if it's invalid… Leave it as StepsType_Invalid”; SetStepsType in NotesLoaderSSC.cpp calls GAMEMAN->StringToStepsType and always keeps the original string in m_StepsTypeStr]`

---

## 2. Family, panel count, player meaning

Taken from the same `g_StepsTypeInfos` row (`szName`, `iNumTracks`, `bAllowAutogen`, `m_StepsTypeCategory`) plus the `StepsTypeCategory` enum. `[CODE: GameManager.cpp; GameConstantsAndTypes.h]`

| String | Family | Tracks (panels) | Category | Play meaning |
|---|---|---|---|---|
| `dance-single` | dance | 4 | Single | One player, one pad |
| `dance-double` | dance | 8 | Double | One player, both pads |
| `dance-couple` | dance | 8 | Couple | Two players, each on their own pad |
| `dance-solo` | dance | 6 | Single | One player, 6-panel (solo) layout |
| `dance-threepanel` | dance | 3 | Single | One player, three-panel layout |
| `dance-routine` | dance | 8 | Routine | Two players share both pads (composite note data) |
| `pump-single` | pump | 5 | Single | One player, one 5-panel pad |
| `pump-halfdouble` | pump | 6 | Double | One player, half-double |
| `pump-double` | pump | 10 | Double | One player, both pads |
| `pump-couple` | pump | 10 | Couple | Two players, each on own pad |
| `pump-routine` | pump | 10 | Routine | Two players share both pads |
| `techno-single4` | techno | 4 | Single | Techno 4-panel single |
| `techno-single5` | techno | 5 | Single | Techno 5-panel single |
| `techno-single8` | techno | 8 | Single | Techno 8-panel single |
| `techno-double4` | techno | 8 | Double | Techno 4-panel double |
| `techno-double5` | techno | 10 | Double | Techno 5-panel double |
| `techno-double8` | techno | 16 | Double | Techno 8-panel double |
| `lights-cabinet` | lights | NUM_CabinetLight | Single | Cabinet lights (not a playable dance style; autogen disabled) |

“Versus” is a *style* (`StyleType_TwoPlayersTwoSides`) that re-uses `dance-single` charts, not a distinct `#STEPSTYPE`. `[CODE: GameManager.cpp g_Style_Dance_Versus uses StepsType_dance_single]`

---

## 3. Proposed display labels

Decided dance labels (brain-dump item 4):

| Raw value | Display label |
|---|---|
| `dance-single` | Single |
| `dance-double` | Double |
| `dance-couple` | Couple |
| `dance-solo` | Solo |
| `dance-threepanel` | Three-panel |
| `dance-routine` | Routine |

Proposed labels for the remaining engine-recognized values (table still shows these rows until any deprecation half lands). Pattern: drop the family prefix for the common play modes, keep a short family tag where the family is not “dance”, and keep panel-count suffixes where they distinguish variants.

| Raw value | Proposed display label |
|---|---|
| `pump-single` | Pump Single |
| `pump-halfdouble` | Pump Half-double |
| `pump-double` | Pump Double |
| `pump-couple` | Pump Couple |
| `pump-routine` | Pump Routine |
| `techno-single4` | Techno Single 4 |
| `techno-single5` | Techno Single 5 |
| `techno-single8` | Techno Single 8 |
| `techno-double4` | Techno Double 4 |
| `techno-double5` | Techno Double 5 |
| `techno-double8` | Techno Double 8 |
| `lights-cabinet` | Lights |

Fallback for any unrecognized / invalid string that still appears in a cache row: show the raw string (or a neutral “Unknown”) so the mapping stays display-only and never invents a key. `[INFERRED from the hard rule below]`

Chart-sort order (issue #259): dance types first in the order Single → Double → Couple → Solo → Three-panel → Routine (Routine after Three-panel unless the owner moves it). Non-dance types sort after the dance block (exact secondary order not yet decided).

---

## 4. Join-key boundary — raw value must not leak

**Where the raw value is a key today**

- Stats.xml join: `stats_index` builds keys as  
  `(song_path.casefold(), steps_type.casefold(), diff.casefold())`  
  (or a 4-tuple with description for described Edits).  
  `steps_type` comes from the XML attribute `StepsType`.  
  Cache side: `parse_cache_file` builds the same base key from `#STEPSTYPE` (also casefolded).  
  `[CODE: library_sources.py stats_index ~lines 33–60; parse_cache_file ~lines 288–311]`

- Course-file writing: any path that emits a `#STEPSTYPE:` (or equivalent style token) into a `.crs` must keep the engine string. The raw value is the contract the engine and other tools expect. `[INFERRED from course notes / cref; app course writers not re-read in this pass — treat as hard boundary]`

**Boundary the display mapping must not cross**

- The mapping is **display-only**.  
- Row field `"Type"` (and any search/filter token that matches against the stored field) continues to hold the raw engine string.  
- UI cells, column headings, dropdown captions, and sort *labels* may show the friendly form.  
- Never write the friendly label into Stats.xml keys, into course files, or into any on-disk join key.  
- Search directives such as `type:dance-single` should keep matching the stored raw value (or both forms if a bidirectional alias is later added); changing the stored value would break the Stats join.

---

## 5. Edge cases

**Missing `#STEPSTYPE`**

- App: `parse_cache_file` drops the chart block when `#STEPSTYPE` or `#DIFFICULTY` is empty (issue #18). `[CODE: library_sources.py parse_cache_file]`  
- Engine: `SetStepsType` still runs; an empty/missing value becomes `StepsType_Invalid` and the original (empty) string is kept in `m_StepsTypeStr`. `TidyUpData` logs a warning and does **not** default the type to `dance-single`. The song can still hold the Steps object; gameplay/style selection simply will not match it. `[CODE: NotesLoaderSSC.cpp SetStepsType; Steps.cpp TidyUpData]`

**Unrecognized value**

- Engine: `StringToStepsType` → `StepsType_Invalid`; string preserved; warning on tidy. Chart is not deleted. `[CODE]`  
- App: stores whatever string is in the cache tag; join uses the casefolded form. An unrecognized type will not match any Stats.xml entry that used a recognized type.

**Case sensitivity**

- App join key: **casefolds** both the cache `#STEPSTYPE` and the Stats.xml `StepsType` attribute. `[CODE: library_sources.py]`  
- Engine: `StringToStepsType` / the name table comparison — exact behaviour of case folding is not re-verified in this pass; the canonical strings in `g_StepsTypeInfos` are all lowercase. `[UNVERIFIED for engine case-insensitivity; practical files use lowercase]`

**Values the engine knows that never appear in practice**

- `lights-cabinet` is present for cabinet-light charts; ordinary song libraries almost never contain it.  
- Techno and most pump variants are rare in an ITG-focused library but are fully recognized.  
- No evidence in the v1.3.0 table of “parse but never emit” strings.

---

## 6. What appears in the app’s own fixtures

Only one fixture carries a non-single dance type:

- `tests/fixtures/routine_subtitle.cache`  
  ```
  #STEPSTYPE:dance-routine;
  #DIFFICULTY:Hard;
  …
  ```
  `[CODE: tests/fixtures/routine_subtitle.cache]`

Other fixtures (`plain_tune.cache`, `apostrophe.cache`, `double_edit.cache`, `tempo_tangle.cache`, etc.) use `dance-single` or are not chart-type exercises. `[INFERRED from fixture names + the one routine file read]`

**Live scan of the owner’s library:** not performed. A real scan would be the only way to know which of the 18 engine strings actually occur in his Cache/Songs. Do not assume contents. `[UNVERIFIED]`

---

## 7. Deprecation half (scoped, not built)

Hiding non-dance rows would touch:

| Surface | What changes |
|---|---|
| Type dropdown (filter UI) | Values offered; possibly restricted to the six dance labels (or dance + “Other”) |
| `type:` search field | Whether non-dance tokens remain matchable; documentation of accepted tokens |
| Table | Default visibility / filter that drops non-dance rows |
| Song-page sort / chart sort (issue #259) | Primary key already planned around dance order; non-dance placement must be defined |

A filter-contract change (what the Type dropdown and `type:` directive accept) is a user-visible behaviour change and **likely needs a short proposal** before implementation, consistent with prior filter/search contract work. Display-label mapping alone (raw value kept, label only in the cell) does **not** need a proposal beyond the already-decided dance labels; the non-dance labels above are a recommendation for that mapping.

---

## Sources (engine)

- `src/GameConstantsAndTypes.h` — `enum StepsType`, `enum StepsTypeCategory` (v1.3.0 tag `8a3bf8884a`)  
- `src/GameManager.cpp` — `g_StepsTypeInfos[]`, style tables  
- `src/Steps.cpp` — `TidyUpData`, note-data handling for Invalid  
- `src/NotesLoaderSSC.cpp` — `SetStepsType`  

## Sources (app)

- `itgmania_library/library_sources.py` — `stats_index`, `parse_cache_file`, join keys  
- `tests/fixtures/routine_subtitle.cache`  

## Sources (notes)

- `notes/itgmania_cache_format_spec.txt` — confirms `#STEPSTYPE` is written per chart block; examples `dance-single`, `dance-double`. No exhaustive enum list in the notes (search for STEPSTYPE / StepsType in the notes repo returned nothing further).  

---

*End of research. Owner may attach; nothing pushed or opened.*
