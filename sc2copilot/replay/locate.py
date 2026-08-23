"""Find the player's replay folder and the newest replay automatically.

Standard location on Windows:
  Documents/StarCraft II/Accounts/<account>/<handle>/Replays/Multiplayer
Documents is sometimes redirected into OneDrive, so both roots are checked.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional


def find_replay_dirs(home: Optional[Path] = None) -> List[Path]:
    home = home or Path.home()
    roots = [
        home / "Documents" / "StarCraft II" / "Accounts",
        home / "OneDrive" / "Documents" / "StarCraft II" / "Accounts",
    ]
    dirs: List[Path] = []
    for root in roots:
        if root.is_dir():
            dirs.extend(p for p in root.glob("*/*/Replays/Multiplayer") if p.is_dir())
    return dirs


def newest_replay(dirs: Optional[List[Path]] = None) -> Optional[Path]:
    if dirs is None:
        dirs = find_replay_dirs()
    replays = [p for d in dirs for p in d.glob("*.SC2Replay")]
    if not replays:
        return None
    return max(replays, key=lambda p: p.stat().st_mtime)
