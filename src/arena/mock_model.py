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
answer, so refusal paths and the report's taxonomy have data to count.

Telemetry is synthetic (characters ÷ 4) and marked ``served_model = "mock"``: enough to
exercise the cost arithmetic, and impossible to mistake for a real measurement.
"""

import json
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from src.arena.agent import Agent, ScriptedAgent
from src.arena.free_text import render_command
from src.arena.interfaces import C1, C2, C2_MENU, C3, ActionInterface
from src.arena.llm_common import decide_one_action
from src.arena.telemetry import RequestRecord
from src.arena.tools import TOOL_ATTACK, TOOL_MOVE, ToolCall

#: What the mock reports as the model that served it.
MOCK_MODEL = "mock"

#: One written answer: the tool call the "provider" returns (if any) and its text.
Answer = Tuple[Optional[ToolCall], Optional[str]]


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


class MockModelAgent(Agent):
    """A deterministic "model" that plays by a script and writes like a model.

    Args:
        interface: The study condition to answer in.
        stumble_on: Zero-based decision indices at which to answer malformed instead.
    """

    def __init__(
        self,
        name: str,
        team: Optional[str],
        interface: ActionInterface,
        *,
        stumble_on: Iterable[int] = (),
    ) -> None:
        super().__init__(name, team)
        if interface.name not in _WRITERS:
            raise ValueError(
                f"No mock writer for condition {interface.name!r}; "
                f"expected one of {sorted(_WRITERS)}"
            )
        self.interface = interface
        self.model = MOCK_MODEL
        self._policy = ScriptedAgent(name, team)
        self._stumble_on = set(stumble_on)
        self._decisions = 0

    def decide(self, observation: Dict[str, Any]) -> ToolCall:
        write, stumble = _WRITERS[self.interface.name]
        index = self._decisions
        self._decisions += 1
        if index in self._stumble_on:
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
            if call is not None:
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
                # A fresh copy each request: the loop pops `note` off what it returns.
                return ToolCall(call.name, dict(call.arguments)), record
            return None, record

        return decide_one_action(request, self, observation, self.interface)
