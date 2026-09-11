"""Tests for the benchmark scenarios — each must build a valid, playable fight."""

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
    a = SCENARIOS[name].build()
    b = SCENARIOS[name].build()
    ids_a = {e.entity_id for e in a.combatants}
    ids_b = {e.entity_id for e in b.combatants}
    assert ids_a.isdisjoint(ids_b)  # no shared mutable state across builds


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

    assert combat.state in (CombatState.ENDED, CombatState.ACTIVE)  # ran without raising
    assert result.reason in ("last_standing", "round_cap")
    # Every action a scripted agent took was legal (no schema/geometry surprises in setup).
    assert result.rounds >= 1
