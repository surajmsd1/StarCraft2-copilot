"""Read live game state from the SC2 client's built-in localhost API.

The StarCraft 2 client serves a small read-only HTTP API on
http://127.0.0.1:6119 whenever it is running (it powers stream overlays and
tools like SC2ReplayStats):

  /ui    -> {"activeScreens": [...]}          empty list means "in a game"
  /game  -> {"isReplay": bool, "displayTime": float, "players": [...]}

displayTime is the number the in-game clock shows, so cues synced to it are
correct through pauses and lag. Polling this API is passive - no injection,
no memory reading, no automation - which is why this approach is safe to run
during ranked ladder games.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import List, Optional

DEFAULT_BASE_URL = "http://127.0.0.1:6119"


@dataclass
class GameState:
    in_game: bool
    is_replay: bool = False
    display_time: float = 0.0
    players: List[dict] = field(default_factory=list)


class SC2ClientAPI:
    """Thin poller over the client API. One instance per SC2 client."""

    def __init__(self, base_url: str = DEFAULT_BASE_URL, timeout: float = 1.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _get(self, path: str) -> Optional[dict]:
        try:
            with urllib.request.urlopen(self.base_url + path, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, ValueError):
            return None

    def is_running(self) -> bool:
        return self._get("/ui") is not None

    def poll(self) -> Optional[GameState]:
        """Return current state, or None if the SC2 client is not reachable."""
        ui = self._get("/ui")
        if ui is None:
            return None
        game = self._get("/game") or {}
        in_game = ui.get("activeScreens") == [] and bool(game.get("players"))
        return GameState(
            in_game=in_game,
            is_replay=bool(game.get("isReplay", False)),
            display_time=float(game.get("displayTime", 0.0) or 0.0),
            players=list(game.get("players", [])),
        )
