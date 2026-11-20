"""Where a secondary window opens (Proposal 0016).

WindowPlacement holds what the five secondary windows would otherwise each
copy: reading the main window's box, the desktop and the work area, and
turning them, with the geometry saved last time, into the geometry string a
window opens with. The decision itself is the pure opening_geometry in
library_geometry; this class only gathers its inputs from the windows.

It is not a window and imports no Tkinter. It works on the objects it is
handed (the parent window, through winfo_* calls and state()), so a Tk-free
stand-in can drive it in tests, as library_filter does.
"""

from __future__ import annotations

from itgmania_library.library_geometry import (
    opening_geometry,
    parse_window_geometry,
    parse_window_size,
    scale_pixels,
    work_area_of,
)


class WindowPlacement:
    """The opening geometry for one secondary window.

    parent:         the window to center over (today always the main window)
    dpi_scale:      the display scale factor
    saved_geometry: the geometry remembered last time in canonical 100%
                    units, in either form ("WxH+X+Y" or "+X+Y"), or None
    """

    def __init__(self, parent, dpi_scale, saved_geometry=None):
        self.parent = parent
        self.dpi_scale = dpi_scale
        self._saved_geometry = saved_geometry

    @property
    def saved_geometry(self):
        return self._saved_geometry

    @property
    def has_saved_size(self):
        """True when the saved value is a full geometry, with a size."""
        return parse_window_geometry(self._saved_geometry) is not None

    def geometry_for_open(self, default_size_text):
        """The geometry for a window whose size is known up front.

        default_size_text is the canonical size from the theme ("1000x620");
        it is used when nothing usable is saved.
        """
        size = parse_window_size(default_size_text)
        if size is None:
            raise ValueError(f"not a size: {default_size_text!r}")
        return self.geometry_for_content(
            scale_pixels(size[0], self.dpi_scale),
            scale_pixels(size[1], self.dpi_scale))

    def geometry_for_content(self, width, height):
        """The geometry for a window whose size (physical pixels) is known
        only once its content is built."""
        desktop, work, anchor = self._surroundings()
        return opening_geometry(self._saved_geometry, (width, height), desktop,
                                self.dpi_scale, anchor=anchor, work=work)

    def _surroundings(self):
        """The desktop box, the work area and the anchor, read from the parent."""
        parent = self.parent
        left = parent.winfo_vrootx()
        top = parent.winfo_vrooty()
        desktop = (left, top, left + parent.winfo_vrootwidth(),
                   top + parent.winfo_vrootheight())
        # A normal or maximized parent is the anchor, read the same way for
        # both: its geometry() string goes stale when maximized, while the
        # winfo_* values stay right. A minimized or withdrawn parent has no
        # usable box (it is parked off screen), so the window is centered in
        # the primary monitor's work area instead.
        if parent.state() in ("normal", "zoomed"):
            anchor = (parent.winfo_x(), parent.winfo_y(),
                      parent.winfo_width(), parent.winfo_height())
            work = work_area_of(parent.winfo_id())
        else:
            anchor = None
            work = work_area_of(None)
        return desktop, work or desktop, anchor
