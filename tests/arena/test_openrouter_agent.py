"""Tests for the OpenRouter adapter — mocked OpenAI-style client, no network."""

from types import SimpleNamespace

import pytest

from src.arena import credentials
from src.arena import openrouter_agent as ora
from src.arena.agent import NoToolCallError, ProviderError, RejectedResponse
from src.arena.error_codes import MALFORMED_OUTPUT, PROVIDER_ERROR
from src.arena.interfaces import SHARED_PROMPT
from src.arena.llm_common import PROVIDER_ATTEMPTS
from src.arena.openrouter_agent import DEFAULT_MODEL, OpenRouterAgent, _to_openai_tools
from src.arena.tools import TOOLS
from src.arena.transcript import Transcript
from src.arena.turn_driver import run_turn

from .conftest import force_turn, melee_attack


def fn_call(name, arguments, call_id="tc1"):
    return SimpleNamespace(
        id=call_id, function=SimpleNamespace(name=name, arguments=arguments)
    )


def response(*tool_calls):
    message = SimpleNamespace(tool_calls=list(tool_calls) or None)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class _Completions:
    def __init__(self, outer):
        self._outer = outer

    def create(self, **kwargs):
        self._outer.calls.append(kwargs)
        return self._outer.responses.pop(0)


class FakeClient:
    """Stand-in for openai.OpenAI: returns queued chat completions, records calls."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.chat = SimpleNamespace(completions=_Completions(self))


def _obs():
    return {"round": 1, "self": {"name": "Hero"}, "enemies": [], "legal_actions": {}}


def test_tool_envelope_conversion():
    converted = {t["function"]["name"]: t for t in _to_openai_tools(TOOLS)}
    assert converted["attack"]["type"] == "function"
    # input_schema is carried through as the function's parameters.
    assert converted["attack"]["function"]["parameters"] == next(
        t["input_schema"] for t in TOOLS if t["name"] == "attack"
    )


def test_decide_parses_tool_call_and_json_arguments():
    client = FakeClient(
        [response(fn_call("attack", '{"action_name": "Bite", "defender_id": "g1"}'))]
    )
    agent = OpenRouterAgent("O", "a", client=client)

    call = agent.decide(_obs())

    assert call.name == "attack"
    assert call.arguments == {
        "action_name": "Bite",
        "defender_id": "g1",
    }  # JSON string parsed
    assert call.call_id == "tc1"


def test_request_shape_is_well_formed():
    client = FakeClient([response(fn_call("end_turn", "{}"))])
    agent = OpenRouterAgent("O", "a", client=client)
    agent.decide(_obs())
    kwargs = client.calls[0]

    assert kwargs["model"] == DEFAULT_MODEL
    system = kwargs["messages"][0]
    assert system["role"] == "system"
    assert system["content"] == agent.interface.system_prompt()
    assert SHARED_PROMPT in system["content"]
    assert kwargs["tool_choice"] == "auto"
    assert "extra_headers" in kwargs
    # end_turn tool was augmented with the note field (shared helper) and OpenAI-shaped.
    end_turn = next(t for t in kwargs["tools"] if t["function"]["name"] == "end_turn")
    assert "note" in end_turn["function"]["parameters"]["properties"]


def test_note_is_captured_and_stripped():
    client = FakeClient([response(fn_call("end_turn", '{"note": "kite next turn"}'))])
    agent = OpenRouterAgent("O", "a", client=client)

    call = agent.decide(_obs())

    assert call.name == "end_turn"
    assert "note" not in call.arguments
    assert agent.notes == "kite next turn"


def test_retries_once_when_no_tool_call():
    client = FakeClient(
        [response(), response(fn_call("end_turn", "{}"))]
    )  # first: no tool call
    agent = OpenRouterAgent("O", "a", client=client)

    call = agent.decide(_obs())

    assert call.name == "end_turn"
    assert len(client.calls) == 2


def test_raises_after_retry_with_no_tool_call():
    client = FakeClient([response(), response()])
    agent = OpenRouterAgent("O", "a", client=client)
    with pytest.raises(RuntimeError, match="no usable action"):
        agent.decide(_obs())


def test_missing_dependency_gives_clear_error(monkeypatch):
    monkeypatch.setattr(ora, "openai", None)
    with pytest.raises(ImportError, match="openai"):
        OpenRouterAgent("O", "a")  # client=None -> would construct the real SDK


def test_missing_key_gives_clear_error(monkeypatch, tmp_path):
    monkeypatch.setattr(ora, "openai", object())  # get past the dependency check
    monkeypatch.setattr(credentials, "_SECRETS_DIR", tmp_path)  # empty -> no key file
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        OpenRouterAgent("O", "a")


def test_openrouter_agent_drives_a_real_turn(make_entity, make_combat):
    fighter = make_entity("Fighter", team="a", pos=(0, 0, 0), attacks=[melee_attack()])
    goblin = make_entity("Goblin", team="b", pos=(5, 0, 0), hp=30)
    combat = make_combat([fighter, goblin])
    combat.start_combat()
    force_turn(combat, fighter)

    client = FakeClient(
        [
            response(
                fn_call(
                    "attack",
                    f'{{"action_name": "Longsword", "defender_id": "{goblin.entity_id}"}}',
                )
            ),
            response(fn_call("end_turn", "{}")),
        ]
    )
    agent = OpenRouterAgent("O", "a", client=client)

    outcome = run_turn(combat, fighter, agent)

    assert outcome.actions_taken == 1
    assert outcome.forced_end is False
    assert len(client.calls) == 2
    assert combat.get_current_entity() is not fighter


# -- provider failures (CODEBASE_REVIEW A1) ----------------------------------


def _broken(**fields):
    """A response envelope a struggling free host really returns."""
    return SimpleNamespace(**fields)


@pytest.mark.parametrize(
    "envelope",
    [
        _broken(choices=None),  # observed live, 2026-09-15
        _broken(choices=[]),
        _broken(error={"message": "rate limited", "code": 429}),  # no choices at all
        _broken(choices=[SimpleNamespace(message=None)]),
    ],
    ids=["choices-none", "choices-empty", "error-body", "message-none"],
)
def test_broken_envelope_is_a_provider_error_not_a_crash(envelope):
    """A malformed payload must not abort the match with a TypeError.

    `response.choices[0]` on any of these raised and killed a whole match; a four-day
    background grid cannot die on one flaky response. It is retried, and only an
    envelope that stays broken on every attempt surfaces as a ProviderError.
    """
    agent = OpenRouterAgent("O", "a", client=FakeClient([envelope] * PROVIDER_ATTEMPTS))

    with pytest.raises(ProviderError):
        agent.decide(_obs())


def test_provider_error_is_distinguishable_from_a_model_with_nothing_to_say():
    """The two failures look alike and must not be counted alike.

    An empty payload is infrastructure (a §3.5 exclusion); a well-formed reply with no
    tool call is the model's own behaviour, which is never an exclusion. Both are
    NoToolCallError so the turn driver handles them identically — only the type
    differs.
    """
    chatty = OpenRouterAgent("O", "a", client=FakeClient([response(), response()]))
    with pytest.raises(NoToolCallError) as chatty_exc:
        chatty.decide(_obs())
    assert not isinstance(chatty_exc.value, ProviderError)

    broken = OpenRouterAgent(
        "O", "a", client=FakeClient([_broken(choices=None)] * PROVIDER_ATTEMPTS)
    )
    with pytest.raises(ProviderError):
        broken.decide(_obs())


def test_provider_error_reports_the_error_body_and_the_model():
    agent = OpenRouterAgent(
        "O",
        "a",
        model="vendor/flaky:free",
        client=FakeClient(
            [_broken(error={"message": "upstream 502"})] * PROVIDER_ATTEMPTS
        ),
    )
    with pytest.raises(ProviderError, match="vendor/flaky:free") as exc:
        agent.decide(_obs())
    assert "upstream 502" in str(exc.value)


def test_a_flaky_response_is_retried_and_costs_the_model_nothing(
    make_entity, make_combat
):
    """One broken envelope is retried with the same request, invisibly to the model.

    The turn goes on with no failure charged, and the failed attempt is kept as cost
    in ``provider_failures`` — the end-to-end assertion behind A1 and review H-2.
    """
    fighter = make_entity("Fighter", team="a", pos=(0, 0, 0), attacks=[melee_attack()])
    goblin = make_entity("Goblin", team="b", pos=(5, 0, 0), hp=30)
    combat = make_combat([fighter, goblin])
    combat.start_combat()
    force_turn(combat, fighter)

    transcript = Transcript()
    client = FakeClient([_broken(choices=None), response(fn_call("end_turn", "{}"))])
    agent = OpenRouterAgent("O", "a", client=client)

    outcome = run_turn(combat, fighter, agent, transcript=transcript)

    assert outcome.failures == 0
    assert outcome.forced_end is False
    (action,) = transcript.records_of("action")
    assert action["result"]["ok"] is True
    assert action["telemetry"]["request_count"] == 1
    assert len(action["telemetry"]["provider_failures"]) == 1


def test_a_response_that_stays_broken_is_a_provider_error(make_entity, make_combat):
    fighter = make_entity("Fighter", team="a", pos=(0, 0, 0), attacks=[melee_attack()])
    goblin = make_entity("Goblin", team="b", pos=(5, 0, 0), hp=30)
    combat = make_combat([fighter, goblin])
    combat.start_combat()
    force_turn(combat, fighter)

    transcript = Transcript()
    client = FakeClient(
        [_broken(choices=None)] * PROVIDER_ATTEMPTS
        + [response(fn_call("end_turn", "{}"))]
    )
    outcome = run_turn(
        combat, fighter, OpenRouterAgent("O", "a", client=client), transcript=transcript
    )

    assert outcome.failures == 1
    failed = [r for r in transcript.records_of("action") if r["result"]["ok"] is False]
    assert [r["result"]["code"] for r in failed] == [PROVIDER_ERROR]


def test_a_text_condition_sends_no_tool_fields():
    """C1 offers no tools; `tool_choice` without `tools` is an API error, so both go."""
    message = SimpleNamespace(tool_calls=None, content="ACTION: end turn")
    client = FakeClient([SimpleNamespace(choices=[SimpleNamespace(message=message)])])
    agent = OpenRouterAgent("O", "a", client=client)

    call, record = agent._request_action([{"role": "user", "content": "go"}], [])

    kwargs = client.calls[0]
    assert "tools" not in kwargs
    assert "tool_choice" not in kwargs
    assert "parallel_tool_calls" not in kwargs
    assert call is None
    assert record.raw_output == "ACTION: end turn"


def test_a_pinned_host_and_seed_are_sent_and_the_served_host_recorded():
    """One model id can be served by several hosts; the study pins and records it."""
    served = response(fn_call("end_turn", "{}"))
    served.provider = "DeepInfra"
    client = FakeClient([served])
    agent = OpenRouterAgent("O", "a", client=client, hosts=["DeepInfra"], seed=7)

    agent.decide(_obs())
    kwargs = client.calls[0]

    assert kwargs["extra_body"] == {
        "provider": {"order": ["DeepInfra"], "allow_fallbacks": False}
    }
    assert kwargs["seed"] == 7
    assert agent.telemetry.requests[0].served_provider == "DeepInfra"


def test_without_hosts_routing_is_left_alone_but_still_recorded():
    served = response(fn_call("end_turn", "{}"))
    served.model_extra = {"provider": "Together"}
    client = FakeClient([served])
    agent = OpenRouterAgent("O", "a", client=client)

    agent.decide(_obs())
    assert "extra_body" not in client.calls[0] and "seed" not in client.calls[0]
    assert agent.telemetry.requests[0].served_provider == "Together"


# -- malformed tool-call arguments (review 2026-09-24, C-1) --------------------


@pytest.mark.parametrize("empty", ["", "   "], ids=["empty", "whitespace"])
def test_empty_arguments_are_an_empty_object(empty):
    """Some hosts send ``""`` for a tool with no arguments — a transport convention."""
    agent = OpenRouterAgent(
        "O", "a", client=FakeClient([response(fn_call("end_turn", empty))])
    )

    assert agent.decide(_obs()).arguments == {}


@pytest.mark.parametrize(
    "arguments",
    ["{bad json", '{"x": 1', "null", "[1, 2]", '"a string"', "42"],
    ids=["unparseable", "truncated", "null", "list", "string", "number"],
)
def test_unusable_arguments_are_malformed_output_not_a_crash(arguments):
    """Arguments that are not a JSON object are the model's formatting failure.

    They used to escape as ``JSONDecodeError``/``TypeError``, which the study runner
    treats as a harness bug and stops the whole grid on. They are a coded refusal,
    counted like any other, and the attempted text is kept.
    """
    agent = OpenRouterAgent(
        "O", "a", client=FakeClient([response(fn_call("move", arguments))])
    )

    with pytest.raises(RejectedResponse) as exc:
        agent.decide(_obs())

    assert exc.value.code == MALFORMED_OUTPUT
    assert exc.value.call.name == "move"
    assert exc.value.call.arguments == {"raw_arguments": arguments}
    # The request still cost something, and a refusal must not hide that.
    assert agent.last_telemetry().request_count == 1


def test_unusable_arguments_cost_a_failure_but_not_the_match(make_entity, make_combat):
    fighter = make_entity("Fighter", team="a", pos=(0, 0, 0), attacks=[melee_attack()])
    goblin = make_entity("Goblin", team="b", pos=(5, 0, 0), hp=30)
    combat = make_combat([fighter, goblin])
    combat.start_combat()
    force_turn(combat, fighter)

    transcript = Transcript()
    client = FakeClient(
        [response(fn_call("attack", "{bad")), response(fn_call("end_turn", "{}"))]
    )
    outcome = run_turn(
        combat, fighter, OpenRouterAgent("O", "a", client=client), transcript=transcript
    )

    assert outcome.failures == 1
    assert outcome.forced_end is False
    failed = [r for r in transcript.records_of("action") if not r["result"]["ok"]]
    assert [r["result"]["code"] for r in failed] == [MALFORMED_OUTPUT]
    assert failed[0]["telemetry"]["request_count"] == 1


def test_reasoning_and_max_tokens_are_sent_beside_the_pinned_host():
    """A thinking model's reasoning budget is a sampling setting like temperature.

    Left to host defaults it can differ between hosts and change silently, so the
    grid pins it and the adapter sends it (review 2026-09-24, M-1).
    """
    client = FakeClient([response(fn_call("end_turn", "{}"))])
    agent = OpenRouterAgent(
        "O",
        "a",
        client=client,
        hosts=["DeepInfra"],
        reasoning={"effort": "low"},
        max_tokens=2048,
    )

    agent.decide(_obs())
    kwargs = client.calls[0]

    assert kwargs["extra_body"] == {
        "provider": {"order": ["DeepInfra"], "allow_fallbacks": False},
        "reasoning": {"effort": "low"},
    }
    assert kwargs["max_tokens"] == 2048


def test_no_reasoning_setting_sends_none():
    client = FakeClient([response(fn_call("end_turn", "{}"))])
    OpenRouterAgent("O", "a", client=client).decide(_obs())
    assert "extra_body" not in client.calls[0]


# -- several calls in one response (review 2026-09-24, prereg §6) -----------------


def test_two_different_calls_are_malformed_output_not_the_first_one_run():
    """C1 refuses two different actions; C2 must not quietly run the first."""
    client = FakeClient(
        [
            response(
                fn_call("end_turn", "{}"),
                fn_call("attack", '{"action_name": "Bite", "defender_id": "g1"}', "t2"),
            )
        ]
    )
    agent = OpenRouterAgent("O", "a", client=client)

    with pytest.raises(RejectedResponse) as refused:
        agent.decide(_obs())

    assert refused.value.code == MALFORMED_OUTPUT
    assert refused.value.call.name == "end_turn"
    assert len(client.calls) == 1  # a coded refusal, not the correction re-prompt
    record = agent.telemetry.requests[0]
    assert (record.distinct_tool_calls, record.extra_tool_calls) == (2, 1)


def test_an_identical_repeated_call_is_one_action():
    client = FakeClient(
        [
            response(
                fn_call("attack", '{"action_name": "Bite", "defender_id": "g1"}'),
                fn_call("attack", '{"defender_id": "g1", "action_name": "Bite"}', "t2"),
            )
        ]
    )
    agent = OpenRouterAgent("O", "a", client=client)

    call = agent.decide(_obs())

    assert call.name == "attack"
    record = agent.telemetry.requests[0]
    assert (record.distinct_tool_calls, record.extra_tool_calls) == (1, 1)


def test_parallel_tool_calls_are_asked_off_whenever_tools_are_sent():
    client = FakeClient([response(fn_call("end_turn", "{}"))])
    OpenRouterAgent("O", "a", client=client).decide(_obs())
    assert client.calls[0]["parallel_tool_calls"] is False
