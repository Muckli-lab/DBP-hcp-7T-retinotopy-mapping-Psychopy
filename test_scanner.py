"""Synthetic scanner tests. These do not certify physical scanner/display timing."""
import csv
import json
import struct
from pathlib import Path
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

import retinotopy_scanner as r
from scanner_input import ScannerInput


class FakeDPx:
    def __init__(self, initial=31, selected=True, error=0, ram_unit=2):
        self.ram_unit = ram_unit
        self.raw = initial
        self.selected = selected
        self.time = 100.
        self._rows = []
        self.running = False
        self.closed = False
        self.debounce_disabled = False
        self.error = error
        self.pending_override = None

    def DPxOpen(self): pass
    def DPxSelectDevice(self, name): return int(self.selected)
    def DPxClose(self): self.closed = True
    def DPxUpdateRegCache(self): pass
    def DPxGetTime(self): return self.time
    def DPxGetError(self): return self.error
    def DPxGetDinValue(self): return self.raw
    def DPxDisableDinLogEvents(self): self.running = False
    def DPxEnableDinLogEvents(self): self.running = True
    def DPxIsDinLogEvents(self): return self.running
    def DPxIsDoutDinLoopback(self): return False
    def DPxGetDinDataDir(self): return 0
    def DPxGetRamSize(self): return 32_000_000
    def DPxEnableDinLogTimetags(self): pass
    def DPxEnableDinStabilize(self): pass
    def DPxDisableDinDebounce(self): self.debounce_disabled = True
    def DPxSetDinBuff(self, base, size):
        self.base, self.size, self.offset = base, size, 0
        self.memory = bytearray(size)
    @property
    def rows(self):
        return self._rows
    @rows.setter
    def rows(self, events):
        self._rows = events
        for t, bits in events:
            struct.pack_into("<QH", self.memory, self.offset, round(t * 1e9), bits)
            self.offset = (self.offset + 10) % self.size
    def DPxGetDinBuffWriteAddr(self):
        if self.pending_override is not None:
            return self.base + self.pending_override * 10
        return self.base + self.offset
    def DPxReadRam(self, addr, length):
        if length % 2:
            self.error = "DPX_ERR_RAM_READ_LEN_ODD"
            return b""
        start = addr - self.base
        end = start + length * self.ram_unit
        assert 0 <= start < end <= self.size
        raw = self.memory[start:end]
        return np.frombuffer(raw, dtype="<u2") if self.ram_unit == 2 else bytes(raw)


class InputTests(unittest.TestCase):
    def device(self, initial=31, error=0, ram_unit=2, **kwargs):
        fake = FakeDPx(initial, error=error, ram_unit=ram_unit)
        module = ModuleType("pypixxlib")
        module._libdpx = fake
        with patch.dict("sys.modules", {"pypixxlib": module}):
            scanner = ScannerInput(**kwargs)
        self.addCleanup(scanner.close)
        scanner.arm()
        return fake, scanner

    def test_symbolic_success_during_connect_arm_and_read(self):
        fake, scanner = self.device(error="DPX_SUCCESS")
        fake.rows = [(100.01, 15)]
        self.assertEqual(scanner.read()[0]["kind"], "trigger")
        fake.error = "DPX_ERR_USB"
        with self.assertRaisesRegex(RuntimeError, "DPX_ERR_USB"):
            scanner.read()

    def test_monitor_reports_unassigned_line_and_both_edges(self):
        fake, scanner = self.device()
        fake.rows = [(100.001, 31 | (1 << 12)), (100.002, 31)]
        self.assertEqual([(e["key"], e["kind"]) for e in scanner.read(monitor_all=True)],
                         [("DIN12", "rising"), ("DIN12", "falling")])

    def test_short_pulse_and_release_in_same_batch_are_retained(self):
        fake, scanner = self.device()
        fake.rows = [(100.001, 15), (100.0011, 31)]
        events = scanner.read()
        self.assertEqual([e["kind"] for e in events], ["trigger", "trigger_release"])
        self.assertEqual([e["device_time_s"] for e in events], [100.001, 100.0011])
        self.assertTrue(fake.debounce_disabled)

    def test_multiple_pulses_and_box_response_are_not_collapsed(self):
        fake, scanner = self.device()
        fake.rows = [(100.001, 15), (100.002, 31), (100.003, 15),
                     (100.004, 31), (100.005, 30), (100.006, 31)]
        events = scanner.read()
        self.assertEqual([e["kind"] for e in events],
                         ["trigger", "trigger_release", "trigger", "trigger_release", "boxpress", "boxrelease"])
        self.assertEqual(events[-2]["key"], "red")

    def test_active_input_at_arming_requires_release_then_fresh_edge(self):
        fake, scanner = self.device(initial=15)
        self.assertEqual(scanner.read(), [])
        fake.rows = [(100.001, 15), (100.002, 31), (100.003, 15)]
        events = scanner.read()
        self.assertEqual([e["kind"] for e in events], ["trigger_release", "trigger"])
        self.assertEqual(events[-1]["device_time_s"], 100.003)

    def test_stale_log_rows_do_not_revert_the_arm_snapshot(self):
        fake, scanner = self.device(initial=15)
        fake.rows = [(99.9, 31), (100., 31), (100.001, 15)]
        self.assertEqual(scanner.read(), [])
        fake.rows = [(100.002, 31), (100.003, 15)]
        self.assertEqual([e["kind"] for e in scanner.read()], ["trigger_release", "trigger"])

    def test_wrap_preserves_both_edges(self):
        fake, scanner = self.device()
        fake.offset = scanner.read_offset = fake.size - 10
        fake.rows = [(100.001, 15), (100.002, 31)]
        self.assertEqual([e["kind"] for e in scanner.read()], ["trigger", "trigger_release"])
        self.assertEqual(scanner.read(), [])

    def test_single_and_simultaneous_button_edges_in_both_ram_formats(self):
        for unit in (1, 2):
            with self.subTest(unit=unit):
                fake, scanner = self.device(ram_unit=unit)
                fake.offset = scanner.read_offset = fake.size - 10
                for t, bits, expected in [(100.1, 30, ["boxpress"]),
                                          (100.2, 31, ["boxrelease"]),
                                          (100.3, 14, ["boxpress", "trigger"])]:
                    fake.rows = [(t, bits)]
                    result = scanner.read()
                    self.assertEqual([e["kind"] for e in result], expected)
                    self.assertEqual([e["device_time_s"] for e in result], [t] * len(expected))
                    self.assertEqual(scanner.read(), [])

    def test_device_error_identifies_first_arming_call(self):
        fake, scanner = self.device()
        fake.DPxEnableDinLogTimetags = lambda: setattr(fake, "error", "DPX_ERR_USB_SYSDEVSEL_INDEX")
        with self.assertRaisesRegex(RuntimeError, "DPxEnableDinLogTimetags.*DPX_ERR_USB_SYSDEVSEL_INDEX"):
            scanner.arm()

    def test_raw_zero_uses_bit_values_without_binary_string_errors(self):
        fake, scanner = self.device()
        fake.rows = [(100.001, 0)]
        events = scanner.read()
        self.assertEqual(sum(e["kind"] == "trigger" for e in events), 1)
        self.assertEqual(sum(e["kind"] == "boxpress" for e in events), 4)

    def test_high_polarity_and_different_trigger_bit(self):
        fake, scanner = self.device(initial=15, trigger_bit=7, trigger_level=1)
        fake.rows = [(100.001, 143), (100.002, 15)]
        self.assertEqual([e["kind"] for e in scanner.read()], ["trigger", "trigger_release"])

    def test_missing_device_closes_connection(self):
        fake = FakeDPx(selected=False)
        module = ModuleType("pypixxlib")
        module._libdpx = fake
        with patch.dict("sys.modules", {"pypixxlib": module}):
            with self.assertRaisesRegex(RuntimeError, "not found"):
                ScannerInput()
        self.assertTrue(fake.closed)

    def test_stopped_logging_and_nearly_full_buffer_fail_explicitly(self):
        fake, scanner = self.device()
        fake.running = False
        with self.assertRaisesRegex(RuntimeError, "stopped"):
            scanner.read()
        fake.running = True
        fake.pending_override = 9000
        with self.assertRaisesRegex(RuntimeError, "nearly full"):
            scanner.read()

    def test_error_during_log_transfer_rejects_returned_events(self):
        fake, scanner = self.device()
        fake.rows = [(100.001, 15)]
        original_read = fake.DPxReadRam
        def failed_transfer(status, count):
            rows = original_read(status, count)
            fake.error = 77
            return rows
        fake.DPxReadRam = failed_transfer
        with self.assertRaisesRegex(RuntimeError, "77"):
            scanner.read()

    def test_invalid_gui_values_are_rejected_after_parsing(self):
        for field, value in (("trigger_bit", 16), ("trigger_bit", -1),
                             ("trigger_level", 2),):
            with self.subTest(field=field, value=value):
                arguments = r.parse_args([])
                setattr(arguments, field, value)
                with self.assertRaises(ValueError):
                    r.validate_args(arguments)


class GamepadTests(unittest.TestCase):
    def test_sdl_button_mapping_and_device_filter(self):
        from gmpd3_input import Gamepad
        pad = Gamepad.__new__(Gamepad)
        pad.instance = 7
        events = [SimpleNamespace(instance_id=7, type=1, button=i) for i in range(6)]
        events.extend([SimpleNamespace(instance_id=9, type=1, button=1),
                       SimpleNamespace(instance_id=7, type=2, button=1)])
        pad.pg = SimpleNamespace(JOYBUTTONDOWN=1, JOYDEVICEREMOVED=3,
                                 event=SimpleNamespace(get=lambda: events))
        self.assertEqual(pad.read(), ["Y", "B", "X", "LT", "A", "RT"])


class RuntimeTests(unittest.TestCase):
    """Use independent fake host/device clocks, never real PsychoPy or USB."""
    def simulate(self, output, preview=False, abort_wait=False, abort_run=False, batch_start=False, connect_error=False, keyboard_ttl=False):
        state = SimpleNamespace(time=0., started=False, frames=0, key_started=False,
                                scanner_reads=0, closed=False, scanner_closed=False,
                                resets=[], scans_at_start=None, sent_frames=set())

        class Clock:
            def __init__(self): self.zero = state.time
            def reset(self):
                self.zero = state.time
                state.resets.append(state.time)
            def getTime(self): return state.time-self.zero

        class Window:
            def __init__(self, **kwargs):
                self.size = np.array([1920, 1080], dtype=np.int64)
                self.nDroppedFrames = 0
                self.callbacks = []
            def flip(self):
                state.time += 1/60
                if state.started:
                    state.frames += 1
                for callback in self.callbacks:
                    callback()
                self.callbacks = []
                return state.time
            def callOnFlip(self, callback):
                state.started = True
                state.scans_at_start = state.scanner_reads
                self.callbacks.append(callback)
            def getActualFrameRate(self, **kwargs): return 60.
            def getFutureFlipTime(self, **kwargs): return state.time+1/60
            def close(self): state.closed = True

        class Stim:
            def __init__(self, *args, **kwargs): pass
            def draw(self): pass
            def setImage(self, *args, **kwargs): pass

        class Keyboard:
            def __init__(self, clock): self.clock = clock
            def clearEvents(self): pass
            def getKeys(self, keyList=None, **kwargs):
                if keyList:
                    return []
                if keyboard_ttl and not state.started:
                    return [SimpleNamespace(name="5", rt=self.clock.getTime())]
                if not state.key_started:
                    state.key_started = True
                    return [SimpleNamespace(name="space", rt=self.clock.getTime())]
                if abort_wait and not state.started and state.scanner_reads >= 4:
                    return [SimpleNamespace(name="escape", rt=self.clock.getTime())]
                if abort_run and state.frames == 5:
                    return [SimpleNamespace(name="escape", rt=self.clock.getTime())]
                return []

        class Scanner:
            package_version = "synthetic"
            log_backend = "synthetic"
            def __init__(self, *args):
                if connect_error:
                    raise RuntimeError("simulated controller failure")
                self.max_pending = np.int64(0)
                self.sync = None
            def arm(self):
                self.armed_time = 100+state.time
            def read(self):
                state.scanner_reads += 1
                self.sync = dict(device_time_s=100+state.time, host_before_s=state.time-.0001,
                                 host_after_s=state.time+.0001)
                events = []
                def item(kind, when, key="scanner"):
                    return dict(kind=kind, device_time_s=100+when, host_detected_s=state.time,
                                key=key, raw_din=15 if kind == "trigger" else 31)
                if not state.started and not abort_wait:
                    if batch_start and state.scanner_reads == 3:
                        for offset in (-.0008, -.0005, -.0002):
                            events += [item("trigger", state.time+offset),
                                       item("trigger_release", state.time+offset+.0001)]
                    elif not batch_start and state.scanner_reads in (3, 4, 5):
                        events += [item("trigger", state.time-.0002),
                                   item("trigger_release", state.time-.0001)]
                if state.started and state.frames not in state.sent_frames:
                    state.sent_frames.add(state.frames)
                    if state.frames in (3, 8, 12):
                        events += [item("trigger", state.time-.0002), item("trigger_release", state.time-.0001)]
                    if state.frames == 5:
                        events.append(item("boxpress", state.time-.001, "red"))
                self.max_pending = max(self.max_pending, len(events))
                return events
            def close(self): state.scanner_closed = True

        psychopy = ModuleType("psychopy")
        psychopy.__version__ = "synthetic-test"
        psychopy.core = SimpleNamespace(Clock=Clock, wait=lambda duration: setattr(state, "time", state.time+duration))
        psychopy.event = SimpleNamespace(Mouse=lambda **kwargs: SimpleNamespace(getPressed=lambda: [False]*3))
        psychopy.gui = SimpleNamespace()
        psychopy.monitors = SimpleNamespace(Monitor=lambda *args, **kwargs: None)
        psychopy.visual = SimpleNamespace(Window=Window, TextStim=Stim, ImageStim=Stim, Circle=Stim)
        hardware = ModuleType("psychopy.hardware")
        hardware.keyboard = SimpleNamespace(Keyboard=Keyboard)
        class Pad:
            name = "simulated GMPD3"
            index = 0
            def __init__(self, index): pass
            def read(self):
                return ["A"] if state.started and state.frames == 5 else []
            def close(self): pass

        scanner_module = ModuleType("scanner_input")
        scanner_module.ScannerInput = Scanner
        rows = np.array([[-1, 0, 0 if index < 2 else 1] for index in range(9)], dtype=np.int32)
        arguments = ["--no-dialog", "--windowed", "--duration", "0.6", "--skip-triggers", "2",
                     "--output", str(output)]
        if connect_error:
            arguments.remove("--windowed")
        if preview:
            arguments.append("--keyboard-preview")
        if keyboard_ttl:
            arguments += ["--no-vpixx", "--trigger", "5"]
        modules = {"psychopy": psychopy, "psychopy.hardware": hardware, "scanner_input": scanner_module,
                   "gmpd3_input": SimpleNamespace(Gamepad=Pad)}
        with patch.dict("sys.modules", modules), patch.object(r, "perf_counter", side_effect=lambda: state.time), \
                patch.object(r, "load_orders", return_value=(rows, 0)), \
                patch.object(r, "preload", return_value=({}, {}, Image.new("RGBA", (768, 768)))):
            r.run_experiment(r.parse_args(arguments))
        result = {"meta": json.loads(next(output.glob("*_session.json")).read_text()), "state": state}
        for label in ("steps", "responses", "flips", "scanner"):
            paths = list(output.glob(f"*_{label}.csv"))
            if paths:
                with paths[0].open() as stream:
                    result[label] = list(csv.DictReader(stream))
        return result

    def test_fullscreen_failure_saves_numeric_metadata_and_original_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(RuntimeError, "simulated controller failure"):
                self.simulate(Path(tmp), connect_error=True)
            meta = json.loads(next(Path(tmp).glob("*_session.json")).read_text())
            self.assertEqual(meta["status"], "error")
            self.assertIsInstance(meta["stimulus_diameter_px"], int)
            self.assertIn("simulated controller failure", meta["error"])

    def test_start_on_pulse_n_plus_one_and_later_triggers_do_not_reset(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.simulate(Path(tmp))
        pulses = [event for event in result["scanner"] if event["kind"] == "trigger"]
        self.assertEqual([event["role"] for event in pulses[:3]], ["skipped", "skipped", "start"])
        self.assertTrue(all(event["role"] == "subsequent" for event in pulses[3:]))
        self.assertEqual(result["state"].scans_at_start, 5)  # Space arrived before any scanner pulse.
        self.assertEqual(len(result["state"].resets), 2)  # Waiting origin, then first presentation flip.
        self.assertEqual(float(pulses[2]["since_start_trigger_s"]), 0.)
        self.assertAlmostEqual(result["meta"]["actual_duration_s"], .6)
        self.assertEqual(result["meta"]["presented_steps"], 9)
        self.assertEqual(result["meta"]["skipped_steps"], 0)
        self.assertTrue(result["state"].scanner_closed)
        self.assertTrue(result["state"].closed)
        box = [event for event in result["responses"] if event["kind"] == "gmpd3_press"]
        self.assertEqual(len(box), 1)
        self.assertEqual(box[0]["timing_source"], "host_poll")
        self.assertEqual(box[0]["key"], "A")
        self.assertFalse(any(e["kind"].startswith("box") for e in result["scanner"]))
        self.assertGreater(result["meta"]["scanner_trigger_to_first_flip_s_estimate"], 0.)

    def test_several_pulses_in_start_batch_are_all_logged(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.simulate(Path(tmp), batch_start=True)
        pulses = [event for event in result["scanner"] if event["kind"] == "trigger"]
        self.assertEqual([event["role"] for event in pulses[:3]], ["skipped", "skipped", "start"])
        self.assertEqual(result["state"].scans_at_start, 3)
        self.assertEqual(result["meta"]["status"], "completed")

    def test_escape_while_waiting_saves_partial_run_and_closes_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.simulate(Path(tmp), abort_wait=True)
        self.assertEqual(result["meta"]["status"], "aborted")
        self.assertFalse(result["state"].started)
        self.assertTrue(result["state"].scanner_closed)
        self.assertTrue(result["state"].closed)
        self.assertEqual(result["scanner"], [])
        self.assertTrue(all(step["status"] == "not_presented" for step in result["steps"]))

    def test_escape_during_run_removes_stimulus_and_saves(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.simulate(Path(tmp), abort_run=True)
        self.assertEqual(result["meta"]["status"], "aborted")
        self.assertLess(result["meta"]["actual_duration_s"], .6)
        self.assertEqual(result["flips"][-1]["step_index"], "-1")
        self.assertTrue(result["state"].scanner_closed)

    def test_keyboard_scanner_start_and_gamepad(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.simulate(Path(tmp), keyboard_ttl=True)
        self.assertEqual(result["state"].scanner_reads, 0)
        self.assertEqual(result["meta"]["status"], "completed")
        self.assertEqual([e["key"] for e in result["responses"] if e["kind"] == "gmpd3_press"], ["A"])

    def test_keyboard_preview_runs_without_a_hardware_connection(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.simulate(Path(tmp), preview=True)
        self.assertEqual(result["state"].scanner_reads, 0)
        self.assertEqual(result["meta"]["status"], "completed")
        self.assertAlmostEqual(result["meta"]["actual_duration_s"], .6)
        self.assertIn("start_key_to_first_flip_s", result["meta"])
        self.assertNotIn("scanner", result)
        self.assertEqual([e["key"] for e in result["responses"] if e["kind"] == "gmpd3_press"], ["A"])


if __name__ == "__main__":
    unittest.main()
