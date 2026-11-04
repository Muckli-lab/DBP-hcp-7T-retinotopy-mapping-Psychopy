#!/usr/bin/env python3
"""PROPixx scanner version of the PsychoPy retinotopy port (GPL-3.0-only).

Upstream copyright (2026) Christophe Pallier <christophe@pallier.org>.
Port created 2026-09-28. See README.md for differences and validation limits.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from time import perf_counter

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent
UPSTREAM_COMMIT = "be2ea4de40c66ff0f59f04a27b9ff54412559713"
RUNS = ("RETBAR1", "RETBAR2", "RETCCW", "RETCW", "RETEXP", "RETCON")
RATE = 15.0
SIZE = 768
COLORS = ((255, 255, 255), (0, 0, 0), (255, 0, 0))
MASKS = {1: ("swippingBars", "bar", 1680), 2: ("swippingBars", "bar", 1680),
         3: ("rotatingWedge", "wedge", 480), 4: ("rotatingWedge", "wedge", 480),
         5: ("expendingCircles", "circle", 420), 6: ("expendingCircles", "circle", 420)}


def read_columns(path, columns):
    with Path(path).open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if not set(columns).issubset(reader.fieldnames or []):
            raise ValueError(f"Missing columns {columns} in {path}")
        result = [[] for _ in columns]
        for line, row in enumerate(reader, 2):
            for values, col in zip(result, columns):
                try:
                    values.append(int(row[col]))
                except (ValueError, TypeError) as exc:
                    raise ValueError(f"Invalid integer in {path}, line {line}, {col}") from exc
    return result


def load_orders(assets, subject, run, lead_in=-1, duration=None):
    if run not in MASKS or subject < 0:
        raise ValueError("Run must be 1-6 and subject must be a nonnegative integer.")
    order_dir = Path(assets) / "StimuliOrder"
    masks, = read_columns(order_dir / "maskOrderRetinotopy.csv", [RUNS[run-1]])
    patterns, dots = read_columns(order_dir / f"sub-{subject:03d}_stimuliOrderRetinotopy.csv",
                                  [f"run{run}_pattern", f"run{run}_dotColor"])
    if not masks or len({len(masks), len(patterns), len(dots)}) != 1:
        raise ValueError("Mask, pattern and dot schedules must be nonempty and equal length.")
    rows = np.column_stack((masks, patterns, dots)).astype(np.int32)
    for col, low, high in ((0, -1, MASKS[run][2]-1), (1, 0, 99), (2, 0, 2)):
        if np.any((rows[:, col] < low) | (rows[:, col] > high)):
            raise ValueError(f"Schedule column {col} contains out-of-range IDs.")
    blank = next((i for i, m in enumerate(masks) if m >= 0), len(masks))
    dropped = 0 if lead_in < 0 else max(0, blank - int(math.floor(lead_in*RATE + .5)))
    rows = rows[dropped:]
    if duration is not None:
        rows = rows[:max(1, int(math.floor(duration*RATE + .5)))]
    if not len(rows):
        raise ValueError("No stimulus steps remain after trimming.")
    return rows, dropped


def geometry(width_px, height_px, width_cm, distance_cm, eccentricity=15):
    """Flat-screen visual angle: radius = distance * tan(eccentricity)."""
    desired = 2 * distance_cm * math.tan(math.radians(eccentricity)) * width_px / width_cm
    diameter = min(desired, width_px, height_px)
    actual = math.degrees(math.atan((diameter/2) * width_cm/width_px / distance_cm))
    return diameter, actual


def schedule_index(predicted_elapsed, period):
    """Select the 15-Hz step at the nearest refresh; no accumulated 66-ms drift."""
    return max(0, int(math.floor((predicted_elapsed + period/2)*RATE + 1e-8)))


def load_pixels(path, mode):
    with Image.open(path) as im:
        if im.size != (SIZE, SIZE):
            raise ValueError(f"Expected {SIZE}x{SIZE} image: {path}; got {im.size}")
        return np.array(im.convert(mode), dtype=np.uint8)


def preload(assets, run, rows, progress=lambda msg: None):
    assets = Path(assets)
    patterns, masks = {}, {}
    visible = rows[rows[:, 0] >= 0]
    folder, prefix, _ = MASKS[run]
    tasks = [(patterns, int(i), assets / "patterns" / f"pattern_{i+1:04d}.png", "RGB")
             for i in np.unique(visible[:, 1])]
    tasks += [(masks, int(i), assets / "masks" / folder / f"{prefix}_{i+1:04d}.png", "L")
              for i in np.unique(visible[:, 0])]
    for n, (dest, i, path, mode) in enumerate(tasks):
        if n % 25 == 0:
            progress(f"Loading stimulus images: {n}/{len(tasks)}")
        dest[i] = load_pixels(path, mode)
    grid = np.full((SIZE, SIZE, 4), 255, dtype=np.uint8)
    grid[:, :, 3] = load_pixels(assets / "fixationGrid.png", "L")
    return patterns, masks, Image.fromarray(grid)


def compose(pattern, mask, buffer):
    """PIL retains top-to-bottom source orientation; PsychoPy flips on upload."""
    buffer[:, :, :3] = pattern
    buffer[:, :, 3] = mask
    return Image.fromarray(buffer)


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("-s", "--subject", type=int, default=0)
    p.add_argument("-r", "--run", type=int, choices=range(1, 7), default=1)
    p.add_argument("--assets", type=Path, default=ROOT / "assets")
    p.add_argument("--output", type=Path, default=ROOT / "data")
    p.add_argument("--screen-width", type=float, default=30, help="Physical full display width, cm")
    p.add_argument("--viewing-distance", type=float, default=50, help="Eye to display distance, cm")
    p.add_argument("--display", type=int, default=0)
    p.add_argument("--windowed", action="store_true", help="Uncalibrated 1024x768 preview")
    p.add_argument("--lead-in", type=float, default=-1, help="Negative keeps full baseline; preview: 2")
    p.add_argument("--duration", type=float, help="Preview duration, seconds (default: entire schedule)")
    p.add_argument("--keyboard-preview", dest="scanner", action="store_false",
                   help="Use keyboard start instead of PROPixx TTL (preview only)")
    p.set_defaults(scanner=True)
    p.add_argument("--trigger-bit", type=int, choices=range(16), default=4, help="Scanner DIN bit, zero based")
    p.add_argument("--trigger-level", type=int, choices=(0, 1), default=0, help="Active scanner level: 0=low, 1=high")
    p.add_argument("--button-level", type=int, choices=(0, 1), default=0, help="Active button-box level")
    p.add_argument("--skip-triggers", type=int, default=0, help="Ignore N fresh pulses, then start on pulse N+1")
    p.add_argument("--trigger", default="", help="Keyboard preview start key; blank uses Space")
    p.add_argument("--response-keys", default="", help="Comma-separated keys; blank: any non-trigger key")
    p.add_argument("--no-dialog", action="store_true")
    p.add_argument("--validate-only", action="store_true", help="Check schedule/assets without PsychoPy")
    a = p.parse_args(argv)
    return a


def validate_args(a):
    for name in ("screen_width", "viewing_distance"):
        v = getattr(a, name)
        if not math.isfinite(v) or v <= 0:
            raise ValueError(f"{name} must be finite and greater than zero.")
    if not math.isfinite(a.lead_in):
        raise ValueError("lead_in must be finite.")
    if a.duration is not None and (not math.isfinite(a.duration) or a.duration <= 0):
        raise ValueError("duration must be finite and greater than zero.")
    if a.subject < 0 or a.display < 0:
        raise ValueError("Subject and display must be nonnegative.")
    if a.skip_triggers < 0:
        raise ValueError("skip_triggers must be nonnegative.")
    if not 0 <= a.trigger_bit <= 15 or a.trigger_level not in (0, 1) or a.button_level not in (0, 1):
        raise ValueError("DIN bit must be 0-15; active levels must be 0 or 1.")
    a.trigger = a.trigger.strip().lower()
    if a.trigger == "escape":
        raise ValueError("Escape is reserved for ending the run.")


def save_csv(path, fields, rows):
    with Path(path).open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def run_experiment(a):
    try:
        import psychopy
        from psychopy import core, event, gui, monitors, visual
        from psychopy.hardware import keyboard
    except ImportError as exc:
        raise RuntimeError("Open this script in PsychoPy Coder and click Run. See README.md.") from exc

    if not a.no_dialog:
        info = {"Subject ID": str(a.subject), "Run": [RUNS[a.run-1]] + [r for r in RUNS if r != RUNS[a.run-1]],
                "Screen width (cm)": a.screen_width, "Viewing distance (cm)": a.viewing_distance,
                "Display index": a.display, "Windowed preview": a.windowed,
                "Lead-in seconds (-1 = full)": a.lead_in,
                "Preview duration (blank = full)": "" if a.duration is None else str(a.duration),
                "Use scanner (PROPixx TTL)": a.scanner,
                "Scanner DIN bit (zero based)": a.trigger_bit,
                "Scanner active level (0=low, 1=high)": a.trigger_level,
                "Button active level (0=low, 1=high)": a.button_level,
                "Skip initial scanner pulses": a.skip_triggers,
                "Preview key (blank = Space)": a.trigger,
                "Response keys (blank = any)": a.response_keys}
        if not gui.DlgFromDict(info, title="Retinotopy - PsychoPy", sortKeys=False).OK:
            return
        a.subject = int(info["Subject ID"])
        a.run = RUNS.index(info["Run"]) + 1
        a.screen_width = float(info["Screen width (cm)"])
        a.viewing_distance = float(info["Viewing distance (cm)"])
        a.display = int(info["Display index"])
        a.windowed = bool(info["Windowed preview"])
        a.lead_in = float(info["Lead-in seconds (-1 = full)"])
        a.duration = float(info["Preview duration (blank = full)"]) if str(info["Preview duration (blank = full)"]).strip() else None
        a.scanner = bool(info["Use scanner (PROPixx TTL)"])
        a.trigger_bit = int(info["Scanner DIN bit (zero based)"])
        a.trigger_level = int(info["Scanner active level (0=low, 1=high)"])
        a.button_level = int(info["Button active level (0=low, 1=high)"])
        a.skip_triggers = int(info["Skip initial scanner pulses"])
        a.trigger = str(info["Preview key (blank = Space)"])
        a.response_keys = str(info["Response keys (blank = any)"])
    validate_args(a)
    rows, dropped = load_orders(a.assets, a.subject, a.run, a.lead_in, a.duration)
    a.output.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    stem = a.output / f"sub-{a.subject:03d}_{RUNS[a.run-1]}_{stamp}"
    meta = {k: str(v) if isinstance(v, Path) else v for k, v in vars(a).items()}
    meta.update(upstream_commit=UPSTREAM_COMMIT, psychopy_version=psychopy.__version__,
                run_label=RUNS[a.run-1], stimulus_rate_hz=RATE, dropped_lead_in_steps=dropped,
                planned_steps=len(rows), planned_duration_s=len(rows)/RATE, status="initializing",
                geometry_calibrated=not a.windowed, utc_started=stamp)
    steps, responses, flips = [], [], []
    win = scanner = None
    scanner_events = []
    pulse_count = 0
    start_trigger = start_sync = None
    first_flip_host = None
    try:
        monitor = monitors.Monitor("retinotopy_session", width=a.screen_width, distance=a.viewing_distance)
        win = visual.Window(size=(1024, 768), fullscr=not a.windowed, screen=a.display,
                            monitor=monitor, units="pix", color=(128, 128, 128), colorSpace="rgb255",
                            waitBlanking=True, allowGUI=a.windowed, autoLog=False)
        win.mouseVisible = False
        clock = core.Clock()
        kb = keyboard.Keyboard(clock=clock)
        mouse = event.Mouse(win=win, visible=False)
        text = visual.TextStim(win, color="white", height=24, wrapWidth=min(900, win.size[0]-60), autoLog=False)

        def status(message):
            text.text = message
            text.draw()
            win.flip()
            if kb.getKeys(["escape"], waitRelease=False):
                raise KeyboardInterrupt

        def read_scanner():
            """Keep all pulses, including several edges returned in one batch."""
            nonlocal start_trigger, start_sync, pulse_count
            for item in scanner.read():
                if item["kind"] == "trigger":
                    pulse_count += 1
                    item["pulse_number"] = pulse_count
                    if pulse_count <= a.skip_triggers:
                        item["role"] = "skipped"
                    elif start_trigger is None:
                        item["role"] = "start"
                        start_trigger = item
                        start_sync = dict(scanner.sync)
                    else:
                        item["role"] = "subsequent"
                scanner_events.append(item)

        diameter, eccentricity = geometry(*win.size, a.screen_width, a.viewing_distance)
        if a.windowed:
            diameter = float(min(win.size))
            eccentricity = None  # A window's pixel width is not the physical monitor width.
        meta.update(window_pixels=[int(x) for x in win.size], stimulus_diameter_px=diameter,
                    actual_max_eccentricity_deg=eccentricity)
        patterns, masks, grid_image = preload(a.assets, a.run, rows, status)
        rgba = np.zeros((SIZE, SIZE, 4), dtype=np.uint8)
        stim = visual.ImageStim(win, image=Image.fromarray(rgba), size=(diameter, diameter),
                                units="pix", interpolate=False, autoLog=False)
        grid = visual.ImageStim(win, image=grid_image, size=(diameter, diameter), units="pix",
                                interpolate=False, autoLog=False)
        dot = visual.Circle(win, radius=7*diameter/SIZE, edges=64, units="pix", lineColor=None,
                            fillColor=COLORS[0], colorSpace="rgb255", autoLog=False)
        # Warm texture upload/drawing before the timed interval.
        if patterns:
            stim.setImage(compose(next(iter(patterns.values())), next(iter(masks.values())), rgba), log=False)
            stim.draw()
        dot.draw()
        grid.draw()
        win.flip()
        status("Measuring display refresh rate...")
        hz = win.getActualFrameRate(nIdentical=20, nMaxFrames=240, nWarmUpFrames=30, threshold=1)
        if hz is None or hz < 30:
            raise RuntimeError("Could not measure a stable display refresh rate >=30 Hz. Check display settings and retry.")
        period = 1.0 / hz
        meta.update(measured_refresh_hz=float(hz), refreshes_per_step=float(hz/RATE),
                    timing_policy="nearest-refresh, elapsed-time schedule; missed steps logged as skipped")
        win.refreshThreshold = 1.5*period
        # Upload the actual first texture before accepting the start pulse.
        first_mask, first_pattern, first_dot = map(int, rows[0])
        if first_mask >= 0:
            stim.setImage(compose(patterns[first_pattern], masks[first_mask], rgba), log=False)
        dot.fillColor = COLORS[first_dot]
        start_key = a.trigger or "space"
        calibration = "Windowed preview (visual angle uncalibrated)" if a.windowed else f"Maximum eccentricity: {eccentricity:.2f} degrees"
        if a.scanner:
            status("Connecting to scanner input...\nDo not start the scanner yet.\nEscape exits.")
            from scanner_input import ScannerInput
            scanner = ScannerInput(a.trigger_bit, a.trigger_level, a.button_level)
            # Finish loading, texture uploads and refresh measurement before
            # arming. The device now retains edges even during the ready flip.
            scanner.arm()
            meta["scanner_armed_device_time_s"] = scanner.armed_time
        wait_message = (f"Waiting for scanner TTL: DIN bit {a.trigger_bit}, active {a.trigger_level}\n"
                        f"Skip {a.skip_triggers} pulses; start on pulse {a.skip_triggers+1}"
                        if a.scanner else f"Waiting for key: {start_key}")
        status(f"{RUNS[a.run-1]} | {len(rows)/RATE:.1f} seconds\n{calibration}\n\n"
               "Keep looking at the central dot.\nPress the response button whenever its color changes.\n\n"
               f"{wait_message}\nEscape exits and saves data.")
        kb.clearEvents()
        clock.reset()
        start_press = None
        while start_trigger is None and start_press is None:
            for key in kb.getKeys(waitRelease=False, clear=True):
                if key.name == "escape":
                    raise KeyboardInterrupt
                if not a.scanner and key.name == start_key:
                    start_press = key
                    break
            if scanner is not None:
                read_scanner()
            if start_trigger is None and start_press is None:
                core.wait(.001)
        # Keep keyboard times relative to the first actual stimulus flip.
        def begin():
            nonlocal first_flip_host
            first_flip_host = perf_counter()
            if start_press is not None:
                meta["start_key_to_first_flip_s"] = clock.getTime() - start_press.rt
            clock.reset()
        kb.clearEvents()
        win.callOnFlip(begin)
        win.recordFrameIntervals = True
        previous_buttons = mouse.getPressed()
        accepted_keys = {s.strip().lower() for s in a.response_keys.split(",") if s.strip()}
        current = -1
        first_flip = None
        previous_dot = None
        last_flip = None
        meta["status"] = "running"
        while True:
            if first_flip is None:
                index = 0
            else:
                predicted = win.getFutureFlipTime(clock=None) - first_flip
                index = max(current, schedule_index(predicted, period))
            ending = index >= len(rows)
            changed = index != current
            if ending:
                pass  # Clear to grey at the planned end, removing the final frame.
            else:
                mask_id, pattern_id, dot_id = map(int, rows[index])
                if changed:
                    if mask_id >= 0 and index != 0:
                        stim.setImage(compose(patterns[pattern_id], masks[mask_id], rgba), log=False)
                    dot.fillColor = COLORS[dot_id]
                if mask_id >= 0:
                    stim.draw()
                dot.draw()
                grid.draw()  # Matches upstream's grid-over-dot draw order.
            absolute = win.flip()
            if absolute is None:
                raise RuntimeError("Window.flip did not return a timestamp; VSync is required.")
            if first_flip is None:
                first_flip = absolute
            elapsed = absolute - first_flip
            flips.append({"flip_index": len(flips), "onset_s": elapsed,
                          "interval_s": "" if last_flip is None else absolute-last_flip,
                          "step_index": -1 if ending else index})
            last_flip = absolute
            if changed and not ending:
                dot_changed = previous_dot is not None and dot_id != previous_dot
                steps.append({"step_index": index, "source_row": index+dropped,
                              "target_onset_s": index/RATE, "actual_onset_s": elapsed,
                              "onset_error_s": elapsed-index/RATE, "mask_id": mask_id,
                              "pattern_id": pattern_id, "dot_color_id": dot_id,
                              "dot_changed": dot_changed, "status": "presented"})
                previous_dot = dot_id
                current = index
            abort = False
            for key in kb.getKeys(waitRelease=False, clear=True):
                kind = "trigger" if not a.scanner and a.trigger and key.name == a.trigger else "keypress"
                if key.name == "escape":
                    kind, abort = "abort", True
                if kind != "keypress" or not accepted_keys or key.name in accepted_keys:
                    responses.append({"time_s": key.rt, "kind": kind, "key": key.name})
            buttons = mouse.getPressed()
            for button, (now, before) in enumerate(zip(buttons, previous_buttons)):
                if now and not before:
                    responses.append({"time_s": clock.getTime(), "kind": "mousepress", "key": button+1})
            previous_buttons = buttons
            if scanner is not None:
                read_scanner()  # Hardware retained every edge since the last read.
            if ending or abort:
                meta["status"] = "aborted" if abort else "completed"
                if abort and not ending:
                    last_flip = win.flip()  # Remove stimulus immediately on abort.
                    flips.append({"flip_index": len(flips), "onset_s": last_flip-first_flip,
                                  "interval_s": last_flip-absolute, "step_index": -1})
                meta["actual_duration_s"] = last_flip-first_flip
                break
    except KeyboardInterrupt:
        meta["status"] = "aborted"
    except Exception as exc:
        meta.update(status="error", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        if scanner is not None:
            meta["scanner_max_pending_edges"] = scanner.max_pending
            meta["scanner_last_clock_sample"] = scanner.sync
            try:
                scanner.close()
            except Exception as exc:
                meta["scanner_cleanup_error"] = str(exc)
        # Device and host clocks differ. Preserve raw device times and explicitly
        # label the midpoint mapping as an estimate, never as physical onset.
        device_first_flip = None
        if start_trigger is not None:
            meta["scanner_start_trigger_device_time_s"] = start_trigger["device_time_s"]
            meta["scanner_start_clock_sample"] = start_sync
            if first_flip_host is not None:
                midpoint = (start_sync["host_before_s"] + start_sync["host_after_s"])/2
                device_first_flip = start_sync["device_time_s"] + first_flip_host-midpoint
                meta["scanner_trigger_to_first_flip_s_estimate"] = device_first_flip-start_trigger["device_time_s"]
                meta["scanner_clock_sample_span_s"] = start_sync["host_after_s"]-start_sync["host_before_s"]
                meta["scanner_detection_to_first_flip_s"] = first_flip_host-start_trigger["host_detected_s"]
        for item in scanner_events:
            item["since_start_trigger_s"] = (item["device_time_s"]-start_trigger["device_time_s"]
                                               if start_trigger is not None else "")
            item["time_s_estimate"] = (item["device_time_s"]-device_first_flip
                                       if device_first_flip is not None else "")
            item["host_detection_since_flip_s"] = (item["host_detected_s"]-first_flip_host
                                                    if first_flip_host is not None else "")
            if item["kind"] == "boxpress" and device_first_flip is not None and item["time_s_estimate"] >= 0:
                responses.append({"time_s": item["time_s_estimate"], "kind": "boxpress", "key": item["key"],
                                  "timing_source": "vpixx_clock_mapping_estimate"})
        if win is not None:
            meta["psychopy_dropped_refreshes"] = int(win.nDroppedFrames)
            win.close()
        if a.scanner:
            save_csv(str(stem)+"_scanner.csv", ["device_time_s", "since_start_trigger_s", "time_s_estimate",
                     "host_detected_s", "host_detection_since_flip_s", "kind", "key", "raw_din",
                     "pulse_number", "role"], scanner_events)
        shown = {s["step_index"]: s for s in steps}
        last_shown = max(shown, default=-1)
        for i, (mask_id, pattern_id, dot_id) in enumerate(rows):
            if i not in shown:
                steps.append({"step_index": i, "source_row": i+dropped, "target_onset_s": i/RATE,
                              "actual_onset_s": "", "onset_error_s": "", "mask_id": int(mask_id),
                              "pattern_id": int(pattern_id), "dot_color_id": int(dot_id), "dot_changed": "",
                              "status": "skipped" if i < last_shown or meta["status"] == "completed" else "not_presented"})
        steps.sort(key=lambda s: s["step_index"])
        # Associate responses by event timestamp, not by the time they were polled.
        visible_steps = [s for s in steps if s["status"] == "presented"]
        onsets = np.array([s["actual_onset_s"] for s in visible_steps])
        changes = [s["actual_onset_s"] for s in visible_steps if s["dot_changed"]]
        for response in responses:
            response.setdefault("timing_source", "host_poll" if response["kind"] == "mousepress" else "psychopy_keyboard")
            t = response["time_s"]
            j = int(np.searchsorted(onsets, t, side="right"))-1
            response["step_index"] = visible_steps[j]["step_index"] if j >= 0 else -1
            c = int(np.searchsorted(changes, t, side="right"))-1
            response["since_dot_change_s"] = t-changes[c] if c >= 0 else ""
        meta["skipped_steps"] = sum(s["status"] == "skipped" for s in steps)
        meta["presented_steps"] = len(visible_steps)
        save_csv(str(stem)+"_steps.csv", ["step_index", "source_row", "target_onset_s", "actual_onset_s",
                 "onset_error_s", "mask_id", "pattern_id", "dot_color_id", "dot_changed", "status"], steps)
        responses.sort(key=lambda response: response["time_s"])
        save_csv(str(stem)+"_responses.csv", ["time_s", "kind", "key", "step_index", "since_dot_change_s", "timing_source"], responses)
        save_csv(str(stem)+"_flips.csv", ["flip_index", "onset_s", "interval_s", "step_index"], flips)
        Path(str(stem)+"_session.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        print(f"{meta['status']}: saved {stem}_*.csv and _session.json")


def main(argv=None):
    a = parse_args(argv)
    if a.validate_only:
        validate_args(a)
        rows, dropped = load_orders(a.assets, a.subject, a.run, a.lead_in, a.duration)
        patterns, masks, _ = preload(a.assets, a.run, rows)
        print(f"Validated {RUNS[a.run-1]}: {len(rows)} steps, {len(rows)/RATE:.3f} s; "
              f"{len(patterns)} patterns, {len(masks)} masks; {dropped} baseline steps removed.")
    else:
        run_experiment(a)


if __name__ == "__main__":
    main()
