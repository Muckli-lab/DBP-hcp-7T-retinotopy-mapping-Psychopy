# Retinotopy with GMPD3 and optional VPixx triggering

A PsychoPy experiment for presenting retinotopic mapping stimuli during fMRI. It combines precomputed bar, wedge, and ring masks with changing image patterns, displays a central fixation task, and records participant responses from a Current Designs GMPD3 button device.

The experiment can start from a VPixx PROPixx controller digital input, a scanner keyboard pulse, or a manual Space press. **The GMPD3 is required for participant responses in every presentation mode, including windowed previews.** Schedule validation and synthetic tests can run without connected hardware.

## Project contents

```text
retinotopy_gmpd3/
├── retinotopy_scanner.py       # Experiment, command-line options, and data saving
├── gmpd3_input.py             # GMPD3 input and standalone button monitor
├── scanner_input.py           # VPixx digital-input logging and standalone monitor
├── test_scanner.py            # Synthetic input and experiment runtime tests
├── GMPD3_SETUP.md             # Additional device and lab setup notes
├── requirements-original.txt  # Original environment snapshot
├── LICENSE
├── assets/
│   ├── fixationGrid.png
│   ├── patterns/              # 100 pattern images
│   ├── masks/
│   │   ├── swippingBars/      # 1,680 bar masks
│   │   ├── rotatingWedge/     # 480 wedge masks
│   │   └── expendingCircles/  # 420 ring masks
│   └── StimuliOrder/          # Shared mask order and subject-specific schedules
└── data/                     # Default location for session outputs
```

Keep the asset folder names exactly as supplied, including `swippingBars` and `expendingCircles`. All stimulus PNGs are 768 × 768 pixels.

## Requirements and setup

Use a Python environment that can run PsychoPy on the presentation workstation. The experiment directly uses:

| Package | Purpose |
| --- | --- |
| `psychopy` | Display, configuration dialog, keyboard input, and flip timestamps |
| `numpy` | Schedules, image buffers, and response-to-step association |
| `Pillow` | Loading and composing stimulus images |
| `pygame` 2.x | GMPD3 input through SDL |
| `pypixxlib` | VPixx scanner triggering only |

Throughout this README, `python` means the interpreter used to launch the experiment. Use `python3` instead where appropriate. Install the supporting packages into that same environment:

```sh
python -m pip install numpy Pillow "pygame>=2,<3"
```

For VPixx sessions, also install the lab's `pypixxlib` package and required VPixx drivers/libraries. `--no-vpixx` avoids loading `pypixxlib`; it does not change how the selected display presents the stimuli.

`requirements-original.txt` records the original environment rather than providing a portable installation recipe. It includes Linux-specific packages and a `pypixxlib` reference to a local archive. Adapt those entries before using it on another workstation. The supplied `.venv`, if present, comes from Linux/Python 3.12 and should be recreated for the target machine.

Run the commands below from the folder containing `retinotopy_scanner.py`. The default asset and output paths are relative to the script, so launching it from another working directory also works.

### Check the GMPD3

Set the Current Designs 932 interface to **USB joystick mode**, connect the device, and run:

```sh
python gmpd3_input.py
```

Press each of the six buttons and check the printed labels. Exit with **Ctrl+C**.

| SDL button index | Recorded label |
| --- | --- |
| 0 | `Y` |
| 1 | `B` |
| 2 | `X` |
| 3 | `LT` |
| 4 | `A` |
| 5 | `RT` |

Only button-down events are recorded; stick movement and button releases are ignored. Automatic selection requires one eligible joystick. If selection fails or several devices are connected, use the index in the error's SDL device list:

```sh
python gmpd3_input.py --gamepad-index 0
```

Use the same `--gamepad-index` when launching the experiment, or enter it in the configuration dialog. See [GMPD3_SETUP.md](GMPD3_SETUP.md) for the mapping reference and lab notes.

## Quick start

### Validate a schedule and its assets

```sh
python retinotopy_scanner.py --validate-only --subject 1 --run 1
```

This checks schedule lengths and ID ranges, loads the images required by the selected run, and verifies their dimensions. It needs NumPy and Pillow, but does not load PsychoPy, pygame, or VPixx, open a window, or write session files. Full-run validation preloads many images and can use substantial memory. For a short check:

```sh
python retinotopy_scanner.py --validate-only --subject 1 --run 1 --lead-in 2 --duration 5
```

### Preview without VPixx

```sh
python retinotopy_scanner.py --no-vpixx --windowed --subject 1 --run 1 --lead-in 2 --duration 30
```

Confirm the settings in the dialog, wait for loading and refresh measurement to finish, then press **Space** at the waiting screen. This presents a 30-second, uncalibrated 1024 × 768 preview with two seconds of the initial baseline retained. The GMPD3 must remain connected. Press **Escape** to end the run and save the available data.

### Run with VPixx scanner triggering

```sh
python retinotopy_scanner.py --subject 1 --run 1
```

VPixx triggering and fullscreen presentation are enabled by default. In the dialog:

1. Select the subject, run, and projector display index.
2. Enter the physical full-display width and eye-to-display viewing distance in centimetres.
3. Keep **Use VPixx for scanner trigger** enabled and enter the lab's verified DIN bit, active level, and number of initial pulses to skip.
4. Leave duration blank and lead-in at `-1` for the full schedule.
5. Wait until the experiment reports that it is waiting for scanner TTL before starting acquisition.

The default trigger is **DIN bit 4, active low**, with no pulses skipped. These defaults must match the actual wiring. After arming, the experiment ignores old events and requires a fresh active edge; a line already active at arming must return inactive first. With `--skip-triggers N`, it starts on fresh pulse **N + 1**. Later pulses are logged without restarting the stimulus schedule.

To inspect all 16 digital inputs before launching PsychoPy:

```sh
python scanner_input.py
```

This requires the VPixx hardware and `pypixxlib`. It prints timestamped rising and falling edges; exit with **Ctrl+C**.

### Run with a keyboard scanner pulse

For a scanner interface that sends the `5` key:

```sh
python retinotopy_scanner.py --no-vpixx --trigger 5 --skip-triggers 4 --subject 1 --run 1
```

This skips four key pulses and starts on the fifth. Subsequent `5` pulses are recorded in the response log as `trigger` events. With no explicit `--trigger`, Space is a manual start and starts on one press regardless of `--skip-triggers`. Other trigger interfaces require an adapter.

The settings dialog appears by default and can override command-line values. Add `--no-dialog` to use the supplied arguments directly. A single launch presents one run; launch again for the next run.

## Runs and participant task

All six supplied schedules contain **4,500 steps at 15 Hz: 300 seconds (5 minutes) per run**, including baseline periods.

The table pairs the phase-encoding direction to select **on the scanner** with the run number to select **in PsychoPy**, following the acquisition protocol supplied for this experiment. Each run lasts **5 minutes**.

| Scanner run | Retinotopy stimulus | PsychoPy run | Phase encoding |
| --- | --- | --- | --- |
| RET1 | RETCCW · Counterclockwise wedge | `-r 3` | AP |
| RET2 | RETCW · Clockwise wedge | `-r 4` | PA |
| RET3 | RETEXP · Expanding ring | `-r 5` | AP |
| RET4 | RETCON · Contracting ring | `-r 6` | PA |
| RET5 | RETBAR1 · Multidirectional bar sweeps | `-r 1` | AP |
| RET6 | RETBAR2 · Same bar sweeps as RETBAR1 | `-r 2` | PA |

Set AP/PA in the scanner acquisition protocol. The PsychoPy `-r` argument selects the stimulus schedule and does not configure scanner phase encoding. The initial fixation baseline is 16 seconds for the bar runs and 22 seconds for the wedge and ring runs; these periods are included in the five-minute duration.

The two bar runs share the supplied mask schedule and use their respective subject-specific pattern and dot-color columns. Subjects `0` through `100` have bundled order files. Other nonnegative subject IDs require a corresponding `sub-NNN_stimuliOrderRetinotopy.csv` file.

Participants keep looking at the central dot and press a response button whenever its color changes. Dot-color IDs are `0 = white`, `1 = black`, and `2 = red`. During blank mask periods, the fixation dot and grid remain visible. All six GMPD3 buttons are logged; the program does not assign a correct button or calculate task accuracy.

### Stimulus motion

Both bar runs use the following sweep order:

1. Top → bottom
2. Right → left
3. Bottom → top
4. Left → right
5. Upper-right → lower-left
6. Lower-right → upper-left
7. Lower-left → upper-right
8. Upper-left → lower-right

These motion directions follow the supplied PNG masks and CSV playback order, with the top of the image treated as up. For the wedge masks, playback rotates opposite to the inherited `RETCCW`/`RETCW` labels in image coordinates; participant-view rotation depends on display mirroring. The acquisition table retains the protocol's stimulus names.

### Schedule format

- `assets/StimuliOrder/maskOrderRetinotopy.csv` supplies a column named for each run label, such as `RETBAR1`.
- Each subject file supplies `run1_pattern` through `run6_pattern` and `run1_dotColor` through `run6_dotColor`.
- For a selected run, mask, pattern, and dot schedules must be nonempty and have equal lengths.
- IDs are zero-based. Mask `-1` means blank; other mask IDs select the corresponding mask image. Pattern IDs range from `0` to `99`; dot-color IDs range from `0` to `2`.
- Image filenames are one-based: pattern ID `0` loads `pattern_0001.png`, for example.

`--lead-in` only shortens the existing initial blank period; it does not add baseline time. A negative value preserves it, and `0` removes it. `--duration` then truncates the remaining schedule, including any retained baseline. Both operations use the 15 Hz step grid. Omit these preview overrides for the supplied full protocol.

## Command-line reference

```sh
python retinotopy_scanner.py --help
```

| Option | Default | Meaning |
| --- | --- | --- |
| `-s`, `--subject` | `0` | Nonnegative subject ID |
| `-r`, `--run` | `1` | Run number, `1`–`6` |
| `--assets` | Script's `assets/` | Asset directory |
| `--output` | Script's `data/` | Output directory; created if needed |
| `--screen-width` | `30` | Physical full-display width in cm |
| `--viewing-distance` | `50` | Eye-to-display distance in cm |
| `--display` | `0` | PsychoPy display index |
| `--windowed` | Off | Uncalibrated 1024 × 768 preview |
| `--lead-in` | `-1` | Initial baseline seconds to retain; negative preserves all |
| `--duration` | Full schedule | Maximum duration after baseline trimming, in seconds |
| `--no-vpixx` | VPixx enabled | Use a manual or keyboard start; alias: `--keyboard-preview` |
| `--gamepad-index` | `-1` | SDL joystick index; `-1` selects automatically |
| `--trigger-bit` | `4` | Zero-based VPixx DIN bit, `0`–`15` |
| `--trigger-level` | `0` | Active VPixx input level: `0` low, `1` high |
| `--skip-triggers` | `0` | Fresh scanner pulses to skip before the start pulse |
| `--trigger` | Blank | Non-VPixx start/pulse key; blank uses manual Space |
| `--no-dialog` | Off | Skip the configuration dialog |
| `--validate-only` | Off | Check the selected schedule and required assets, then exit |

## Output files

Outputs use a shared stem containing the zero-padded subject ID, run label, and UTC timestamp:

```text
data/sub-001_RETBAR1_YYYYMMDDTHHMMSS_microsecondsZ_*
```

| Suffix | Contents |
| --- | --- |
| `_session.json` | Settings, run status, planned/presented/skipped step counts, display geometry, refresh rate, and available device/timing metadata |
| `_steps.csv` | Every planned step, stimulus IDs, target and actual onset, onset error, dot change, and presentation status |
| `_responses.csv` | GMPD3 presses, configured keyboard trigger events, and keyboard aborts, with step and dot-change associations |
| `_flips.csv` | Display flip timestamps and intervals; `step_index = -1` marks stimulus removal |
| `_scanner.csv` | VPixx trigger and release edges, device/host timestamps, pulse numbers, and roles; written only with VPixx enabled |

Step status is `presented`, `skipped` when the elapsed-time schedule has passed a step, or `not_presented` for unreached steps after interruption. `source_row` preserves the zero-based position in the original schedule after baseline trimming. Session status can be `completed`, `aborted`, or `error`. Escape and errors inside the recording block save the data available so far; failures before that block may produce no files.

GMPD3 response rows use `kind = gmpd3_press`, the button label in `key`, and `timing_source = host_poll`. `time_s` is relative to the first stimulus flip. `since_dot_change_s` measures time since the latest presented dot-color change, so it is not a scored or uniquely matched reaction time. Ordinary keyboard presses and mouse clicks are not recorded as fixation-task responses.

## Display and timing

The presentation loop follows elapsed time at a nominal 15 Hz and selects steps at the nearest display refresh. It skips missed schedule steps rather than extending the run to replay them. Startup requires a measured stable display refresh rate of at least 30 Hz.

Fullscreen geometry targets a 15° maximum eccentricity using the entered physical width and viewing distance. The stimulus diameter is clipped to the available display width and height, so the achieved eccentricity can be smaller. Inspect `actual_max_eccentricity_deg` in the session JSON. Windowed previews do not provide calibrated visual angles.

PsychoPy flip times describe software display flips, not measured physical light onset. GMPD3 times are host polling times, typically quantized by the presentation loop, rather than hardware button timestamps. VPixx retains digital edges with device timestamps between polls; the logged mapping to the first flip (`time_s_estimate` and related metadata) is an estimate based on a bracketed host/device clock sample. Physical scanner, display, and response timing need separate validation on the acquisition setup.

## Tests and troubleshooting

Run the existing synthetic tests with NumPy and Pillow installed:

```sh
python -m unittest -v test_scanner
```

The tests mock PsychoPy, GMPD3, and VPixx hardware. They cover button mapping, input edges, buffer handling, trigger skipping, keyboard starts, aborts, and output saving. They do not certify physical device or display timing.

| Problem | Check |
| --- | --- |
| PsychoPy or pygame cannot be imported | Run with the intended Python interpreter and install packages into that same environment. You can also open `retinotopy_scanner.py` in PsychoPy Coder and click Run. |
| No GMPD3 selected, or several devices listed | Check the 932's USB joystick mode, run the button monitor, and set `--gamepad-index` explicitly. |
| `pypixxlib` cannot load or PROPixx controller is missing | Check the VPixx installation and connection, or use `--no-vpixx` for a keyboard/manual start. |
| Waiting indefinitely for a trigger | Check the DIN bit and polarity or keyboard pulse key, skipped-pulse count, and that pulses arrive after the ready screen. |
| No stable refresh rate | Check the chosen display, VSync, and workstation display settings. |
| Missing schedule/image or invalid dimensions | Check the subject's order file, asset path, folder spellings, and 768 × 768 image dimensions with `--validate-only`. |
| Slow loading or high memory use | Required patterns and masks are preloaded; full bar runs use over 1 GB of raw image arrays. Shorten a preview with `--duration` and `--lead-in`. |

## License and provenance

The experiment entry point identifies the port as **GPL-3.0-only**; see [LICENSE](LICENSE) for the license text. The source credits upstream copyright (2026) to Christophe Pallier and records upstream commit `be2ea4de40c66ff0f59f04a27b9ff54412559713`. This variant uses PsychoPy presentation, the supplied asset schedules, GMPD3 participant input, and optional VPixx scanner-trigger logging.
