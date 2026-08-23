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


# Cue timing on import: a structure needs money banked and a worker walked to
# the spot, so its cue comes earlier than a unit's. The first of each tech
# structure additionally gets a spoken heads-up (warn) well in advance -
# that's the "commitment" moment of a build.
LEAD_STRUCTURE = 8.0
LEAD_SUPPLY = 6.0
LEAD_UNIT = 4.0
WARN_FIRST_TECH = 15.0

SUPPLY_NAMES = {"SupplyDepot", "Pylon", "Overlord"}
STRUCTURE_NAMES = {
    # Terran
    "CommandCenter", "OrbitalCommand", "PlanetaryFortress", "Refinery",
    "Barracks", "EngineeringBay", "Bunker", "SensorTower", "MissileTurret",
    "Factory", "GhostAcademy", "Starport", "Armory", "FusionCore",
    "TechLab", "Reactor", "BarracksTechLab", "BarracksReactor",
    "FactoryTechLab", "FactoryReactor", "StarportTechLab", "StarportReactor",
    # Zerg
    "Hatchery", "Lair", "Hive", "SpawningPool", "Extractor",
    "EvolutionChamber", "RoachWarren", "BanelingNest", "SpineCrawler",
    "SporeCrawler", "HydraliskDen", "LurkerDen", "Spire", "GreaterSpire",
    "NydusNetwork", "InfestationPit", "UltraliskCavern",
    # Protoss
    "Nexus", "Assimilator", "Gateway", "WarpGate", "Forge",
    "CyberneticsCore", "PhotonCannon", "ShieldBattery", "RoboticsFacility",
    "Stargate", "TwilightCouncil", "RoboticsBay", "FleetBeacon",
    "TemplarArchives", "DarkShrine",
}


def _cue_timing(name: str, seen_structures: set) -> tuple:
    """(lead, warn) for an imported step."""
    if name in SUPPLY_NAMES:
        return LEAD_SUPPLY, 0.0
    if name in STRUCTURE_NAMES:
        first = name not in seen_structures
        seen_structures.add(name)
        return LEAD_STRUCTURE, WARN_FIRST_TECH if first else 0.0
    return LEAD_UNIT, 0.0


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
    seen_structures: set = set()
    for entry in pdata.get("buildOrder", []):
        if entry.get("is_chronoboosted") is True and not entry.get("name"):
            continue
        if not include_workers and entry.get("is_worker"):
            continue
        seconds = parse_time(entry.get("time", 0))
        if until is not None and seconds > until:
            break
        supply = entry.get("supply")
        name = str(entry.get("name", "?"))
        lead, warn = _cue_timing(name, seen_structures)
        steps.append(
            BuildStep(
                time=seconds,
                action=name,
                supply=int(supply) if supply is not None else None,
                kind="build",
                lead=lead,
                warn=warn,
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
