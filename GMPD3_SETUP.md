# Retinotopy with the Current Designs GMPD3

Copy the three Python application files beside the existing assets folder in a copy of the retinotopy repository. This variant uses the six physical buttons for the fixation task. Set the Current Designs 932 interface to USB joystick mode. Install pygame 2 in the same Python environment that launches PsychoPy:

    python3 -m pip install "pygame>=2,<3"

Check the controller without starting PsychoPy or loading VPixx:

    python3 gmpd3_input.py

Press the six buttons, confirm Y, B, X, LT, A and RT, then exit with Ctrl+C. The mapping follows https://github.com/tomov/fmri-gym/blob/main/humans/inputs/current_designs_gamepad3.py . SDL indices 0 through 5 correspond to those six labels respectively. Stick movement is ignored. For multiple eligible devices, specify the index printed in the device list with --gamepad-index N or in the experiment dialog.

    python3 retinotopy_scanner.py --duration 30

At Glasgow, enable “Use VPixx for scanner trigger” and select the projector display and your validated DIN settings. At other labs, disable the checkbox. A blank start key uses Space. For scanners that emit keyboard pulses, enter the actual key (e.g. 5). Skip initial scanner pulses applies to TTL or a configured keyboard pulse, while a manual Space start needs one press. Other trigger interfaces require their own adapter. Leave duration blank for a full run.

Participant presses appear in *_responses.csv with kind gmpd3_press and key identifying the button. Time is the host polling time relative to the first flip, with frame-level timing quantisation. With VPixx enabled, *_scanner.csv records trigger edges. With a configured keyboard trigger, subsequent keyboard pulses appear in *_responses.csv as trigger events. The projector uses the normal PsychoPy display selection in either mode. Only VPixx sites require pypixxlib.

From the project folder, run the synthetic tests with python3 -m unittest -v test_scanner.
