"""Tests for the provider-neutral LLM helpers shared by every adapter."""

import pytest

from src.arena.llm_common import (
    augment_tools_with_notes,
    capture_notes,
    decide_one_action,
    render_observation,
)
from src.arena.telemetry import RequestRecord
from src.arena.tools import TOOLS, ToolCall


class _StubAgent:
    def __init__(self):
        self.name = "Stub"
        self.notes = ""
        self.telemetry = None

    def remember(self, text):
        self.notes = text


def test_augment_adds_note_only_to_end_turn():
    aug = {t["name"]: t for t in augment_tools_with_notes(TOOLS)}
    assert "note" in aug["end_turn"]["input_schema"]["properties"]
    assert "note" not in aug["attack"]["input_schema"].get("properties", {})
    # original TOOLS untouched (deep-copied)
    orig = {t["name"]: t for t in TOOLS}
    assert "note" not in orig["end_turn"]["input_schema"].get("properties", {})


def test_render_includes_notes_and_state():
    out = render_observation("kite the archer", {"round": 2})
    assert "kite the archer" in out
    assert '"round": 2' in out


def test_render_surfaces_rejected_actions_as_header_not_json():
    obs = {
        "round": 2,
        "rejected_actions": [
            {
                "action": {"name": "move", "arguments": {"x": 5, "z": 0}},
                "error": "destination overlaps Bandit",
            },
        ],
    }
    out = render_observation("", obs)
    assert "REJECTED" in out
    assert "destination overlaps Bandit" in out  # the reason is shown
    assert (
        '"rejected_actions"' not in out
    )  # pulled out of the JSON dump (not duplicated)


def test_capture_notes_strips_and_stores():
    agent = _StubAgent()
    call = capture_notes(agent, ToolCall("end_turn", {"note": "focus the mage"}))
    assert "note" not in call.arguments
    assert agent.notes == "focus the mage"


def test_decide_one_action_returns_first_tool_call():
    agent = _StubAgent()
    seq = [(ToolCall("attack", {"defender_id": "g1"}), RequestRecord(latency_ms=1.0))]
    call = decide_one_action(lambda m, t: seq.pop(0), agent, {}, TOOLS)
    assert call.name == "attack"


def test_decide_one_action_retries_then_raises():
    agent = _StubAgent()
    calls = {"n": 0}

    def always_none(messages, tools):
        calls["n"] += 1
        return None, RequestRecord(latency_ms=1.0, input_tokens=10, output_tokens=5)

    with pytest.raises(RuntimeError, match="no tool call"):
        decide_one_action(always_none, agent, {}, TOOLS)
    assert calls["n"] == 2  # initial + one retry


def test_a_failed_decision_still_reports_what_it_spent():
    """Both requests of a failed decision are accounted for.

    Cost per *accepted* action is the metric, so the tokens burned on decisions that
    never produced one must not vanish — those are exactly the decisions that
    distinguish the interface conditions.
    """
    agent = _StubAgent()

    def always_none(messages, tools):
        return None, RequestRecord(latency_ms=2.0, input_tokens=10, output_tokens=5)

    with pytest.raises(RuntimeError):
        decide_one_action(always_none, agent, {}, TOOLS)

    assert agent.telemetry.request_count == 2
    assert agent.telemetry.input_tokens == 20
    assert agent.telemetry.output_tokens == 10
    assert agent.telemetry.latency_ms == 4.0
