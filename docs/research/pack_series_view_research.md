> **Provenance:** research report by Claude, 2026-11-22. Landed in the repo with the roadmap (2026-11-22). Verified by Muse against the v1.3.0 engine source — accept. Body below is verbatim as delivered; only this header was added.

# Research report: the pack and series view (roadmap theme 2)

**Author:** Claude · **Date:** 2026-11-22 · **Type:** research only. No code, branch, PR or notes commit was made.

**What was read, and at which version**

| Source | Version | Notes |
|---|---|---|
| itgmania-notes | INDEX.md rev 2026-10-31-g; `itgmania_series_notes.txt` rev 2026-10-31-a; `itgmania_engine_notes_v3.txt` (sections 1, 3, 3a, 8); `itgmania_cache_format_spec.txt` | Read first, per the repo rule. |
| ITGmania engine source | **v1.3.0, `8a3bf8884a`** (the notes' pin), re-read directly | All engine line numbers below are v1.3.0. |
| ITGmania beta | head `9778a4e36a` (2026-11-21), **spot-checked only** | Beta is [UNVERIFIED] by project rule except where stated. |
| ITGmania-librarian | main `dbdecf1` (2026-11-22) | All app line numbers below. |

The sandbox Python was 3.13.18 (you run 3.14.7 on Windows). **No Python or test was executed** for this report, so nothing here is tagged [RAN]. Engine claims are [CODE] where I read the lines. I could not run the game, so nothing is [TESTED]/[OBSERVED].

Tags: [CODE] read in source (file:line) · [INFERRED] reasoned from code, not run · [UNVERIFIED] not determined · [RAN] none in this report.

---

## 0. Plain-language summary

- **How the game decides a pack's Series.** It opens `Pack.ini` in the pack's folder and reads one line, `Series=...`, from a section that must be literally `[Group]`. The file is ignored entirely unless it also has a non-empty `Version=`. The Series text is trimmed at both ends and otherwise used exactly as written: no case-folding, no space-collapsing. Two packs are in the same series only if the text is byte-for-byte identical.
- **Where that data is.** Not in the cache the Librarian reads. The cache has no Series, and the engine's cache code never touches it. The view therefore needs one new read: `Pack.ini` from each pack's real folder in the game's Songs folders.
- **The one real obstacle.** The app can find the user-data `Songs` folder and the folders named in `Preferences.ini`. By its own docstring it cannot find the game's install `Songs` folder. Packs living only there would show "no series" even if their `Pack.ini` has one. Which folders your packs live in is not known to me and is not assumed (section 6).
- **How the game shows series.** Only when the wheel is in the Series sort. A series is one expandable row, its packs sit under it, and songs under them. In v1.3.0 even a series with a single pack gets a parent row. Beta removes the row for single-pack series.
- **Series banner.** The first pack in byte order whose `SeriesBanner` "resolves" wins. "Resolves" means only that a directory listing finds an entry (file *or* folder) with that name. It does not mean the file loads as an image. If none resolves, the series uses the banner of the alphabetically first pack, even if that pack has none.
- **Cost.** One tiny file per pack folder. It scales with the number of packs, not songs. The read does not belong inside the per-cache-file loop. A separate step is the natural shape, but that is a design choice for you (section 4).

---

## 1. How the engine decides a pack's Series

### 1.1 Where the file lives and how it is found

- The filename is the constant `"Pack.ini"`. `INI_VERSION` is 2. [CODE `src/Group.cpp:22-23`]
- For a normal pack the path is `sDir + sGroupDirName + "/" + "Pack.ini"`: **the Pack.ini at the root of the pack folder**, not inside any song folder. The group name is the folder's basename. [CODE `Group.cpp:54-57`]
- A `Group` is created once per pack folder. Pack folders come from a directory-only listing of `Songs/`. `Songs/` is the virtual filesystem, which merges the install, user-data and Additional song folders. [CODE `src/SongManager.cpp:524` (`new Group(sDir, sGroupDirName)`); pack-folder listing at `:438`, per-pack loop `~450-475`] Extra song folders are mounted into the same listing, not loaded by separate calls. [notes engine:8 #2 (note tag [CODE])]
- The file's existence is tested with `FILEMAN->DoesFileExist` (`Group.cpp:78`). That layer keeps a lower-cased name for each entry (`struct File`, `lname`, `src/RageUtil_FileDB.h:15-22,55`). So the filename's letter case should not matter on the engine's file layer. [INFERRED; on Windows the filesystem is case-insensitive anyway]
- Beta also reads a Pack.ini for custom songs on a USB profile (`bce0ac6749`, 2026-10-19). v1.3.0 already has a `bFromProfile` constructor path (`Group.cpp:48-52`). This is irrelevant to the Songs-folder case and noted only so it is not a surprise.

### 1.2 How the file is parsed

The reader is `IniFile::ReadFile` (`src/IniFile.cpp:37-114`). Every item below is [CODE] unless tagged.

| Behaviour | Evidence |
|---|---|
| A UTF-8 BOM is removed from each line. CR/LF are stripped by the line reader. | `IniFile.cpp:57`; `src/RageFileBasic.cpp:~325` |
| A line ending in `\` is joined with the next line. | `IniFile.cpp:59-64` |
| Blank lines are skipped. Lines starting `;` or `#` are comments, as are lines starting `//` or `--`. | `IniFile.cpp:67-79` |
| A section header is a line that starts with `[` **and ends with `]`**. The name is everything between, **untrimmed and case-sensitive**. | `IniFile.cpp:80-89` |
| A repeated section header does not create a second section. It re-opens the first, so two `[Group]` blocks merge. | `IniFile.cpp:84-87` |
| A `key=value` line before any section header is ignored. | `IniFile.cpp:93-95` |
| The line is split at the **first** `=`. Only the **key** is trimmed here. A key that is empty after trimming is dropped. A line with no `=` logs a warning and is skipped. | `IniFile.cpp:97-109` |
| Keys are stored in a `std::map<std::string, …>`, so key and section lookups are **exact, case-sensitive**. `series=` or `[group]` do not match. | `src/XmlFile.h:60`; `XmlFile.cpp:65-71,91-99`; `IniFile.h:31-39` |

Two consequences of the section rule are [INFERRED] from those lines. A header with leading whitespace (`  [Group]`) fails the `line[0]=='['` test and is treated as a key line, so the section never opens. A header with trailing whitespace (`[Group] `) fails the "ends with `]`" test for the same reason. In both cases there is no `[Group]` section, `Version` is not found, and the whole file is ignored.

### 1.3 What `Group::Group` does with the parsed file

[CODE `Group.cpp:78-148`]

1. If the file does not exist, nothing is read and all defaults stand. If it exists but cannot be opened, the constructor logs a warning and returns early with defaults (`:78-85`).
2. `Version` is read from `[Group]` and trimmed (`:87-89`). **Only if it is non-empty** (`:93`) does the engine mark the pack as having a Pack.ini and read the rest. Any non-empty text counts, even `Version=abc`, which parses to 0 (`:95`). If it is empty or missing, a warning is logged and **the whole file is ignored, Series included** (`:142-147`).
3. The fields `DisplayTitle`, `SortTitle`, `TranslitTitle`, `Series`, `Banner`, `SeriesBanner` are read through one loop: `ini.GetValue("Group", key, value); Trim(value);` (`:98-117`). `Trim` defaults to stripping the four characters `\r \n \t space` (`src/RageUtil.h:443`; `RageUtil.cpp:1006-1016`). Other whitespace, such as a non-breaking space, is not stripped. [CODE]
4. Defaults: `Series` starts as `""` (`:61`). `DisplayTitle` and `SortTitle` fall back to the folder name when empty. `TranslitTitle` falls back to `DisplayTitle` (`:110-116`).

### 1.4 The specific cases you asked about

| Case | What happens | Evidence |
|---|---|---|
| **Pack.ini missing** | Pack has no series (`Series=""`). Display and sort title are the folder name. | `Group.cpp:61,78` |
| **Pack.ini present, `[Group]`/`Version` missing or empty** | Whole file ignored, including any `Series=`. Warning logged. | `Group.cpp:87-93,142-147` |
| **`Series=` line absent** | No series. | `Group.cpp:61,102` |
| **`Series=` empty or only space/tab** | Trimmed to empty, so no series. | `Group.cpp:108-110` |
| **Duplicate `Series=` lines** | **The last one wins.** Each line calls `AppendAttr(name, value)`. `AppendAttr(name)` returns the existing attribute if the key is already present, and `SetValue` then overwrites it. | `IniFile.cpp:103` → `IniFile.h:49-53`; `XmlFile.h:157-162`; `XmlFile.cpp:196-204`. This is a code reading. Not run in game ([UNVERIFIED] in game, check G1). |
| **Case** | Series text is case-sensitive everywhere it is compared. The keyword `Series` itself and the `[Group]` header are case-sensitive too. | `XmlFile.cpp:91-99`; `SongManager.cpp:400` (map key); `MusicWheel.cpp:930` (`!=`) |
| **Whitespace** | Only leading/trailing `\r \n \t space` is trimmed. Internal whitespace is kept exactly. | `Group.cpp:108`; `RageUtil.cpp:1006` |
| **Normalization** | **None.** The Series string is stored as parsed and used verbatim as the grouping key and the parent row's label. I found no case-folding or Unicode handling in `Group.cpp`, `AddGroup` or the wheel code. | `Group.cpp:98-117`; `SongManager.cpp:399-404`; `MusicWheel.cpp:925-947` |
| **Display only** | The label on the wheel passes through `ShortenSeriesName`, a regex rewrite from `Data/Translations.xml` `<Series>`. The shipped rule rewrites "In The Groove…" to "ITG…". This changes the label only, not the key. | `SongManager.cpp:1237-1244`; `MusicWheelItem.cpp:231-234`; `Data/Translations.xml:65-68` |

**Series is not in the cache.** A grep of `src/` finds `GetSeries` used only by `Group`, `MusicWheel`, `SongManager` and `SongUtil`. `Song.cpp` and the cache writer never reference it. The cache spec's tag list has no Series either [notes cache_format_spec:31-40]. [CODE, grep-based]

---

## 2. SeriesBanner resolution

### 2.1 The rule, verified

The rule in the notes (series:3) is **confirmed**, with two refinements below.

- Resolution happens inside `SongManager::AddGroup` as each pack is registered (`SongManager.cpp:399-413`). For a pack that has a Series: it gets its entry in `m_mapNameToSeries[series]` (`:400`) and is inserted into that series' set of groups (`:404`). Then, only if the series has no banner yet *and* this pack's `SeriesBanner` is non-empty (`:405`), the engine runs `GetDirListing(sDir + sGroupDirName + "/" + SeriesBanner, out, false, true)` (`:407-409`). If the listing is non-empty, `arraySeriesBanners[0]` becomes the series banner (`:410-411`). A pack whose `SeriesBanner` matches nothing leaves the series banner empty, so a later pack can still supply one.
- `AddGroup` is called in `std::map<string,…>` iteration order over the pack-folder names, which is **byte order, case-sensitive** (`SongManager.cpp:443,652,678`). "Zeta" is therefore visited before "alpha". [CODE] This matches notes engine:3a and the corrected claim in engine:8 #3.
- A pack with zero loaded songs is deleted before `AddGroup` and cannot contribute a banner or a series membership (`SongManager.cpp:666-673`). [CODE]
- If no pack supplies a working banner, `GetSeriesBannerPath` picks the group with the smallest `GetGroupName()` by plain `std::string <` (byte order) and returns that **group's own banner path** (`SongManager.cpp:834-857`). [CODE] The lookup key is the exact Series text (`:835-836`).

### 2.2 What "resolves" means (refinement 1)

It means **only that the directory-listing call returns at least one entry.** [CODE `SongManager.cpp:407-411`]

- The listing goes through `RageFileManager::GetDirListing` → `FilenameDB::GetDirListing` → `GetFilesSimpleMatch` (`RageFileManager.cpp:503-564`; `RageUtil_FileDB.cpp:597-626,251-278`).
- Matching is **case-insensitive** (names are compared lower-cased: `RageUtil_FileDB.cpp:24-30`).
- A pattern may contain **one or two `*`** and no other wildcard. With no `*` it is an exact (case-insensitive) name match (`RageUtil_FileDB.cpp:76-88,251-278`). So `series-banner.*` works, and `?` is a literal character. This upgrades the notes' series:2 "wildcard should match [INFERRED]" to [CODE].
- The call passes `bOnlyDirs=false`, and the match code only skips non-directories when `bOnlyDirs` is true (`RageUtil_FileDB.cpp:34-36`). So **a folder with that name also "resolves".** There is **no extension check and no attempt to load the image.** [CODE]
- The value is a path relative to the pack folder. A subfolder such as `art/series.png` works, because the last path element is the mask and the rest is the directory (`RageUtil_FileDB.cpp:597-626`). [CODE]
- Entries starting `._` are stripped from the listing (`RageFileManager.cpp:554`, `StripMacResourceForks`). [CODE]

### 2.3 Refinement 2: the fallback does not skip bannerless packs

The fallback returns `GetSongGroupBannerPath(<alphabetically first pack in the series>)` and does not look further (`SongManager.cpp:855-857`). If that pack has no banner, the result is the empty string, even if a later pack in the series has a banner. [CODE] The notes' series:3(c) is correct but does not state this consequence.

### 2.4 When nothing resolves, or what resolves is not an image

- On song select, a highlighted series row sets `g_sBannerPath = SONGMAN->GetSeriesBannerPath(selectedSection)` (`src/ScreenSelectMusic.cpp:1807-1811`).
- An empty path loads the theme's **fallback banner**. `Banner::LoadFromCachedBanner` begins `if (sPath.empty()) { LoadFallback(); return; }`. A path that is not a texture and not a file (`IsAFile` false) also gets `LoadFallback()` (`src/Banner.cpp:63-85`). [CODE]
- Combining those: a `SeriesBanner` that resolves to a **folder**, or to a file that is not a loadable image, is accepted as "the" series banner. It stops later packs from supplying one, and then displays as the fallback banner. For the folder case this follows from the two code paths above and is [INFERRED]. For a non-image file I did not read the texture loader, so what shows is [UNVERIFIED] (check G3).

---

## 3. How the engine presents series (for mirroring, or deliberately differing)

All v1.3.0 unless marked. Most of this matches the notes (series:4-6); I re-read it in `MusicWheel.cpp`, `SongUtil.cpp` and `MusicWheelItem.cpp`.

### 3.1 When and how rows appear

- **Only in the Series sort order** (`SORT_SERIES`). The code's own comment says this is currently the only sort that makes parent rows (`MusicWheel.cpp:911-913`). Whether a theme offers or defaults to Series is theme-specific. Simply Love at `dd06138` lists it first and makes it the default [notes series:11, tag [CODE]]. I did not re-read the theme.
- **Row structure:** parent (series) row → pack (section) rows → song rows (`MusicWheel.cpp:911-970`). A pack with no series stays a top-level pack row.
- **Parent rows are made from runs of consecutive songs, not from a set.** A new parent row starts whenever a song's Series string differs from the previous song's: `!seriesName.empty() && (!haveLast || seriesName != lastSeries)` (`MusicWheel.cpp:929-930`). Likewise a new pack row starts whenever the pack's folder name changes (`:951-952`). This matters for the case-variants edge case (section 5).
- **Every non-empty Series gets a parent row in v1.3.0, even with one pack** (nothing in `:925-947` counts packs). [CODE]
- **Beta differs (not in v1.3.0):** a series with ≤1 group is treated as no series for display (`beta:src/MusicWheel.cpp:937-944`, from `05507f6b40`). The count is of groups registered in the series, not of packs with visible songs. [CODE for the rule on beta head; the count semantics are [INFERRED]]
- **Counts:** a series row shows its **song** count. A pack row shows its song count. Both are recomputed after filtering (`MusicWheel.cpp:~1401-1425`), and a header left with 0 songs is removed (`:~1427-1440`). [CODE]
- **Labels:** the series row shows the Series text via `ShortenSeriesName`. The pack row shows the pack's **DisplayTitle** (via `ShortenGroupName`, `Translations.xml` `<Groups>`), not the folder name. [CODE `MusicWheelItem.cpp:231-253`] The pack's identity in the wheel data is still its folder name (`MusicWheel.cpp:951-958`).
- Open/close behaviour, the `OnlyShowActiveParentSection` / `OnlyShowActiveSection` / `HideActiveSectionTitle` metrics and the "close folder" input are as in notes series:5-6. I did not re-verify them, because the Librarian view does not need them.

### 3.2 Ordering

[CODE `SongUtil.cpp:946-975`, `MakeSortString` `:450-463`]

- Each song gets the sort key `"1" + MakeSortString(Series) + '\x01' + MakeSortString(SortTitle)`. A pack with no series gets `"1" + MakeSortString(SortTitle)`. The sort is `stable_sort`.
- `MakeSortString` upper-cases the string, **drops one leading `.`**, and prefixes `~` (char 126) when the first character is not A-Z or 0-9. So names starting with a symbol sort **last**.
- So: series are ordered by their Series text, packs inside a series by **SortTitle**, and **standalone packs are interleaved with series names** by their own SortTitle. There is no separate "series sort title". A pack's `SortTitle` defaults to its folder name.
- **No tiebreaker on pack identity.** If two packs in the same series have the same SortTitle, equal keys keep their prior song order, so their songs can interleave and the wheel may emit repeated pack rows. [INFERRED from `:946-975` + the run logic above. Not run.]

### 3.3 What a one-pack series looks like

- **v1.3.0:** a parent row labelled with the Series text containing one pack row, whose count equals the pack's. [CODE]
- **Beta:** no parent row. The pack is a plain top-level row, but it still sorts at the position of its **Series text**, not its SortTitle alone, because the sort key is unchanged. [notes series:12b, tag [CODE]; the sort file `SongUtil.cpp` is unchanged on beta per notes series:12h, but see 3.4]

### 3.4 Beta status

The notes' beta comparisons stop at `e4b4bf0755` (84 commits past v1.3.0). Beta head is now `9778a4e36a`, **163 commits** past v1.3.0. Beta has since renamed members across these files (`368b41156e`, `7e06eaaf5f`), so a whole-file diff against v1.3.0 is almost entirely renames and no longer shows what changed in behaviour. I spot-checked on beta head: `Group.cpp` still reads `Series`/`SeriesBanner`/`Version` with the same trim, `GetSeriesBannerPath` has the same byte-order fallback, and the single-group rule is present. I did **not** re-diff the wheel, sort or loading code semantically. Treat beta as [UNVERIFIED] beyond those three points, per project rule.

### 3.5 Mirror or differ: the points where the view must choose

| Point | Engine (v1.3.0) | Choice for the Librarian view |
|---|---|---|
| Grouping key | Exact string | Mirror exactly (so the view says what the game will show), or fold case and warn. See section 5. |
| One-pack series | Gets a parent row | Mirror v1.3.0 (the pin), or follow beta. Beta behaviour is unverified at head. |
| Order | Series text, then SortTitle, `MakeSortString` rules | Mirror, or a simpler case-insensitive order. |
| What a "count" means | Songs after filtering | The app's rows are **charts**. Pack and series counts need distinct songs (`Course path`), or must be labelled as charts. |
| Pack label | DisplayTitle, shortened by `<Groups>` rules | The app's `Pack` is the folder name today (section 4). DisplayTitle needs the same Pack.ini read. |
| Where it shows | Series sort only | The view is separate from sorting, so this is a free choice. |

---

## 4. What the app already has, and what the one new read looks like

### 4.1 What the app has now [CODE, `dbdecf1`]

- **Pack is derived, not read.** `parse_cache_file` takes the cache's `#SONGFILENAME`, strips through the first `Songs`/`AdditionalSongs` component (`split_path`, `library_format.py:165-177`), and sets `pack` to the **first path segment** of the remaining song directory (`library_sources.py:264-267`). That value goes into each chart row as `"Pack"`, with the whole song folder as `"Course path"` (`:311`). It is the pack's **folder name**, not a display name.
- **The scan.** `_load_worker` lists the **flat** cache folder, `[p for p in cache.iterdir() if p.is_file()]` (`library_loader.py:326`), and parses each file in a loop with a per-file try/except (`:342-365`). Then it writes a snapshot under a lock (`:371-380`). The README states the cache folder is flat and the Songs tree is "not scanned recursively" (`README.md:25`).
- **Rows are charts.** Rows have no Series field. The snapshot schema is version 6 (`library_stores.py:21`). Adding a field to rows would bump it.
- **The existing Pack UI.** The dropdown is the sorted distinct `Pack` values from the rows, with "All packs" first (`library_filter.py:115-124`). Selecting one filters on exact equality, `row["Pack"] != pack` (`library_filter.py:178`). The `pack:` search directive is a case-insensitive substring match (`library_search.py:340-342`). The selection is saved as `filter_pack` (`library_librarian.py:612`).
- **Where the app knows the Songs folders.** `library_media.song_roots(cache_dir)` (`library_media.py:94-139`) is the app's only code that points at real song folders. It builds an ordered list from `<user-data>/Save/Preferences.ini` (`AdditionalSongFolders*`, `AdditionalFolders*`) plus `<user-data>/Songs`, where `<user-data>` is `cache_dir.parent.parent` (`:114-115`). Its docstring states: **"The install Songs root cannot be derived from the cache dir, so it is not supplied in v1."** It also says `Data/Static.ini` can override Preferences and is not read (`:105-111`). The only caller is the song page, `library_librarian.py:661`.
- **The Data paths dialog asks only for the Cache/Songs folder and Stats.xml** (`data_paths_dialog.py:199`; README paths). There is no setting for a Songs folder.
- **No existing Pack.ini, Series or pack-banner code.** A grep of `itgmania_library/*.py` for `Pack.ini`/`series`/`AdditionalSongs` finds only the path-stripping and media-roots code above.

### 4.2 What the one new read looks like

For each distinct `Pack` value in the loaded rows, look for `<root>/<Pack>/Pack.ini` across the roots, parse the `[Group]` section with the section 1 rules, and keep `Series` (and, for free, `DisplayTitle`, `SortTitle`, `Year`, `SeriesBanner`). The result would be a small **pack → fields** mapping, separate from the chart rows. Rules the reader must copy to agree with the game are in section 1.2-1.4. In short: exact `[Group]` and key names, `Version` required, last duplicate wins, trim only `\r\n\t `, first `=` splits, comments and line-continuation as listed.

### 4.3 Cost [INFERRED, not measured]

- **One small file read per pack folder per root.** Work is proportional to the number of packs, not songs. The existing scan already reads one file per cache file, which is per song, so this is a small fraction of it. I have not measured it. I do not know your pack count, and I made no timing run (no Windows, no real library).
- A **series-banner or pack-banner display** would add a directory listing per pack folder (the engine does one per pack for banners). That is separate from Pack.ini and only needed if the view shows banners.
- A single read is a few hundred bytes. The only slow case I can think of is network or USB drives, where each open has latency. [INFERRED]

### 4.4 Where the read belongs: options, no choice made

Per AGENTS.md, more than one defensible design means options plus a recommendation, then wait for you. These are the options I see. None is built.

| Option | Shape | Effect |
|---|---|---|
| **A. Inside the scan worker** | Read Pack.ini beside the cache-file loop; store the result in the snapshot. | Stored with the library, so it restores instantly at startup. But it changes the snapshot (schema 6→7) and mixes a second file source into `_load_worker`. A Pack.ini edit is not seen until the next full refresh. |
| **B. Separate step after the scan, not snapshotted** (recommended) [INFERRED] | A small data function (`library_*`, no Tkinter, tested) that takes the set of `Pack` values and the roots and returns the mapping. Called on the worker thread after a scan, and also when the view opens after a snapshot restore. | No schema change, because the snapshot already restores rows without a scan. Pack.ini is read fresh each time, which matches how the game itself only reads it at load/reload. One more place that must know about roots. |
| **C. Lazy, only when the view is opened** | Same function as B, run on demand. | Zero cost for users who never open the view. The first open has a small delay. |

B and C are the same function called from different places, so the choice between them can be made later. Option A is the only one that alters stored data and would likely need a design proposal under AGENTS.md ("persists a new … file format"). Introducing any new setting for Songs folders (see 4.5) also needs a proposal. This is [INFERRED] from the AGENTS.md text, not a ruling.

### 4.5 The root-discovery gap

This is the design's biggest dependency. `song_roots` omits the install `Songs` folder by design, and may also miss folders set only in `Static.ini`. Options, again unbuilt:

1. **Accept the limit.** Series shows for packs found in the user-data and Additional folders and shows "unknown" otherwise. Cheap, but a pack in the install folder is silently reported as "no series", which would be wrong.
2. **Add an optional Songs-folder path** (or an optional extra root) to the Data paths dialog. Complete, but it is a new setting and a UI change.
3. **Show the state honestly.** The view distinguishes "no Pack.ini found" from "Pack.ini found, no Series". With option 1 this at least avoids a false "no series" claim. [INFERRED]

Whichever is chosen, a pack split across two roots is **one** engine group with **one** Pack.ini. The engine's file layer merges the mounts. Which copy wins for Pack.ini is [UNVERIFIED] (check G6). `song_roots` assumes "later mounts win" for media (`library_media.py:94-104`), but I did not verify that rule for Pack.ini specifically.

---

## 5. Edge cases that shape the design

"Engine" is v1.3.0 [CODE] unless tagged. The last column is a suggestion for the view, [INFERRED], not a decision.

| # | Case | Engine behaviour | Implication for the view |
|---|---|---|---|
| 1 | **No Pack.ini** | No series. Display/sort title = folder name. (`Group.cpp:61,78`) | Group under "No series". The app cannot tell "no file" from "file not found because the root is unknown" (section 4.5). |
| 2 | **Pack.ini without usable `Version`/`[Group]`** | Whole file ignored, including `Series=`. (`Group.cpp:87-93`) | Mirror this. A pack whose file has `Series=` but no `Version=` is **not** in a series in game. A view that shows one anyway would disagree with the wheel. Consider a hint ("Pack.ini present but ignored by the game"). |
| 3 | **No `Series=` line, or empty** | No series. (`Group.cpp:61,108-110`) | "No series", same as 1. |
| 4 | **Series containing one pack** | v1.3.0: parent row with one child. Beta: no parent row, but sorted by Series text. (`MusicWheel.cpp:925-947`; beta `:937-944`) | Choose per section 3.5. |
| 5 | **Same Series name, different case** (`ITL Online` / `ITL online`) | Different series: the map key and the wheel comparison are exact (`SongManager.cpp:400`; `MusicWheel.cpp:930`). But sorting upper-cases, so they sort adjacent and interleave by pack SortTitle. Because parent rows start at every change of the exact string, a pattern like A-case, B-case, A-case in SortTitle order yields **three** parent rows, two labelled the same. [INFERRED from the run logic; not run, check G2] | If the view mirrors exactly, show them separately. A near-duplicate warning would be a useful addition, since this is almost certainly a typo in a Pack.ini. |
| 6 | **Duplicate `Series=` lines in one file** | Last wins (section 1.4). | Mirror. A parser that takes the first match would disagree with the game. |
| 7 | **`SeriesBanner` points to a missing file** | Ignored for that pack; a later pack in byte order can still supply one. If none does, falls back to the alphabetically first pack's banner, possibly none. (`SongManager.cpp:405-411,834-857`) | Only matters if the view shows banners. If it does, copy the order exactly: byte-order folder names, first non-empty wins. |
| 8 | **`SeriesBanner` points to a folder or non-image** | Counted as resolved (section 2.2); displays as fallback in game. | Same: only relevant if banners are shown. |
| 9 | **Folder name differs from the display name** | Engine key = folder name; wheel shows `DisplayTitle` (default: folder name), shortened by Translations `<Groups>`; order uses `SortTitle`. (`MusicWheelItem.cpp:244-253`; `Group.cpp:110-116`) | The app's `Pack` column and dropdown show the **folder name**. The view should decide whether to show DisplayTitle (needs this same read) or the folder name. Keep the folder name as the join key regardless, because `Pack` in rows and `Course path` in `.crs` files use it. |
| 10 | **Pack with no loaded songs** | Deleted before `AddGroup`; not in any series. (`SongManager.cpp:666-673`) | Packs come from the app's rows, which already only contain packs with at least one cached chart. This is consistent. A pack the cache has but the game failed to load is not detectable by the app. [INFERRED] |
| 11 | **Pack split across two roots** | One group; one Pack.ini. Precedence for Pack.ini is [UNVERIFIED]. | See 4.5 and check G6. |
| 12 | **Series text only differs by spaces inside** (`Mute  Sims`) | Different series (no normalization, section 1.4). | Mirror, or warn like case 5. |

---

## 6. What this report could not verify, and the exact check for each

I could not run the game, so every item below that says "in game" is a check for you. I also made no assumption about the contents of your library, your Songs folders or your Preferences.ini.

### 6.1 In-game checks (Windows, v1.3.0 build)

Use throwaway test packs with a few dummy songs. Switch the wheel to the Series sort for each.

| ID | Check | Settles |
|---|---|---|
| G1 | Pack with two lines, `Series=Alpha` then `Series=Beta`. Which parent row label appears? | Duplicate-key last-wins (section 1.4). Prediction: `Beta`. |
| G2 | Three packs: `Series=ITL Online`, `ITL online`, `ITL Online`, with SortTitles in the order A, B, C. How many parent rows, and what are they labelled? Also reported as an open item in notes series:10 item 1. | Case variants and the run-based parent rows (section 5 #5). Prediction: three. |
| G3 | `SeriesBanner` set to (a) a folder name that exists in the pack, (b) a non-image file, (c) `series-banner.*`, (d) a missing file, in different packs of one series. What banner shows on the series row? | "Resolves" semantics, folder and non-image cases, wildcard (section 2). Prediction: (a) fallback banner, (b) unknown, (c) the matched file. |
| G4 | Pack.ini with `Series=` but no `Version=` line. Does the pack join a series? | Version gate (section 1.3). Notes series:10 item 7 already lists it. Prediction: no. |
| G5 | A Series used by exactly one pack, on v1.3.0. Parent row with one child? | Section 3.3. Notes series:10 item 8. |
| G6 | One pack folder name present in two song roots, each with a different `Series=`. Which one wins? | Pack.ini precedence for split packs (section 4.5). |

### 6.2 Checks on your own machine (no game needed)

These need your real folders, so I give the commands without assuming any paths. Windows PowerShell commands below are **not run here** (no Windows in the sandbox).

1. **Where are your packs?** Open `%APPDATA%\ITGmania\Save\Preferences.ini` and note the `AdditionalSongFolders…` and `AdditionalFolders…` lines. Also note whether your game's install folder has its own `Songs` folder with packs in it. This settles whether the root gap (section 4.5) affects you.
2. **How many packs have a Pack.ini with a Series?** For each song root `<root>`:
   - `(Get-ChildItem "<root>" -Directory).Count`
   - `(Get-ChildItem "<root>\*\Pack.ini").Count`
   - `Select-String -Path "<root>\*\Pack.ini" -Pattern '^\s*Series\s*=' | Select-Object Path, Line`
   - `Select-String -Path "<root>\*\Pack.ini" -Pattern '^\s*Version\s*=' | Select-Object Path, Line` (a Pack.ini missing here is ignored by the game).
3. Anything the game would reject (leading-space `[Group]`, a `[group]` in the wrong case) will not show in the commands above, so compare their counts against what the in-game Series sort actually shows.

### 6.3 Not verified in this report

| Item | Status | What would settle it |
|---|---|---|
| Duplicate `Series=` behaviour in game | [CODE] only | Check G1. |
| Case-variant series producing several parent rows | [INFERRED] | Check G2. |
| What a folder or non-image `SeriesBanner` displays | folder: [INFERRED]; non-image: [UNVERIFIED] | Check G3, plus reading the texture loader if needed. |
| Pack.ini precedence for a pack in two roots | [UNVERIFIED] | Check G6, or read `RageFileManager::Open` and the mount order. |
| Beta head `9778a4e36a` wheel, sort and loading semantics | [UNVERIFIED] beyond the three spot-checks in 3.4 | A semantic re-diff against v1.3.0 that ignores renames. The notes' beta comparison (`e4b4bf0755`) is stale. |
| Simply Love behaviour (default sort, `HideInactiveSeries`) | Taken from notes series:11 [CODE at `dd06138`] | I did not re-read the theme. |
| Header-whitespace consequences (`  [Group]`, `[Group] `) | [INFERRED] | A test Pack.ini with each, in game. |
| Same-SortTitle packs in one series interleaving | [INFERRED] | Two packs, same SortTitle and Series, then look at the wheel. |
| Cost of the read on your library | [INFERRED], not measured | Time the PowerShell commands in 6.2 on your real folders, or time a prototype once one exists. |
| Cache `#SONGFILENAME` for songs in Additional folders reading `Songs/<pack>/…` | Notes cache spec, tag [INFERRED]; I did not inspect a real cache file | Open one cache file from a pack that lives in an Additional folder. |
| CI results or the app's test suite | Not run. I did not run `python -m unittest` for this report | Not needed for these findings. |

---

## 7. How this differs from what the notes say

These are refinements for the notes. I did **not** edit the notes repo, because this task said nothing is pushed. A follow-up commit there is expected under rule E and needs your go-ahead given that instruction.

1. **series:2 / series:3 (SeriesBanner "wildcard … [INFERRED]", "resolves to a real file").** Now [CODE]: only `*` wildcards (one or two), case-insensitive, and any file **or folder** counts as resolved. Nothing checks it is an image.
2. **series:3(c).** The fallback uses the alphabetically first pack's banner even if that banner is empty. It does not skip bannerless packs.
3. **series:2 (parsing).** New: duplicate `Series=` last wins; section and key names are case-sensitive and exact; a second `[Group]` block merges into the first; whitespace around `[Group]` breaks the section.
4. **series:4-5 (grouping).** New: parent rows are built from runs of consecutive songs with the same exact Series string, so case variants can yield repeated parent rows. This is [INFERRED], not run.
5. **series:12 (beta).** The beta comparison base is stale: beta is now 163 commits past v1.3.0 and has renamed members across the Series files.

---

## 8. Questions that need your decision before a proposal

These are the choices that change the design. I have not made them.

1. **Match the game exactly (case-sensitive grouping) or tidy it?** Mirroring tells you what the game will show. Folding case would hide the typo case in section 5 #5 unless a warning is added.
2. **v1.3.0 behaviour or beta behaviour for one-pack series?** The pin says v1.3.0. Beta is where the game is going, but I could not verify beta at head.
3. **How should the view find all Songs folders?** Accept the install-folder gap, add an optional Songs-folder setting, or both (4.5).
4. **Does the view show banners?** If not, section 2 is reference only and the read can stay at one small text file per pack.
5. **Pack label: folder name or DisplayTitle?** The read is the same either way.

— Claude
