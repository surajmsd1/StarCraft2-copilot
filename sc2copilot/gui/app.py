"""Point-and-click front end (Tkinter, ships with Python - no extra installs).

Layout:
  left   - your build library (JSON files in ~/SC2Copilot/builds)
  right  - activity log: cues while coaching, reports after review
  bottom - Start/Stop coaching, Review newest replay, auto-review toggle,
           and a live SC2-client status line

Threading rule: all SC2/replay work happens on daemon threads; results are
posted to a queue and drained on the Tk main loop (Tk is not thread-safe).
"""

from __future__ import annotations

import queue
import shutil
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ..models import Build, format_time
from ..practice.announce import Announcer
from ..practice.coach import live_clock, run_coach
from ..practice.game_client import SC2ClientAPI
from ..replay.locate import find_replay_dirs, newest_replay

APP_DIR = Path.home() / "SC2Copilot"
BUILDS_DIR = APP_DIR / "builds"
ERROR_LOG = APP_DIR / "gui-error.log"
SETTINGS_FILE = APP_DIR / "settings.json"


def load_settings() -> dict:
    try:
        import json

        return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_settings(settings: dict) -> None:
    try:
        import json

        SETTINGS_FILE.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    except Exception:
        pass
EXAMPLE_BUILD = Path(__file__).resolve().parent.parent / "data" / "builds" / "example-proxy-4-reaper.json"


def ensure_dirs() -> None:
    BUILDS_DIR.mkdir(parents=True, exist_ok=True)
    example_dest = BUILDS_DIR / EXAMPLE_BUILD.name
    if EXAMPLE_BUILD.exists() and not example_dest.exists():
        shutil.copy(EXAMPLE_BUILD, example_dest)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("SC2 Copilot")
        self.geometry("860x560")
        self.minsize(700, 420)

        self.events: "queue.Queue[tuple]" = queue.Queue()
        self.coach_stop = threading.Event()
        self.coach_thread = None
        self.announcer = None
        self.replay_dirs = find_replay_dirs()
        self.last_reviewed: Path = newest_replay(self.replay_dirs) or Path("")

        self._build_widgets()
        self._refresh_builds()
        self._log("How this works:")
        self._log(" 1. Import a replay (yours or a pro's) - its opener becomes a build, listed on the left.")
        self._log("    When it asks whose build, pick YOUR name to practice your own play.")
        self._log(" 2. Select a build, press Start Coaching, then go play a match in StarCraft II.")
        self._log("    During the game each step is called out just before its time.")
        self._log(" 3. When the game ends, the review appears here by itself: what was late, missed,")
        self._log("    and key timings like first blood.")
        if not self.replay_dirs:
            self._log("Replay folder not auto-detected - use 'Import replay file...' to browse.")

        threading.Thread(target=self._status_loop, daemon=True).start()
        threading.Thread(target=self._auto_review_loop, daemon=True).start()
        self.after(100, self._drain_events)

    # ---------- layout ----------

    def _build_widgets(self) -> None:
        root = ttk.Frame(self, padding=8)
        root.pack(fill="both", expand=True)

        main = ttk.Frame(root)
        main.pack(fill="both", expand=True)

        left = ttk.Frame(main)
        left.pack(side="left", fill="y", padx=(0, 8))
        ttk.Label(left, text="My builds").pack(anchor="w")
        self.build_list = tk.Listbox(left, width=36, exportselection=False)
        self.build_list.pack(fill="y", expand=True)
        self.build_list.bind("<<ListboxSelect>>", lambda e: self._show_selected_build())

        ttk.Button(left, text="Import newest replay", command=self._import_newest).pack(fill="x", pady=(8, 2))
        ttk.Button(left, text="Import replay file...", command=self._import_browse).pack(fill="x", pady=2)
        ttk.Button(left, text="Open builds folder", command=self._open_builds_folder).pack(fill="x", pady=2)

        right = ttk.Frame(main)
        right.pack(side="left", fill="both", expand=True)

        ttk.Label(right, text="Selected build").pack(anchor="w")
        detail_frame = ttk.Frame(right)
        detail_frame.pack(fill="both", expand=True)
        self.detail = tk.Text(detail_frame, wrap="none", state="disabled",
                              font=("Consolas", 10), height=14)
        detail_scroll = ttk.Scrollbar(detail_frame, command=self.detail.yview)
        self.detail.configure(yscrollcommand=detail_scroll.set)
        self.detail.pack(side="left", fill="both", expand=True)
        detail_scroll.pack(side="left", fill="y")

        ttk.Label(right, text="Activity (cues while coaching, reports after games)").pack(anchor="w", pady=(6, 0))
        log_frame = ttk.Frame(right)
        log_frame.pack(fill="both", expand=True)
        self.log = tk.Text(log_frame, wrap="word", state="disabled", font=("Consolas", 10), height=12)
        scroll = ttk.Scrollbar(log_frame, command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set)
        self.log.pack(side="left", fill="both", expand=True)
        scroll.pack(side="left", fill="y")

        bottom = ttk.Frame(root)
        bottom.pack(fill="x", pady=(8, 0))
        self.coach_btn = ttk.Button(bottom, text="Start Coaching", command=self._toggle_coach)
        self.coach_btn.pack(side="left")
        ttk.Button(bottom, text="Review newest replay", command=self._review_newest).pack(side="left", padx=6)
        self.auto_review = tk.BooleanVar(value=True)
        self._auto_review_enabled = True  # plain mirror; Tk vars aren't thread-safe
        ttk.Checkbutton(
            bottom, text="Auto-review after each game", variable=self.auto_review,
            command=lambda: setattr(self, "_auto_review_enabled", self.auto_review.get()),
        ).pack(side="left", padx=6)
        self.speak = tk.BooleanVar(value=True)
        ttk.Checkbutton(bottom, text="Speak cues", variable=self.speak).pack(side="left", padx=6)
        ttk.Button(bottom, text="Test voice", command=self._test_voice).pack(side="left", padx=6)
        self.status = ttk.Label(bottom, text="SC2: looking...", anchor="e")
        self.status.pack(side="right")

    # ---------- event pump ----------

    def _post(self, kind: str, *payload) -> None:
        self.events.put((kind, payload))

    def _drain_events(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "log":
                    self._log(payload[0])
                elif kind == "status":
                    self.status.config(text=payload[0])
                elif kind == "coach_done":
                    self.coach_btn.config(text="Start Coaching")
                elif kind == "refresh":
                    self._refresh_builds(select=payload[0] if payload else None)
                elif kind == "pick_player":
                    self._pick_player_dialog(*payload)
                elif kind == "auto_review":
                    replay = payload[0]
                    if replay != self.last_reviewed:
                        self._log(f"New replay detected: {replay.name}")
                        self._review(replay)
        except queue.Empty:
            pass
        self.after(100, self._drain_events)

    def _log(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    # ---------- build library ----------

    def _refresh_builds(self, select=None) -> None:
        self.build_list.delete(0, "end")
        self._build_paths = sorted(BUILDS_DIR.glob("*.json"))
        for path in self._build_paths:
            try:
                name = Build.load(path).name
            except Exception:
                name = path.stem + " (unreadable)"
            self.build_list.insert("end", name)
        if select is not None and select in self._build_paths:
            self.build_list.selection_clear(0, "end")
            self.build_list.selection_set(self._build_paths.index(select))
        elif self._build_paths and not self.build_list.curselection():
            self.build_list.selection_set(0)
        self._show_selected_build()

    def _selected_build_path(self):
        selection = self.build_list.curselection()
        if not selection:
            return None
        return self._build_paths[selection[0]]

    def _show_selected_build(self) -> None:
        path = self._selected_build_path()
        if not path:
            return
        try:
            build = Build.load(path)
        except Exception as exc:
            self._set_detail(f"Could not read {path.name}: {exc}")
            return
        lines = [build.name, ""]
        lines.append(" when  supply  what")
        for step in build.sorted_steps():
            supply = f"{step.supply}" if step.supply is not None else "-"
            lines.append(f"{format_time(step.time):>5}  {supply:>5}   {step.action}")
        if build.benchmarks:
            lines.append("")
            lines.append("Timings hit in the source replay:")
            lines.extend(f"{format_time(b.time):>5}          {b.name}" for b in build.benchmarks)
        self._set_detail("\n".join(lines))

    def _set_detail(self, text: str) -> None:
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.insert("1.0", text)
        self.detail.configure(state="disabled")

    def _open_builds_folder(self) -> None:
        if sys.platform == "win32":
            subprocess.Popen(["explorer", str(BUILDS_DIR)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(BUILDS_DIR)])
        else:
            subprocess.Popen(["xdg-open", str(BUILDS_DIR)])

    # ---------- import ----------

    def _import_newest(self) -> None:
        replay = newest_replay(self.replay_dirs)
        if replay is None:
            messagebox.showinfo("No replays found", "Couldn't find your replay folder. Use 'Import replay file...' instead.")
            return
        self._start_import(replay)

    def _import_browse(self) -> None:
        initial = str(self.replay_dirs[0]) if self.replay_dirs else str(Path.home())
        path = filedialog.askopenfilename(
            title="Choose a replay", initialdir=initial,
            filetypes=[("StarCraft 2 replays", "*.SC2Replay"), ("All files", "*.*")],
        )
        if path:
            self._start_import(Path(path))

    def _start_import(self, replay: Path) -> None:
        self._log(f"Reading {replay.name} ...")

        def worker():
            try:
                from ..replay.extract import list_players
                players = list_players(str(replay))
                self._post("pick_player", replay, players)
            except Exception as exc:
                self._post("log", f"Import failed: {exc}")

        threading.Thread(target=worker, daemon=True).start()

    def _pick_player_dialog(self, replay: Path, players: list) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("Whose build?")
        dialog.transient(self)
        dialog.grab_set()
        ttk.Label(
            dialog,
            text=f"{replay.name}\n\nPick YOUR name to practice your own build.\n"
                 "(Picking the opponent copies their build instead - also useful!)",
            padding=8,
        ).pack()
        listbox = tk.Listbox(dialog, width=40, height=max(2, len(players)))
        for p in players:
            listbox.insert("end", f"{p['name']} ({p['race']})")
        remembered = load_settings().get("player_name", "")
        preselect = next(
            (i for i, p in enumerate(players) if p["name"] == remembered), 0
        )
        listbox.selection_set(preselect)
        listbox.pack(padx=8)

        def confirm():
            selection = listbox.curselection()
            if not selection:
                return
            player = players[selection[0]]
            dialog.destroy()
            settings = load_settings()
            settings["player_name"] = player["name"]
            save_settings(settings)
            self._finish_import(replay, player["name"])

        ttk.Button(dialog, text="Import build", command=confirm).pack(pady=8)
        listbox.bind("<Double-Button-1>", lambda e: confirm())

    def _finish_import(self, replay: Path, player_name: str) -> None:
        def worker():
            try:
                from ..replay.extract import extract_build
                build = extract_build(str(replay), player=player_name, until=300)
                build.name = f"{player_name} - {replay.stem}"
                out = BUILDS_DIR / (self._safe_name(build.name) + ".json")
                build.save(out)
                self._post("log", f"Imported '{build.name}': {len(build.steps)} steps, "
                                  f"{len(build.benchmarks)} benchmarks (first 5 minutes).")
                self._post("log", "It is selected on the left - press Start Coaching to practice it.")
                self._post("refresh", out)
            except Exception as exc:
                self._post("log", f"Import failed: {exc}")

        threading.Thread(target=worker, daemon=True).start()

    @staticmethod
    def _safe_name(name: str) -> str:
        return "".join(c if c.isalnum() or c in " -_" else "_" for c in name).strip()[:80]

    # ---------- coaching ----------

    def _toggle_coach(self) -> None:
        if self.coach_thread and self.coach_thread.is_alive():
            self.coach_stop.set()
            self.coach_btn.config(text="Start Coaching")
            self._log("Coaching stopped.")
            return
        path = self._selected_build_path()
        if not path:
            messagebox.showinfo("No build selected", "Select a build on the left first.")
            return
        try:
            build = Build.load(path)
        except Exception as exc:
            self._log(f"Could not read build: {exc}")
            return
        self.coach_stop.clear()
        self.coach_btn.config(text="Stop Coaching")
        self._log(f"Coaching armed: '{build.name}'.")
        if SC2ClientAPI(timeout=0.8).poll() is None:
            self._log("StarCraft II is not running yet - open it and start a match.")
        self._log("Nothing happens until a match begins; then each step is called out"
                  " a few seconds early, following the in-game clock.")
        self.announcer = Announcer(
            use_tts=self.speak.get(),
            sink=lambda line: self._post("log", line),
            voice=load_settings().get("voice", ""),
        )
        if self.speak.get():
            self._log(f"Voice: {self.announcer.describe_voice()}.")
            if not self.announcer.tts_available:
                self._log("Cues will be text-only in this window.")

        def worker():
            try:
                run_coach(
                    build, self.announcer, live_clock(),
                    should_stop=self.coach_stop.is_set,
                    status=lambda line: self._post("log", line),
                )
            except Exception as exc:
                self._post("log", f"Coach error: {exc}")
            finally:
                self._post("coach_done")

        self.coach_thread = threading.Thread(target=worker, daemon=True)
        self.coach_thread.start()

    def _test_voice(self) -> None:
        chosen = load_settings().get("voice", "")
        if getattr(self, "_voice_tester_choice", None) != chosen:
            self._voice_tester = Announcer(
                use_tts=True, sink=lambda line: self._post("log", line), voice=chosen
            )
            self._voice_tester_choice = chosen
        tester = self._voice_tester
        self._log(f"Voice: {tester.describe_voice()}"
                  + (f" ('{chosen}')" if chosen else "")
                  + ". You should hear a test sentence now.")
        if not tester.tts_available:
            self._log("No speech engine found on this system - cues will be text-only.")
            return
        tester.test_voice()

        def worker():
            voices = tester.list_voices()
            if voices:
                self._post("log", "Installed voices: " + ", ".join(voices))
                self._post("log", f'To switch, put e.g. "voice": "{voices[-1]}" into {SETTINGS_FILE}')

        threading.Thread(target=worker, daemon=True).start()

    # ---------- review ----------

    def _review_newest(self) -> None:
        replay = newest_replay(self.replay_dirs)
        if replay is None:
            messagebox.showinfo("No replays found", "Couldn't find your replay folder.")
            return
        self._review(replay)

    def _review(self, replay: Path) -> None:
        path = self._selected_build_path()
        if not path:
            self._log("Select a build to review against.")
            return
        self._log(f"Reviewing {replay.name} ...")

        def worker():
            try:
                from ..analyze.compare import compare, render_report
                from ..replay.extract import extract_build
                planned = Build.load(path)
                me = load_settings().get("player_name") or None
                try:
                    actual = extract_build(str(replay), player=me, include_workers=True)
                except Exception:
                    if me is None:
                        raise
                    # Different account/name in this replay - fall back to player 1.
                    actual = extract_build(str(replay), include_workers=True)
                self._post("log", render_report(compare(planned, actual)))
            except Exception as exc:
                self._post("log", f"Review failed: {exc}")

        threading.Thread(target=worker, daemon=True).start()
        self.last_reviewed = replay

    # ---------- background loops ----------

    def _status_loop(self) -> None:
        api = SC2ClientAPI(timeout=0.8)
        while True:
            state = api.poll()
            if state is None:
                text = "SC2: not running"
            elif state.in_game:
                kind = "replay" if state.is_replay else "game"
                text = f"SC2: in {kind}, {format_time(state.display_time)}"
            else:
                text = "SC2: in menus"
            self._post("status", text)
            time.sleep(2)

    def _auto_review_loop(self) -> None:
        # Watch the replay folder; the actual review runs on the main thread
        # (posted as an event) because it reads Tk widget state.
        while True:
            time.sleep(5)
            if not self._auto_review_enabled:
                continue
            replay = newest_replay(self.replay_dirs)
            if replay is None or replay == self.last_reviewed:
                continue
            # Wait until SC2 has finished writing the file.
            if time.time() - replay.stat().st_mtime < 5:
                continue
            self._post("auto_review", replay)


def main() -> None:
    ensure_dirs()
    try:
        App().mainloop()
    except Exception:
        ERROR_LOG.write_text(traceback.format_exc(), encoding="utf-8")
        raise


if __name__ == "__main__":
    main()
