"""Tests for the tool executor — the single execution seam.

These run against a live ``CombatSystem`` (started, with the actor's turn forced) so
they prove the executor really dispatches to the engine and shapes/gates results, not
that it echoes a hand-built dict.
"""

import pytest

from src.arena.information_policy import InformationPolicy
from src.arena.tools import TOOLS, ToolCall, ToolExecutor
from src.models.action_resources import ActionCost

from .conftest import force_turn, load_spell, melee_attack

NO_AC = InformationPolicy(reveal_enemy_ac=False)


def _started(make_combat, entities, focus, registry=None):
    combat = make_combat(entities, registry=registry)
    combat.start_combat()
    force_turn(combat, focus)
    return combat


# -- schema ------------------------------------------------------------------


def test_tools_are_json_schema_shaped():
    names = {t["name"] for t in TOOLS}
    assert names == {"attack", "cast_spell", "move", "end_turn"}
    for tool in TOOLS:
        assert set(tool) >= {"name", "description", "input_schema"}
        assert tool["input_schema"]["type"] == "object"


# -- attack ------------------------------------------------------------------


def test_attack_applies_and_shows_own_roll(make_entity, make_combat):
    fighter = make_entity("Fighter", team="a", pos=(0, 0, 0), attacks=[melee_attack()])
    goblin = make_entity("Goblin", team="b", pos=(5, 0, 0), hp=20)
    combat = _started(make_combat, [fighter, goblin], fighter)

    result = ToolExecutor(combat).apply(
        fighter,
        ToolCall(
            "attack", {"action_name": "Longsword", "defender_id": goblin.entity_id}
        ),
    )

    assert result["ok"] is True
    assert result["action"] == "attack"
    assert result["target_id"] == goblin.entity_id
    assert isinstance(result["hit"], bool)
    assert isinstance(result["damage"], int)
    # Own roll is always shown...
    assert "attack_roll" in result["roll"]
    assert "attack_total" in result["roll"]
    # ...and under full information the target's AC is too (C3).
    assert result["roll"]["target_ac"] == goblin.ac


def test_attack_hides_target_ac_under_policy(make_entity, make_combat):
    fighter = make_entity("Fighter", team="a", pos=(0, 0, 0), attacks=[melee_attack()])
    goblin = make_entity("Goblin", team="b", pos=(5, 0, 0), hp=20)
    combat = _started(make_combat, [fighter, goblin], fighter)

    result = ToolExecutor(combat).apply(
        fighter,
        ToolCall(
            "attack", {"action_name": "Longsword", "defender_id": goblin.entity_id}
        ),
        NO_AC,
    )

    assert result["ok"] is True
    assert "attack_roll" in result["roll"]  # own roll still shown
    assert "target_ac" not in result["roll"]  # the number rolled against is hidden


def test_attack_unknown_defender_is_structured_error(make_entity, make_combat):
    fighter = make_entity("Fighter", team="a", attacks=[melee_attack()])
    goblin = make_entity("Goblin", team="b", pos=(5, 0, 0))
    combat = _started(make_combat, [fighter, goblin], fighter)

    result = ToolExecutor(combat).apply(
        fighter, ToolCall("attack", {"action_name": "Longsword", "defender_id": "nope"})
    )
    assert result["ok"] is False
    assert "Unknown entity_id" in result["error"]


def test_attack_unknown_action_is_structured_error(make_entity, make_combat):
    fighter = make_entity("Fighter", team="a", attacks=[melee_attack()])
    goblin = make_entity("Goblin", team="b", pos=(5, 0, 0))
    combat = _started(make_combat, [fighter, goblin], fighter)

    result = ToolExecutor(combat).apply(
        fighter,
        ToolCall(
            "attack", {"action_name": "Fireball", "defender_id": goblin.entity_id}
        ),
    )
    assert result["ok"] is False
    assert "no attack called" in result["error"]


def test_attack_out_of_turn_is_structured_error(make_entity, make_combat):
    fighter = make_entity("Fighter", team="a", pos=(0, 0, 0), attacks=[melee_attack()])
    goblin = make_entity("Goblin", team="b", pos=(5, 0, 0))
    combat = _started(
        make_combat, [fighter, goblin], goblin
    )  # goblin's turn, not fighter's

    result = ToolExecutor(combat).apply(
        fighter,
        ToolCall(
            "attack", {"action_name": "Longsword", "defender_id": goblin.entity_id}
        ),
    )
    assert result["ok"] is False
    assert "not" in result["error"].lower() and "turn" in result["error"].lower()


# -- move --------------------------------------------------------------------


def test_move_applies_and_spends_movement(make_entity, make_combat):
    fighter = make_entity("Fighter", team="a", pos=(0, 0, 0))
    goblin = make_entity("Goblin", team="b", pos=(50, 0, 50))
    combat = _started(make_combat, [fighter, goblin], fighter)

    result = ToolExecutor(combat).apply(
        fighter, ToolCall("move", {"x": 15, "y": 0, "z": 0})
    )

    assert result["ok"] is True
    assert result["position"] == {"x": 15, "y": 0, "z": 0}
    assert result["movement_remaining"] == 15  # 30 - 15 ft travelled
    assert (fighter.x, fighter.z) == (15, 0)


def test_move_too_far_is_structured_error(make_entity, make_combat):
    fighter = make_entity("Fighter", team="a", pos=(0, 0, 0))
    goblin = make_entity("Goblin", team="b", pos=(200, 0, 200))
    combat = _started(make_combat, [fighter, goblin], fighter)

    result = ToolExecutor(combat).apply(fighter, ToolCall("move", {"x": 100, "z": 100}))
    assert result["ok"] is False
    assert "afford" in result["error"].lower()
    assert (fighter.x, fighter.z) == (0, 0)  # position unchanged on failure


def test_move_by_option_id_resolves_to_candidate_destination(make_entity, make_combat):
    from src.arena.action_space import move_candidates

    fighter = make_entity("Fighter", team="a", pos=(0, 0, 0), attacks=[melee_attack()])
    goblin = make_entity("Goblin", team="b", pos=(60, 0, 0))
    combat = _started(make_combat, [fighter, goblin], fighter)

    option = next(
        o
        for o in move_candidates(combat, fighter)
        if o.option_id == f"toward_melee:{goblin.entity_id}"
    )
    result = ToolExecutor(combat).apply(
        fighter, ToolCall("move", {"option_id": option.option_id})
    )

    assert result["ok"] is True
    assert (fighter.x, fighter.y, fighter.z) == (option.x, option.y, option.z)
    assert 0 < fighter.x <= 30  # moved toward the enemy, within budget


def test_move_unknown_option_id_is_structured_error(make_entity, make_combat):
    fighter = make_entity("Fighter", team="a", pos=(0, 0, 0))
    goblin = make_entity("Goblin", team="b", pos=(60, 0, 0))
    combat = _started(make_combat, [fighter, goblin], fighter)

    result = ToolExecutor(combat).apply(
        fighter, ToolCall("move", {"option_id": "toward_melee:nope"})
    )
    assert result["ok"] is False
    assert "nope" in result["error"]
    assert (fighter.x, fighter.z) == (0, 0)


def test_move_without_option_or_coords_is_structured_error(make_entity, make_combat):
    fighter = make_entity("Fighter", team="a", pos=(0, 0, 0))
    goblin = make_entity("Goblin", team="b", pos=(60, 0, 0))
    combat = _started(make_combat, [fighter, goblin], fighter)

    result = ToolExecutor(combat).apply(fighter, ToolCall("move", {}))
    assert result["ok"] is False
    assert "option_id" in result["error"]


# -- end_turn ----------------------------------------------------------------


def test_end_turn_advances_the_turn(make_entity, make_combat):
    fighter = make_entity("Fighter", team="a", attacks=[melee_attack()])
    goblin = make_entity("Goblin", team="b", pos=(5, 0, 0))
    combat = _started(make_combat, [fighter, goblin], fighter)
    assert combat.get_current_entity() is fighter

    result = ToolExecutor(combat).apply(fighter, ToolCall("end_turn", {}))

    assert result["ok"] is True
    assert result["ended_turn"] is True
    assert combat.get_current_entity() is not fighter


# -- cast_spell --------------------------------------------------------------


def test_cast_attack_spell_shows_own_roll_gates_ac(
    make_entity, make_combat, registry_with
):
    firebolt = load_spell("firebolt.json")
    wizard = make_entity(
        "Wizard",
        team="a",
        pos=(0, 0, 0),
        known_spells=[firebolt.name],
        spellcasting_ability="intelligence",
    )
    goblin = make_entity("Goblin", team="b", pos=(10, 0, 0), hp=20)
    combat = _started(
        make_combat, [wizard, goblin], wizard, registry=registry_with(firebolt)
    )

    executor = ToolExecutor(combat)
    full = executor.apply(
        wizard,
        ToolCall(
            "cast_spell",
            {"spell_name": firebolt.name, "target_ids": [goblin.entity_id]},
        ),
    )
    assert full["ok"] is True
    roll = full["results"][0]["roll"]
    assert "attack_roll" in roll
    assert roll["target_ac"] == goblin.ac

    # Reset the wizard's action for a second cast under a stricter policy.
    wizard.resources.actions = 1
    force_turn(combat, wizard)
    hidden = executor.apply(
        wizard,
        ToolCall(
            "cast_spell",
            {"spell_name": firebolt.name, "target_ids": [goblin.entity_id]},
        ),
        NO_AC,
    )
    assert "target_ac" not in hidden["results"][0]["roll"]


def test_cast_save_spell_shows_own_dc_gates_target_roll(
    make_entity, make_combat, registry_with
):
    sacred_flame = load_spell("sacred_flame.json")
    cleric = make_entity(
        "Cleric",
        team="a",
        pos=(0, 0, 0),
        known_spells=[sacred_flame.name],
        spellcasting_ability="wisdom",
    )
    goblin = make_entity("Goblin", team="b", pos=(10, 0, 0), hp=20)
    combat = _started(
        make_combat, [cleric, goblin], cleric, registry=registry_with(sacred_flame)
    )

    result = ToolExecutor(combat).apply(
        cleric,
        ToolCall(
            "cast_spell",
            {"spell_name": sacred_flame.name, "target_ids": [goblin.entity_id]},
        ),
        NO_AC,
    )

    assert result["ok"] is True
    roll = result["results"][0]["roll"]
    assert "save_dc" in roll  # the actor's own DC is shown...
    assert "target_saved" in roll  # ...and the outcome...
    assert (
        "target_save_roll" not in roll
    )  # ...but not the target's roll value under NO_AC


def test_cast_unknown_spell_is_structured_error(
    make_entity, make_combat, registry_with
):
    firebolt = load_spell("firebolt.json")
    wizard = make_entity(
        "Wizard",
        team="a",
        known_spells=[firebolt.name],
        spellcasting_ability="intelligence",
    )
    goblin = make_entity("Goblin", team="b", pos=(10, 0, 0))
    combat = _started(
        make_combat, [wizard, goblin], wizard, registry=registry_with(firebolt)
    )

    result = ToolExecutor(combat).apply(
        wizard,
        ToolCall(
            "cast_spell",
            {"spell_name": "Meteor Swarm", "target_ids": [goblin.entity_id]},
        ),
    )
    assert result["ok"] is False
    assert "does not know" in result["error"]


# -- dispatch ----------------------------------------------------------------


def test_unknown_tool_is_structured_error(make_entity, make_combat):
    fighter = make_entity("Fighter", team="a", attacks=[melee_attack()])
    goblin = make_entity("Goblin", team="b", pos=(5, 0, 0))
    combat = _started(make_combat, [fighter, goblin], fighter)

    result = ToolExecutor(combat).apply(fighter, ToolCall("teleport", {}))
    assert result["ok"] is False
    assert "Unknown tool" in result["error"]


def test_cost_constant_sanity():
    # Guards the melee fixture's cost assumption used across tests.
    assert ActionCost(actions=1).actions == 1


# -- aiming an area spell ----------------------------------------------------


def _fireball_fight(make_entity, make_combat, registry_with):
    fireball = load_spell("fireball.json")
    wizard = make_entity(
        "Wizard",
        team="a",
        pos=(0, 0, 0),
        known_spells=[fireball.name],
        spellcasting_ability="intelligence",
        spell_slot_defaults={"3": 2},
    )
    goblin = make_entity("Goblin", team="b", pos=(0, 0, 40), hp=30)
    combat = _started(
        make_combat, [wizard, goblin], wizard, registry=registry_with(fireball)
    )
    return combat, wizard, goblin, fireball


def test_target_point_schema_only_requires_keys_the_executor_reads():
    """The schema and the code must agree on which coordinates are mandatory.

    They did not: the schema required ``x``/``y`` while the executor read ``x``/``z``,
    so a model obeying the schema exactly — naming a ground point as x/y — hit a
    KeyError. y is the *vertical* axis, which a ground-level aim never needs.
    """
    schema = next(t for t in TOOLS if t["name"] == "cast_spell")["input_schema"]
    point = schema["properties"]["target_point"]

    assert set(point["required"]) == {"x", "z"}
    assert "y" not in point["required"]
    # Every axis says which way it points, so the convention is not guesswork.
    for axis, direction in (("x", "east"), ("y", "up"), ("z", "south")):
        assert direction in point["properties"][axis]["description"]


def test_aiming_with_ground_coordinates_succeeds(
    make_entity, make_combat, registry_with
):
    combat, wizard, goblin, _ = _fireball_fight(make_entity, make_combat, registry_with)

    result = ToolExecutor(combat).apply(
        wizard,
        ToolCall(
            "cast_spell",
            {"spell_name": "Fireball", "target_point": {"x": 0, "z": 40}},
        ),
    )

    assert result["ok"] is True, result
    assert [r["target_id"] for r in result["results"]] == [goblin.entity_id]


def test_an_explicit_vertical_coordinate_is_still_honoured(
    make_entity, make_combat, registry_with
):
    combat, wizard, goblin, _ = _fireball_fight(make_entity, make_combat, registry_with)

    result = ToolExecutor(combat).apply(
        wizard,
        ToolCall(
            "cast_spell",
            {"spell_name": "Fireball", "target_point": {"x": 0, "y": 0, "z": 40}},
        ),
    )
    assert result["ok"] is True, result


def test_aiming_high_above_the_target_misses_it(
    make_entity, make_combat, registry_with
):
    """Proves y is read as the vertical axis, not ignored."""
    combat, wizard, goblin, _ = _fireball_fight(make_entity, make_combat, registry_with)

    result = ToolExecutor(combat).apply(
        wizard,
        ToolCall(
            "cast_spell",
            {"spell_name": "Fireball", "target_point": {"x": 0, "y": 100, "z": 40}},
        ),
    )
    assert result["ok"] is True
    assert result["results"] == []  # the blast went off far overhead


def test_a_missing_ground_coordinate_is_malformed_output_not_a_crash(
    make_entity, make_combat, registry_with
):
    """The old failure mode: a model names a 2-D point as x/y and omits z."""
    combat, wizard, _, _ = _fireball_fight(make_entity, make_combat, registry_with)

    result = ToolExecutor(combat).apply(
        wizard,
        ToolCall(
            "cast_spell",
            {"spell_name": "Fireball", "target_point": {"x": 0, "y": 40}},
        ),
    )

    assert result["ok"] is False
    assert result["code"] == "malformed_output"
    assert "z" in result["error"]  # names the coordinate it wanted


def test_the_system_prompt_states_the_axis_convention():
    """Per-tool descriptions are not enough — the convention is stated once, centrally."""
    from src.arena.llm_common import SYSTEM_PROMPT

    lowered = SYSTEM_PROMPT.lower()
    assert "east" in lowered and "south" in lowered
    assert "ground plane" in lowered


# -- identifier resolution (shared by every raw-parameter condition) ----------


def _duel(make_entity, make_combat, registry=None, **mage_kwargs):
    mage = make_entity(
        "Mage", team="a", pos=(0, 0, 0), attacks=[melee_attack("Dagger")], **mage_kwargs
    )
    raider = make_entity("Raider 1", team="b", pos=(5, 0, 0), hp=40)
    return mage, raider, _started(make_combat, [mage, raider], mage, registry)


@pytest.mark.parametrize("written", ["raider-1", "Raider 1", "RAIDER_1", "raider–1"])
def test_a_target_resolves_however_it_is_written(make_entity, make_combat, written):
    mage, raider, combat = _duel(make_entity, make_combat)
    result = ToolExecutor(combat).apply(
        mage, ToolCall("attack", {"action_name": "Dagger", "defender_id": written})
    )
    assert result["ok"], result
    assert result["target_id"] == raider.entity_id


def test_an_attack_name_resolves_however_it_is_cased(make_entity, make_combat):
    mage, raider, combat = _duel(make_entity, make_combat)
    result = ToolExecutor(combat).apply(
        mage, ToolCall("attack", {"action_name": "dagger", "defender_id": "raider-1"})
    )
    assert result["ok"], result


def test_a_spell_name_resolves_however_it_is_cased(
    make_entity, make_combat, registry_with
):
    mage, raider, combat = _duel(
        make_entity,
        make_combat,
        registry_with(load_spell("fireball.json")),
        known_spells=["Fireball"],
        spell_slot_defaults={"3": 1},
        spellcasting_ability="intelligence",
    )
    result = ToolExecutor(combat).apply(
        mage,
        ToolCall(
            "cast_spell", {"spell_name": "FIRE BALL", "target_point": {"x": 5, "z": 30}}
        ),
    )
    assert result["ok"], result
    assert result["spell"] == "Fireball"  # reported by its real name


def test_an_invented_target_is_never_repaired(make_entity, make_combat):
    mage, raider, combat = _duel(make_entity, make_combat)
    result = ToolExecutor(combat).apply(
        mage, ToolCall("attack", {"action_name": "Dagger", "defender_id": "raider-3"})
    )
    assert result["code"] == "unknown_target"


def test_an_invented_attack_is_never_repaired(make_entity, make_combat):
    mage, raider, combat = _duel(make_entity, make_combat)
    result = ToolExecutor(combat).apply(
        mage, ToolCall("attack", {"action_name": "Dagge", "defender_id": "raider-1"})
    )
    assert result["code"] == "unknown_action"


def test_an_ambiguous_name_is_refused_not_guessed(make_entity, make_combat):
    """Two creatures a reader could not tell apart by this spelling: refuse."""
    mage = make_entity(
        "Mage", team="a", pos=(0, 0, 0), attacks=[melee_attack("Dagger")]
    )
    one = make_entity("Wolf A", team="b", pos=(5, 0, 0))
    two = make_entity("WolfA", team="b", pos=(0, 0, 5))  # ids wolf-a / wolfa: one key
    combat = _started(make_combat, [mage, one, two], mage)
    result = ToolExecutor(combat).apply(
        mage, ToolCall("attack", {"action_name": "Dagger", "defender_id": "WOLF A"})
    )
    assert result["code"] == "unknown_target"
    assert "ambiguous" in result["error"].lower()
