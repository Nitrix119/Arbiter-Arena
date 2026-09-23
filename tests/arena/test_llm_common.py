"""Tests for the provider-neutral LLM helpers shared by every adapter."""

import pytest

from src.arena.agent import RejectedResponse
from src.arena.interfaces import C1, C2_MENU, C3, get_interface
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
    call = decide_one_action(lambda m, t: seq.pop(0), agent, {}, get_interface(C2_MENU))
    assert call.name == "attack"


def test_decide_one_action_retries_then_raises():
    agent = _StubAgent()
    calls = {"n": 0}

    def always_none(messages, tools):
        calls["n"] += 1
        return None, RequestRecord(latency_ms=1.0, input_tokens=10, output_tokens=5)

    with pytest.raises(RuntimeError, match="no usable action"):
        decide_one_action(always_none, agent, {}, get_interface(C2_MENU))
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
        decide_one_action(always_none, agent, {}, get_interface(C2_MENU))

    assert agent.telemetry.request_count == 2
    assert agent.telemetry.input_tokens == 20
    assert agent.telemetry.output_tokens == 10
    assert agent.telemetry.latency_ms == 4.0


def test_a_coded_refusal_is_not_retried():
    """An answer the interface refuses with a code is a rejected action, not silence.

    C2's executor rejections are counted with no free second try, so a condition-level
    refusal must not get one either — otherwise C3 (and later C1) would be spared a
    failure that C2 is charged for.
    """
    agent = _StubAgent()
    requests = {"n": 0}

    def invented_id(messages, tools):
        requests["n"] += 1
        return (
            ToolCall("choose", {"action_id": "attack:dagger:nobody"}),
            RequestRecord(latency_ms=1.0, input_tokens=10, output_tokens=5),
        )

    observation = {"enumerated_actions": []}
    with pytest.raises(RejectedResponse):
        decide_one_action(invented_id, agent, observation, get_interface(C3))

    assert requests["n"] == 1
    assert agent.telemetry.request_count == 1  # still accounted for


def test_rejected_actions_are_described_by_the_given_formatter():
    """Each condition shows a rejected action in its own format.

    The default is the tool-call rendering the raw-parameter conditions always saw;
    a text condition must not have C2's JSON format leaked into its prompt.
    """
    obs = {
        "round": 2,
        "rejected_actions": [
            {
                "action": {"name": "move", "arguments": {"x": 5, "z": 0}},
                "error": "destination overlaps Bandit",
            },
        ],
    }
    default = render_observation("", obs)
    assert '- move {"x": 5, "z": 0} -> destination overlaps Bandit' in default

    custom = render_observation("", obs, format_rejected=lambda a: "MOVE TO 5,0")
    assert "- MOVE TO 5,0 -> destination overlaps Bandit" in custom
    assert '{"x": 5' not in custom


def test_the_loop_describes_rejections_through_the_interface():
    """`decide_one_action` hands the condition's formatter to the renderer."""
    from src.arena.interfaces import SchemaInterface

    class _Loud(SchemaInterface):
        def format_rejected(self, action):
            return f"<<{action['name']}>>"

    agent = _StubAgent()
    seen = []

    def capture(messages, tools):
        seen.append(messages[0]["content"])
        return ToolCall("end_turn", {}), RequestRecord()

    obs = {"rejected_actions": [{"action": {"name": "move"}, "error": "blocked"}]}
    decide_one_action(capture, agent, obs, _Loud())
    assert "- <<move>> -> blocked" in seen[0]


def _texts(*replies):
    """A text-only provider: each request returns the next reply and no tool call."""
    queue = list(replies)

    def request(messages, tools):
        assert tools == []  # C1 offers the model nothing to call
        return None, RequestRecord(raw_output=queue.pop(0))

    return request


def test_c1_reads_its_action_from_text_after_one_correction():
    agent = _StubAgent()
    request = _texts("Hmm, the raiders are close.", "ACTION: end turn")

    call = decide_one_action(request, agent, {}, get_interface(C1))

    assert call.name == "end_turn"
    assert agent.telemetry.request_count == 2
    assert agent.telemetry.requests[1].interpretation["layer"] == 0


def test_c1_end_turn_note_reaches_the_scratchpad():
    agent = _StubAgent()
    request = _texts("ACTION: end turn \u2014 note: fireball when they bunch")

    call = decide_one_action(request, agent, {}, get_interface(C1))

    assert call.arguments == {}
    assert agent.notes == "fireball when they bunch"


def test_c1_unreadable_attempt_is_refused_not_retried():
    agent = _StubAgent()
    with pytest.raises(RejectedResponse) as refused:
        decide_one_action(_texts("ACTION: attack"), agent, {}, get_interface(C1))
    assert refused.value.code == "malformed_output"
    assert agent.telemetry.request_count == 1
