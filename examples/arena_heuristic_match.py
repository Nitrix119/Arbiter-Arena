"""Benchmark the utility-scoring HeuristicAgent against the scripted yardstick.

    python -m examples.arena_heuristic_match

Runs a canonical kiting matchup — a fast ranged HeuristicAgent vs a slower melee
ScriptedAgent — across a seed set, prints the win margin, and replays one match's battle
log. Fully deterministic and offline (no API/LLM). This is the "see the new yardstick
out-play the old one" demo for Phase A+B of the heuristic work.
"""

from src.arena.agent import ScriptedAgent
from src.arena.heuristic.agent import HeuristicAgent
from src.arena.match import run_match
from src.arena.setup import build_combat
from src.arena.transcript import Transcript
from src.models import AbilityScores, AttackAction, Damage, DamageType, Entity, StatBlock

SEEDS = range(20)
ROUND_CAP = 30


def _unit(name, team, x, *, hp, speed, attack) -> Entity:
    block = StatBlock(
        name=name,
        ability_scores=AbilityScores(16, 14, 14, 10, 12, 10),
        hit_points_max=hp,
        armor_class=15,
        proficiency_bonus=2,
    )
    block.resource_defaults["speed"] = speed
    block.add_action(attack)
    entity = Entity(block, team=team)
    entity.x, entity.y, entity.z = x, 0.0, 0.0
    entity.resources.movement = speed
    return entity


def _crossbow() -> AttackAction:
    return AttackAction(
        name="Heavy Crossbow", description="", bonus_to_hit=6,
        damage=[Damage(DamageType.PIERCING, formula="2d6+4")], range_ft=120.0,
    )


def _greatsword() -> AttackAction:
    return AttackAction(
        name="Greatsword", description="", bonus_to_hit=7,
        damage=[Damage(DamageType.SLASHING, formula="2d8+5")], range_ft=5.0,
    )


def _build():
    """A fresh kiting scenario: heuristic archer (team a) vs scripted brute (team b)."""
    archer = _unit("Archer", "a", 0.0, hp=25, speed=40, attack=_crossbow())
    brute = _unit("Brute", "b", 60.0, hp=25, speed=25, attack=_greatsword())
    combat = build_combat([archer, brute])
    agents = {
        "a": HeuristicAgent("Heuristic", "a", combat),
        "b": ScriptedAgent("Scripted", "b"),
    }
    return combat, agents


def main() -> None:
    wins = {"a": 0, "b": 0, None: 0}
    for seed in SEEDS:
        combat, agents = _build()
        result = run_match(combat, agents, seed=seed, round_cap=ROUND_CAP)
        wins[result.winner] = wins.get(result.winner, 0) + 1

    n = len(list(SEEDS))
    print(f"\n=== Heuristic (kiter) vs Scripted (chaser), {n} seeds ===")
    print(f"  Heuristic wins: {wins['a']}/{n} ({wins['a'] / n:.0%})")
    print(f"  Scripted wins:  {wins['b']}/{n}")
    print(f"  Draws:          {wins[None]}/{n}")

    # Replay one match's battle log so the kiting is visible.
    combat, agents = _build()
    transcript = Transcript()
    result = run_match(combat, agents, seed=0, round_cap=ROUND_CAP, transcript=transcript)
    print(f"\n--- Sample match (seed 0): winner={result.winner!r} "
          f"({result.reason}) in {result.rounds} rounds ---")
    for record in transcript.records_of("action"):
        call, res = record["call"], record["result"]
        actor = record["actor_id"][:8]
        if not res["ok"]:
            line = f"illegal {call['name']} ({res['error']})"
        elif call["name"] == "attack":
            line = f"shoots - {'hit for ' + str(res['damage']) if res['hit'] else 'missed'}"
        elif call["name"] == "move":
            p = res["position"]
            line = f"moves to x={p['x']:.0f}"
        else:
            line = call["name"]
        print(f"  [{actor}] {line}")


if __name__ == "__main__":
    main()
