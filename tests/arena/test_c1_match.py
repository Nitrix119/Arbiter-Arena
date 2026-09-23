"""A whole C1 match, offline: text in, refereed actions out, replayable.

The C1 cell of V1_PLAN's offline smoke. The mock model lets the scripted policy decide,
then *writes* that decision as C1 text — wrapped in prose, and once garbled on purpose —
and everything after that is the real path: ``decide_one_action`` →
``FreeTextInterface`` → the parser → the shared executor → the turn driver → the
transcript → the replay verifier. Nothing here calls a provider.
"""

import pytest

from src.arena.agent import ScriptedAgent
from src.arena.free_text import UNREAD_TEXT
from src.arena.interfaces import C1, get_interface
from src.arena.manifest import Manifest, prompt_hash
from src.arena.match import run_match
from src.arena.mock_model import MockModelAgent
from src.arena.replay import verify
from src.arena.scenarios import SCENARIOS
from src.arena.transcript import Transcript


@pytest.mark.parametrize("scenario", ["aoe_placement", "kiting", "protect_squishy"])
def test_a_c1_match_plays_records_and_replays(scenario):
    build = SCENARIOS[scenario].build
    transcript = Transcript()
    manifest = Manifest(
        scenario=scenario,
        condition=C1,
        prompt_hash=prompt_hash(get_interface(C1).system_prompt()),
    )

    run_match(
        build(),
        {
            "a": MockModelAgent("C1 model", "a", get_interface(C1), stumble_on={0}),
            "b": ScriptedAgent("Opponent", "b"),
        },
        seed=11,
        transcript=transcript,
        manifest=manifest,
    )

    start = transcript.records_of("match_start")[0]
    assert start["condition"] == C1

    model_actions = [r for r in transcript.records_of("action") if "telemetry" in r]
    assert len(model_actions) > 5

    refused = [r for r in model_actions if r["call"]["name"] == UNREAD_TEXT]
    assert len(refused) == 1  # the one deliberate stumble
    assert refused[0]["result"]["code"] == "malformed_output"
    assert refused[0]["result"]["stage"] == "interface"

    for record in model_actions:
        (request,) = record["telemetry"]["requests"]
        reading = request["interpretation"]
        if record is refused[0]:
            assert reading["code"] == "malformed_output"
        else:
            assert reading["layer"] == 3  # read out of the surrounding prose
            assert record["call"]["name"] != UNREAD_TEXT

    report = verify(transcript.records, build)
    assert report.ok, report.detail
