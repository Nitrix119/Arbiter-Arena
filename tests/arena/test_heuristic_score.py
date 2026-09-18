"""The utility function: threat-weighting, kill-securing, overkill, and exposure."""

from src.arena.heuristic import features
from src.arena.heuristic.plan import PlannedAction, TurnPlan
from src.arena.heuristic.score import DEFAULT_WEIGHTS, score
from src.arena.information_policy import FULL_INFORMATION
from src.models import AttackAction, Damage, DamageType

from .conftest import melee_attack, ranged_attack

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


def _attack_plan(target, name="Longsword"):
    return PlannedAction("attack", name, target.entity_id)


def test_prefers_higher_threat_target_at_equal_hp(make_entity, make_combat):
    a = make_entity("A", team="a", pos=(0, 0, 0), attacks=[melee_attack()])
    cannon = make_entity("Cannon", team="b", pos=(5, 0, 0), hp=20, attacks=[_strong_attack()])
    tank = make_entity("Tank", team="b", pos=(5, 5, 0), hp=20, attacks=[_weak_attack()])
    combat = make_combat([a, cannon, tank])

    prog_cannon, _ = features.offense(a, _attack_plan(cannon), combat, policy=POLICY)
    prog_tank, _ = features.offense(a, _attack_plan(tank), combat, policy=POLICY)
    assert prog_cannon > prog_tank  # same damage/HP, but the cannon is worth more to remove


def test_secures_available_kill(make_entity, make_combat):
    a = make_entity("A", team="a", pos=(0, 0, 0), attacks=[_strong_attack()])
    low = make_entity("Low", team="b", pos=(5, 0, 0), hp=3, attacks=[_weak_attack()])
    high = make_entity("High", team="b", pos=(5, 5, 0), hp=30, attacks=[_weak_attack()])
    combat = make_combat([a, low, high])

    _, kill_low = features.offense(a, _attack_plan(low, "Greatsword"), combat, policy=POLICY)
    _, kill_high = features.offense(a, _attack_plan(high, "Greatsword"), combat, policy=POLICY)
    assert kill_low > 0 and kill_high == 0


def test_score_prefers_finishing_over_chipping(make_entity, make_combat):
    """Overkill falls out: min(dmg, hp) caps the near-dead target's value, but the kill wins."""
    a = make_entity("A", team="a", pos=(0, 0, 0), attacks=[_strong_attack()])
    low = make_entity("Low", team="b", pos=(5, 0, 0), hp=3, attacks=[_weak_attack()])
    high = make_entity("High", team="b", pos=(5, 5, 0), hp=30, attacks=[_weak_attack()])
    combat = make_combat([a, low, high])

    s_low = score(
        TurnPlan(None, _attack_plan(low, "Greatsword"), None),
        combat, a, policy=POLICY, weights=DEFAULT_WEIGHTS,
    )
    s_high = score(
        TurnPlan(None, _attack_plan(high, "Greatsword"), None),
        combat, a, policy=POLICY, weights=DEFAULT_WEIGHTS,
    )
    assert s_low > s_high


def test_exposure_penalises_being_in_melee_reach(make_entity, make_combat):
    archer = make_entity("Archer", team="a", pos=(0, 0, 0), hp=20, attacks=[ranged_attack()])
    chaser = make_entity("Chaser", team="b", pos=(10, 0, 0), attacks=[melee_attack()])
    combat = make_combat([archer, chaser])

    near = features.exposure_fraction(archer, (0.0, 0.0, 0.0), combat, policy=POLICY)
    far = features.exposure_fraction(archer, (200.0, 0.0, 0.0), combat, policy=POLICY)
    assert near > 0.0 and far == 0.0


def test_hidden_capabilities_fall_back_to_generic_threat(make_entity, make_combat):
    from src.arena.information_policy import InformationPolicy

    a = make_entity("A", team="a", pos=(0, 0, 0), attacks=[melee_attack()])
    enemy = make_entity("E", team="b", pos=(5, 0, 0), hp=20, attacks=[_strong_attack()])
    combat = make_combat([a, enemy])
    hidden = InformationPolicy(reveal_enemy_actions=False)

    # With capabilities hidden, threat is the generic default, not the true strong DPR.
    known = features.threat(enemy, known=True)
    unknown = features.threat(enemy, known=False)
    assert known != unknown
    assert unknown == features.GENERIC_INCOMING
