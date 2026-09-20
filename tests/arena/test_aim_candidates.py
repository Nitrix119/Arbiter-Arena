"""The area-targeting menu: complete, honest about who it hits, and never opinionated.

Three properties matter, in order:

1. **Truthful.** Every offered point, executed for real, hits exactly the set it
   advertised. A menu that lies is worse than no menu — the study would be measuring
   the menu's bugs rather than the agent's choices.
2. **Non-redundant.** One representative per distinct set of targets. 5e area damage has
   no falloff, so the target set *is* the outcome.
3. **Neutral.** It enumerates what is possible and never ranks it. `HeuristicAgent` has
   a placement search that scores foes-caught minus allies-caught; borrowing it would
   put the heuristic's judgement inside the menu (V1_PLAN §3.1).
"""

import ast
from pathlib import Path

import pytest

from src.arena.action_space import (
    DEFAULT_MAX_AIM_POINTS,
    aim_candidates,
    aim_coverage,
    legal_actions,
)
from src.arena.tools import ToolCall, ToolExecutor

from .conftest import force_turn, load_spell

_ACTION_SPACE = (
    Path(__file__).resolve().parents[2] / "src" / "arena" / "action_space.py"
)


@pytest.fixture
def fireball():
    return load_spell("fireball.json")


def _mage(make_entity, pos=(0, 0, 0), team="a"):
    return make_entity(
        "Mage",
        team=team,
        pos=pos,
        hp=20,
        known_spells=["Fireball"],
        spellcasting_ability="intelligence",
        spell_slot_defaults={3: 2},
    )


def _fight(make_entity, make_combat, registry_with, fireball, extra=()):
    """A mage with two enemies 15 ft apart and one ally between them and home."""
    mage = _mage(make_entity)
    ally = make_entity("Knight", team="a", pos=(0, 0, 25), hp=30)
    foe1 = make_entity("Raider 1", team="b", pos=(0, 0, 60), hp=30)
    foe2 = make_entity("Raider 2", team="b", pos=(15, 0, 60), hp=30)
    entities = [mage, ally, foe1, foe2, *extra]
    combat = make_combat(entities, registry=registry_with(fireball))
    combat.start_combat()
    force_turn(combat, mage)
    return combat, mage


# -- truthfulness ------------------------------------------------------------


def test_every_offered_point_hits_exactly_what_it_advertised(
    make_entity, make_combat, registry_with, fireball
):
    """The property §3.1 demands of the enumerated condition, checked early.

    Executed through the real ToolExecutor, so the menu is compared against the
    engine's own resolution rather than against itself.
    """
    combat, mage = _fight(make_entity, make_combat, registry_with, fireball)
    options = aim_candidates(combat, mage, fireball)
    assert options

    for option in options:
        # Restore the board between casts. The options describe *one* battlefield
        # state, and a real fireball kills people — without this the later options
        # would be checked against a board that the earlier ones had already changed,
        # and a dead creature simply is not caught.
        for entity in combat.combatants:
            entity.current_hp = entity.max_hp
        mage.resources.actions = 1
        mage.spell_slots.remaining[3] = 2
        force_turn(combat, mage)

        result = ToolExecutor(combat).apply(
            mage,
            ToolCall(
                "cast_spell",
                {
                    "spell_name": "Fireball",
                    "target_point": {"x": option.x, "y": option.y, "z": option.z},
                },
            ),
        )

        assert result["ok"] is True, (option.option_id, result)
        hit = {r["target_id"] for r in result["results"]}
        assert hit == {t.entity_id for t in option.hits}, option.option_id


def test_an_enemy_beyond_range_is_not_offered(
    make_entity, make_combat, registry_with, fireball
):
    """Range really bounds the sweep.

    Note the caster is always within range of *itself*, so the menu is not empty —
    self-immolation stays a legal, offered, correctly tagged option. The menu reports
    what is possible; it does not decide what is sensible.
    """
    mage = _mage(make_entity)
    far = make_entity("Raider", team="b", pos=(0, 0, 900), hp=30)
    combat = make_combat([mage, far], registry=registry_with(fireball))

    options = aim_candidates(combat, mage, fireball)

    assert not any(t.entity_id == far.entity_id for o in options for t in o.hits)
    assert all(t.relation == "self" for o in options for t in o.hits)


def test_a_non_area_spell_has_no_aim_points(make_entity, make_combat, registry_with):
    firebolt = load_spell("firebolt.json")
    wizard = make_entity(
        "Wizard",
        team="a",
        pos=(0, 0, 0),
        known_spells=["Firebolt"],
        spellcasting_ability="intelligence",
    )
    goblin = make_entity("Goblin", team="b", pos=(20, 0, 0))
    combat = make_combat([wizard, goblin], registry=registry_with(firebolt))

    assert aim_candidates(combat, wizard, firebolt) == []


# -- non-redundancy and ordering ---------------------------------------------


def test_no_two_options_share_a_set_of_targets(
    make_entity, make_combat, registry_with, fireball
):
    combat, mage = _fight(make_entity, make_combat, registry_with, fireball)
    options = aim_candidates(combat, mage, fireball)

    sets = [frozenset(t.entity_id for t in o.hits) for o in options]
    assert len(set(sets)) == len(sets)


def test_no_option_catches_nobody(make_entity, make_combat, registry_with, fireball):
    combat, mage = _fight(make_entity, make_combat, registry_with, fireball)
    assert all(o.hits for o in aim_candidates(combat, mage, fireball))


def test_ordering_is_stable_and_carries_no_quality_signal(
    make_entity, make_combat, registry_with, fireball
):
    """Sorted by target ids, not by how good the option is.

    Ordering a menu by "most enemies hit" would rank it, and ranking is a nudge in a
    study about how agents choose. The check is that the first option is *not* the
    best one.
    """
    combat, mage = _fight(make_entity, make_combat, registry_with, fireball)
    first = aim_candidates(combat, mage, fireball)
    second = aim_candidates(combat, mage, fireball)

    assert [o.option_id for o in first] == [o.option_id for o in second]
    assert [o.option_id for o in first] == sorted(o.option_id for o in first)

    enemies_hit = [sum(1 for t in o.hits if t.relation == "enemy") for o in first]
    assert enemies_hit != sorted(enemies_hit, reverse=True)


def test_the_cap_is_not_biting_on_a_realistic_fight(
    make_entity, make_combat, registry_with, fireball
):
    """A cap that truncates would silently remove real options."""
    combat, mage = _fight(make_entity, make_combat, registry_with, fireball)
    assert len(aim_candidates(combat, mage, fireball)) < DEFAULT_MAX_AIM_POINTS


def test_the_cap_is_honoured_when_it_does_bite(
    make_entity, make_combat, registry_with, fireball
):
    combat, mage = _fight(make_entity, make_combat, registry_with, fireball)
    assert len(aim_candidates(combat, mage, fireball, max_candidates=2)) == 2


# -- honesty about friendly fire ---------------------------------------------


def test_an_ally_in_the_blast_is_offered_and_tagged(
    make_entity, make_combat, registry_with, fireball
):
    """The menu shows the careless option and labels it — it does not hide or judge it.

    Withholding self-defeating options would be the menu playing the game. The study
    measures whether the agent notices.
    """
    combat, mage = _fight(make_entity, make_combat, registry_with, fireball)
    options = aim_candidates(combat, mage, fireball)

    catches_ally = [o for o in options if any(t.relation == "ally" for t in o.hits)]
    assert catches_ally

    both_foes_and_ally = [
        o for o in catches_ally if sum(1 for t in o.hits if t.relation == "enemy") == 2
    ]
    assert both_foes_and_ally, "the careless placement must be reachable"

    clean = [
        o
        for o in options
        if sum(1 for t in o.hits if t.relation == "enemy") == 2
        and all(t.relation == "enemy" for t in o.hits)
    ]
    assert clean, "the good placement must also be reachable, or it is not a decision"


def test_self_is_tagged_when_the_caster_is_in_its_own_blast(
    make_entity, make_combat, registry_with, fireball
):
    combat, mage = _fight(make_entity, make_combat, registry_with, fireball)
    options = aim_candidates(combat, mage, fireball)

    assert any(t.relation == "self" for o in options for t in o.hits)


def test_a_spell_that_spares_its_caster_never_lists_them(
    make_entity, make_combat, registry_with, fireball
):
    """`cannot_cause_self_damage` must be honoured by the menu as well as the engine."""
    object.__setattr__(fireball, "cannot_cause_self_damage", True)
    combat, mage = _fight(make_entity, make_combat, registry_with, fireball)

    options = aim_candidates(combat, mage, fireball)
    assert options
    assert not any(t.relation == "self" for o in options for t in o.hits)


# -- other shapes ------------------------------------------------------------


@pytest.mark.parametrize(
    "filename", ["lightning_bolt.json", "cone_of_cold.json", "burning_hands.json"]
)
def test_directional_shapes_produce_candidates(
    filename, make_entity, make_combat, registry_with
):
    """Cone and line originate at the caster, so the aim point only sets facing.

    A positional sweep still covers them: points giving the same facing collapse into
    one option under the target-set rule, so no separate directional sweep is needed.
    """
    spell = load_spell(filename)
    caster = make_entity(
        "Mage",
        team="a",
        pos=(0, 0, 0),
        known_spells=[spell.name],
        spellcasting_ability="intelligence",
        spell_slot_defaults={1: 2, 3: 2, 5: 2},
    )
    foe1 = make_entity("Raider 1", team="b", pos=(0, 0, 10), hp=30)
    foe2 = make_entity("Raider 2", team="b", pos=(5, 0, 10), hp=30)
    combat = make_combat([caster, foe1, foe2], registry=registry_with(spell))

    options = aim_candidates(combat, caster, spell)
    assert options, f"{filename} produced no aim points"
    assert all(o.hits for o in options)


# -- the menu, end to end ----------------------------------------------------


def test_aim_points_reach_the_observation_menu(
    make_entity, make_combat, registry_with, fireball
):
    """The seam: a field on a dataclass proves nothing until something populates it."""
    combat, mage = _fight(make_entity, make_combat, registry_with, fireball)
    menu = legal_actions(combat, mage).to_dict()

    spell = next(s for s in menu["spells"] if s["name"] == "Fireball")
    assert spell["aim_points"], "an area spell with no aim guidance is unusable"
    first = spell["aim_points"][0]
    assert {"option_id", "x", "y", "z", "hits"} <= set(first)
    assert first["hits"][0]["relation"] in {"self", "ally", "enemy"}


# -- neutrality --------------------------------------------------------------


def test_the_generator_does_not_import_the_heuristic():
    """§3.1: the menu must not smuggle in `HeuristicAgent`'s placement search.

    Checked structurally rather than by inspection, because the temptation to reuse
    that search is real — it already exists, it is tested, and it does something very
    close to this. The difference is that it *ranks*, and this must not.
    """
    tree = ast.parse(_ACTION_SPACE.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)

    offenders = [m for m in imported if "heuristic" in m]
    assert not offenders, f"action_space must not depend on the heuristic: {offenders}"


# -- what the resolution costs (H4's expressivity number) --------------------


def test_the_menu_resolution_loses_nothing_on_this_geometry(
    make_entity, make_combat, registry_with, fireball
):
    """The measured answer to H4's area arm, at the chosen grid step.

    Because a target set fully determines an area spell's outcome, a menu offering
    every achievable set costs no expressivity — the enumerated condition can express
    everything free aiming can. That is a *finding*, not an assumption, which is why
    it is measured here rather than argued: 100% at 5 ft, on this geometry.
    """
    combat, mage = _fight(make_entity, make_combat, registry_with, fireball)

    coverage = aim_coverage(combat, mage, fireball)

    assert coverage.coverage == 1.0
    assert coverage.missing == []
    assert coverage.achievable > 1, "a trivial space would make this vacuous"


def test_the_metric_can_detect_a_loss(
    make_entity, make_combat, registry_with, fireball
):
    """A coverage metric that always reports 100% would measure nothing.

    At a coarser step the sweep really does miss an achievable target set, so the
    number above is a result rather than an artefact of the metric.
    """
    combat, mage = _fight(make_entity, make_combat, registry_with, fireball)

    coarse = aim_coverage(combat, mage, fireball, menu_step_ft=20.0)

    assert coarse.coverage < 1.0
    assert coarse.missing
    assert all(isinstance(entry, list) for entry in coarse.missing)


def test_coverage_names_which_target_sets_were_lost(
    make_entity, make_combat, registry_with, fireball
):
    """ "3 of 9" is not actionable; which three is."""
    combat, mage = _fight(make_entity, make_combat, registry_with, fireball)

    coarse = aim_coverage(combat, mage, fireball, menu_step_ft=20.0)
    offered = {
        tuple(t.entity_id for t in o.hits)
        for o in aim_candidates(combat, mage, fireball, step_ft=20.0)
    }

    assert coarse.achievable - coarse.offered == len(coarse.missing)
    for entry in coarse.missing:
        assert tuple(entry) not in offered


def test_coverage_of_an_empty_space_is_not_a_division_by_zero(
    make_entity, make_combat, registry_with, fireball
):
    mage = _mage(make_entity)
    far = make_entity("Raider", team="b", pos=(0, 0, 900), hp=30)
    combat = make_combat([mage, far], registry=registry_with(fireball))

    assert aim_coverage(combat, mage, fireball).coverage <= 1.0


def test_coverage_serialises_for_the_record():
    from src.arena.action_space import AimCoverage

    data = AimCoverage(achievable=9, offered=8, missing=[["a", "b"]]).to_dict()
    assert data["coverage"] == pytest.approx(0.8889, abs=1e-4)
    assert data["missing"] == [["a", "b"]]
