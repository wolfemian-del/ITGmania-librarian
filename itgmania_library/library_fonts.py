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
    remove.restype = ctypes.c_int
    remove(str(path), _FR_PRIVATE, None)


def load_fonts(fonts_dir=None, _register=None, _unregister=None):
    """Register the bundled fonts for this process; report what resolved.

    fonts_dir defaults to the fonts/ directory beside the package.
    _register and _unregister are test seams: _register takes a path and
    returns whether the operating system accepted it, _unregister takes
    a path to undo. When they are None, the real Windows calls are used
    on Windows and nothing is attempted elsewhere, so importing and
    calling this module off Windows is always safe. A font error never
    stops the app starting: on (AttributeError, OSError) the loader
    unregisters what this call registered and reports both families
    unloaded, so the theme keeps today's Segoe sizes.
    """
    try:
        directory = (Path(fonts_dir) if fonts_dir is not None
                     else _default_fonts_dir())
    except (AttributeError, OSError):
        return FontLoadResult(False, False, (), ())
    expected = {"barlow": [directory / name for name in _BARLOW_FILES],
                "wendy": [directory / name for name in _WENDY_FILES]}
    failed = [path for paths in expected.values() for path in paths
              if not path.is_file()]
    if sys.platform != "win32" and _register is None:
        return FontLoadResult(False, False, (), tuple(str(p) for p in failed))
    register = _register if _register is not None else _windows_register
    if _unregister is not None:
        unregister = _unregister
    elif _register is None:
        unregister = _windows_unregister
    else:
        # A fake register with no fake unregister: nothing real was
        # registered, so there is nothing to undo.
        unregister = None
    registered: list[Path] = []
    newly: list[Path] = []
    loaded: dict[str, bool] = {}
    try:
        for family, paths in expected.items():
            added: list[Path] = []
            family_newly: list[Path] = []
            for path in paths:
                if path in _REGISTERED:
                    added.append(path)
                elif path.is_file() and register(path):
                    _REGISTERED.add(path)
                    family_newly.append(path)
                    newly.append(path)
                    added.append(path)
            if len(added) == len(paths):
                loaded[family] = True
                registered.extend(added)
            else:
                loaded[family] = False
                # A half-loaded family falls back as a whole: undo the
                # files this call registered for it, so the process font
                # state matches the reported result.
                for path in family_newly:
                    _REGISTERED.discard(path)
                    newly.remove(path)
                    if unregister is not None:
                        unregister(path)
                # Missing files are already in failed from the pre-pass;
                # only present-but-rejected files join them here, so no
                # path is ever reported twice.
                failed.extend(p for p in paths
                              if p.is_file() and p not in added)
    except (AttributeError, OSError):
        for path in newly:
            _REGISTERED.discard(path)
            if unregister is not None:
                try:
                    unregister(path)
                except (AttributeError, OSError):
                    pass
        return FontLoadResult(False, False, (), tuple(str(p) for p in failed))
    return FontLoadResult(
        barlow=loaded["barlow"],
        wendy=loaded["wendy"],
        files=tuple(str(p) for p in registered),
        failed=tuple(str(p) for p in failed),
    )
