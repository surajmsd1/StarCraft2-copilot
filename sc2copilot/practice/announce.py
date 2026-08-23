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
import re
import shutil
import subprocess
import sys
import threading

from ..models import format_time


def humanize(text: str) -> str:
    """Make replay-derived names speakable: 'SpawningPool' -> 'Spawning Pool'.

    Splits lowercase-to-uppercase boundaries only, so acronyms like SCV
    survive intact."""
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", text).replace("_", " ")


def speak_time(seconds: float) -> str:
    """Say a game time the way a person would: '48 seconds', '1 35', '2 minutes'."""
    seconds = int(round(seconds))
    if seconds < 60:
        return f"{seconds} seconds"
    minutes, secs = divmod(seconds, 60)
    if secs == 0:
        return f"{minutes} {'minute' if minutes == 1 else 'minutes'}"
    return f"{minutes} {secs:02d}"


def _detect_backend() -> str:
    if sys.platform == "win32" and shutil.which("powershell"):
        return "windows"
    if sys.platform == "darwin" and shutil.which("say"):
        return "macos"
    if importlib.util.find_spec("pyttsx3") is not None:
        return "pyttsx3"
    return "none"


class Announcer:
    def __init__(self, use_tts: bool = True, sink=None, voice: str = ""):
        """sink: callable(str) that receives each cue line; default prints.
        A GUI passes its own sink to show cues in-window.
        voice: name (or substring) of an installed system voice to use."""
        self._sink = sink or (lambda line: print(line, flush=True))
        self._queue: "queue.Queue[str]" = queue.Queue()
        self.voice = voice or ""
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

    def announce(self, game_time: float, text: str, spoken: str = "") -> None:
        """Show `text` in the sink; say `spoken` (or a humanized `text`) aloud.
        Pass spoken="-" to display without speaking (status lines, filenames)."""
        self._sink(f"[{format_time(game_time)}] {text}")
        if self.tts_available and spoken != "-":
            self._queue.put(humanize(spoken or text))

    def test_voice(self) -> None:
        self._queue.put("Voice check. Supply depot at 17 seconds.")

    def list_voices(self) -> list:
        """Names of installed system voices (Windows only for now)."""
        if self.backend != "windows":
            return []
        try:
            out = subprocess.run(
                [
                    "powershell", "-NoProfile", "-Command",
                    "Add-Type -AssemblyName System.Speech; "
                    "(New-Object System.Speech.Synthesis.SpeechSynthesizer)"
                    ".GetInstalledVoices() | ForEach-Object { $_.VoiceInfo.Name }",
                ],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                capture_output=True, text=True, timeout=20,
            )
            return [line.strip() for line in out.stdout.splitlines() if line.strip()]
        except Exception:
            return []

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
            select = ""
            if self.voice:
                safe_voice = self.voice.replace("'", "''")
                select = (
                    "$m = $v.GetInstalledVoices() | Where-Object "
                    f"{{ $_.VoiceInfo.Name -like '*{safe_voice}*' }} | Select-Object -First 1; "
                    "if ($m) { $v.SelectVoice($m.VoiceInfo.Name) }; "
                )

            def speak(text: str) -> None:
                safe = text.replace("'", "''")
                subprocess.run(
                    [
                        "powershell", "-NoProfile", "-Command",
                        "Add-Type -AssemblyName System.Speech; "
                        "$v = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                        f"{select}$v.Speak('{safe}')",
                    ],
                    creationflags=no_window,
                    timeout=30,
                )

            return speak

        if self.backend == "macos":
            args = ["say"] + (["-v", self.voice] if self.voice else [])
            return lambda text: subprocess.run(args + [text], timeout=30)

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
