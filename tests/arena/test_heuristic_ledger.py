"""Team damage-ledger: allies concentrate fire without overkilling (§8)."""

from src.arena.heuristic.agent import HeuristicAgent
from src.arena.observation import build_observation
from src.arena.tools import TOOLS
from src.models import AttackAction, Damage, DamageType

from .conftest import force_turn


def _big_melee():
    return AttackAction(
        name="Maul", description="", bonus_to_hit=8,
        damage=[Damage(DamageType.BLUDGEONING, formula="3d8+5")], range_ft=5.0,
    )


def test_second_ally_switches_off_a_committed_kill(make_entity, make_combat):
    # Two allied maulers, each expecting ~19 damage. Two equal-threat enemies: one at low
    # HP (one blow kills), one healthy. The first mauler commits the kill; the second must
    # switch to the healthy enemy rather than overkill the dying one.
    a1 = make_entity("A1", team="a", pos=(0, 0, 0), attacks=[_big_melee()])
    a2 = make_entity("A2", team="a", pos=(0, 5, 0), attacks=[_big_melee()])
    low = make_entity("Low", team="b", pos=(5, 0, 0), hp=12, attacks=[_big_melee()])
    high = make_entity("High", team="b", pos=(5, 5, 0), hp=40, attacks=[_big_melee()])
    combat = make_combat([a1, a2, low, high])
    combat.start_combat()

    agent = HeuristicAgent("Team", "a", combat)

    force_turn(combat, a1)
    call1 = agent.decide(build_observation(combat, a1), TOOLS)
    assert call1.name == "attack" and call1.arguments["defender_id"] == low.entity_id

    # Same agent, same round: the ledger now reserves the kill on `low`.
    force_turn(combat, a2)
    call2 = agent.decide(build_observation(combat, a2), TOOLS)
    assert call2.name == "attack" and call2.arguments["defender_id"] == high.entity_id


def test_ledger_resets_between_rounds(make_entity, make_combat):
    a1 = make_entity("A1", team="a", pos=(0, 0, 0), attacks=[_big_melee()])
    low = make_entity("Low", team="b", pos=(5, 0, 0), hp=12, attacks=[_big_melee()])
    combat = make_combat([a1, low])
    combat.start_combat()
    agent = HeuristicAgent("Team", "a", combat)

    force_turn(combat, a1)
    agent.decide(build_observation(combat, a1), TOOLS)
    assert agent._ledger  # a commitment was booked this round
    round_one_reserved = dict(agent._ledger)

    # A later round clears the ledger before booking afresh (no cross-round accumulation).
    later = build_observation(combat, a1)
    later["round"] = later["round"] + 1
    agent.decide(later, TOOLS)
    assert agent._ledger == round_one_reserved  # reset, then this round's single commitment
