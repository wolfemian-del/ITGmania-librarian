# Implementation Proposal: Rename the app to ITGmania Librarian

| | |
|---|---|
| **Status** | Accepted by Owner (2026-11-18) |
| **Author** | Muse (Muse Spark 1.3) |
| **Date** | 2026-11-18 |
| **Base** | main `0bc6328e` (merge of PR #231, issues #196+#197) |
| **Related** | Issue #209 (the name); Proposal 0012 (the package move — the module being renamed lives in the package it created); Proposal 0014 / issue #208 (warm parked; ordering note in §4) |

---

In plain language: the app is renamed from "ITGmania Library Visualizer" to "ITGmania Librarian", everywhere — the window title and About dialog, the settings folder, the shell module's name, and the repo. The owner will notice the new name in the title bar and About, and that the settings folder moves itself on first run, with the settings and the saved library coming along untouched. Nothing else changes: same library, same courses, same scores. The one real decision is the name itself — the owner's pick, Librarian over Manager and the snappier alternatives — and the two forks it carries, rename the module or only the strings, and rename the repo or keep the slug, both decided yes and recorded in §3.

## 1. Background and Goal

Issue #209 asked which name wins, the repo's ("viewer") or the app title's ("visualizer"). The owner's answer (2026-11-18) was neither: both suggest a read-only scope the roadmap no longer matches — courses are already writable, and the visioning points to cache editing as a future step. The owner picked "Librarian": a librarian catalogs, curates, weeds, and recommends, which is the roadmap in one word. "Manager" was the accurate-but-dull alternative; StepShelf, DanceCard, PackRat, and Radar were the snappier alternatives, set aside (PackRat is a real pun and the wrong tone; DanceCard says setlists, not library; StepShelf says storage, not management).

This change renames a component — the shell module — without moving any boundary: no function moves, no constructor changes, no new coupling. The only new shared name is `APP_NAME`, a constant in the bottom-layer constants module (see §4). Done means: one name everywhere — window, About, settings folder, module, repo — with the settings and snapshot carried over automatically, and the suite green.

## 2. Current State (measured on main `0bc6328e`)

- The display name "ITGmania Library Visualizer" appears in 6 code spots in `library_visualizer.py` (window title `:63`, welcome label `:237`, About menu `:434`, About window title `:717`, About label `:722`, the Tkinter-missing exit message `:745`), 2 docstrings (`theme.py:1`, `launch.py:1`), the README title (`:1`) and settings-path sentence (`:67`), and 1 test assertion (`tests/test_library_visualizer.py:1490`). All literals today — there is no single constant.
- The module `itgmania_library/library_visualizer.py` is named in 13 files: 9 import it (2 production, `__main__.py:3` and `launch.py:6`; 7 tests), 2 name it in a module list (`tests/test_layer_enforcement.py:32`, `tests/test_theme.py:15`), and 2 mention it in a comment (`tests/test_advanced_search.py:3`, `tests/test_data_paths_dialog.py:5`). It is also named in `docs/ARCHITECTURE.md` (5 spots), the README (`:91`, `:95`), and `.github/workflows/tests.yml` (`:46`, `:60`, `:61`). The test file is `tests/test_library_visualizer.py`.
- The settings folder name is computed in exactly one place, `_settings_file_path()` (`library_stores.py:156–166`): per-platform config root plus `"ITGmania Library Visualizer" / "settings.json"`. The folder holds exactly two files: `settings.json` and `library_cache.json` (the snapshot path derives from the settings path, `library_visualizer.py:451–452`). Neither file's contents mention the app name. No test pins the folder name.
- The repo slug "ITGmania-library-viewer" appears in 2 comments (`ruff.toml:1`, `.github/PULL_REQUEST_TEMPLATE.md:2`), the repo name itself, and the description ("A simple application to view and sort ITGmania chart data."). The README carries no repo URLs.
- The generic noun "the viewer" appears in 6 live spots (`AGENTS.md:66,71`; `.github/ISSUE_TEMPLATE/bug_report.md:3`, `enhancement.md:3`; `tests/test_end_to_end.py:127`, `tests/test_library_sources.py:552`). Line `AGENTS.md:71` says "viewer code" rather than "the viewer", so it needs its own edit on the same line.
- Coupling inventory: the shell imports the stores, and the stores import nothing from the shell — a stores→shell import would close a cycle, which `tests/test_layer_enforcement.py` fails on (verified 2026-11-18 by reading the test: it checks acyclicity and the exact Tk-importer set, and imposes no directional layer rule beyond the cycle check). `APP_NAME` touches no settings key and no file format; the settings file moves, its contents don't. The layer diagram in `ARCHITECTURE.md` records the shell at layer 5; the rename changes its name, not its layer.

## 3. The Decision: rename everything, once

The recommendation is to rename the module (Option A) and the repo, with `APP_NAME` as the single constant and a whole-directory migration. The alternatives, each decided by the owner on 2026-11-18:

- **Name: Librarian (owner's pick).** Manager is accurate and forgettable; StepShelf, DanceCard, PackRat, and Radar are snappier but each says only part of the job — storage, setlists, hoarding, scanning. Librarian is the only one that says catalog, curate, weed, and recommend.
- **Module: rename (Option A).** Strings-only (Option B) is cheaper and leaves a stale name at the heart of the codebase — the legibility tax the guidelines exist to avoid. Option A is a pure move, trial-verified (§6).
- **Repo: rename.** Keeping the slug is zero-risk and free, but it re-creates the exact mismatch #209 was filed about.
- **Migration: whole-directory rename, silent fallback to the old dir on failure** (see §4). Per-file copying risks missing a file the user dropped in the folder; a read-fallback with no move leaves two folders forever.
- **Version: no special bump.** An Unreleased CHANGELOG bullet; the version decision waits for release time.

## 4. Recommended Design in Detail

- `APP_NAME = "ITGmania Librarian"` lives in `library_constants.py` (the shared-vocabulary module; the only home both layers can import without closing a cycle — see §2). Its docstring widens a line. All six UI spots read it (window title, welcome label, About menu item, About title, About label, exit message); the settings path reads it too (`config_root / APP_NAME / "settings.json"`).
- The module becomes `itgmania_library/library_librarian.py`; the test file becomes `tests/test_library_librarian.py`. The 9 importers re-point; the 2 module lists (`test_layer_enforcement.py` `TK_MODULES`, `test_theme.py` `WINDOW_SOURCES`) rename their entry; the 2 comments re-point; `ARCHITECTURE.md` (5 spots), the README (`:91`, `:95`), and `tests.yml` (comment, step name, `-p` pattern) follow. `LibraryApp`, `main()`, and `__version__` move unchanged.
- The migration: a private `_migrate_config_dir(settings_path)` in `library_stores.py`, called at the top of `LibraryApp.__init__` before the settings load, taking the resolved settings path — the same function the tests patch, so the suite never touches a real config dir. Rules: new dir exists → nothing; old dir exists → rename it whole to the new name; rename fails → return the old path for this session and retry next launch; both exist → prefer the new, leave the old untouched. The migration stays permanently (users upgrade at different times; precedent: the snapshot schema migrations). It is not added to `__all__` — `test_import_surface.py` pins the names consumers import, including the private helpers the surface test lists, and the migration is private.
- The repo rename is the owner's web-UI job (Settings → Rename), done after this proposal is accepted and before the implementation PR, so the PR is filed under the new name; GitHub redirects the old URLs, and open PR #225 survives a rename. The owner also updates the repo description ("Manage your ITGmania library: browse charts, build courses, and keep your collection in order.") and their local remote; the local folder name can stay. Note: #225 is warm parked; its implementation, if ever un-parked, rebases onto the renamed tree.
- Docs: README title, settings-path sentence, `:91`, `:95`; ARCHITECTURE; a CHANGELOG Unreleased bullet; `AGENTS.md` and the issue templates ("the viewer" → "the app" — the durable choice; the proper name appears only where the name is meant); the `ruff.toml` and PR-template comments (the slug); the proposals README row (this proposal).
- The legibility test: the shell is "the shell: `LibraryApp`, the menu, and the `main()` entry point" (ARCHITECTURE's line, unchanged in meaning); the migration is "move the old config dir to the new one once, falling back to the old dir if the rename fails." Both sentences are the whole design.

## 5. What Does Not Change

- Package name `itgmania_library`; `LibraryApp`; `__version__` (1.3.0); the launch command (`python launch.py`); `requirements.txt`; `LICENSE`.
- `settings.json` contents; `library_cache.json` contents and schema (stays 6); the `.CRS` format; the game's files (the README line "The app does not edit either source" stays true).
- Historical records: `docs/proposals/0001–0013`, the CHANGELOG's past entries (including the Unreleased bullet about the 0012 launch command, a true statement about that change), the proposals README's PR #217 link, git history.
- Proposal 0014 stays warm parked; this proposal does not touch the startup wiring, only the shell's name and two import lines in `launch.py` / `__main__.py`.

## 6. Test Plan (for the implementation PR)

- New migration tests (temp dirs, `_settings_file_path` patched): old dir with both files migrates (both land in the new dir, old dir gone); both dirs exist → new wins, old untouched; neither exists → no-op; rename failure (patched to raise) → falls back to the old path.
- The About test asserts the literal "ITGmania Librarian"; the full suite is 791 tests plus the new migration tests, green headless and under Xvfb; pyflakes and ruff clean; no added code line over 100.
- The windows-ui trap: `tests.yml`'s `-p` pattern must become `test_library_librarian.py` — verified [RAN] that a non-matching pattern runs 0 tests and exits 5 (`NO TESTS RAN`), so a stale pattern fails the job instead of passing it silently; the reviewer still checks the run log shows the live tests ran under the new pattern.
- A grep check afterwards: "visualizer" only in `docs/proposals/*` and the CHANGELOG history bullet; "ITGmania-library-viewer" only in `docs/proposals/README.md:26`; "the viewer" only in `docs/proposals/*`.
- One PR, not staged (a half-renamed tree is worse than a big diff). Windows smoke (owner): first launch moves `%APPDATA%\ITGmania Library Visualizer` → `%APPDATA%\ITGmania Librarian` with settings and library intact; About shows the new name and version; a second launch changes nothing.
- Evidence already in hand (trial, 2026-11-18, scratch worktree, nothing pushed): the full rename done once — 24 files, +55/−47 — suite 791 OK headless and under Xvfb, lint clean. The trial did not add a CHANGELOG entry or implement the migration; the implementation PR does both.

## 7. Open Questions — Resolved

The five forks below were decided by the owner on 2026-11-18, before this draft was filed; they are recorded here so the reviewer can challenge them.

- **Q1.** Module rename or strings-only? Recommendation: rename (Option A). **Resolved: rename.**
- **Q2.** Repo rename or keep the slug? Recommendation: rename. **Resolved: rename.**
- **Q3.** Repo description wording? Recommendation: "Manage your ITGmania library: browse charts, build courses, and keep your collection in order." **Resolved: as recommended.**
- **Q4.** Version bump or Unreleased bullet? Recommendation: no special bump; decide at release time. **Resolved: Unreleased bullet.**
- **Q5.** Proposal first or straight to the implementation PR? Recommendation: a small proposal — the workflow rule's triggers are met (a component-boundary identity change, files persisted at a new location, multiple defensible designs). **Resolved: proposal first.**

---

*Written by Muse (Muse Spark 1.3). The scope this proposal is drawn from was verified before filing: a trial rename in a scratch worktree (suite 791 OK headless and under Xvfb, pyflakes and ruff clean) and a migration prototype (4/4 cases pass).*
