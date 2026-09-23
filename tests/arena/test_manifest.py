"""A transcript must say which experiment it is, and fingerprint what happened.

These are the two properties the rest of the study leans on: the batch runner
identifies a grid cell from the transcript alone, and ``ReplayVerifier`` proves a
replay by comparing per-turn hashes. Both are tested through a **real match**, not a
hand-built record — the seam between "the field exists" and "something populates it"
is exactly where a feature dies unnoticed (CLAUDE.md §9, 2026-08-08).
"""

import json

from src.arena.agent import ScriptedAgent
from src.arena.manifest import (
    MATCH_RECORD_SCHEMA,
    Manifest,
    canonical_json,
    prompt_hash,
    state_hash,
)
from src.arena.match import run_match
from src.arena.transcript import Transcript
from src.utils import dice

from .conftest import melee_attack


def _duel(make_entity, make_combat):
    fighter = make_entity("Fighter", team="a", pos=(0, 0, 0), attacks=[melee_attack()])
    goblin = make_entity(
        "Goblin", team="b", pos=(5, 0, 0), hp=20, attacks=[melee_attack("Scimitar")]
    )
    return make_combat([fighter, goblin])


def _play(make_entity, make_combat, *, seed=7, manifest=None):
    """Run a seeded scripted duel and return its transcript.

    The combat is built **under the seed** on purpose. Entity ids come from the RNG
    (``dice.new_id``) and appear in the state snapshot, so a match built outside the
    seed produces different ids — and therefore different hashes — for what is
    otherwise the same battle. ``ReplayVerifier`` inherits this requirement: a replay
    must rebuild its entities under the recorded seed, or nothing will line up.
    """
    transcript = Transcript()
    with dice.using_rng(dice.new_rng(seed)):
        combat = _duel(make_entity, make_combat)
    run_match(
        combat,
        {"a": ScriptedAgent("A", "a"), "b": ScriptedAgent("B", "b")},
        seed=seed,
        transcript=transcript,
        manifest=manifest,
    )
    return transcript


# -- manifest ----------------------------------------------------------------


def test_manifest_round_trips_through_a_real_match(make_entity, make_combat):
    manifest = Manifest(
        commit="abc123",
        scenario="alpha_strike",
        seed=7,
        condition="C3",
        model="vendor/model-x",
        temperature=0.0,
        prompt_hash=prompt_hash("system text", "action section"),
    )

    transcript = _play(make_entity, make_combat, manifest=manifest)
    start = json.loads(transcript.to_jsonl().splitlines()[0])

    assert start["kind"] == "match_start"
    assert start["condition"] == "C3"
    assert start["scenario"] == "alpha_strike"
    assert start["model"] == "vendor/model-x"
    assert start["commit"] == "abc123"
    assert start["temperature"] == 0.0
    # The seed is written once, by the transcript itself — not duplicated by the
    # manifest, where a second copy could disagree with the one the match ran under.
    assert start["seed"] == 7
    assert start["schema_versions"]["match_record"] == MATCH_RECORD_SCHEMA
    # The pre-existing fields are untouched by the merge.
    assert start["teams"] and start["combatants"] and start["round_cap"]


def test_a_match_without_a_manifest_still_logs(make_entity, make_combat):
    """A bare functionality match must not require study metadata to run."""
    transcript = _play(make_entity, make_combat)
    start = transcript.records_of("match_start")[0]

    assert "condition" not in start  # absent, not null
    assert "model" not in start
    assert start["teams"]


def test_empty_manifest_fields_are_omitted_not_nulled():
    data = Manifest(condition="C1").to_dict()
    assert data["condition"] == "C1"
    assert "model" not in data
    assert "scenario" not in data
    assert data["schema_versions"]  # always stamped, even on a near-empty manifest


def test_temperature_zero_survives_the_omit_filter():
    """0.0 is a real, meaningful value — a falsy-based filter would drop it."""
    assert Manifest(temperature=0.0).to_dict()["temperature"] == 0.0


def test_prompt_hash_is_stable_and_separator_safe():
    assert prompt_hash("a", "b") == prompt_hash("a", "b")
    assert prompt_hash("a", "b") != prompt_hash("ab", "")
    assert prompt_hash("system") != prompt_hash("System")


# -- state hash --------------------------------------------------------------


def test_same_seed_reproduces_the_whole_hash_sequence(make_entity, make_combat):
    """The property ``ReplayVerifier`` will be built on.

    Two runs of the same seed with the same deterministic agents are the same battle,
    so every per-turn fingerprint must match — not just the final outcome.
    """
    first = _play(make_entity, make_combat, seed=7)
    second = _play(make_entity, make_combat, seed=7)

    hashes = [r["state_hash"] for r in first.records_of("turn_end")]
    assert hashes, "the match recorded no turns"
    assert hashes == [r["state_hash"] for r in second.records_of("turn_end")]


def test_a_different_seed_diverges(make_entity, make_combat):
    """A hash that never changed would pass the test above for the wrong reason."""
    a = [
        r["state_hash"]
        for r in _play(make_entity, make_combat, seed=7).records_of("turn_end")
    ]
    b = [
        r["state_hash"]
        for r in _play(make_entity, make_combat, seed=99).records_of("turn_end")
    ]
    assert a != b


def test_hash_follows_the_state_it_is_recorded_with(make_entity, make_combat):
    transcript = _play(make_entity, make_combat, seed=7)
    for record in transcript.records_of("turn_end"):
        assert record["state_hash"] == state_hash(record["state"])


def test_one_hit_point_changes_the_hash():
    before = {"entities": [{"id": "x", "hp": 10}]}
    after = {"entities": [{"id": "x", "hp": 9}]}
    assert state_hash(before) != state_hash(after)


def test_key_order_does_not_change_the_hash():
    assert state_hash({"a": 1, "b": 2}) == state_hash({"b": 2, "a": 1})


def test_float_drift_does_not_change_the_hash():
    """The 2026-09-19 movement-drift class must not make one battle look like two.

    30 - 7.1 - 7.1 evaluates to 15.799999999999999 in binary floating point. Two runs
    that reached the same budget by different arithmetic are the same state.
    """
    clean = {"movement": 15.8}
    drifted = {"movement": 30 - 7.1 - 7.1}
    assert drifted["movement"] != clean["movement"]  # genuinely different floats
    assert state_hash(drifted) == state_hash(clean)


def test_integral_floats_and_ints_agree():
    assert state_hash({"hp": 30}) == state_hash({"hp": 30.0})


def test_booleans_are_not_collapsed_into_numbers():
    """``bool`` is an ``int`` subclass — a careless normaliser makes True == 1."""
    assert state_hash({"alive": True}) != state_hash({"alive": 1})
    assert "true" in canonical_json({"alive": True})


# -- the interface fingerprint: everything the model is shown ---------------------------


def test_the_fingerprint_covers_the_tool_schemas_not_just_the_prompt(monkeypatch):
    """A tool description is part of what the model reads, so editing one must show.

    The hash used to cover the system prompt alone, while C2's tool descriptions were
    edited on 2026-09-24 — a change the recorded hash could never have revealed.
    """
    from src.arena import tools
    from src.arena.interfaces import C2, get_interface
    from src.arena.manifest import interface_fingerprint

    before = interface_fingerprint(get_interface(C2))
    edited = [dict(t) for t in tools.TOOLS]
    edited[0] = {**edited[0], "description": edited[0]["description"] + " (edited)"}
    monkeypatch.setattr(tools, "TOOLS", edited)
    monkeypatch.setattr("src.arena.interfaces.TOOLS", edited)

    assert interface_fingerprint(get_interface(C2)) != before


def test_each_condition_has_its_own_stable_fingerprint():
    from src.arena.interfaces import REGISTRY, get_interface
    from src.arena.manifest import interface_fingerprint

    prints = {name: interface_fingerprint(get_interface(name)) for name in REGISTRY}
    assert len(set(prints.values())) == len(REGISTRY)
    assert prints == {n: interface_fingerprint(get_interface(n)) for n in REGISTRY}
