"""Window geometry and DPI.

Parsing a saved geometry string and scaling pixels for the display.
"""

from __future__ import annotations

import ctypes
import math
import re
import sys


def parse_course_geometry(value) -> tuple[int, int, int, int] | None:
    """Parse a Tk window geometry string into (width, height, x, y), or None.

    Validates the course window geometry remembered in settings (issue #25).
    Only the full form with a position is accepted. Tk writes a negative
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
    parsed = parse_course_geometry(value)
    if parsed is not None:
        width, height, x, y = parsed
        return format_geometry(
            scale_pixels(width, factor), scale_pixels(height, factor),
            scale_pixels(x, factor), scale_pixels(y, factor))
    match = re.fullmatch(r"([1-9]\d*)x([1-9]\d*)", value)
    if match is None:
        return value
    return f"{scale_pixels(int(match.group(1)), factor)}x{scale_pixels(int(match.group(2)), factor)}"


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
    "declare_dpi_awareness",
    "dpi_scale_factor",
    "format_geometry",
    "parse_course_geometry",
    "scale_geometry",
    "scale_pixels",
]
