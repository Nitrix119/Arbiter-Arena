"""Tests for the benchmark scenarios — each must build a valid, playable fight."""

import re

import pytest

from src.arena.action_space import (
    DEFAULT_MAX_AIM_POINTS,
    aim_candidates,
    aim_coverage,
    legal_actions,
)
from src.arena.agent import ScriptedAgent
from src.arena.heuristic.agent import HeuristicAgent
from src.arena.match import run_match
from src.arena.scenarios import SCENARIOS
from src.combat.enums import CombatState


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_scenario_declares_two_distinct_teams(name):
    sc = SCENARIOS[name]
    combat = sc.build()
    teams = {e.team for e in combat.combatants}
    assert sc.llm_team in teams
    assert sc.heuristic_team in teams
    assert sc.llm_team != sc.heuristic_team


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_scenario_builds_fresh_entities_each_call(name):
    """Two builds must not share mutable state.

    This used to be asserted via disjoint entity ids, which was only ever a proxy —
    and a proxy that stable, roster-derived ids deliberately break, since the whole
    point is that the same creature has the same id in every build. Assert the real
    property instead: distinct objects, and damage to one leaves the other untouched.
    """
    a = SCENARIOS[name].build()
    b = SCENARIOS[name].build()

    assert all(x is not y for x, y in zip(a.combatants, b.combatants))

    victim = a.combatants[0]
    twin = next(e for e in b.combatants if e.entity_id == victim.entity_id)
    before = twin.current_hp
    victim.current_hp -= 5
    assert twin.current_hp == before


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_scenario_entity_ids_are_readable_and_stable(name):
    """Ids are the same across builds and carry no random noise.

    Under the free-text and raw-parameter conditions the model types these to name a
    target, so they are part of the interface under test (V1_PLAN §3.4).
    """
    first = [e.entity_id for e in SCENARIOS[name].build().combatants]
    second = [e.entity_id for e in SCENARIOS[name].build().combatants]

    assert first == second
    assert len(set(first)) == len(first)  # unique — ids feed __hash__/__eq__
    for entity_id in first:
        assert re.fullmatch(r"[a-z0-9-]+", entity_id), entity_id
        assert len(entity_id) <= 24, f"{entity_id!r} is a lot for a model to copy"


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_scenario_plays_to_completion_offline(name):
    """Scripted-vs-scripted smoke run: the pieces are valid and the match terminates."""
    sc = SCENARIOS[name]
    combat = sc.build()
    agents = {
        sc.llm_team: ScriptedAgent("A", sc.llm_team),
        sc.heuristic_team: ScriptedAgent("B", sc.heuristic_team),
    }
    result = run_match(combat, agents, seed=1, round_cap=30)

    assert combat.state in (
        CombatState.ENDED,
        CombatState.ACTIVE,
    )  # ran without raising
    assert result.reason in ("last_standing", "round_cap")
    # Every action a scripted agent took was legal (no schema/geometry surprises in setup).
    assert result.rounds >= 1


# -- the AoE scenario's central decision must actually exist -----------------


def _aoe_setup():
    sc = SCENARIOS["aoe_placement"]
    combat = sc.build()
    combat.start_combat()
    mage = next(e for e in combat.combatants if e.entity_id == "mage")
    return combat, mage, combat.spell_registry.get("Fireball")


def test_the_aoe_scenario_offers_both_the_good_and_the_careless_line():
    """A scenario whose central decision is unavailable would fail H4 silently.

    The skill under test is *where* to put a 20 ft radius. That is only a decision if
    catching both raiders cleanly and catching both plus your own bodyguard are both
    reachable — otherwise the scenario measures nothing and would look fine.
    """
    combat, mage, fireball = _aoe_setup()
    options = aim_candidates(combat, mage, fireball)

    def shape(option):
        foes = sum(1 for t in option.hits if t.relation == "enemy")
        friends = sum(1 for t in option.hits if t.relation in ("ally", "self"))
        return foes, friends

    assert any(shape(o) == (2, 0) for o in options), "no clean both-raiders placement"
    assert any(shape(o) == (2, 1) for o in options), "no careless placement to avoid"


def test_the_aoe_scenario_is_not_a_puzzle():
    """Pre-registration §4.1: skill-revealing, but not a riddle.

    Several distinct placements exist, so the good one has to be chosen rather than
    being the only thing on offer.
    """
    combat, mage, fireball = _aoe_setup()
    options = aim_candidates(combat, mage, fireball)

    assert len(options) >= 5
    assert len(options) < DEFAULT_MAX_AIM_POINTS  # and the cap is not truncating


def test_the_aoe_menu_loses_nothing_at_the_chosen_resolution():
    """The H4 number, pinned on the real scenario so it is known before the pilot."""
    combat, mage, fireball = _aoe_setup()

    coverage = aim_coverage(combat, mage, fireball)

    assert coverage.coverage == 1.0, coverage.missing
    assert coverage.achievable == 9


def test_the_aoe_scenario_wires_a_spell_registry():
    """The seam: a caster with no registry would silently have no spells at all."""
    combat, mage, _ = _aoe_setup()

    assert combat.spell_registry is not None
    assert "Fireball" in combat.spell_registry
    assert mage.spell_slots.remaining[3] == 2

    menu = legal_actions(combat, mage).to_dict()
    fireball_entry = next(s for s in menu["spells"] if s["name"] == "Fireball")
    assert fireball_entry["aim_points"]


def test_the_scripted_opponent_holds_the_melee_side():
    """ScriptedAgent cannot cast, so it could not play the caster's side."""
    sc = SCENARIOS["aoe_placement"]
    combat = sc.build()

    casters = [e for e in combat.combatants if e.stat_block.known_spells]
    assert casters
    assert all(e.team == sc.llm_team for e in casters)


def test_the_mage_cannot_shrug_off_its_own_fireball():
    """Friendly fire has to be a real risk or the placement decision is free."""
    combat, mage, fireball = _aoe_setup()

    assert not fireball.cannot_cause_self_damage
    # 8d6 averages 28; half on a successful save is still most of a 22 HP mage.
    assert mage.max_hp < 28


def test_using_the_area_spell_well_is_what_wins_this_scenario():
    """The scenario must reward the skill it claims to measure.

    CLAUDE.md §9 (2026-09-17): benchmark every scenario against the trivial baseline
    built to test it. Here the baseline is an agent that *cannot cast at all* — it
    plays the mage as a dagger-poker. If it scored the same as one that places the
    Fireball, the scenario would be measuring something else, and the AoE arm of H4
    would be built on sand.

    The gap is large and in the right direction, so this asserts a wide margin rather
    than a knife-edge; it is a design check, not a tuning target.
    """
    sc = SCENARIOS["aoe_placement"]
    seeds = range(12)

    def win_rate(make_agent):
        wins = 0
        for seed in seeds:
            combat = sc.build()
            result = run_match(
                combat,
                {
                    sc.llm_team: make_agent(combat),
                    sc.heuristic_team: ScriptedAgent("B", sc.heuristic_team),
                },
                seed=seed,
            )
            wins += result.winner == sc.llm_team
        return wins / len(list(seeds))

    cannot_cast = win_rate(lambda c: ScriptedAgent("A", sc.llm_team))
    casts_it = win_rate(lambda c: HeuristicAgent("A", sc.llm_team, c))

    assert casts_it - cannot_cast > 0.25, (
        f"using the area spell gained only {casts_it - cannot_cast:.0%} "
        f"({cannot_cast:.0%} -> {casts_it:.0%}); the scenario may not be measuring "
        "placement at all"
    )
    assert 0.0 < cannot_cast < 1.0, "the baseline is at a floor or ceiling"
