"""Tests for the per-turn driver — the observe/decide/act loop and its guards."""

from typing import Any, Dict, List

from src.arena.agent import Agent, NoToolCallError, ScriptedAgent
from src.arena.tools import ToolCall
from src.arena.transcript import Transcript
from src.arena.turn_driver import run_turn

import math

from .conftest import force_turn, melee_attack, ranged_attack


class _SequenceAgent(Agent):
    """Emits a fixed sequence of ToolCalls (last one repeats if exhausted)."""

    def __init__(self, calls: List[ToolCall]):
        super().__init__("Seq", "a")
        self._calls = calls
        self._i = 0

    def decide(self, observation: Dict[str, Any], tools: List[Dict[str, Any]]) -> ToolCall:
        call = self._calls[min(self._i, len(self._calls) - 1)]
        self._i += 1
        return call


class _RecordingAgent(Agent):
    """Emits a fixed sequence and records the observations it was given."""

    def __init__(self, calls: List[ToolCall]):
        super().__init__("Rec", "a")
        self._calls = calls
        self._i = 0
        self.seen: List[Dict[str, Any]] = []

    def decide(self, observation: Dict[str, Any], tools: List[Dict[str, Any]]) -> ToolCall:
        self.seen.append(observation)
        call = self._calls[min(self._i, len(self._calls) - 1)]
        self._i += 1
        return call


def _started(make_combat, entities, focus):
    combat = make_combat(entities)
    combat.start_combat()
    force_turn(combat, focus)
    return combat


def test_scripted_turn_completes_and_advances(make_entity, make_combat):
    fighter = make_entity("Fighter", team="a", pos=(0, 0, 0), attacks=[melee_attack()])
    goblin = make_entity("Goblin", team="b", pos=(5, 0, 0), hp=30)
    combat = _started(make_combat, [fighter, goblin], fighter)

    outcome = run_turn(combat, fighter, ScriptedAgent("A", "a"))

    assert outcome.actions_taken == 1  # attacked once, then ended its turn
    assert outcome.forced_end is False  # the agent ended its own turn
    assert combat.get_current_entity() is not fighter  # the turn advanced exactly once


def test_consecutive_failures_force_end(make_entity, make_combat):
    fighter = make_entity("Fighter", team="a", pos=(0, 0, 0), attacks=[melee_attack()])
    goblin = make_entity("Goblin", team="b", pos=(5, 0, 0))
    combat = _started(make_combat, [fighter, goblin], fighter)

    always_bad = _SequenceAgent([ToolCall("attack", {"action_name": "Nope", "defender_id": "bad"})])
    outcome = run_turn(combat, fighter, always_bad)

    assert outcome.failures == 3  # 3 consecutive failures trips the budget
    assert outcome.actions_taken == 0
    assert outcome.forced_end is True
    assert combat.get_current_entity() is not fighter


def test_total_failure_budget_forces_end(make_entity, make_combat):
    fighter = make_entity("Fighter", team="a", pos=(0, 0, 0), attacks=[melee_attack()])
    goblin = make_entity("Goblin", team="b", pos=(60, 0, 0))  # far, so the moves are unobstructed
    combat = _started(make_combat, [fighter, goblin], fighter)

    bad = ToolCall("attack", {"action_name": "Nope", "defender_id": "bad"})
    ok = ToolCall("move", {"x": 1, "z": 0})  # legal move (resets consecutive)
    # fail,fail,ok,fail,fail,ok,fail -> 5 total failures before 3-in-a-row
    agent = _SequenceAgent([bad, bad, ok, bad, bad, ok, bad])
    outcome = run_turn(combat, fighter, agent)

    assert outcome.failures == 5
    assert outcome.actions_taken == 2  # the two successful moves
    assert outcome.forced_end is True


class _NoToolAgent(Agent):
    """Never produces a tool call — mimics a flaky model returning only prose."""

    def __init__(self):
        super().__init__("NoTool", "a")

    def decide(self, observation, tools):
        raise NoToolCallError("no tool call")


def test_no_tool_call_is_contained_not_crashing(make_entity, make_combat):
    fighter = make_entity("Fighter", team="a", pos=(0, 0, 0), attacks=[melee_attack()])
    goblin = make_entity("Goblin", team="b", pos=(5, 0, 0))
    combat = _started(make_combat, [fighter, goblin], fighter)

    outcome = run_turn(combat, fighter, _NoToolAgent())  # must not raise

    assert outcome.failures == 3  # counted against the budget like an illegal move
    assert outcome.forced_end is True
    assert combat.get_current_entity() is not fighter  # the turn still advanced


def test_dead_actor_turn_is_skipped(make_entity, make_combat):
    fighter = make_entity("Fighter", team="a", pos=(0, 0, 0), attacks=[melee_attack()])
    goblin = make_entity("Goblin", team="b", pos=(5, 0, 0))
    combat = _started(make_combat, [fighter, goblin], goblin)
    goblin.current_hp = 0  # downed

    outcome = run_turn(combat, goblin, ScriptedAgent("B", "b"))

    assert outcome.actions_taken == 0
    assert outcome.forced_end is True


def test_rejected_action_is_fed_back_next_observation(make_entity, make_combat):
    fighter = make_entity("Fighter", team="a", pos=(0, 0, 0), attacks=[melee_attack()])
    goblin = make_entity("Goblin", team="b", pos=(5, 0, 0))
    combat = _started(make_combat, [fighter, goblin], fighter)

    # First an illegal attack (bad target), then end the turn.
    illegal = ToolCall("attack", {"action_name": "Longsword", "defender_id": "bad"})
    agent = _RecordingAgent([illegal, ToolCall("end_turn", {})])
    run_turn(combat, fighter, agent)

    assert "rejected_actions" not in agent.seen[0]  # nothing rejected yet on the first call
    fed = agent.seen[1]["rejected_actions"]  # the second call carries the rejection + reason
    assert fed[0]["action"]["name"] == "attack"
    assert "Unknown entity_id" in fed[0]["error"]


def test_success_clears_rejection_feedback(make_entity, make_combat):
    fighter = make_entity("Fighter", team="a", pos=(0, 0, 0), attacks=[melee_attack()])
    goblin = make_entity("Goblin", team="b", pos=(5, 0, 0), hp=30)
    combat = _started(make_combat, [fighter, goblin], fighter)

    illegal = ToolCall("attack", {"action_name": "Longsword", "defender_id": "bad"})
    good = ToolCall("attack", {"action_name": "Longsword", "defender_id": goblin.entity_id})
    agent = _RecordingAgent([illegal, good, ToolCall("end_turn", {})])
    run_turn(combat, fighter, agent)

    assert "rejected_actions" in agent.seen[1]  # after the illegal attempt
    assert "rejected_actions" not in agent.seen[2]  # cleared after the successful attack


def test_kite_option_ends_turn_out_of_reach(make_entity, make_combat):
    """Choosing the kite_range move opens distance and lands the archer out of melee reach."""
    archer = make_entity("Archer", team="a", pos=(0, 0, 0), attacks=[ranged_attack()])
    bruiser = make_entity("Bruiser", team="b", pos=(40, 0, 0), attacks=[melee_attack()])
    combat = _started(make_combat, [archer, bruiser], archer)

    agent = _SequenceAgent(
        [ToolCall("move", {"option_id": f"kite_range:{bruiser.entity_id}"}), ToolCall("end_turn", {})]
    )
    outcome = run_turn(combat, archer, agent)

    assert outcome.failures == 0  # the kite move was legal by construction
    dist = math.dist((archer.x, archer.z), (bruiser.x, bruiser.z))
    assert dist > 40  # opened the gap rather than standing and trading
    melee_reach = archer.stat_block.size.size_ft / 2 + bruiser.stat_block.size.size_ft / 2 + 5
    assert dist > melee_reach  # ends the turn beyond the bruiser's reach


def test_transcript_records_turn(make_entity, make_combat):
    fighter = make_entity("Fighter", team="a", pos=(0, 0, 0), attacks=[melee_attack()])
    goblin = make_entity("Goblin", team="b", pos=(5, 0, 0), hp=30)
    combat = _started(make_combat, [fighter, goblin], fighter)

    transcript = Transcript()
    run_turn(combat, fighter, ScriptedAgent("A", "a"), transcript=transcript)

    assert transcript.records_of("turn_start")
    assert transcript.records_of("action")
    assert transcript.records_of("turn_end")
