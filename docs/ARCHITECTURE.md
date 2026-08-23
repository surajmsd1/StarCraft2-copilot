# Architecture & decision record

## The problem

Help a player create, execute, and internalize SC2 openers (e.g. proxy 4-reaper into macro):

- Build creation without tedious manual entry.
- Live execution help: audio/visual cues at the right in-game moments, including "meta" actions replays of pros reveal (send proxy SCVs at 0:38).
- Post-game analytics beyond the in-game tab: first blood time, actual vs planned step timings, when the proxy SCVs really left.
- Say timings out loud so the player learns them like a pro and eventually doesn't need the tool.
- Survive a period of rapid balance patches.

## Decision 1: external app, not in-game features

Three ways to put information in front of a player:

| Approach | Ranked? | Control | Verdict |
|---|---|---|---|
| In-game (custom maps, triggers, mods) | **No** — arcade/custom only | High inside the sandbox | Rejected: the whole point is ladder practice |
| Memory reading / injection overlays | Bannable (Warden) | Total | Rejected: account risk, breaks every patch |
| External app + passive data sources | **Yes** | Full (our code, our data) | **Chosen** |

"Passive data sources" means two things only:

1. **Replay files** — complete ground truth, available seconds after each game.
2. **SC2 Client API** — the game client serves a read-only HTTP API on `127.0.0.1:6119` while running (`/ui` → active screens, `/game` → players, `isReplay`, `displayTime`). It exists for stream overlays; established tools have polled it for years. `displayTime` matches the in-game clock, so cues survive pauses and slow loads. No injection, no automation, no memory access — nothing a ranked ToS cares about.

This is the same category of tool as existing accepted software (Spawning Tool Build Advisor, SC2ReplayStats uploader), so we're not pioneering legally grey ground — we're rebuilding it under our own control, which was the stated goal.

## Decision 2: replays are the source of truth

Nobody wants to type build orders in. So the input format for a build **is a replay**:

- `sc2copilot import game.SC2Replay` → `Build` JSON (steps with times/supply, plus extracted benchmarks). Works on your own games *and any pro replay you can download* — that's the "populate many builds" path.
- The JSON is deliberately human-editable: add spoken cues, add `move`/`note` steps (send proxy SCVs, move out), trim the tail. The replay gives 90% for free; the player curates the last 10%.
- This also answers **patch volatility**: after a balance patch, play the build once, re-import, and every timing is regenerated from the new reality. Build files carry `game_version` so stale ones are identifiable. Patch-notes parsing was considered and rejected — notes describe *changes*, replays describe *outcomes*, and outcomes are what we cue on.

Parsing stack: `spawningtool` (build-order extraction, powers spawningtool.com) on top of `sc2reader`, with Blizzard's `s2protocol` definitions underneath. New game builds get supported upstream; our exposure to patch churn is `pip install -U`.

## Decision 3: coach is a clock, judge is a replay

During a live ranked game we deliberately cannot see what the player is doing (that would require non-passive access). So responsibilities split:

- **Coach (live)** — a metronome keyed to `displayTime`. Fires each step's cue `lead` seconds early (default 5s), announces via console + offline TTS. It never claims to know what you did.
- **Analyzer (post-game)** — the replay tells the truth. `review` matches the plan's `build` steps against extracted reality (name-normalized, in-order, ±90s window), reports EARLY/LATE/MISS per step, improvised extras, and benchmark timings.

This split is what makes the tool ranked-legal *and* honest: live guidance is time-based, judgment is evidence-based.

## Benchmarks: the analytics the game doesn't give you

Extracted from tracker + game events (`sc2copilot/replay/benchmarks.py`):

- **First blood** — first enemy unit death credited to the player.
- **Combat unit timings** — reaper #1–#4 pop times, etc.
- **Proxy detection** — a structure closer to the enemy start than to yours is a proxy.
- **Proxy SCV send time** — earliest player order targeting near the eventual proxy site before the structure started. This is a heuristic (replays record commands, not intent) but it directly answers "when should my SCVs leave" — import a replay where the timing worked, and the send time becomes a cue.

All benchmark extraction is defensive: a patch that changes event shapes degrades to "benchmark missing", never a crashed import.

## Code map

```
sc2copilot/
  models.py              Build / BuildStep / Benchmark, JSON round-trip (times as in-game seconds)
  replay/extract.py      replay -> Build (spawningtool)
  replay/benchmarks.py   replay -> key timings (sc2reader tracker/game events)
  practice/game_client.py  localhost:6119 poller (GameState: in_game, display_time)
  practice/coach.py      CueScheduler (pure, tested) + run_coach loop; live/sim clocks
  practice/announce.py   console + optional pyttsx3 TTS on a worker thread
  analyze/compare.py     plan vs actual matching + text report
  cli.py                 import / show / practice / review / timings
```

`CueScheduler` and the benchmark geometry are pure functions with unit tests; everything touching SC2 (HTTP API, replay files) is a thin adapter around them, testable by hand on a real machine.

## Roadmap (in priority order)

1. **Auto-watch replay folder** — after each game, auto-run `review` against the active build and pop the report. Removes the last bit of friction.
2. **Visual overlay window** — always-on-top translucent strip showing the next 2–3 cues and a drift indicator. Tauri or plain tkinter (`-topmost` + transparency) on Windows; the coach loop already exposes everything it needs.
3. **Cross-game stats** — store every review; trend per-step drift ("your second rax is on average 9s late") and benchmark history ("first blood: 2:41 → 2:35 → 2:33").
4. **Practice-vs-best mode** — cue from your *fastest clean* execution rather than the original import.
5. **Build library UX** — tag/organize many imported builds, one keypress to arm one before queueing.

## Non-goals

- Anything that reads game memory, injects, or acts in-game on the player's behalf.
- Real-time deviation detection during ranked games (impossible passively; the post-game review covers it).
- Maintaining our own per-patch unit database (replays + upstream parsers already encode it).
