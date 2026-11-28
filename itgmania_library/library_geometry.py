"""Window geometry and DPI.

Parsing a saved geometry string and scaling pixels for the display.
"""

from __future__ import annotations

import ctypes
import math
import re
import sys


def parse_window_geometry(value) -> tuple[int, int, int, int] | None:
    """Parse a Tk window geometry string into (width, height, x, y), or None.

    Validates a window geometry remembered in settings (issues #25, #98, and
    Proposal 0016). Only the full form with a position is accepted. Tk writes a negative
    offset two ways — "-8" and, after the leading sign, "+-8" — and both are
    understood, so a value the app itself saved always parses.
    """
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"([1-9]\d*)x([1-9]\d*)([+-]-?\d+)([+-]-?\d+)", value)
    if match is None:
        return None
    try:
        width, height = int(match.group(1)), int(match.group(2))
        # "+-8" is the negative-offset spelling; int() alone rejects it.
        x = int(match.group(3).replace("+-", "-"))
        y = int(match.group(4).replace("+-", "-"))
    except ValueError:
        # A component with thousands of digits trips Python's int-conversion
        # limit; that is a corrupt value, not a reason to fail.
        return None
    return width, height, x, y


def dpi_scale_factor(fpixels: float) -> float:
    """The display scale factor from Tk's pixels-per-inch probe (issue #51).

    `winfo_fpixels("1i")` is 96.0 at 100% scaling, 120.0 at 125%, 144.0 at
    150%; dividing by 96.0 gives the factor to multiply canonical (100%)
    pixel values by. A non-positive or non-finite reading cannot happen on
    a real display; treat it as 1.0 rather than scaling by nonsense.
    """
    try:
        factor = float(fpixels) / 96.0
    except (TypeError, ValueError):
        return 1.0
    if not math.isfinite(factor) or factor <= 0:
        return 1.0
    return factor


def parse_window_size(value) -> tuple[int, int] | None:
    """Parse a size-only geometry string such as "1000x620" into (width, height), or None.

    The theme's default window geometries are in this form, which
    parse_window_geometry rejects because it has no position.
    """
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"([1-9]\d*)x([1-9]\d*)", value)
    if match is None:
        return None
    try:
        return int(match.group(1)), int(match.group(2))
    except ValueError:
        # A component with thousands of digits trips Python's int-conversion
        # limit; that is a corrupt value, not a reason to fail.
        return None


def scale_pixels(value: int, factor: float) -> int:
    """A pixel count in canonical 100% units, scaled to this display (issue #51).

    At factor 1.0 the value is unchanged. Rounds to the nearest whole
    pixel (Python's round, so a .5 goes to the even neighbour); zero stays
    zero, so a padding of 0 does not become 1.
    """
    return round(value * factor)


def format_geometry(width: int, height: int, x: int, y: int) -> str:
    """A Tk window geometry string from its four numbers.

    The offsets carry their own sign after the leading "+": a negative
    x renders as "+-8", which is the spelling Tk itself writes.
    """
    return f"{width}x{height}+{x}+{y}"


def scale_geometry(value: str, factor: float) -> str:
    """A geometry string in canonical 100% units, scaled to this display (issue #51).

    Handles both the size-only form ("1500x850") and the full form with a
    position ("1000x620+10+10", negative offsets as "+-8"). A value that
    parses as neither is returned unchanged — the caller validates stored
    strings separately, and a default that cannot be scaled is better
    applied as-is than dropped.
    """
    parsed = parse_window_geometry(value)
    if parsed is not None:
        width, height, x, y = parsed
        return format_geometry(
            scale_pixels(width, factor), scale_pixels(height, factor),
            scale_pixels(x, factor), scale_pixels(y, factor))
    match = re.fullmatch(r"([1-9]\d*)x([1-9]\d*)", value)
    if match is None:
        return value
    return (
        f"{scale_pixels(int(match.group(1)), factor)}"
        f"x{scale_pixels(int(match.group(2)), factor)}"
    )


# The window frame's extra width and height in canonical 100% units: Tk
# geometry() sizes are client sizes, while positions are the outer frame's
# top-left, so a window's outer box is this much larger than its size.
# Measured on Windows 11 at 100% (8 px each side, 31 px title bar; Proposal 0016).
WINDOW_FRAME = (16, 39)


def parse_window_position(value) -> tuple[int, int] | None:
    """Parse a position-only geometry string such as "+100+50" into (x, y), or None.

    Both negative-offset spellings parse ("-8" and "+-8"), as in
    parse_window_geometry. A string with a size is not a position: it
    belongs to parse_window_geometry or parse_window_size.
    """
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"([+-]-?\d+)([+-]-?\d+)", value)
    if match is None:
        return None
    try:
        # "+-8" is the negative-offset spelling; int() alone rejects it.
        return (int(match.group(1).replace("+-", "-")),
                int(match.group(2).replace("+-", "-")))
    except ValueError:
        return None


def _visible_enough(desktop, x, y, width, height, scale) -> bool:
    """Whether a window box shows enough of itself on the virtual desktop.

    At least a grabbable strip of it (100 by 32 pixels at 100%), so a window
    left hanging a little off an edge comes back as it was, while one left
    on a since-unplugged monitor, or pushed almost entirely off an edge,
    does not open lost. The top edge has its own rule on top of that: a
    window can show plenty of its body while its title bar sits above every
    monitor (a stacked monitor unplugged since, say), leaving nothing to
    grab, so the top edge must sit within 16 pixels of the desktop's top.
    """
    left, top, right, bottom = desktop
    visible_width = min(x + width, right) - max(x, left)
    visible_height = min(y + height, bottom) - max(y, top)
    return (visible_width >= scale_pixels(100, scale)
            and visible_height >= scale_pixels(32, scale)
            and y >= top - scale_pixels(16, scale))


def _enforced_size(width, height, work, frame, min_size, scale):
    """The size a window actually opens with: capped to the work area
    less the frame, and never below its minimum (issue #244).

    When the work area is smaller than the minimum plus the frame, the
    minimum wins and the window hangs off the work area; the clamp in
    opening_geometry then keeps its left and top edges on screen.
    """
    frame_width = scale_pixels(frame[0], scale)
    frame_height = scale_pixels(frame[1], scale)
    min_width = scale_pixels(min_size[0], scale)
    min_height = scale_pixels(min_size[1], scale)
    work_left, work_top, work_right, work_bottom = work
    max_width = max(1, (work_right - work_left) - frame_width)
    max_height = max(1, (work_bottom - work_top) - frame_height)
    return (max(min_width, min(width, max_width)),
            max(min_height, min(height, max_height)))


def _visible_saved_box(saved, desktop, scale, work, frame, min_size):
    """The capped (width, height, x, y) of a saved full-form geometry
    that is visible enough on the desktop, or None.

    The shared parse, scale, cap and visibility step behind
    opening_geometry's rule 2 and saved_geometry_visible (Proposal
    0023): both call this one function, so a saved place cannot be
    visible to one and invisible to the other. A missing, position-only
    or unparsable value is not a full geometry, so it is not visible.
    """
    work = work or desktop
    full = parse_window_geometry(saved)
    if full is None:
        return None
    width, height, x, y = (scale_pixels(value, scale) for value in full)
    width, height = _enforced_size(width, height, work, frame, min_size, scale)
    if _visible_enough(desktop, x, y, width, height, scale):
        return (width, height, x, y)
    return None


def opening_geometry(saved, size, desktop, scale, *, anchor=None, work=None,
                     frame=WINDOW_FRAME, min_size=(1, 1)) -> str:
    """The geometry string a window opens with (issues #25, #98, #103; Proposal 0016).

    saved:   the geometry remembered last time, in canonical 100% units: a
             full "WxH+X+Y", a position-only "+X+Y", or None.
    size:    the (width, height) the window opens with when nothing usable is
             remembered, in physical pixels. For a position-only value it is
             the size the window needs for its content.
    desktop: (left, top, right, bottom) of the virtual desktop, which spans
             every monitor, in physical pixels.
    scale:   the display scale factor.
    anchor:  (x, y, width, height) of the window to center over, or None.
    work:    (left, top, right, bottom) of the work area, the part of the
             monitor Windows leaves free of the taskbar; default: desktop.
    frame:   the window frame's extra (width, height) in canonical units.
    min_size: the window's minimum size in canonical units; the size never
             goes below it, so the position is clamped for the size the
             window will actually have (issue #244).

    Four rules, in this order. Integer division here is Python's floor
    division, which rounds negative values toward negative infinity.

    1. The size is capped to the work area less the frame, and floored at
       the minimum size. With the default minimum of 1x1 this is never
       below 1.
    2. A full saved geometry whose capped box is visible enough (see
       _visible_enough) is returned as it is: a place the owner dragged to
       is not second-guessed, so it is never clamped. Rule 2 shares
       _visible_saved_box with saved_geometry_visible (Proposal 0023).
    3. A position-only saved geometry whose capped box, at the saved
       position, is visible enough is kept, shifted if need be so the whole
       outer box (size plus frame) lies inside the work area.
    4. Otherwise the window is centered over the anchor, or in the work
       area without one, and clamped so its outer box lies inside the work
       area. A full saved geometry that is no longer visible keeps its
       (capped) size and loses only its position.
    """
    work = work or desktop
    frame_width = scale_pixels(frame[0], scale)
    frame_height = scale_pixels(frame[1], scale)
    work_left, work_top, work_right, work_bottom = work

    def clamped(x, y, width, height):
        return (max(work_left, min(x, work_right - (width + frame_width))),
                max(work_top, min(y, work_bottom - (height + frame_height))))

    visible = _visible_saved_box(saved, desktop, scale, work, frame, min_size)
    if visible is not None:
        return format_geometry(*visible)
    full = parse_window_geometry(saved)
    if full is not None:
        # Rule 4: a full saved geometry that is no longer visible keeps
        # its (capped) size and loses only its position.
        width, height = _enforced_size(
            scale_pixels(full[0], scale), scale_pixels(full[1], scale),
            work, frame, min_size, scale)
    else:
        width, height = _enforced_size(size[0], size[1], work, frame, min_size, scale)
        position = parse_window_position(saved)
        if position is not None:
            x, y = (scale_pixels(value, scale) for value in position)
            if _visible_enough(desktop, x, y, width, height, scale):
                return format_geometry(width, height, *clamped(x, y, width, height))
    if anchor is not None:
        anchor_x, anchor_y, anchor_width, anchor_height = anchor
        x = anchor_x + (anchor_width - width) // 2
        y = anchor_y + (anchor_height - height) // 2
    else:
        x = work_left + ((work_right - work_left) - (width + frame_width)) // 2
        y = work_top + ((work_bottom - work_top) - (height + frame_height)) // 2
    return format_geometry(width, height, *clamped(x, y, width, height))


def canonical_geometry(geometry, scale):
    """A geometry string in canonical 100% units (Proposal 0023).

    The window reports physical pixels; this is the inverse of
    scale_geometry — the same conversion WindowPlacement._canonical
    does for a window, as a public Tk-free function so the shell can
    canonicalize the main window's geometry without a helper. A scale
    that is not a positive finite number leaves the string unchanged
    rather than scaling by nonsense.
    """
    try:
        factor = 1.0 / float(scale)
    except (TypeError, ValueError, ZeroDivisionError):
        return geometry
    if not math.isfinite(factor) or factor <= 0:
        return geometry
    return scale_geometry(geometry, factor)


def saved_geometry_visible(saved, desktop, scale, work, min_size=(1, 1)):
    """Whether a saved full-form geometry is visible enough to restore (Proposal 0023).

    The visibility half of opening_geometry's rule 2, as a Tk-free
    helper the shell calls before choosing the work area: a saved place
    on a second monitor selects that monitor's work area, and one that
    is no longer visible selects the primary's. It shares
    _visible_saved_box with opening_geometry, so the two cannot
    disagree; min_size is the same minimum the opening call uses, so
    the cap matches too. A missing, position-only or unparsable value
    is not visible. The work area is the one to cap against; None falls
    back to the desktop, as opening_geometry does.
    """
    return _visible_saved_box(saved, desktop, scale, work, WINDOW_FRAME, min_size) is not None


def decide_main_window_save(last_geometry, opening_baseline, last_maximized, saved_maximized):
    """The settings keys a closing main window writes, or None (Proposal 0023).

    A Tk-free pure function: the shell compares what the window was
    last doing against what it opened with and what the file holds.
    The geometry is written exactly when the last normal geometry
    differs from the opening baseline, and the flag exactly when the
    last shown maximized state differs from the saved flag:

    - both unchanged: nothing;
    - geometry changed, flag unchanged: the geometry only;
    - geometry unchanged, flag changed: the flag only;
    - both changed: the geometry and the flag.

    A last geometry of None (the window was never placed) writes no
    geometry, and a baseline of None cannot be compared, so it writes
    no geometry either. Minimizing alone changes neither input, so a
    minimized window writes nothing on its own.
    """
    keys = {}
    if (last_geometry is not None and opening_baseline is not None
            and last_geometry != opening_baseline):
        keys["main_window_geometry"] = last_geometry
    if bool(last_maximized) != bool(saved_maximized):
        keys["main_window_maximized"] = bool(last_maximized)
    return keys or None


def work_area_of(hwnd=None, point=None):
    """The work area of a monitor as (left, top, right, bottom), or None.

    The work area is the part of a monitor Windows leaves free of reserved
    areas such as the taskbar. With a window handle it is the work area of
    the monitor holding that window (the nearest monitor, should the window
    be off every one); with a point, in physical pixels, it is the work
    area of the monitor nearest that point (Proposal 0023); without either,
    the primary monitor's. Returns None off Windows and when any call
    fails, and the caller falls back to the virtual desktop. Windows only;
    not testable in the sandbox beyond that fallback (Proposal 0016 D6).
    """
    if sys.platform != "win32":
        return None
    try:
        from ctypes import wintypes

        class MonitorInfo(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                        ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

        # A private DLL handle, so setting argument types here cannot change
        # how any other code calls the same functions.
        user32 = ctypes.WinDLL("user32")
        user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MonitorInfo)]
        if point is not None:
            # MonitorFromPoint takes a POINT by value (Proposal 0023).
            user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
            user32.MonitorFromPoint.restype = wintypes.HANDLE
            monitor = user32.MonitorFromPoint(
                wintypes.POINT(point[0], point[1]), 2)  # MONITOR_DEFAULTTONEAREST
        elif hwnd:
            user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
            user32.MonitorFromWindow.restype = wintypes.HANDLE
            monitor = user32.MonitorFromWindow(hwnd, 2)  # MONITOR_DEFAULTTONEAREST
        else:
            rect = wintypes.RECT()
            # SPI_GETWORKAREA: the primary monitor's work area.
            if not user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):
                return None
            return (rect.left, rect.top, rect.right, rect.bottom)
        info = MonitorInfo()
        info.cbSize = ctypes.sizeof(MonitorInfo)
        if not monitor or not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            return None
        rect = info.rcWork
        return (rect.left, rect.top, rect.right, rect.bottom)
    except (AttributeError, IndexError, OSError, ValueError, TypeError, ctypes.ArgumentError):
        return None


def declare_dpi_awareness() -> None:
    """Declare system DPI awareness on Windows, before any window exists (issue #51).

    A process that declares nothing is bitmap-stretched by Windows at
    125%/150% (blurry text, wrong sizes). SetProcessDpiAwareness(1)
    (system awareness) stops the stretching; Tk then reads the real DPI
    and sizes point-fonts for it. Falls back to SetProcessDPIAware on
    older Windows; does nothing anywhere else. Must run before tk.Tk().
    """
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


__all__ = [
    "WINDOW_FRAME",
    "canonical_geometry",
    "decide_main_window_save",
    "declare_dpi_awareness",
    "dpi_scale_factor",
    "format_geometry",
    "opening_geometry",
    "parse_window_geometry",
    "parse_window_position",
    "parse_window_size",
    "saved_geometry_visible",
    "scale_geometry",
    "scale_pixels",
    "work_area_of",
]
