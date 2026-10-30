"""main.py turns alia-engine input actions into the RawInput the game reads."""

import g3d
from main import ACTIONS, raw_input


class FakeActions:
    def __init__(self, held=(), pressed=(), ride=(0.0, 0.0), look=(0.0, 0.0)):
        self.h, self.p, self.axes = set(held), set(pressed), {"ride": ride, "look": look}

    def held(self, name):
        return name in self.h

    def pressed(self, name):
        return name in self.p

    def axis(self, name):
        return self.axes[name]


def test_actions_become_game_buttons_and_sticks():
    raw = raw_input(FakeActions(held={"shoot", "hook"}, pressed={"pause"}, ride=(0.5, -1.0), look=(-1.0, 0.25)), 9)
    assert raw.held == g3d.BTN_B | g3d.BTN_C and raw.pressed == g3d.BTN_START and raw.seq_ack == 9
    assert (raw.jx, raw.jy, raw.rx, raw.ry) == (64, 127, -127, -32)  # stick up (-y) reads positive


def test_every_action_is_bound():
    assert {"confirm", "shoot", "hook", "stick", "pause", "ride", "look"} == set(ACTIONS)
