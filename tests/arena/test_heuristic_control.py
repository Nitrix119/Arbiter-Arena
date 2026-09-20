"""Control/status scoring and spell-slot economy."""

import pytest

from src.arena.heuristic import features
from src.arena.heuristic.agent import HeuristicAgent
from src.arena.heuristic.plan import PlannedAction
from src.arena.information_policy import FULL_INFORMATION
from src.arena.observation import build_observation
from src.arena.tools import TOOLS
from src.models import AttackAction, Damage, DamageType

from .conftest import force_turn, load_spell

POLICY = FULL_INFORMATION


def _strong_attack():
    return AttackAction(
        name="Greatsword",
        description="",
        bonus_to_hit=7,
        damage=[Damage(DamageType.SLASHING, formula="2d8+5")],
        range_ft=5.0,
    )


def _weak_attack():
    return AttackAction(
        name="Club",
        description="",
        bonus_to_hit=2,
        damage=[Damage(DamageType.BLUDGEONING, formula="1d4")],
        range_ft=5.0,
    )


def _caster(make_entity, known, slots):
    return make_entity(
        "Mage",
        team="a",
        pos=(0, 0, 0),
        hp=20,
        known_spells=known,
        spellcasting_ability="intelligence",
        spell_slot_defaults=slots,
    )


def test_control_scales_with_target_threat(make_entity, make_combat, registry_with):
    caster = _caster(make_entity, ["Charm Person"], {"1": 2})
    scary = make_entity("Scary", team="b", pos=(5, 0, 0), attacks=[_strong_attack()])
    harmless = make_entity(
        "Harmless", team="b", pos=(5, 5, 0), attacks=[_weak_attack()]
    )
    combat = make_combat(
        [caster, scary, harmless], registry_with(load_spell("charm_person.json"))
    )

    v_scary = features.control(
        caster,
        PlannedAction("spell", "Charm Person", scary.entity_id),
        combat,
        policy=POLICY,
    )
    v_harmless = features.control(
        caster,
        PlannedAction("spell", "Charm Person", harmless.entity_id),
        combat,
        policy=POLICY,
    )
    assert v_scary > v_harmless > 0.0  # disabling the dangerous foe is worth more


def test_resource_cost_is_zero_for_cantrips_and_scales_with_level(
    make_entity, make_combat, registry_with
):
    caster = _caster(make_entity, ["Fire Bolt", "Fireball"], {"3": 1})
    foe = make_entity("Foe", team="b", pos=(20, 0, 0), attacks=[_weak_attack()])
    combat = make_combat(
        [caster, foe],
        registry_with(load_spell("firebolt.json"), load_spell("fireball.json")),
    )

    cantrip = features.resource_cost(
        caster, PlannedAction("spell", "Fire Bolt", foe.entity_id), combat
    )
    levelled = features.resource_cost(
        caster, PlannedAction("aoe", "Fireball", foe.entity_id), combat
    )
    assert cantrip == 0.0
    assert levelled == pytest.approx(3 / 9)


def test_caster_saves_the_slot_on_a_trivial_target(
    make_entity, make_combat, registry_with
):
    """One dying enemy that a cantrip finishes — don't burn a 3rd-level slot on it."""
    caster = _caster(make_entity, ["Fire Bolt", "Fireball"], {"3": 1})
    dying = make_entity(
        "Dying", team="b", pos=(20, 0, 0), hp=1, attacks=[_weak_attack()]
    )
    combat = make_combat(
        [caster, dying],
        registry_with(load_spell("firebolt.json"), load_spell("fireball.json")),
    )
    combat.start_combat()
    force_turn(combat, caster)

    agent = HeuristicAgent("Mage", "a", combat)
    call = agent.decide(build_observation(combat, caster))
    assert call.name == "cast_spell" and call.arguments.get("spell_name") == "Fire Bolt"
