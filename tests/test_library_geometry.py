import json
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from itgmania_library import library_geometry as data


class CourseGeometryParsingTests(unittest.TestCase):
    def test_full_geometry_parses(self):
        self.assertEqual(data.parse_window_geometry("1000x620+10+10"), (1000, 620, 10, 10))

    def test_both_negative_offset_spellings_parse(self):
        # Tk writes a negative offset as "-8" or, after the sign, as "+-8".
        self.assertEqual(data.parse_window_geometry("1000x620-8+100"), (1000, 620, -8, 100))
        self.assertEqual(data.parse_window_geometry("1000x620+-8+100"), (1000, 620, -8, 100))
        self.assertEqual(data.parse_window_geometry("1000x620+-8+-30"), (1000, 620, -8, -30))

    def test_invalid_values_are_rejected(self):
        for value in (None, 42, "", "garbage", "1000x620", "0x0+0+0", "1000x620+10",
                      "1000x620+10+10+10", "1000x620++10+10", " 1000x620+10+10",
                      # Thousands of digits trip Python's int-conversion limit;
                      # a corrupt value must be rejected, not raise.
                      "9" * 5000 + "x620+0+0", "1000x620+" + "9" * 5000 + "+0"):
            with self.subTest(value=value):
                self.assertIsNone(data.parse_window_geometry(value))


class WindowSizeParsingTests(unittest.TestCase):
    def test_size_only_string_parses(self):
        self.assertEqual(data.parse_window_size("1000x620"), (1000, 620))

    def test_anything_else_is_rejected(self):
        # A string with a position belongs to parse_window_geometry, and the
        # two parsers must not overlap.
        for value in (None, 42, "", "garbage", "1000x620+10+10", "0x620", "1000x0",
                      " 1000x620", "1000x620 ", "-1000x620", "9" * 5000 + "x620"):
            with self.subTest(value=value):
                self.assertIsNone(data.parse_window_size(value))


class OpeningGeometryTests(unittest.TestCase):
    """The shared on-screen rule (issue #103, Proposal 0016 PR 1).

    Each threshold is pinned as an exact pair: the last value that restores
    and the first that does not. A test on one side alone leaves a mutated
    threshold on the other side undetected.
    """

    DESKTOP = (0, 0, 1920, 1080)
    SIZE = (1000, 620)

    def open(self, saved, desktop=DESKTOP, scale=1.0):
        return data.opening_geometry(saved, self.SIZE, desktop, scale)

    def test_no_saved_geometry_returns_the_default_size_alone(self):
        for saved in (None, "", "garbage", "1000x620", "1000x620+10"):
            with self.subTest(saved=saved):
                self.assertEqual(self.open(saved), "1000x620")

    def test_a_visible_saved_geometry_is_restored_unchanged(self):
        self.assertEqual(self.open("900x620+30+40"), "900x620+30+40")

    def test_a_negative_offset_is_written_the_way_tk_writes_it(self):
        self.assertEqual(self.open("900x620+-30+40"), "900x620+-30+40")

    def test_a_lost_position_keeps_the_saved_size_and_drops_the_position(self):
        self.assertEqual(self.open("900x620+5000+40"), "900x620")

    def test_width_threshold_exactly_100_pixels_visible_restores(self):
        self.assertEqual(self.open("900x620+1820+40"), "900x620+1820+40")

    def test_width_threshold_99_pixels_visible_does_not_restore(self):
        self.assertEqual(self.open("900x620+1821+40"), "900x620")

    def test_width_threshold_at_the_left_edge_pair(self):
        # x + width - left: 100 visible restores, 99 does not.
        self.assertEqual(self.open("900x620+-800+40"), "900x620+-800+40")
        self.assertEqual(self.open("900x620+-801+40"), "900x620")

    def test_height_threshold_exactly_32_pixels_visible_restores(self):
        self.assertEqual(self.open("900x620+40+1048"), "900x620+40+1048")

    def test_height_threshold_31_pixels_visible_does_not_restore(self):
        self.assertEqual(self.open("900x620+40+1049"), "900x620")

    def test_height_sliver_shorter_than_the_threshold_does_not_restore(self):
        # The window is only 20 px tall, so even fully on screen it never
        # shows 32 px of itself.
        self.assertEqual(self.open("900x20+40+100"), "900x20")

    def test_title_bar_exactly_16_pixels_above_the_top_restores(self):
        self.assertEqual(self.open("900x620+100+-16"), "900x620+100+-16")

    def test_title_bar_17_pixels_above_the_top_does_not_restore(self):
        self.assertEqual(self.open("900x620+100+-17"), "900x620")

    def test_thresholds_scale_with_the_display(self):
        # At 150% the strips are 150 and 48 pixels and the title allowance is
        # 24, and the saved canonical values are scaled before the test:
        # canonical x 1180 is 1770 px, leaving exactly 150 visible; 1181
        # rounds to 1772 and leaves 148.
        self.assertEqual(self.open("900x620+1180+40", scale=1.5), "1350x930+1770+60")
        self.assertEqual(self.open("900x620+1181+40", scale=1.5), "1350x930")
        # Canonical y 32 is 48 px; -16 is -24 px, the title-bar allowance.
        self.assertEqual(self.open("900x620+100+-16", scale=1.5), "1350x930+150+-24")
        self.assertEqual(self.open("900x620+100+-17", scale=1.5), "1350x930")

    def test_a_negative_origin_desktop_restores_a_position_on_the_left_monitor(self):
        left_monitor = (-1920, 0, 1920, 1080)
        self.assertEqual(self.open("900x620+-1500+40", desktop=left_monitor),
                         "900x620+-1500+40")
        self.assertEqual(self.open("900x620+-1500+40"), "900x620")

    def test_a_stacked_monitor_above_sets_the_top_edge_rule(self):
        above = (0, -1080, 1920, 1080)
        self.assertEqual(self.open("900x620+100+-1080", desktop=above),
                         "900x620+100+-1080")
        self.assertEqual(self.open("900x620+100+-1097", desktop=above), "900x620")

    def test_recorded_cases_from_the_two_copies_this_function_replaced(self):
        # 228 outcomes recorded from CourseBuilder._geometry_for_open on main
        # (aed5218) before the two copies were removed: four scales, three
        # desktop shapes, the threshold boundaries, and unparseable values.
        path = Path(__file__).parent / "fixtures" / "opening_geometry_cases.json"
        cases = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(len(cases), 228)
        for case in cases:
            with self.subTest(case=case):
                self.assertEqual(
                    data.opening_geometry(case["saved"], tuple(case["size"]),
                                          tuple(case["desktop"]), case["scale"]),
                    case["expected"])


class DpiScaleTests(unittest.TestCase):
    """Display scaling (issue #51): the factor probe, pixel/geometry scaling, and the awareness call."""

    def test_dpi_scale_factor_reads_the_standard_dpi_values(self):
        self.assertEqual(data.dpi_scale_factor(96.0), 1.0)
        self.assertEqual(data.dpi_scale_factor(120.0), 1.25)
        self.assertEqual(data.dpi_scale_factor(144.0), 1.5)

    def test_dpi_scale_factor_treats_nonsense_readings_as_100_percent(self):
        for value in (0, -96.0, float("inf"), float("nan")):
            with self.subTest(value=value):
                self.assertEqual(data.dpi_scale_factor(value), 1.0)

    def test_scale_pixels_rounds_and_keeps_zero_at_zero(self):
        self.assertEqual(data.scale_pixels(100, 1.5), 150)
        self.assertEqual(data.scale_pixels(27, 1.25), 34)
        # 27 x 1.5 is 40.5; Python's round takes the even neighbour.
        self.assertEqual(data.scale_pixels(27, 1.5), 40)
        self.assertEqual(data.scale_pixels(0, 1.5), 0)
        self.assertEqual(data.scale_pixels(-8, 1.5), -12)

    def test_scale_geometry_handles_both_forms_and_negative_offsets(self):
        self.assertEqual(data.scale_geometry("1000x620+10+10", 1.5), "1500x930+15+15")
        self.assertEqual(data.scale_geometry("1500x850", 1.5), "2250x1275")
        self.assertEqual(data.scale_geometry("1000x620+-8+100", 1.5), "1500x930+-12+150")
        self.assertEqual(data.scale_geometry("1000x620+10+10", 1.0), "1000x620+10+10")

    def test_scale_geometry_returns_unparseable_values_unchanged(self):
        for value in ("banana", "", "1000x"):
            with self.subTest(value=value):
                self.assertEqual(data.scale_geometry(value, 1.5), value)

    def test_scaling_then_unscaling_round_trips(self):
        for value in ("1000x620+10+10", "900x620+-8+100", "1500x850"):
            for factor in (1.25, 1.5):
                with self.subTest(value=value, factor=factor):
                    self.assertEqual(
                        data.scale_geometry(data.scale_geometry(value, factor), 1.0 / factor), value)

    def test_declare_dpi_awareness_calls_system_awareness_on_windows(self):
        mock_windll = Mock()
        with patch.object(data, "ctypes") as mock_ctypes, patch.object(data.sys, "platform", "win32"):
            mock_ctypes.windll = mock_windll
            data.declare_dpi_awareness()
        mock_windll.shcore.SetProcessDpiAwareness.assert_called_once_with(1)
        mock_windll.user32.SetProcessDPIAware.assert_not_called()

    def test_declare_dpi_awareness_falls_back_when_system_awareness_is_missing(self):
        mock_windll = Mock()
        mock_windll.shcore.SetProcessDpiAwareness.side_effect = AttributeError("no shcore")
        with patch.object(data, "ctypes") as mock_ctypes, patch.object(data.sys, "platform", "win32"):
            mock_ctypes.windll = mock_windll
            data.declare_dpi_awareness()
        mock_windll.user32.SetProcessDPIAware.assert_called_once_with()

    def test_declare_dpi_awareness_does_nothing_off_windows(self):
        with patch.object(data, "ctypes") as mock_ctypes, patch.object(data.sys, "platform", "linux"):
            mock_ctypes.windll = Mock(side_effect=AssertionError("windll must not be touched"))
            data.declare_dpi_awareness()
