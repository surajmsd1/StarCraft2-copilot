from sc2copilot.analyze.compare import compare, render_report
from sc2copilot.models import Benchmark, Build, BuildStep


def planned():
    return Build(
        name="plan",
        steps=[
            BuildStep(time=17, action="Supply Depot"),
            BuildStep(time=38, action="Send proxy SCVs", kind="move"),
            BuildStep(time=48, action="Barracks"),
            BuildStep(time=65, action="Barracks"),
            BuildStep(time=95, action="Reaper"),
        ],
    )


def actual():
    return Build(
        name="actual",
        steps=[
            BuildStep(time=18, action="SupplyDepot"),
            BuildStep(time=52, action="Barracks"),
            BuildStep(time=80, action="Barracks"),
            BuildStep(time=140, action="Marine"),
        ],
        benchmarks=[Benchmark("First blood", 155, "Killed enemy SCV")],
    )


def test_compare_matches_in_order_with_normalized_names():
    comparison = compare(planned(), actual())
    by_action = {r.planned.action: r for r in comparison.results if r.planned.kind == "build"}
    assert by_action["Supply Depot"].matched
    assert abs(by_action["Supply Depot"].delta - 1.0) < 1e-9
    reaper = [r for r in comparison.results if r.planned.action == "Reaper"][0]
    assert not reaper.matched  # never built one


def test_duplicate_actions_consume_distinct_candidates():
    comparison = compare(planned(), actual())
    rax = [r for r in comparison.results if r.planned.action == "Barracks"]
    assert [r.actual_time for r in rax] == [52, 80]


def test_move_steps_not_judged():
    comparison = compare(planned(), actual())
    move = [r for r in comparison.results if r.planned.kind == "move"][0]
    assert not move.matched
    assert comparison.comparable_count == 4  # move step excluded


def test_extra_actions_reported():
    comparison = compare(planned(), actual())
    assert [s.action for s in comparison.extra_actions] == ["Marine"]


def test_far_off_timing_does_not_match():
    plan = Build(name="p", steps=[BuildStep(time=10, action="Barracks")])
    act = Build(name="a", steps=[BuildStep(time=300, action="Barracks")])
    comparison = compare(plan, act)
    assert not comparison.results[0].matched


def test_render_report_smoke():
    report = render_report(compare(planned(), actual()))
    assert "MISS" in report
    assert "First blood" in report
    assert "2:35" in report
    assert "Marine" in report
