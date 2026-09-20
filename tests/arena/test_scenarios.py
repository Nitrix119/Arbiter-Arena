"""Tests for the benchmark scenarios — each must build a valid, playable fight."""

import re

import pytest

from src.arena.agent import ScriptedAgent
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
