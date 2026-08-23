from sc2copilot.models import Build, BuildStep
from sc2copilot.practice.coach import CueScheduler, run_coach


def make_build():
    return Build(
        name="test",
        steps=[
            BuildStep(time=17, action="Supply Depot", lead=5),
            BuildStep(time=38, action="Send proxy SCVs", kind="move", lead=3),
            BuildStep(time=48, action="Barracks", lead=5),
        ],
    )


def test_scheduler_fires_at_lead_time():
    sched = CueScheduler(make_build())
    assert sched.advance(0) == []
    assert sched.advance(11.9) == []
    due = sched.advance(12.0)  # 17 - lead 5
    assert [s.action for s in due] == ["Supply Depot"]


def test_scheduler_fires_each_step_once():
    sched = CueScheduler(make_build())
    fired = []
    t = 0.0
    while t < 60:
        fired.extend(s.action for s in sched.advance(t))
        t += 0.25
    assert fired == ["Supply Depot", "Send proxy SCVs", "Barracks"]
    assert sched.done


def test_scheduler_catches_up_after_clock_jump():
    sched = CueScheduler(make_build())
    due = sched.advance(50)
    assert [s.action for s in due] == ["Supply Depot", "Send proxy SCVs", "Barracks"]


def test_scheduler_resets_on_backwards_clock():
    sched = CueScheduler(make_build())
    sched.advance(50)
    assert sched.done
    due = sched.advance(12)  # new game started
    assert [s.action for s in due] == ["Supply Depot"]
    assert not sched.done


class RecordingAnnouncer:
    def __init__(self):
        self.messages = []

    def announce(self, game_time, text):
        self.messages.append((game_time, text))


def test_run_coach_with_fake_clock():
    times = iter([None, 0.0, 12.0, 35.0, 43.0, 50.0, 60.0])
    last = [0.0]

    def clock():
        try:
            last[0] = next(times)
        except StopIteration:
            pass
        return last[0]

    announcer = RecordingAnnouncer()
    run_coach(make_build(), announcer, clock, sleep=lambda _: None)
    texts = [t for _, t in announcer.messages]
    assert any("Supply Depot" in t for t in texts)
    assert any("proxy SCVs" in t for t in texts)
    assert any("Barracks" in t for t in texts)
    assert "complete" in texts[-1].lower()


def test_run_coach_stops_when_asked():
    announcer = RecordingAnnouncer()
    calls = [0]

    def should_stop():
        calls[0] += 1
        return calls[0] > 3

    run_coach(make_build(), announcer, clock=lambda: 0.0, sleep=lambda _: None, should_stop=should_stop)
    # stopped before any cue time was reached; only the intro message
    assert len(announcer.messages) == 1


def test_run_coach_gives_up_without_game():
    announcer = RecordingAnnouncer()
    run_coach(make_build(), announcer, clock=lambda: None, sleep=lambda _: None, max_wait=1.0)
    # only the intro message; no cues fired
    assert len(announcer.messages) == 1
