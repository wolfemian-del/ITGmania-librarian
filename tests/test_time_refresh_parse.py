"""Tests for the pass-4 timing tool (tools/time_refresh_parse.py).

The tool is loaded from its file (it is a developer tool, not a
shipped module): the tests pin the Revision 1 behaviours — the
startup measurement starts every worker, --cold runs one worker
count per invocation, and the aggregate RSS covers the pool's
workers, not just the parent — and the Revision 2 parent-RSS fix,
which opens a real handle on Windows instead of the pseudo-handle.
"""

import importlib.util
import io
import multiprocessing
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent

_spec = importlib.util.spec_from_file_location(
    "time_refresh_parse", ROOT / "tools" / "time_refresh_parse.py")
tool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tool)


def _cache_text(song, difficulty="Hard", charts=1):
    text = (f"#SONGFILENAME:Songs/{song}/audio.ogg;\n"
            f"#TITLE:{song.split('/')[-1]};\n")
    for _ in range(charts):
        text += ("#NOTEDATA:;\n#STEPSTYPE:dance-single;\n"
                 f"#DIFFICULTY:{difficulty};\n")
    return text


class _RecordingExecutor:
    """Records submits; any use runs nothing."""

    def __init__(self, *args, **kwargs):
        self.submitted = []

    def submit(self, fn, *args):
        self.submitted.append((fn, args))

        class _Done:
            def result(self):
                return None

        return _Done()

    def shutdown(self, wait=True, cancel_futures=False):
        pass


class StartupMeasurementTests(unittest.TestCase):
    def test_measure_pool_startup_submits_one_task_per_worker(self):
        # The executor spawns its workers lazily, one per submitted
        # task, so a single submit only times one worker (Greptile
        # finding 2, Revision 1): the measurement must submit one
        # task per worker and wait for all of them.
        with tempfile.TemporaryDirectory() as directory:
            cache_dir = Path(directory)
            (cache_dir / "a.cache").write_text(
                _cache_text("Pack/A"), encoding="utf-8")
            created = []

            class Recording(_RecordingExecutor):
                def __init__(self, *args, **kwargs):
                    super().__init__(*args, **kwargs)
                    created.append(self)

            with patch.object(tool, "ProcessPoolExecutor", Recording):
                seconds = tool._measure_pool_startup(cache_dir, {}, 3)
            self.assertEqual(len(created), 1)
            self.assertEqual(len(created[0].submitted), 3)
            self.assertGreaterEqual(seconds, 0.0)


class ColdRunTests(unittest.TestCase):
    def _fixture(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        cache_dir = root / "Cache"
        cache_dir.mkdir()
        for name, song in (("a.cache", "Pack/A"), ("b.cache", "Pack/B"),
                           ("c.cache", "Pack/C")):
            (cache_dir / name).write_text(_cache_text(song), encoding="utf-8")
        stats_file = root / "Stats.xml"
        stats_file.write_text("<Stats/>", encoding="utf-8")
        return cache_dir, stats_file

    def test_cold_without_workers_flag_errors(self):
        # --cold runs one worker count per invocation: a second count
        # in the same invocation would read warmed file contents and
        # still be labeled cold (Greptile finding 3, Revision 1).
        cache_dir, stats_file = self._fixture()
        err = io.StringIO()
        with redirect_stderr(err):
            with self.assertRaises(SystemExit) as caught:
                tool.main([str(cache_dir), str(stats_file), "--cold"])
        self.assertEqual(caught.exception.code, 2)
        self.assertIn("--workers", err.getvalue())

    def test_cold_with_workers_runs_one_count(self):
        cache_dir, stats_file = self._fixture()
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(
                tool.main([str(cache_dir), str(stats_file),
                           "--cold", "--workers", "8"]), 0)
        lines = [line for line in out.getvalue().splitlines()
                 if line.startswith("pass 4 (cold,")]
        self.assertEqual(len(lines), 1)
        self.assertIn("8 workers", lines[0])

    def test_workers_flag_selects_one_count_warm(self):
        cache_dir, stats_file = self._fixture()
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(
                tool.main([str(cache_dir), str(stats_file),
                           "--workers", "4"]), 0)
        lines = [line for line in out.getvalue().splitlines()
                 if line.startswith("pass 4 (warm,")]
        self.assertEqual(len(lines), 1)
        self.assertIn("4 workers", lines[0])


class AggregateRssTests(unittest.TestCase):
    def test_child_rss_finds_a_live_child(self):
        # The aggregate sampler lists this process's children; a
        # live child must appear with a positive RSS. Skipped where
        # child enumeration is unavailable (macOS).
        if tool._child_pids() is None:
            self.skipTest("child enumeration unavailable on this platform")
        ctx = multiprocessing.get_context("spawn")
        child = ctx.Process(target=time.sleep, args=(5,))
        child.start()
        try:
            deadline = time.time() + 5
            found = None
            while time.time() < deadline:
                found = tool._child_pids()
                if child.pid in found:
                    break
                time.sleep(0.05)
            self.assertIn(child.pid, found or [])
            rss = tool._current_rss_bytes(child.pid)
            self.assertIsNotNone(rss)
            self.assertGreater(rss, 0)
        finally:
            child.terminate()
            child.join()

    def test_run_pool_pass_reports_aggregate_rss(self):
        # The aggregate is the parent + workers peak the sampler saw
        # (Revision 1, Lane D Q5), not the parent peak alone. On a
        # tiny fixture the run may be too fast for the sampler to
        # catch a worker, so the pin is presence, not size.
        if tool._child_pids() is None:
            self.skipTest("child enumeration unavailable on this platform")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache_dir = root / "Cache"
            cache_dir.mkdir()
            for name, song in (("a.cache", "Pack/A"), ("b.cache", "Pack/B")):
                (cache_dir / name).write_text(_cache_text(song),
                                              encoding="utf-8")
            stats_file = root / "Stats.xml"
            stats_file.write_text("<Stats/>", encoding="utf-8")
            _rows, _files, _counts, _seconds, _startup, peak, aggregate, \
                _entries, _pickled = tool.run_pool_pass(
                    cache_dir, stats_file, workers=2)
            self.assertIsNotNone(aggregate)
            self.assertGreater(aggregate, 0)
            self.assertIsNotNone(peak)


class _FakeKernel32:
    """Records handle calls; OpenProcess answers for one PID only."""

    def __init__(self):
        self.get_current_process_calls = 0
        self.opened = []
        self.closed = []

    def GetCurrentProcessId(self):
        return 1234

    def GetCurrentProcess(self):
        self.get_current_process_calls += 1
        return -1

    def OpenProcess(self, access, inherit, pid):
        self.opened.append((access, inherit, pid))
        return 5678 if pid == 1234 else 0

    def CloseHandle(self, handle):
        self.closed.append(handle)
        return True


class _FakePsapi:
    """Fails the -1 pseudo-handle; answers a real handle with a peak."""

    def __init__(self):
        self.seen_handles = []

    def GetProcessMemoryInfo(self, handle, counters, cb):
        self.seen_handles.append(handle)
        if handle == -1:
            return 0
        # counters arrives as a byref pointer; _obj is the struct.
        counters._obj.PeakWorkingSetSize = 42424224
        return 1


class _FakeWindll:
    def __init__(self, kernel32, psapi):
        self.kernel32 = kernel32
        self.psapi = psapi


class ParentRssWindowsTests(unittest.TestCase):
    def test_parent_peak_opens_a_real_handle_not_the_pseudo_handle(self):
        # GetCurrentProcess() returns the -1 pseudo-handle, which an
        # untyped ctypes call truncates to 32 bits on 64-bit Windows,
        # so GetProcessMemoryInfo fails and the parent peak reads as
        # unavailable (owner's warm pass 4, Revision 2). The reader
        # must open a real handle on its own PID instead. The fake
        # windll runs on Linux: resource is hidden so the function
        # takes the Windows branch, and the platform is faked.
        kernel32 = _FakeKernel32()
        psapi = _FakePsapi()
        windll = _FakeWindll(kernel32, psapi)
        with patch.object(sys, "platform", "win32"), \
                patch.dict(sys.modules, {"resource": None}), \
                patch.object(tool.ctypes, "windll", windll, create=True):
            self.assertEqual(tool._peak_rss_bytes(), 42424224)
        self.assertEqual(kernel32.get_current_process_calls, 0)
        self.assertEqual(kernel32.opened, [(0x0400 | 0x0010, False, 1234)])
        self.assertEqual(kernel32.closed, [5678])
        self.assertEqual(psapi.seen_handles, [5678])


if __name__ == "__main__":
    unittest.main()
