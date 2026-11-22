"""Tests for itgmania_library.library_fonts (Proposal 0017).

The Windows registration call cannot run in this sandbox, so the tests
that exercise the registration flow pass a fake _register callable. The
tests that call load_fonts() with no fake run the real platform path and
assert only what holds on every platform; the one test that depends on
the non-Windows early return is skipped on Windows.
"""
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from itgmania_library import library_fonts
from itgmania_library.library_fonts import FontLoadResult, load_fonts

BARLOW_FILES = (
    "BarlowCondensed-Light.ttf",
    "BarlowCondensed-Regular.ttf",
    "BarlowCondensed-SemiBold.ttf",
    "BarlowCondensed-Bold.ttf",
)
WENDY_FILES = ("wendy.ttf",)
ALL_FILES = BARLOW_FILES + WENDY_FILES


class LoadFontsTests(unittest.TestCase):
    def _folder_with(self, names):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        for name in names:
            (Path(folder.name) / name).write_bytes(b"not a real font")
        return folder.name

    def test_missing_folder_returns_nothing_loaded(self):
        result = load_fonts("/definitely/not/a/fonts/folder")
        self.assertEqual(result, FontLoadResult(False, False, (), tuple(
            f"/definitely/not/a/fonts/folder/{name}" for name in ALL_FILES)))

    def test_empty_folder_returns_nothing_loaded(self):
        folder = self._folder_with(())
        result = load_fonts(folder)
        self.assertFalse(result.barlow)
        self.assertFalse(result.wendy)
        self.assertEqual(result.files, ())
        self.assertEqual(
            sorted(Path(p).name for p in result.failed), sorted(ALL_FILES))

    def test_partial_folder_reports_the_missing_files(self):
        folder = self._folder_with(WENDY_FILES)
        result = load_fonts(folder)
        self.assertFalse(result.barlow)
        self.assertFalse(result.wendy)
        self.assertEqual(result.files, ())
        # The four Barlow files are missing on every platform. The
        # Wendy file is garbage bytes, so on Windows it also fails to
        # register and joins them; off Windows nothing is attempted.
        self.assertTrue(
            set(BARLOW_FILES) <= {Path(p).name for p in result.failed})

    @unittest.skipUnless(sys.platform != "win32",
                         "the real path registers fonts on Windows")
    def test_non_windows_returns_nothing_loaded_even_with_files_present(self):
        # The real path on this platform: the files are there, but no
        # registration is attempted off Windows.
        folder = self._folder_with(ALL_FILES)
        result = load_fonts(folder)
        self.assertFalse(result.barlow)
        self.assertFalse(result.wendy)
        self.assertEqual(result.files, ())
        self.assertEqual(result.failed, ())

    def test_default_dir_is_the_fonts_folder_beside_the_package(self):
        # The repo ships fonts/ beside the package with all five files,
        # so the default resolves there and nothing is missing. On
        # Windows the real files register; off Windows nothing is
        # attempted; either way nothing is reported failed.
        result = load_fonts()
        self.assertEqual(result.failed, ())

    def test_fake_register_success_loads_both_families(self):
        folder = self._folder_with(ALL_FILES)
        result = load_fonts(folder, _register=lambda path: True)
        self.assertTrue(result.barlow)
        self.assertTrue(result.wendy)
        self.assertEqual(
            sorted(Path(p).name for p in result.files), sorted(ALL_FILES))
        self.assertEqual(result.failed, ())

    def test_rejected_file_falls_back_its_whole_family(self):
        # A corrupt file the OS rejects: Barlow falls back as a whole
        # (its other three files do not stay registered), Wendy loads.
        folder = self._folder_with(ALL_FILES)
        seen = []

        def register(path):
            seen.append(path.name)
            return path.name != "BarlowCondensed-SemiBold.ttf"

        result = load_fonts(folder, _register=register)
        self.assertFalse(result.barlow)
        self.assertTrue(result.wendy)
        self.assertEqual(
            sorted(Path(p).name for p in result.files), sorted(WENDY_FILES))
        self.assertEqual(
            [Path(p).name for p in result.failed],
            ["BarlowCondensed-SemiBold.ttf"])
        self.assertEqual(sorted(seen), sorted(ALL_FILES))

    def test_double_load_is_idempotent(self):
        folder = self._folder_with(ALL_FILES)
        calls = []

        def register(path):
            calls.append(path.name)
            return True

        first = load_fonts(folder, _register=register)
        second = load_fonts(folder, _register=register)
        self.assertEqual(first, second)
        self.assertEqual(sorted(calls), sorted(ALL_FILES))


if __name__ == "__main__":
    unittest.main()
