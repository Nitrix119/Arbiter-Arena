"""Action economy resources for D&D combat turns.

Movement is a **float** measured in feet, not an int and not grid squares: SRD 5.1
measures movement, range and reach in feet and carries no grid rules, so a 5-ft
diagonal step legitimately costs sqrt(50) = 7.07 ft. The 5-ft square is the PHB's
"Variant: Playing on a Grid" sidebar, which the SRD omits.

Because a continuous budget is *subtracted from* repeatedly, it is quantised to
FEET_DP decimal places on every spend. Without that, 30 - 7.1 - 7.1 evaluates to
15.799999999999999 in binary floating point, and the residue reaches `can_afford`
comparisons, the web UI, and the movement budget shown to LLM agents.
"""

from dataclasses import dataclass

# Decimal places the foot-denominated budget is held to. One tenth of a foot is
# far finer than any rule distinguishes, while keeping the value exact and legible.
FEET_DP = 1


@dataclass(frozen=True)
class ActionCost:
    """Immutable resource cost for performing an action.

    All fields default to 0 — only specify the resources consumed.
    """

    actions: int = 0
    bonus_actions: int = 0
    reactions: int = 0
    movement: float = 0.0  # feet; continuous, see the module docstring


# Common cost constants
ACTION_COST = ActionCost(actions=1)
BONUS_ACTION_COST = ActionCost(bonus_actions=1)
REACTION_COST = ActionCost(reactions=1)
NO_COST = ActionCost()


@dataclass
class ActionResources:
    """Mutable per-turn action economy budget for an entity."""

    actions: int = 1
    bonus_actions: int = 1
    reactions: int = 1
    movement: float = 30.0  # feet; continuous, see the module docstring

    def can_afford(self, cost: ActionCost) -> bool:
        """Check whether the entity has enough resources to pay *cost*."""
        return (
            self.actions >= cost.actions
            and self.bonus_actions >= cost.bonus_actions
            and self.reactions >= cost.reactions
            and self.movement >= cost.movement
        )

    def spend(self, cost: ActionCost) -> None:
        """Deduct *cost* from current resources.

        Raises:
            ValueError: If any resource is insufficient.
        """
        if not self.can_afford(cost):
            raise ValueError(f"Insufficient resources: have {self}, need {cost}")
        self.actions -= cost.actions
        self.bonus_actions -= cost.bonus_actions
        self.reactions -= cost.reactions
        # Re-quantised, not just subtracted: repeated subtraction of a fractional
        # foot cost otherwise drifts (30 - 7.1 - 7.1 -> 15.799999999999999).
        self.movement = round(self.movement - cost.movement, FEET_DP)
