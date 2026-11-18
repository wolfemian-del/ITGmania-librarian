"""The launcher pin: launch.py must hand over to the package's main."""

import runpy
import unittest
from pathlib import Path

from itgmania_library import library_librarian

ROOT = Path(__file__).resolve().parent.parent


class LaunchTests(unittest.TestCase):
    def test_launch_runs_the_package_main(self):
        self.assertIs(
            runpy.run_path(ROOT / "launch.py", run_name="x")["main"],
            library_librarian.main,
        )
