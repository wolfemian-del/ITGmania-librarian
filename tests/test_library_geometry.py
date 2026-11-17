import unittest
from unittest.mock import Mock, patch

from itgmania_library import library_geometry as data


class CourseGeometryParsingTests(unittest.TestCase):
    def test_full_geometry_parses(self):
        self.assertEqual(data.parse_course_geometry("1000x620+10+10"), (1000, 620, 10, 10))

    def test_both_negative_offset_spellings_parse(self):
        # Tk writes a negative offset as "-8" or, after the sign, as "+-8".
        self.assertEqual(data.parse_course_geometry("1000x620-8+100"), (1000, 620, -8, 100))
        self.assertEqual(data.parse_course_geometry("1000x620+-8+100"), (1000, 620, -8, 100))
        self.assertEqual(data.parse_course_geometry("1000x620+-8+-30"), (1000, 620, -8, -30))

    def test_invalid_values_are_rejected(self):
        for value in (None, 42, "", "garbage", "1000x620", "0x0+0+0", "1000x620+10",
                      "1000x620+10+10+10", "1000x620++10+10", " 1000x620+10+10",
                      # Thousands of digits trip Python's int-conversion limit;
                      # a corrupt value must be rejected, not raise.
                      "9" * 5000 + "x620+0+0", "1000x620+" + "9" * 5000 + "+0"):
            with self.subTest(value=value):
                self.assertIsNone(data.parse_course_geometry(value))


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
