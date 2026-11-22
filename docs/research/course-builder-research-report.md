> **Provenance:** research report by Grok, 2026-11-22. Landed in the repo with the roadmap (2026-11-22). Verified by Muse against the v1.3.0 engine source and the notes' course format reference (cref) — accept, no corrections. Note: the body's header calls courses "proposed theme 5"; the roadmap now numbers it theme 4. Body below is otherwise verbatim as delivered; only this header was added.

# Research report: fleshing out the course builder

**Roadmap context:** proposed theme 5, “Courses and lists”  
**Scope:** research only — no code changes, no branch, no PR  
**Author:** Grok (xAI)  
**Date:** 2026-11-22  
**Basis:** notes repo `wolfemian-del/itgmania-notes` (INDEX.md → cref = `notes/itgmania_course_format_reference.txt` REVISION 2026-10-31-b; course builder findings where cited), ITGmania v1.3.0 engine (`Docs/CourseFormat.txt`, `CourseLoaderCRS.cpp` / `Course.cpp` as cited in cref), app code `itgmania_library/library_course.py`, `course_builder.py`, `docs/ARCHITECTURE.md`, AGENTS.md design-proposal rule.

Confidence tags follow the notes / AGENTS convention: **[CODE]** (file + line or function), **[RAN]** (executed here), **[INFERRED]**, **[UNVERIFIED]**. Engine line numbers are those recorded in cref for v1.3.0 `8a3bf8884a` unless noted.

---

## 1. Full `.crs` directive set the engine honors

### Course-level (header)

| Directive | What it does in game | App can safely write? |
| --- | --- | --- |
| `#COURSE:title;` | Course title. | **Yes.** App already writes this. [CODE] `library_course.format_new_course`; cref §4 |
| `#COURSETRANSLIT:t;` | Transliterated title. | **Yes** (harmless if unused by theme). [CODE] cref §4 |
| `#SCRIPTER:t;` | Scripter credit. | **Yes.** [CODE] cref §4 |
| `#DESCRIPTION:t;` | Description text. | **Yes.** [CODE] cref §4 |
| `#REPEAT:…;` | Endless if lowercased value **contains** `"yes"` (e.g. `yes`, `YES`, `yesterday`). Any other value: no effect. | **Yes**, with value `YES`. [CODE] cref §4 |
| `#BANNER:path;` | Banner image path, relative to the course folder (resolution rules not fully read in notes). | **Yes** if path is under the course dir the user chose; path rules partially [UNVERIFIED]. [CODE] cref §4 |
| `#BACKGROUND:path;` | Background image (SM5/sm-ssc lineage; still parsed). | **Yes** same as banner. [CODE] cref §4 |
| `#LIVES:n;` | `max(n,0)`. `n > 0` → **Oni / battery** course; selection sets battery with that many lives (`ScreenSelectMusic.cpp` 1317–1325 per cref). | **Yes.** [CODE] cref §4, §10 |
| `#GAINSECONDS:s;` | Float; stays in force for **every later** `#SONG` until changed (variable never reset). First entry with gain > 0 and no `#LIVES` → **Survival**. `#SONGSELECT` does not consume the course-level gain variable the same way (cref §4 line 152). | **Yes** as a course-level header, or carefully before entries. Trailing after last song is the risk the app already blocks on append. [CODE] cref §4; app `course_trailing_risk` |
| `#METER:n;` | Custom meter for **Regular** (Medium) course difficulty. | **Yes.** [CODE] cref §4 |
| `#METER:Name:n;` | Name must be one of `Beginner, Easy, Regular, Difficult, Challenge, Edit` (`g_CRSDifficultyNames`). **Not** `Medium`/`Hard` — those are logged and skipped. Trap: `#SONG` difficulty word `difficult` means the Medium **chart** slot; here `Difficult` means the Hard **course** difficulty. | **Yes**, using the legal names only. [CODE] cref §4; OBSERVED M10a invalid `Medium` |
| `#MODS:…;` (KEY=VALUE form) | Timed attacks attached to the **next** `#SONG` / `#SONGSELECT`. Only `TIME=…:LEN=…:MODS=…` (or `END=`) works. | **Yes** with the `=` form only. See §2 for the docs forms that do nothing. [CODE] cref §7; TESTED in notes |
| `#STYLE:…;` | **Never read** (loader branch is dead). | **Do not write** — waste and false documentation. [CODE] cref §4, F5 |
| `#DISPLAYCOURSE` / `#COMBO` / `#COMBOMODE` | Ignored by design. | **Do not write.** [CODE] cref §4 |
| Unknown tags | Typos never logged; later branches (`#RADAR` cache read, etc.) never run because of the dead `||` chain. | **Do not invent tags.** [CODE] cref §4, O1 |

Course type derivation [CODE] `Course.cpp` 199–209 (cref §4): `#REPEAT` → Endless; else lives > 0 → Oni; else first entry gain > 0 → Survival; else Nonstop. Survival and Oni both use `PLAY_MODE_ONI`.

### Per-entry

| Directive / field | What it does | App can safely write? |
| --- | --- | --- |
| `#SONG:path:difficulty[:mods];` | Fixed or wildcard song + chart criteria + optional mod list. Missing song → entry skipped, course marked incomplete. | **Yes** for path + difficulty (app already does). Third field optional. [CODE] cref §5; app `course_song_line` |
| Path field | Pack/Song, bare folder/title, `*`, `Pack/*`, `BEST<n>`, `WORST<n>`, `GRADEBEST<n>`, `GRADEWORST<n>`. | Fixed `Pack/Song` is what the app writes today; wildcards are valid but outside the builder’s “queue concrete charts” model. [CODE] cref §5 |
| Difficulty field | Difficulty word (old synonyms) or meter `lo..hi` / `n`. Invalid → log + fallback 3..6. | Named difficulty is safe. Meter ranges are legal but reintroduce the “which chart?” ambiguity. [CODE] cref §5 |
| Mods field (3rd) | Comma list. Keywords stripped and acted on: `showcourse`, `noshowcourse`, `nodifficult`, `awardN` (needs length > 5; bare `award` is an unknown mod). Remainder = entry mod string. | Keywords **yes**. Arbitrary PlayerOptions/SongOptions tokens **yes** if known; unknown tokens produce no load dialog but log when applied. [CODE] cref §5, §7.4, OBSERVED M7 |
| `#SONGSELECT:KEY=value:…;` | Criteria-based pick. Keys: `TITLE GROUP ARTIST GENRE DIFFICULTY METER BPMRANGE DURATION SORT GAINLIVES GAINSECONDS MODS`. Malformed `=` piece → whole entry skipped. | **Yes** when the app intentionally builds criteria courses; not needed for “queue these charts”. GROUP match is **case-sensitive**. [CODE] cref §6 |
| Timed `#MODS` before an entry | Attaches to the next resolved entry. If the next `#SONG` fails to resolve, pending attacks are **not** cleared and attach to a later entry. | Write only with a following resolvable entry; never trail the file with bare `#MODS`. [CODE] cref §5, §7.3 |

---

## 2. What the game ignores or mishandles (app must not write / must warn)

**Must not write (ignored or dead):**

- `#STYLE` — never reached. [CODE] cref F5, §4  
- `#DISPLAYCOURSE`, `#COMBO`, `#COMBOMODE` — ignored by design. [CODE] cref §4  
- `#MODS` forms from `Docs/CourseFormat.txt` that use colon-separated `TIME:0.500:LEN:…` **without** `=` — produce **zero** attacks and no log. Only `TIME=…:LEN=…:MODS=…` works. [CODE][TESTED] cref F1, §7.1  
- `#METER:Medium:n` / `#METER:Hard:n` — invalid names; logged and skipped. Use `Regular` / `Difficult`. [CODE] cref §4; OBSERVED M10a  

**Silently accepts but misreads / drops — warn or avoid:**

- Cache round-trip drops some `#SONGSELECT` criteria on second load: **GENRE always**; **DURATION / BPMRANGE when minimum is 0**, because writer and loader disagree. [CODE] cref F6, §11.3; OBSERVED M6/M6b  
- `#GAINSECONDS` as a **trailing** directive after the last song: still in force for a later append’s first new entry. App already refuses append when trailing `#MODS` or `#GAINSECONDS` is present. [CODE] app `course_trailing_risk` / `course_append_bytes`; cref §4  
- Failed `#SONG` resolution leaves pending `#MODS` attached to the **next** successful entry. [CODE] cref §5  
- Entry mod tokens unknown to PlayerOptions/SongOptions: no load-time dialog for `#SONG` mods; log at apply time. [CODE][OBSERVED] cref §7.4 M7  
- Options that parse but cannot take effect from a course because the engine reads them at Stage / Preferred level (e.g. life **type** `battery`/`bar`, visual delay). [CODE][INFERRED] cref §9.3; OBSERVED M8 for `battery`  
- Noteskin names as entry mods: wiki and user run (M9) show no visible skin change; cause not fully traced. [UNVERIFIED] root cause; [OBSERVED] no change  

**Do not write what the notes say the game ignores or mishandles** (AGENTS.md). Prefer the `=` form of `#MODS`, legal `#METER` names, and never emit `#STYLE`.

---

## 3. How the game resolves a `#SONG` entry to a chart

[CODE] cref §5 (`ParseCourseSong`, `Course.cpp` ~633, 640–710):

1. Resolve the song (path / wildcard / BEST/WORST/…). Missing song → entry skipped; course may be marked incomplete (`HideIncompleteCourses`, default false).  
2. Build the set of **all** charts on that song matching the entry’s steps criteria (difficulty word or meter range).  
3. Pick **one** candidate with `RandomInt` — not “first in list”.  
4. For non-Regular **course** difficulties, the chart slot is shifted unless `nodifficult` is set.

Consequences for the app’s ambiguity warning [CODE] `find_ambiguous_course_entries` in `library_course.py`:

- A `#SONG` line stores only path + difficulty word (and optional mods). It does **not** store chart type (`dance-single` vs `dance-double`, etc.) or which Edit.  
- If the library has another chart for the same path + difficulty in a **different type**, or a second Edit of the same type, the line is ambiguous: the game may pick either.  
- Meter-range difficulties widen the candidate set further (any chart of the song in range).  
- There is **no preference for a particular chart type** in the course path described by the notes; type is not in the line at all. Resolution is random among matching Steps. [CODE] cref §5; OBSERVED M01/M02 different difficulties across loads for the same two songs when range was wide.

Unresolved entry: skipped; does not stop the rest of the course from loading.

---

## 4. What the parser already reads but the writer never emits

[CODE] `parse_course_text` / `course_trailing_risk` in `library_course.py`:

| Token | Parser today | Writer today | What safe write would take |
| --- | --- | --- | --- |
| `#SONGSELECT` | Detected only for trailing-risk scan (`#(?:SONG\|SONGSELECT)`). Not expanded into queue rows. | Never emitted. | A separate “criteria entry” model (keys, multi-value lists, escapes for `,=:#;`), UI for filters, and validation that at least one library song matches — or document that criteria courses are out of scope for the fixed-queue builder. [CODE] cref §6 |
| `#MODS` | Trailing risk only (`course_trailing_risk`). Not parsed into attack objects. | Never emitted. | Emit only KEY=VALUE groups; attach each group to the following queue entry; reject colon-only docs forms; optional validation against known PlayerOptions/SongOptions tokens (warn, don’t block). [CODE] cref §7 |
| `#GAINSECONDS` | Trailing risk only. | Never emitted. | Course-level header field and/or per-entry (via `#SONGSELECT GAINSECONDS=` or course-level sticky). On rewrite of an existing file, preserve or re-emit sticky gain so append semantics stay correct. [CODE] cref §4, §6 |

`parse_course_text` also returns only `#SONG` path/difficulty/raw — not the third mods field content as structured data, and not header metadata beyond title. Extending the parse is a prerequisite for open-and-edit.

---

## 5. What the game shows for a course (what matters to the player)

From cref and engine docs, player-visible / selection-visible metadata:

- **Title** (`#COURSE`) — course wheel / select label.  
- **Banner** (`#BANNER`) — artwork on the wheel / select UI (path relative to course folder). [CODE] cref §4; path resolution details [UNVERIFIED]  
- **Lives** (`#LIVES`) — Oni battery life count at selection; changes play mode to battery. [CODE] cref §4, §10  
- **Course type** (Endless / Oni / Survival / Nonstop) derived from REPEAT / LIVES / GAINSECONDS — determines life meter and fail rules.  
- **Custom meters** (`#METER`) — shown as the trail meter for that course difficulty (Simply Love reads `trail:GetMeter()`). [CODE][OBSERVED] cref M10  
- **Description / scripter / translit** — available to themes; importance theme-dependent.  
- **Background** — secondary artwork where the theme uses it.

Per-entry mods and timed attacks affect **play**, not the wheel listing. Incomplete courses may be hidden by preference. For the builder’s “what the player sees,” title, banner, lives (and thus mode), and whether the course is complete are the highest-leverage fields.

---

## 6. Feature clusters in dependency order

Implementation-sized steps. “Needs proposal?” uses AGENTS.md: new component boundary/contract, new settings key or format, or a real design fork → proposal in `docs/proposals/`.

### (a) Open and edit an existing course

- Load file → parse headers + ordered entries into the queue (extend `parse_course_text` to keep mods field, `#SONGSELECT` as opaque or structured rows, and unknown/raw lines).  
- **Unknown directives:** **preserve verbatim** on rewrite (safest; matches “do not write what the game mishandles” without dropping user content). Refuse only if the file is not a course (`#COURSE` + at least one entry). Drop-with-warning is worse than preserve for community courses that use cache-only or theme-only tags.  
- Replace / reorder / delete entries; save = rewrite whole file (or write-new + optional replace).  
- **Depends on:** richer parse (below); ambiguity check already exists.  
- **Proposal?** Likely **yes** if open-edit changes the CourseBuilder constructor contract (e.g. load path, dirty state, preserve-unknown policy) or introduces a “course document” type shared outside the dialog. Pure dialog-internal load may ship without a proposal if the format helpers stay in `library_course` and the dialog remains the only consumer.

### (b) Course-level metadata

- UI fields: title (already), lives, gain-seconds, repeat, banner path, description, per-difficulty meters.  
- Writer emits only tags the engine honors (table in §1).  
- **Depends on:** (a) if editing existing files so headers round-trip; can land on “new course only” first.  
- **Proposal?** Usually **no** if fields are dialog-local and format functions stay in `library_course`. **Yes** if a settings key remembers last lives/banner folder, or a shared CourseMetadata type becomes a boundary.

### (c) Per-entry settings

- Third-field keywords (`nodifficult`, `showcourse`, `awardN`) and optional mod string; optional timed `#MODS` groups bound to an entry.  
- **Depends on:** (a) to edit; (b) only loosely.  
- **Proposal?** **Yes** if the queue row model gains a stable schema (mods list, attacks) consumed by more than the dialog, or if validation policy (warn vs block unknown mods) is a lasting product rule.

### (d) Queue helpers

- Duplicate entry, clear queue, jump to library row, filter-add by search, multi-select reorder polish, “replace selection with library selection.”  
- **Depends on:** nothing hard; improves (a)–(c) UX.  
- **Proposal?** **No** (dialog-internal).

### (e) Validation and preview against the library

- Resolve each `#SONG` against current `library_rows`: missing path, ambiguous type/Edit (already), mixed types (already), empty `#SONGSELECT` match set, sticky gain/mods trailing risk on rewrite.  
- Preview: total time (already), estimated lives flow, list of unresolved paths.  
- **Depends on:** library load; richer parse for `#SONGSELECT`.  
- **Proposal?** **No** unless preview becomes a separate panel/component with its own contract.

### (f) Course management (list, rename, duplicate, delete)

- Scan a courses directory (user-configured path), list `.crs`, open in builder, rename file, duplicate file, delete file.  
- App remains read-only on **game** song folders; course files the user points at are the existing write exception.  
- **Depends on:** (a) for open; data-paths or a new courses-root setting.  
- **Proposal?** **Yes** — new settings key (courses directory), and possibly a new management window/component boundary.

### (g) Queue persistence

- Remember queue across dialog close / app restart.  
- **Depends on:** settings or snapshot store shape.  
- **Proposal?** **Yes** if a new settings key or file format is introduced. Behaviour (whether to persist, clear on library reload, etc.) is an **owner call**, not a research finding — listed under open questions.

**Suggested build order:** (d) any time → (e) deepen → (a) open/edit with preserve-unknown → (b) headers → (c) per-entry → (f) management → (g) only after owner decision.

---

## 7. Roadmap placement

Settled theme order (from the task):  
1 unified windows (done); 2 pack and series view; 3 scores, profiles, and the song page; 4 “what should I play next”; open playlists candidate; proposed 5 “Courses and lists.”

| Option | Fit | Drawbacks |
| --- | --- | --- |
| **New theme 5 “Courses and lists” after theme 4** | Matches the proposal; courses are a distinct artifact (`.crs` files, play modes, lives) from “what to play next” recommendations. Management (f) and lists/playlists sit naturally together. | Delays course polish until after theme 4. |
| **Fold into theme 4 as its output** | Theme 4 could emit a course as one “play this set” action. | Overloads theme 4; course **editing**, metadata, Oni/Survival, and file management are not “recommendation” work. Risk of shipping a half-builder inside a different theme. |
| **Leave the builder unthemed** | Small queue helpers and validation can ship opportunistically. | Larger clusters (open-edit, management, metadata) still need a home; unthemed work competes poorly with numbered themes. |

**Recommendation:** **New theme 5 “Courses and lists” after theme 4.**

Reasons: (1) the engine surface is large enough (headers, modes, `#SONGSELECT`, mods) to justify its own theme; (2) theme 4 stays focused on recommendation/ranking; (3) playlists (if pursued) share “ordered lists of charts the player owns” with courses and belong in the same theme; (4) open-edit + management need a settings/courses-root decision that is theme-scoped, not a drive-by fix. Opportunistic (d)/(e) fixes can still land before theme 5 without waiting.

---

## 8. Unverified items and open questions

### Could not verify (exact check that would settle it)

| Item | Check |
| --- | --- |
| `#BANNER` / `#BACKGROUND` path resolution (relative roots, missing file behaviour) | Read remaining path code in engine; or OBSERVED with a course folder banner present/absent. |
| Noteskin entry mods never applying | Trace ScreenGameplay noteskin attack path vs Current-level reset (cref §9.2); in-game M9-style test with a known-different skin. |
| Survival vs Oni life meter interaction when both `#LIVES` and `#GAINSECONDS` appear | In-game course with both; cref says mutually exclusive in docs but code priority is lives-first for type. |
| `#SONGSELECT` SORT accuracy | Notes already say results “aren’t exactly accurate” (Docs + cref); controlled machine stats + SORT=MostPlays,1. |
| Theme (Simply Love) course wheel fields beyond title/meter | Read theme Lua for course panes; OBSERVED. |
| Whether app should ever emit `#SONGSELECT` for fixed charts | Product choice; engine allows fixed TITLE+GROUP+DIFFICULTY as a substitute for `#SONG`, with different matching rules (GROUP case-sensitive). |

### Open questions for the owner (behaviour calls, not research)

1. **Queue persistence (g):** Persist across dialog close? Across app restart? Clear on library reload always, or only when paths no longer resolve?  
2. **Course deletion (f):** Soft-delete, recycle bin, or permanent delete with confirm? Any backup of the previous `.crs` body on overwrite?  
3. **Unknown directive policy on save:** Confirm **preserve verbatim** (recommended) vs refuse to save vs drop-with-warning.  
4. **Courses directory:** New settings key vs reuse a path under Data paths vs always file-picker-only.  
5. **Scope of theme 5 vs playlists:** Same theme or separate candidate after courses land.

---

## Sources (primary)

- Notes: `INDEX.md`; `notes/itgmania_course_format_reference.txt` (cref) — tags, `#SONG`, `#SONGSELECT`, `#MODS`, lives, pipeline, doc-vs-code, in-game checks M1–M11.  
- Engine: `Docs/CourseFormat.txt` (v1.3.0); loader/writer behaviour as cited in cref (`CourseLoaderCRS.cpp`, `Course.cpp`, `CourseWriterCRS.cpp`, `PlayerOptions.cpp`, etc.).  
- App: `itgmania_library/library_course.py` (parse, append, ambiguity); `itgmania_library/course_builder.py` (dialog, queue, validation); `docs/ARCHITECTURE.md` (course rows / `Course path`); `AGENTS.md` (proposal rule, tag convention, “do not write what the notes say the game ignores”).

---

*Signed: Grok (xAI), 2026-11-22*  
*Deliverable only — nothing pushed or opened.*
