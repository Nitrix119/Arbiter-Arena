"""Feature extractors — the factors the scorer weighs, each read from live state.

These read ``Entity``/``StatBlock`` objects and the combat directly (the heuristic is
in-process), applying the :class:`InformationPolicy` where enemy knowledge would be
hidden — so the same code plays fairly under a hidden-information experiment. Every
feature returns a dimensionless magnitude (a fraction, or a threat-normalised ratio) so
one weight vector generalises across rosters of very different HP totals
(HEURISTIC_DECISION_MODEL §5.3).

The offensive core (:func:`offense`) is one principled quantity — threat-weighted
effective-HP removed — from which overkill, target-priority and kill-securing fall out
together, rather than four features that fight each other.
"""

from __future__ import annotations

import math
from typing import List, Optional, Tuple, TYPE_CHECKING

from src.arena.information_policy import InformationPolicy
from src.models.action import AttackAction
from src.models.entity import Entity

from . import estimate

if TYPE_CHECKING:  # avoid importing the combat stack at module load
    from src.combat.combat_system import CombatSystem
    from .plan import PlannedAction

# A "typical" single-attack expected damage per turn, used to normalise threat into a
# dimensionless ratio (a typical enemy scores ~1). Keeps offense/kill features O(1).
TYPICAL_DPR = 7.0

# The expected incoming damage assumed for an enemy whose capabilities are hidden — a
# generic melee threat, so exposure to an unknown foe is still penalised (§9 fallback).
GENERIC_INCOMING = 5.0

# Reach of an enemy whose weapons are hidden: a default 5 ft melee.
DEFAULT_REACH_FT = 5.0


def _owned_attacks(entity: Entity) -> List[AttackAction]:
    actions = list(entity.stat_block.actions) + list(entity.granted_actions)
    return [a for a in actions if isinstance(a, AttackAction)]


def best_attack(entity: Entity) -> Optional[AttackAction]:
    """The entity's highest-expected-damage weapon attack (vs a typical AC), or None."""
    attacks = _owned_attacks(entity)
    if not attacks:
        return None
    return max(attacks, key=lambda a: estimate.attack_ev_vs_ac(a, estimate.TYPICAL_AC))


def _speed_ft(entity: Entity) -> float:
    return float(entity.stat_block.resource_defaults.get("speed", 30))


def _max_reach_ft(entity: Entity) -> float:
    attacks = _owned_attacks(entity)
    return max((a.range_ft for a in attacks), default=DEFAULT_REACH_FT)


def threat(enemy: Entity, *, known: bool = True) -> float:
    """Expected damage-per-turn of *enemy* — how dangerous it is to leave alive.

    ``known`` reflects whether the agent may see the enemy's capabilities
    (``policy.reveal_enemy_actions``); when hidden, a generic-threat default stands in.
    """
    if not known:
        return GENERIC_INCOMING
    attack = best_attack(enemy)
    if attack is None:
        return 0.0
    return estimate.attack_ev_vs_ac(attack, estimate.TYPICAL_AC)


def _threat_ratio(enemy: Entity, *, known: bool) -> float:
    return threat(enemy, known=known) / TYPICAL_DPR


def _current_hp(entity: Entity) -> int:
    """Current HP, treating an uninitialised ``None`` as full (as the engine does)."""
    return entity.current_hp if entity.current_hp is not None else entity.max_hp


def effective_hp(entity: Entity) -> float:
    """HP that must be removed to drop *entity* (current + temporary), floored at 1."""
    return max(1.0, float(_current_hp(entity) + entity.temporary_hp))


def offense(
    attacker: Entity,
    action: "PlannedAction",
    combat: "CombatSystem",
    *,
    policy: InformationPolicy,
) -> Tuple[float, float]:
    """The offensive value of *action*, as ``(progress, kill)`` — both threat-normalised.

    * ``progress`` — threat-weighted fraction of the target's effective HP removed
      (``threat_ratio · min(damage, hp) / hp``). Capping at ``hp`` means overkill adds
      nothing, and multiplying by the target's threat makes the same damage worth more
      against a dangerous foe — so overkill-avoidance and target-priority are folded in.
    * ``kill`` — the threat removed *this turn* when the blow is expected to be lethal
      (``damage >= hp``); a discontinuous bonus for deleting a whole action economy now
      rather than next round.

    Returned separately so the genome can weight securing-a-kill against chip damage.
    """
    target = _lookup(combat, action.target_id)
    if target is None or not target.is_alive():
        return 0.0, 0.0

    known = policy.reveal_enemy_actions
    dmg = action.expected_damage(attacker, target, combat, policy=policy)
    hp = effective_hp(target)
    ratio = _threat_ratio(target, known=known)

    progress = ratio * (min(dmg, hp) / hp)
    kill = ratio if dmg >= hp else 0.0
    return progress, kill


def exposure_fraction(
    entity: Entity,
    pos: Tuple[float, float, float],
    combat: "CombatSystem",
    *,
    policy: InformationPolicy,
) -> float:
    """Expected incoming damage next turn if *entity* ends at *pos*, as a fraction of HP.

    A 1-ply lookahead: for each enemy that could close-and-reach *pos* on its next turn
    (``distance <= enemy.speed + enemy.reach``), add its best attack's expected damage
    against *entity* (its own AC and resistances, which it always knows). Enemies whose
    capabilities are hidden contribute a generic estimate. Normalised by *entity*'s max
    HP so the penalty is comparable across rosters.
    """
    known = policy.reveal_enemy_actions
    self_half = entity.stat_block.size.size_ft / 2.0
    total = 0.0
    for enemy in combat.get_enemies(entity):
        if not enemy.is_alive():
            continue
        reach = _speed_ft(enemy) + _max_reach_ft(enemy)
        gap = _center_distance(pos, enemy) - self_half - enemy.stat_block.size.size_ft / 2.0
        if max(0.0, gap) > reach:
            continue
        attack = best_attack(enemy) if known else None
        if attack is not None:
            total += estimate.expected_attack_damage(attack, entity)
        else:
            total += GENERIC_INCOMING
    return total / max(1.0, float(entity.max_hp))


def engagement(
    entity: Entity,
    pos: Tuple[float, float, float],
    combat: "CombatSystem",
    *,
    policy: InformationPolicy,
) -> float:
    """How well *pos* sets up offence against the best target — a range-aware gradient.

    For the highest-threat enemy, the value is ``threat_ratio · approach``, where
    ``approach`` is ``1`` once the enemy is within *entity*'s own attack reach and decays
    (over a scale of *entity*'s speed) as it sits further out. A ranged unit is therefore
    "engaged" from afar and feels no pull inward, while a melee unit is rewarded for
    closing the gap turn by turn — the gradient a myopic scorer needs to make units
    advance toward the enemy they most want to remove rather than dithering out of reach.
    """
    reach = _max_reach_ft(entity)
    speed = _speed_ft(entity)
    self_half = entity.stat_block.size.size_ft / 2.0
    known = policy.reveal_enemy_actions
    best = 0.0
    for enemy in combat.get_enemies(entity):
        if not enemy.is_alive():
            continue
        gap = max(
            0.0,
            _center_distance(pos, enemy) - self_half - enemy.stat_block.size.size_ft / 2.0,
        )
        over = max(0.0, gap - reach)
        approach = 1.0 / (1.0 + over / max(1.0, speed))
        best = max(best, _threat_ratio(enemy, known=known) * approach)
    return best


def fragility(entity: Entity) -> float:
    """How much *entity* should fear incoming damage: 1 at full HP, rising as it drops."""
    return 1.0 + (1.0 - _current_hp(entity) / max(1, entity.max_hp))


def _center_distance(pos: Tuple[float, float, float], entity: Entity) -> float:
    dx = pos[0] - entity.x
    dy = pos[1] - entity.y
    dz = pos[2] - entity.z
    return math.sqrt(dx * dx + dy * dy + dz * dz)


def _lookup(combat: "CombatSystem", entity_id: str) -> Optional[Entity]:
    for e in combat.combatants:
        if e.entity_id == entity_id:
            return e
    return None
