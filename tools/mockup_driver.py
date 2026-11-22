"""Mockup driver: open the real app on the fixture library, in a given font,
open the song page over the main window, and screenshot the screen.

Adapted from tests/test_library_librarian.py::_layout_and_app (same temp
library, same snapshot writer, same song page path). Run under xvfb-run.

Two modes: --family/--body sets every title and body constant to one
family (the mode the blind-comparison mockups used), and --real applies
the bundled configuration instead, through theme.apply_fonts(), so the
screenshot shows exactly what the app will look like once Proposal 0017
lands. In --real mode the bundled fonts must be visible to fontconfig
first (copy fonts/*.ttf into ~/.local/share/fonts and run fc-cache);
the probe below reports the family Tk actually resolved for both the
body and the title, so a silent fallback is visible.
"""
import argparse
import contextlib
import json
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import tkinter as tk  # noqa: E402

from itgmania_library import library_librarian as app  # noqa: E402
from itgmania_library import theme  # noqa: E402

FIXTURES = REPO / "tests" / "fixtures"


def rows():
    out = []
    for title, difficulty, meter, bpm, time_value, course_path, banner in (
            ("One", "Hard", 10.0, "150", 93.987999, "P/One", "banner.png"),
            ("One", "Challenge", 13.0, "150-180", 93.987999, "P/One", "banner.png"),
            ("Two", "Medium", 8.0, "120", 80.0, "P/Two", "banner.jpg"),
            ("Three", "Easy", 5.0, "100", 60.0, "P/Three", "banner.png"),
            ("Four", "Beginner", 2.0, "90", 45.0, "Q/Four", "banner.png")):
        row = {header: "" for header in app.HEADERS}
        row.update({"Title": title, "Artist": f"Artist {title}",
                    "Pack": course_path.split("/")[0],
                    "Type": "dance-single", "Difficulty": difficulty, "Meter": meter,
                    "BPM": bpm, "Time": time_value,
                    "Score": 985000.0 if title == "One" and difficulty == "Hard" else "",
                    "Course path": course_path, "Music": "song.ogg",
                    "SongMusic": "song.ogg",
                    "Banner": banner, "Background": "", "Jacket": "", "CDTitle": "",
                    "SampleStart": 64.58 if title == "One" else 10.0,
                    "SampleLength": 15.0 if title == "One" else 12.0})
        out.append(row)
    return out


def pump_until(root, condition, timeout=10):
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        root.update()
        time.sleep(0.02)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--family")
    parser.add_argument("--body", type=int, default=11)
    parser.add_argument("--real", action="store_true",
                        help="apply the bundled Barlow/Wendy configuration")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    if args.real:
        # The real configuration, through the same setter main() calls.
        theme.apply_fonts(barlow=True, wendy=True)
        family, body = "Barlow Condensed", 11
    else:
        if not args.family:
            parser.error("--family is required unless --real is given")
        family, body = args.family, args.body
        # Equalizing sizes from the measurement report (Miso 9pt -> 11-12pt).
        theme.FONT_BODY = (family, body)
        theme.FONT_BODY_BOLD = (family, body, "bold")
        theme.FONT_SMALL = (family, max(body - 1, 8))
        theme.FONT_ENTRY_LARGE = (family, body + 1)
        theme.FONT_PANEL_TITLE = (family, body + 3, "bold")
        theme.FONT_DIALOG_TITLE = (family, body + 8, "bold")
        theme.FONT_COURSE_TITLE = (family, body + 10, "bold")
        theme.FONT_APP_TITLE = (family, body + 13, "bold")

    tmp = tempfile.TemporaryDirectory()
    base = Path(tmp.name)
    cache_dir = base / "Cache" / "Songs"
    cache_dir.mkdir(parents=True)
    songs_dir = base / "Songs"
    for song in ("One", "Two", "Three"):
        (songs_dir / "P" / song).mkdir(parents=True)
    (songs_dir / "P" / "One" / "banner.png").write_bytes(
        (FIXTURES / "song_banner.png").read_bytes())
    (songs_dir / "P" / "One" / "song.ogg").write_bytes(b"fake ogg")
    (songs_dir / "P" / "Two" / "banner.jpg").write_bytes(
        (FIXTURES / "song_banner.jpg").read_bytes())
    (songs_dir / "P" / "Three" / "banner.png").write_bytes(
        (FIXTURES / "song_banner_corrupt.png").read_bytes())
    (base / "Save").mkdir()
    (base / "Save" / "Preferences.ini").write_text(
        f"AdditionalSongFoldersWritable={songs_dir}\n", encoding="utf-8")
    stats_file = base / "Stats.xml"
    stats_file.write_text("<Stats/>")
    settings_path = base / "settings.json"
    settings_path.write_text(json.dumps(
        {"cache_dir": str(cache_dir), "stats_file": str(stats_file)}))
    all_rows = rows()

    writer_root = tk.Tk()
    with patch.object(app.LibraryApp, "_settings_file_path",
                      staticmethod(lambda: settings_path)):
        writer = app.LibraryApp(writer_root)
        writer._snapshot_store.write(cache_dir, stats_file, all_rows,
                                     len(all_rows), 0, 0, False)
    writer_root.destroy()

    root = tk.Tk()
    with patch.object(app.LibraryApp, "_settings_file_path",
                      staticmethod(lambda: settings_path)):
        application = app.LibraryApp(root)
    pump_until(root, lambda: len(application._table.tree.get_children()) == len(all_rows))
    for _ in range(5):
        root.update()

    # Sanity: the font actually resolved (Tk falls back silently otherwise).
    import tkinter.font as tkfont
    probe = tkfont.Font(family=family, size=body)
    print(f"family={family} actual={probe.actual('family')} "
          f"rows={len(application._table.tree.get_children())}")
    if args.real:
        title_probe = tkfont.Font(family=theme.FONT_APP_TITLE[0],
                                  size=theme.FONT_APP_TITLE[1])
        print(f"title family={theme.FONT_APP_TITLE[0]} "
              f"actual={title_probe.actual('family')}")

    # The row must be the app's own dict object: _open_song_page prepends
    # the opened chart and drops it from the rest by identity, so passing
    # our own dict would show the opened chart twice.
    library_rows = application._filter.library_rows()
    opened = next(r for r in library_rows
                  if r.get("Title") == "One" and r.get("Difficulty") == "Hard")
    application._open_song_page(opened)
    pump_until(root, lambda: application.song_page.window is not None)
    page = application.song_page.window
    for _ in range(8):
        root.update()
        time.sleep(0.05)
    page.focus_force()
    page.lift()
    root.lift()
    page.lift()
    for _ in range(5):
        root.update()
        time.sleep(0.05)
    print(f"song page title={application.song_page._title_label['text']} "
          f"banner_image_set={application.song_page._banner_label['image'] != ''}")

    from PIL import ImageGrab
    ImageGrab.grab().save(args.out)
    print(f"saved {args.out}")
    root.destroy()


if __name__ == "__main__":
    main()
