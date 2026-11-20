"""Tests for the opening half of WindowPlacement (Proposal 0016, PR 2).

The helper gathers the main window's state, box, the desktop and the work
area and hands them to opening_geometry; these tests drive it with a
Tk-free stand-in for the main window.
"""

import unittest
from unittest.mock import Mock, patch

from itgmania_library.window_placement import WindowPlacement
from tests.window_fakes import main_window_fake, settle_opening

WORK = (0, 0, 1920, 1032)


class WindowPlacementTests(unittest.TestCase):
    def placement(self, saved=None, scale=1.0, **parent_args):
        return WindowPlacement(main_window_fake(**parent_args), scale, saved)

    def test_a_dialog_is_centered_over_a_normal_main_window(self):
        with patch("itgmania_library.window_placement.work_area_of", return_value=WORK) as lookup:
            geometry = self.placement().geometry_for_open("1000x620")
        self.assertEqual(geometry, "1000x620+350+165")
        lookup.assert_called_once_with(1)  # the main window's handle

    def test_a_maximized_main_window_is_read_the_same_way(self):
        # geometry() goes stale when maximized; the winfo_* box does not,
        # so one reading serves both states.
        with patch("itgmania_library.window_placement.work_area_of", return_value=WORK):
            geometry = self.placement(box=(-8, -8, 1936, 1048),
                                      state="zoomed").geometry_for_open("1000x620")
        self.assertEqual(geometry, "1000x620+460+206")

    def test_a_minimized_main_window_centers_in_the_primary_work_area(self):
        for state in ("iconic", "withdrawn"):
            with self.subTest(state=state), patch(
                    "itgmania_library.window_placement.work_area_of",
                    return_value=WORK) as lookup:
                geometry = self.placement(box=(-32000, -32000, 160, 28),
                                          state=state).geometry_for_open("1000x620")
            self.assertEqual(geometry, "1000x620+452+186")
            lookup.assert_called_once_with(None)  # no handle: the primary monitor

    def test_an_unknown_work_area_falls_back_to_the_virtual_desktop(self):
        with patch("itgmania_library.window_placement.work_area_of", return_value=None):
            geometry = self.placement(state="iconic").geometry_for_open("1000x620")
        self.assertEqual(geometry, "1000x620+452+210")

    def test_the_work_area_keeps_a_tall_window_off_the_taskbar(self):
        with patch("itgmania_library.window_placement.work_area_of", return_value=WORK):
            geometry = self.placement(box=(100, 250, 1500, 850)).geometry_for_content(760, 910)
        self.assertEqual(geometry, "760x910+470+83")

    def test_the_default_size_is_scaled_to_the_display(self):
        with patch("itgmania_library.window_placement.work_area_of", return_value=None):
            geometry = self.placement(scale=1.5).geometry_for_open("560x620")
        self.assertEqual(geometry, "840x930+430+10")

    def test_a_visible_saved_geometry_is_restored(self):
        with patch("itgmania_library.window_placement.work_area_of", return_value=WORK):
            geometry = self.placement(saved="900x620+30+40").geometry_for_open("1000x620")
        self.assertEqual(geometry, "900x620+30+40")

    def test_a_position_only_value_uses_the_content_size(self):
        with patch("itgmania_library.window_placement.work_area_of", return_value=WORK):
            placement = self.placement(saved="+200+800")
            self.assertFalse(placement.has_saved_size)
            self.assertEqual(placement.geometry_for_content(760, 910), "760x910+200+83")

    def test_has_saved_size_is_true_only_for_a_full_geometry(self):
        self.assertFalse(self.placement().has_saved_size)
        self.assertFalse(self.placement(saved="+200+100").has_saved_size)
        self.assertFalse(self.placement(saved="garbage").has_saved_size)
        self.assertTrue(self.placement(saved="900x620+30+40").has_saved_size)

    def test_the_saved_value_is_the_one_it_was_given(self):
        self.assertIsNone(self.placement().saved_geometry)
        self.assertEqual(self.placement(saved="+200+100").saved_geometry, "+200+100")

    def test_a_default_that_is_not_a_size_is_an_error(self):
        with self.assertRaises(ValueError):
            self.placement().geometry_for_open("1000x620+10+10")


if __name__ == "__main__":
    unittest.main()


class WindowPlacementSaveTests(unittest.TestCase):
    """The save half (Proposal 0016 D3, PR 3): only a deliberate change is remembered."""

    OPENED = "1000x620+350+165"

    def opened(self, saved=None, scale=1.0, report=None):
        """A placement and a Mock window that has finished opening at OPENED."""
        placement = WindowPlacement(main_window_fake(), scale, saved, report)
        window = Mock()
        placement.record_opening(window)
        settle_opening(window, self.OPENED)
        return placement, window

    def test_a_window_closed_where_it_opened_remembers_nothing(self):
        report = Mock()
        placement, window = self.opened(report=report)
        placement.save(window)
        report.assert_not_called()
        self.assertIsNone(placement.saved_geometry)

    def test_a_move_is_remembered_and_reported(self):
        report = Mock()
        placement, window = self.opened(report=report)
        window.geometry.return_value = "1000x620+10+10"
        placement.save(window)
        report.assert_called_once_with("1000x620+10+10")
        self.assertEqual(placement.saved_geometry, "1000x620+10+10")

    def test_a_resize_is_remembered(self):
        report = Mock()
        placement, window = self.opened(report=report)
        window.geometry.return_value = "1200x700+350+165"
        placement.save(window)
        report.assert_called_once_with("1200x700+350+165")

    def test_the_saved_value_updates_without_anyone_listening(self):
        placement, window = self.opened()  # no report_geometry
        window.geometry.return_value = "900x620+5+5"
        placement.save(window)
        self.assertEqual(placement.saved_geometry, "900x620+5+5")

    def test_a_window_dragged_away_and_back_remembers_nothing(self):
        report = Mock()
        placement, window = self.opened(report=report)
        window.geometry.return_value = "1000x620+10+10"  # dragged away ...
        window.geometry.return_value = self.OPENED  # ... and back, before closing
        placement.save(window)
        report.assert_not_called()

    def test_the_stored_value_is_in_canonical_units(self):
        report = Mock()
        placement, window = self.opened(scale=1.5, report=report)
        window.geometry.return_value = "1350x930+45+60"
        placement.save(window)
        report.assert_called_once_with("900x620+30+40")

    def test_a_minimized_or_maximized_window_saves_nothing(self):
        for state in ("iconic", "zoomed", "withdrawn"):
            with self.subTest(state=state):
                report = Mock()
                placement, window = self.opened(report=report)
                window.geometry.return_value = "160x28+-32000+-32000"
                window.state.return_value = state
                placement.save(window)
                report.assert_not_called()

    def test_a_window_that_is_gone_or_missing_saves_nothing(self):
        report = Mock()
        placement, window = self.opened(report=report)
        window.geometry.return_value = "1000x620+10+10"
        window.winfo_exists.return_value = 0
        placement.save(window)
        placement.save(None)
        report.assert_not_called()

    def test_a_close_before_the_opening_was_captured_saves_nothing(self):
        report = Mock()
        placement = WindowPlacement(main_window_fake(), 1.0, None, report)
        window = Mock()
        placement.record_opening(window)  # the idle capture has not run
        window.state.return_value = "normal"
        window.geometry.return_value = "1000x620+10+10"
        placement.save(window)
        report.assert_not_called()

    def test_a_new_open_clears_the_previous_baseline_at_once(self):
        # Closing the second window before its capture runs must not compare
        # against the first open's baseline.
        report = Mock()
        placement, window = self.opened(report=report)
        second = Mock()
        placement.record_opening(second)
        second.state.return_value = "normal"
        second.geometry.return_value = "1000x620+10+10"
        placement.save(second)
        report.assert_not_called()

    def test_the_capture_runs_once_a_later_run_cannot_overwrite_it(self):
        report = Mock()
        placement, window = self.opened(report=report)
        window.geometry.return_value = "1000x620+10+10"  # moved, then a stray second capture
        window.after_idle.call_args.args[0]()
        placement.save(window)
        report.assert_called_once_with("1000x620+10+10")

    def test_the_capture_does_nothing_for_a_window_destroyed_in_the_meantime(self):
        placement = WindowPlacement(main_window_fake(), 1.0)
        window = Mock()
        placement.record_opening(window)
        window.winfo_exists.return_value = 0
        window.after_idle.call_args.args[0]()
        window.geometry.assert_not_called()
