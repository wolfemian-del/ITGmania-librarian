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
    """The shared on-screen rule (issue #103, Proposal 0016).

    Each threshold is pinned as an exact pair: the last value that restores
    and the first that does not. A test on one side alone leaves a mutated
    threshold on the other side undetected. A window that does not restore
    is centered, so "does not restore" is asserted as the centered result.
    """

    DESKTOP = (0, 0, 1920, 1080)
    SIZE = (1000, 620)

    def open(self, saved, desktop=DESKTOP, scale=1.0, size=SIZE, **kwargs):
        return data.opening_geometry(saved, size, desktop, scale, **kwargs)

    # Without an anchor the outer box (size plus a 16 by 39 frame) is
    # centered in the desktop: x = (1920 - (w + 16)) // 2, y = (1080 - (h + 39)) // 2.

    def test_nothing_usable_saved_centers_the_default_size(self):
        for saved in (None, "", "garbage", "1000x620", "1000x620+10", "+10", "+10+x"):
            with self.subTest(saved=saved):
                self.assertEqual(self.open(saved), "1000x620+452+210")

    def test_a_visible_saved_geometry_is_restored_unchanged(self):
        self.assertEqual(self.open("900x620+30+40"), "900x620+30+40")

    def test_a_negative_offset_is_written_the_way_tk_writes_it(self):
        self.assertEqual(self.open("900x620+-30+40"), "900x620+-30+40")

    def test_a_lost_position_keeps_the_saved_size_and_centers(self):
        self.assertEqual(self.open("900x620+5000+40"), "900x620+502+210")

    def test_width_threshold_exactly_100_pixels_visible_restores(self):
        self.assertEqual(self.open("900x620+1820+40"), "900x620+1820+40")

    def test_width_threshold_99_pixels_visible_does_not_restore(self):
        self.assertEqual(self.open("900x620+1821+40"), "900x620+502+210")

    def test_width_threshold_at_the_left_edge_pair(self):
        # x + width - left: 100 visible restores, 99 does not.
        self.assertEqual(self.open("900x620+-800+40"), "900x620+-800+40")
        self.assertEqual(self.open("900x620+-801+40"), "900x620+502+210")

    def test_height_threshold_exactly_32_pixels_visible_restores(self):
        self.assertEqual(self.open("900x620+40+1048"), "900x620+40+1048")

    def test_height_threshold_31_pixels_visible_does_not_restore(self):
        self.assertEqual(self.open("900x620+40+1049"), "900x620+502+210")

    def test_height_sliver_shorter_than_the_threshold_does_not_restore(self):
        # The window is only 20 px tall, so even fully on screen it never
        # shows 32 px of itself.
        self.assertEqual(self.open("900x20+40+100"), "900x20+502+510")

    def test_title_bar_exactly_16_pixels_above_the_top_restores(self):
        self.assertEqual(self.open("900x620+100+-16"), "900x620+100+-16")

    def test_title_bar_17_pixels_above_the_top_does_not_restore(self):
        self.assertEqual(self.open("900x620+100+-17"), "900x620+502+210")

    def test_thresholds_scale_with_the_display(self):
        # At 150% the strips are 150 and 48 pixels and the title allowance is
        # 24, and the saved canonical values are scaled before the test:
        # canonical x 1180 is 1770 px, leaving exactly 150 visible; 1181
        # rounds to 1772 and leaves 148. A lost position centers the scaled
        # size: the frame is 24 by 58 at 150%.
        self.assertEqual(self.open("900x620+1180+40", scale=1.5), "1350x930+1770+60")
        self.assertEqual(self.open("900x620+1181+40", scale=1.5), "1350x930+273+46")
        # Canonical y -16 is -24 px, the title-bar allowance.
        self.assertEqual(self.open("900x620+100+-16", scale=1.5), "1350x930+150+-24")
        self.assertEqual(self.open("900x620+100+-17", scale=1.5), "1350x930+273+46")

    def test_a_negative_origin_desktop_restores_a_position_on_the_left_monitor(self):
        left_monitor = (-1920, 0, 1920, 1080)
        self.assertEqual(self.open("900x620+-1500+40", desktop=left_monitor),
                         "900x620+-1500+40")
        self.assertEqual(self.open("900x620+-1500+40"), "900x620+502+210")

    def test_a_stacked_monitor_above_sets_the_top_edge_rule(self):
        above = (0, -1080, 1920, 1080)
        self.assertEqual(self.open("900x620+100+-1080", desktop=above),
                         "900x620+100+-1080")
        self.assertEqual(self.open("900x620+100+-1097", desktop=above),
                         "900x620+502+-330")

    def test_the_restore_decisions_match_the_two_copies_this_function_replaced(self):
        # 228 outcomes recorded from CourseBuilder._geometry_for_open on main
        # (aed5218) before the two copies were removed: four scales, three
        # desktop shapes, the threshold boundaries, and unparseable values.
        # Where the old code restored a position, so does this; where it
        # fell back to the size alone, this centers the same size.
        path = Path(__file__).parent / "fixtures" / "opening_geometry_cases.json"
        cases = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(len(cases), 228)
        for case in cases:
            with self.subTest(case=case):
                left, top, right, bottom = case["desktop"]
                scale = case["scale"]
                got = data.opening_geometry(case["saved"], tuple(case["size"]),
                                            tuple(case["desktop"]), scale)
                # The one new rule that applies: a size larger than the
                # screen less the frame is capped (at 200% the default and
                # the doubled saved sizes are).
                max_width = (right - left) - data.scale_pixels(16, scale)
                max_height = (bottom - top) - data.scale_pixels(39, scale)
                size_part, _, position = case["expected"].partition("+")
                width, height = (int(v) for v in size_part.split("x"))
                capped = f"{min(width, max_width)}x{min(height, max_height)}"
                if position:
                    self.assertEqual(got, f"{capped}+{position}")
                else:
                    self.assertEqual(got.split("+", 1)[0], capped)
                    self.assertIn("+", got)


class OpeningGeometryPlacementTests(unittest.TestCase):
    """Centering, the work area and the position-only form (Proposal 0016 §4.1).

    1920x1080 desktop, a 1920x1032 work area (a 48 px taskbar), the 16 by 39
    frame, a main window of 1500x850 at +100+50. The expected strings were
    worked out by the reference implementation behind the proposal's table.
    """

    DESKTOP = (0, 0, 1920, 1080)
    WORK = (0, 0, 1920, 1032)
    MAIN = (100, 50, 1500, 850)

    def place(self, saved, size, anchor=MAIN, work=WORK, desktop=DESKTOP, scale=1.0,
              min_size=(1, 1)):
        return data.opening_geometry(saved, size, desktop, scale, anchor=anchor,
                                     work=work, min_size=min_size)

    def test_a_dialog_is_centered_over_the_main_window(self):
        self.assertEqual(self.place(None, (1000, 620)), "1000x620+350+165")
        self.assertEqual(self.place(None, (760, 580)), "760x580+470+185")

    def test_a_tall_window_is_shifted_up_off_the_taskbar(self):
        low = (100, 250, 1500, 850)
        self.assertEqual(self.place(None, (760, 910), anchor=low), "760x910+470+83")
        # The same window clamped to the whole desktop would cover the taskbar.
        self.assertEqual(self.place(None, (760, 910), anchor=low, work=self.DESKTOP),
                         "760x910+470+131")

    def test_a_window_taller_than_the_work_area_is_capped(self):
        self.assertEqual(self.place(None, (760, 1400)), "760x993+470+0")

    def test_without_an_anchor_the_outer_box_is_centered_in_the_work_area(self):
        self.assertEqual(self.place(None, (1000, 620), anchor=None), "1000x620+452+186")

    def test_a_full_saved_position_is_restored_unclamped(self):
        # Rule 2: a place the owner dragged to is not second-guessed, even
        # when part of it hangs off an edge or under the taskbar.
        self.assertEqual(self.place("900x620+30+40", (1, 1)), "900x620+30+40")
        self.assertEqual(self.place("900x620+-30+40", (1, 1)), "900x620+-30+40")
        # Outer bottom 100 + 900 + 39 = 1039, 7 px past the 1032 work area.
        self.assertEqual(self.place("900x900+30+100", (1, 1)), "900x900+30+100")
        self.assertEqual(self.place("900x620+30+700", (1, 1)), "900x620+30+700")

    def test_a_full_saved_size_larger_than_the_work_area_is_capped_in_place(self):
        self.assertEqual(self.place("3000x2000+10+10", (1, 1)), "1904x993+10+10")

    def test_a_lost_full_position_keeps_the_saved_size_and_centers(self):
        self.assertEqual(self.place("900x620+5000+40", (1, 1)), "900x620+400+165")
        self.assertEqual(self.place("1x1+0+0", (1000, 620)), "1x1+849+474")

    def test_a_negative_origin_desktop_with_a_matching_work_area(self):
        desktop = (-1920, 0, 1920, 1080)
        work = (-1920, 0, 1920, 1032)
        self.assertEqual(self.place("900x620+-1500+40", (1, 1), desktop=desktop, work=work),
                         "900x620+-1500+40")

    def test_a_position_only_value_keeps_its_position_and_the_content_size(self):
        self.assertEqual(self.place("+200+100", (760, 580)), "760x580+200+100")

    def test_a_position_only_value_is_shifted_so_the_outer_box_fits(self):
        self.assertEqual(self.place("+200+800", (760, 910)), "760x910+200+83")
        self.assertEqual(self.place("+200+100", (760, 1400)), "760x993+200+0")
        self.assertEqual(self.place("+-30+40", (760, 580)), "760x580+0+40")
        self.assertEqual(self.place("+1800+100", (760, 580)), "760x580+1144+100")

    def test_a_position_only_value_that_is_off_screen_centers(self):
        self.assertEqual(self.place("+5000+40", (760, 580)), "760x580+470+185")

    def test_a_size_below_the_minimum_is_floored_to_it(self):
        # Issue #244: on a work area smaller than the minimum plus the
        # frame, the cap alone would size below the minimum and Tk would
        # enforce it anyway, so the window opens at its minimum and the
        # position is clamped for that enforced size.
        small = (0, 0, 500, 400)
        minimum = (560, 420)
        self.assertEqual(self.place("900x620+30+40", (1000, 620), work=small,
                                    min_size=minimum), "560x420+30+40")
        self.assertEqual(self.place("+200+100", (760, 580), work=small,
                                    min_size=minimum), "560x420+0+0")
        self.assertEqual(self.place(None, (760, 580), work=small,
                                    min_size=minimum), "560x420+0+0")

    def test_the_minimum_floor_starts_exactly_at_the_minimum_plus_the_frame(self):
        # One pixel either side of the boundary: at 577x460 the cap is
        # 561x421 (above the minimum, no floor); at 576x459 it is the
        # minimum itself.
        self.assertEqual(self.place(None, (760, 580), work=(0, 0, 577, 460),
                                    min_size=(560, 420)), "561x421+0+0")
        self.assertEqual(self.place(None, (760, 580), work=(0, 0, 576, 459),
                                    min_size=(560, 420)), "560x420+0+0")

    def test_the_minimum_floor_scales_with_the_display(self):
        # Grok's review of PR #247: at 150% the 560x420 minimum is
        # 840x630 and the frame 24x58, so on an 860x680 work area the
        # floor wins in both dimensions.
        self.assertEqual(self.place(None, (1140, 870),
                                    anchor=(100, 50, 2250, 1275),
                                    work=(0, 0, 860, 680), scale=1.5,
                                    min_size=(560, 420)), "840x630+0+0")

    def test_the_frame_scales_with_the_display(self):
        # 150%: the frame is 24 by 58, so a 1350x930 window needs 1374 by 988 px of
        # the work area. Centered over a main window of 2250x1275 at +100+50 it
        # would sit at +550+222; the clamp pulls it to +546+44.
        self.assertEqual(self.place(None, (1350, 930), anchor=(100, 50, 2250, 1275), scale=1.5),
                         "1350x930+546+44")

    def test_a_work_area_smaller_than_the_frame_collapses_to_one_pixel(self):
        # The size cannot go below 1 and the left and top edges win the clamp.
        self.assertEqual(self.place(None, (500, 500), anchor=None, work=(0, 0, 10, 10),
                                    desktop=(0, 0, 10, 10)), "1x1+0+0")

    def test_every_centered_result_lies_inside_the_work_area(self):
        for anchor in (self.MAIN, (-500, -300, 900, 700), (1800, 900, 1500, 850), None):
            for size in ((300, 200), (1000, 620), (760, 1400), (2500, 2500)):
                with self.subTest(anchor=anchor, size=size):
                    width, height, x, y = data.parse_window_geometry(
                        self.place(None, size, anchor=anchor))
                    self.assertLessEqual(width + 16, 1920)
                    self.assertLessEqual(height + 39, 1032)
                    self.assertGreaterEqual(x, 0)
                    self.assertGreaterEqual(y, 0)
                    self.assertLessEqual(x + width + 16, 1920)
                    self.assertLessEqual(y + height + 39, 1032)


class WindowPositionParsingTests(unittest.TestCase):
    def test_position_only_strings_parse(self):
        self.assertEqual(data.parse_window_position("+100+50"), (100, 50))
        self.assertEqual(data.parse_window_position("+-8+40"), (-8, 40))
        self.assertEqual(data.parse_window_position("-8+40"), (-8, 40))
        self.assertEqual(data.parse_window_position("+-8+-30"), (-8, -30))

    def test_anything_else_is_rejected(self):
        for value in (None, 42, "", "garbage", "1000x620", "1000x620+10+10", "+100", "+100+50+7",
                      "++100+50", " +100+50", "+100+50 ", "+1+x",
                      "+" + "9" * 5000 + "+0"):
            with self.subTest(value=value):
                self.assertIsNone(data.parse_window_position(value))


class WorkAreaTests(unittest.TestCase):
    def test_off_windows_there_is_no_work_area(self):
        with patch.object(data.sys, "platform", "linux"):
            self.assertIsNone(data.work_area_of(None))
            self.assertIsNone(data.work_area_of(1234))

    def test_a_failing_call_gives_none_not_an_exception(self):
        # On Windows the DLL is there, so make the platform check pass and
        # the call itself fail: any OSError or AttributeError means "unknown".
        with patch.object(data.sys, "platform", "win32"), \
                patch.object(data.ctypes, "WinDLL", side_effect=OSError("no user32"), create=True):
            self.assertIsNone(data.work_area_of(1234))
        with patch.object(data.sys, "platform", "win32"), \
                patch.object(data.ctypes, "WinDLL", create=True) as dll:
            dll.return_value.MonitorFromWindow.return_value = 0  # no monitor
            self.assertIsNone(data.work_area_of(1234))

    def test_a_point_is_accepted_and_ignored_off_windows(self):
        # Proposal 0023: the point is the saved place's top-left, scaled
        # to physical pixels; off Windows there is no monitor to ask, so
        # the lookup reports "unknown" and the caller falls back to the
        # virtual desktop.
        with patch.object(data.sys, "platform", "linux"):
            self.assertIsNone(data.work_area_of(point=(100, 100)))
            self.assertIsNone(data.work_area_of(point=(5000, 5000)))

    def test_a_point_asks_monitor_from_point_by_value(self):
        # Proposal 0023, item 4: MonitorFromPoint takes a POINT by value,
        # so argtypes is set on the private WinDLL handle, as for
        # MonitorFromWindow. The call itself is pinned, not the rect: the
        # real rect comes from Windows, which the sandbox cannot reach.
        with patch.object(data.sys, "platform", "win32"), \
                patch.object(data.ctypes, "WinDLL", create=True) as dll:
            user32 = dll.return_value
            user32.MonitorFromPoint.return_value = 7
            result = data.work_area_of(point=(200, 100))
            self.assertEqual(user32.MonitorFromPoint.call_count, 1)
            point, flags = user32.MonitorFromPoint.call_args.args
            self.assertEqual((point.x, point.y), (200, 100))
            self.assertEqual(flags, 2)  # MONITOR_DEFAULTTONEAREST
            self.assertEqual(user32.MonitorFromPoint.argtypes,
                             [data.ctypes.wintypes.POINT, data.ctypes.wintypes.DWORD])
            # The monitor was found and the info call answered: the work
            # area is whatever rcWork holds (a Mock here, so only the
            # shape is asserted).
            self.assertEqual(len(result), 4)


class CanonicalGeometryTests(unittest.TestCase):
    """canonical_geometry (Proposal 0023): the inverse of scale_geometry."""

    def test_scale_one_leaves_the_string_unchanged(self):
        self.assertEqual(data.canonical_geometry("1500x850+100+50", 1.0),
                         "1500x850+100+50")

    def test_a_scaled_geometry_comes_back_to_canonical_units(self):
        self.assertEqual(data.canonical_geometry("2250x1275+150+75", 1.5),
                         "1500x850+100+50")
        self.assertEqual(data.canonical_geometry("2250x1275", 1.5), "1500x850")
        self.assertEqual(data.canonical_geometry("1500x930+-12+150", 1.5),
                         "1000x620+-8+100")

    def test_scaling_then_canonicalizing_round_trips(self):
        for value in ("1000x620+10+10", "900x620+-8+100", "1500x850"):
            for factor in (1.25, 1.5):
                with self.subTest(value=value, factor=factor):
                    self.assertEqual(
                        data.canonical_geometry(data.scale_geometry(value, factor), factor),
                        value)

    def test_an_unusable_scale_leaves_the_string_unchanged(self):
        for scale in (0, -1.5, float("inf"), float("nan")):
            with self.subTest(scale=scale):
                self.assertEqual(data.canonical_geometry("1000x620+10+10", scale),
                                 "1000x620+10+10")

    def test_an_unparseable_value_is_returned_unchanged(self):
        self.assertEqual(data.canonical_geometry("banana", 1.5), "banana")


class SavedGeometryVisibleTests(unittest.TestCase):
    """saved_geometry_visible (Proposal 0023): the visibility half of opening_geometry's rule 2."""

    DESKTOP = (0, 0, 1920, 1080)
    WORK = (0, 0, 1920, 1032)
    MIN_SIZE = (900, 550)

    def visible(self, saved, desktop=DESKTOP, scale=1.0, work=WORK, min_size=MIN_SIZE):
        return data.saved_geometry_visible(saved, desktop, scale, work, min_size)

    def test_a_visible_saved_place_is_visible(self):
        self.assertTrue(self.visible("900x620+30+40"))

    def test_a_place_off_every_monitor_is_not_visible(self):
        self.assertFalse(self.visible("900x620+5000+40"))

    def test_width_threshold_exactly_100_pixels_visible(self):
        self.assertTrue(self.visible("900x620+1820+40"))
        self.assertFalse(self.visible("900x620+1821+40"))

    def test_width_threshold_at_the_left_edge_pair(self):
        self.assertTrue(self.visible("900x620+-800+40"))
        self.assertFalse(self.visible("900x620+-801+40"))

    def test_height_threshold_exactly_32_pixels_visible(self):
        self.assertTrue(self.visible("900x620+40+1048"))
        self.assertFalse(self.visible("900x620+40+1049"))

    def test_title_bar_exactly_16_pixels_above_the_top_is_visible(self):
        self.assertTrue(self.visible("900x620+100+-16"))
        self.assertFalse(self.visible("900x620+100+-17"))

    def test_a_missing_position_only_or_unparsable_value_is_not_visible(self):
        for saved in (None, "", "garbage", "1000x620", "1000x620+10", "+10+10"):
            with self.subTest(saved=saved):
                self.assertFalse(self.visible(saved))

    def test_no_work_area_falls_back_to_the_desktop(self):
        # Off Windows the lookup returns None; the helper caps against
        # the desktop, as opening_geometry does.
        self.assertTrue(self.visible("900x620+30+40", work=None))
        self.assertFalse(self.visible("900x620+5000+40", work=None))

    def test_thresholds_scale_with_the_display(self):
        # At 150% the strips are 150 and 48 pixels and the title
        # allowance is 24, and the saved canonical values are scaled
        # before the test, as in opening_geometry.
        self.assertTrue(self.visible("900x620+1180+40", scale=1.5))
        self.assertFalse(self.visible("900x620+1181+40", scale=1.5))
        self.assertTrue(self.visible("900x620+100+-16", scale=1.5))
        self.assertFalse(self.visible("900x620+100+-17", scale=1.5))


class VisibilityAgreementTests(unittest.TestCase):
    """saved_geometry_visible and opening_geometry agree (Proposal 0023, Claude note 1).

    Both call the one shared _visible_saved_box, so a saved place cannot
    be visible to one and invisible to the other. The grid asserts the
    biconditional through opening_geometry's observable behaviour: a
    visible place is restored at its saved position, an invisible one is
    centered elsewhere. The centered position for a 900x620 window in
    the 1920x1032 work area is (502, 186), which no grid position is,
    so the two cases cannot be confused.
    """

    DESKTOP = (0, 0, 1920, 1080)
    WORK = (0, 0, 1920, 1032)
    MIN_SIZE = (900, 550)

    def test_the_two_agree_over_a_grid_of_saved_places(self):
        xs = (-1000, -800, -100, 0, 100, 500, 1000, 1500, 1820, 1821, 1900, 5000)
        ys = (-100, -17, -16, 0, 100, 500, 700, 1048, 1049, 1080)
        for x in xs:
            for y in ys:
                saved = f"900x620+{x}+{y}"
                with self.subTest(saved=saved):
                    visible = data.saved_geometry_visible(
                        saved, self.DESKTOP, 1.0, self.WORK, self.MIN_SIZE)
                    result = data.opening_geometry(
                        saved, (1500, 850), self.DESKTOP, 1.0,
                        work=self.WORK, min_size=self.MIN_SIZE)
                    width, height, rx, ry = data.parse_window_geometry(result)
                    if visible:
                        self.assertEqual((rx, ry), (x, y))
                        self.assertEqual((width, height), (900, 620))
                    else:
                        self.assertNotEqual((rx, ry), (x, y))

    def test_the_two_agree_at_150_percent_and_on_a_second_monitor(self):
        # At 150% the saved canonical values are scaled before the test.
        self.assertTrue(data.saved_geometry_visible(
            "900x620+1180+40", self.DESKTOP, 1.5, self.WORK, self.MIN_SIZE))
        result = data.opening_geometry(
            "900x620+1180+40", (1500, 850), self.DESKTOP, 1.5,
            work=self.WORK, min_size=self.MIN_SIZE)
        self.assertEqual(result, "1350x930+1770+60")
        # A second monitor's work area: the same saved place is visible
        # there and the rule restores it at its saved position.
        desktop = (0, 0, 3840, 1080)
        second = (1920, 0, 3840, 1032)
        self.assertTrue(data.saved_geometry_visible(
            "900x620+2000+100", desktop, 1.0, second, self.MIN_SIZE))
        result = data.opening_geometry(
            "900x620+2000+100", (1500, 850), desktop, 1.0,
            work=second, min_size=self.MIN_SIZE)
        self.assertEqual(result, "900x620+2000+100")

    def test_the_proposals_named_exception_different_work_areas_can_disagree(self):
        # The proposal's documented exception: the shell calls the
        # helper with the saved-point monitor's work area, and if it
        # says invisible calls opening_geometry with the primary work
        # area. A box left of the virtual-desktop edge can be invisible
        # after the smaller saved-monitor cap but visible after the
        # larger primary cap, so the two answers differ — by design,
        # and the rule restores it at its saved position.
        desktop = (-1920, 0, 1920, 1080)
        saved_work = (-1920, 0, -640, 1032)
        primary_work = (0, 0, 1920, 1032)
        saved = "3000x620+-3200+40"
        self.assertFalse(data.saved_geometry_visible(
            saved, desktop, 1.0, saved_work, self.MIN_SIZE))
        result = data.opening_geometry(
            saved, (1500, 850), desktop, 1.0,
            work=primary_work, min_size=self.MIN_SIZE)
        width, height, rx, ry = data.parse_window_geometry(result)
        self.assertEqual((rx, ry), (-3200, 40))


class MainWindowSaveDecisionTests(unittest.TestCase):
    """decide_main_window_save (Proposal 0023, §6): the ten save cases as a Tk-free pure function.

    Cases (1)–(7) are the function alone; (8)–(10) are the shell's
    wiring and live in tests/test_library_librarian.py.
    """

    OPENING = "1500x850+210+91"
    MOVED = "1500x850+300+100"

    def decide(self, last, opening, last_maximized, saved_maximized):
        return data.decide_main_window_save(last, opening, last_maximized, saved_maximized)

    def test_case_1_an_untouched_normal_session_writes_nothing(self):
        self.assertIsNone(self.decide(self.OPENING, self.OPENING, False, False))

    def test_case_2_a_moved_window_writes_the_geometry_only(self):
        self.assertEqual(self.decide(self.MOVED, self.OPENING, False, False),
                         {"main_window_geometry": self.MOVED})

    def test_case_3_a_window_dragged_back_to_its_opening_place_writes_nothing(self):
        # The function sees only the final values: moved and returned
        # reads exactly as never moved.
        self.assertIsNone(self.decide(self.OPENING, self.OPENING, False, False))

    def test_case_4_opened_normal_maximized_closed_with_no_move_writes_the_flag_only(self):
        # The last normal geometry is the opening geometry, so it equals
        # the baseline and the saved geometry stays as it was.
        self.assertEqual(self.decide(self.OPENING, self.OPENING, True, False),
                         {"main_window_maximized": True})

    def test_case_5_opened_maximized_closed_untouched_writes_nothing(self):
        self.assertIsNone(self.decide(self.OPENING, self.OPENING, True, True))

    def test_case_6_opened_maximized_un_maximized_closed_with_no_move_writes_the_flag_only(self):
        # The window returns to the opening geometry, so it equals the
        # baseline and the saved geometry stays as it was.
        self.assertEqual(self.decide(self.OPENING, self.OPENING, False, True),
                         {"main_window_maximized": False})

    def test_case_7_minimizing_alone_changes_neither_input(self):
        # Maximized then minimized: the shown state keeps its last shown
        # value, so the flag is written.
        self.assertEqual(self.decide(self.OPENING, self.OPENING, True, False),
                         {"main_window_maximized": True})
        # Normal then minimized: the flag stays false, so nothing is written.
        self.assertIsNone(self.decide(self.OPENING, self.OPENING, False, False))

    def test_both_changed_writes_both(self):
        self.assertEqual(self.decide(self.MOVED, self.OPENING, True, False),
                         {"main_window_geometry": self.MOVED,
                          "main_window_maximized": True})

    def test_a_window_never_placed_writes_no_geometry(self):
        self.assertIsNone(self.decide(None, None, False, False))
        self.assertEqual(self.decide(None, None, True, False),
                         {"main_window_maximized": True})


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
