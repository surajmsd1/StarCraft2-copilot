"""Turn a replay into a Build.

This is the answer to "people don't like inputting their build order":
play the build once (or grab a pro replay), point sc2copilot at the file,
and the build order becomes a practice-ready Build JSON.

spawningtool does the heavy lifting of build-order extraction (it powers
spawningtool.com and tracks game-version quirks); we normalize its output
into our Build model and enrich it with benchmarks from the tracker events.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from ..models import Build, BuildStep, parse_time
from .benchmarks import extract_benchmarks


class ExtractionError(RuntimeError):
    pass


def _load_spawningtool(replay_path: str) -> dict:
    try:
        import spawningtool.parser
    except ImportError as exc:  # pragma: no cover
        raise ExtractionError(
            "spawningtool is not installed; run: pip install spawningtool"
        ) from exc
    return spawningtool.parser.parse_replay(replay_path)


def list_players(replay_path: str) -> List[dict]:
    """Return [{pid, name, race}] for the replay, for player selection UIs."""
    parsed = _load_spawningtool(replay_path)
    players = []
    for pid, pdata in sorted(parsed.get("players", {}).items()):
        players.append(
            {"pid": pid, "name": pdata.get("name", ""), "race": pdata.get("race", "")}
        )
    return players


def _pick_player(parsed: dict, player: Optional[str]) -> tuple:
    """Pick the player whose build we extract; by name substring, else pid 1."""
    players = parsed.get("players", {})
    if not players:
        raise ExtractionError("No players found in replay")
    if player:
        needle = player.lower()
        for pid, pdata in players.items():
            if needle in str(pdata.get("name", "")).lower():
                return pid, pdata
        raise ExtractionError(
            f"Player '{player}' not found; players: "
            + ", ".join(str(p.get("name")) for p in players.values())
        )
    pid = sorted(players)[0]
    return pid, players[pid]


def extract_build(
    replay_path: str,
    player: Optional[str] = None,
    until: Optional[float] = None,
    include_workers: bool = False,
) -> Build:
    """Extract a Build from a replay.

    until: cut the build order off after this many in-game seconds (openers
    are usually the first 3-5 minutes; the rest is reactive macro).
    include_workers: keep worker production steps (off by default; constant
    worker production is better trained as a habit than as cues).
    """
    parsed = _load_spawningtool(replay_path)
    pid, pdata = _pick_player(parsed, player)

    steps: List[BuildStep] = []
    for entry in pdata.get("buildOrder", []):
        if entry.get("is_chronoboosted") is True and not entry.get("name"):
            continue
        if not include_workers and entry.get("is_worker"):
            continue
        seconds = parse_time(entry.get("time", 0))
        if until is not None and seconds > until:
            break
        supply = entry.get("supply")
        steps.append(
            BuildStep(
                time=seconds,
                action=str(entry.get("name", "?")),
                supply=int(supply) if supply is not None else None,
                kind="build",
            )
        )

    build = Build(
        name=f"{pdata.get('race', '?')} build from {Path(replay_path).stem}",
        race=str(pdata.get("race", "")),
        matchup=_matchup(parsed, pid),
        game_version=str(parsed.get("game_version") or parsed.get("build", "")),
        source_replay=Path(replay_path).name,
        steps=steps,
    )

    try:
        build.benchmarks = extract_benchmarks(replay_path, player_name=pdata.get("name"))
    except Exception as exc:
        # Benchmarks are enrichment; a tracker-event quirk on a new patch
        # should not block getting the build order out.
        build.notes = f"Benchmark extraction failed: {exc}"

    return build


def _matchup(parsed: dict, pid) -> str:
    races = []
    me = None
    for p, pdata in sorted(parsed.get("players", {}).items()):
        letter = str(pdata.get("race", "?"))[:1]
        if p == pid:
            me = letter
        else:
            races.append(letter)
    if me is None:
        return ""
    return me + "v" + "".join(races)
