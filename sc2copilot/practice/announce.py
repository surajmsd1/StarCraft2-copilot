"""Announce cues: always to the console, out loud when TTS is available.

Speaking the cues is deliberate: hearing "reapers should be at their ramp,
one-thirty" every game is how the timings migrate from the tool into your
head - the point is to eventually not need the tool.
"""

from __future__ import annotations

import queue
import threading

from ..models import format_time


class Announcer:
    def __init__(self, use_tts: bool = True):
        self._tts_queue: "queue.Queue[str]" = queue.Queue()
        self._engine = None
        if use_tts:
            self._engine = self._init_tts()
        if self._engine is not None:
            threading.Thread(target=self._tts_loop, daemon=True).start()

    def _init_tts(self):
        try:
            import pyttsx3

            return pyttsx3.init()
        except Exception:
            return None

    @property
    def tts_available(self) -> bool:
        return self._engine is not None

    def _tts_loop(self) -> None:
        while True:
            text = self._tts_queue.get()
            try:
                self._engine.say(text)
                self._engine.runAndWait()
            except Exception:
                pass

    def announce(self, game_time: float, text: str) -> None:
        print(f"[{format_time(game_time)}] {text}", flush=True)
        if self._engine is not None:
            self._tts_queue.put(text)
