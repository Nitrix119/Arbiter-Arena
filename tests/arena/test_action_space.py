"""Tests for legal-action assembly.

These exercise the real range-check, resource, and spell-slot logic — not a
hand-built menu — so they prove the assembler agrees with what the engine would
actually allow.
"""

from src.arena.action_space import legal_actions, move_candidates
from src.models.action_resources import ActionCost

from .conftest import force_turn, melee_attack, ranged_attack, single_target_spell


def test_melee_attack_lists_only_in_range_targets(make_entity, make_combat):
    attacker = make_entity("Fighter", team="a", pos=(0, 0, 0), attacks=[melee_attack()])
    near = make_entity("Goblin", team="b", pos=(5, 0, 0))
    far = make_entity("Archer", team="b", pos=(60, 0, 0))
    combat = make_combat([attacker, near, far])

    legal = legal_actions(combat, attacker)

    assert legal.movement_remaining_ft == 30
    assert legal.can_end_turn is True
    assert len(legal.attacks) == 1
    target_ids = {t.entity_id for t in legal.attacks[0].targets}
    assert near.entity_id in target_ids
    assert far.entity_id not in target_ids
    assert attacker.entity_id not in target_ids  # never targets itself


def test_unaffordable_attack_is_omitted(make_entity, make_combat):
    attacker = make_entity("Fighter", team="a", attacks=[melee_attack()])
    enemy = make_entity("Goblin", team="b", pos=(5, 0, 0))
    combat = make_combat([attacker, enemy])

    attacker.resources.actions = 0  # spent this turn's action already

    assert legal_actions(combat, attacker).attacks == []


def test_no_movement_left_reported(make_entity, make_combat):
    attacker = make_entity("Fighter", team="a", attacks=[melee_attack()])
    enemy = make_entity("Goblin", team="b", pos=(5, 0, 0))
    combat = make_combat([attacker, enemy])

    attacker.resources.movement = 0

    assert legal_actions(combat, attacker).movement_remaining_ft == 0


def test_spells_skipped_without_registry(make_entity, make_combat):
    caster = make_entity("Wizard", team="a", known_spells=["Firebolt"])
    enemy = make_entity("Goblin", team="b", pos=(5, 0, 0))
    combat = make_combat([caster, enemy])  # no registry configured

    assert legal_actions(combat, caster).spells == []


def test_cantrip_is_always_castable(make_entity, make_combat, registry_with):
    firebolt = single_target_spell("Firebolt", spell_level=0)
    caster = make_entity("Wizard", team="a", known_spells=["Firebolt"])
    enemy = make_entity("Goblin", team="b", pos=(10, 0, 0))
    combat = make_combat([caster, enemy], registry=registry_with(firebolt))

    legal = legal_actions(combat, caster)

    assert len(legal.spells) == 1
    spell = legal.spells[0]
    assert spell.name == "Firebolt"
    assert spell.castable_levels == [0]
    assert spell.targeting == "single_target"
    assert {t.entity_id for t in spell.targets} == {enemy.entity_id}


def test_levelled_spell_needs_a_slot(make_entity, make_combat, registry_with):
    scorch = single_target_spell("Scorching Ray", spell_level=1)
    caster = make_entity(
        "Wizard",
        team="a",
        known_spells=["Scorching Ray"],
        spell_slot_defaults={"1": 2, "2": 1},
        spellcasting_ability="intelligence",
    )
    enemy = make_entity("Goblin", team="b", pos=(10, 0, 0))
    combat = make_combat([caster, enemy], registry=registry_with(scorch))

    # With slots, castable at level 1 and (upcast) level 2.
    spell = legal_actions(combat, caster).spells[0]
    assert spell.castable_levels == [1, 2]

    # Drain every slot -> the spell drops out of the menu.
    caster.spell_slots.remaining = {1: 0, 2: 0}
    assert legal_actions(combat, caster).spells == []


def test_out_of_range_single_target_spell_lists_no_targets(
    make_entity, make_combat, registry_with
):
    short = single_target_spell("Shocking Grasp", spell_level=0, distance_ft=5)
    caster = make_entity("Wizard", team="a", pos=(0, 0, 0), known_spells=["Shocking Grasp"])
    enemy = make_entity("Goblin", team="b", pos=(60, 0, 0))
    combat = make_combat([caster, enemy], registry=registry_with(short))

    spell = legal_actions(combat, caster).spells[0]
    assert spell.targets == []  # in the menu, but nobody is reachable


def test_to_dict_is_json_shaped(make_entity, make_combat):
    attacker = make_entity("Fighter", team="a", attacks=[melee_attack()])
    enemy = make_entity("Goblin", team="b", pos=(5, 0, 0))
    combat = make_combat([attacker, enemy])

    data = legal_actions(combat, attacker).to_dict()

    assert set(data) == {
        "entity_id",
        "movement_remaining_ft",
        "attacks",
        "spells",
        "moves",
        "can_end_turn",
    }
    assert data["attacks"][0]["cost"] == ActionCost(actions=1).__dict__
    assert data["attacks"][0]["targets"][0]["entity_id"] == enemy.entity_id
    assert data["attacks"][0]["targets"][0]["relation"] == "enemy"


# -- move candidates ---------------------------------------------------------


def test_move_candidates_are_all_legal(make_entity, make_combat):
    """Every generated destination must be one the engine actually accepts."""
    fighter = make_entity("Fighter", team="a", pos=(0, 0, 0), attacks=[ranged_attack()])
    goblin = make_entity("Goblin", team="b", pos=(40, 0, 0))
    combat = make_combat([fighter, goblin])
    combat.start_combat()
    force_turn(combat, fighter)

    options = move_candidates(combat, fighter)
    assert options  # a ranged attacker vs one enemy has toward/retreat/kite

    budget = fighter.resources.movement
    origin = (fighter.x, fighter.y, fighter.z)
    for opt in options:
        combat.move_entity(fighter, opt.x, opt.y, opt.z)  # must not raise
        assert (fighter.x, fighter.y, fighter.z) == (opt.x, opt.y, opt.z)
        fighter.x, fighter.y, fighter.z = origin  # reset for the next candidate
        fighter.resources.movement = budget


def test_toward_melee_backs_off_a_blocking_third_body(make_entity, make_combat):
    """A standoff point that would land on a third creature is backed off to a clear one."""
    fighter = make_entity("Fighter", team="a", pos=(0, 0, 0), attacks=[melee_attack()])
    goblin = make_entity("Goblin", team="b", pos=(60, 0, 0))
    blocker = make_entity("Bystander", team="b", pos=(30, 0, 0))  # sits in the path
    combat = make_combat([fighter, goblin, blocker])
    combat.start_combat()
    force_turn(combat, fighter)

    toward = next(
        o for o in move_candidates(combat, fighter) if o.option_id == f"toward_melee:{goblin.entity_id}"
    )
    # Naive standoff (~54 ft) is unreachable in 30 ft anyway, but the 30 ft point overlaps the
    # blocker at x=30; the option must be backed off to a clear point and be legal to execute.
    assert combat.is_destination_clear(fighter, toward.x, toward.y, toward.z)
    assert toward.x <= 25  # clear of the blocker's 27.5–32.5 ft footprint
    combat.move_entity(fighter, toward.x, toward.y, toward.z)  # legal, does not raise


def test_kite_option_only_for_ranged_attackers(make_entity, make_combat):
    ranged = make_entity("Archer", team="a", pos=(0, 0, 0), attacks=[ranged_attack()])
    melee = make_entity("Brute", team="a", pos=(0, 0, 10), attacks=[melee_attack()])
    goblin = make_entity("Goblin", team="b", pos=(40, 0, 0))
    combat = make_combat([ranged, melee, goblin])

    ranged_ids = {o.option_id for o in move_candidates(combat, ranged)}
    melee_ids = {o.option_id for o in move_candidates(combat, melee)}

    assert f"kite_range:{goblin.entity_id}" in ranged_ids
    assert f"kite_range:{goblin.entity_id}" not in melee_ids


def test_attacks_exclude_allies_but_spells_tag_every_relation(make_entity, make_combat, registry_with):
    caster = make_entity(
        "Cleric", team="a", pos=(0, 0, 0),
        attacks=[melee_attack()], known_spells=["Firebolt"],
    )
    ally = make_entity("Ally", team="a", pos=(5, 0, 5))
    enemy = make_entity("Goblin", team="b", pos=(5, 0, 0))
    registry = registry_with(single_target_spell("Firebolt", distance_ft=120))
    combat = make_combat([caster, ally, enemy], registry=registry)

    legal = legal_actions(combat, caster)

    # Weapon attack: enemies only, tagged enemy.
    attack_targets = {t.entity_id: t.relation for t in legal.attacks[0].targets}
    assert attack_targets == {enemy.entity_id: "enemy"}

    # Spell: both friend and foe are offered, each tagged by relation.
    spell_targets = {t.entity_id: t.relation for t in legal.spells[0].targets}
    assert spell_targets == {ally.entity_id: "ally", enemy.entity_id: "enemy"}


def test_move_candidates_are_deterministic(make_entity, make_combat):
    fighter = make_entity("Fighter", team="a", pos=(0, 0, 0), attacks=[ranged_attack()])
    g1 = make_entity("G1", team="b", pos=(40, 0, 0))
    g2 = make_entity("G2", team="b", pos=(0, 0, 40))
    combat = make_combat([fighter, g1, g2])

    first = [o.option_id for o in move_candidates(combat, fighter)]
    second = [o.option_id for o in move_candidates(combat, fighter)]
    assert first == second
