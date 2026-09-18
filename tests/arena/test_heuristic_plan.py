"""Turn-plan enumeration: legal-by-construction candidates for the common tactics."""

from src.arena.action_space import move_candidates
from src.arena.heuristic.plan import enumerate_plans
from src.arena.information_policy import FULL_INFORMATION

from .conftest import melee_attack, ranged_attack


def _has_attack_plan(plans, target_id, *, pre_move=None, post_move=None):
    for p in plans:
        if (
            p.action is None
            or p.action.kind != "attack"
            or p.action.target_id != target_id
        ):
            continue
        if pre_move is not None and (p.pre_move is None) == pre_move:
            continue
        if post_move is not None and (p.post_move is None) == post_move:
            continue
        return True
    return False


def test_stay_and_attack_plan_when_in_range(make_entity, make_combat):
    a = make_entity("A", team="a", pos=(0, 0, 0), attacks=[melee_attack()])
    b = make_entity("B", team="b", pos=(5, 0, 0), attacks=[melee_attack()])
    combat = make_combat([a, b])

    plans = enumerate_plans(combat, a, policy=FULL_INFORMATION)
    assert any(
        p.pre_move is None
        and p.action is not None
        and p.action.target_id == b.entity_id
        for p in plans
    )


def test_ranged_unit_gets_a_kite_tail(make_entity, make_combat):
    a = make_entity("A", team="a", pos=(0, 0, 0), attacks=[ranged_attack(range_ft=80)])
    b = make_entity("B", team="b", pos=(10, 0, 0), attacks=[melee_attack()])
    combat = make_combat([a, b])

    plans = enumerate_plans(combat, a, policy=FULL_INFORMATION)
    # some plan shoots B and then falls back (a post_move tail) — attack-then-retreat.
    assert any(
        p.action is not None
        and p.action.target_id == b.entity_id
        and p.post_move is not None
        for p in plans
    )


def test_out_of_range_melee_unit_plans_to_close(make_entity, make_combat):
    a = make_entity("A", team="a", pos=(0, 0, 0), attacks=[melee_attack()])
    b = make_entity("B", team="b", pos=(40, 0, 0), attacks=[melee_attack()])
    combat = make_combat([a, b])

    plans = enumerate_plans(combat, a, policy=FULL_INFORMATION)
    # a close-to-melee move paired with the attack it enables.
    assert any(
        p.pre_move is not None
        and p.pre_move.option_id.startswith("toward_melee:")
        and p.action is not None
        for p in plans
    )


def test_every_move_used_is_a_legal_candidate(make_entity, make_combat):
    """No plan invents a destination — all come from the overlap-checked candidates."""
    a = make_entity("A", team="a", pos=(0, 0, 0), attacks=[melee_attack()])
    b = make_entity("B", team="b", pos=(40, 0, 0), attacks=[melee_attack()])
    combat = make_combat([a, b])

    legal_ids = {m.option_id for m in move_candidates(combat, a)}
    plans = enumerate_plans(combat, a, policy=FULL_INFORMATION)
    used = {p.pre_move.option_id for p in plans if p.pre_move is not None}
    used |= {p.post_move.option_id for p in plans if p.post_move is not None}
    assert used <= legal_ids


# --- disengage gating: melee holds ground, ranged/escapable units may open range --------


def _move_ids(plans):
    ids = {p.pre_move.option_id for p in plans if p.pre_move is not None}
    ids |= {p.post_move.option_id for p in plans if p.post_move is not None}
    return ids


def _disengages(ids):
    return any(i.startswith(("retreat:", "kite_range:")) for i in ids)


def test_healthy_melee_unit_is_offered_no_disengage_plans(make_entity, make_combat):
    a = make_entity("A", team="a", pos=(0, 0, 0), attacks=[melee_attack()])
    b = make_entity("B", team="b", pos=(10, 0, 0), attacks=[melee_attack()])
    combat = make_combat([a, b])

    ids = _move_ids(enumerate_plans(combat, a, policy=FULL_INFORMATION))
    assert not _disengages(ids)  # it holds its ground rather than backpedalling
    assert any(i.startswith("toward_melee:") for i in ids)  # advancing is still offered


def test_ranged_unit_is_offered_disengage_plans(make_entity, make_combat):
    a = make_entity("A", team="a", pos=(0, 0, 0), attacks=[ranged_attack(range_ft=80)])
    b = make_entity("B", team="b", pos=(10, 0, 0), attacks=[melee_attack()])
    combat = make_combat([a, b])

    assert _disengages(_move_ids(enumerate_plans(combat, a, policy=FULL_INFORMATION)))


def test_cornered_melee_flees_only_when_it_can_outrun_the_threat(
    make_entity, make_combat
):
    a = make_entity("A", team="a", pos=(0, 0, 0), hp=30, attacks=[melee_attack()])
    a.current_hp = 3  # hurt: 3/30 below RETREAT_HP_FRACTION
    b = make_entity("B", team="b", pos=(10, 0, 0), attacks=[melee_attack()])  # speed 30
    combat = make_combat([a, b])

    a.stat_block.resource_defaults["speed"] = 40  # faster than the enemy -> may flee
    assert _disengages(_move_ids(enumerate_plans(combat, a, policy=FULL_INFORMATION)))

    a.stat_block.resource_defaults["speed"] = 30  # equal speed -> fleeing is futile
    assert not _disengages(
        _move_ids(enumerate_plans(combat, a, policy=FULL_INFORMATION))
    )
