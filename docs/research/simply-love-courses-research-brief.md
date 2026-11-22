> **Provenance:** research brief by Grok, 2026-11-22. Landed in the repo with the roadmap (2026-11-22). Verified by Muse against Simply Love v5.9.0 @ dd06138 — accept, with one citation nit: two file paths in the body are shortened; both live under `BGAnimations/ScreenSelectMusic overlay/`. Body below is otherwise verbatim as delivered; only this header was added.

# Research follow-up: Simply Love and courses

**Parent survey:** course-builder research report (2026-11-22), §8 open item on theme course-wheel fields  
**Scope:** research only — no code changes, no branch, no PR  
**Author:** Grok (xAI)  
**Date:** 2026-11-22  

**Theme source read:** [Simply-Love/Simply-Love-SM5](https://github.com/Simply-Love/Simply-Love-SM5), branch **`itgmania-release`**, commit **`dd06138`** (release tag **v5.9.0**, same SHA the notes repo cites for Simply Love in several places). Compatible with ITGmania **1.3.0+**. This is the community theme shipped with the ITGmania + Simply Love bundle and the one the vast majority of users run.

Engine behaviour is taken from the parent survey and notes `cref` (`notes/itgmania_course_format_reference.txt`); this brief does not re-litigate the `.crs` loader.

Confidence tags: **[CODE]** theme file + path (or engine/cref as cited), **[INFERRED]**, **[UNVERIFIED]**, **[RAN]** (not used — theme was read, not executed in game).

---

## 1. What Simply Love displays for a course (wheel and select)

Simply Love does **not** invent custom `.crs` tags. It reads the engine’s Course / Trail objects after the loader has run. Display is therefore bounded by what the engine exposes from the file.

| UI surface | Fields used | Source |
| --- | --- | --- |
| **Banner** | Course banner if `HasBanner()`, else theme fallback (`Graphics/Banner course fallback`). Driven by preference `ShowBanners`. | [CODE] `BGAnimations/ScreenSelectMusic overlay/banner.lua` — `SongOrCourse = …GetCurrentCourse()`, `HasBanner()`, ActorProxy onto screen Banner |
| **Title** | Engine wheel / banner title (`GetDisplayFullTitle` / translit via preference). Theme does not special-case a separate title actor for courses beyond the stock MusicWheel. | [CODE] wheel item is mostly chrome: `Graphics/MusicWheelItem Course NormalPart.lua` (background quads only; no title string). Title comes from engine metrics / MusicWheel. |
| **Song count** | `#course:GetCourseEntries()` shown in the “Artist” slot (label switches to “NumSongs” in course mode). | [CODE] `SongDescription/SongDescription.lua` SetCommand |
| **Length** | `TrailUtil.GetTotalSeconds(trail)` for the master player’s current trail, rate-adjusted. | [CODE] same file, `WheelItemDataType_Course` branch |
| **BPM** | `StringifyDisplayBPMs()` (helpers) for the current trail(s); split P1/P2 supported. | [CODE] same file + `Scripts/SL-BPMDisplayHelpers.lua` |
| **Trail meter / difficulty** | `trail:GetMeter()` and difficulty colour on the pane and on evaluation. | [CODE] `PaneDisplay.lua` (`StepsOrTrail:GetMeter()`); evaluation `Difficulty.lua` / `nice.lua` |
| **Course contents list** | Scrolling list of entry titles (`params.Song:GetDisplayFullTitle()` or `??????????` if unresolved) and per-player meters. | [CODE] `StepsDisplayList/CourseContentsList.lua` |
| **Radar counts** | Trail radar (taps, jumps, holds, …) in the pane — same widgets as songs, fed from `StepsOrTrail:GetRadarValues`. | [CODE] `PaneDisplay.lua` |
| **High scores** | Profile / machine high score for `(Course, Trail)` via `profile:GetHighScoreList(SongOrCourse, StepsOrTrail)`. GrooveStats requests are **skipped** in course mode. | [CODE] `PaneDisplay.lua` GetSongAndSteps / GetScoreFromProfile; comment “we don't run the RequestResponseActor in CourseMode” |

**Not displayed by Simply Love on select (from the files read):**

- `#LIVES` / battery life count as its own select-screen label  
- `#DESCRIPTION`, `#SCRIPTER`, `#COURSETRANSLIT` as select chrome (they are **read** when writing custom score JSON — see §3 — but not painted on the select UI in the actors above)  
- Course type label (Oni / Survival / Endless / Nonstop) as text on the wheel  
- Any theme-only custom `.crs` tag (none found)

**Custom tags the theme honors that the loader never sees:** **None found.** [CODE] search of course-related BGAnimations, Graphics, and Scripts under `dd06138` shows only engine Course/Trail API calls (`GetCurrentCourse`, `GetCurrentTrail`, `GetCourseEntries`, `GetMeter`, `GetDisplayFullTitle`, `GetScripter`, `GetDescription`, `GetCourseDir`, `HasBanner`). No theme parser of raw `.crs` text.

**Implication:** Banner, title, entry count, total time, and legal `#METER` values are the select-visible surface. Lives and mode are play-time / life-meter concerns (engine), not SL select chrome.

---

## 2. What Simply Love does at course play time

### Mods (per-song and timed)

Theme does **not** re-implement course mods. Engine applies `#SONG` / `#SONGSELECT` entry mods and KEY=VALUE `#MODS` attacks (parent survey §1–§2, cref §5–§7). Simply Love only:

- Plays the stock course-attack sound cues (`Sounds/Player course attack launch.redir`, `…ending.redir`). [CODE] theme tree  
- Adjusts **display** of measure counters / mods level when `IsCourseMode()` (reads the current trail entry’s Steps). [CODE] `ScreenGameplay in/MeasureCounterAndModsLevel.lua`  
- Handles “next course song” screen and a speed-mod-before-first-note helper under `BGAnimations/ScreenGameplay next course song/`. [CODE] tree listing  

No evidence the theme changes which song is chosen inside a course or rewrites attack strings.

### Lives and fail rules (Oni / Survival / Endless / Nonstop)

Course **type** and life rules remain engine-derived (REPEAT → Endless; lives > 0 → Oni; first-entry gain > 0 → Survival; else Nonstop — cref §4). Simply Love exposes a **LifeMeterType** player option [CODE] `Scripts/SL-PlayerOptions.lua` (`LifeMeterType = {…}`), which is the normal SL life-meter preference surface; it does not appear to override course-forced battery/time modes from the `.crs` (engine Stage/Song level rules from cref §9 still apply). Exact interaction when a course forces battery and the player preference disagrees was **not** fully traced in theme Lua → [UNVERIFIED] in-game check recommended (see §6).

### Song selection inside a course

Theme does **not** alter resolution of `#SONG` / `#SONGSELECT`. Contents list shows whatever the engine resolved (`??????????` when the entry has no Song pointer). [CODE] `CourseContentsList.lua`

### Course options at runtime

Player options in course mode still offer **playable trails** for the current course (`GetPlayableTrails(course)`, labeled with difficulty + `trail:GetMeter()`). [CODE] `SL-PlayerOptions.lua`. That is trail choice (course difficulty / style), not a rewrite of the `.crs`. No separate “course editor” or “edit entries” screen in the theme.

**Implication for the builder:** Do not duplicate runtime mod application, life-meter switching, or trail picking. Writing correct engine tags (`#LIVES`, `#GAINSECONDS`, `#REPEAT`, legal `#METER`, `#SONG` lines) is enough; SL will display the resulting Trail.

---

## 3. What Simply Love records about courses

### Engine profile scores

Same path as songs: `Profile:GetHighScoreList(Course, Trail)` → machine and player panes on select; evaluation screen uses trail meter/difficulty. [CODE] `PaneDisplay.lua`, evaluation Difficulty actors.

### Theme-written score files

After a played stage, `WriteScores()` in `Scripts/SL-CustomScores.lua` writes a JSON file under the **player profile** `SL-Scores/` directory (timestamped `.json`). For courses it stores:

```text
content.Course = {
  Path, FullTitle, TranslitFullTitle, Scripter, Description
}
content.Trail = {
  Difficulty, Meter, StepsType, LengthSeconds, Radar
}
```

plus the usual score block (grade, percent DP, judgments, modifiers, …). [CODE] `SL-CustomScores.lua` (course branch uses `course:GetCourseDir()`, `GetDisplayFullTitle()`, `GetTranslitFullTitle()`, `GetScripter()`, `GetDescription()`, `trail:GetMeter()`, etc.)

Guest profiles and autoplay are skipped. These files are **not** `.crs` and are not read back by the engine course loader.

### Machine / other

No theme-owned “course favorites” file or per-course settings store was found beyond the shared high-score lists and `SL-Scores` JSON.

**Implication for the builder:** Writing `#COURSE`, `#COURSETRANSLIT`, `#SCRIPTER`, `#DESCRIPTION` improves **score JSON completeness** and any future UI that surfaces those fields; it does not change play rules. The builder should not invent parallel score files.

---

## 4. Course-adjacent lists the theme owns

| List | Format / location | Course-related? |
| --- | --- | --- |
| **Favorites** | `favorites.txt` in the player profile dir (`getFavoritesPath`). Lines are `Group/Song` paths; optional `---` section headers for Preferred Sort. | **Songs only.** Add/remove requires `GAMESTATE:GetCurrentSong()`; no course branch. [CODE] `Scripts/SL-FavoritesHandler.lua` |
| **Preferred Sort (Favorites)** | Same file drives a music-wheel sort with custom sections. | Song wheel, not course wheel. |
| **Course groupings / course favorites / playlists** | **None found** in v5.9.0 Scripts/BGAnimations for a course-specific list file. | — |
| **Custom course sorts/filters** | No theme-side course-wheel filter beyond engine course mode + trail selection. | — |

**Implication:** The builder should **not** try to write `favorites.txt` as a course list, and should **not** assume a parallel “course favorites” format exists in stock Simply Love. Theme 5 “Courses and lists” may still introduce **Librarian-side** lists; that would be a new format under AGENTS.md, not an SL mirror.

---

## 5. Implications for the Librarian course builder

| Finding | Builder action | Proposal under AGENTS.md? |
| --- | --- | --- |
| Select UI shows banner, title, entry count, length, trail meter | Prefer writing `#COURSE`, `#BANNER` (path relative to course folder), and legal `#METER:Name:n` / `#METER:n` so SL’s pane and contents list look intentional. | **No** if fields stay in existing `library_course` / dialog (parent survey §6b). |
| Description / scripter appear in SL-Scores JSON | Optional write of `#DESCRIPTION` / `#SCRIPTER` for authors who care about score exports; low priority for play. | **No** for optional header fields. |
| Lives / mode not shown as select labels | Still write `#LIVES` / `#GAINSECONDS` / `#REPEAT` for **play** correctness; validation preview can show derived mode (Oni/Survival/Endless/Nonstop) as a **display-only** hint. | Preview-only: **no**. Mode derivation is already settled by engine (cref). |
| No theme custom `.crs` tags | Do not invent SL-only tags. | — |
| Mods / attacks are engine-only at play | Builder may emit KEY=VALUE `#MODS` and entry mod fields per parent survey; do not simulate attacks in the app. | Covered by parent survey §6c (proposal if queue schema grows). |
| Favorites are song-only | Do not duplicate favorites format for courses; do not write into profile `favorites.txt`. | Any new “lists” feature: **yes** (new format / settings). |
| Course scores live in profile + `SL-Scores` | Builder remains read-only on profiles; no need to write score JSON. | — |
| Unresolved entries show as `??????????` | Validation against the library (parent survey §6e) is the right place to warn before the player sees that string in SL. | **No** (existing validation cluster). |

Nothing in Simply Love expands the set of **safe-to-write** `.crs` tags beyond the engine table in the parent survey. The theme **consumes** title, banner, meters, entry list, and (for scores) description/scripter/translit; it does not add a second contract the builder must satisfy.

---

## 6. Unverified items and version notes

**Version read:** Simply Love **v5.9.0** / `itgmania-release` @ **`dd06138`**. Notes and the parent survey already use this line for ITGmania 1.3.0 work.

**What may differ on other versions users run:**

- Older SL (pre-5.9 / pre–ITGmania 1.3.0 bundles) may lack some evaluation or GrooveStats guards; course select actors (`CourseContentsList`, banner, SongDescription course branch) have been stable in structure across recent releases, but this brief did not diff v5.8.x → v5.9.0 line-by-line for course UI.  
- Forks (e.g. Simply-ITGMania) can add panes; they are out of scope.  

| Gap | Exact check |
| --- | --- |
| Whether `#DESCRIPTION` / `#SCRIPTER` appear anywhere on select or evaluation in SL beyond score JSON | In-game OBSERVED on v5.9.0 with a course that sets both; grep remaining Evaluation actors if needed. |
| LifeMeterType preference vs course-forced battery/survival | OBSERVED: Oni course with `#LIVES:4` while player LifeMeterType is bar; Survival with `#GAINSECONDS` likewise. |
| Banner path resolution when `#BANNER` is relative vs absolute | Engine path rules (parent survey still [UNVERIFIED]) + OBSERVED with a course folder banner. |
| MusicWheel course **title** string source (metrics vs Course:GetDisplayFullTitle) | Read remaining `[MusicWheel]` / course title metrics in `metrics.ini` and any `Graphics/MusicWheelItem Course*` text actors; OBSERVED wheel text. |
| Whether any Module or operator-menu script writes course list files | Search `Modules/` and operator menu scripts on the same commit (not fully enumerated here). |

---

## Sources

- Theme: `Simply-Love/Simply-Love-SM5` @ `dd06138` / v5.9.0 — especially `banner.lua`, `SongDescription.lua`, `CourseContentsList.lua`, `PaneDisplay.lua`, `MusicWheelItem Course NormalPart.lua`, `SL-FavoritesHandler.lua`, `SL-CustomScores.lua`, `SL-PlayerOptions.lua`, `SL-Helpers.lua`, theme tree paths under `ScreenGameplay next course song` and course attack sounds.  
- Notes / parent: `cref`; course-builder research report (2026-11-22).  
- App: consulted only for implication boundaries (`library_course` / builder write surface from the parent survey).

---

*Signed: Grok (xAI), 2026-11-22*  
*Deliverable only — nothing pushed or opened.*
