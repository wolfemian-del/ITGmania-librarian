"""The launcher pin: launch.py must hand over to the package's main."""

import runpy
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from itgmania_library import library_librarian

ROOT = Path(__file__).resolve().parent.parent


class LaunchTests(unittest.TestCase):
    def test_launch_runs_the_package_main(self):
        # The import lives inside the __main__ guard, so run the file
        # as __main__ with the package main stubbed: the stub is what
        # the guarded import binds, and the guard calls it.
        recorder = Mock()
        with patch.object(library_librarian, "main", recorder):
            runpy.run_path(ROOT / "launch.py", run_name="__main__")
        recorder.assert_called_once_with()

    def test_launch_as_mp_main_imports_no_ui(self):
        # A spawn child re-imports launch.py as __mp_main__; it must
        # not pull in the UI module or Tkinter (ChatGPT-6 follow-up 1,
        # Revision 1). Run in a subprocess so the check sees a fresh
        # interpreter, the way a worker does.
        code = (
            "import runpy, sys;"
            " runpy.run_path('launch.py', run_name='__mp_main__');"
            " print('tkinter' in sys.modules);"
            " print('itgmania_library.library_librarian' in sys.modules)"
        )
        out = subprocess.run(
            [sys.executable, "-c", code], cwd=ROOT, capture_output=True,
            text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip().splitlines(),
                         ["False", "False"])
