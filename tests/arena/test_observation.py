"""Tests for building an agent's observation, including information hiding."""

from src.arena.information_policy import (
    FULL_INFORMATION,
    HP_BUCKETED,
    HP_HIDDEN,
    InformationPolicy,
)
from src.arena.observation import build_observation

from .conftest import melee_attack, single_target_spell


def _setup(make_entity, make_combat):
    me = make_entity("Fighter", team="a", pos=(0, 0, 0), attacks=[melee_attack()])
    ally = make_entity("Cleric", team="a", pos=(5, 0, 0), hp=25)
    enemy = make_entity("Goblin", team="b", pos=(5, 0, 0), hp=30, ac=13)
    enemy.current_hp = 7  # 7 of 30 -> "critical" bucket
    combat = make_combat([me, ally, enemy])
    return me, ally, enemy, combat


def test_observation_shape_and_viewpoint(make_entity, make_combat):
    me, ally, enemy, combat = _setup(make_entity, make_combat)

    obs = build_observation(combat, me)

    assert set(obs) >= {
        "state",
        "round",
        "turn",
        "is_my_turn",
        "self",
        "allies",
        "enemies",
        "legal_actions",
    }
    assert obs["self"]["entity_id"] == me.entity_id
    assert [a["entity_id"] for a in obs["allies"]] == [ally.entity_id]
    assert [e["entity_id"] for e in obs["enemies"]] == [enemy.entity_id]
    # Positions are reported in backend feet, not cell units.
    assert obs["self"]["position"] == {"x": 0, "y": 0, "z": 0}


def test_legal_actions_menu_includes_move_options_and_relations(
    make_entity, make_combat
):
    me = make_entity("Fighter", team="a", pos=(0, 0, 0), attacks=[melee_attack()])
    enemy = make_entity("Goblin", team="b", pos=(40, 0, 0))
    combat = make_combat([me, enemy])

    la = build_observation(combat, me)["legal_actions"]

    assert "moves" in la
    toward = next(
        m for m in la["moves"] if m["option_id"] == f"toward_melee:{enemy.entity_id}"
    )
    assert set(toward) == {
        "option_id",
        "label",
        "description",
        "x",
        "y",
        "z",
        "cost_ft",
    }
    # Attack targets carry their relation to the actor.
    assert la["attacks"][0]["targets"] == []  # enemy is out of melee range at 40 ft


def test_full_information_shows_enemy_hp_and_ac(make_entity, make_combat):
    me, ally, enemy, combat = _setup(make_entity, make_combat)

    enemy_view = build_observation(combat, me, FULL_INFORMATION)["enemies"][0]

    assert enemy_view["hp"] == 7
    assert enemy_view["max_hp"] == enemy.max_hp
    assert enemy_view["ac"] == 13
    assert "conditions" in enemy_view
    assert "resources" in enemy_view


def test_allies_are_never_redacted(make_entity, make_combat):
    me, ally, enemy, combat = _setup(make_entity, make_combat)

    policy = InformationPolicy(reveal_enemy_hp=False, reveal_enemy_ac=False)
    obs = build_observation(combat, me, policy)

    # Self and allies keep full detail regardless of the (enemy-only) policy.
    assert obs["self"]["hp"] == me.current_hp
    assert obs["self"]["ac"] == me.ac
    assert obs["allies"][0]["hp"] == ally.current_hp


def test_hidden_hp_removes_enemy_hp_fields(make_entity, make_combat):
    me, ally, enemy, combat = _setup(make_entity, make_combat)

    policy = InformationPolicy(hp_display=HP_HIDDEN)
    enemy_view = build_observation(combat, me, policy)["enemies"][0]

    assert "hp" not in enemy_view
    assert "max_hp" not in enemy_view
    assert "hp_bucket" not in enemy_view
    # position/name/team are still shown — the battlefield is shared.
    assert enemy_view["name"] == "Goblin"


def test_bucketed_hp_shows_label_not_number(make_entity, make_combat):
    me, ally, enemy, combat = _setup(make_entity, make_combat)  # enemy at 7/30

    policy = InformationPolicy(hp_display=HP_BUCKETED)
    enemy_view = build_observation(combat, me, policy)["enemies"][0]

    assert "hp" not in enemy_view
    assert enemy_view["hp_bucket"] == "critical"


def test_enemy_capabilities_gated_by_policy(make_entity, make_combat):
    me = make_entity("Fighter", team="a", pos=(0, 0, 0), attacks=[melee_attack()])
    enemy = make_entity(
        "Mage",
        team="b",
        pos=(5, 0, 0),
        attacks=[melee_attack("Dagger")],
        known_spells=["Fireball"],
    )
    combat = make_combat([me, enemy])

    shown = build_observation(combat, me, FULL_INFORMATION)["enemies"][0]
    assert shown["actions"] == ["Dagger"]
    assert shown["known_spells"] == ["Fireball"]

    hidden = build_observation(
        combat, me, InformationPolicy(reveal_enemy_actions=False)
    )["enemies"][0]
    assert "actions" not in hidden
    assert "known_spells" not in hidden


def test_hidden_ac_and_resources(make_entity, make_combat):
    me, ally, enemy, combat = _setup(make_entity, make_combat)

    policy = InformationPolicy(reveal_enemy_ac=False, reveal_enemy_resources=False)
    enemy_view = build_observation(combat, me, policy)["enemies"][0]

    assert "ac" not in enemy_view
    assert "resources" not in enemy_view
    # HP still shown (default), proving flags are independent.
    assert enemy_view["hp"] == 7


# -- own capabilities: what a creature *is*, shown in every condition ---------


def test_self_and_allies_carry_their_own_capabilities(
    make_entity, make_combat, registry_with
):
    """Without this, a no-menu condition must guess its own weapon and spell names.

    Names are matched by the executor, and until they were listed here the only place
    a creature's own attacks appeared was the legal-action menu — which C1 and C2 do
    not see. That made C2 → C2+M measure "being told what you are" on top of "being
    told what is legal".
    """
    from .conftest import load_spell

    fireball = load_spell("fireball.json")
    me = make_entity(
        "Mage",
        team="a",
        attacks=[melee_attack("Dagger")],
        known_spells=["Fireball"],
        spell_slot_defaults={"3": 1},
        spellcasting_ability="intelligence",
    )
    ally = make_entity("Guard", team="a", pos=(5, 0, 0), attacks=[melee_attack()])
    combat = make_combat([me, ally], registry=registry_with(fireball))

    obs = build_observation(combat, me)
    mine = obs["self"]["capabilities"]

    assert [a["name"] for a in mine["attacks"]] == ["Dagger"]
    assert mine["attacks"][0]["range_ft"] == 5.0
    (spell,) = mine["spells"]
    assert spell["name"] == "Fireball"
    assert spell["spell_level"] == 3
    assert spell["targeting"] == "aoe"
    assert spell["range_ft"] == 150.0
    assert spell["area"] == {"shape": "sphere", "size_ft": 20}

    assert [a["name"] for a in obs["allies"][0]["capabilities"]["attacks"]] == [
        "Longsword"
    ]


def test_capabilities_are_facts_not_legality(make_entity, make_combat, registry_with):
    """An attack you cannot afford right now is still one you have.

    Affordability belongs to the menu; listing only what is legal here would smuggle
    the menu's affordance into the conditions that are meant not to have it.
    """
    me = make_entity(
        "Mage",
        team="a",
        attacks=[melee_attack("Dagger")],
        known_spells=["Firebolt"],
    )
    combat = make_combat([me], registry=registry_with(single_target_spell()))
    me.resources.actions = 0  # spent: nothing is affordable

    mine = build_observation(combat, me)["self"]["capabilities"]
    assert [a["name"] for a in mine["attacks"]] == ["Dagger"]
    assert [s["name"] for s in mine["spells"]] == ["Firebolt"]
    assert build_observation(combat, me)["legal_actions"]["attacks"] == []


def test_a_spell_missing_from_the_registry_is_still_named(make_entity, make_combat):
    me = make_entity("Mage", team="a", known_spells=["Wish"])
    combat = make_combat([me])

    assert build_observation(combat, me)["self"]["capabilities"]["spells"] == [
        {"name": "Wish"}
    ]


def test_the_state_snapshot_does_not_carry_capabilities(make_entity, make_combat):
    """The snapshot feeds the per-turn state hash; static fields there would change
    every recorded hash and break verification of existing transcripts."""
    from src.arena.observation import snapshot_state

    me, ally, enemy, combat = _setup(make_entity, make_combat)
    for entity in snapshot_state(combat)["entities"]:
        assert "capabilities" not in entity
