"""Compare a planned Build against what actually happened in a replay.

This is the "clearly show in the next game what you did in your previous
game" piece: after a ladder game, run the freshest replay against the build
you were practicing and get per-step deltas, missed steps, and benchmark
timings (first blood, proxy send, unit counts).

Matching model: steps are matched by action name, in order, within a time
window. Replays don't record intent, so `move`/`note` steps (send proxy
SCVs, scout now) are never marked missed - they only show as planned
reference lines unless a matching benchmark exists.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from ..models import Benchmark, Build, BuildStep, format_time

MATCH_WINDOW = 90.0  # seconds a real step may drift from plan and still match


@dataclass
class StepResult:
    planned: BuildStep
    actual_time: Optional[float] = None

    @property
    def matched(self) -> bool:
        return self.actual_time is not None

    @property
    def delta(self) -> Optional[float]:
        if self.actual_time is None:
            return None
        return self.actual_time - self.planned.time


@dataclass
class Comparison:
    build_name: str
    results: List[StepResult] = field(default_factory=list)
    extra_actions: List[BuildStep] = field(default_factory=list)
    benchmarks: List[Benchmark] = field(default_factory=list)

    @property
    def matched_count(self) -> int:
        return sum(1 for r in self.results if r.matched)

    @property
    def comparable_count(self) -> int:
        return sum(1 for r in self.results if r.planned.kind == "build")

    def average_delay(self) -> Optional[float]:
        deltas = [r.delta for r in self.results if r.delta is not None]
        if not deltas:
            return None
        return sum(deltas) / len(deltas)


def compare(planned: Build, actual: Build) -> Comparison:
    """Match planned steps to the actual (replay-extracted) build in order."""
    comparison = Comparison(build_name=planned.name, benchmarks=list(actual.benchmarks))
    remaining = actual.sorted_steps()

    for step in planned.sorted_steps():
        result = StepResult(planned=step)
        if step.kind == "build":
            idx = _find_match(step, remaining)
            if idx is not None:
                result.actual_time = remaining.pop(idx).time
        comparison.results.append(result)

    comparison.extra_actions = remaining
    return comparison


def _find_match(step: BuildStep, candidates: List[BuildStep]) -> Optional[int]:
    best_idx, best_dist = None, None
    for i, cand in enumerate(candidates):
        if not _names_equal(step.action, cand.action):
            continue
        dist = abs(cand.time - step.time)
        if dist > MATCH_WINDOW:
            continue
        if best_dist is None or dist < best_dist:
            best_idx, best_dist = i, dist
    return best_idx


def _names_equal(a: str, b: str) -> bool:
    norm = lambda s: "".join(ch for ch in s.lower() if ch.isalnum())
    return norm(a) == norm(b)


def render_report(comparison: Comparison) -> str:
    """Human-readable post-game report."""
    lines = [f"Build review: {comparison.build_name}", "=" * (14 + len(comparison.build_name)), ""]

    lines.append("Build order execution:")
    for r in comparison.results:
        plan_t = format_time(r.planned.time)
        label = r.planned.action
        if r.planned.kind != "build":
            lines.append(f"  ~    {plan_t}  {label}  (cue-only, not judged from replay)")
        elif not r.matched:
            lines.append(f"  MISS {plan_t}  {label}  (not found in replay)")
        else:
            delta = r.delta or 0.0
            sign = "+" if delta >= 0 else "-"
            flag = "OK  " if abs(delta) <= 5 else ("LATE" if delta > 0 else "EARLY".ljust(4))
            lines.append(
                f"  {flag} {plan_t}  {label}  actual {format_time(r.actual_time)}"
                f" ({sign}{abs(delta):.0f}s)"
            )

    if comparison.extra_actions:
        lines.append("")
        lines.append("Not in the plan (improvised):")
        for step in comparison.extra_actions[:15]:
            lines.append(f"       {format_time(step.time)}  {step.action}")
        if len(comparison.extra_actions) > 15:
            lines.append(f"       ... and {len(comparison.extra_actions) - 15} more")

    if comparison.benchmarks:
        lines.append("")
        lines.append("Key timings this game:")
        for b in comparison.benchmarks:
            desc = f"  ({b.description})" if b.description else ""
            lines.append(f"       {format_time(b.time)}  {b.name}{desc}")

    avg = comparison.average_delay()
    lines.append("")
    lines.append(
        f"Matched {comparison.matched_count}/{comparison.comparable_count} build steps."
        + (f" Average drift: {avg:+.0f}s." if avg is not None else "")
    )
    return "\n".join(lines)
