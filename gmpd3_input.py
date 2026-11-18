"""Current Designs GMPD3 button input for a PsychoPy experiment."""
import os
from time import monotonic, sleep

# SDL joystick indices from tomov/fmri-gym, current_designs_gamepad3.py.
BUTTONS = ("Y", "B", "X", "LT", "A", "RT")


class Gamepad:
    def __init__(self, index=-1):
        os.environ.setdefault("SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", "1")
        import pygame
        from pygame._sdl2 import controller

        self.pg = pygame
        pygame.display.init()
        pygame.joystick.init()
        controller.init()
        deadline = monotonic() + 0.5
        while not pygame.joystick.get_count() and monotonic() < deadline:
            pygame.event.pump()
            sleep(0.02)
        sticks = [pygame.joystick.Joystick(i) for i in range(pygame.joystick.get_count())]
        candidates = [i for i, stick in enumerate(sticks)
                      if stick.get_numbuttons() >= 6 and stick.get_numaxes() >= 2
                      and (i == index or (index == -1 and not controller.is_controller(i)))]
        if len(candidates) != 1:
            names = [(i, s.get_name()) for i, s in enumerate(sticks)]
            raise RuntimeError(f"Select one GMPD3 in 932 joystick mode. SDL devices: {names}. "
                               "Set the GMPD3 device index if needed.")
        self.index = candidates[0]
        self.stick = sticks[self.index]
        self.name = self.stick.get_name()
        self.instance = self.stick.get_instance_id()

    def read(self):
        pg = self.pg
        presses = []
        for event in pg.event.get():
            if getattr(event, "instance_id", None) != self.instance:
                continue
            if event.type == pg.JOYDEVICEREMOVED:
                raise RuntimeError(f"GMPD3 disconnected: {self.name}")
            if event.type == pg.JOYBUTTONDOWN and 0 <= event.button < len(BUTTONS):
                presses.append(BUTTONS[event.button])
        return presses

    def close(self):
        self.stick.quit()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Show GMPD3 button presses. Ctrl+C exits.")
    parser.add_argument("--gamepad-index", type=int, default=-1)
    pad = Gamepad(parser.parse_args().gamepad_index)
    try:
        print(f"Ready: {pad.name} (index {pad.index})", flush=True)
        while True:
            for button in pad.read():
                print(button, flush=True)
            sleep(0.005)
    except KeyboardInterrupt:
        pass
    finally:
        pad.close()
