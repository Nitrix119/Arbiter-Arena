"""End-to-end: the HeuristicAgent fixes the four ScriptedAgent flaws and out-plays it."""

from src.arena.agent import ScriptedAgent
from src.arena.heuristic.agent import HeuristicAgent
from src.arena.information_policy import FULL_INFORMATION
from src.arena.match import run_match
from src.arena.observation import build_observation
from src.arena.tools import TOOLS, ToolExecutor
from src.models import AttackAction, Damage, DamageType

from .conftest import force_turn, melee_attack, ranged_attack


def _decide(combat, actor):
    agent = HeuristicAgent("H", actor.team, combat)
    obs = build_observation(combat, actor)
    return agent.decide(obs, TOOLS)


def _started(make_combat, entities, focus):
    combat = make_combat(entities)
    combat.start_combat()
    force_turn(combat, focus)
    return combat


def _strong_ranged(name="Heavy Crossbow", range_ft=120.0):
    return AttackAction(
        name=name,
        description="",
        bonus_to_hit=6,
        damage=[Damage(DamageType.PIERCING, formula="2d6+4")],
        range_ft=range_ft,
    )


def _strong_melee():
    return AttackAction(
        name="Greatsword",
        description="",
        bonus_to_hit=7,
        damage=[Damage(DamageType.SLASHING, formula="2d8+5")],
        range_ft=5.0,
    )


def _weak_melee():
    return AttackAction(
        name="Club", description="", bonus_to_hit=2,
        damage=[Damage(DamageType.BLUDGEONING, formula="1d4")], range_ft=5.0,
    )


# --- the four flaws, fixed ---------------------------------------------------


def test_attacks_a_reachable_enemy_and_it_resolves(make_entity, make_combat):
    a = make_entity("A", team="a", pos=(0, 0, 0), attacks=[melee_attack()])
    b = make_entity("B", team="b", pos=(5, 0, 0), attacks=[melee_attack()])
    combat = _started(make_combat, [a, b], a)

    call = _decide(combat, a)
    assert call.name == "attack" and call.arguments["defender_id"] == b.entity_id
    result = ToolExecutor(combat).apply(a, call, FULL_INFORMATION)
    assert result["ok"] is True


def test_targets_the_higher_threat_not_the_nearest(make_entity, make_combat):
    a = make_entity("A", team="a", pos=(0, 0, 0), attacks=[melee_attack()])
    cannon = make_entity("Cannon", team="b", pos=(5, 0, 0), hp=20, attacks=[_strong_melee()])
    tank = make_entity("Tank", team="b", pos=(0, 5, 0), hp=20, attacks=[_weak_melee()])
    combat = _started(make_combat, [a, cannon, tank], a)

    call = _decide(combat, a)
    assert call.name == "attack" and call.arguments["defender_id"] == cannon.entity_id


def test_secures_the_kill(make_entity, make_combat):
    # Equal-threat enemies so the choice is purely about finishing one now.
    a = make_entity("A", team="a", pos=(0, 0, 0), attacks=[_strong_melee()])
    low = make_entity("Low", team="b", pos=(5, 0, 0), hp=3, attacks=[_strong_melee()])
    high = make_entity("High", team="b", pos=(0, 5, 0), hp=30, attacks=[_strong_melee()])
    combat = _started(make_combat, [a, low, high], a)

    call = _decide(combat, a)
    assert call.name == "attack" and call.arguments["defender_id"] == low.entity_id


def test_closes_on_a_distant_enemy_with_a_legal_move(make_entity, make_combat):
    a = make_entity("A", team="a", pos=(0, 0, 0), attacks=[melee_attack()])
    b = make_entity("B", team="b", pos=(50, 0, 0), attacks=[melee_attack()])
    combat = _started(make_combat, [a, b], a)

    call = _decide(combat, a)
    assert call.name == "move" and call.arguments["option_id"].startswith("toward_melee:")
    result = ToolExecutor(combat).apply(a, call, FULL_INFORMATION)
    assert result["ok"] is True  # legal by construction — never lands on an occupied cell


# --- out-plays the weak baseline --------------------------------------------


def _set_speed(entity, speed):
    entity.stat_block.resource_defaults["speed"] = speed
    entity.resources.movement = speed


def test_heuristic_kiter_beats_scripted_melee(make_entity, make_combat):
    """A fast ranged HeuristicAgent kites a slower ScriptedAgent melee unit and wins.

    The canonical kiting matchup (AGENT_ARENA_METRICS D2): a faster ranged unit that
    holds distance stays untouched while it plinks the chaser down. An equal-speed kiter
    could not escape once caught, so speed is the skill the scenario tests.
    """

    def build():
        archer = make_entity("Archer", team="a", pos=(0, 0, 0), hp=25, attacks=[_strong_ranged()])
        brute = make_entity("Brute", team="b", pos=(60, 0, 0), hp=25, attacks=[_strong_melee()])
        _set_speed(archer, 40)
        _set_speed(brute, 25)
        combat = make_combat([archer, brute])
        agents = {
            "a": HeuristicAgent("Kiter", "a", combat),
            "b": ScriptedAgent("Chaser", "b"),
        }
        return combat, agents

    wins = 0
    seeds = range(10)
    for seed in seeds:
        combat, agents = build()
        result = run_match(combat, agents, seed=seed, round_cap=30)
        if result.winner == "a":
            wins += 1
    assert wins >= 9, f"kiter won only {wins}/{len(list(seeds))}"
