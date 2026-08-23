"""Announce cues: always to the sink (console/GUI), out loud when possible.

Speaking the cues is deliberate: hearing "reapers should be at their ramp,
one-thirty" every game is how the timings migrate from the tool into your
head - the point is to eventually not need the tool.

Voice backends, most reliable first per platform:
  Windows - the built-in speech engine driven through PowerShell
            (System.Speech). No third-party packages, no COM threading
            issues; one short-lived hidden process per cue.
  macOS   - the built-in `say` command.
  other   - pyttsx3 if installed (initialized INSIDE the speaking thread;
            SAPI/espeak engines refuse cross-thread use).

All speech happens on one worker thread fed by a queue, so cues never block
the coach loop and never overlap each other.
"""

from __future__ import annotations

import importlib.util
import queue
import shutil
import subprocess
import sys
import threading

from ..models import format_time


def _detect_backend() -> str:
    if sys.platform == "win32" and shutil.which("powershell"):
        return "windows"
    if sys.platform == "darwin" and shutil.which("say"):
        return "macos"
    if importlib.util.find_spec("pyttsx3") is not None:
        return "pyttsx3"
    return "none"


class Announcer:
    def __init__(self, use_tts: bool = True, sink=None):
        """sink: callable(str) that receives each cue line; default prints.
        A GUI passes its own sink to show cues in-window."""
        self._sink = sink or (lambda line: print(line, flush=True))
        self._queue: "queue.Queue[str]" = queue.Queue()
        self.backend = _detect_backend() if use_tts else "off"
        if self.backend not in ("none", "off"):
            threading.Thread(target=self._speech_loop, daemon=True).start()

    @property
    def tts_available(self) -> bool:
        return self.backend not in ("none", "off")

    def describe_voice(self) -> str:
        return {
            "windows": "Windows speech",
            "macos": "macOS speech",
            "pyttsx3": "pyttsx3",
            "none": "unavailable (no speech engine found)",
            "off": "off",
        }[self.backend]

    def announce(self, game_time: float, text: str) -> None:
        self._sink(f"[{format_time(game_time)}] {text}")
        if self.tts_available:
            self._queue.put(text)

    def test_voice(self) -> None:
        self._queue.put("Voice check. Supply depot at 17 seconds.")

    # ---------- speech worker ----------

    def _speech_loop(self) -> None:
        speak = self._make_speaker()
        while True:
            text = self._queue.get()
            try:
                speak(text)
            except Exception:
                pass

    def _make_speaker(self):
        if self.backend == "windows":
            no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)

            def speak(text: str) -> None:
                safe = text.replace("'", "''")
                subprocess.run(
                    [
                        "powershell", "-NoProfile", "-Command",
                        "Add-Type -AssemblyName System.Speech; "
                        "$v = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                        f"$v.Rate = 1; $v.Speak('{safe}')",
                    ],
                    creationflags=no_window,
                    timeout=30,
                )

            return speak

        if self.backend == "macos":
            return lambda text: subprocess.run(["say", text], timeout=30)

        # pyttsx3: engine must be created on this thread (its SAPI/espeak
        # drivers are single-apartment and go silent if used cross-thread).
        try:
            import pyttsx3

            engine = pyttsx3.init()

            def speak(text: str) -> None:
                engine.say(text)
                engine.runAndWait()

            return speak
        except Exception:
            self.backend = "none"
            return lambda text: None
