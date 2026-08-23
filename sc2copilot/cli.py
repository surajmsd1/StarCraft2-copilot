"""Command-line entry point.

Workflow:
  sc2copilot import  <replay> -o builds/my-opener.json   # replay -> build
  sc2copilot show    builds/my-opener.json               # inspect / tweak
  sc2copilot practice builds/my-opener.json              # live audio cues
  sc2copilot review  <new-replay> -b builds/my-opener.json  # post-game report
  sc2copilot timings <replay>                            # benchmarks only
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .models import Build, format_time


def cmd_import(args) -> int:
    from .replay.extract import extract_build, list_players

    if args.list_players:
        for p in list_players(args.replay):
            print(f"  {p['pid']}: {p['name']} ({p['race']})")
        return 0

    build = extract_build(
        args.replay,
        player=args.player,
        until=args.until,
        include_workers=args.workers,
    )
    if args.name:
        build.name = args.name
    out = Path(args.output or (Path(args.replay).stem + ".json"))
    build.save(out)
    print(f"Saved build '{build.name}' ({len(build.steps)} steps, "
          f"{len(build.benchmarks)} benchmarks) -> {out}")
    return 0


def cmd_show(args) -> int:
    build = Build.load(args.build)
    print(f"{build.name}  [{build.matchup}]  (from {build.source_replay or 'hand-written'})")
    if build.notes:
        print(f"  note: {build.notes}")
    print()
    for step in build.sorted_steps():
        supply = f"{step.supply:>3}" if step.supply is not None else "  ."
        print(f"  {format_time(step.time):>5}  {supply}  {step.action}")
    if build.benchmarks:
        print("\nBenchmarks:")
        for b in build.benchmarks:
            print(f"  {format_time(b.time):>5}  {b.name}")
    return 0


def cmd_practice(args) -> int:
    from .practice.announce import Announcer
    from .practice.coach import live_clock, run_coach, sim_clock

    build = Build.load(args.build)
    announcer = Announcer(use_tts=not args.no_tts)
    if not announcer.tts_available and not args.no_tts:
        print("(TTS unavailable - install with: pip install sc2copilot[tts])")
    clock = sim_clock(speed=args.speed) if args.sim else live_clock()
    if not args.sim:
        print("Watching for a live game on the SC2 client API (localhost:6119)...")
    try:
        run_coach(build, announcer, clock)
    except KeyboardInterrupt:
        print("\nStopped.")
    return 0


def cmd_review(args) -> int:
    from .analyze.compare import compare, render_report
    from .replay.extract import extract_build

    planned = Build.load(args.build)
    actual = extract_build(args.replay, player=args.player, include_workers=True)
    print(render_report(compare(planned, actual)))
    return 0


def cmd_timings(args) -> int:
    from .replay.benchmarks import extract_benchmarks

    benchmarks = extract_benchmarks(args.replay, player_name=args.player)
    if not benchmarks:
        print("No benchmarks extracted.")
        return 1
    for b in benchmarks:
        desc = f"  ({b.description})" if b.description else ""
        print(f"  {format_time(b.time):>5}  {b.name}{desc}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sc2copilot", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("import", help="Extract a build from a replay")
    p.add_argument("replay")
    p.add_argument("-o", "--output", help="Output build JSON path")
    p.add_argument("-p", "--player", help="Player name (substring) to extract")
    p.add_argument("--name", help="Name for the build")
    p.add_argument("--until", type=float, help="Cut off after N in-game seconds")
    p.add_argument("--workers", action="store_true", help="Include worker production steps")
    p.add_argument("--list-players", action="store_true", help="Just list players in the replay")
    p.set_defaults(func=cmd_import)

    p = sub.add_parser("show", help="Print a build file")
    p.add_argument("build")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("practice", help="Run live audio/text cues for a build")
    p.add_argument("build")
    p.add_argument("--sim", action="store_true", help="Simulate the game clock (no SC2 needed)")
    p.add_argument("--speed", type=float, default=1.0, help="Sim clock speed multiplier")
    p.add_argument("--no-tts", action="store_true", help="Console cues only")
    p.set_defaults(func=cmd_practice)

    p = sub.add_parser("review", help="Compare a replay against a planned build")
    p.add_argument("replay")
    p.add_argument("-b", "--build", required=True, help="Planned build JSON")
    p.add_argument("-p", "--player", help="Player name (substring) in the replay")
    p.set_defaults(func=cmd_review)

    p = sub.add_parser("timings", help="Print key timings (first blood, proxies...) from a replay")
    p.add_argument("replay")
    p.add_argument("-p", "--player", help="Player name (substring)")
    p.set_defaults(func=cmd_timings)

    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except FileNotFoundError as exc:
        print(f"File not found: {exc.filename or exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
