"""A whole C1 match, offline: text in, refereed actions out, replayable.

The C1 cell of V1_PLAN's offline smoke. A mocked "model" lets the scripted policy
decide, then *writes* that decision as C1 text — wrapped in prose, and once garbled on
purpose — and everything after that is the real path: ``decide_one_action`` →
``FreeTextInterface`` → the parser → the shared executor → the turn driver → the
transcript → the replay verifier. Nothing here calls a provider.
"""

from typing import Any, Dict

import pytest

from src.arena.agent import Agent, ScriptedAgent
from src.arena.free_text import UNREAD_TEXT, render_command
from src.arena.interfaces import C1, get_interface
from src.arena.llm_common import decide_one_action
from src.arena.manifest import Manifest, prompt_hash
from src.arena.match import run_match
from src.arena.replay import verify
from src.arena.scenarios import SCENARIOS
from src.arena.telemetry import RequestRecord
from src.arena.tools import TOOL_MOVE, ToolCall
from src.arena.transcript import Transcript


def _as_coordinates(call: ToolCall, observation: Dict[str, Any]) -> ToolCall:
    """The scripted policy moves by menu option; C1 can only write coordinates."""
    option_id = call.arguments.get("option_id")
    if call.name != TOOL_MOVE or not option_id:
        return call
    for move in observation["legal_actions"]["moves"]:
        if move["option_id"] == option_id:
            return ToolCall(TOOL_MOVE, {k: move[k] for k in ("x", "y", "z")})
    raise AssertionError(f"scripted policy chose an unlisted move {option_id!r}")


class _TextModel(Agent):
    """A mocked C1 model: the scripted policy decides, the decision is *written*."""

    def __init__(self, name: str, team: str, *, stumble_once: bool) -> None:
        super().__init__(name, team)
        self._policy = ScriptedAgent(name, team)
        self._stumble = stumble_once

    def decide(self, observation: Dict[str, Any]) -> ToolCall:
        if self._stumble:
            self._stumble = False
            reply = "I should strike first.\nACTION: attack"  # garbled on purpose
        else:
            call = _as_coordinates(self._policy.decide(observation), observation)
            reply = "Following the plan.\nACTION: " + render_command(call)

        def request(messages, tools):
            assert tools == []  # C1 offers no tools
            return None, RequestRecord(raw_output=reply)

        return decide_one_action(request, self, observation, get_interface(C1))


@pytest.mark.parametrize("scenario", ["aoe_placement", "kiting"])
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
            "a": _TextModel("C1 model", "a", stumble_once=True),
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
