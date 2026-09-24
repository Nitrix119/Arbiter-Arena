"""A provider-free stand-in for an LLM, speaking any study condition's format.

Used by the batch runner as ``provider = "mock"`` and by the offline smoke test, so the
whole study grid — every condition, every scenario — can run end to end with no network
and no cost. The *decisions* come from a deterministic policy (:class:`ScriptedAgent`);
what the mock adds is **writing** each decision the way a model under that condition
must: C1 as a line of text, C2/C2+M as a raw-parameter tool call, C3 as
``choose(action_id)``. Everything after that is the real path —
:func:`~src.arena.llm_common.decide_one_action`, the condition's ``interpret``, the
executor, the turn driver — so the mock exercises the harness, not a copy of it.

It can also **stumble** on chosen decisions, writing each condition's typical malformed
answer, so refusal paths and the report's taxonomy have data to count. The ``hostile``
style stumbles the way real models and hosts do — unparseable tool arguments, ``null``
where a value belongs, numbers as words, a move by menu id, a choice with no id — so
the offline grid proves the harness survives them (review 2026-09-24).

Telemetry is synthetic (characters ÷ 4) and marked ``served_model = "mock"``: enough to
exercise the cost arithmetic, and impossible to mistake for a real measurement.
"""

import json
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple, Union

from src.arena.agent import Agent, ScriptedAgent
from src.arena.free_text import render_command
from src.arena.interfaces import C1, C2, C2_MENU, C3, ActionInterface
from src.arena.llm_common import decide_one_action, decode_arguments
from src.arena.telemetry import RequestRecord
from src.arena.tools import TOOL_ATTACK, TOOL_CAST_SPELL, TOOL_MOVE, ToolCall
from src.utils import dice

#: What the mock reports as the model that served it.
MOCK_MODEL = "mock"


@dataclass(frozen=True)
class RawCall:
    """A tool call whose arguments are still the provider's raw text.

    Decoded by :func:`~src.arena.llm_common.decode_arguments`, exactly as a real
    adapter decodes them, so the mock exercises that path rather than a copy of it.
    """

    name: str
    arguments: str


#: One written answer: the tool call the "provider" returns (if any) and its text.
Answer = Tuple[Optional[Union[ToolCall, RawCall]], Optional[str]]


def as_coordinates(call: ToolCall, observation: Dict[str, Any]) -> ToolCall:
    """The scripted policy moves by menu option; a model can only write coordinates."""
    option_id = call.arguments.get("option_id")
    if call.name != TOOL_MOVE or not option_id:
        return call
    for move in observation["legal_actions"]["moves"]:
        if move["option_id"] == option_id:
            return ToolCall(TOOL_MOVE, {k: move[k] for k in ("x", "y", "z")})
    raise ValueError(f"scripted policy chose an unlisted move {option_id!r}")


def _normalised(call: ToolCall) -> Tuple[str, str]:
    """A call as comparable text, with a point's y defaulting to the ground."""
    args = dict(call.arguments)
    if call.name == TOOL_MOVE:
        args = {k: float(args.get(k, 0.0)) for k in ("x", "y", "z")}
    if "target_point" in args:
        point = args["target_point"]
        args["target_point"] = {k: float(point.get(k, 0.0)) for k in ("x", "y", "z")}
    return call.name, json.dumps(args, sort_keys=True)


# -- writing a decision in each condition's format ----------------------------------


def _write_text(call: ToolCall, observation: Dict[str, Any]) -> Answer:
    return None, "Following the plan.\nACTION: " + render_command(call)


def _write_tool_call(call: ToolCall, observation: Dict[str, Any]) -> Answer:
    return call, None


def _write_choice(call: ToolCall, observation: Dict[str, Any]) -> Answer:
    wanted = _normalised(call)
    for action in observation.get("enumerated_actions", []):
        if _normalised(action.call) == wanted:
            return ToolCall("choose", {"action_id": action.action_id}), None
    raise ValueError(f"no enumerated action matches the policy's choice {call}")


def _stumble_text(observation: Dict[str, Any]) -> Answer:
    return None, "I should strike first.\nACTION: attack"


def _stumble_tool_call(observation: Dict[str, Any]) -> Answer:
    return ToolCall(TOOL_ATTACK, {"action_name": "Dagger"}), None  # no defender_id


def _stumble_choice(observation: Dict[str, Any]) -> Answer:
    return ToolCall("choose", {"action_id": "attack:nothing:nobody"}), None


#: What real models and hosts send that a well-behaved mock never would. Each list is
#: cycled through in order, one entry per stumble; every entry must be refused as
#: ``malformed_output`` — never crash the grid, never land in ``engine_error``.
_HOSTILE_CALLS: List[Union[ToolCall, RawCall]] = [
    RawCall(TOOL_ATTACK, "{bad json"),
    ToolCall(TOOL_MOVE, {"x": None, "z": 0}),
    ToolCall(TOOL_MOVE, {"option_id": "retreat:raider-1"}),
    ToolCall(TOOL_CAST_SPELL, {"spell_name": None}),
    ToolCall(TOOL_ATTACK, {"action_name": 7, "defender_id": ["raider-1"]}),
    ToolCall(TOOL_MOVE, {"x": "five", "z": 0}),
    RawCall(TOOL_MOVE, "[10, 0]"),
]
_HOSTILE_CHOICES: List[Union[ToolCall, RawCall]] = [
    RawCall("choose", ""),
    ToolCall("choose", {"action_id": None}),
    RawCall("choose", "[1]"),
]
_HOSTILE_TEXTS = [
    "ACTION: move to x=five z=0",
    "ACTION:",
    "ACTION: attack raider-1 or raider-2 with Greatsword",
]

#: Stumble styles: the condition's typical malformed answer, or the hostile set.
STUMBLE_STYLES = ("malformed", "hostile")


def _hostile(condition: str, count: int) -> Answer:
    """The *count*-th hostile answer for *condition*."""
    if condition == C1:
        return None, _HOSTILE_TEXTS[count % len(_HOSTILE_TEXTS)]
    shapes = _HOSTILE_CHOICES if condition == C3 else _HOSTILE_CALLS
    return shapes[count % len(shapes)], None


#: condition → (write a decision, write a stumble). A table, not a branch per name.
_WRITERS: Dict[
    str,
    Tuple[
        Callable[[ToolCall, Dict[str, Any]], Answer],
        Callable[[Dict[str, Any]], Answer],
    ],
] = {
    C1: (_write_text, _stumble_text),
    C2: (_write_tool_call, _stumble_tool_call),
    C2_MENU: (_write_tool_call, _stumble_tool_call),
    C3: (_write_choice, _stumble_choice),
}


def _synthetic_tokens(text: str) -> int:
    return max(1, len(text) // 4)


class RandomMenuPolicy(Agent):
    """The C3 random baseline: a uniform choice among the enumerated legal actions.

    Seeded through :meth:`reseed` (the match runner derives it from the match seed),
    with its stream from :mod:`src.utils.dice` like every other RNG.
    """

    def __init__(self, name: str, team: Optional[str]) -> None:
        super().__init__(name, team)
        self._rng = dice.new_rng(0)

    def reseed(self, seed: int) -> None:
        self._rng = dice.new_rng(seed)

    def decide(self, observation: Dict[str, Any]) -> ToolCall:
        options = observation.get("enumerated_actions") or []
        if not options:
            return ToolCall("end_turn", {})
        chosen = options[self._rng.randrange(len(options))].call
        return ToolCall(chosen.name, dict(chosen.arguments))


class MockModelAgent(Agent):
    """A deterministic "model" that plays by a script and writes like a model.

    Args:
        interface: The study condition to answer in.
        stumble_on: Zero-based decision indices at which to answer malformed instead.
        stumble_style: ``"malformed"`` (the condition's typical slip) or
            ``"hostile"`` (the shapes real models and hosts send; see above).
        policy: What decides; the scripted policy by default. A baseline swaps in its
            own, and is then written through the same condition path.
        record_telemetry: False for a baseline, which calls no provider and so, like
            every deterministic agent, carries no telemetry.
    """

    def __init__(
        self,
        name: str,
        team: Optional[str],
        interface: ActionInterface,
        *,
        stumble_on: Iterable[int] = (),
        stumble_style: str = "malformed",
        policy: Optional[Agent] = None,
        record_telemetry: bool = True,
    ) -> None:
        super().__init__(name, team)
        if interface.name not in _WRITERS:
            raise ValueError(
                f"No mock writer for condition {interface.name!r}; "
                f"expected one of {sorted(_WRITERS)}"
            )
        if stumble_style not in STUMBLE_STYLES:
            raise ValueError(
                f"Unknown stumble_style {stumble_style!r}; expected one of "
                f"{list(STUMBLE_STYLES)}"
            )
        self.interface = interface
        self._stumble_style = stumble_style
        self._stumbles = 0
        self.model = MOCK_MODEL
        self._policy = policy or ScriptedAgent(name, team)
        self._stumble_on = set(stumble_on)
        self._decisions = 0
        self._record_telemetry = record_telemetry

    def reseed(self, seed: int) -> None:
        self._policy.reseed(seed)  # a stochastic policy follows the match seed

    def decide(self, observation: Dict[str, Any]) -> ToolCall:
        write, stumble = _WRITERS[self.interface.name]
        index = self._decisions
        self._decisions += 1
        if index in self._stumble_on and self._stumble_style == "hostile":
            call, text = _hostile(self.interface.name, self._stumbles)
            self._stumbles += 1
        elif index in self._stumble_on:
            call, text = stumble(observation)
        else:
            chosen = as_coordinates(self._policy.decide(observation), observation)
            call, text = write(chosen, observation)

        def request(
            messages: List[Dict[str, Any]], tools: List[Dict[str, Any]]
        ) -> Tuple[Optional[ToolCall], RequestRecord]:
            prompt = "".join(str(m.get("content", "")) for m in messages)
            # Every written answer is text (C1) or a call (the tool conditions).
            answer = text if text is not None else ""
            if isinstance(call, RawCall):
                answer = answer or call.arguments
            elif call is not None:
                answer = answer or json.dumps(call.arguments)
            record = RequestRecord(
                latency_ms=0.0,
                input_tokens=_synthetic_tokens(prompt),
                output_tokens=_synthetic_tokens(answer or ""),
                served_model=MOCK_MODEL,
                finish_reason="mock",
                raw_output=text,
            )
            if call is not None:
                record.tool_call = {"name": call.name, "arguments": call.arguments}
            if isinstance(call, RawCall):
                args = decode_arguments(call.name, call.arguments, record)
                return ToolCall(call.name, args), record
            if call is not None:
                # A fresh copy each request: the loop pops `note` off what it returns.
                return ToolCall(call.name, dict(call.arguments)), record
            return None, record

        action = decide_one_action(request, self, observation, self.interface)
        if not self._record_telemetry:
            self.telemetry = None
        return action
