"""Per-process loading of the bundled Barlow Condensed and Wendy fonts.

The font files live in fonts/ beside the package. On Windows they are
registered with AddFontResourceEx and FR_PRIVATE, so they exist only in
this process: nothing is installed, no admin rights are needed, and they
vanish with the process. Anywhere else, or when a file is missing or
unusable, the loader reports that family as not loaded and the theme
keeps today's Segoe sizes; the app never fails to start over a font.

The loader depends on nothing in the package except the standard library.
"""

import ctypes
import sys
from dataclasses import dataclass
from pathlib import Path

# Register the font for this process only (AddFontResourceEx flag).
_FR_PRIVATE = 0x10

_BARLOW_FILES = (
    "BarlowCondensed-Light.ttf",
    "BarlowCondensed-Regular.ttf",
    "BarlowCondensed-SemiBold.ttf",
    "BarlowCondensed-Bold.ttf",
)
_WENDY_FILES = ("wendy.ttf",)

# Paths already registered in this process, so a second load does not
# register them twice. Tests use a fresh temporary folder per call, so
# they never share an entry here.
_REGISTERED: set[Path] = set()


@dataclass(frozen=True)
class FontLoadResult:
    """Which bundled font families resolved for this process.

    files lists the files registered with the operating system; failed
    lists the expected files that could not be registered (absent, or
    rejected by the OS). A family is usable only when every one of its
    files registered, so a half-loaded family falls back as a whole.
    """

    barlow: bool
    wendy: bool
    files: tuple[str, ...] = ()
    failed: tuple[str, ...] = ()


def _default_fonts_dir() -> Path:
    """The fonts/ directory beside the package, never the working directory."""
    return Path(__file__).resolve().parent.parent / "fonts"


def _windows_register(path: Path) -> bool:
    """Register one file with Windows for this process only."""
    add = ctypes.windll.gdi32.AddFontResourceExW
    add.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_void_p]
    add.restype = ctypes.c_int
    return add(str(path), _FR_PRIVATE, None) > 0


def _windows_unregister(path: Path) -> None:
    """Undo a registration made by _windows_register."""
    remove = ctypes.windll.gdi32.RemoveFontResourceExW
    remove.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_void_p]
    remove.restype = ctypes.c_bool
    remove(str(path), _FR_PRIVATE, None)


def load_fonts(fonts_dir=None, _register=None):
    """Register the bundled fonts for this process; report what resolved.

    fonts_dir defaults to the fonts/ directory beside the package.
    _register is a test seam: a callable taking a path and returning
    whether the operating system accepted it. When it is None, the real
    Windows call is used on Windows and nothing is attempted elsewhere,
    so importing and calling this module off Windows is always safe.
    """
    directory = Path(fonts_dir) if fonts_dir is not None else _default_fonts_dir()
    expected = {"barlow": [directory / name for name in _BARLOW_FILES],
                "wendy": [directory / name for name in _WENDY_FILES]}
    failed = [path for paths in expected.values() for path in paths
              if not path.is_file()]
    if sys.platform != "win32" and _register is None:
        return FontLoadResult(False, False, (), tuple(str(p) for p in failed))
    register = _register if _register is not None else _windows_register
    registered: list[Path] = []
    for paths in expected.values():
        added: list[Path] = []
        newly: list[Path] = []
        for path in paths:
            if path in _REGISTERED:
                added.append(path)
            elif path.is_file() and register(path):
                _REGISTERED.add(path)
                newly.append(path)
                added.append(path)
        if len(added) == len(paths):
            registered.extend(added)
        else:
            # A half-loaded family falls back as a whole: undo the files
            # this call registered for it, so the process font state
            # matches the reported result.
            for path in newly:
                _REGISTERED.discard(path)
                if _register is None:
                    _windows_unregister(path)
            failed.extend(p for p in paths if p not in added)
    return FontLoadResult(
        barlow=len([p for p in registered if p.name.startswith("Barlow")]) == 4,
        wendy=len([p for p in registered if p.name == "wendy.ttf"]) == 1,
        files=tuple(str(p) for p in registered),
        failed=tuple(str(p) for p in failed),
    )
