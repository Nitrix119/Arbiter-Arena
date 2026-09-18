"""Bounded turn-plan enumeration — the candidates the scorer ranks.

A :class:`TurnPlan` is the unit we score (HEURISTIC_DECISION_MODEL §1): *(maybe)
reposition → act → (maybe) reposition*, evaluated by the board state it leaves and
executed one step at a time (the agent emits :meth:`TurnPlan.first_step` and re-plans
next call). The candidate set stays small: destinations come from the already-legal
:func:`~src.arena.action_space.move_candidates`, and a move is paired with the action
it *enables by construction* (``toward_melee`` → a melee attack on that enemy;
``kite_range`` → a ranged attack), so no hypothetical re-ranging is needed in Phase B.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Tuple, TYPE_CHECKING

from src.arena.action_space import LegalActions, MoveOption, legal_actions
from src.arena.information_policy import InformationPolicy
from src.arena.tools import (
    TOOL_ATTACK,
    TOOL_CAST_SPELL,
    TOOL_END_TURN,
    TOOL_MOVE,
    ToolCall,
)
from src.models.action import AttackAction, SpellAction
from src.models.entity import Entity
from src.models.spell_properties import TargetingType
from src.spatial.geometry import Point3D
from src.spatial.range_check import derive_aoe_origin

from . import estimate

if TYPE_CHECKING:
    from src.combat.combat_system import CombatSystem

# An attack reaching beyond this is "ranged" — its owner can act from a distance and so
# genuinely benefits from opening range.
MELEE_RANGE_FT = 5.0

# A healthy pure-melee unit does not flee: retreating from an equal-speed enemy only
# forfeits its own offence (it must re-close next turn) while the enemy follows.
# Disengage plans (retreat / kite tail) are therefore offered only to a unit that can
# act from range, or one hurt below this HP fraction, where self-preservation outweighs
# its damage.
RETREAT_HP_FRACTION = 0.35


@dataclass(frozen=True)
class PlannedAction:
    """The main action of a plan.

    ``kind`` is ``"attack"`` or ``"spell"`` (single target, via ``target_id``) or
    ``"aoe"`` (an area spell aimed at ``target_point``, catching ``aoe_targets`` — the
    entity ids the volume covers, precomputed by the placement search so scoring and
    resolution agree on who is hit).
    """

    kind: str
    name: str
    target_id: str = ""
    target_point: Optional[Tuple[float, float, float]] = None
    aoe_targets: Tuple[str, ...] = ()

    def to_tool_call(self) -> ToolCall:
        if self.kind == "attack":
            return ToolCall(
                TOOL_ATTACK, {"action_name": self.name, "defender_id": self.target_id}
            )
        if self.kind == "aoe" and self.target_point is not None:
            px, py, pz = self.target_point
            return ToolCall(
                TOOL_CAST_SPELL,
                {"spell_name": self.name, "target_point": {"x": px, "y": py, "z": pz}},
            )
        return ToolCall(
            TOOL_CAST_SPELL, {"spell_name": self.name, "target_ids": [self.target_id]}
        )

    def expected_damage(
        self,
        attacker: Entity,
        target: Entity,
        combat: "CombatSystem",
        *,
        policy: InformationPolicy,
    ) -> float:
        """Expected damage this action deals to *target*.

        Resistances are applied only when the agent may know the enemy (proxied by
        ``reveal_enemy_actions`` — the one policy flag that gates enemy capabilities),
        so hidden-information play does not lean on a defensive profile it should not
        see.
        """
        apply_resistance = policy.reveal_enemy_actions
        if self.kind == "attack":
            attack = _find_attack(attacker, self.name)
            if attack is None:
                return 0.0
            return estimate.expected_attack_damage(
                attack, target, apply_resistance=apply_resistance
            )
        spell = combat.get_spell_for_entity(attacker, self.name)
        return estimate.spell_expected_damage(
            spell, attacker, target, apply_resistance=apply_resistance
        )


@dataclass(frozen=True)
class TurnPlan:
    """A bounded turn-plan: an optional reposition, an optional action, an optional
    tail."""

    pre_move: Optional[MoveOption]
    action: Optional[PlannedAction]
    post_move: Optional[MoveOption]

    def end_position(self, entity: Entity) -> Tuple[float, float, float]:
        """Where the entity ends the turn (for scoring exposure/positioning there)."""
        move = self.post_move or self.pre_move
        if move is not None:
            return (move.x, move.y, move.z)
        return (entity.x, entity.y, entity.z)

    def first_step(self) -> ToolCall:
        """The single tool call this plan commits now; the rest is re-planned next
        call."""
        if self.pre_move is not None:
            return ToolCall(TOOL_MOVE, {"option_id": self.pre_move.option_id})
        if self.action is not None:
            return self.action.to_tool_call()
        if self.post_move is not None:
            return ToolCall(TOOL_MOVE, {"option_id": self.post_move.option_id})
        return ToolCall(TOOL_END_TURN, {})

    @property
    def is_end_turn(self) -> bool:
        return self.pre_move is None and self.action is None and self.post_move is None


def enumerate_plans(
    combat: "CombatSystem", entity: Entity, *, policy: InformationPolicy
) -> List[TurnPlan]:
    """The bounded set of turn-plans for *entity* right now (excludes the empty/end
    plan).

    Reuses :func:`legal_actions` / ``move_candidates`` as the legal-by-construction
    substrate. Produces: stay-and-act plans (with an optional kite/retreat tail), a
    move-that-enables-an-action plan per destination, and pure reposition plans.
    """
    la = legal_actions(combat, entity)
    moves = list(la.moves)
    may_disengage = _may_disengage(combat, entity)
    plans: List[TurnPlan] = []

    for act in _legal_main_actions(la):
        plans.append(TurnPlan(None, act, None))
        if may_disengage:
            tail = _tail_for(moves, act.target_id)
            if tail is not None:
                plans.append(TurnPlan(None, act, tail))

    for act in _aoe_plans(combat, entity, la):
        plans.append(TurnPlan(None, act, None))

    for move in moves:
        enabled = _attack_after_move(combat, entity, move)
        if enabled is not None:
            plans.append(TurnPlan(move, enabled, None))

    for move in moves:
        if _is_disengage(move) and not may_disengage:
            # a healthy pure-melee unit holds its ground rather than backpedalling
            continue
        plans.append(TurnPlan(move, None, None))

    return plans


def _is_disengage(move: MoveOption) -> bool:
    """A move that opens distance from an enemy (retreat or kite), not an advance."""
    return move.option_id.startswith(("retreat:", "kite_range:"))


def _may_disengage(combat: "CombatSystem", entity: Entity) -> bool:
    """Whether *entity* should even consider opening range.

    A ranged unit always may (it can attack from the distance it opens). A pure-melee
    unit may only when it is both hurt (below RETREAT_HP_FRACTION) *and* fast enough to
    actually outrun its pursuers — fleeing an equal-speed enemy just forfeits a turn of
    damage while the enemy follows, so in a straight brawl a melee unit holds its ground
    and fights.
    """
    if any(a.range_ft > MELEE_RANGE_FT for a in _owned_attacks(entity)):
        return True
    current_hp = entity.current_hp if entity.current_hp is not None else entity.max_hp
    if current_hp / max(1, entity.max_hp) >= RETREAT_HP_FRACTION:
        return False
    my_speed = entity.stat_block.resource_defaults.get("speed", 30)
    fastest_threat = max(
        (
            e.stat_block.resource_defaults.get("speed", 30)
            for e in combat.get_enemies(entity)
        ),
        default=0,
    )
    return my_speed > fastest_threat


def _legal_main_actions(la: LegalActions) -> List[PlannedAction]:
    """Offensive main actions from the legal menu: attacks and single-target damage
    spells."""
    out: List[PlannedAction] = []
    for atk in la.attacks:
        for target in atk.targets:  # attacks list enemies only
            out.append(PlannedAction("attack", atk.name, target.entity_id))
    for spell in la.spells:
        if spell.targeting != TargetingType.SINGLE_TARGET.value:
            continue  # AoE/multi-target handled in Phase C
        for target in spell.targets:
            if target.relation == "enemy":
                out.append(PlannedAction("spell", spell.name, target.entity_id))
    return out


def _aoe_plans(
    combat: "CombatSystem", entity: Entity, la: LegalActions
) -> List[PlannedAction]:
    """A best-placement AoE plan per castable area spell — the placement search (§3.1).

    For each candidate aim point (each alive enemy's position) it asks the engine's own
    ``derive_aoe_origin`` + ``get_targets_in_aoe`` who the volume would catch (so
    scoring and resolution agree), and keeps the point catching the most enemies for the
    fewest allies. Final utility (enemy damage vs friendly fire) is scored in
    ``features``.
    """
    out: List[PlannedAction] = []
    for spell_opt in la.spells:
        if spell_opt.targeting != TargetingType.AOE.value:
            continue
        spell = combat.get_spell_for_entity(entity, spell_opt.name)
        if not isinstance(spell, SpellAction) or spell.aoe is None:
            continue
        best_point: Optional[Tuple[float, float, float]] = None
        best_ids: Tuple[str, ...] = ()
        best_net = 0
        for enemy in combat.get_enemies(entity):
            if not enemy.is_alive():
                continue
            aim = (enemy.x, enemy.y, enemy.z)
            origin, direction = derive_aoe_origin(entity, spell, Point3D(*aim))
            hit = combat.get_targets_in_aoe(origin, spell.aoe, direction)
            foes = [e for e in hit if e.team != entity.team]
            if not foes:
                continue
            allies = [e for e in hit if e.team == entity.team]
            net = len(foes) - len(
                allies
            )  # a proxy to pick the point; features scores value
            if best_point is None or net > best_net:
                best_point = aim
                best_ids = tuple(e.entity_id for e in hit)
                best_net = net
        if best_point is not None:
            out.append(
                PlannedAction(
                    "aoe", spell_opt.name, target_point=best_point, aoe_targets=best_ids
                )
            )
    return out


def _tail_for(moves: List[MoveOption], target_id: str) -> Optional[MoveOption]:
    """The retreat tail for a plan attacking *target_id* — kite (stays in range) or
    retreat."""
    kite = _find_move(moves, f"kite_range:{target_id}")
    if kite is not None:
        return kite
    return _find_move(moves, f"retreat:{target_id}")


def _attack_after_move(
    combat: "CombatSystem", entity: Entity, move: MoveOption
) -> Optional[PlannedAction]:
    """The best attack *entity* could make against the move's enemy *from the
    destination*.

    Range is re-checked at the move's end point (not assumed from the option's name), so
    a move that only closes part of the way — ``toward_melee`` when the enemy is beyond
    reach even after moving — correctly enables no attack and is scored as a pure
    advance.
    """
    _, _, enemy_id = move.option_id.partition(":")
    if not enemy_id:
        return None
    enemy = _lookup(combat, enemy_id)
    if enemy is None or not enemy.is_alive():
        return None
    gap = _gap_at((move.x, move.y, move.z), entity, enemy)
    best: Optional[AttackAction] = None
    best_ev = 0.0
    for attack in _owned_attacks(entity):
        if not entity.can_afford(attack.cost) or gap > attack.range_ft:
            continue
        ev = estimate.expected_attack_damage(attack, enemy)
        if best is None or ev > best_ev:
            best, best_ev = attack, ev
    if best is None:
        return None
    return PlannedAction("attack", best.name, enemy_id)


def _gap_at(pos: Tuple[float, float, float], entity: Entity, other: Entity) -> float:
    """Edge-to-edge gap between *entity* standing at *pos* and *other* (floored at
    0)."""
    dx = pos[0] - other.x
    dy = pos[1] - other.y
    dz = pos[2] - other.z
    dist = math.sqrt(dx * dx + dy * dy + dz * dz)
    gap = (
        dist
        - entity.stat_block.size.size_ft / 2.0
        - other.stat_block.size.size_ft / 2.0
    )
    return max(0.0, gap)


def _lookup(combat: "CombatSystem", entity_id: str) -> Optional[Entity]:
    for e in combat.combatants:
        if e.entity_id == entity_id:
            return e
    return None


def _owned_attacks(entity: Entity) -> List[AttackAction]:
    actions = list(entity.stat_block.actions) + list(entity.granted_actions)
    return [a for a in actions if isinstance(a, AttackAction)]


def _find_move(moves: List[MoveOption], option_id: str) -> Optional[MoveOption]:
    for move in moves:
        if move.option_id == option_id:
            return move
    return None


def _find_attack(entity: Entity, name: str) -> Optional[AttackAction]:
    for action in list(entity.stat_block.actions) + list(entity.granted_actions):
        if isinstance(action, AttackAction) and action.name == name:
            return action
    return None
