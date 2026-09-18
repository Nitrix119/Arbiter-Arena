"""Print benchmark metrics for one or more recorded match transcripts.

    python -m examples.arena_metrics matches/20260915_055818_protect_squishy_...jsonl
    python -m examples.arena_metrics matches/*.jsonl
    python -m examples.arena_metrics some.jsonl --scenario kiting

The scenario (which authorises scenario-scoped metrics like kiting/protection) is taken from
``--scenario`` if given, else guessed from the filename by matching a known scenario name; if
neither identifies one, only the global metrics are shown. No model is re-run — everything is read
from the log.
"""

import argparse
import glob
import os
from typing import Optional

from src.arena.metrics import MatchReport, compute_report, load_transcript

_KNOWN_SCENARIOS = ("protect_squishy", "alpha_strike", "kiting")


def _guess_scenario(path: str) -> Optional[str]:
    base = os.path.basename(path)
    for name in _KNOWN_SCENARIOS:  # most-specific first
        if name in base:
            return name
    return None


def _print_report(path: str, scenario: Optional[str], report: MatchReport) -> None:
    print(f"\n=== {os.path.basename(path)} ===")
    print(f"scenario={scenario or '(none)'}  seed={report.seed}  "
          f"winner={report.winner!r} ({report.reason}) in {report.rounds} rounds")
    hp = "  ".join(f"{t}:{frac:.0%}" for t, frac in sorted(report.hp_fraction.items()))
    print(f"HP remaining: {hp}")

    print("  team | turns | decisions | illegal | no-tool | forfeit | dmg dealt | dmg/turn | overkill | dmg taken")
    for t in sorted(report.teams):
        m = report.teams[t]
        print(f"   {t:>3} | {m.turns:5} | {m.decisions:9} | "
              f"{m.rejected:3} ({m.illegal_rate:4.0%}) | {m.no_tool_calls:7} | {m.forfeit_turns:7} | "
              f"{m.damage_dealt:9} | {m.damage_per_turn:8.1f} | {m.overkill:8} | {m.damage_taken:9}")

    for s in report.scoped:
        if not s.applicable:
            print(f"  scoped [{s.name}]: n/a — {s.reason}")
            continue
        vals = "  ".join(f"{k}={v}" for k, v in s.values.items())
        print(f"  scoped [{s.name}] subject={s.subject_name!r}: {vals}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Compute metrics from match transcript(s).")
    parser.add_argument("paths", nargs="+", help="transcript .jsonl path(s) or glob(s).")
    parser.add_argument("--scenario", default=None, help="override the scenario for all inputs.")
    args = parser.parse_args()

    files = [f for p in args.paths for f in (glob.glob(p) or [p])]
    for path in files:
        scenario = args.scenario or _guess_scenario(path)
        report = compute_report(load_transcript(path), scenario=scenario)
        _print_report(path, scenario, report)


if __name__ == "__main__":
    main()
