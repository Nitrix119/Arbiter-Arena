"""Assemble the set of actions an entity may legally take right now.

Nothing in the engine assembles this today:
:meth:`CombatSystem.get_affordable_actions` reads only ``stat_block.actions`` (missing
``granted_actions``) and does not range-check, check spell slots, or expand
``known_spells`` into castable spells. This module fills that gap by combining the
existing pieces —

* attacks/abilities from ``stat_block.actions`` + ``granted_actions``, filtered by
  :meth:`Entity.can_afford`;
* spells from ``stat_block.known_spells``, resolved through the combat's spell
  registry and filtered by action-economy cost *and* remaining spell slots;
* targets from :meth:`CombatSystem.get_alive_entities`, each range-checked via
  :mod:`src.spatial.range_check`;
* the remaining movement budget.

The result is a **hint**, embedded in an agent's observation so it can see its
options; the engine's ``resolve_*`` methods remain the authority that actually
enforces legality.
"""

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

from src.models.action import Action, AttackAction, SpellAction
from src.models.action_resources import ActionCost
from src.models.entity import Entity
from src.models.spell_properties import TargetingType
from src.spatial.geometry import Point3D
from src.spatial.range_check import (
    check_attack_range,
    check_single_target_range,
    derive_aoe_origin,
    effective_range_ft,
)

if TYPE_CHECKING:  # avoid importing the whole combat stack at module load
    from src.combat.combat_system import CombatSystem

#: Grid resolution for the aim-point sweep offered to agents, in feet. Fine enough to
#: separate the placements that matter at 5e creature scale, coarse enough that the
#: menu stays short. How much it costs in lost options is measured, not assumed — see
#: :func:`aim_coverage`.
DEFAULT_AIM_STEP_FT = 5.0
#: Safety valve on menu length (a §3.1 cost covariate). A cap that bites removes real
#: options, so it is set well above what the study's scenarios produce and truncation
#: is reported rather than hidden.
DEFAULT_MAX_AIM_POINTS = 24
#: Largest creature half-extent to pad sweep bounds by (Gargantuan is 20 ft).
_MAX_CREATURE_HALF_FT = 10.0


@dataclass(frozen=True)
class TargetOption:
    """A single entity an action may be aimed at.

    ``relation`` is the target's affiliation to the acting entity — ``"self"``,
    ``"ally"``, or ``"enemy"`` — so an agent can tell friend from foe (a weapon
    attack lists only enemies; a spell lists every reachable target, tagged, since
    the same spell may heal an ally or harm a foe).
    """

    entity_id: str
    name: str
    relation: str

    def to_dict(self) -> dict:
        return {
            "entity_id": self.entity_id,
            "name": self.name,
            "relation": self.relation,
        }


@dataclass(frozen=True)
class AttackOption:
    """A weapon/attack action the entity can afford, and who it can reach."""

    name: str
    cost: dict
    range_ft: float
    targets: List[TargetOption]

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "cost": self.cost,
            "range_ft": self.range_ft,
            "targets": [t.to_dict() for t in self.targets],
        }


@dataclass(frozen=True)
class AimOption:
    """One place an area spell could be aimed, and who it would catch.

    Aim points are offered as **one representative per distinct set of targets hit**.
    5e area damage has no falloff, so the set of creatures caught fully determines the
    outcome — two points catching the same creatures are the same decision, and
    offering both would pad the menu without adding a choice.

    ``hits`` reuses :class:`TargetOption`, so an ally caught in the blast is visible
    and tagged. The menu states who would be hit; it never says whether that is wise.
    """

    option_id: str
    x: float
    y: float
    z: float
    hits: List[TargetOption]

    def to_dict(self) -> dict:
        return {
            "option_id": self.option_id,
            "x": self.x,
            "y": self.y,
            "z": self.z,
            "hits": [t.to_dict() for t in self.hits],
        }


@dataclass(frozen=True)
class SpellOption:
    """A spell the entity knows, can afford, and has a slot for.

    Attributes:
        targeting: The spell's targeting mode (``single_target``/``aoe``/…).
        targets: In-range entities for single-target spells; empty for AoE and
            multi-target spells, which are aimed at a point (``target_point``) or
            assigned per projectile by the caster.
        aim_points: For an AoE spell, the distinct ways it could be aimed and who each
            would catch (see :func:`aim_candidates`). Empty for every other targeting
            mode. Until this existed an area spell appeared in the menu with no targets
            and no aim guidance at all — knowable only by solving the geometry.
        range_ft: Numeric range in feet, or ``None`` when unlimited/self.
        castable_levels: Slot levels this spell may be cast at right now (its base
            level and any higher level with a remaining slot). ``[0]`` for a cantrip.
    """

    name: str
    cost: dict
    spell_level: int
    targeting: str
    range_ft: Optional[float]
    castable_levels: List[int]
    targets: List[TargetOption]
    aim_points: List[AimOption] = field(default_factory=list)
    #: True when :data:`DEFAULT_MAX_AIM_POINTS` cut real aim options. Harness
    #: metadata, never shown to an agent (not in :meth:`to_dict`).
    aim_points_truncated: bool = False

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "cost": self.cost,
            "spell_level": self.spell_level,
            "targeting": self.targeting,
            "range_ft": self.range_ft,
            "castable_levels": self.castable_levels,
            "targets": [t.to_dict() for t in self.targets],
            "aim_points": [a.to_dict() for a in self.aim_points],
        }


@dataclass(frozen=True)
class MoveOption:
    """A named, legal destination the entity can move to this turn.

    Every ``MoveOption`` is affordable (within the movement budget) and
    overlap-clear (does not land on another creature) — *legal by construction*, so
    an agent can pick one by ``option_id`` instead of solving the geometry itself.
    Raw-coordinate movement stays available for bespoke positioning. ``x/y/z`` are
    the destination in backend feet; ``cost_ft`` the movement it spends.
    """

    option_id: str
    label: str
    description: str
    x: float
    y: float
    z: float
    cost_ft: float

    def to_dict(self) -> dict:
        return {
            "option_id": self.option_id,
            "label": self.label,
            "description": self.description,
            "x": self.x,
            "y": self.y,
            "z": self.z,
            "cost_ft": self.cost_ft,
        }


@dataclass(frozen=True)
class LegalActions:
    """Everything *entity* may legally attempt on its turn, as a menu.

    A hint for the agent, not an enforcement boundary — the engine still validates
    each chosen action. ``can_end_turn`` is always True (ending a turn is always legal).
    """

    entity_id: str
    movement_remaining_ft: float
    attacks: List[AttackOption] = field(default_factory=list)
    spells: List[SpellOption] = field(default_factory=list)
    moves: List[MoveOption] = field(default_factory=list)
    can_end_turn: bool = True

    @property
    def truncated(self) -> bool:
        """Whether a cap removed real options anywhere in this menu."""
        return any(s.aim_points_truncated for s in self.spells)

    def to_dict(self) -> dict:
        return {
            "entity_id": self.entity_id,
            "movement_remaining_ft": self.movement_remaining_ft,
            "attacks": [a.to_dict() for a in self.attacks],
            "spells": [s.to_dict() for s in self.spells],
            "moves": [m.to_dict() for m in self.moves],
            "can_end_turn": self.can_end_turn,
        }


def _cost_to_dict(cost: ActionCost) -> dict:
    return {
        "actions": cost.actions,
        "bonus_actions": cost.bonus_actions,
        "reactions": cost.reactions,
        "movement": cost.movement,
    }


def _relation(actor: Entity, other: Entity) -> str:
    """Affiliation of *other* to *actor*: ``self``, ``ally``, or ``enemy``."""
    if other is actor:
        return "self"
    return "ally" if other.team == actor.team else "enemy"


def _attack_targets(
    combat: "CombatSystem", attacker: Entity, action: AttackAction
) -> List[TargetOption]:
    """Enemies within the attack's range.

    Weapon attacks list only foes — offering allies invites wasted, self-defeating
    actions and muddies the benchmark signal. (The referee does not forbid a raw
    ally attack; the menu simply does not suggest one.)
    """
    reachable: List[TargetOption] = []
    for other in combat.get_alive_entities():
        if other is attacker or other.team == attacker.team:
            continue
        try:
            check_attack_range(attacker, other, action)
        except ValueError:
            continue
        reachable.append(TargetOption(other.entity_id, other.name, "enemy"))
    return reachable


def _spell_targets(
    combat: "CombatSystem", caster: Entity, action: SpellAction
) -> List[TargetOption]:
    """In-range entities for a single-target spell, each tagged by relation.

    Unlike an attack, a spell may aim at friend or foe (heal an ally, harm an
    enemy), and the engine carries no generic beneficial/harmful flag — so every
    reachable target is listed with its ``relation`` and the caster chooses.
    AoE / multi-target / special spells are aimed at a point or assigned per
    projectile, so no fixed target list is produced for them.
    """
    if action.targeting_type != TargetingType.SINGLE_TARGET:
        return []
    reachable: List[TargetOption] = []
    for other in combat.get_alive_entities():
        if other is caster and not action.can_target_self:
            continue
        try:
            check_single_target_range(caster, other, action)
        except ValueError:
            continue
        reachable.append(
            TargetOption(other.entity_id, other.name, _relation(caster, other))
        )
    return reachable


def _castable_levels(caster: Entity, action: SpellAction) -> List[int]:
    """Slot levels *action* can be cast at right now.

    A cantrip (level 0) needs no slot and is always ``[0]``. A levelled spell can
    be cast at its base level or any higher level for which a slot remains.
    """
    base = action.spell_level
    if base == 0:
        return [0]
    if caster.spell_slots is None:
        return []
    max_level = max(caster.spell_slots.max_slots) if caster.spell_slots.max_slots else 0
    return [
        level
        for level in range(base, max_level + 1)
        if caster.spell_slots.can_afford(level)
    ]


def _owned_attacks(entity: Entity) -> List[Action]:
    """Attack/ability actions the entity carries directly (innate + granted)."""
    return list(entity.stat_block.actions) + list(entity.granted_actions)


def _max_attack_range_ft(entity: Entity) -> float:
    """Longest reach among the entity's affordable weapon/attack actions (0 if none)."""
    ranges = [
        a.range_ft
        for a in _owned_attacks(entity)
        if isinstance(a, AttackAction) and entity.can_afford(a.cost)
    ]
    return max(ranges) if ranges else 0.0


def _clear_option_along(
    combat: "CombatSystem",
    entity: Entity,
    unit: tuple,
    desired_travel: float,
    budget: float,
    option_id: str,
    label: str,
    description: str,
) -> Optional[MoveOption]:
    """Build a legal :class:`MoveOption` a distance ``desired_travel`` along *unit*.

    Clamps to the movement ``budget``, then steps back toward the origin in 1 ft
    decrements until the destination is overlap-clear (the origin is always clear, so
    this terminates). Returns ``None`` when no clear point of at least 1 ft exists —
    the option is simply omitted rather than offered as an illegal move.
    """
    ux, uy, uz = unit
    travel = min(max(desired_travel, 0.0), budget)
    while travel >= 1.0:
        nx = entity.x + ux * travel
        ny = entity.y + uy * travel
        nz = entity.z + uz * travel
        if combat.is_destination_clear(entity, nx, ny, nz):
            return MoveOption(
                option_id, label, description, nx, ny, nz, round(travel, 1)
            )
        travel -= 1.0
    return None


def move_candidates(combat: "CombatSystem", entity: Entity) -> List[MoveOption]:
    """Named, legal move destinations for *entity* — its tactical positioning menu.

    For each enemy (ordered by ``entity_id`` for deterministic replays): close to melee
    standoff, retreat at full speed, and — for an entity with a ranged attack — a
    ``kite_range`` point as far back as possible while staying within weapon range.
    Every option is affordable and overlap-clear (see :func:`_clear_option_along`); an
    agent may still move to a raw coordinate instead. Read-only.
    """
    budget = entity.resources.movement
    if budget < 1:
        return []

    options: List[MoveOption] = []
    max_range = _max_attack_range_ft(entity)
    ox, oy, oz = entity.x, entity.y, entity.z
    self_half = entity.stat_block.size.size_ft / 2.0

    for enemy in sorted(combat.get_enemies(entity), key=lambda e: e.entity_id):
        dx, dy, dz = enemy.x - ox, enemy.y - oy, enemy.z - oz
        dist = math.sqrt(dx * dx + dy * dy + dz * dz)
        if dist == 0:
            continue
        toward = (dx / dist, dy / dist, dz / dist)
        away = (-toward[0], -toward[1], -toward[2])
        standoff = self_half + enemy.stat_block.size.size_ft / 2.0 + 0.5

        melee = _clear_option_along(
            combat,
            entity,
            toward,
            dist - standoff,
            budget,
            f"toward_melee:{enemy.entity_id}",
            f"Close to melee reach of {enemy.name}",
            f"Move toward {enemy.name}, stopping just within melee reach.",
        )
        if melee is not None:
            options.append(melee)

        retreat = _clear_option_along(
            combat,
            entity,
            away,
            budget,
            budget,
            f"retreat:{enemy.entity_id}",
            f"Retreat from {enemy.name}",
            f"Move directly away from {enemy.name} at full speed.",
        )
        if retreat is not None:
            options.append(retreat)

        if max_range > 5:
            travel = min(max_range, dist + budget) - dist  # extra distance to open up
            if travel >= 1:
                kite = _clear_option_along(
                    combat,
                    entity,
                    away,
                    travel,
                    budget,
                    f"kite_range:{enemy.entity_id}",
                    f"Kite {enemy.name} to weapon range",
                    f"Fall back from {enemy.name} as far as possible while staying "
                    f"within your {max_range:g} ft attack range.",
                )
                if kite is not None:
                    options.append(kite)

    return options


def _sweep_bounds(
    combat: "CombatSystem", caster: Entity, reach_ft: float
) -> Tuple[float, float, float, float]:
    """``(min_x, max_x, min_z, max_z)`` covering every aim point that could hit anyone.

    A point catches a creature only if it is within the area's reach of it, so the
    creatures' own extent expanded by that reach is a *complete* bound — sweeping
    outside it would only ever produce empty target sets. That keeps a fine sweep
    cheap without discarding a single option.

    The caster is included because directional shapes (cone, line) originate at the
    caster, so directions "behind" it must still be reachable by the sweep.
    """
    xs = [e.x for e in combat.get_alive_entities()] + [caster.x]
    zs = [e.z for e in combat.get_alive_entities()] + [caster.z]
    margin = reach_ft + _MAX_CREATURE_HALF_FT
    return min(xs) - margin, max(xs) + margin, min(zs) - margin, max(zs) + margin


def _frange(start: float, stop: float, step: float) -> List[float]:
    """Inclusive float range, quantised so the same bounds always give the same grid."""
    count = int(math.floor((stop - start) / step)) + 1
    return [round(start + i * step, 3) for i in range(max(count, 1))]


def aim_candidates(
    combat: "CombatSystem",
    caster: Entity,
    spell: SpellAction,
    *,
    step_ft: float = DEFAULT_AIM_STEP_FT,
    max_candidates: Optional[int] = DEFAULT_MAX_AIM_POINTS,
) -> List[AimOption]:
    """Distinct ways *caster* could aim *spell* right now — the area-targeting menu.

    **Deliberately neutral.** This enumerates what is *possible* and never scores it.
    The :class:`~src.arena.heuristic.agent.HeuristicAgent` has its own placement search
    that ranks points by foes-caught minus allies-caught; borrowing it would smuggle
    the heuristic's judgement into the menu and inflate the enumerated condition's
    apparent tactical skill (V1_PLAN §3.1). Nothing here imports from
    ``src.arena.heuristic``, and a test enforces that.

    Method: sweep a ground grid at *step_ft* over :func:`_sweep_bounds`, ask the
    **engine's own** ``derive_aoe_origin`` and ``get_targets_in_aoe`` who each point
    would catch — so the menu and the resolver can never disagree — then keep one
    representative per distinct set of targets. Points catching nobody are dropped.

    Results are ordered lexicographically by their target ids. That ordering carries
    no quality signal on purpose: sorting a menu by "most enemies hit" would rank it,
    and ranking is a nudge in an experiment about how agents choose.

    Returns ``[]`` for a non-area spell, and for an area shape the engine cannot model
    spatially — the menu omits what it cannot describe, exactly as it already omits a
    spell missing from the registry.
    """
    if spell.targeting_type != TargetingType.AOE or spell.aoe is None:
        return []

    range_ft = effective_range_ft(spell)
    caster_centre = caster.bounding_box.center()
    min_x, max_x, min_z, max_z = _sweep_bounds(combat, caster, float(spell.aoe.size_ft))

    seen: Dict[frozenset, AimOption] = {}
    for z in _frange(min_z, max_z, step_ft):
        for x in _frange(min_x, max_x, step_ft):
            point = Point3D(x, 0.0, z)
            # Offer only points the caster could actually name. The engine clamps an
            # over-range aim to the edge, so skipping these loses no reachable target
            # set — it just avoids listing a point whose stated coordinates are not
            # where the spell would land.
            if range_ft is not None and caster_centre.distance_to(point) > range_ft:
                continue
            try:
                origin, direction = derive_aoe_origin(caster, spell, point)
                caught = combat.get_targets_in_aoe(origin, spell.aoe, direction)
            except ValueError:
                return []  # a shape the engine does not model spatially

            if spell.cannot_cause_self_damage:
                caught = [e for e in caught if e is not caster]
            if not caught:
                continue

            key = frozenset(e.entity_id for e in caught)
            if key in seen:
                continue
            ids = sorted(e.entity_id for e in caught)
            seen[key] = AimOption(
                option_id="aim:" + "+".join(ids),
                x=x,
                y=0.0,
                z=z,
                hits=[
                    TargetOption(e.entity_id, e.name, _relation(caster, e))
                    for e in sorted(caught, key=lambda e: e.entity_id)
                ],
            )

    options = sorted(seen.values(), key=lambda o: [t.entity_id for t in o.hits])
    return options if max_candidates is None else options[:max_candidates]


@dataclass(frozen=True)
class AimCoverage:
    """How much of the possible aiming space the offered menu actually covers.

    This is H4's expressivity number (V1_PLAN §3.3). It exists because the candidate
    rule creates a subtlety worth stating plainly: since a target set fully determines
    an area spell's outcome, a menu offering *every achievable target set* costs no
    expressivity at all — the enumerated condition could then express everything free
    aiming can, and H4's area arm would be null **by construction rather than by
    evidence**.

    Whether that is so depends entirely on the grid resolution, which is an
    implementation choice, not a fact. So it is measured: a fine sweep establishes what
    is achievable, the menu sweep establishes what is offered, and ``missing`` is the
    difference. A coverage of 1.0 is a finding ("enumeration need not cost expressivity
    when the candidates are outcome-complete"), not a free pass.
    """

    achievable: int
    offered: int
    missing: List[List[str]]

    @property
    def coverage(self) -> float:
        """Fraction of achievable target sets the menu offers (1.0 = lossless)."""
        return self.offered / self.achievable if self.achievable else 1.0

    def to_dict(self) -> dict:
        return {
            "achievable": self.achievable,
            "offered": self.offered,
            "coverage": round(self.coverage, 4),
            "missing": self.missing,
        }


def aim_coverage(
    combat: "CombatSystem",
    caster: Entity,
    spell: SpellAction,
    *,
    menu_step_ft: float = DEFAULT_AIM_STEP_FT,
    oracle_step_ft: float = 1.0,
) -> AimCoverage:
    """Measure what the menu's resolution costs, against a finer sweep of the same rule.

    The oracle *is* :func:`aim_candidates` at a finer step, so there is no second
    implementation to disagree with the first — only one parameter differs. Offline
    and free; no model is involved.

    ``max_candidates`` is disabled on both sides on purpose: this measures what the
    *resolution* costs, and folding in what the cap costs would confuse two separate
    questions.
    """
    unlimited = 10**9
    offered = {
        tuple(t.entity_id for t in o.hits)
        for o in aim_candidates(
            combat, caster, spell, step_ft=menu_step_ft, max_candidates=unlimited
        )
    }
    achievable = {
        tuple(t.entity_id for t in o.hits)
        for o in aim_candidates(
            combat, caster, spell, step_ft=oracle_step_ft, max_candidates=unlimited
        )
    }
    return AimCoverage(
        achievable=len(achievable),
        offered=len(offered),
        missing=sorted(list(t) for t in achievable - offered),
    )


def _threat_class(
    combat: "CombatSystem", entity: Entity, x: float, y: float, z: float
) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
    """What standing at ``(x, y, z)`` *means*, as an outcome-equivalence class.

    Two destinations are tactically the same when they offer the same attacks and
    expose you to the same threats, so a position is summarised as **(enemies I could
    attack from here, enemies that could reach me next turn)**. Everything else about a
    point — its exact coordinates, the route taken — has no effect the engine models.

    Reach is the engine's own (``check_attack_range`` against real bounding boxes), so
    the measurement agrees with what an attack would actually do. Threat is the
    standard approximation: an enemy that can close its speed and still reach.

    Moves *entity* temporarily and puts it back; callers see no change.
    """
    origin = (entity.x, entity.y, entity.z)
    entity.x, entity.y, entity.z = x, y, z
    try:
        attackable = []
        threatened_by = []
        my_attacks = [
            a
            for a in _owned_attacks(entity)
            if isinstance(a, AttackAction) and entity.can_afford(a.cost)
        ]
        for enemy in combat.get_enemies(entity):
            if not enemy.is_alive():
                continue
            if any(_in_reach(entity, enemy, a) for a in my_attacks):
                attackable.append(enemy.entity_id)
            reach = _max_attack_range_ft(enemy) + enemy.resources.movement
            if _gap_ft(entity, enemy) <= reach:
                threatened_by.append(enemy.entity_id)
        return tuple(sorted(attackable)), tuple(sorted(threatened_by))
    finally:
        entity.x, entity.y, entity.z = origin


def _in_reach(attacker: Entity, defender: Entity, action: AttackAction) -> bool:
    try:
        check_attack_range(attacker, defender, action)
    except ValueError:
        return False
    return True


def _gap_ft(a: Entity, b: Entity) -> float:
    """Edge-to-edge distance between two creatures, as the engine measures reach."""
    box_a, box_b = a.bounding_box, b.bounding_box
    gx = max(
        0.0,
        box_a.min_corner.x - box_b.max_corner.x,
        box_b.min_corner.x - box_a.max_corner.x,
    )
    gy = max(
        0.0,
        box_a.min_corner.y - box_b.max_corner.y,
        box_b.min_corner.y - box_a.max_corner.y,
    )
    gz = max(
        0.0,
        box_a.min_corner.z - box_b.max_corner.z,
        box_b.min_corner.z - box_a.max_corner.z,
    )
    return math.sqrt(gx * gx + gy * gy + gz * gz)


def _reachable_classes(combat: "CombatSystem", entity: Entity, step_ft: float) -> set:
    """Every threat class *entity* could reach this turn, by sweeping its budget."""
    budget = entity.resources.movement
    classes = {_threat_class(combat, entity, entity.x, entity.y, entity.z)}
    if budget < 1:
        return classes

    steps = int(budget // step_ft)
    for i in range(-steps, steps + 1):
        for j in range(-steps, steps + 1):
            dx, dz = i * step_ft, j * step_ft
            if math.sqrt(dx * dx + dz * dz) > budget:
                continue  # outside the movement budget
            x, z = entity.x + dx, entity.z + dz
            if not combat.is_destination_clear(entity, x, entity.y, z):
                continue
            classes.add(_threat_class(combat, entity, x, entity.y, z))
    return classes


def move_coverage(
    combat: "CombatSystem",
    entity: Entity,
    *,
    oracle_step_ft: float = 2.5,
) -> AimCoverage:
    """How much of the *movement* outcome space the named destinations cover.

    The counterpart of :func:`aim_coverage`, and the one that matters. Area aiming
    turned out to be outcome-complete, which makes H4's area arm null by construction
    (see :class:`AimCoverage`); movement candidates are three named destinations per
    enemy and have never been measured. If they are lossy — and they are expected to
    be — this is where an enumerated condition genuinely gives something up, and H4's
    live arm is here rather than in the area menu.

    Offered classes come from :func:`move_candidates`, achievable ones from sweeping
    the whole movement budget, both scored by :func:`_threat_class`. Offline and free.
    """
    offered = {
        _threat_class(combat, entity, option.x, option.y, option.z)
        for option in move_candidates(combat, entity)
    }
    offered.add(_threat_class(combat, entity, entity.x, entity.y, entity.z))
    achievable = _reachable_classes(combat, entity, oracle_step_ft)

    missing = sorted(
        [f"attack:{'+'.join(a) or '-'}", f"threatened:{'+'.join(t) or '-'}"]
        for a, t in achievable - offered
    )
    return AimCoverage(
        achievable=len(achievable),
        offered=len(offered & achievable),
        missing=missing,
    )


def legal_actions(combat: "CombatSystem", entity: Entity) -> LegalActions:
    """Assemble the legal-action menu for *entity* in *combat*.

    Read-only: it inspects resources, slots, and ranges but changes nothing. Spells
    are skipped when the combat has no spell registry configured, or a known spell is
    absent from it (the engine would raise at cast time — the menu simply omits it).
    """
    result = LegalActions(
        entity_id=entity.entity_id,
        movement_remaining_ft=entity.resources.movement,
    )
    attacks: List[AttackOption] = []
    spells: List[SpellOption] = []

    for action in _owned_attacks(entity):
        if not isinstance(action, AttackAction):
            continue
        if not entity.can_afford(action.cost):
            continue
        attacks.append(
            AttackOption(
                name=action.name,
                cost=_cost_to_dict(action.cost),
                range_ft=action.range_ft,
                targets=_attack_targets(combat, entity, action),
            )
        )

    registry = combat.spell_registry
    if registry is not None:
        for spell_name in entity.stat_block.known_spells:
            if spell_name not in registry:
                continue
            action = registry.get(spell_name)
            if not entity.can_afford(action.cost):
                continue
            levels = _castable_levels(entity, action)
            if not levels:
                continue
            # Capped here, with the bite recorded, rather than silently inside
            # aim_candidates. The cap is read at call time so a test can lower it.
            aims = aim_candidates(combat, entity, action, max_candidates=None)
            cap = DEFAULT_MAX_AIM_POINTS
            spells.append(
                SpellOption(
                    name=action.name,
                    cost=_cost_to_dict(action.cost),
                    spell_level=action.spell_level,
                    targeting=action.targeting_type.value,
                    range_ft=effective_range_ft(action),
                    castable_levels=levels,
                    targets=_spell_targets(combat, entity, action),
                    aim_points=aims[:cap],
                    aim_points_truncated=len(aims) > cap,
                )
            )

    return LegalActions(
        entity_id=result.entity_id,
        movement_remaining_ft=result.movement_remaining_ft,
        attacks=attacks,
        spells=spells,
        moves=move_candidates(combat, entity),
    )
