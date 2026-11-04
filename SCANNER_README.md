# Scanner version

Open `retinotopy_scanner.py` in PsychoPy Coder and click **Run**. Keep it and
`scanner_input.py` beside the existing `assets/` folder. The original
`retinotopy_psychopy.py` and `button_box_threading.py` are unchanged.

This version uses the **PROPixx controller digital input**, matching your supplied
button-box code. Install the lab's compatible `pypixxlib` and VPixx drivers in the
Python environment used by PsychoPy. Do not run the old button-box thread alongside
this script: both would access the same hardware log.

## Settings

- **Use scanner (PROPixx TTL):** keep checked for acquisition. Space cannot start
  a scanner run. Uncheck for a keyboard preview.
- **Scanner DIN bit:** default **4**, zero based, corresponding to the fifth bit
  in your original code. Confirm the actual scanner cable/channel.
- **Scanner active level:** default **0**, meaning a falling edge. This matches
  the supplied module with `IsMRI = 0`. Use **1** for a rising-edge trigger.
- **Button active level:** default **0**. Buttons on bits 0–3 are logged as red,
  yellow, green and blue, following your module's mapping. Confirm these too.
- **Skip initial scanner pulses:** default **0** starts on the first fresh pulse.
  A value of **4** skips four pulses and starts on the fifth. Set this from the
  acquisition protocol; emitted pulses and scanner-discarded volumes may differ.
- For the full existing 300-second protocol, keep **lead-in = -1** and duration
  blank. This retains the opening fixation baseline; it is part of the run.

Wait until **Waiting for scanner TTL** appears before starting acquisition.
Loading, texture preparation and refresh measurement happen first. The input log
is armed immediately before that ready screen. A line already active at arming
must return idle and then produce a new active edge. Escape aborts and saves
partial data, including while waiting.

Example, subject 1/run 4, with the default bit-4 falling-edge trigger:

```shell
python retinotopy_scanner.py --no-dialog -s 1 -r 4 --screen-width 40 --viewing-distance 60
```

Those display measurements are examples; use your measured acquisition geometry.
Add `--skip-triggers 4` only if your protocol requires starting on pulse five.
For a preview without VPixx hardware:

```shell
python retinotopy_scanner.py --keyboard-preview --windowed --lead-in 2 --duration 30
```

## Trigger and timing

The small `scanner_input.py` helper reads **every recorded input edge**, preserving
short low/high pulses within one batch. The VPixx device buffers the events, so a
Python thread is unnecessary. Polling happens while waiting and once per display
frame during the run. The supplied thread's 30-ms debounce is disabled; the short
stabilization filter enabled by `DPxSetDinLog()` is retained. Check compatibility
with the scanner pulse width. The 10,000-event circular buffer must hold all
transitions between reads; a near-capacity check cannot detect every possible
complete buffer wrap. [VPixx API](https://docs.vpixx.com/python/libdpx-wrapper)

The stimulus clock resets **once, on the first presentation flip**. Later scanner
pulses are recorded without resetting it. The existing elapsed-time schedule and
full baseline are retained, and missed stimulus steps are logged. The first flip
follows the accepted trigger on an available refresh; it is not simultaneous with
the TTL edge. [PsychoPy flip API](https://psychopy.org/api/visual/window.html)

Existing step, flip, response and session files remain. Scanner runs also save
`*_scanner.csv`:

| Field | Meaning |
| --- | --- |
| `device_time_s` | Raw VPixx hardware timestamp, seconds since power-up |
| `since_start_trigger_s` | Hardware time relative to the accepted start pulse; skipped pulses are negative |
| `time_s_estimate` | Event time mapped approximately to first-flip zero |
| `host_detection_since_flip_s` | When Python read the event, relative to the first-flip callback |
| `pulse_number`, `role` | Pulse count and skipped/start/subsequent classification |

In `*_session.json`, `scanner_trigger_to_first_flip_s_estimate` relates the two
origins. For example:

```text
estimated stimulus onset after scanner start
    = steps.csv actual_onset_s + scanner_trigger_to_first_flip_s_estimate
```

This estimate maps the two clocks using a bracketed hardware-clock read. The
saved `scanner_clock_sample_span_s` measures that sampling span, **not total
timing accuracy**. Clock drift, flip-callback delay and physical display latency
add uncertainty. Raw hardware times and start/end clock samples are saved for
inspection. Button-box responses use the estimated mapping and are labelled
`vpixx_clock_mapping_estimate` in the response CSV. Keyboard and mouse responses
remain supported. `--response-keys` filters keyboard responses only.

## Validation

Synthetic tests cover batched pulses, arming, polarity, skipped pulses, later
triggers, cleanup, Escape and keyboard preview:

```shell
python -m unittest -v test_scanner.py
```

PsychoPy display output and the actual scanner/VPixx hardware have **not** been
tested here. Before collecting participant data, verify the physical input bit,
polarity, pulse count and width, then measure TTL-to-visible-onset timing with the
lab's photodiode/timing equipment. Inspect scanner pulse intervals and flip logs
during a full-length test run. These tests do not certify hardware synchronization.
