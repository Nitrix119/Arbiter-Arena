"""Drive one entity's turn: observe → decide → act → observe, until the turn ends.

The driver calls the agent for **one** action at a time (B2), executes it through the
:class:`~src.arena.tools.ToolExecutor`, feeds the result back into the next observation,
and repeats. It stops when the agent ends its turn, or a guard trips:

* **failure budget (C2):** 3 consecutive or 5 total illegal/failed calls in a turn →
  auto-end the turn (illegal-move rate is a metric);
* **action cap:** a safety valve against an agent that acts forever without ending;
* **dead/again:** a downed actor's turn is skipped;
* **fight over:** an action that leaves one side standing ends the turn at once — the
  engine has already ended combat, and nobody is asked for a decision against no one.

**Invariant:** every ``run_turn`` either advances the combat exactly once — the agent's
own ``end_turn`` (executed by the ``ToolExecutor``) or a single forced ``end_turn`` — or
returns with the combat already over.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from src.arena.agent import Agent, NoToolCallError, ProviderError, RejectedResponse
from src.arena.error_codes import NO_TOOL_CALL, PROVIDER_ERROR
from src.arena.information_policy import FULL_INFORMATION, InformationPolicy
from src.arena.observation import build_observation, snapshot_state
from src.arena.tools import ToolCall, ToolExecutor
from src.arena.transcript import Transcript
from src.combat.enums import CombatState
from src.models.entity import Entity

if TYPE_CHECKING:
    from src.combat.combat_system import CombatSystem

MAX_CONSECUTIVE_FAILURES = 3
MAX_TOTAL_FAILURES = 5
MAX_ACTIONS_PER_TURN = 20
#: ``result["stage"]`` of a refusal made by the study condition, not the executor.
INTERFACE_STAGE = "interface"

#: Why a turn ended, recorded on its ``turn_end`` so metrics read it rather than
#: reconstructing it from the action stream.
END_AGENT = "agent"  # the agent ended its own turn
END_BUDGET = "budget"  # the failure budget forced the end
END_CAP = "cap"  # the per-turn action cap forced the end
END_SKIP = "skip"  # a downed actor took no turn
END_OVER = "over"  # the actor's action decided the fight; combat has ended


@dataclass
class TurnOutcome:
    """Summary of one entity's turn (useful for tests and metrics)."""

    entity_id: str
    actions_taken: int
    failures: int
    #: True when the driver ended the turn (budget/cap/skip) — not the agent, and not
    #: the fight ending (END_OVER).
    forced_end: bool


def run_turn(
    combat: "CombatSystem",
    actor: Entity,
    agent: Agent,
    *,
    executor: Optional[ToolExecutor] = None,
    policy: InformationPolicy = FULL_INFORMATION,
    transcript: Optional[Transcript] = None,
    max_actions: int = MAX_ACTIONS_PER_TURN,
) -> TurnOutcome:
    """Run *actor*'s whole turn under *agent*'s control; return a
    :class:`TurnOutcome`."""
    executor = executor or ToolExecutor(combat)

    if not actor.is_alive():  # a downed creature takes no turn
        combat.end_turn(actor.entity_id)
        return _finish(transcript, combat, actor, 0, 0, cause=END_SKIP)

    if transcript is not None:
        transcript.turn_start(actor.entity_id, combat.round, combat.turn)

    consecutive = 0
    failures = 0
    actions = 0
    # Rejected actions since the last successful one — fed back so the agent learns
    # *why* a move was refused and can self-correct within the turn (cleared on any
    # success).
    rejections: List[Dict[str, Any]] = []

    while True:
        observation = build_observation(combat, actor, policy)
        if rejections:
            observation["rejected_actions"] = list(rejections)
        try:
            call = agent.decide(observation)
        except NoToolCallError as exc:
            # A flaky/weak model produced no tool call — treat it like an illegal action
            # (counted against the budget, fed back), not a match-ending crash. A
            # ProviderError is the same shape but a different *cause*: infrastructure,
            # which the study may exclude a match for, rather than model behaviour,
            # which it never may.
            call = ToolCall("(no_tool_call)", {})
            code = PROVIDER_ERROR if isinstance(exc, ProviderError) else NO_TOOL_CALL
            result = {"ok": False, "code": code, "error": str(exc)}
            if isinstance(exc, RejectedResponse):
                # The model *did* answer; its condition refused the answer with a code.
                # Log the attempt and the real code, and mark the stage so a replay
                # re-raises it rather than handing the call to the executor.
                call = exc.call or call
                result = {
                    "ok": False,
                    "code": exc.code,
                    "error": str(exc),
                    "stage": INTERFACE_STAGE,
                }
        else:
            result = executor.apply(actor, call, policy)
        if transcript is not None:
            # Read after both branches: a decision that raised still spent tokens, and
            # a cost metric that ignored failed decisions would flatter the conditions
            # that fail most.
            transcript.action(
                actor.entity_id, call, result, telemetry=agent.last_telemetry()
            )

        if not result["ok"]:
            rejections.append(
                {
                    "action": {"name": call.name, "arguments": dict(call.arguments)},
                    "code": result.get("code", ""),
                    "error": result.get("error", ""),
                }
            )
            consecutive += 1
            failures += 1
            if (
                consecutive >= MAX_CONSECUTIVE_FAILURES
                or failures >= MAX_TOTAL_FAILURES
            ):
                combat.end_turn(actor.entity_id)
                return _finish(
                    transcript, combat, actor, actions, failures, cause=END_BUDGET
                )
            continue

        rejections.clear()
        consecutive = 0
        if result.get("ended_turn"):  # the agent ended its own turn (already advanced)
            return _finish(
                transcript, combat, actor, actions, failures, cause=END_AGENT
            )

        actions += 1
        if combat.state != CombatState.ACTIVE:
            # This action decided the fight and the engine ended combat on the spot
            # (ledger A24): no further decision, and no end_turn to advance.
            return _finish(transcript, combat, actor, actions, failures, cause=END_OVER)
        if actions >= max_actions:
            combat.end_turn(actor.entity_id)
            return _finish(transcript, combat, actor, actions, failures, cause=END_CAP)


def _finish(
    transcript: Optional[Transcript],
    combat: "CombatSystem",
    actor: Entity,
    actions: int,
    failures: int,
    *,
    cause: str,
) -> TurnOutcome:
    if transcript is not None:
        transcript.turn_end(actor.entity_id, snapshot_state(combat), end_cause=cause)
    return TurnOutcome(
        actor.entity_id, actions, failures, cause not in (END_AGENT, END_OVER)
    )
