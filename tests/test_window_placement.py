"""Tests for the opening half of WindowPlacement (Proposal 0016, PR 2).

The helper gathers the main window's state, box, the desktop and the work
area and hands them to opening_geometry; these tests drive it with a
Tk-free stand-in for the main window.
"""

import unittest
from unittest.mock import patch

from itgmania_library.window_placement import WindowPlacement
from tests.window_fakes import main_window_fake

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
