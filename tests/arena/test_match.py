"""Tests for the match runner — a full headless battle, end to end."""

from typing import Any, Dict, List

from src.arena.agent import Agent, ScriptedAgent
from src.arena.match import run_match
from src.arena.tools import ToolCall
from src.arena.transcript import Transcript
from src.combat.enums import CombatState

from .conftest import force_turn, melee_attack


class PacifistAgent(Agent):
    """Always ends its turn — used to force a round-cap outcome."""

    def decide(self, observation: Dict[str, Any]) -> ToolCall:
        return ToolCall("end_turn", {})


def _duel(make_entity, make_combat):
    a = make_entity("Knight", team="a", pos=(0, 0, 0), hp=12, attacks=[melee_attack()])
    b = make_entity("Bandit", team="b", pos=(5, 0, 0), hp=12, attacks=[melee_attack()])
    return make_combat([a, b])


def test_scripted_duel_produces_a_winner(make_entity, make_combat):
    combat = _duel(make_entity, make_combat)
    agents = {"a": ScriptedAgent("A", "a"), "b": ScriptedAgent("B", "b")}
    transcript = Transcript()

    result = run_match(combat, agents, seed=7, transcript=transcript)

    assert combat.state == CombatState.ENDED
    assert result.reason == "last_standing"
    assert result.winner in {"a", "b"}
    assert result.rounds <= 20
    # The transcript captured the whole match.
    assert transcript.records_of("match_start")
    assert transcript.records_of("action")
    assert transcript.records_of("match_end")[0]["winner"] == result.winner


def test_scripted_2v2_makes_no_illegal_moves(make_entity, make_combat):
    """The heuristic must not trip over occupied space in a crowded fight (the 2v2 bug)."""
    entities = [
        make_entity("A1", team="a", pos=(0, 0, 0), hp=15, attacks=[melee_attack()]),
        make_entity("A2", team="a", pos=(0, 0, 10), hp=15, attacks=[melee_attack()]),
        make_entity("B1", team="b", pos=(15, 0, 0), hp=15, attacks=[melee_attack()]),
        make_entity("B2", team="b", pos=(15, 0, 10), hp=15, attacks=[melee_attack()]),
    ]
    combat = make_combat(entities)
    agents = {"a": ScriptedAgent("A", "a"), "b": ScriptedAgent("B", "b")}
    transcript = Transcript()

    run_match(combat, agents, seed=1, transcript=transcript)

    failed = [
        r
        for r in transcript.records_of("action")
        if r["call"]["name"] == "move" and not r["result"].get("ok")
    ]
    assert failed == []  # every move the heuristic chose was legal by construction


def test_match_is_deterministic_under_a_seed(make_entity, make_combat):
    def play():
        combat = _duel(make_entity, make_combat)
        agents = {"a": ScriptedAgent("A", "a"), "b": ScriptedAgent("B", "b")}
        return run_match(combat, agents, seed=42)

    first, second = play(), play()
    assert (first.winner, first.rounds) == (second.winner, second.rounds)


def test_round_cap_ends_a_stalemate_as_a_draw(make_entity, make_combat):
    combat = _duel(make_entity, make_combat)
    agents = {"a": PacifistAgent("A", "a"), "b": PacifistAgent("B", "b")}

    result = run_match(combat, agents, seed=1, round_cap=2)

    assert result.reason == "round_cap"
    assert result.winner is None  # equal (full) HP -> draw
    assert combat.state == CombatState.ACTIVE  # nobody died


def test_stronger_side_wins(make_entity, make_combat):
    strong = make_entity(
        "Champion", team="a", pos=(0, 0, 0), hp=40, attacks=[melee_attack()]
    )
    weakling = make_entity(
        "Kobold", team="b", pos=(5, 0, 0), hp=3, attacks=[melee_attack()]
    )
    combat = make_combat([strong, weakling])
    agents = {"a": ScriptedAgent("A", "a"), "b": ScriptedAgent("B", "b")}

    result = run_match(combat, agents, seed=3)

    assert result.winner == "a"
    assert result.reason == "last_standing"


# -- a fight ends the moment one side is left (ledger A24) -----------------------------


def _sure_kill():
    """Hits on anything but a natural 1, and kills anything in the tests below."""
    from src.models import AttackAction, Damage, DamageType

    return AttackAction(
        name="Executioner",
        description="",
        bonus_to_hit=50,
        damage=[Damage(DamageType.SLASHING, formula="100")],
        range_ft=5.0,
    )


def _two_on_one(make_entity, make_combat):
    fighter = make_entity("Fighter", team="a", pos=(0, 0, 0), attacks=[_sure_kill()])
    ally = make_entity("Squire", team="a", pos=(0, 0, 10))
    goblin = make_entity("Goblin", team="b", pos=(5, 0, 0), hp=5)
    combat = make_combat([fighter, ally, goblin])
    combat.start_combat()
    force_turn(combat, fighter)
    return combat, fighter, ally, goblin


def test_combat_ends_at_the_killing_blow_whoever_survives(make_entity, make_combat):
    """Two survivors on one side is a finished fight, not one that plays on."""
    combat, fighter, ally, goblin = _two_on_one(make_entity, make_combat)
    combat.rng.seed(3)
    round_before = combat.round

    hit, _, _ = combat.resolve_attack(fighter, goblin, _sure_kill())

    assert hit and not goblin.is_alive()
    assert fighter.is_alive() and ally.is_alive()
    assert combat.state == CombatState.ENDED
    assert combat.round == round_before  # decided mid-turn; no round was started


def test_end_turn_catches_a_death_from_an_effect(make_entity, make_combat):
    """A creature can die outside an attack (damage over time); ending the turn must
    then end the fight rather than start another round."""
    combat, fighter, _, goblin = _two_on_one(make_entity, make_combat)
    goblin.current_hp = 0
    round_before = combat.round

    combat.end_turn(fighter.entity_id)

    assert combat.state == CombatState.ENDED
    assert combat.round == round_before


def test_ending_a_turn_after_the_fight_is_over_changes_nothing(
    make_entity, make_combat
):
    combat, fighter, _, goblin = _two_on_one(make_entity, make_combat)
    combat.rng.seed(3)
    combat.resolve_attack(fighter, goblin, _sure_kill())
    state = (combat.round, combat.turn, len(combat.log))

    combat.end_turn(fighter.entity_id)  # the web UI's "end turn" after a kill

    assert combat.state == CombatState.ENDED
    assert (combat.round, combat.turn, len(combat.log)) == state


def test_creatures_without_a_team_each_fight_for_themselves(make_entity, make_combat):
    """Free-for-all (no teams): the fight goes on while two creatures stand."""
    a = make_entity("A", pos=(0, 0, 0), attacks=[_sure_kill()])
    b = make_entity("B", pos=(5, 0, 0), hp=5)
    c = make_entity("C", pos=(0, 0, 20))
    combat = make_combat([a, b, c])
    combat.start_combat()
    force_turn(combat, a)
    combat.rng.seed(3)

    combat.resolve_attack(a, b, _sure_kill())

    assert not b.is_alive()
    assert combat.state == CombatState.ACTIVE  # A and C are still opponents


def test_a_won_match_records_no_decision_after_the_win(make_entity, make_combat):
    """The winners used to take turns against nobody until the round cap: paid calls
    wasted, and H1 padded with trivial decisions in exactly the matches a model won."""
    fighter = make_entity("Fighter", team="a", pos=(0, 0, 0), attacks=[_sure_kill()])
    ally = make_entity("Squire", team="a", pos=(0, 0, 10), attacks=[melee_attack()])
    goblin = make_entity("Goblin", team="b", pos=(5, 0, 0), hp=5)
    combat = make_combat([fighter, ally, goblin])
    agents = {"a": ScriptedAgent("A", "a"), "b": ScriptedAgent("B", "b")}
    transcript = Transcript()

    result = run_match(combat, agents, seed=3, transcript=transcript)

    assert result.winner == "a" and result.reason == "last_standing"
    assert not goblin.is_alive()
    records = transcript.records
    kill = max(
        i
        for i, r in enumerate(records)
        if r["kind"] == "action" and r["result"].get("damage")
    )
    assert [r["kind"] for r in records[kill + 1 :]] == ["turn_end", "match_end"]
    assert records[kill + 1]["end_cause"] == "over"
    assert result.rounds == records[kill + 1]["state"]["round"]
