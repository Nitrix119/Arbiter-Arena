"""The mock model speaks every condition's format, through the real decision path.

The batch runner's offline mode and the CI smoke both rest on this: a match played by
the mock must go through the same interpret → executor → driver path a real model's
would, and its deliberate stumbles must land in the taxonomy codes each condition is
expected to produce.
"""

import pytest

from src.arena.agent import ScriptedAgent
from src.arena.interfaces import C1, C2, C2_MENU, C3, get_interface
from src.arena.match import run_match
from src.arena.mock_model import MOCK_MODEL, MockModelAgent
from src.arena.replay import verify
from src.arena.scenarios import SCENARIOS
from src.arena.transcript import Transcript

#: The code each condition's typical malformed answer must be recorded under.
STUMBLE_CODE = {
    C1: "malformed_output",
    C2: "malformed_output",
    C2_MENU: "malformed_output",
    C3: "unknown_target",
}


def _play(condition, scenario="aoe_placement", stumble_on=(0,)):
    build = SCENARIOS[scenario].build
    transcript = Transcript()
    model = MockModelAgent("mock", "a", get_interface(condition), stumble_on=stumble_on)
    run_match(
        build(),
        {"a": model, "b": ScriptedAgent("Opponent", "b")},
        seed=4,
        transcript=transcript,
    )
    decisions = [r for r in transcript.records_of("action") if "telemetry" in r]
    return build, transcript, decisions


@pytest.mark.parametrize("condition", [C1, C2, C2_MENU, C3])
def test_a_mock_match_plays_and_replays_in_every_condition(condition):
    build, transcript, decisions = _play(condition)

    assert len(decisions) > 5
    assert verify(transcript.records, build).ok


@pytest.mark.parametrize("condition", [C1, C2, C2_MENU, C3])
def test_the_stumble_lands_in_the_expected_code(condition):
    _, _, decisions = _play(condition)

    stumble, *rest = decisions
    assert stumble["result"]["ok"] is False
    assert stumble["result"]["code"] == STUMBLE_CODE[condition]
    # Everything the script chose is accepted, first time, in one request.
    for record in rest:
        assert record["result"]["ok"], record
        assert record["telemetry"]["request_count"] == 1


def test_mock_telemetry_is_marked_and_nonzero():
    _, _, decisions = _play(C3, stumble_on=())
    telemetry = decisions[0]["telemetry"]

    assert telemetry["served_model"] == MOCK_MODEL
    assert telemetry["input_tokens"] > 0
    assert telemetry["menu_length"] > 0


def test_an_unknown_condition_is_refused_loudly():
    class _Nameless(type(get_interface(C2))):
        name = "C9"

    with pytest.raises(ValueError, match="C9"):
        MockModelAgent("mock", "a", _Nameless())


# -- the hostile mock (review 2026-09-24) ---------------------------------------


@pytest.mark.parametrize("condition", [C1, C2, C2_MENU, C3])
def test_a_hostile_mock_is_coded_never_a_crash_and_still_replays(condition):
    """Real models write things a well-behaved mock never does.

    Unparseable tool arguments, ``null`` where a value belongs, numbers as words, a
    move by menu id, a choice with no id. Every one of them must come back as a coded
    refusal, never an exception that stops the study grid, never ``engine_error`` —
    and a match full of them must still replay exactly.
    """
    build = SCENARIOS["aoe_placement"].build
    transcript = Transcript()
    model = MockModelAgent(
        "mock",
        "a",
        get_interface(condition),
        stumble_on=range(0, 40, 2),
        stumble_style="hostile",
    )
    run_match(
        build(),
        {"a": model, "b": ScriptedAgent("Opponent", "b")},
        seed=4,
        transcript=transcript,
    )

    decisions = [r for r in transcript.records_of("action") if "telemetry" in r]
    refused = [r for r in decisions if not r["result"]["ok"]]
    assert len(refused) >= 3  # every hostile shape was actually sent
    assert {r["result"]["code"] for r in refused} == {"malformed_output"}
    assert all(r["telemetry"]["request_count"] == 1 for r in refused)
    assert verify(transcript.records, build).ok


def test_an_unknown_stumble_style_is_refused_naming_the_options():
    with pytest.raises(ValueError, match="hostile"):
        MockModelAgent("mock", "a", get_interface(C2), stumble_style="rude")
