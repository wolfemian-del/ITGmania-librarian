"""The song page: one window for a song's media and charts.

Display only (Proposal 0011, stage 3): the page is given the song and its
already-resolved media and calls back for everything else. It never
resolves a path itself and never touches the filter, the loader, or the
stores. Playback arrives in stage 4, so in this stage there is no player
and the Play and Stop buttons stay disabled.
"""

from __future__ import annotations

import math
from pathlib import Path
try:
    import tkinter as tk
except ImportError:
    tk = None

from itgmania_library import theme
from itgmania_library.library_format import format_duration
from itgmania_library.library_geometry import scale_geometry, scale_pixels

# The page's fixed content widths, in canonical 100% units: the banner
# spans the window, the three small images share a row.
_BANNER_MAX_WIDTH = 700
_SMALL_IMAGE_MAX_WIDTH = 220
_PAGE_PADX = 18

# Placeholder texts for media the page does not have.
_NO_BANNER = "No banner"
_NO_BACKGROUND = "No background"
_NO_JACKET = "No jacket"
_NO_CD_TITLE = "No CD title"
_NO_MUSIC = "No music file"
_NOT_IN_FOLDERS = "Not in the known song folders"


def _cell(value):
    """A row value the way the table shows it: floats with :g, else as text."""
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


class SongPage:
    """The song page: one window for a song's media and charts.

    parent: the root window, for the Toplevel
    on_play: starts the preview — on_play(path, start, length) -> bool;
        None when there is no player (stage 4 supplies it), which is how
        the page knows to disable Play
    on_stop: stops the preview, None when there is no player
    on_open_folder: opens the song's folder — on_open_folder(path) -> bool;
        None where the folder cannot be opened (off Windows, where
        os.startfile does not exist)
    dpi_scale: the display scale factor
    button_factory: makes a themed button (LibraryApp._button)
    """

    def __init__(self, parent, on_play, on_stop, on_open_folder, dpi_scale,
                 button_factory):
        self.parent = parent
        self.on_play = on_play
        self.on_stop = on_stop
        self.on_open_folder = on_open_folder
        self.dpi_scale = dpi_scale
        self.button_factory = button_factory
        # The window and its content while it is open; the geometry the
        # window was last closed at, in canonical units, so the next open
        # in this session puts it back where it was (not persisted — the
        # page has no settings key in v1).
        self.window = None
        self._saved_geometry = None
        self._song = None
        self._media = None
        self._images = {}
        self._banner_label = None
        self._title_label = None
        self._artist_label = None
        self._music_label = None
        self._folder_label = None
        self._charts_frame = None
        self._image_labels = {}
        self._play_button = None
        self._stop_button = None
        self._folder_button = None

    def show(self, song, media):
        """Show the song page for one song, raising it if it is already open.

        song: the song — a dict with "title", "artist", "pack", and
            "charts" (every row sharing the song's "Course path", the
            opened chart first). media: the SongMedia record for the song.
        """
        self._song = song
        self._media = media
        if self.window is not None and self.window.winfo_exists():
            self._fill()
            self.window.lift()
            self.window.focus_force()
            return
        self._build_window()

    def _build_window(self):
        window = tk.Toplevel(self.parent)
        self.window = window
        window.title(self._song.get("title") or "Song")
        window.geometry(self._geometry_for_open())
        window.minsize(scale_pixels(theme.SONG_PAGE_MIN_SIZE[0], self.dpi_scale),
                       scale_pixels(theme.SONG_PAGE_MIN_SIZE[1], self.dpi_scale))
        window.configure(bg=theme.BG_WINDOW)
        window.transient(self.parent)

        pad = scale_pixels(_PAGE_PADX, self.dpi_scale)
        self._banner_label = tk.Label(window, bg=theme.BG_WINDOW, fg=theme.TEXT_MUTED,
                                      font=theme.FONT_BODY)
        self._banner_label.pack(fill="x", padx=pad, pady=(pad, 0))
        self._title_label = tk.Label(window, bg=theme.BG_WINDOW, fg=theme.TEXT_TITLE,
                                     font=theme.FONT_DIALOG_TITLE, anchor="w")
        self._title_label.pack(fill="x", padx=pad,
                               pady=(scale_pixels(10, self.dpi_scale), 0))
        self._artist_label = tk.Label(window, bg=theme.BG_WINDOW, fg=theme.TEXT_MUTED,
                                      font=theme.FONT_BODY, anchor="w")
        self._artist_label.pack(fill="x", padx=pad)
        images_row = tk.Frame(window, bg=theme.BG_WINDOW)
        images_row.pack(fill="x", padx=pad, pady=(scale_pixels(10, self.dpi_scale), 0))
        self._image_labels = {}
        for name, caption in (("background", "Background"), ("jacket", "Jacket"),
                              ("cd_title", "CD title")):
            cell = tk.Frame(images_row, bg=theme.BG_WINDOW)
            cell.pack(side="left", padx=(0, scale_pixels(12, self.dpi_scale)))
            tk.Label(cell, text=caption, bg=theme.BG_WINDOW, fg=theme.TEXT_FIELD_LABEL,
                     font=theme.FONT_BODY).pack(anchor="w")
            label = tk.Label(cell, bg=theme.BG_PANEL, fg=theme.TEXT_MUTED,
                             font=theme.FONT_BODY)
            label.pack(anchor="w")
            self._image_labels[name] = label
        self._music_label = tk.Label(window, bg=theme.BG_WINDOW, fg=theme.TEXT_PRIMARY,
                                     font=theme.FONT_BODY, anchor="w")
        self._music_label.pack(fill="x", padx=pad,
                               pady=(scale_pixels(10, self.dpi_scale), 0))
        self._folder_label = tk.Label(window, bg=theme.BG_WINDOW, fg=theme.TEXT_MUTED,
                                      font=theme.FONT_BODY, anchor="w")
        self._folder_label.pack(fill="x", padx=pad)
        tk.Label(window, text="Charts", bg=theme.BG_WINDOW, fg=theme.TEXT_FIELD_LABEL,
                 font=theme.FONT_BODY_BOLD, anchor="w").pack(
                     fill="x", padx=pad, pady=(scale_pixels(10, self.dpi_scale), 0))
        self._charts_frame = tk.Frame(window, bg=theme.BG_WINDOW)
        self._charts_frame.pack(fill="both", expand=True, padx=pad)
        btn_row = tk.Frame(window, bg=theme.BG_WINDOW)
        btn_row.pack(fill="x", padx=pad,
                     pady=(scale_pixels(12, self.dpi_scale), pad))
        self._play_button = self.button_factory(btn_row, "Play preview", self._play)
        self._play_button.pack(side="left")
        self._stop_button = self.button_factory(btn_row, "Stop", self._stop)
        self._stop_button.pack(side="left", padx=(scale_pixels(8, self.dpi_scale), 0))
        self._folder_button = self.button_factory(btn_row, "Open song folder",
                                                  self._open_folder)
        self._folder_button.pack(side="left", padx=(scale_pixels(8, self.dpi_scale), 0))
        self.button_factory(btn_row, "Close", self.close).pack(side="right")

        window.protocol("WM_DELETE_WINDOW", self.close)
        window.bind("<Escape>", lambda _event: self.close() or "break")
        # A new window does not always take keyboard focus (seen on
        # Windows); without it Escape would go to the main window instead
        # of closing this one.
        window.focus_force()
        self._fill()

    def _fill(self):
        """Refill the open window with the current song and media."""
        song, media = self._song, self._media
        self.window.title(song.get("title") or "Song")
        self._title_label.configure(text=song.get("title") or "")
        artist = song.get("artist") or ""
        pack = song.get("pack") or ""
        self._artist_label.configure(
            text=" · ".join(part for part in (artist, pack) if part))
        self._images = {}
        banner = self._load_image(media.banner)
        if banner is not None:
            banner = self._fit_image(
                banner, scale_pixels(_BANNER_MAX_WIDTH, self.dpi_scale))
            self._images["banner"] = banner
        self._set_image(self._banner_label, banner, _NO_BANNER)
        for name, placeholder in (("background", _NO_BACKGROUND),
                                  ("jacket", _NO_JACKET),
                                  ("cd_title", _NO_CD_TITLE)):
            image = self._load_image(getattr(media, name))
            if image is not None:
                image = self._fit_image(
                    image, scale_pixels(_SMALL_IMAGE_MAX_WIDTH, self.dpi_scale))
                self._images[name] = image
            self._set_image(self._image_labels[name], image, placeholder)
        self._music_label.configure(text=self._music_text(media))
        if media.folder is None:
            self._folder_label.configure(text=_NOT_IN_FOLDERS)
        else:
            self._folder_label.configure(text=str(media.folder))
        for child in self._charts_frame.winfo_children():
            child.destroy()
        for row in song.get("charts") or []:
            tk.Label(self._charts_frame, text=self._chart_line(row),
                     bg=theme.BG_WINDOW, fg=theme.TEXT_PRIMARY,
                     font=theme.FONT_BODY, anchor="w").pack(fill="x")
        play_state = ("normal" if self.on_play is not None
                      and media.music is not None else "disabled")
        self._play_button.configure(state=play_state)
        # Nothing is playing in stage 3 (there is no player yet), so Stop
        # stays disabled; stage 4 enables it while a preview plays.
        self._stop_button.configure(state="disabled")
        folder_state = ("normal" if self.on_open_folder is not None
                        and media.folder is not None else "disabled")
        self._folder_button.configure(state=folder_state)

    @staticmethod
    def _music_text(media):
        """The music line: the file with its length and preview window, or
        just the file when the opened chart carries its own #MUSIC (the
        record then carries no length and no sample window), or a
        placeholder when there is no music file at all."""
        if media.music is None:
            return _NO_MUSIC
        name = media.music.name
        if (media.music_length is None or media.sample_start is None
                or media.sample_length is None):
            return f"Music: {name}"
        start = format_duration(media.sample_start)
        end = format_duration(media.sample_start + media.sample_length)
        return (f"Music: {name} · {format_duration(media.music_length)} · "
                f"preview {start}–{end}")

    @staticmethod
    def _chart_line(row):
        """One chart's line: game type, difficulty, meter, BPM, and score —
        the same values the table shows for the row. A missing game type is
        simply omitted, the way a missing meter is."""
        parts = [str(row.get("Type") or ""), str(row.get("Difficulty") or "")]
        meter = row.get("Meter")
        if meter not in (None, ""):
            parts.append(f"Meter {_cell(meter)}")
        bpm = row.get("BPM")
        if bpm not in (None, ""):
            parts.append(str(bpm))
        score = row.get("Score")
        if score not in (None, ""):
            parts.append(f"Score {_cell(score)}")
        else:
            parts.append("No score")
        return " · ".join(part for part in parts if part)

    @staticmethod
    def _load_image(path):
        """A PhotoImage for a PNG file, or None where there is nothing to show.

        Anything that is not a PNG — a JPEG background, a missing file —
        takes the placeholder path without trying to load it, and a corrupt
        PNG takes the placeholder path through the TclError.
        """
        if path is None:
            return None
        if Path(path).suffix.casefold() != ".png":
            return None
        try:
            return tk.PhotoImage(file=str(path))
        except tk.TclError:
            return None

    @staticmethod
    def _fit_image(image, max_width):
        """The image subsampled by an integer factor so it fits max_width.

        PhotoImage subsample takes integer factors only, so a wide banner
        lands at or under the width rather than exactly on it.
        """
        width = image.width()
        if width <= max_width:
            return image
        return image.subsample(math.ceil(width / max_width))

    @staticmethod
    def _set_image(label, image, placeholder):
        """Show the image on the label, or the placeholder text where there is none."""
        if image is None:
            label.configure(image="", text=placeholder)
        else:
            label.configure(image=image, text="")

    def _play(self):
        """Start the preview from the sample window (stage 4 supplies the player)."""
        if self.on_play is None or self._media is None or self._media.music is None:
            return
        self.on_play(self._media.music, self._media.sample_start,
                     self._media.sample_length)

    def _stop(self):
        """Stop the preview."""
        if self.on_stop is not None:
            self.on_stop()

    def _open_folder(self):
        """Open the song's folder in the file manager."""
        if (self.on_open_folder is None or self._media is None
                or self._media.folder is None):
            return
        self.on_open_folder(self._media.folder)

    def close(self):
        """Close the song page, remembering its geometry for the next open
        in this session (not persisted — the page has no settings key)."""
        self.save_window_geometry()
        if self.window is not None:
            self.window.destroy()
        self.window = None
        self._song = None
        self._media = None
        self._images = {}
        self._banner_label = None
        self._title_label = None
        self._artist_label = None
        self._music_label = None
        self._folder_label = None
        self._charts_frame = None
        self._image_labels = {}
        self._play_button = None
        self._stop_button = None
        self._folder_button = None

    def save_window_geometry(self):
        """Remember the window's geometry in canonical units, or nothing.

        Called when the page closes and when the app exits with the page
        open. Does nothing when the page is closed, and nothing while the
        window is minimized or maximized: those states report a parked or
        full-screen geometry the user did not choose as the window's place.
        """
        if self.window is None or not self.window.winfo_exists():
            return
        if self.window.state() != "normal":
            return
        # The window reports physical pixels; store canonical 100% units.
        self._saved_geometry = scale_geometry(self.window.geometry(),
                                              1.0 / self.dpi_scale)

    def _geometry_for_open(self):
        return scale_geometry(self._saved_geometry or theme.SONG_PAGE_GEOMETRY,
                              self.dpi_scale)
