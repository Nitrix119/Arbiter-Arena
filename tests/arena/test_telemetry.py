"""Per-decision cost, latency and raw output reach the transcript intact.

The study divides tokens and dollars by *accepted* action (V1_PLAN §3.4), so these
tests care most about the cases where naive accounting goes wrong: a decision that took
two requests, a decision that failed, and a provider that reports no usage at all.
"""

import json
from types import SimpleNamespace

import pytest

from src.arena.agent import ProviderError, RejectedResponse, ScriptedAgent
from src.arena.llm_common import PROVIDER_ATTEMPTS
from src.arena.openrouter_agent import OpenRouterAgent
from src.arena.telemetry import (
    REDACTED,
    DecisionTelemetry,
    RequestRecord,
    scrub,
)
from src.arena.tools import TOOLS
from src.arena.transcript import Transcript
from src.arena.turn_driver import run_turn

from .conftest import force_turn, melee_attack
from .test_openrouter_agent import FakeClient, fn_call


def _response(*tool_calls, content=None, usage=(120, 30), model="vendor/served-x"):
    """An OpenAI-style completion with a usage block."""
    message = SimpleNamespace(tool_calls=list(tool_calls) or None, content=content)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason="tool_calls")],
        usage=SimpleNamespace(
            prompt_tokens=usage[0] if usage else None,
            completion_tokens=usage[1] if usage else None,
        ),
        model=model,
    )


def _obs():
    return {"round": 1, "self": {"name": "Hero"}, "enemies": [], "legal_actions": {}}


# -- the summing layer -------------------------------------------------------


def test_sums_span_every_request_of_a_decision():
    telemetry = DecisionTelemetry(
        requests=[
            RequestRecord(latency_ms=10.0, input_tokens=100, output_tokens=20),
            RequestRecord(latency_ms=5.0, input_tokens=150, output_tokens=8),
        ]
    )
    assert telemetry.request_count == 2
    assert telemetry.input_tokens == 250
    assert telemetry.output_tokens == 28
    assert telemetry.latency_ms == 15.0


def test_unreported_usage_is_none_not_zero():
    """ "Not reported" and "free" are different facts and must not be conflated."""
    telemetry = DecisionTelemetry(requests=[RequestRecord(latency_ms=1.0)])
    assert telemetry.input_tokens is None
    assert telemetry.output_tokens is None


def test_partial_usage_sums_what_was_reported():
    telemetry = DecisionTelemetry(
        requests=[
            RequestRecord(latency_ms=1.0, input_tokens=10),
            RequestRecord(latency_ms=1.0),
        ]
    )
    assert telemetry.input_tokens == 10


def test_served_model_is_the_last_one_the_provider_named():
    telemetry = DecisionTelemetry(
        requests=[
            RequestRecord(latency_ms=1.0, served_model="vendor/a"),
            RequestRecord(latency_ms=1.0, served_model="vendor/b"),
        ]
    )
    assert telemetry.served_model == "vendor/b"


# -- adapter capture ---------------------------------------------------------


def test_adapter_records_tokens_latency_and_raw_output():
    client = FakeClient(
        [_response(fn_call("end_turn", "{}"), content="Nothing worth doing.")]
    )
    agent = OpenRouterAgent("O", "a", client=client)

    agent.decide(_obs())
    telemetry = agent.last_telemetry()

    assert telemetry.input_tokens == 120
    assert telemetry.output_tokens == 30
    assert telemetry.latency_ms > 0
    assert telemetry.requests[0].raw_output == "Nothing worth doing."
    assert telemetry.requests[0].finish_reason == "tool_calls"
    assert telemetry.requests[0].tool_call == {"name": "end_turn", "arguments": "{}"}


def test_the_served_model_is_recorded_not_the_requested_one():
    """A router may substitute a model silently; §3.1 wants what actually answered."""
    client = FakeClient([_response(fn_call("end_turn", "{}"), model="vendor/actual")])
    agent = OpenRouterAgent("O", "a", model="vendor/requested", client=client)

    agent.decide(_obs())

    assert agent.model == "vendor/requested"
    assert agent.last_telemetry().served_model == "vendor/actual"


def test_a_retried_decision_records_both_requests():
    """The case a single-record implementation would silently under-report."""
    client = FakeClient(
        [
            _response(content="Let me think about this...", usage=(100, 40)),
            _response(fn_call("end_turn", "{}"), usage=(160, 12)),
        ]
    )
    agent = OpenRouterAgent("O", "a", client=client)

    agent.decide(_obs())
    telemetry = agent.last_telemetry()

    assert telemetry.request_count == 2
    assert telemetry.input_tokens == 260
    assert telemetry.output_tokens == 52
    # The prose that caused the retry is kept — it is the failure story, not noise.
    assert telemetry.requests[0].raw_output == "Let me think about this..."


def test_a_provider_failure_still_records_its_request():
    broken = SimpleNamespace(choices=None, error={"message": "rate limited"})
    agent = OpenRouterAgent("O", "a", client=FakeClient([broken] * PROVIDER_ATTEMPTS))

    with pytest.raises(ProviderError):
        agent.decide(_obs())

    telemetry = agent.last_telemetry()
    # The model never answered, so it made no request; the provider's failed
    # attempts are all kept, each with its latency.
    assert telemetry.request_count == 0
    assert len(telemetry.provider_failures) == PROVIDER_ATTEMPTS
    assert "rate limited" in telemetry.provider_failures[0].error
    assert telemetry.provider_failures[0].latency_ms > 0


def test_a_response_without_usage_degrades_rather_than_raising():
    """A provider that omits `usage` must not take a match down (the A1 lesson)."""
    bare = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    tool_calls=[fn_call("end_turn", "{}")], content=None
                ),
                finish_reason=None,
            )
        ]
    )
    agent = OpenRouterAgent("O", "a", client=FakeClient([bare]))

    agent.decide(_obs())
    telemetry = agent.last_telemetry()

    assert telemetry.input_tokens is None
    assert telemetry.served_model is None
    assert telemetry.latency_ms > 0


def test_temperature_is_sent_and_defaults_to_zero():
    client = FakeClient([_response(fn_call("end_turn", "{}"))])
    OpenRouterAgent("O", "a", client=client).decide(_obs())
    assert client.calls[0]["temperature"] == 0.0


# -- reaching the transcript -------------------------------------------------


def _turn_with(client, make_entity, make_combat):
    fighter = make_entity("Fighter", team="a", pos=(0, 0, 0), attacks=[melee_attack()])
    goblin = make_entity("Goblin", team="b", pos=(5, 0, 0), hp=30)
    combat = make_combat([fighter, goblin])
    combat.start_combat()
    force_turn(combat, fighter)

    transcript = Transcript()
    run_turn(
        combat, fighter, OpenRouterAgent("O", "a", client=client), transcript=transcript
    )
    return transcript


def test_telemetry_reaches_every_action_record(make_entity, make_combat):
    client = FakeClient(
        [
            _response(
                fn_call(
                    "attack", '{"action_name": "Longsword", "defender_id": "goblin"}'
                )
            ),
            _response(fn_call("end_turn", "{}")),
        ]
    )
    transcript = _turn_with(client, make_entity, make_combat)

    actions = transcript.records_of("action")
    assert len(actions) == 2
    for record in actions:
        assert record["telemetry"]["input_tokens"] == 120
        assert record["telemetry"]["served_model"] == "vendor/served-x"
        assert record["telemetry"]["request_count"] == 1


def test_a_deterministic_agent_logs_no_telemetry_key(make_entity, make_combat):
    fighter = make_entity("Fighter", team="a", pos=(0, 0, 0), attacks=[melee_attack()])
    goblin = make_entity("Goblin", team="b", pos=(5, 0, 0), hp=30)
    combat = make_combat([fighter, goblin])
    combat.start_combat()
    force_turn(combat, fighter)

    transcript = Transcript()
    run_turn(combat, fighter, ScriptedAgent("S", "a"), transcript=transcript)

    assert transcript.records_of("action")
    for record in transcript.records_of("action"):
        assert "telemetry" not in record  # absent, not null


def test_a_failed_decision_is_recorded_with_its_cost(make_entity, make_combat):
    """The turn driver reads telemetry on the exception path too."""
    client = FakeClient(
        [SimpleNamespace(choices=None)] * PROVIDER_ATTEMPTS
        + [_response(fn_call("end_turn", "{}"))]
    )
    transcript = _turn_with(client, make_entity, make_combat)

    failed = [r for r in transcript.records_of("action") if not r["result"]["ok"]]
    assert len(failed) == 1
    assert failed[0]["telemetry"]["request_count"] == 0
    assert len(failed[0]["telemetry"]["provider_failures"]) == PROVIDER_ATTEMPTS
    assert failed[0]["result"]["code"] == "provider_error"


# -- secrets -----------------------------------------------------------------


@pytest.mark.parametrize(
    "secret",
    [
        "sk-or-v1-0123456789abcdef0123",
        "sk-ant-api03-abcdefghijklmnop",
        "sk-abcdefghijklmnopqrstuvwx",
    ],
)
def test_scrub_redacts_key_shapes(secret):
    assert secret not in scrub(f"my key is {secret} ok")
    assert REDACTED in scrub(f"my key is {secret} ok")


def test_scrub_leaves_ordinary_prose_alone():
    text = "I attack the goblin with my longsword."
    assert scrub(text) == text


def test_scrub_survives_fields_being_filled_in_after_construction():
    """Regression: the scrub used to live in ``__post_init__`` and protected nothing.

    Adapters build a RequestRecord with the timing and usage they have, then assign
    ``raw_output`` as they parse the rest of the response — so a constructor-time
    scrub ran before the field it guarded existed. Scrubbing belongs at the
    serialisation boundary, which nothing can bypass by mutating later.
    """
    secret = "sk-or-v1-0123456789abcdef0123"
    record = RequestRecord(latency_ms=1.0)
    record.raw_output = f"key {secret}"
    record.error = f"failed with {secret}"

    data = record.to_dict()
    assert secret not in data["raw_output"]
    assert secret not in data["error"]


def test_how_a_response_was_read_is_scrubbed_too():
    """C1 copies the model's text into `interpretation`, so it passes the same guard."""
    secret = "sk-or-v1-0123456789abcdef0123"
    record = RequestRecord(latency_ms=1.0)
    record.interpretation = {"code": "malformed_output", "line": f"say {secret}"}

    data = record.to_dict()
    assert secret not in str(data["interpretation"])
    assert data["interpretation"]["code"] == "malformed_output"


def test_an_echoed_key_never_reaches_the_saved_transcript(
    make_entity, make_combat, tmp_path
):
    """Defence in depth: only responses are logged, but a model could echo one back."""
    secret = "sk-or-v1-deadbeefdeadbeefdeadbeef"
    client = FakeClient(
        [_response(fn_call("end_turn", "{}"), content=f"Using key {secret} now.")]
    )
    transcript = _turn_with(client, make_entity, make_combat)
    path = transcript.save_auto(str(tmp_path), "secrets")

    written = path.read_text(encoding="utf-8")
    assert secret not in written
    assert REDACTED in written
    assert json.loads(written.splitlines()[0])  # still valid JSONL


def test_a_key_in_a_call_or_its_result_never_reaches_the_saved_transcript(
    make_entity, make_combat, tmp_path
):
    """Ledger A9: the arguments and the referee's echo of them are model text too.

    A key-shaped string used as a target id is logged three ways: in the call's
    arguments, in the provider's raw tool call, and in the engine's refusal message
    ("Unknown entity_id: '...'"). None may reach disk.
    """
    secret = "sk-or-v1-feedfacefeedfacefeedface"
    client = FakeClient(
        [
            _response(
                fn_call(
                    "attack",
                    json.dumps({"action_name": "Longsword", "defender_id": secret}),
                )
            ),
            _response(fn_call("end_turn", json.dumps({"note": f"remember {secret}"}))),
        ]
    )
    transcript = _turn_with(client, make_entity, make_combat)
    path = transcript.save_auto(str(tmp_path), "secrets")

    written = path.read_text(encoding="utf-8")
    assert secret not in written
    assert written.count(REDACTED) >= 3


def test_the_raw_tool_call_is_scrubbed():
    secret = "sk-or-v1-0123456789abcdef0123"
    record = RequestRecord(latency_ms=1.0)
    record.tool_call = {"name": "end_turn", "arguments": f'{{"note": "{secret}"}}'}
    assert secret not in json.dumps(record.to_dict())


def test_extra_tool_calls_are_counted_not_silently_dropped():
    """Ledger A5: extra calls are evidence. Two *different* calls are also refused
    (prereg §6), and the refused request is still counted."""
    client = FakeClient(
        [_response(fn_call("end_turn", "{}"), fn_call("attack", "{}", call_id="t2"))]
    )
    agent = OpenRouterAgent("O", "a", client=client)
    with pytest.raises(RejectedResponse):
        agent.decide(_obs())
    assert agent.telemetry.requests[0].extra_tool_calls == 1
    assert agent.telemetry.requests[0].distinct_tool_calls == 2
