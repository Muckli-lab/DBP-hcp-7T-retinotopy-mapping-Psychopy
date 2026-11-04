# Retinotopy for PsychoPy

A PsychoPy **Coder Python script**, ported from [Christophe Pallier's retinotopy-go](https://github.com/chrplr/retinotopy-go), commit `be2ea4de40c66ff0f59f04a27b9ff54412559713` (retrieved 28 September 2026).

Includes the original 100 pattern images, 2,580 aperture masks, fixation grid, and schedules for subjects **0–100**. No asset downloads are needed after extracting this package. This is a `.py` implementation, not a Builder `.psyexp` file.

## Run it

1. Install [Standalone PsychoPy](https://www.psychopy.org/download.html), if needed.
2. Extract the ZIP completely, preserving the `assets` folder alongside the script.
3. In PsychoPy's **Coder** view, open `retinotopy_psychopy.py` and click **Run**.
4. Enter the subject ID, run, measured screen width and viewing distance. Choose the correct display index (0 is primary).
5. After image loading and refresh measurement, press **Space** to start. If you specified a scanner trigger key, the script waits for that key instead.

Press a response key or mouse button whenever the central dot changes color. **Escape** ends the run and saves partial results. The initial dot color does not count as a change. Later scanner trigger presses are logged separately from responses.

For a quick demonstration, tick **Windowed preview**, set **Lead-in seconds** to `2`, and **Preview duration** to `30`. Windowed mode is explicitly uncalibrated. For the full protocol, leave lead-in at `-1` and duration blank.

| Run | Label | Stimulus |
| --- | --- | --- |
| 1 | RETBAR1 | Sweeping bars, first pass |
| 2 | RETBAR2 | Sweeping bars, second pass |
| 3 | RETCCW | Counter-clockwise wedge |
| 4 | RETCW | Clockwise wedge |
| 5 | RETEXP | Expanding rings |
| 6 | RETCON | Contracting rings |

Each complete run contains 4,500 stimulus steps at 15 Hz: **300 seconds**. Initial fixation-only baseline is 16 seconds for bars and 22 seconds for wedges/rings. A single invocation runs one selected run.

## Command line

Use a Python environment that already has PsychoPy, NumPy and Pillow installed. Standalone PsychoPy's Coder is the simplest way to run this package; a system `python` command may refer to a different environment.

```shell
# Full protocol, subject 1, clockwise wedge; wait for scanner key 5.
python retinotopy_psychopy.py --no-dialog -s 1 -r 4 --trigger 5 --screen-width 40 --viewing-distance 60

# 30-second preview with two seconds of opening baseline.
python retinotopy_psychopy.py --no-dialog --windowed --lead-in 2 --duration 30

# Restrict keyboard responses to 1 and 2; mouse responses remain enabled.
python retinotopy_psychopy.py --response-keys 1,2

# Check files and IDs without opening a window or importing PsychoPy.
python retinotopy_psychopy.py --validate-only -s 0 -r 1

python retinotopy_psychopy.py --help
```

`--trigger` supports scanner devices that emulate a keyboard. Serial/parallel TTL devices need a separate adapter. The first received trigger starts the run; there is no automatic dummy-volume count or resynchronization on later triggers. No participant demographics are requested or cached.

## Stimulus fidelity and timing

- Uses the original CSV rows directly, with zero-based pattern/mask IDs; PNG filenames are one-based. A mask ID of `-1` is fixation-only baseline.
- Preserves original pattern pixels and grayscale mask opacity. The fixation grid is rendered as white with the source grayscale values as alpha, over the dot, matching the upstream draw order. Dot colors are white, black and red, with radius `7 × stimulus_diameter/768` pixels.
- Requests a 15-degree maximum eccentricity using flat-screen geometry (`radius_cm = distance_cm × tan(15°)`), clamped to fit the display. Records the resulting eccentricity. This intentionally differs slightly from upstream, which applies a full-width angle conversion to the stimulus radius: without clamping, this port's diameter is about 1.8% larger. Use the physical width of the full selected display and the eye-to-display distance; projection/mirror setups need their appropriate effective geometry.
- Preloads the images referenced by the selected run. A full bar run needs roughly 1.2 GB of raw image memory plus PsychoPy overhead. No image files are read from disk during stimulus presentation, but each new stimulus step requires a GPU texture upload.
- Keeps the **full baseline by default**. Upstream's Go default trims baseline to two seconds; this port requires an explicit preview setting to do that.
- Uses `1/15` seconds per step. Upstream uses integer `1000/15 = 66` milliseconds. This port therefore follows the intended 300-second schedule rather than reproducing that rounding error.
- Presents steps on the nearest predicted display refresh. A 60 Hz display normally gives four refreshes per step. Other refresh rates can produce uneven frame counts per step. Actual flip times are always logged.
- If rendering stalls, the elapsed-time schedule catches up and logs unshown steps as `skipped`, rather than extending every later onset. Review these logs for each acquired run.

## Output

Files go into `data/` beside the script, or the directory supplied with `--output`. Each run has a UTC timestamp to avoid overwriting earlier results:

| File | Contents |
| --- | --- |
| `*_steps.csv` | Original row, stimulus IDs, intended/actual onset, onset error, displayed dot changes, and presented/skipped/not-presented status |
| `*_responses.csv` | Keyboard/mouse/trigger/abort events, timestamps, associated displayed step, and time since the latest displayed dot change |
| `*_flips.csv` | Every display flip and interval, including final stimulus removal (`step_index=-1`) |
| `*_session.json` | Settings, source revision, PsychoPy version, display geometry, measured refresh rate, start-key delay, run status and timing totals |

All time values are seconds relative to the first stimulus flip. Keyboard times use `psychopy.hardware.keyboard`; mouse times are sampled once per refresh. `since_dot_change_s` is descriptive and is **not** a hit/false-alarm classification. The script saves on ordinary completion, Escape, and handled Python exceptions; a process kill or power loss can prevent saving.

## Validation status

The package has passed nine automated tests, including all **606 subject/run schedules**, baseline alignment, refresh scheduling without accumulated drift, geometry, image-channel/alpha preservation, and simulated normal/stalled/aborted runs. All supplied PNGs have been decoded and checked against the source revision. See `VALIDATION.json` for the recorded asset checks.

**PsychoPy was not installed in the preparation environment. Actual PsychoPy rendering, display orientation, luminance calibration, response hardware and scanner synchronization have not been tested.** The simulated tests do not establish display timing accuracy. Before data collection, run on the acquisition computer, compare stimulus appearance/direction with the original, inspect the flip/error logs, and validate timing with your display/trigger equipment. No PsychoPy release is certified by this package.

To rerun the non-display tests (only NumPy and Pillow are required):

```shell
python -m unittest -v test_retinotopy.py
```

Relevant PsychoPy APIs: [ImageStim](https://psychopy.org/api/visual/imagestim.html), [Window/flip](https://psychopy.org/api/visual/window.html), [Keyboard](https://psychopy.org/api/hardware/keyboard.html).

## Attribution and license

Original Go implementation and assets: Christophe Pallier, 2026; upstream also credits Claude Sonnet 4.6. This Python port was created with OpenAI Codex on 28 September 2026. Distributed under **GNU GPL version 3**, following the upstream license declaration; see `LICENSE`. Preserve the upstream attribution and any applicable stimulus-source terms when redistributing.

The upstream experiment references Benson et al. (2018), *The Human Connectome Project 7 Tesla retinotopy dataset: Description and population receptive field analysis*, Journal of Vision 18(13), 23. [DOI: 10.1167/18.13.23](https://doi.org/10.1167/18.13.23).
