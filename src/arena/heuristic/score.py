"""The utility function — a weighted sum of features, and the weight genome.

``score`` is a pure function of ``(plan, combat, entity, policy, weights)``: it rolls no
dice and mutates nothing, so a seeded match replays exactly and the future regret metric
(AGENT_ARENA_METRICS family I) can replay each decision through it. The weights are the
genome a self-play GA (Phase D) will later tune; the default is hand-set to something
already competent.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.arena.information_policy import InformationPolicy
from src.models.entity import Entity

from . import features
from .plan import TurnPlan

if TYPE_CHECKING:
    from src.combat.combat_system import CombatSystem


@dataclass(frozen=True)
class HeuristicWeights:
    """The genome: how much each factor counts. All features are ~O(1) and dimensionless.

    Attributes:
        damage: weight on threat-weighted progress toward removing a target.
        kill: weight on securing an expected-lethal blow (removing a whole actor now).
        exposure: weight on expected incoming damage at the plan's end position.
        engagement: weight on ending in position to strike a high-threat enemy (the
            range-aware gradient that makes melee units close and ranged units hold range).
        aggression: divides the exposure fear — higher is braver (holds ground/advances).
        end_turn_threshold: minimum score improvement over standing pat to bother acting.
    """

    damage: float = 1.0
    kill: float = 1.2
    exposure: float = 0.8
    engagement: float = 0.9
    aggression: float = 1.0
    end_turn_threshold: float = 0.01


DEFAULT_WEIGHTS = HeuristicWeights()


def score(
    plan: TurnPlan,
    combat: "CombatSystem",
    entity: Entity,
    *,
    policy: InformationPolicy,
    weights: HeuristicWeights,
) -> float:
    """The utility of *plan* for *entity* — higher is better. Pure and deterministic."""
    total = 0.0

    if plan.action is not None:
        progress, kill = features.offense(entity, plan.action, combat, policy=policy)
        total += weights.damage * progress + weights.kill * kill

    end_pos = plan.end_position(entity)
    exposure = features.exposure_fraction(entity, end_pos, combat, policy=policy)
    fragility = features.fragility(entity)
    total -= weights.exposure * exposure * fragility / max(0.1, weights.aggression)

    total += weights.engagement * features.engagement(
        entity, end_pos, combat, policy=policy
    )
    return total
