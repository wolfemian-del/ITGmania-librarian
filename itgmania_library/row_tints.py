"""Row tinting shared by the song table and the course queue.

Both trees tint a row by its difficulty and turn the selected row's text
white. The rule for a row's tag, the tag setup, and the bookkeeping for
the white tag live here once, so the two tables cannot drift apart
(issue #84). Colors themselves come from theme.py, as everywhere.
"""

from __future__ import annotations

from itgmania_library import theme

UNKNOWN_DIFFICULTY_TAG = "diff_unknown"  # tag for a difficulty name that theme.DIFFICULTY_COLORS lacks
SELECTED_ROW_TAG = "selected_row"  # tag that turns a selected row's text white


def difficulty_tag(row):
    """The tag that tints a row by its difficulty name."""
    name = str(row.get("Difficulty", "")).strip()
    return f"diff_{name}" if name in theme.DIFFICULTY_COLORS else UNKNOWN_DIFFICULTY_TAG


def row_tags(row, selected=False):
    """The tags a row is inserted with: its difficulty tint, plus the white tag when selected."""
    tags = [difficulty_tag(row)]
    if selected:
        tags.append(SELECTED_ROW_TAG)
    return tuple(tags)


def configure_tree_tags(tree):
    """Configure a tree's difficulty tags and its selected-row tag from the theme."""
    for diff, color in theme.DIFFICULTY_COLORS.items():
        tree.tag_configure(f"diff_{diff}", foreground=color)
    tree.tag_configure(UNKNOWN_DIFFICULTY_TAG, foreground=theme.DIFFICULTY_COLOR_UNKNOWN)
    # Keep this one last: in this order a selected row shows white text instead of its
    # difficulty color (checked in the window on Windows). A row has both tags while selected.
    tree.tag_configure(SELECTED_ROW_TAG, foreground=theme.TEXT_ON_ACCENT)


class SelectedRowTint:
    """Tracks which of one tree's rows carry the white selected-row tag.

    Bind on_select to the tree's <<TreeviewSelect>> event. A row inserted
    already carrying the tag (a refresh that kept it selected) is reported
    through note_selected, and a rebuilt tree's kept selection through
    reset, so the tracking stays true.

    The tree may be None: the course dialog's tint is created before the
    dialog (and its tree) exists. The bookkeeping methods work as usual
    then; on_select has no selection to read and does nothing.
    """

    def __init__(self, tree):
        self._tree = tree
        self.items = set()  # rows currently carrying the white tag

    def on_select(self, _event=None):
        """Give the white tag to the rows that just became selected and take it from the rest."""
        if self._tree is None:  # no tree yet (see the class docstring): nothing to read
            return
        current = set(self._tree.selection())
        for item in self.items - current:
            if self._tree.exists(item):  # a refresh may have removed the row already
                self._set(item, False)
        for item in current - self.items:
            self._set(item, True)
        self.items = current

    def note_selected(self, item):
        """Record a row that was inserted already carrying the white tag."""
        self.items.add(item)

    def forget(self, item):
        """Drop a row from the tracking and take its white tag off.

        Called when a row leaves the table without a selection event
        (Proposal 0021, D4): detaching a selected row fires no
        <<TreeviewSelect>> event, so on_select never runs for it — and
        the item stays addressable, so the stale tag would survive
        until it is reattached. A deleted row needs no forget: the
        tree drops its tags with it, and the next reset replaces the
        tracked set.

        The tag comes off whether or not the tracker knows the item
        (PR #283 Revision 1): a row selected while a refresh walk is
        still running is dropped from the tracking by the walk's final
        reset, so by detach time the tracker has already lost it — the
        old early return left its white tag on, and the row came back
        white while unselected. The tag is only written when it is
        actually there, so forgetting an untracked row without the tag
        changes nothing.
        """
        self.items.discard(item)
        if self._tree is None or not self._tree.exists(item):
            return
        # Read the item's tags rather than trusting the tracking: a
        # row selected while a walk is still running is dropped from
        # the tracking by the walk's final reset, so the tracker may
        # not know the item carries the tag. The tag is only cleared
        # when the tree actually reports it — a tree that returns
        # something other than a tag list has nothing to clear.
        tags = self._tree.item(item, "tags")
        if isinstance(tags, (tuple, list)) and SELECTED_ROW_TAG in tags:
            self._set(item, False)

    def reset(self, items=()):
        """Replace the tracked rows, e.g. after a refresh rebuilt the tree."""
        self.items = set(items)

    def _set(self, item, selected):
        tags = [tag for tag in self._tree.item(item, "tags") if tag != SELECTED_ROW_TAG]
        if selected:
            tags.append(SELECTED_ROW_TAG)
        self._tree.item(item, tags=tags)
