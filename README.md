# sc2copilot

A StarCraft 2 build creator, practice coach, and post-game analyzer — driven by your own replays, running entirely outside the game so it works everywhere, including ranked.

**The loop:**

1. **Import** — play a build once (or grab any replay of it) and extract the build order + key timings. No manual build entry.
2. **Practice** — while you play, get audio + console cues synced to the real in-game clock: *"Depot now"*, *"Send two SCVs across the map, now"*, *"First proxy barracks"*.
3. **Review** — after the game, compare the replay against the plan: which steps were late, which were missed, and key timings the in-game tab never shows you (first blood at 2:35, when your proxy SCVs actually left, when reaper #4 popped).
4. Repeat until the timings live in your head, not the tool.

## Easiest way to try it (Windows)

1. Install Python from [python.org/downloads](https://www.python.org/downloads/) — tick **"Add Python to PATH"** in the installer.
2. Download this repo (green **Code** button → **Download ZIP**) and unzip it anywhere.
3. Double-click **`SC2Copilot.bat`**. First run installs everything (~1 min), then the app opens.

The launcher **updates itself from GitHub on every start** — download once, always current. (Offline? It just runs the version you have.)

In the app:

- **Import newest replay** → pick your name → your last game's opener becomes a build.
- Select a build → **Start Coaching** → start a game; cues are spoken and shown, synced to the in-game clock.
- **Auto-review after each game** is on by default: finish a game and the report (drift per step, first blood, missed steps) appears by itself.

Your builds live in `~/SC2Copilot/builds` as editable JSON (add custom cues, tweak times). If something breaks, `~/SC2Copilot/gui-error.log` has the details.

## Install (command line)

```
pip install -e .[tts,dev]
```

Requires Python 3.9+. `tts` adds spoken cues (pyttsx3, offline); without it cues are console-only. `sc2copilot gui` opens the same graphical app.

## Quick start (command line)

```bash
# See who's in a replay
sc2copilot import "path/to/game.SC2Replay" --list-players

# Extract your opener (first 5 minutes) into a build file
sc2copilot import "path/to/game.SC2Replay" -p YourName --until 300 -o builds/proxy-reaper.json

# Inspect / hand-tune it (it's plain JSON — add cues, move steps, notes)
sc2copilot show builds/proxy-reaper.json

# Start the coach, then start a game. Cues fire against the live in-game clock.
sc2copilot practice builds/proxy-reaper.json

# Try the coach without SC2 running (wall-clock simulation, 2x speed)
sc2copilot practice sc2copilot/data/builds/example-proxy-4-reaper.json --sim --speed 2

# After a ladder game: how did I actually execute it?
sc2copilot review "path/to/new-game.SC2Replay" -b builds/proxy-reaper.json -p YourName

# Just the key timings from any replay (first blood, proxy send, unit counts)
sc2copilot timings "path/to/game.SC2Replay" -p YourName
```

Replays live under `Documents/StarCraft II/Accounts/<id>/<handle>/Replays/Multiplayer/` — the newest file there is the game you just played.

## Is this legal in ranked?

Yes, by design. sc2copilot never reads game memory, never injects, and never automates anything. It uses exactly two passive data sources:

- **Replay files** on disk (after the game).
- The SC2 client's **built-in localhost API** (`http://127.0.0.1:6119/game`), which the client itself serves for overlays/streaming tools and which reports whether you're in a game and the current in-game clock (`displayTime`). That's how cues stay synced through pauses without touching the game.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full decision record (why not in-game mods, how patch volatility is handled, roadmap to a visual overlay).

## Surviving balance patches

SC2 is patching heavily right now. sc2copilot's answer is: **the replay is the source of truth.** Build files record the game version they were extracted from; after a patch, play the build once and re-import — every timing regenerates from reality instead of stale notes. Replay decoding rides on `s2protocol`/`sc2reader`/`spawningtool`, which track new game builds upstream, so a `pip install -U` picks up new patches.

## Status

v0.1 — working core (import, practice cues, review, timings) with a CLI front end. Not yet built: visual overlay window, auto-watch of the replay folder, per-build stats across many games. See the roadmap in `docs/ARCHITECTURE.md`.
