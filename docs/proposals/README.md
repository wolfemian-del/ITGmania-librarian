# Proposals

Design proposals for changes that need one under `AGENTS.md`: a change that
creates or alters a component boundary or constructor contract, persists a
new settings key or file format, or has two or more defensible designs where
the choice constrains later work. Each proposal is reviewed like a pull
request and marked Accepted by the owner before implementation. The status
line in each file's header is the record; this index summarizes it.

`0000-template.md` is the blank template, not a proposal.

| Proposal | Title | Status | Implemented by |
| --- | --- | --- | --- |
| [0001](0001-course-builder-split.md) | Extract the Course Builder into `course_builder.py` | Accepted 2026-11-07 | PR #81 (merged 2026-11-08) |
| [0002](0002-layout-constants.md) | Move Layout Constants into `theme.py` | Accepted 2026-11-08 | PR #90 (merged 2026-11-08) |
| [0003](0003-course-builder-geometry.md) | Remember the Course Builder Window's Size and Position | Accepted 2026-11-08 | PR #96 (merged 2026-11-08) |
| [0004](0004-advanced-search-split.md) | Extract the Advanced Search Dialog into Its Own Component | Accepted 2026-11-08 | PR #99 (merged 2026-11-08) |
| [0005](0005-distribution-panel-split.md) | Extract the Distribution Panel into Its Own Component | Accepted 2026-11-09 | PRs #110, #111, #113 (merged 2026-11-10) |
| [0006](0006-filter-persistence.md) | Persist the Pack / Type / Difficulty Filter Dropdowns | Accepted 2026-11-10 | PR #117 (merged 2026-11-11) |
| [0007](0007-bpm-and-subtitle.md) | BPM semantics and the Subtitle column | Accepted 2026-11-11 | PRs #127, #128, #134 (merged 2026-11-11) |
| [0008](0008-settings-snapshot-split.md) | Split the Settings and Snapshot Machinery out of `LibraryApp` | Accepted 2026-11-12 | PRs #146, #148, #149 (merged 2026-11-12) |
| [0009](0009-libraryapp-split.md) | Split LibraryApp into Its Own Components | Accepted 2026-11-14 | PRs #163–#168 (proposal #161, acceptance #162; merged 2026-11-14) |
| [0010](0010-library-data-split.md) | Split library_data.py into Data Modules | Accepted 2026-11-14 | PRs #170, #174–#181 (proposal #169; merged 2026-11-14/15) |
| [0011](0011-song-page-media-previews.md) | Song Page with Media Previews | Accepted 2026-11-16 | PR #185 (merged 2026-11-16) |
| [0012](0012-package-move.md) | Move the app into the `itgmania_library` package | Accepted 2026-11-16 | PR #188 (merged 2026-11-16) |
| [0013](0013-song-page-sizing.md) | Size the song page by its contents, and scroll the chart list | Accepted 2026-11-17 | [#217](https://github.com/wolfemian-del/ITGmania-library-viewer/pull/217) |
| [0014](0014-startup-wiring.md) | Make the startup wiring plain | Accepted 2026-11-18 | – (issue #208) |
