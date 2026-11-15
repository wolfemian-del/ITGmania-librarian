"""The shared vocabulary — the column and grade tables every other module and the UI read from."""


TECH_FIELDS = ("Crossovers", "HalfCrossovers", "FullCrossovers", "Footswitches",
               "UpFootswitches", "DownFootswitches", "Sideswitches", "Jacks",
               "Brackets", "Doublesteps")
DIFFICULTY_ORDER = ("Beginner", "Easy", "Medium", "Hard", "Challenge", "Edit")
DIFFICULTY_RANK = {difficulty.casefold(): index for index, difficulty in enumerate(DIFFICULTY_ORDER)}
RADAR_FIELDS = ("Stream", "Voltage", "Air", "Freeze", "Chaos", "Notes",
                "TapsAndHolds", "Jumps", "Holds", "Mines", "Hands", "Rolls",
                "Lifts", "Fakes")
RADAR_COUNT_FIELDS = {
    "jumps": "Jumps",
    "holds": "Holds",
    "rolls": "Rolls",
    "mines": "Mines",
    "hands": "Hands",
    "lifts": "Lifts",
    "taps": "Taps/Holds",
}
TAP_FIELDS = ("W1", "W2", "W3", "W4", "W5", "Miss")

HEADERS = ("Title", "Subtitle", "Artist", "Pack", "Type", "Difficulty", "Meter", "Time", "BPM", "Chart", "Score",
           "Grade", "Best %", "Plays", "Last played", "Peak NPS", "Taps/Holds", "Jumps",
           "Holds", "Rolls", "Mines", "Hands", "Lifts", "W1", "W2", "W3", "W4", "W5",
           "Miss", "Max combo", *TECH_FIELDS)
NUMERIC_COLUMNS = {"Meter", "Time", "Score", "Best %", "Plays", "Peak NPS", "Taps/Holds", "Jumps",
                   "Holds", "Rolls", "Mines", "Hands", "Lifts", "W1", "W2", "W3", "W4",
                   "W5", "Miss", "Max combo", *TECH_FIELDS}
# The groups shown under View > Columns, in menu order. Every column in HEADERS belongs to exactly one group.
COLUMN_GROUPS = {
    "Song & chart": ("Title", "Subtitle", "Artist", "Pack", "Type", "Difficulty", "Meter", "Time", "BPM", "Chart"),
    "Score": ("Score", "Grade", "Best %", "Plays", "Last played", "Max combo"),
    "Tap judgments": TAP_FIELDS,
    "Chart counts": ("Peak NPS", "Taps/Holds", "Jumps", "Holds", "Rolls", "Mines", "Hands", "Lifts"),
    "Tech counts": TECH_FIELDS,
}
# Groups whose columns are shown on a fresh install and after "Reset column layout".
DEFAULT_VISIBLE_GROUPS = ("Song & chart", "Score")
# Subtitle is the one exception to the rule that every column of a default
# group starts shown: it belongs to "Song & chart" but starts hidden
# (issue #49, option B), opt-in via View -> Columns.
DEFAULT_VISIBLE_COLUMNS = frozenset(
    column for group in DEFAULT_VISIBLE_GROUPS for column in COLUMN_GROUPS[group]) - {"Subtitle"}
GRADE_NAMES = {
    "Tier01": "★★★★", "Tier02": "★★★", "Tier03": "★★", "Tier04": "★",
    "Tier05": "S+", "Tier06": "S", "Tier07": "S-", "Tier08": "A+",
    "Tier09": "A", "Tier10": "A-", "Tier11": "B+", "Tier12": "B",
    "Tier13": "B-", "Tier14": "C+", "Tier15": "C", "Tier16": "C-", "Tier17": "D",
}
GRADE_OPTIONS = tuple(GRADE_NAMES.values())
# Best grade first (low index). Accept both Tier keys and display labels.
GRADE_RANK = {name.casefold(): index for index, name in enumerate(GRADE_NAMES.values())}
GRADE_RANK.update({tier.casefold(): index for index, tier in enumerate(GRADE_NAMES)})


# GRADE_RANK and DIFFICULTY_RANK are intentionally omitted here:
# they are consumed only by library_format.
__all__ = [
    "COLUMN_GROUPS",
    "DEFAULT_VISIBLE_COLUMNS",
    "DEFAULT_VISIBLE_GROUPS",
    "DIFFICULTY_ORDER",
    "GRADE_NAMES",
    "GRADE_OPTIONS",
    "HEADERS",
    "NUMERIC_COLUMNS",
    "RADAR_COUNT_FIELDS",
    "RADAR_FIELDS",
    "TAP_FIELDS",
    "TECH_FIELDS",
]
