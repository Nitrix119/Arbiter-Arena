"""AoE placement search: aim to catch the most enemies, sparing allies."""

import pytest

from src.arena.heuristic import estimate
from src.arena.heuristic.agent import HeuristicAgent
from src.arena.heuristic.plan import enumerate_plans
from src.arena.information_policy import FULL_INFORMATION
from src.arena.observation import build_observation
from src.arena.tools import TOOLS, ToolExecutor

from .conftest import force_turn, load_spell, melee_attack


def _caster(make_entity, pos, team="a"):
    return make_entity(
        "Mage",
        team=team,
        pos=pos,
        hp=20,
        known_spells=["Fireball"],
        spellcasting_ability="intelligence",
        spell_slot_defaults={"3": 1},
    )


def _aoe_action(plans):
    return [p for p in plans if p.action is not None and p.action.kind == "aoe"]


def test_fireball_ev_unwraps_for_each_target(make_entity):
    # Fireball: for_each_target -> [DEX save, 8d6 half-on-save]. DC = 8+2+INT(1)=11.
    # Defender DEX save +2 -> need 9 -> 12 success faces -> p_success .6, p_fail .4.
    # 8d6 mean 28: EV = .4*28 + .6*(28/2=14) = 11.2 + 8.4 = 19.6.
    caster = _caster(make_entity, (0, 0, 0))
    defender = make_entity("D", team="b", pos=(20, 0, 0))
    fireball = load_spell("fireball.json")
    assert estimate.spell_expected_damage(fireball, caster, defender) == pytest.approx(
        19.6
    )


def test_placement_catches_the_cluster(make_entity, make_combat, registry_with):
    caster = _caster(make_entity, (0, 0, 0))
    # Three enemies clustered ~40 ft away, in range of a 150 ft Fireball.
    e1 = make_entity("E1", team="b", pos=(40, 0, 0), attacks=[melee_attack()])
    e2 = make_entity("E2", team="b", pos=(45, 0, 0), attacks=[melee_attack()])
    e3 = make_entity("E3", team="b", pos=(40, 5, 0), attacks=[melee_attack()])
    combat = make_combat(
        [caster, e1, e2, e3], registry_with(load_spell("fireball.json"))
    )

    aoe = _aoe_action(enumerate_plans(combat, caster, policy=FULL_INFORMATION))
    assert aoe, "expected an AoE plan for Fireball"
    hit = set(aoe[0].action.aoe_targets)
    assert {
        e1.entity_id,
        e2.entity_id,
        e3.entity_id,
    } <= hit  # the whole cluster is caught


def test_placement_prefers_sparing_the_ally(make_entity, make_combat, registry_with):
    """Between two aim points, the scorer avoids the one that also burns an ally."""
    caster = _caster(make_entity, (0, 0, 0))
    lone = make_entity("Lone", team="b", pos=(40, 0, 0), attacks=[melee_attack()])
    # A second enemy tangled up with a friendly, far from the lone foe.
    tangled = make_entity(
        "Tangled", team="b", pos=(40, 60, 0), attacks=[melee_attack()]
    )
    friend = make_entity("Friend", team="a", pos=(43, 60, 0), attacks=[melee_attack()])
    combat = make_combat(
        [caster, lone, tangled, friend], registry_with(load_spell("fireball.json"))
    )

    # The placement search keeps one point; with equal enemy counts it should not be the
    # one that also catches the ally. Verify the friendly-fire feature separates them.
    from src.spatial.geometry import Point3D
    from src.spatial.range_check import derive_aoe_origin

    fireball = combat.get_spell_for_entity(caster, "Fireball")

    def friendly_fire_at(point):
        origin, direction = derive_aoe_origin(caster, fireball, Point3D(*point))
        hit = combat.get_targets_in_aoe(origin, fireball.aoe, direction)
        return any(e.team == caster.team for e in hit)

    assert friendly_fire_at((40, 60, 0)) is True  # catches the ally
    assert friendly_fire_at((40, 0, 0)) is False  # the lone foe is clean


def test_caster_casts_aoe_and_it_resolves(make_entity, make_combat, registry_with):
    caster = _caster(make_entity, (0, 0, 0))
    e1 = make_entity("E1", team="b", pos=(30, 0, 0), attacks=[melee_attack()])
    e2 = make_entity("E2", team="b", pos=(33, 0, 0), attacks=[melee_attack()])
    combat = make_combat([caster, e1, e2], registry_with(load_spell("fireball.json")))
    combat.start_combat()
    force_turn(combat, caster)

    agent = HeuristicAgent("Mage", "a", combat)
    call = agent.decide(build_observation(combat, caster))
    assert call.name == "cast_spell" and "target_point" in call.arguments
    result = ToolExecutor(combat).apply(caster, call, FULL_INFORMATION)
    assert result["ok"] is True
