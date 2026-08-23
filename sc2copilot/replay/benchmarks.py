"""Extract key timings from a replay that the in-game tab never shows you.

Examples of what comes out of here for a 4-reaper proxy opener:
  - "First blood" at 2:35 (your first kill of an enemy army unit/worker)
  - "Proxy Barracks started" at 0:51, flagged as a proxy by map position
  - "Proxy SCVs sent" at 0:19 (earliest order targeting the proxy site)
  - first-N combat unit timings ("Reaper #4" at 2:12)

Everything here reads tracker/game events via sc2reader. Attribute access is
defensive because event shapes shift across game patches and sc2reader
releases; a missing field should degrade to "benchmark absent", never crash
the import of a build.
"""

from __future__ import annotations

import math
from typing import List, Optional, Tuple

from ..models import Benchmark, frames_to_seconds

WORKER_TYPES = {"SCV", "Probe", "Drone"}
TOWNHALL_TYPES = {"CommandCenter", "Nexus", "Hatchery"}
SUPPLY_TYPES = {"SupplyDepot", "Pylon", "Overlord"}
# Distance (map units) within which a command target counts as "at" a site.
PROXY_CMD_RADIUS = 25.0


def distance(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def is_proxy_location(
    building_pos: Tuple[float, float],
    own_start: Tuple[float, float],
    enemy_start: Tuple[float, float],
) -> bool:
    """A structure is a proxy if it sits closer to the enemy than to you."""
    return distance(building_pos, enemy_start) < distance(building_pos, own_start)


def earliest_order_near(
    commands: List[Tuple[float, Tuple[float, float]]],
    site: Tuple[float, float],
    before: float,
    radius: float = PROXY_CMD_RADIUS,
) -> Optional[float]:
    """Earliest command time targeting within `radius` of `site` before `before`.

    commands: [(seconds, (x, y)), ...] of a player's targeted orders.
    This is the 'when did the proxy SCVs actually leave' heuristic: the move
    order across the map targets (roughly) the proxy site well before the
    structure starts.
    """
    hits = [t for t, pos in commands if t < before and distance(pos, site) <= radius]
    return min(hits) if hits else None


def _load_replay(replay_path: str):
    try:
        import sc2reader
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("sc2reader is not installed; run: pip install sc2reader") from exc
    return sc2reader.load_replay(replay_path, load_map=False)


def _find_player(replay, player_name: Optional[str]):
    players = [p for p in replay.players if not getattr(p, "is_observer", False)]
    if player_name:
        needle = player_name.lower()
        for p in players:
            if needle in p.name.lower():
                return p
    return players[0] if players else None


def _start_locations(replay) -> dict:
    """pid -> (x, y) of the starting townhall (born on frame 0)."""
    starts = {}
    for event in getattr(replay, "tracker_events", []):
        if type(event).__name__ != "UnitBornEvent":
            continue
        if event.frame > 0:
            break
        name = getattr(event, "unit_type_name", "")
        if name in TOWNHALL_TYPES:
            pid = getattr(event, "control_pid", None)
            starts[pid] = (float(event.x), float(event.y))
    return starts


def extract_benchmarks(replay_path: str, player_name: Optional[str] = None) -> List[Benchmark]:
    replay = _load_replay(replay_path)
    player = _find_player(replay, player_name)
    if player is None:
        return []
    pid = player.pid

    benchmarks: List[Benchmark] = []
    benchmarks.extend(_first_blood(replay, pid))
    benchmarks.extend(_combat_unit_timings(replay, pid))
    benchmarks.extend(_proxy_benchmarks(replay, pid))
    benchmarks.sort(key=lambda b: b.time)
    return benchmarks


def _first_blood(replay, pid) -> List[Benchmark]:
    for event in getattr(replay, "tracker_events", []):
        if type(event).__name__ != "UnitDiedEvent":
            continue
        killer = getattr(event, "killer_pid", None)
        unit = getattr(event, "unit", None)
        owner = getattr(getattr(unit, "owner", None), "pid", None)
        if killer != pid or owner in (None, pid):
            continue
        name = getattr(unit, "name", None) or "enemy unit"
        seconds = frames_to_seconds(event.frame)
        return [Benchmark("First blood", seconds, f"Killed enemy {name}")]
    return []


def _combat_unit_timings(replay, pid, per_type: int = 4) -> List[Benchmark]:
    """Timing of the first few of each combat unit type (e.g. Reaper #1..#4)."""
    counts: dict = {}
    out: List[Benchmark] = []
    for event in getattr(replay, "tracker_events", []):
        if type(event).__name__ != "UnitBornEvent":
            continue
        if getattr(event, "control_pid", None) != pid or event.frame == 0:
            continue
        name = getattr(event, "unit_type_name", "")
        if not name or name in WORKER_TYPES or name in SUPPLY_TYPES:
            continue
        unit = getattr(event, "unit", None)
        if unit is not None and not (getattr(unit, "is_army", False)):
            continue
        counts[name] = counts.get(name, 0) + 1
        if counts[name] <= per_type:
            out.append(
                Benchmark(
                    f"{name} #{counts[name]}",
                    frames_to_seconds(event.frame),
                    f"{name} number {counts[name]} completed",
                )
            )
    return out


def _proxy_benchmarks(replay, pid) -> List[Benchmark]:
    starts = _start_locations(replay)
    own_start = starts.get(pid)
    enemy_starts = [pos for p, pos in starts.items() if p != pid]
    if own_start is None or not enemy_starts:
        return []
    enemy_start = enemy_starts[0]

    commands: List[Tuple[float, Tuple[float, float]]] = []
    for event in getattr(replay, "game_events", []):
        if "TargetPointCommandEvent" not in type(event).__name__:
            continue
        if getattr(getattr(event, "player", None), "pid", None) != pid:
            continue
        loc = getattr(event, "location", None)
        if loc is None:
            continue
        commands.append((frames_to_seconds(event.frame), (float(loc[0]), float(loc[1]))))

    out: List[Benchmark] = []
    for event in getattr(replay, "tracker_events", []):
        if type(event).__name__ != "UnitInitEvent":
            continue
        if getattr(event, "control_pid", None) != pid:
            continue
        pos = (float(event.x), float(event.y))
        if not is_proxy_location(pos, own_start, enemy_start):
            continue
        name = getattr(event, "unit_type_name", "structure")
        started = frames_to_seconds(event.frame)
        out.append(Benchmark(f"Proxy {name} started", started, f"At {pos[0]:.0f},{pos[1]:.0f}"))
        sent = earliest_order_near(commands, pos, before=started)
        if sent is not None:
            out.append(
                Benchmark(
                    f"Proxy workers sent ({name})",
                    sent,
                    "Earliest order targeting the proxy site",
                )
            )
    return out
