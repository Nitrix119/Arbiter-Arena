"""Identifier resolution: forgiving of how a name is *written*, never of which it is.

A model that writes ``Raider 1`` for ``raider-1`` has named the right creature; one
that writes ``raider-3`` has not. The first is a transcription cost the readable-id
control (prereg §4.2) exists to remove, and it is shared by every raw-parameter
condition — C1's parser and C2's tool calls resolve through the same function, so
neither gets a tolerance the other lacks. The second is a hallucination the study
counts, so there is deliberately no edit distance anywhere here.
"""

import pytest

from src.arena.identifiers import identifier_key, resolve


@pytest.mark.parametrize(
    "written",
    ["raider-1", "Raider 1", "RAIDER_1", "raider1", " raider–1 ", "Raider 1"],
)
def test_spellings_of_one_name_share_a_key(written):
    assert identifier_key(written) == "raider1"


def test_distinct_names_keep_distinct_keys():
    assert identifier_key("raider-1") != identifier_key("raider-2")
    assert identifier_key("Magic Missile") != identifier_key("Fireball")


def test_exact_spelling_wins_before_any_normalisation():
    """`goblin` is an exact id even though another goblin is *named* "Goblin"."""
    tiers = [
        [("goblin", "g1"), ("goblin-2", "g2")],
        [("Goblin", "g1"), ("Goblin", "g2")],
    ]
    assert resolve("goblin", tiers) == ["g1"]


def test_an_earlier_tier_wins_on_a_normalised_match():
    tiers = [
        [("goblin", "g1"), ("goblin-2", "g2")],
        [("Goblin", "g1"), ("Goblin", "g2")],
    ]
    assert resolve("GOBLIN", tiers) == ["g1"]  # id key before name key


def test_a_name_resolves_when_no_id_matches():
    tiers = [[("raider-1", "r1"), ("raider-2", "r2")], [("Big Bob", "r1")]]
    assert resolve("big bob", tiers) == ["r1"]


def test_a_collision_is_reported_not_guessed():
    tiers = [[("a-b", "x"), ("ab", "y")]]
    assert sorted(resolve("A B", tiers)) == ["x", "y"]


def test_no_near_miss_is_repaired():
    tiers = [[("raider-1", "r1"), ("raider-2", "r2")]]
    assert resolve("raider-3", tiers) == []
    assert resolve("raidr-1", tiers) == []


def test_punctuation_alone_names_nothing():
    assert resolve("--", [[("combatant", "c")]]) == []
