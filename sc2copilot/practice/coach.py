"""The practice coach: fire build cues against the live game clock.

The coach never looks at what you actually did in-game (that would require
game-state access that is not available in ranked matches); it is a metronome
keyed to the real in-game clock. What you *actually* did is judged afterwards
from the replay by sc2copilot.analyze.

Design notes:
  - Each step announces once, `lead` seconds before its time (default 5s).
  - The clock is injected, so the same loop runs against the SC2 client API,
    a wall-clock simulation, or a fake clock in tests.
  - If the clock jumps backwards (new game, replay scrub), the coach resets.
"""

from __future__ import annotations

import time as _time
from typing import Callable, List, Optional

from ..models import Build, BuildStep, format_time
from .announce import speak_time
from .game_client import SC2ClientAPI


class CueScheduler:
    """Pure scheduling logic: given a monotonically advancing game clock,
    decide which cues fire now. Kept free of I/O so it is unit-testable."""

    def __init__(self, build: Build):
        self.build = build
        self._pending: List[BuildStep] = build.sorted_steps()
        self._fired: List[BuildStep] = []
        self._last_time: float = -1.0

    def reset(self) -> None:
        self._pending = self.build.sorted_steps()
        self._fired = []
        self._last_time = -1.0

    @property
    def done(self) -> bool:
        return not self._pending

    def advance(self, game_time: float) -> List[BuildStep]:
        """Return the steps whose cue window starts at or before game_time."""
        if game_time < self._last_time - 1.0:
            self.reset()
        self._last_time = game_time
        due: List[BuildStep] = []
        while self._pending and game_time >= self._pending[0].time - self._pending[0].lead:
            step = self._pending.pop(0)
            self._fired.append(step)
            due.append(step)
        return due


def run_coach(
    build: Build,
    announcer,
    clock: Callable[[], Optional[float]],
    poll_interval: float = 0.25,
    sleep: Callable[[float], None] = _time.sleep,
    max_wait: Optional[float] = None,
    should_stop: Callable[[], bool] = lambda: False,
    status: Callable[[str], None] = print,
) -> None:
    """Drive a CueScheduler off `clock` until the build is exhausted.

    clock() returns current in-game seconds, or None while no game is active.
    should_stop() lets a host (GUI, signal handler) cancel between polls.
    status() receives non-cue progress lines (waiting, gave up) so a GUI can
    surface them; cues themselves go through the announcer.
    """
    scheduler = CueScheduler(build)
    # Status lines are informational; only actual cues deserve the voice.
    announcer.announce(0, f"Practicing: {build.name} ({len(build.steps)} cues)", spoken="-")
    waited = 0.0
    waiting_said = False
    while not scheduler.done:
        if should_stop():
            return
        now = clock()
        if now is None:
            if not waiting_said:
                status("Waiting for a game to start...")
                waiting_said = True
            waited += poll_interval
            if max_wait is not None and waited > max_wait:
                status("No game detected, giving up.")
                return
            sleep(poll_interval)
            continue
        waiting_said = False
        for step in scheduler.advance(now):
            early = step.time - now > 1.5
            text = f"{step.spoken_cue} at {format_time(step.time)}" if early else step.spoken_cue
            spoken = f"{step.spoken_cue}, {speak_time(step.time)}" if early else step.spoken_cue
            announcer.announce(now, text, spoken=spoken)
        sleep(poll_interval)
    announcer.announce(clock() or 0, "Build complete. Good luck out there.")


def live_clock(api: Optional[SC2ClientAPI] = None) -> Callable[[], Optional[float]]:
    """Clock backed by the SC2 client API; None until a live game is running."""
    api = api or SC2ClientAPI()

    def clock() -> Optional[float]:
        state = api.poll()
        if state is None or not state.in_game or state.is_replay:
            return None
        return state.display_time

    return clock


def sim_clock(speed: float = 1.0) -> Callable[[], Optional[float]]:
    """Wall-clock simulation for practicing cues without SC2 running."""
    start = _time.monotonic()

    def clock() -> Optional[float]:
        return (_time.monotonic() - start) * speed

    return clock
