"""The song page: one window for a song's media and charts.

Display only (Proposal 0011, stage 3): the page is given the song and its
already-resolved media and calls back for everything else. It never
resolves a path itself and never touches the filter, the loader, or the
stores. Playback (stage 4) runs through the on_play/on_stop callbacks:
the page owns the stop timer and stops the preview whenever the page
closes, shows another song, or Stop is pressed. Sizing (Proposal 0013):
the window opens at the height its song needs, capped at the screen, and
the chart list scrolls when the song has more charts than fit; a move or
resize is remembered, and any other open sizes to its song again. Memory
(Proposal 0016): a resize is remembered as a full geometry, a move alone as
a position, so the page keeps fitting each song; both persist across
sessions through the saved_geometry and report_geometry inputs.
"""

from __future__ import annotations

import math
from pathlib import Path
try:
    import tkinter as tk
    from tkinter import ttk
except ImportError:
    tk = None
    ttk = None

from itgmania_library import theme
from itgmania_library.library_format import format_duration
from itgmania_library.library_geometry import parse_window_size, scale_geometry, scale_pixels
from itgmania_library.window_placement import WindowPlacement

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
    on_play: starts the preview — on_play(path, start, length) -> float
        | None; the effective preview length in seconds, or None when
        it could not start. None when there is no player (no pygame-ce),
        which is how the page knows to disable Play. (The proposal's
        contract said bool; the page needs the effective length for its
        stop timer, so the callback returns it — None still means "could
        not start".)
    on_stop: stops the preview, None when there is no player
    on_open_folder: opens the song's folder — on_open_folder(path) -> bool;
        None where the folder cannot be opened (off Windows, where
        os.startfile does not exist)
    dpi_scale: the display scale factor
    button_factory: makes a themed button (LibraryApp._button)
    saved_geometry: the place remembered last time, in canonical 100% units:
        "WxH+X+Y" after a resize, "+X+Y" after a move alone, or None
    report_geometry: called with the canonical geometry when a new place is
        to be remembered; None keeps the memory to this session
    """

    def __init__(self, parent, on_play, on_stop, on_open_folder, dpi_scale,
                 button_factory, saved_geometry=None, report_geometry=None):
        self.parent = parent
        self.on_play = on_play
        self.on_stop = on_stop
        self.on_open_folder = on_open_folder
        self.dpi_scale = dpi_scale
        self.button_factory = button_factory
        # The window and its content while it is open.
        self.window = None
        # Where the window opens and what it remembers (Proposal 0016): the
        # placement owns the geometry saved last time and the geometry the
        # window opened with, so close() can tell a plain close from a move
        # or resize. The page sizes itself to its song, so a move alone is
        # remembered as a position only.
        self._placement = WindowPlacement(parent, dpi_scale, saved_geometry,
                                          report_geometry, content_sized=True)
        self._song = None
        self._media = None
        self._images = {}
        self._banner_label = None
        self._title_label = None
        self._artist_label = None
        self._music_label = None
        self._folder_label = None
        self._charts_frame = None
        self._charts_canvas = None
        self._charts_scrollbar = None
        self._charts_window_id = None
        self._image_labels = {}
        self._play_button = None
        self._stop_button = None
        self._folder_button = None
        # The pending stop timer's after id, or None when nothing plays:
        # the page stops the preview after the effective length, since
        # the player takes no length of its own. _playing is the
        # preview's state: the timer id alone cannot say it, because
        # after the timer fires the audio is still playing until
        # on_stop is called.
        self._stop_after_id = None
        self._playing = False

    def show(self, song, media):
        """Show the song page for one song, raising it if it is already open.

        song: the song — a dict with "title", "artist", "pack", and
            "charts" (every row sharing the song's "Course path", the
            opened chart first). media: the SongMedia record for the song.
        """
        # Showing another song ends the one playing: the preview is one
        # at a time, and a stale timer must never cut the next one short.
        self._stop_preview()
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
        # Withdrawn while it is built, so it appears once, at its final size
        # and place, instead of at the corner first and then jumping
        # (Proposal 0016). Shown again at the end of this method.
        window.withdraw()
        window.title(self._song.get("title") or "Song")
        placement = self._placement
        if placement.has_saved_size:
            window.geometry(placement.geometry_for_open(theme.SONG_PAGE_GEOMETRY))
        else:
            # The size is known only once the content is built; lay it out
            # at the default size until then.
            window.geometry(scale_geometry(theme.SONG_PAGE_GEOMETRY, self.dpi_scale))
        window.minsize(scale_pixels(theme.SONG_PAGE_MIN_SIZE[0], self.dpi_scale),
                       scale_pixels(theme.SONG_PAGE_MIN_SIZE[1], self.dpi_scale))
        window.configure(bg=theme.BG_WINDOW)
        window.transient(self.parent)

        pad = scale_pixels(_PAGE_PADX, self.dpi_scale)
        # The button row is built and packed first, at the bottom of the
        # window: pack hands out space in packing order, so a row packed
        # after the content gets nothing when the window is shorter than
        # it (issue #220 — after a manual resize to a short height the
        # buttons were cut off). First in packing order, the row keeps
        # its space and the chart list absorbs the shortfall, which is
        # what it is for. It still appears at the bottom, because of
        # side="bottom" — only the packing order, not the layout, moves.
        btn_row = tk.Frame(window, bg=theme.BG_WINDOW)
        btn_row.pack(fill="x", padx=pad, side="bottom",
                     pady=(scale_pixels(12, self.dpi_scale), pad))
        self._play_button = self.button_factory(btn_row, "Play preview", self._play)
        self._play_button.pack(side="left")
        self._stop_button = self.button_factory(btn_row, "Stop", self._stop)
        self._stop_button.pack(side="left", padx=(scale_pixels(8, self.dpi_scale), 0))
        self._folder_button = self.button_factory(btn_row, "Open song folder",
                                                  self._open_folder)
        self._folder_button.pack(side="left", padx=(scale_pixels(8, self.dpi_scale), 0))
        self.button_factory(btn_row, "Close", self.close).pack(side="right")
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
        # The chart list scrolls inside the window (Proposal 0013): the
        # labels live in a frame inside a canvas, so a song with more
        # charts than fit scrolls instead of pushing the buttons off.
        charts_outer = tk.Frame(window, bg=theme.BG_WINDOW)
        charts_outer.pack(fill="both", expand=True, padx=pad)
        charts_outer.columnconfigure(0, weight=1)
        charts_outer.rowconfigure(0, weight=1)
        self._charts_canvas = tk.Canvas(charts_outer, bg=theme.BG_WINDOW,
                                        highlightthickness=0, borderwidth=0)
        self._charts_canvas.grid(row=0, column=0, sticky="nsew")
        self._charts_scrollbar = ttk.Scrollbar(
            charts_outer, orient="vertical",
            command=self._charts_canvas.yview)
        self._charts_scrollbar.grid(row=0, column=1, sticky="ns")
        self._charts_canvas.configure(yscrollcommand=self._on_charts_scroll)
        self._charts_frame = tk.Frame(self._charts_canvas, bg=theme.BG_WINDOW)
        self._charts_window_id = self._charts_canvas.create_window(
            (0, 0), window=self._charts_frame, anchor="nw")
        self._charts_frame.bind("<Configure>",
                                self._on_charts_frame_configure)
        self._charts_canvas.bind("<Configure>",
                                 self._on_charts_canvas_configure)
        self._bind_wheel(self._charts_canvas)
        self._bind_wheel(self._charts_frame)

        window.protocol("WM_DELETE_WINDOW", self.close)
        window.bind("<Escape>", lambda _event: self.close() or "break")
        self._fill()
        # An untouched open sizes the window to the song it shows; once
        # the owner moves or resizes it, the saved geometry is used
        # instead (Proposal 0013, the refinement).
        if not placement.has_saved_size:
            self._size_to_content(placement)
        window.deiconify()
        # A new window does not always take keyboard focus (seen on
        # Windows); without it Escape would go to the main window instead
        # of closing this one. After the window is shown: the window
        # manager ignores a focus request on a withdrawn window.
        window.focus_force()
        # Note the geometry the window opened with, once the event loop has
        # placed and sized it: close() compares against it to tell a plain
        # close from a move or resize. Last, after the content sizing above:
        # its update_idletasks() would run the capture too early.
        self._placement.record_opening(window)

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
            label = tk.Label(self._charts_frame, text=self._chart_line(row),
                             bg=theme.BG_WINDOW, fg=theme.TEXT_PRIMARY,
                             font=theme.FONT_BODY, anchor="w")
            label.pack(fill="x")
            self._bind_wheel(label)
        play_state = ("normal" if self.on_play is not None
                      and media.music is not None else "disabled")
        self._play_button.configure(state=play_state)
        # Nothing is playing after a fill (show() stops any preview
        # first), so Stop stays disabled until Play starts one.
        self._stop_button.configure(state="disabled")
        folder_state = ("normal" if self.on_open_folder is not None
                        and media.folder is not None else "disabled")
        self._folder_button.configure(state=folder_state)

    def _on_charts_frame_configure(self, _event):
        """The chart labels changed size: follow them with the canvas.

        The scroll region is the labels' bounding box, so the scrollbar
        and the wheel know how far the list runs. The canvas also asks
        for the labels' height, so the window's requested height is the
        content's height — that is what _size_to_content measures. The
        guard keeps a width change from feeding back into a height
        change (the labels never wrap, so the height cannot change
        through the width).
        """
        frame_height = self._charts_frame.winfo_reqheight()
        if self._charts_canvas["height"] != frame_height:
            self._charts_canvas.configure(height=frame_height)
        self._charts_canvas.configure(
            scrollregion=self._charts_canvas.bbox("all"))

    def _on_charts_canvas_configure(self, event):
        """The canvas changed size: keep the chart labels as wide as it.

        The labels fill the inner frame, so the frame must be as wide as
        the canvas or the list would end at its widest label.
        """
        self._charts_canvas.itemconfigure(self._charts_window_id,
                                          width=event.width)

    def _on_charts_scroll(self, first, last):
        """The canvas view changed: move the scrollbar, hiding it when
        the whole list fits — a fitting list looks exactly as it did
        before the scrolling was added."""
        self._charts_scrollbar.set(first, last)
        if float(first) <= 0.0 and float(last) >= 1.0:
            self._charts_scrollbar.grid_remove()
        else:
            self._charts_scrollbar.grid()

    def _bind_wheel(self, widget):
        """Scroll the chart list from the mouse wheel over a widget.

        <MouseWheel> is the Windows and macOS event (delta is ±120 per
        notch); <Button-4>/<Button-5> are the X11 events, so the binding
        also works in the sandbox. Bound on the canvas, the inner frame,
        and each chart label, since a binding on a parent does not fire
        for events on its children.
        """
        widget.bind("<MouseWheel>", self._on_mousewheel)
        widget.bind("<Button-4>", self._on_mousewheel)
        widget.bind("<Button-5>", self._on_mousewheel)

    def _on_mousewheel(self, event):
        """Scroll the chart list one line per wheel notch."""
        if event.num == 4:
            self._charts_canvas.yview_scroll(-1, "units")
        elif event.num == 5:
            self._charts_canvas.yview_scroll(1, "units")
        else:
            self._charts_canvas.yview_scroll(int(-event.delta / 120),
                                             "units")
        return "break"

    def _size_to_content(self, placement):
        """Size and place a newly built window for the song it shows.

        The height is the window's requested height after the fill — the
        chrome plus one line per chart — never below the window's minimum
        height (a shorter request would only be clamped by the window
        manager, leaving the recorded geometry disagreeing with the
        window). The placement caps it at the monitor's work area less the
        window frame, so a song with more charts than fit opens as tall as
        the usable screen with a scrollbar instead of pushing the buttons
        off or under the taskbar, and centers the window over the main
        window (Proposal 0016). The width is the theme default's, scaled.
        """
        window = self.window
        window.update_idletasks()
        min_height = scale_pixels(theme.SONG_PAGE_MIN_SIZE[1],
                                  self.dpi_scale)
        height = max(window.winfo_reqheight(), min_height)
        width = scale_pixels(parse_window_size(theme.SONG_PAGE_GEOMETRY)[0],
                             self.dpi_scale)
        window.geometry(placement.geometry_for_content(width, height))

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
        """Start the preview from the sample window.

        The player returns the effective length — the window it is
        actually playing, after normalization — and the page stops it
        after that length, since the player takes no length of its own.
        A new Play stops the old preview first, and a preview that
        could not start (None) leaves Stop disabled with no timer.
        """
        if self.on_play is None or self._media is None or self._media.music is None:
            return
        self._stop_preview()
        length = self.on_play(self._media.music, self._media.sample_start,
                              self._media.sample_length)
        if length is None:
            return
        self._playing = True
        self._stop_button.configure(state="normal")
        try:
            self._stop_after_id = self.window.after(
                int(length * 1000), self._on_preview_finished)
        except (tk.TclError, OverflowError):
            # A garbage window the seam did not bound (a hand-edited
            # snapshot with a huge sample length and no music length)
            # cannot be scheduled; the preview still plays, and Stop
            # still stops it.
            self._stop_after_id = None

    def _on_preview_finished(self):
        """The preview's length elapsed: stop it and drop the timer."""
        self._stop_after_id = None
        self._stop_preview()

    def _stop(self):
        """Stop the preview."""
        self._stop_preview()

    def _stop_preview(self):
        """Stop any playing preview and its timer; safe when nothing plays.

        Called by show() on another song, by a new Play, by Stop, by
        the timer, and by close(), so playback never outlives the page
        or the song it is playing for. on_stop is only called when a
        preview is actually playing — the player is idempotent, but
        the page should not ask it to stop nothing.
        """
        if self._stop_after_id is not None and self.window is not None:
            if self.window.winfo_exists():
                self.window.after_cancel(self._stop_after_id)
            self._stop_after_id = None
        if self._playing:
            self._playing = False
            if self.on_stop is not None:
                self.on_stop()
        if self._stop_button is not None:
            self._stop_button.configure(state="disabled")

    def _open_folder(self):
        """Open the song's folder in the file manager."""
        if (self.on_open_folder is None or self._media is None
                or self._media.folder is None):
            return
        self.on_open_folder(self._media.folder)

    def save_window_geometry(self):
        """Remember the open window's place if it was moved or resized.

        close() calls this, and so does the app's exit path, because the
        page is otherwise torn down with the main window without close()
        running. Does nothing when no page is open.
        """
        self._placement.save(self.window)

    def close(self):
        """Close the song page. A move or resize is remembered for the
        next open (and reported, to be saved with the settings); a plain
        close records nothing, so the next open sizes to its song again."""
        self._stop_preview()
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
        self._charts_canvas = None
        self._charts_scrollbar = None
        self._charts_window_id = None
        self._image_labels = {}
        self._play_button = None
        self._stop_button = None
        self._folder_button = None
        self._stop_after_id = None
