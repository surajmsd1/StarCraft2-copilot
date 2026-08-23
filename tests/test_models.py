import json

from sc2copilot.models import (
    Benchmark,
    Build,
    BuildStep,
    format_time,
    frames_to_seconds,
    parse_time,
)


def test_parse_time_formats():
    assert parse_time(150) == 150.0
    assert parse_time("150") == 150.0
    assert parse_time("2:30") == 150.0
    assert parse_time("0:05") == 5.0


def test_format_time():
    assert format_time(155) == "2:35"
    assert format_time(5) == "0:05"
    assert format_time(0) == "0:00"


def test_frames_to_seconds_lotv_rate():
    assert abs(frames_to_seconds(224) - 10.0) < 1e-9


def test_build_roundtrip(tmp_path):
    build = Build(
        name="Test build",
        race="Terran",
        matchup="TvZ",
        steps=[
            BuildStep(time=17, action="Supply Depot", supply=14, cue="Depot now"),
            BuildStep(time=38, action="Send proxy SCVs", kind="move", lead=3),
        ],
        benchmarks=[Benchmark("First blood", 155, "test")],
    )
    path = tmp_path / "build.json"
    build.save(path)
    loaded = Build.load(path)
    assert loaded.name == "Test build"
    assert len(loaded.steps) == 2
    assert loaded.steps[0].supply == 14
    assert loaded.steps[1].kind == "move"
    assert loaded.steps[1].lead == 3
    assert loaded.benchmarks[0].time == 155


def test_steps_sorted_on_serialize(tmp_path):
    build = Build(name="b", steps=[BuildStep(time=60, action="B"), BuildStep(time=10, action="A")])
    path = tmp_path / "b.json"
    build.save(path)
    data = json.loads(path.read_text())
    assert [s["action"] for s in data["steps"]] == ["A", "B"]


def test_time_accepts_clock_strings_in_json(tmp_path):
    path = tmp_path / "b.json"
    path.write_text(json.dumps({"name": "b", "steps": [{"time": "2:35", "action": "Reaper"}]}))
    build = Build.load(path)
    assert build.steps[0].time == 155.0


def test_merge_batches_collapses_same_action_close_in_time():
    from sc2copilot.replay.extract import merge_batches

    steps = [
        BuildStep(time=134, action="Roach"),
        BuildStep(time=134, action="Roach"),
        BuildStep(time=135, action="Roach"),
        BuildStep(time=146, action="Roach"),   # > 3s after previous: own step
        BuildStep(time=156, action="Queen"),
    ]
    merged = merge_batches(steps)
    assert [(s.action, s.count) for s in merged] == [("Roach", 3), ("Roach", 1), ("Queen", 1)]
