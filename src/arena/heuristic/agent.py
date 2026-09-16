"""The utility-scoring heuristic policy — the arena's strong, tunable yardstick.

:class:`HeuristicAgent` scores whole-turn plans and commits the first step of the best
one, re-planning each call (HEURISTIC_DECISION_MODEL §2). Being in-process, it is bound to
the live :class:`~src.combat.combat_system.CombatSystem` and reads entity state directly
(read-only), applying its :class:`~src.arena.information_policy.InformationPolicy` when it
consults enemy facts so a hidden-information match still degrades correctly. It replaces
``ScriptedAgent`` as the competent rung of the ladder; Scripted/Random stay as the
weak/floor rungs.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

from src.arena.agent import Agent
from src.arena.information_policy import FULL_INFORMATION, InformationPolicy
from src.arena.tools import TOOL_END_TURN, ToolCall
from src.models.entity import Entity

from .plan import TurnPlan, enumerate_plans
from .score import DEFAULT_WEIGHTS, HeuristicWeights, score

if TYPE_CHECKING:  # avoids importing the combat stack at module load
    from src.combat.combat_system import CombatSystem


class HeuristicAgent(Agent):
    """Plays any stat block pragmatically by scoring plans — no per-creature special-casing."""

    def __init__(
        self,
        name: str,
        team: Optional[str],
        combat: "CombatSystem",
        *,
        policy: InformationPolicy = FULL_INFORMATION,
        weights: HeuristicWeights = DEFAULT_WEIGHTS,
    ) -> None:
        super().__init__(name, team)
        self._combat = combat
        self._policy = policy
        self._weights = weights

    def decide(self, observation: Dict[str, Any], tools: List[Dict[str, Any]]) -> ToolCall:
        entity = self._active_entity(observation)
        if entity is None:
            return ToolCall(TOOL_END_TURN, {})

        stay = TurnPlan(None, None, None)  # ending the turn where we stand
        candidates = enumerate_plans(self._combat, entity, policy=self._policy)
        # Deterministic order so ties resolve identically on replay; `max` then returns the
        # first plan achieving the best score.
        ordered = sorted(candidates + [stay], key=_plan_sort_key)
        scored = {_plan_sort_key(p): self._score(entity, p) for p in ordered}

        best = max(ordered, key=lambda p: scored[_plan_sort_key(p)])
        if best.is_end_turn:
            return ToolCall(TOOL_END_TURN, {})
        if scored[_plan_sort_key(best)] - scored[_plan_sort_key(stay)] <= self._weights.end_turn_threshold:
            return ToolCall(TOOL_END_TURN, {})
        return best.first_step()

    def _score(self, entity: Entity, plan: TurnPlan) -> float:
        return score(
            plan, self._combat, entity, policy=self._policy, weights=self._weights
        )

    def _active_entity(self, observation: Dict[str, Any]) -> Optional[Entity]:
        self_id = observation.get("self", {}).get("entity_id")
        for e in self._combat.combatants:
            if e.entity_id == self_id:
                return e
        return None


def _plan_sort_key(plan: TurnPlan) -> Tuple[int, str, str, str, str, str]:
    """A stable, total ordering over plans for deterministic tie-breaking."""
    act = plan.action
    return (
        0 if act is not None else 1,  # prefer acting on ties
        act.kind if act else "",
        act.name if act else "",
        act.target_id if act else "",
        plan.pre_move.option_id if plan.pre_move else "",
        plan.post_move.option_id if plan.post_move else "",
    )
