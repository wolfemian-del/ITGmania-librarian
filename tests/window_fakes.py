"""Tk-free stand-ins for the main window, shared by the dialog tests.

The secondary windows now center themselves over the main window
(Proposal 0016), so a test that opens one needs a parent that answers the
questions WindowPlacement asks: its state, its box, the virtual desktop.
"""

from unittest.mock import Mock, patch


def main_window_fake(box=(100, 50, 1500, 850), vroot=(0, 0, 1920, 1080), state="normal"):
    """A parent window at box = (x, y, width, height) on a desktop of vroot."""
    parent = Mock()
    parent.winfo_vrootx.return_value = vroot[0]
    parent.winfo_vrooty.return_value = vroot[1]
    parent.winfo_vrootwidth.return_value = vroot[2]
    parent.winfo_vrootheight.return_value = vroot[3]
    parent.state.return_value = state
    (parent.winfo_x.return_value, parent.winfo_y.return_value,
     parent.winfo_width.return_value, parent.winfo_height.return_value) = box
    parent.winfo_id.return_value = 1
    return parent


def no_work_area():
    """Start a patch making the work-area lookup report 'unknown' and return it.

    The real lookup asks Windows, so on the owner's machine the answer would
    depend on the taskbar. With None the placement falls back to the virtual
    desktop and the expected numbers are the same everywhere. The caller
    stops the patch (setUpModule / tearDownModule).
    """
    patcher = patch("itgmania_library.window_placement.work_area_of", return_value=None)
    patcher.start()
    return patcher
