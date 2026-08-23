"""Core data model: builds, steps, benchmarks.

A Build is the unit of everything in sc2copilot: it is what gets extracted
from a replay, what the practice coach reads cues from, and what post-game
review compares a new replay against. Builds serialize to plain JSON so they
can be hand-edited, shared, and diffed.

All times are in-game seconds as shown on the LotV in-game clock (which runs
at real-time speed on Faster). Replay frames convert at 22.4 frames/second.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional

FRAMES_PER_SECOND = 22.4  # LotV on Faster: 22.4 game frames per displayed second


def frames_to_seconds(frames: int) -> float:
    return frames / FRAMES_PER_SECOND


def format_time(seconds: float) -> str:
    seconds = int(round(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


def parse_time(value) -> float:
    """Accept 150, 150.0, "2:30", or "150" and return seconds."""
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if ":" in text:
        minutes, secs = text.split(":", 1)
        return int(minutes) * 60 + float(secs)
    return float(text)


@dataclass
class BuildStep:
    """One action in a build order.

    kind is a coarse category the coach and reviewer use:
      build   - structure or unit production (comparable against replay data)
      move    - map movement like sending proxy SCVs (cue-only; replays don't
                label intent, so these are matched heuristically or not at all)
      note    - anything else worth announcing (scout, drop, attack timing)
    """

    time: float
    action: str
    supply: Optional[int] = None
    count: int = 1
    kind: str = "build"
    cue: Optional[str] = None
    lead: float = 5.0  # announce this many seconds before `time`

    @property
    def spoken_cue(self) -> str:
        return self.cue or self.action

    def to_dict(self) -> dict:
        d = asdict(self)
        if d["supply"] is None:
            del d["supply"]
        if d["cue"] is None:
            del d["cue"]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "BuildStep":
        return cls(
            time=parse_time(d["time"]),
            action=d["action"],
            supply=d.get("supply"),
            count=int(d.get("count", 1)),
            kind=d.get("kind", "build"),
            cue=d.get("cue"),
            lead=float(d.get("lead", 5.0)),
        )


@dataclass
class Benchmark:
    """A named timing to hit (or that was hit), e.g. 'First blood' at 2:35."""

    name: str
    time: float
    description: str = ""

    def to_dict(self) -> dict:
        return {"name": self.name, "time": self.time, "description": self.description}

    @classmethod
    def from_dict(cls, d: dict) -> "Benchmark":
        return cls(name=d["name"], time=parse_time(d["time"]), description=d.get("description", ""))


@dataclass
class Build:
    name: str
    race: str = ""
    matchup: str = ""
    game_version: str = ""
    source_replay: str = ""
    notes: str = ""
    steps: List[BuildStep] = field(default_factory=list)
    benchmarks: List[Benchmark] = field(default_factory=list)

    def sorted_steps(self) -> List[BuildStep]:
        return sorted(self.steps, key=lambda s: s.time)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "race": self.race,
            "matchup": self.matchup,
            "game_version": self.game_version,
            "source_replay": self.source_replay,
            "notes": self.notes,
            "steps": [s.to_dict() for s in self.sorted_steps()],
            "benchmarks": [b.to_dict() for b in self.benchmarks],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Build":
        return cls(
            name=d["name"],
            race=d.get("race", ""),
            matchup=d.get("matchup", ""),
            game_version=d.get("game_version", ""),
            source_replay=d.get("source_replay", ""),
            notes=d.get("notes", ""),
            steps=[BuildStep.from_dict(s) for s in d.get("steps", [])],
            benchmarks=[Benchmark.from_dict(b) for b in d.get("benchmarks", [])],
        )

    def save(self, path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")

    @classmethod
    def load(cls, path) -> "Build":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
