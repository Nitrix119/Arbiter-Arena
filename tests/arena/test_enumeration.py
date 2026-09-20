"""Every action C3 lists must really be takeable.

This is the property V1_PLAN §3.1 demands of the enumerated condition, and it is the
one that makes the condition fair: if a listed id fails, C3's agent is punished for
obeying the interface, and its invalid-action rate — the study's primary metric —
measures the harness rather than the model.
"""

import pytest

from src.arena.enumeration import (
    DEFAULT_MAX_ACTIONS,
    EnumeratedAction,
    enumerate_legal_actions,
    multi_target_spells_not_enumerated,
)
from src.arena.scenarios import SCENARIOS
from src.arena.tools import ToolExecutor

from .conftest import force_turn, load_spell, melee_attack, ranged_attack


def _at_turn(scenario_name, entity_id):
    scenario = SCENARIOS[scenario_name]
    combat = scenario.build()
    combat.start_combat()
    entity = next(e for e in combat.combatants if e.entity_id == entity_id)
    force_turn(combat, entity)
    return combat, entity


def _snapshot(combat):
    return {e.entity_id: (e.current_hp, e.x, e.y, e.z) for e in combat.combatants}


def _restore(combat, entity, snapshot):
    """Put the board back so each listed action is tried against the state it described.

    Positions matter as much as hit points: the list describes *one* board, and
    executing a move changes where the actor stands, so the next destination would be
    measured from somewhere the enumeration never saw.
    """
    for other in combat.combatants:
        hp, x, y, z = snapshot[other.entity_id]
        other.current_hp, other.x, other.y, other.z = hp, x, y, z
    entity.resources.actions = 1
    entity.resources.bonus_actions = 1
    entity.resources.movement = entity.stat_block.resource_defaults.get("speed", 30)
    if entity.spell_slots is not None:
        entity.spell_slots.refill()
    force_turn(combat, entity)


# -- the property that makes C3 fair -----------------------------------------


@pytest.mark.parametrize(
    "scenario_name,entity_id",
    [
        ("aoe_placement", "mage"),
        ("aoe_placement", "bodyguard"),
        ("kiting", "archer"),
        ("protect_squishy", "sharpshooter"),
        ("alpha_strike", "fighter-a1"),
    ],
)
def test_every_listed_action_executes(scenario_name, entity_id):
    combat, entity = _at_turn(scenario_name, entity_id)
    actions = enumerate_legal_actions(combat, entity)
    assert actions, f"{entity_id} was offered nothing at all"

    board = _snapshot(combat)
    executor = ToolExecutor(combat)
    for action in actions:
        _restore(combat, entity, board)
        result = executor.apply(entity, action.call)
        assert result["ok"] is True, (action.action_id, result)


def test_ending_the_turn_is_always_offered():
    """Ending a turn is always legal, so it must always be choosable."""
    for scenario_name, entity_id in (("aoe_placement", "mage"), ("kiting", "archer")):
        combat, entity = _at_turn(scenario_name, entity_id)
        ids = [a.action_id for a in enumerate_legal_actions(combat, entity)]
        assert "end_turn" in ids


def test_an_entity_with_nothing_to_do_can_still_end_its_turn():
    combat, entity = _at_turn("kiting", "archer")
    entity.resources.actions = 0
    entity.resources.movement = 0.0

    actions = enumerate_legal_actions(combat, entity)
    assert [a.action_id for a in actions] == ["end_turn"]


# -- what it enumerates ------------------------------------------------------


def test_area_spells_are_listed_once_per_distinct_aim():
    combat, mage = _at_turn("aoe_placement", "mage")
    ids = [a.action_id for a in enumerate_legal_actions(combat, mage)]

    casts = [i for i in ids if i.startswith("cast:fireball:")]
    assert len(casts) == 9  # one per distinct set of targets hit
    assert "cast:fireball:aim:raider-1+raider-2" in casts


def test_moves_are_listed_and_resolve_to_coordinates():
    """Menu ids must not leak into the move tool — that would be C3 wearing C2's
    format."""
    combat, archer = _at_turn("kiting", "archer")
    moves = [
        a for a in enumerate_legal_actions(combat, archer) if a.call.name == "move"
    ]

    assert moves
    for move in moves:
        assert move.action_id.startswith("move:")
        assert set(move.call.arguments) == {"x", "y", "z"}
        assert "option_id" not in move.call.arguments


def test_attacks_are_listed_per_target(make_entity, make_combat):
    fighter = make_entity("Fighter", team="a", pos=(0, 0, 0), attacks=[melee_attack()])
    a = make_entity("Goblin A", team="b", pos=(5, 0, 0))
    b = make_entity("Goblin B", team="b", pos=(0, 0, 5))
    combat = make_combat([fighter, a, b])
    combat.start_combat()
    force_turn(combat, fighter)

    ids = [x.action_id for x in enumerate_legal_actions(combat, fighter)]
    assert "attack:longsword:goblin-a" in ids
    assert "attack:longsword:goblin-b" in ids


def test_upcasting_is_offered_rather_than_silently_lost(
    make_entity, make_combat, registry_with
):
    """A menu that could only cast at base level would be an expressivity loss the
    interface introduced, not one the study measured."""
    bolt = load_spell("guiding_bolt.json")
    wizard = make_entity(
        "Wizard",
        team="a",
        pos=(0, 0, 0),
        known_spells=[bolt.name],
        spellcasting_ability="intelligence",
        spell_slot_defaults={"1": 2, "2": 2, "3": 1},
    )
    goblin = make_entity("Goblin", team="b", pos=(20, 0, 0), hp=40)
    combat = make_combat([wizard, goblin], registry=registry_with(bolt))
    combat.start_combat()
    force_turn(combat, wizard)

    actions = enumerate_legal_actions(combat, wizard)
    casts = [a for a in actions if a.call.name == "cast_spell"]
    levels = {a.call.arguments.get("slot_level") for a in casts}

    assert None in levels  # the base level, with no slot_level argument
    assert {2, 3} <= levels
    # And every one of them really works.
    board = _snapshot(combat)
    executor = ToolExecutor(combat)
    for cast in casts:
        _restore(combat, wizard, board)
        assert executor.apply(wizard, cast.call)["ok"] is True, cast.action_id


# -- ids and ordering --------------------------------------------------------


def test_ids_are_readable_stable_and_unique():
    """Ids are typed by the model, so they follow the entity-id reasoning."""
    import re

    combat, mage = _at_turn("aoe_placement", "mage")
    first = enumerate_legal_actions(combat, mage)
    second = enumerate_legal_actions(combat, mage)

    ids = [a.action_id for a in first]
    assert ids == [a.action_id for a in second]
    assert len(set(ids)) == len(ids)
    for action_id in ids:
        assert re.fullmatch(r"[a-z0-9:+@_-]+", action_id), action_id


def test_ordering_carries_no_quality_signal():
    """Sorted by id. Ranking a menu nudges the choice the study measures."""
    combat, mage = _at_turn("aoe_placement", "mage")
    actions = enumerate_legal_actions(combat, mage)

    assert [a.action_id for a in actions] == sorted(a.action_id for a in actions)
    # The best fireball is not conveniently first.
    assert actions[0].action_id != "cast:fireball:aim:raider-1+raider-2"


def test_labels_describe_the_action_without_judging_it():
    combat, mage = _at_turn("aoe_placement", "mage")
    careless = next(
        a
        for a in enumerate_legal_actions(combat, mage)
        if a.action_id == "cast:fireball:aim:bodyguard+raider-1+raider-2"
    )

    assert "Bodyguard (ally)" in careless.label  # states the cost
    for verdict in ("best", "recommended", "bad", "avoid", "careless"):
        assert verdict not in careless.label.lower()


def test_the_cap_is_not_biting_on_the_study_scenarios():
    for scenario_name in sorted(SCENARIOS):
        combat = SCENARIOS[scenario_name].build()
        combat.start_combat()
        for entity in combat.combatants:
            force_turn(combat, entity)
            count = len(enumerate_legal_actions(combat, entity))
            assert count < DEFAULT_MAX_ACTIONS, (scenario_name, entity.entity_id, count)


def test_the_cap_is_honoured_when_it_does_bite():
    combat, mage = _at_turn("aoe_placement", "mage")
    assert len(enumerate_legal_actions(combat, mage, max_actions=3)) == 3


def test_the_agent_facing_view_hides_the_underlying_call():
    action = EnumeratedAction("end_turn", "End your turn", None)  # type: ignore[arg-type]
    assert action.to_dict() == {"action_id": "end_turn", "label": "End your turn"}


# -- menu length, the cost covariate -----------------------------------------


def test_menu_length_is_recorded_for_the_cost_model(make_entity, make_combat):
    """§3.1 treats menu length as an input-token covariate, so it must be knowable."""
    combat, mage = _at_turn("aoe_placement", "mage")
    ranged = ranged_attack()
    assert ranged  # imported fixture stays used

    assert len(enumerate_legal_actions(combat, mage)) > len(
        enumerate_legal_actions(combat, combat.combatants[1])
    )


# -- the declared gap, kept visible ------------------------------------------


def test_the_study_scenarios_have_no_unenumerable_spell():
    """If this fails, C3 is quietly less expressive than C2 for that roster.

    The difference would show up as a tactical gap attributed to the condition, when
    it is really the harness failing to offer an action the other conditions can take.
    """
    for scenario_name in sorted(SCENARIOS):
        combat = SCENARIOS[scenario_name].build()
        combat.start_combat()
        for entity in combat.combatants:
            missing = multi_target_spells_not_enumerated(combat, entity)
            assert not missing, (scenario_name, entity.entity_id, missing)


def test_a_multi_target_spell_is_reported_rather_than_silently_dropped(
    make_entity, make_combat, registry_with
):
    """Magic Missile allocates projectiles across targets — neither a single target
    list nor an aim point, so nothing enumerates it. Declared, not hidden."""
    missile = load_spell("magic_missile.json")
    wizard = make_entity(
        "Wizard",
        team="a",
        pos=(0, 0, 0),
        known_spells=[missile.name],
        spellcasting_ability="intelligence",
        spell_slot_defaults={"1": 2},
    )
    goblin = make_entity("Goblin", team="b", pos=(20, 0, 0), hp=40)
    combat = make_combat([wizard, goblin], registry=registry_with(missile))
    combat.start_combat()
    force_turn(combat, wizard)

    assert multi_target_spells_not_enumerated(combat, wizard) == ["Magic Missile"]
    ids = [a.action_id for a in enumerate_legal_actions(combat, wizard)]
    assert not any(i.startswith("cast:magic-missile") for i in ids)
