"""Tests for itgmania_library.library_fonts (Proposal 0017).

The Windows registration call cannot run in this sandbox, so the tests
that exercise the registration flow pass a fake _register callable. The
tests that call load_fonts() with no fake run the real platform path and
assert only what holds on every platform; the one test that depends on
the non-Windows early return is skipped on Windows. A test that means
to reach the real Windows font API uses a real bundled font file, never
garbage bytes.
"""
import shutil
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
REPO_FONTS = Path(__file__).resolve().parent.parent / "fonts"


class LoadFontsTests(unittest.TestCase):
    def setUp(self):
        super().setUp()
        # _REGISTERED is module-level and ignores which registrar made
        # an entry, so clear it between tests: a test that reuses a
        # folder would otherwise see a stale answer. This mirrors the
        # reset the theme tests already do for the font names.
        self.addCleanup(library_fonts._REGISTERED.clear)

    def _folder_with(self, names):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        for name in names:
            (Path(folder.name) / name).write_bytes(b"not a real font")
        return folder.name

    def test_missing_folder_returns_nothing_loaded(self):
        # The expectation is built with Path, not a hard-coded string:
        # on Windows the loader's paths carry backslashes.
        folder = Path("/definitely/not/a/fonts/folder")
        result = load_fonts(folder)
        self.assertEqual(result, FontLoadResult(
            False, False, (),
            tuple(str(folder / name) for name in ALL_FILES)))

    def test_empty_folder_returns_nothing_loaded(self):
        folder = self._folder_with(())
        result = load_fonts(folder)
        self.assertFalse(result.barlow)
        self.assertFalse(result.wendy)
        self.assertEqual(result.files, ())
        self.assertEqual(
            sorted(Path(p).name for p in result.failed), sorted(ALL_FILES))

    def test_partial_folder_reports_the_missing_files(self):
        # The one present file is the real bundled wendy.ttf, so on
        # Windows the real font API is fed a valid font, not garbage.
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        shutil.copy(REPO_FONTS / "wendy.ttf", folder.name)
        if sys.platform == "win32":
            # A font added with AddFontResourceEx stays loaded for the
            # process, and Windows will not delete a file that is in
            # use: unregister it before the folder cleanup runs, or
            # the teardown raises PermissionError. These cleanups are
            # registered after the folder cleanup, so they run first.
            wendy_path = Path(folder.name) / "wendy.ttf"
            self.addCleanup(library_fonts._REGISTERED.discard, wendy_path)
            self.addCleanup(library_fonts._windows_unregister, wendy_path)
        result = load_fonts(folder.name)
        self.assertFalse(result.barlow)
        self.assertEqual(
            sorted(Path(p).name for p in result.failed), sorted(BARLOW_FILES))
        if sys.platform == "win32":
            self.assertTrue(result.wendy)
            self.assertEqual(
                [Path(p).name for p in result.files], ["wendy.ttf"])
        else:
            self.assertFalse(result.wendy)
            self.assertEqual(result.files, ())

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
        # attempted.
        result = load_fonts()
        self.assertEqual(result.failed, ())
        if sys.platform == "win32":
            self.assertTrue(result.barlow)
            self.assertTrue(result.wendy)
            self.assertEqual(len(result.files), 5)
        else:
            self.assertFalse(result.barlow)
            self.assertFalse(result.wendy)
            self.assertEqual(result.files, ())

    def test_fake_register_success_loads_both_families(self):
        folder = self._folder_with(ALL_FILES)
        result = load_fonts(folder, _register=lambda path: True)
        self.assertTrue(result.barlow)
        self.assertTrue(result.wendy)
        self.assertEqual(
            sorted(Path(p).name for p in result.files), sorted(ALL_FILES))
        self.assertEqual(result.failed, ())

    def test_empty_folder_reports_five_failures_with_no_duplicates(self):
        # The duplicate-failed guard (Revision 1): with a fake register
        # the loop runs on every platform, so this pins the guard where
        # the missing-folder tests cannot (they return early off Windows).
        folder = self._folder_with(())
        result = load_fonts(folder, _register=lambda path: True)
        self.assertEqual(len(result.failed), 5)
        self.assertEqual(len(set(result.failed)), 5)

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
        # The rollback also discards the three files from _REGISTERED:
        # a later call with a register that accepts everything must
        # register them again, not skip them as already loaded. If the
        # discard were deleted, only SemiBold would be called here.
        calls = []
        again = load_fonts(folder, _register=lambda p: calls.append(p.name) or True)
        self.assertTrue(again.barlow)
        self.assertEqual(sorted(calls), sorted(BARLOW_FILES))

    def test_unregister_called_for_the_files_a_failed_family_registered(self):
        # The cleanup the rejected-file test cannot see: when SemiBold
        # is rejected, the three Barlow files this call registered are
        # unregistered again, so the process font state matches the
        # reported result.
        folder = self._folder_with(ALL_FILES)
        unregistered = []

        def register(path):
            return path.name != "BarlowCondensed-SemiBold.ttf"

        result = load_fonts(folder, _register=register,
                            _unregister=lambda p: unregistered.append(p.name))
        self.assertFalse(result.barlow)
        self.assertEqual(sorted(unregistered), [
            "BarlowCondensed-Bold.ttf",
            "BarlowCondensed-Light.ttf",
            "BarlowCondensed-Regular.ttf",
        ])

    def test_register_error_falls_back_without_raising(self):
        # Proposal 0017 §4.1: a font error never stops the app starting.
        # Barlow registers, then Wendy's register raises: the error
        # path unregisters what this call registered, so the process
        # font state matches the all-False result, and a later call can
        # register those files again.
        folder = self._folder_with(ALL_FILES)
        unregistered = []

        def register(path):
            if path.name == "wendy.ttf":
                raise OSError("the OS refused the file")
            return True

        result = load_fonts(folder, _register=register,
                            _unregister=lambda p: unregistered.append(p.name))
        self.assertEqual(result, FontLoadResult(False, False, (), ()))
        self.assertEqual(sorted(unregistered), sorted(BARLOW_FILES))
        calls = []
        again = load_fonts(folder, _register=lambda p: calls.append(p.name) or True)
        self.assertTrue(again.barlow)
        self.assertEqual(sorted(calls), sorted(ALL_FILES))

    def test_register_attribute_error_falls_back_without_raising(self):
        folder = self._folder_with(ALL_FILES)

        def register(path):
            raise AttributeError("no such font call")

        result = load_fonts(folder, _register=register)
        self.assertEqual(result, FontLoadResult(False, False, (), ()))

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
