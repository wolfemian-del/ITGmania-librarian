"""Song media resolution (Proposal 0011, stage 2) and preview playback
(stage 4).

Tk-free helpers for the song page: where the game's song folders live,
how a media filename from the cache resolves to a file on disk, which
charts belong to one song, the media record the page is shown, and the
preview player seam — pygame-ce's mixer, imported lazily so the page
still opens without it.

The engine resolves the VFS path ``Songs/<pack>/<song>/<file>`` against
its mounts at open time, first hit wins per file (StepMania.cpp:715-725,
:826-837; RageFileManager.cpp:701-703). This module mirrors that order
for filesystem roots only: media inside Packages zips is out of scope
for v1, so a song whose media lives only in a zip shows placeholders.
"""

import dataclasses
import importlib.util
import math
import os
import re
from pathlib import Path

from itgmania_library.library_format import difficulty_sort_key

__all__ = [
    "AUDIO_EXTENSIONS",
    "IMAGE_EXTENSIONS",
    "SongMedia",
    "SongPreviewPlayer",
    "build_song_media",
    "charts_for_song",
    "normalize_sample_window",
    "open_song_folder",
    "player_available",
    "resolve_media_file",
    "song_roots",
]

# The engine's extension allowlists (RageSurface_Load.cpp:23-30 for
# images; RageSoundReader_FileReader.cpp:22-31, ActorUtil.cpp:536-540
# for audio). A filename outside its kind's list is "not found", so a
# path built from simfile text cannot open an arbitrary file.
IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".gif", ".bmp"})
AUDIO_EXTENSIONS = frozenset({".ogg", ".oga", ".mp3", ".wav"})

# Preference keys in Preferences.ini (ITGmania v1.3.0, PrefsManager.cpp).
_SONG_WRITABLE_KEY = "AdditionalSongFoldersWritable"
_SONG_READONLY_KEY = "AdditionalSongFoldersReadOnly"
_SONG_DEPRECATED_KEY = "AdditionalSongFolders"
_FOLDERS_WRITABLE_KEY = "AdditionalFoldersWritable"
_FOLDERS_READONLY_KEY = "AdditionalFoldersReadOnly"
_FOLDERS_DEPRECATED_KEY = "AdditionalFolders"

# A value starting with one of these is a VFS-top-relative path, not a
# song-relative one: the engine would resolve it against the VFS top.
_VFS_TOP_PREFIXES = ("songs/", "additionalsongs/")
_DRIVE_LETTER = re.compile(r"^[A-Za-z]:")
# A single path component that is a drive letter ("C:"): joining it
# onto a root drops the root on Windows (PureWindowsPath), so it is
# refused wherever it appears, not only at the start of a value.
_DRIVE_PART = re.compile(r"^[A-Za-z]:$")


def _split_list(value):
    """A comma-split preference value as stripped, non-empty entries."""
    if not isinstance(value, str):
        return []
    return [entry.strip() for entry in value.split(",") if entry.strip()]


def _read_preferences(path):
    """Preferences.ini as a key/value dict, or {} when it cannot be read.

    Read as utf-8-sig, on the settings store's idiom: a BOM is
    tolerated, and a missing or unreadable file means no additional
    folders, never a crash.
    """
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError):
        return {}
    prefs = {}
    for line in text.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        prefs[key.strip()] = value.strip()
    return prefs


def song_roots(cache_dir):
    """The ordered song-folder roots for a cache dir, highest first.

    Derived from Preferences.ini and the cache dir every time (Proposal
    0011 Q7): the AdditionalSongFoldersWritable entries, then the
    ReadOnly entries, then the AdditionalFoldersWritable entries (each
    plus /Songs), then the AdditionalFoldersReadOnly entries (each plus
    /Songs), then the user-data Songs folder. Within one list the later
    entries outrank the earlier ones, since later mounts win. The
    deprecated AdditionalSongFolders / AdditionalFolders value wins over
    its Writable one whenever it is nonempty (PrefsManager.cpp:548-556).
    A missing or unreadable Preferences.ini means no additional folders.
    The install Songs root cannot be derived from the cache dir, so it
    is not supplied in v1. Data/Static.ini is read after Preferences.ini
    and can override these preferences, so it is a stated limit of
    deriving from Preferences.ini alone.
    """
    if cache_dir is None:
        return []
    cache_dir = Path(cache_dir)
    user_data_root = cache_dir.parent.parent
    prefs = _read_preferences(user_data_root / "Save" / "Preferences.ini")

    def effective(deprecated_key, writable_key):
        deprecated = _split_list(prefs.get(deprecated_key, ""))
        if deprecated:
            return deprecated
        return _split_list(prefs.get(writable_key, ""))

    roots = []
    for entry in reversed(effective(_SONG_DEPRECATED_KEY, _SONG_WRITABLE_KEY)):
        roots.append(Path(entry))
    for entry in reversed(_split_list(prefs.get(_SONG_READONLY_KEY, ""))):
        roots.append(Path(entry))
    for entry in reversed(effective(_FOLDERS_DEPRECATED_KEY, _FOLDERS_WRITABLE_KEY)):
        roots.append(Path(entry) / "Songs")
    for entry in reversed(_split_list(prefs.get(_FOLDERS_READONLY_KEY, ""))):
        roots.append(Path(entry) / "Songs")
    roots.append(user_data_root / "Songs")
    seen = set()
    unique = []
    for root in roots:
        if root not in seen:
            seen.add(root)
            unique.append(root)
    return unique


def _song_dir_parts(song_dir):
    """A song dir as its path components, or None when it is not one."""
    if not isinstance(song_dir, str) or not song_dir:
        return None
    parts = [part for part in song_dir.replace("\\", "/").split("/")
             if part not in ("", ".")]
    if not parts or ".." in parts:
        return None
    if any(_DRIVE_PART.match(part) for part in parts):
        return None
    return parts


def _media_path(song_dir, filename):
    """A media filename resolved lexically under the song's pack folder.

    Returns the path relative to a root, or None when the value is not
    a song-relative file: absolute, drive-letter, or VFS-top-relative
    (starting with Songs/ or AdditionalSongs/), or escaping the pack
    folder with ... A bare filename, a subdirectory, and a .. that lands
    inside the pack folder are song-relative.
    """
    if not isinstance(filename, str) or not filename:
        return None
    value = filename.replace("\\", "/")
    if value.startswith("/") or _DRIVE_LETTER.match(value):
        return None
    if value.casefold().startswith(_VFS_TOP_PREFIXES):
        return None
    parts = _song_dir_parts(song_dir)
    if parts is None:
        return None
    stack = list(parts)
    for part in value.split("/"):
        if part in ("", "."):
            continue
        if _DRIVE_PART.match(part):
            return None
        if part == "..":
            if len(stack) <= 1:
                return None
            stack.pop()
            continue
        stack.append(part)
    return Path(*stack)


def resolve_media_file(song_dir, filename, roots, kind):
    """The first file for a media filename, probing the roots in order.

    ``kind`` is "image" or "audio"; anything else is a programming
    error and raises ValueError. A filename outside its kind's
    allowlist, a non-string or empty filename, and any value that is
    not a song-relative file under the pack folder (see _media_path)
    all read as "not found" and return None. Resolution is per file,
    not per folder, because the engine's priority is per file — a split
    pack can take its banner from one root and its music from another.
    """
    if kind == "image":
        allowed = IMAGE_EXTENSIONS
    elif kind == "audio":
        allowed = AUDIO_EXTENSIONS
    else:
        raise ValueError(f"unknown media kind: {kind!r}")
    if not isinstance(filename, str) or not filename:
        return None
    if Path(filename).suffix.casefold() not in allowed:
        return None
    relative = _media_path(song_dir, filename)
    if relative is None:
        return None
    for root in roots:
        candidate = Path(root) / relative
        if candidate.is_file():
            return candidate
    return None


def charts_for_song(library_rows, course_path):
    """The charts for one song, ordered by chart type then difficulty.

    The song's identity is its "Course path": every row sharing it is
    one of the song's charts. The order is the page's order — type
    first, then the difficulty rank.
    """
    charts = [row for row in library_rows
              if row.get("Course path") == course_path]
    charts.sort(key=lambda row: (
        str(row.get("Type", "")).casefold(),
        difficulty_sort_key(row.get("Difficulty", "")),
    ))
    return charts


@dataclasses.dataclass(frozen=True)
class SongMedia:
    """The media record for one song, as the song page is shown it.

    Paths are files that exist, or None where no root holds the file.
    The length and sample window describe the song's music file, so
    when the opened chart carries its own #MUSIC the record carries
    that file with no length and no sample window. ``folder`` is the
    highest-priority root where the song's folder is a directory, or
    None.
    """

    banner: Path | None = None
    background: Path | None = None
    jacket: Path | None = None
    cd_title: Path | None = None
    music: Path | None = None
    music_length: float | None = None
    sample_start: float | None = None
    sample_length: float | None = None
    folder: Path | None = None


def _finite_float(value):
    """A row value as a finite float, or None when it is not one.

    The parse stores numbers as floats and missing values as "", but a
    hand-edited snapshot can hold anything: a non-numeric string, a
    non-finite float, or a value of the wrong type. All of those read as
    missing, so one bad row cannot fail the page open (Proposal 0011,
    stage 2 — the F1 carry-over from the stage-1 review).
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            number = float(value)
        except OverflowError:
            # A huge int from a hand-edited snapshot's JSON number
            # (10**10000): too large to convert, so it reads as missing
            # rather than raising into the page open or the Play action.
            return None
    elif isinstance(value, str):
        try:
            number = float(value)
        except ValueError:
            return None
    else:
        return None
    return number if math.isfinite(number) else None


def _media_value(row, key):
    """A row's media filename as a string, or None when it is not one."""
    value = row.get(key)
    return value if isinstance(value, str) and value else None


def build_song_media(song_dir, roots, rows):
    """Assemble the media record for one song from its chart rows.

    ``rows`` are the song's charts, with the opened chart first: the
    record's music is the opened chart's effective Music, and the length
    and sample window are included only when that music is the song's
    music. The song's music is inferred, not stored: stage 1 keeps only
    each chart's effective Music, so the record keeps the window only
    when every chart carries the same Music as the opened chart. When
    charts disagree, the song's file cannot be told apart from a chart
    override, so the window is dropped rather than applied to the wrong
    file; a single chart keeps its window, since there is nothing to
    disagree with — which is also wrong when that one chart has an
    override, and cannot be known from the rows. A song under no root
    has no folder and no media, never a crash.
    """
    if not rows:
        return SongMedia()
    opened = rows[0]
    opened_music = _media_value(opened, "Music")
    music_is_song_music = (
        opened_music is not None
        and all(row.get("Music") == opened_music for row in rows)
    )
    folder = None
    parts = _song_dir_parts(song_dir)
    if parts is not None:
        for root in roots:
            candidate = Path(root).joinpath(*parts)
            if candidate.is_dir():
                folder = candidate
                break
    return SongMedia(
        banner=resolve_media_file(song_dir, _media_value(opened, "Banner"),
                                  roots, "image"),
        background=resolve_media_file(song_dir, _media_value(opened, "Background"),
                                      roots, "image"),
        jacket=resolve_media_file(song_dir, _media_value(opened, "Jacket"),
                                  roots, "image"),
        cd_title=resolve_media_file(song_dir, _media_value(opened, "CDTitle"),
                                    roots, "image"),
        music=resolve_media_file(song_dir, opened_music, roots, "audio"),
        music_length=(_finite_float(opened.get("Time"))
                      if music_is_song_music else None),
        sample_start=(_finite_float(opened.get("SampleStart"))
                      if music_is_song_music else None),
        sample_length=(_finite_float(opened.get("SampleLength"))
                       if music_is_song_music else None),
        folder=folder,
    )


def open_song_folder(path):
    """Open a song's folder in the file manager; True when it opened.

    Windows-only: os.startfile does not exist elsewhere, so off Windows
    this returns False and the folder button stays disabled. A missing
    path, or a path that is not a directory, also returns False.
    """
    if path is None:
        return False
    folder = Path(path)
    if not folder.is_dir():
        return False
    startfile = getattr(os, "startfile", None)
    if startfile is None:
        return False
    try:
        startfile(str(folder))
    except OSError:
        return False
    return True


# The engine's default sample length in seconds (Song.cpp:72): the
# fallback wherever the cache gives no usable window.
DEFAULT_SAMPLE_LENGTH = 12.0


def normalize_sample_window(start, length, music_length):
    """A sample window as (start, length) in seconds, fit to play.

    The cache values are post-normalisation — the engine tidies them
    before writing the cache (Song.cpp:387/:395) — so a real cache
    needs nothing here; this only handles the blank and garbage cases
    the page must not hand to play(): a blank, zero or negative length
    plays the default 12 s (stage-2 F5: a negative value is unusable);
    a blank or negative start, or a window running past the music
    length, starts at 0 for 12 s or to the end of the song, whichever
    is shorter (Proposal 0011 §4). A music length of zero or less is
    treated as unknown. The returned length is always positive.
    """
    start = _finite_float(start)
    length = _finite_float(length)
    total = _finite_float(music_length)
    if total is not None and total <= 0:
        total = None
    if length is None or length <= 0:
        length = DEFAULT_SAMPLE_LENGTH
    if (start is None or start < 0
            or (total is not None and start + length > total)):
        start = 0.0
        length = (DEFAULT_SAMPLE_LENGTH if total is None
                  else min(DEFAULT_SAMPLE_LENGTH, total))
    return start, length


def player_available():
    """Whether pygame-ce is installed — without importing it.

    The shell decides from this whether to hand the page its play
    callbacks; find_spec answers without importing anything, so the
    lazy design holds. A broken install reads as no player.
    """
    try:
        return importlib.util.find_spec("pygame") is not None
    except Exception:
        return False


def _import_mixer():
    """pygame's mixer module, imported lazily on the first play."""
    import pygame
    return pygame.mixer


class SongPreviewPlayer:
    """One song preview at a time through pygame-ce's mixer.

    The mixer is imported lazily on the first play, so the module
    imports cleanly without pygame-ce installed; the shell only hands
    the page its play callbacks when player_available() is true. A
    mixer may be passed in (the tests pass a stub) — otherwise the
    real one is imported on first use. Any audio failure — no device,
    a failed init, a missing or unreadable file — reads as "could not
    start" and never raises into the page.
    """

    def __init__(self, mixer=None):
        self._mixer = mixer
        self._initialized = False

    def play(self, path, start, length, music_length):
        """Start the preview; the effective length in seconds, or None.

        The window is normalized first (see normalize_sample_window),
        then the file plays from the effective start until stop() is
        called — the mixer takes no length, so the page owns the stop
        timer and stops it after the returned length. Returns None
        when the preview could not start. A mixer that cannot set the
        position for the file's format (WAV seeking is undocumented
        in pygame-ce's mixer docs, and an out-of-range start raises)
        falls back to playing from the start for the window length,
        rather than leaving the preview silent.
        """
        eff_start, eff_length = normalize_sample_window(start, length,
                                                        music_length)
        try:
            if self._mixer is None:
                self._mixer = _import_mixer()
            if not self._initialized:
                self._mixer.init()
                self._initialized = True
            self._mixer.music.load(str(path))
            try:
                self._mixer.music.play(loops=0, start=eff_start)
            except Exception:
                if eff_start == 0.0:
                    raise
                self._mixer.music.play(loops=0, start=0.0)
        except Exception:
            return None
        return eff_length

    def stop(self):
        """Stop the preview, if one is playing; never raises."""
        if self._mixer is None or not self._initialized:
            return
        try:
            self._mixer.music.stop()
        except Exception:
            pass
