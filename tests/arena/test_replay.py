"""A recorded match re-runs to exactly the same states — and a corrupted one does not.

Both directions matter. A verifier that cannot fail proves nothing, so every "it
verifies" test here is paired with evidence that the check would have caught a change.
"""

import pytest

from src.arena.agent import Agent, ScriptedAgent
from src.arena.match import run_match
from src.arena.manifest import Manifest
from src.arena.replay import (
    ReplayAgent,
    ReplayReport,
    verify,
    verify_bundle,
)
from src.arena.scenarios import SCENARIOS
from src.arena.tools import TOOL_ATTACK, TOOL_END_TURN, ToolCall
from src.arena.transcript import Transcript

from .conftest import melee_attack


def _record_scenario(name="alpha_strike", seed=7, round_cap=20):
    sc = SCENARIOS[name]
    transcript = Transcript()
    run_match(
        sc.build(),
        {
            sc.llm_team: ScriptedAgent("A", sc.llm_team),
            sc.heuristic_team: ScriptedAgent("B", sc.heuristic_team),
        },
        seed=seed,
        round_cap=round_cap,
        transcript=transcript,
    )
    return transcript, sc.build


# -- the happy path ----------------------------------------------------------


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_every_scenario_replays_exactly(name):
    transcript, build = _record_scenario(name)
    report = verify(transcript.records, build)

    assert report.ok, report.detail
    assert report.turns_checked > 0
    assert bool(report) is True


def test_the_report_counts_every_recorded_turn():
    transcript, build = _record_scenario()
    report = verify(transcript.records, build)
    assert report.turns_checked == len(transcript.records_of("turn_end"))


# -- the cases that motivated the design -------------------------------------


def test_a_match_with_rejected_actions_replays(make_entity, make_combat):
    """Rejections are replayed, and answer the RNG question by construction.

    Every engine validation runs before the first roll, so a refused action should
    consume no randomness — if it did, skipping or reordering rejections would desync
    the dice and this hash comparison would fail.
    """
    combat, build = _combat_with_a_stubborn_agent()
    transcript = Transcript()
    run_match(
        combat,
        {"a": _IllegalThenLegal("A", "a"), "b": ScriptedAgent("B", "b")},
        seed=11,
        transcript=transcript,
    )

    rejected = [r for r in transcript.records_of("action") if not r["result"]["ok"]]
    assert rejected, "this test needs at least one rejection to be meaningful"

    report = verify(transcript.records, build)
    assert report.ok, report.detail


def test_a_forced_turn_end_replays(make_entity, make_combat):
    """The case that ruled out replaying only accepted actions.

    A turn ended by the failure budget is ended by the driver calling `end_turn`
    directly, so it never appears in the transcript as an action. Driving the replay
    through the ordinary turn driver reproduces it; replaying accepted actions alone
    would have lost it and desynced everything after.
    """
    combat, build = _combat_with_a_stubborn_agent()
    transcript = Transcript()
    run_match(
        combat,
        {"a": _AlwaysIllegal("A", "a"), "b": ScriptedAgent("B", "b")},
        seed=5,
        transcript=transcript,
    )

    # Three consecutive failures trip the budget and force the end.
    failures = [r for r in transcript.records_of("action") if not r["result"]["ok"]]
    assert len(failures) >= 3

    report = verify(transcript.records, build)
    assert report.ok, report.detail


def test_a_no_tool_call_failure_replays(make_entity, make_combat):
    """A model that produced nothing is part of the history and must be reproduced."""
    combat, build = _combat_with_a_stubborn_agent()
    transcript = Transcript()
    run_match(
        combat,
        {"a": _NoToolCallThenEnd("A", "a"), "b": ScriptedAgent("B", "b")},
        seed=5,
        transcript=transcript,
    )

    assert any(
        r["call"]["name"] == "(no_tool_call)" for r in transcript.records_of("action")
    )
    report = verify(transcript.records, build)
    assert report.ok, report.detail


def test_an_interface_refusal_replays_by_the_same_route(make_entity, make_combat):
    """A coded refusal is re-raised on replay, never handed to the executor.

    The recorded call (`choose(...)`) is not a tool the executor knows, so replaying it
    through the executor would log `unknown_action` where the original logged
    `unknown_target` — the same history under a different code.
    """
    from src.arena.agent import RejectedResponse

    combat, build = _combat_with_a_stubborn_agent()
    transcript = Transcript()
    run_match(
        combat,
        {"a": _RefusedThenEnd("A", "a"), "b": ScriptedAgent("B", "b")},
        seed=5,
        transcript=transcript,
    )

    refused = [
        r
        for r in transcript.records_of("action")
        if r["result"].get("stage") == "interface"
    ]
    assert refused and refused[0]["result"]["code"] == "unknown_target"
    assert verify(transcript.records, build).ok

    replayer = ReplayAgent("A", "a", refused)
    with pytest.raises(RejectedResponse) as again:
        replayer.decide({})
    assert again.value.code == "unknown_target"
    assert again.value.call.name == "choose"


# -- the verifier must be able to fail ---------------------------------------


def test_a_tampered_action_is_caught():
    """Swap one recorded target and the replay must diverge and say where."""
    transcript, build = _record_scenario()
    records = [dict(r) for r in transcript.records]

    attacks = [
        r for r in records if r["kind"] == "action" and r["call"]["name"] == TOOL_ATTACK
    ]
    assert len(attacks) >= 2
    victim, other = attacks[0], attacks[-1]
    tampered = dict(victim["call"])
    tampered["arguments"] = dict(tampered["arguments"])
    tampered["arguments"]["defender_id"] = other["call"]["arguments"]["defender_id"]
    victim["call"] = tampered

    report = verify(records, build)

    assert not report.ok
    assert report.first_divergence is not None
    assert report.expected_hash != report.actual_hash
    assert "diverged" in report.detail


def test_a_tampered_state_hash_is_caught():
    transcript, build = _record_scenario()
    records = [dict(r) for r in transcript.records]
    turn_ends = [r for r in records if r["kind"] == "turn_end"]
    turn_ends[1]["state_hash"] = "0" * 64

    report = verify(records, build)

    assert not report.ok
    assert report.first_divergence == 1


def test_a_different_seed_does_not_verify():
    """Sanity: the seed really governs the battle the hashes describe."""
    transcript, build = _record_scenario(seed=7)
    records = [dict(r) for r in transcript.records]
    start = next(r for r in records if r["kind"] == "match_start")
    start["seed"] = 999

    assert not verify(records, build).ok


def test_a_truncated_transcript_is_caught():
    transcript, build = _record_scenario()
    records = [
        r for r in transcript.records if not (r["kind"] == "turn_end" and r["i"] > 40)
    ]

    report = verify(records, build)
    assert not report.ok
    assert "turn count differs" in report.detail


# -- unverifiable inputs report, rather than crash ---------------------------


def test_a_transcript_without_a_match_start_reports():
    report = verify([{"i": 0, "kind": "turn_end", "state_hash": "x"}], lambda: None)
    assert not report.ok
    assert "match_start" in report.detail


def test_a_transcript_without_hashes_says_so():
    """A pre-hashing transcript is unverifiable — which is a finding, not a pass."""
    transcript, build = _record_scenario()
    records = [
        {k: v for k, v in r.items() if k != "state_hash"} for r in transcript.records
    ]

    report = verify(records, build)
    assert not report.ok
    assert "state hashes" in report.detail


def test_report_is_falsy_when_it_failed():
    assert not bool(ReplayReport(ok=False, turns_checked=0))


def test_replay_agent_refuses_to_improvise_when_it_runs_out():
    agent = ReplayAgent("r", "a", [])
    with pytest.raises(RuntimeError, match="more decisions than the transcript"):
        agent.decide({})


# -- bundle-level verification (the §5 definition-of-done check) --------------


def _builder_for(records):
    start = next(r for r in records if r["kind"] == "match_start")
    return SCENARIOS[start["scenario"]].build


def _bundle():
    bundle = {}
    for name in sorted(SCENARIOS):
        sc = SCENARIOS[name]
        transcript = Transcript()
        run_match(
            sc.build(),
            {
                sc.llm_team: ScriptedAgent("A", sc.llm_team),
                sc.heuristic_team: ScriptedAgent("B", sc.heuristic_team),
            },
            seed=3,
            transcript=transcript,
            manifest=Manifest(scenario=name),
        )
        bundle[name] = transcript.records
    return bundle


def test_a_clean_bundle_verifies_at_one_hundred_percent():
    report = verify_bundle(_bundle(), _builder_for)

    assert report.total == len(SCENARIOS)
    assert report.rate == 1.0
    assert not report.failures
    assert bool(report) is True


def test_one_bad_transcript_fails_the_bundle_and_is_named():
    bundle = _bundle()
    target = sorted(bundle)[0]
    bundle[target] = [dict(r) for r in bundle[target]]
    turn_ends = [r for r in bundle[target] if r["kind"] == "turn_end"]
    turn_ends[0]["state_hash"] = "0" * 64

    report = verify_bundle(bundle, _builder_for)

    assert not report
    assert report.verified == len(SCENARIOS) - 1
    assert len(report.failures) == 1
    assert report.failures[0].startswith(target)


def test_an_empty_bundle_is_not_a_pass():
    """Zero verified out of zero must not read as success."""
    report = verify_bundle({}, _builder_for)
    assert not report
    assert report.rate == 0.0


# -- fixtures ----------------------------------------------------------------


def _combat_with_a_stubborn_agent():
    """A tiny duel plus a builder that reproduces it exactly."""
    from src.arena.setup import build_combat
    from src.models import AbilityScores, Damage, DamageType, Entity, StatBlock

    def _make():
        def block(name, hp):
            sb = StatBlock(
                name=name,
                ability_scores=AbilityScores(15, 14, 13, 12, 11, 10),
                hit_points_max=hp,
                armor_class=13,
                proficiency_bonus=2,
            )
            sb.add_action(melee_attack())
            return sb

        knight = Entity(block("Knight", 30), team="a")
        knight.x, knight.y, knight.z = 0.0, 0.0, 0.0
        bandit = Entity(block("Bandit", 30), team="b")
        bandit.x, bandit.y, bandit.z = 5.0, 0.0, 0.0
        assert Damage and DamageType  # imported for the attack factory's types
        return build_combat([knight, bandit])

    return _make(), _make


class _IllegalThenLegal(Agent):
    """One impossible attack, then play properly — exercises a recovered rejection."""

    def __init__(self, name, team):
        super().__init__(name, team)
        self._tried = False

    def decide(self, observation):
        if not self._tried:
            self._tried = True
            return ToolCall(
                TOOL_ATTACK, {"action_name": "Longsword", "defender_id": "ghost"}
            )
        enemies = observation["enemies"]
        if enemies and observation["legal_actions"].get("attacks"):
            return ToolCall(
                TOOL_ATTACK,
                {
                    "action_name": "Longsword",
                    "defender_id": enemies[0]["entity_id"],
                },
            )
        return ToolCall(TOOL_END_TURN, {})


class _AlwaysIllegal(Agent):
    """Never does anything legal — the failure budget must force the turn to end."""

    def decide(self, observation):
        return ToolCall(
            TOOL_ATTACK, {"action_name": "Longsword", "defender_id": "ghost"}
        )


class _NoToolCallThenEnd(Agent):
    """Produces no call once, then ends — the flaky-model shape."""

    def __init__(self, name, team):
        super().__init__(name, team)
        self._failed = False

    def decide(self, observation):
        from src.arena.agent import NoToolCallError

        if not self._failed:
            self._failed = True
            raise NoToolCallError("the model said nothing useful")
        return ToolCall(TOOL_END_TURN, {})


class _RefusedThenEnd(Agent):
    """Has one answer refused by the interface with a code, then ends."""

    def __init__(self, name, team):
        super().__init__(name, team)
        self._refused = False

    def decide(self, observation):
        from src.arena.agent import RejectedResponse

        if not self._refused:
            self._refused = True
            raise RejectedResponse(
                "unknown_target",
                "No listed action 'attack:dagger:ghost'.",
                ToolCall("choose", {"action_id": "attack:dagger:ghost"}),
            )
        return ToolCall(TOOL_END_TURN, {})
