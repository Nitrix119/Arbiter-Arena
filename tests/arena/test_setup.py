"""The arena's combat-setup path, and the readable entity ids it assigns.

The ids are tested here rather than filed under cosmetics because they are part of the
interface under test: under the free-text and raw-parameter conditions the model types
an entity id to name a target, while the menu condition never does (V1_PLAN §3.4).
"""

import re

import pytest

from src.arena.setup import (
    assign_stable_ids,
    build_combat,
    stable_entity_ids,
)

from .conftest import melee_attack


def test_ids_are_readable_slugs_of_the_creature_names(make_entity, make_combat):
    combat = make_combat(
        [
            make_entity("Fighter A1", team="a", pos=(0, 0, 0)),
            make_entity("Sharpshooter", team="a", pos=(0, 0, 10)),
            make_entity("Raider 1", team="b", pos=(20, 0, 0)),
        ]
    )

    assert [e.entity_id for e in combat.combatants] == [
        "fighter-a1",
        "sharpshooter",
        "raider-1",
    ]


def test_ids_are_stable_across_builds_without_any_seeding(make_entity, make_combat):
    """The property that makes the ids useful — no `using_rng` dance required.

    A replay, and every cell of a paired-seed grid, must name the same creature the
    same way.
    """

    def ids():
        combat = make_combat(
            [
                make_entity("Archer", team="a", pos=(0, 0, 0)),
                make_entity("Bruiser", team="b", pos=(40, 0, 0)),
            ]
        )
        return [e.entity_id for e in combat.combatants]

    assert ids() == ids() == ["archer", "bruiser"]


def test_duplicate_names_get_a_numeric_suffix(make_entity, make_combat):
    """Uniqueness matters more than usual here: ids drive ``__hash__``/``__eq__``.

    Two combatants sharing an id would compare *equal*, so a lookup would silently
    return the wrong creature instead of failing.
    """
    combat = make_combat(
        [
            make_entity("Goblin", team="b", pos=(0, 0, 0)),
            make_entity("Goblin", team="b", pos=(10, 0, 0)),
            make_entity("Goblin", team="b", pos=(20, 0, 0)),
        ]
    )

    ids = [e.entity_id for e in combat.combatants]
    assert ids == ["goblin", "goblin-2", "goblin-3"]
    assert len(set(combat.combatants)) == 3  # distinct under __hash__/__eq__


def test_duplicate_names_across_teams_still_get_distinct_ids(make_entity, make_combat):
    combat = make_combat(
        [
            make_entity("Goblin", team="a", pos=(0, 0, 0)),
            make_entity("Goblin", team="b", pos=(10, 0, 0)),
        ]
    )
    ids = [e.entity_id for e in combat.combatants]
    assert len(set(ids)) == 2


@pytest.mark.parametrize("name", ["!!!", "   ", "---", "..."])
def test_an_unsluggable_name_still_yields_a_usable_id(name, make_entity):
    """A name that reduces to nothing must not produce an empty id."""
    ids = stable_entity_ids([make_entity(name, team="a")])
    assert ids == ["combatant"]


def test_unsluggable_duplicates_do_not_collide(make_entity):
    ids = stable_entity_ids(
        [make_entity("!!!", team="a"), make_entity("???", team="a")]
    )
    assert ids == ["combatant", "combatant-2"]


def test_entities_built_outside_the_arena_keep_a_random_id(make_entity):
    """The web layer constructs entities directly and needs no stable id."""
    entity = make_entity("Fighter", team="a")
    assert re.fullmatch(r"[0-9a-f]{16}", entity.entity_id)


def test_stable_ids_can_be_turned_off(make_entity):
    fighter = make_entity("Fighter", team="a", pos=(0, 0, 0))
    original = fighter.entity_id
    goblin = make_entity("Goblin", team="b", pos=(5, 0, 0))

    build_combat([fighter, goblin], global_rules=False, stable_ids=False)

    assert fighter.entity_id == original


def test_ids_survive_a_real_match(make_entity, make_combat):
    """Prove the wiring, not just the helper — the seam CLAUDE.md §9 2026-08-08 warns of."""
    from src.arena.agent import ScriptedAgent
    from src.arena.match import run_match
    from src.arena.transcript import Transcript

    combat = make_combat(
        [
            make_entity("Knight", team="a", pos=(0, 0, 0), attacks=[melee_attack()]),
            make_entity(
                "Bandit",
                team="b",
                pos=(5, 0, 0),
                hp=12,
                attacks=[melee_attack("Scimitar")],
            ),
        ]
    )
    transcript = Transcript()
    run_match(
        combat,
        {"a": ScriptedAgent("A", "a"), "b": ScriptedAgent("B", "b")},
        seed=3,
        transcript=transcript,
    )

    start = transcript.records_of("match_start")[0]
    assert sorted(start["teams"]["a"] + start["teams"]["b"]) == ["bandit", "knight"]
    # And the ids the agents actually acted with are the readable ones.
    actors = {r["actor_id"] for r in transcript.records_of("action")}
    assert actors <= {"knight", "bandit"}


def test_assign_is_idempotent(make_entity):
    """Re-assigning the same roster yields the same ids, so a double call is harmless."""
    roster = [make_entity("Archer", team="a"), make_entity("Bruiser", team="b")]
    assign_stable_ids(roster)
    first = [e.entity_id for e in roster]
    assign_stable_ids(roster)
    assert [e.entity_id for e in roster] == first
