"""Run a benchmark scenario: an LLM side vs the deterministic heuristic. Spends tokens.

    python -m examples.arena_scenario --scenario kiting --llm openrouter:nvidia/nemotron-3.5-lightning:free
    python -m examples.arena_scenario --scenario alpha_strike --llm claude
    python -m examples.arena_scenario --scenario protect_squishy --llm claude:claude-opus-5

The heuristic (ScriptedAgent) is the fixed yardstick; only the LLM side varies, so results
compare models into the same fight. Needs the relevant provider set up — see
docs/current/AGENT_ARENA_LLM_SETUP.md. Free OpenRouter models cost ~nothing.
"""

import argparse

from src.arena.agent import ScriptedAgent
from src.arena.match import run_match
from src.arena.scenarios import SCENARIOS
from src.arena.transcript import Transcript


def _make_llm(spec: str, name: str, team: str):
    if spec.startswith("claude"):
        from src.arena.llm_agent import DEFAULT_MODEL as CLAUDE_DEFAULT, LLMAgent

        model = spec.split(":", 1)[1] if ":" in spec else CLAUDE_DEFAULT
        return LLMAgent(name, team, model=model)
    from src.arena.openrouter_agent import DEFAULT_MODEL as OR_DEFAULT, OpenRouterAgent

    model = spec.split(":", 1)[1] if ":" in spec else OR_DEFAULT
    return OpenRouterAgent(name, team, model=model)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run an LLM-vs-heuristic benchmark scenario.")
    parser.add_argument("--scenario", choices=sorted(SCENARIOS), required=True)
    parser.add_argument(
        "--llm", default="claude",
        help="LLM side spec: 'claude[:model]' | 'openrouter[:model]'.",
    )
    parser.add_argument("--seed", type=int, default=1, help="RNG seed for a reproducible battle.")
    args = parser.parse_args()

    scenario = SCENARIOS[args.scenario]
    combat = scenario.build()
    llm = _make_llm(args.llm, f"LLM:{args.llm}", scenario.llm_team)
    agents = {
        scenario.llm_team: llm,
        scenario.heuristic_team: ScriptedAgent("Heuristic", scenario.heuristic_team),
    }

    print(scenario.description)
    print(
        f"LLM = team {scenario.llm_team} ({args.llm}); heuristic = team "
        f"{scenario.heuristic_team}. {scenario.llm_rationale}\n"
    )

    transcript = Transcript()
    result = run_match(combat, agents, seed=args.seed, transcript=transcript)

    print(f"=== winner={result.winner!r} ({result.reason}) in {result.rounds} rounds ===")
    for team, frac in result.hp_fraction.items():
        who = "LLM" if team == scenario.llm_team else "heuristic"
        print(f"  team {team} ({who}): {frac:.0%} HP remaining")

    path = transcript.save_auto(label=f"{args.scenario}_{args.llm}")
    print(f"\nTranscript saved to {path} ({len(transcript.records)} records).")


if __name__ == "__main__":
    main()
