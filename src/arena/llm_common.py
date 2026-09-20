"""Provider-neutral pieces shared by every LLM adapter.

The notes scratchpad, the tool-note augmentation and the one-action-per-call loop are
the same whether the model is served by Anthropic, OpenRouter or anything else — only
the request differs. Keeping them here means one copy for all adapters (CLAUDE.md §2.7:
no duplicated vocabulary); an adapter supplies just a ``request_fn`` that turns messages
plus tools into one :class:`~src.arena.tools.ToolCall` (or ``None``) and a cost record.

What the model is *shown, offered and read by* varies with the study condition. That is
:mod:`src.arena.interfaces`' job — this module drives the loop and never learns which
condition it is running, which is how four conditions share one agent path.
"""

import json
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.arena.agent import NoToolCallError, ProviderError
from src.arena.interfaces import SHARED_PROMPT, ActionInterface
from src.arena.telemetry import DecisionTelemetry, RequestRecord
from src.arena.tools import TOOL_END_TURN, ToolCall

#: One request → the ToolCall it produced (or None when the model made none), paired
#: with what that request cost. The record is returned *alongside* the call rather than
#: stashed by the adapter, so a decision that takes two requests cannot lose the first
#: one's cost — the retry lives here, so the accounting does too.
RequestFn = Callable[
    [List[Dict[str, Any]], List[Dict[str, Any]]],
    Tuple[Optional[ToolCall], RequestRecord],
]

#: Back-compat alias. The prompt is now assembled per condition — the shared world
#: model lives in :data:`~src.arena.interfaces.SHARED_PROMPT` and each condition adds
#: its own action section. An adapter that still wants "the prompt" without a condition
#: gets the shared half, which is the part that is genuinely provider-neutral.
SYSTEM_PROMPT = SHARED_PROMPT


def augment_tools_with_notes(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return a copy of *tools* with an optional ``note`` field added to ``end_turn``.

    Lets the model leave a brief reminder for its next turn without spending an action
    or polluting the shared engine tool schema. Tools are in the neutral
    ``{name, description, input_schema}`` shape; each adapter reshapes the envelope for
    its own API.
    """
    augmented: List[Dict[str, Any]] = []
    for tool in tools:
        if tool["name"] == TOOL_END_TURN:
            tool = json.loads(json.dumps(tool))  # deep copy
            tool["input_schema"].setdefault("properties", {})["note"] = {
                "type": "string",
                "description": (
                    "Optional: a short reminder to your future self for next turn."
                ),
            }
        augmented.append(tool)
    return augmented


def render_observation(notes: str, observation: Dict[str, Any]) -> str:
    """Render an observation as the user message.

    Order: prior note → any rejected-action feedback (a compact header, so the model
    learns *why* its last attempt this turn failed and can choose differently — not a
    wasteful conversation thread) → the instruction and state JSON. ``rejected_actions``
    is pulled out of the dict before dumping so it isn't shown twice.
    """
    obs = dict(observation)
    rejected = obs.pop("rejected_actions", None)

    parts: List[str] = []
    if notes:
        parts.append(f"Your note to self from last turn: {notes}")
    if rejected:
        lines = [
            "Your last action(s) this turn were REJECTED by the referee — read why and "
            "choose a DIFFERENT action (do not repeat a rejected one):"
        ]
        for r in rejected:
            action = r.get("action", {})
            lines.append(
                f"- {action.get('name')} {json.dumps(action.get('arguments', {}))}"
                f" -> {r.get('error')}"
            )
        parts.append("\n".join(lines))
    # Deliberately says nothing about *how* to act or what is listed: that is the
    # action section's job, and it is the only text allowed to differ between
    # conditions (§3.1). "your legal options" used to live here, which silently made
    # the shared body condition-specific.
    parts.append(
        "It is your turn. Study the battlefield, then take exactly one action.\n\n"
        + json.dumps(obs, indent=2, default=str)
    )
    return "\n\n".join(parts)


def capture_notes(agent: Any, call: ToolCall) -> ToolCall:
    """Pull a ``note`` off an ``end_turn`` call into *agent*'s scratchpad; clean the
    call.
    """
    if call.name == TOOL_END_TURN and "note" in call.arguments:
        note = call.arguments.pop("note")
        if note:
            agent.remember(str(note))
    return call


def _record_request(
    request_fn: RequestFn,
    telemetry: DecisionTelemetry,
    messages: List[Dict[str, Any]],
    api_tools: List[Dict[str, Any]],
) -> Tuple[Optional[ToolCall], RequestRecord]:
    """Make one request, recording what it cost whether or not it succeeded.

    A :class:`~src.arena.agent.ProviderError` carries its own record, so a broken
    envelope is accounted for and then re-raised unchanged — the turn driver still
    needs the type to tag it as infrastructure rather than model behaviour.
    """
    try:
        call, record = request_fn(messages, api_tools)
    except ProviderError as exc:
        if exc.record is not None:
            telemetry.requests.append(exc.record)
        raise
    telemetry.requests.append(record)
    return call, record


def decide_one_action(
    request_fn: RequestFn,
    agent: Any,
    observation: Dict[str, Any],
    interface: ActionInterface,
) -> ToolCall:
    """The shared decide skeleton: render → request → one retry → capture notes.

    *request_fn* is the adapter's provider call; *interface* is the study condition,
    which owns the three things that vary — what the model is shown, what it is offered
    and how its answer is read. The loop itself is the same for every condition, so
    there is exactly one agent path no matter how many conditions exist (CLAUDE.md §3).

    If the interface cannot make an action out of the response we re-prompt once; if it
    still cannot, we fail loudly (never silently end the turn).

    Every request's cost is accumulated onto ``agent.telemetry`` as it happens — before
    any raise — so a decision that ended in failure still reports the tokens it spent.
    A failed decision is not a free one, and the study divides cost by *accepted*
    actions precisely to capture that.
    """
    shown = interface.shape_observation(observation)
    api_tools = augment_tools_with_notes(interface.api_tools(shown))
    messages: List[Dict[str, Any]] = [
        {"role": "user", "content": render_observation(agent.notes, shown)}
    ]
    telemetry = DecisionTelemetry()
    agent.telemetry = telemetry

    action = _attempt(
        request_fn, telemetry, messages, api_tools, interface, observation
    )
    if action is None:  # the model gave nothing usable — correct it once
        messages.append({"role": "user", "content": interface.correction()})
        action = _attempt(
            request_fn, telemetry, messages, api_tools, interface, observation
        )
    if action is None:
        raise NoToolCallError(
            f"{agent.name}: the model returned no usable action after a retry "
            f"(condition {interface.name}); cannot act."
        )
    return capture_notes(agent, action)


def _attempt(
    request_fn: RequestFn,
    telemetry: DecisionTelemetry,
    messages: List[Dict[str, Any]],
    api_tools: List[Dict[str, Any]],
    interface: ActionInterface,
    observation: Dict[str, Any],
) -> Optional[ToolCall]:
    """One request, decoded by the condition into an executable action or ``None``.

    The interface sees both the decoded call and the raw record, so a text condition
    can read ``record.raw_output`` without this loop knowing which kind it is driving.
    *observation* is the **unshaped** one: decoding resolves against ground truth, not
    against the trimmed copy the model was shown.
    """
    call, record = _record_request(request_fn, telemetry, messages, api_tools)
    return interface.interpret(call, record, observation)
