"""Run: python -m unittest -v test_retinotopy.py (PsychoPy not required)."""
import csv
import json
from pathlib import Path
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
import retinotopy_psychopy as r


class ProtocolTests(unittest.TestCase):
    def test_all_606_subject_run_schedules(self):
        for subject in range(101):
            for run in range(1, 7):
                rows, dropped = r.load_orders(r.ROOT / "assets", subject, run)
                self.assertEqual(rows.shape, (4500, 3))
                self.assertEqual(dropped, 0)
                self.assertEqual(np.flatnonzero(rows[:, 0] >= 0)[0], 240 if run < 3 else 330)

    def test_trimming_keeps_orders_aligned(self):
        for run in range(1, 7):
            full, _ = r.load_orders(r.ROOT / "assets", 0, run)
            short, drop = r.load_orders(r.ROOT / "assets", 0, run, 2)
            self.assertEqual(drop, (240 if run < 3 else 330)-30)
            np.testing.assert_array_equal(short, full[drop:])
            self.assertEqual(np.flatnonzero(short[:, 0] >= 0)[0], 30)

    def test_schedule_has_no_accumulated_drift(self):
        for hz in (60, 75, 120, 144, 59.94):
            seen = {}
            for frame in range(int(300*hz)+2):
                time = frame/hz
                index = r.schedule_index(time, 1/hz)
                seen.setdefault(index, time)
            for step in range(4501):
                self.assertLessEqual(abs(seen[step]-step/15), .501/hz)

    def test_geometry_and_clamping(self):
        diameter, eccentricity = r.geometry(1920, 1080, 60, 50)
        self.assertAlmostEqual(eccentricity, 15)
        self.assertLess(diameter, 1080)
        diameter, eccentricity = r.geometry(1920, 1080, 30, 50)
        self.assertEqual(diameter, 1080)
        self.assertLess(eccentricity, 15)

    def test_rgba_preserves_pixels_and_mask_polarity(self):
        pattern = np.array([[[255, 0, 0], [0, 255, 0]], [[0, 0, 255], [64, 64, 64]]], dtype=np.uint8)
        mask = np.array([[0, 255], [128, 64]], dtype=np.uint8)
        result = np.array(r.compose(pattern, mask, np.zeros((2, 2, 4), dtype=np.uint8)))
        np.testing.assert_array_equal(result[:, :, :3], pattern)
        np.testing.assert_array_equal(result[:, :, 3], mask)

    def test_invalid_values_rejected(self):
        for argv in (["--duration", "0"], ["--screen-width", "nan"], ["--viewing-distance", "-1"],
                     ["--trigger", "escape"], ["--lead-in", "inf"]):
            with self.assertRaises(ValueError):
                r.validate_args(r.parse_args(argv))
        with self.assertRaises(FileNotFoundError):
            r.load_orders(r.ROOT / "assets", 999, 1)


class RuntimeTests(unittest.TestCase):
    """Synthetic display tests exercise control flow; they do not validate hardware."""
    def simulate(self, output, stall=False, abort=False):
        state = SimpleNamespace(time=0., started=False, frames=0, key_started=False)
        class Clock:
            def __init__(self): self.zero = state.time
            def reset(self): self.zero = state.time
            def getTime(self): return state.time-self.zero
        class Window:
            def __init__(self, **kw):
                self.size = (1024, 768)
                self.nDroppedFrames = 0
                self.callbacks = []
            def flip(self):
                state.time += 1/60
                if state.started:
                    state.frames += 1
                    if stall and state.frames == 3: state.time += .2
                for cb in self.callbacks: cb()
                self.callbacks = []
                return state.time
            def callOnFlip(self, cb):
                state.started = True
                self.callbacks.append(cb)
            def getActualFrameRate(self, **kw): return 60.
            def getFutureFlipTime(self, **kw): return state.time+1/60
            def close(self): pass
        class Stim:
            def __init__(self, *args, **kw): pass
            def draw(self): pass
            def setImage(self, *args, **kw): pass
        class Keyboard:
            def __init__(self, clock): self.clock=clock
            def clearEvents(self): pass
            def getKeys(self, keyList=None, **kw):
                if keyList: return []
                if not state.key_started:
                    state.key_started = True
                    return [SimpleNamespace(name="space", rt=self.clock.getTime())]
                if abort and state.frames == 5:
                    return [SimpleNamespace(name="escape", rt=self.clock.getTime())]
                return []
        psychopy = ModuleType("psychopy")
        psychopy.__version__ = "synthetic-test"
        psychopy.core = SimpleNamespace(Clock=Clock, wait=lambda _: None)
        psychopy.event = SimpleNamespace(Mouse=lambda **kw: SimpleNamespace(getPressed=lambda: [False]*3))
        psychopy.gui = SimpleNamespace()
        psychopy.monitors = SimpleNamespace(Monitor=lambda *a, **kw: None)
        psychopy.visual = SimpleNamespace(Window=Window, TextStim=Stim, ImageStim=Stim, Circle=Stim)
        hardware = ModuleType("psychopy.hardware")
        hardware.keyboard = SimpleNamespace(Keyboard=Keyboard)
        with patch.dict("sys.modules", {"psychopy": psychopy, "psychopy.hardware": hardware}):
            a = r.parse_args(["--no-dialog", "--windowed", "--lead-in", "0", "--duration", "0.6",
                              "--output", str(output)])
            r.run_experiment(a)
        meta = json.loads(next(output.glob("*_session.json")).read_text())
        with next(output.glob("*_steps.csv")).open() as f:
            steps = list(csv.DictReader(f))
        return meta, steps

    def test_full_last_step_and_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            meta, steps = self.simulate(Path(tmp))
        self.assertEqual(meta["status"], "completed")
        self.assertEqual(meta["presented_steps"], 9)
        self.assertEqual(meta["skipped_steps"], 0)
        self.assertAlmostEqual(meta["actual_duration_s"], .6)
        self.assertAlmostEqual(float(steps[-1]["actual_onset_s"]), 8/15)

    def test_stall_is_logged_and_schedule_catches_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            meta, steps = self.simulate(Path(tmp), stall=True)
        self.assertGreater(meta["skipped_steps"], 0)
        self.assertAlmostEqual(meta["actual_duration_s"], .6)
        self.assertTrue(any(s["status"] == "skipped" for s in steps))

    def test_escape_saves_partial_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            meta, steps = self.simulate(Path(tmp), abort=True)
        self.assertEqual(meta["status"], "aborted")
        self.assertLess(meta["actual_duration_s"], .6)
        self.assertTrue(any(s["status"] == "not_presented" for s in steps))


if __name__ == "__main__":
    unittest.main()
