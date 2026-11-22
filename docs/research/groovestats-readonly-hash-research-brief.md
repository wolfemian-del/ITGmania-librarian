> **Provenance:** research brief by Grok, 2026-11-22. Landed in the repo with the roadmap (2026-11-22). Verified by Muse against the v1.3.0 engine source, the notes' cache spec, and Simply Love v5.9.0 — accept, no corrections. Body below is verbatim as delivered; only this header was added.

# Research brief: GrooveStats read-only integration — the chart-hash question

**Parent work:** course-builder survey and Simply Love courses brief (both 2026-11-22)  
**Scope:** research only — no code changes, no branch, no PR  
**Author:** Grok (xAI)  
**Date:** 2026-11-22  

**Sources read:** notes `INDEX.md`, `notes/itgmania_cache_format_spec.txt` §5, `notes/itgmania_score_matching_findings.txt` §5–§6; engine v1.3.0 `8a3bf8884a` (`Steps.cpp` / `Steps.h`, `NotesWriterSSC.cpp`, `NotesLoaderSSC.cpp`); Simply Love v5.9.0 @ `dd06138` (`SL-Helpers-GrooveStats.lua`, `SL-ChartParser.lua`, `SL_Init.lua`, `PaneDisplay.lua`); app `library_sources.py` (`parse_cache_file`), `library_constants.py` (`HEADERS`).

Score **submission is out of scope** (the game already submits). Shape under evaluation: read-only best/rank beside local best.

Confidence tags: **[CODE]**, **[INFERRED]**, **[UNVERIFIED]**, **[RAN]** (none — no live API calls).

---

## 1. The chart hash (crux)

**Algorithm** [CODE] `Steps::CalculateGrooveStatsHash` / `MinimizedChartString` in `src/Steps.cpp` (v1.3.0); notes cache-format §5:

1. Build a **minimized** SM note string from `NoteData` via `NoteDataUtil::GetSMNoteDataString(..., bIncludeMeasureComments=false)`, then collapse empty odd-row padding in measures (so quarter-note padding does not change the hash).  
2. Append **BPM segments only**: each `BPMSegment` as `NormalizeDecimal(beat)=NormalizeDecimal(bpm)`, joined by commas.  
3. `SHA-1` of that string → hex → **first 16 characters**.  
4. Store as `m_sGrooveStatsHash`; set `m_iGrooveStatsHashVersion = CURRENT_GROOVE_STATS_HASH_VERSION` (**3** in `Steps.h`).

**Inputs covered:** note data (all tracks — column count matters) and BPM change list.  
**Not covered:** stops, delays, warps, speed/scroll, song offset, steps type name, difficulty, meter, description, credit. [CODE][INFERRED] consequence: two charts with identical notes+BPMs but different stops share a hash (documented in cache-format §5).

**SSC tags:** `#GROOVESTATSHASH` and `#GROOVESTATSHASHVERSION` are written by `NotesWriterSSC` and loaded by `NotesLoaderSSC` (`steps_tag_handlers["GROOVESTATSHASH"]`). [CODE]

**Same value from what the app already has?**  
**Yes, without re-hashing, for charts whose cache is current.** The song **cache** already embeds the precomputed hash (next section). The app’s cache parse simply does not read those tags yet. Reimplementing SHA-1 from note data is only a fallback for missing/stale cache or empty charts.

Simply Love’s own `ComputeChartHash` [CODE] `Scripts/SL-ChartParser.lua` re-derives the same 16-hex form by parsing the **simfile** (note string + BPMs) and `CRYPTMAN:SHA1String` — it does **not** call `steps:GetGrooveStatsHash()`. That is a theme choice (expensive; they cache per filename/type/difficulty/description); the engine already computed and cached the value on disk.

---

## 2. Does the game cache carry the GrooveStats hash?

**Yes.** [CODE] cache-format spec §2c / §5; `NotesWriterSSC.cpp` writes under `// step cache tags:`:

```text
#GROOVESTATSHASH:<16 hex>;
#GROOVESTATSHASHVERSION:<int>;
```

alongside `#TECHCOUNTS`, `#NPSPERMEASURE`, `#PEAKNPS`, etc. No note data is in the cache file — only these derived fields.

**App today:** `parse_cache_file` in `library_sources.py` builds rows from `#TITLE`, `#STEPSTYPE`, `#DIFFICULTY`, `#METER`, radar, tech counts, `#PEAKNPS`, media tags, etc. **It does not read `#GROOVESTATSHASH` or `#GROOVESTATSHASHVERSION`.** [CODE] row construction in that function; `HEADERS` in `library_constants.py` has no GS column.

**Where the parse would pick it up:** same chart block loop that already reads `#PEAKNPS` / `#TECHCOUNTS` — add two tags (or one hash + version) as **hidden** row keys (like `Course path`), not necessarily as table columns.

Stale or pre-hash caches may lack the tags; `FILE_CACHE_VERSION` is 232 on v1.3.0 and the engine rewrites when it changes [CODE] cache-format §4. Missing hash → treat as unavailable for GS lookup, not as a hard parse failure.

---

## 3. Stats.xml `Hash=` vs GrooveStats hash

**Different values, different purposes.** [CODE] score-matching notes §3, §5, §6:

| | Profile `Hash=` (Edit charts only) | GrooveStats hash |
| --- | --- | --- |
| Algorithm | CRC32 of compressed/normalized note string (`Steps::GetHash` → `GetHashForString`) | SHA-1, first 16 hex of minimized notes + BPM segments |
| When used | StepsID key **only** for `Difficulty_Edit` (with description) | Online chart identity for all difficulties |
| Non-Edit charts | Hash stored as 0 / not part of key | Still has a GS hash |
| Timing | Not in CRC string | BPMs in; stops/warps **out** |

So **Stats.xml does not give the GrooveStats key**, even for Edits. The app’s existing score path cannot substitute for GS.

---

## 4. If cache / Stats lacked it — work size (fallback only)

Given §2, the **primary path does not need this**. Fallbacks if a row has no `#GROOVESTATSHASH`:

| Approach | Work | App today |
| --- | --- | --- |
| Read `#GROOVESTATSHASH` from `.ssc`/`.sm` on disk | Small: open song file, regex one tag per chart | **New read** — app is cache+Stats only for library rows; song folders are used for media, not full simfile parse |
| Reimplement `MinimizedChartString` + SHA-1 | Medium–large: need full note data + BPM list; parity with engine minimization is easy to get wrong | App does **not** load note data today |
| Call into a native helper / ask the game | Out of scope for a read-only Python app | — |

**Recommendation:** Prefer cache field; optional “missing hash” status; only consider simfile `#GROOVESTATSHASH` if product needs coverage of unscanned packs. Do not reimplement the hash in v1.

---

## 5. Read API surface (from SL as reference client)

**Base URL** [CODE] `SL-Helpers-GrooveStats.lua`:  
`https://apiservice.groovestats.com/api/`

**Actions SL uses** (from theme + task context): `newSession`, `playerScores`, `playerLeaderboards`, `scoreSubmit` (submit out of scope).

### `newSession`

- Example endpoint: `?action=newSession&chartHashVersion=` + `SL.GrooveStats.ChartHashVersion` (**3**). [CODE] comment/example in `RequestResponseActor`  
- Sets which services are available (`GetScores`, `Leaderboard`, `AutoSubmit` flags in `SL.GrooveStats`). [CODE] `SL_Init.lua`  
- **Whether every read client must call it first:** theme does; **service contract stability for a third-party client is [UNVERIFIED] — only GrooveStats can confirm.**

### `playerScores` (select pane)

- Query includes per-player `chartHashP1` / `chartHashP2` and headers `x-api-key-player-1` / `x-api-key-player-2`. [CODE] `PaneDisplay.lua`  
- Response (as consumed by SL): per `playerN` object with `chartHash`, `gsLeaderboard` and/or `exLeaderboard` arrays of entries with at least **`rank`**, **`score`** (integer, e.g. 9823 → 98.23%), **`isSelf`**, **`isRival`**, **`name`**, **`machineTag`**. [CODE] `GetScoresRequestProcessor` in `PaneDisplay.lua`  
- Exact full schema, error bodies, and versioning: **[UNVERIFIED]** without service docs or a live capture.

### `playerLeaderboards`

- Used elsewhere in SL for fuller leaderboard UI; same hash + API key pattern. Full response shape not fully enumerated in this pass → **[UNVERIFIED]** detail.

### Caching / rate behaviour visible in the theme

- In-memory `SL.GrooveStats.RequestCache` keyed by a hash of chart hashes + API keys; `RemoveStaleCachedRequests` drops old entries. [CODE] `SL_Init.lua`, `SL-Helpers-GrooveStats.lua`  
- **Service-side rate limits, ToS for non-game clients, and required contact process:** **[UNVERIFIED]** — GrooveStats asks developers to contact them before building; do that before any implementation.

---

## 6. Auth handling

**File:** `GrooveStats.ini` in the **player profile directory** (same tree as `Stats.xml`). [CODE] `ParseGrooveStatsIni` in `SL-Helpers-GrooveStats.lua`:

```ini
[GrooveStats]
ApiKey=<64-character key>
Username=...
IsPadPlayer=0|1
```

- Key length must be **64**; otherwise SL clears it.  
- Path relative to the profile the app already targets for Stats.xml:  
  `{profile_dir}/GrooveStats.ini` next to `{profile_dir}/Stats.xml`.

**App implications:**

- If the user already has Simply Love configured, **no new credential entry** is required — read the ini at use time from the configured profile path.  
- **Secret handling:** read at request time; **never** log, never show in UI, never write into `settings.json` or the snapshot. Optional in-memory only for the session. Failed/missing key → degrade to local-only (no GS columns), not a crash.  
- Pad-player / multi-profile: one key per profile file; match the profile the app is showing scores for.

---

## 7. What the app would have to change (honest size)

| Piece | Size | Proposal under AGENTS.md? |
| --- | --- | --- |
| **Parse `#GROOVESTATSHASH` / `#GROOVESTATSHASHVERSION` into hidden row keys** | Small, localized in `library_sources.parse_cache_file` | **Yes if snapshot schema bumps** (rows are snapshotted; adding fields that must survive restore is a schema concern — current snapshot is version **6**). If treated as ephemeral “enrichment after load” and not stored in snapshot, schema bump may be avoidable — **design fork → proposal**. |
| **Optional column / song-page fields** (GS best %, rank) | UI + constants | Column group / song-page layout: follow existing patterns; proposal only if new settings keys (e.g. “show GrooveStats”). |
| **Network layer** (none today) | New module or service: HTTP GET, JSON parse, timeouts, cancel on navigation | **Yes — new component boundary** (who owns requests, threading vs Tk, error surface). |
| **Request cache + offline/fail** | Local best always shown; GS side “unavailable / stale / no key / offline” | Policy should be explicit; may be part of the same proposal. |
| **Auth read** | Read `GrooveStats.ini` beside Stats path | No new secret storage; path discovery may share data-paths settings. |
| **`newSession` + service flags** | Small if required | Depends on §5 verification with GrooveStats. |
| **Score submit** | **Do not implement** | — |

**Suggested ownership:** a Tk-free data helper for hash extraction + request building; an application-service or shell-owned async requester (same pattern as load workers) so the table never blocks on the network.

**Degrade path:** local Score / Best % / Grade unchanged; GS fields empty or marked unavailable; no blocking dialogs on every row.

---

## 8. Unverified items and checks

| Item | Check that settles it |
| --- | --- |
| Official API docs, rate limits, allowed third-party clients | **Contact GrooveStats** before building (they request this). |
| Whether `newSession` is mandatory for `playerScores` | Ask them; or capture SL traffic on boot vs first scores request. |
| Full JSON schema of `playerScores` / `playerLeaderboards` | Capture responses (or docs from GS); theme only uses a subset. |
| Stability across `chartHashVersion` (currently 3) | Ask GS; theme constant must stay in sync if the service bumps. |
| Real cache sample contains `#GROOVESTATSHASH` on the owner’s machine | Open one `Cache/Songs/…` file after playing a chart under v1.3.0; confirm tags present. |
| Cache missing hash for some packs (old caches) | Sample older cache files; measure miss rate. |
| Whether engine Lua exposes `GetGrooveStatsHash()` for themes | Optional; SL does not use it — app does not need Lua. |

---

## Bottom line

Read-only GrooveStats integration is **practical** if:

1. The app **reads `#GROOVESTATSHASH` already written in the song cache** (primary key — no note-data hash reimplementation).  
2. It **reads `GrooveStats.ini` next to Stats.xml** (no new secret store).  
3. It adds a **small, cancelable HTTP client** for `playerScores` (and optionally leaderboards), with offline degrade.  
4. **GrooveStats is contacted first** for client approval, rate limits, and session requirements.

The main product/design decisions (snapshot schema vs ephemeral enrichment; network module boundary; UI placement) need an **AGENTS.md proposal** before implementation. Hash **acquisition** itself is not the hard part — the cache already has the answer.

---

*Signed: Grok (xAI), 2026-11-22*  
*Deliverable only — nothing pushed or opened.*
