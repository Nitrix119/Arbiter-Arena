"""Expected-value primitives — the deterministic twins of the engine's dice rollers.

Every function here is pure and side-effect-free: it reads authoring fields and entity
state and returns an *expectation*, rolling no dice and mutating nothing. The estimates
mirror the engine's real resolution so the scorer's ranking matches what actually
happens in combat:

* to-hit follows ``src/spells/blocks/rolls.py`` — a natural 20 always hits, a natural 1
  always misses, otherwise ``d20 + bonus >= AC``;
* crits double the *dice* (not flat modifiers), matching ``src/spells/blocks/damage.py``;
* saving throws use the defender's real save bonus and have no crit.

``tests/arena/test_heuristic_estimate.py`` checks :func:`expected_formula` against a large
sample of ``roll_formula`` (parity), so a drift between an estimate and the engine is
caught rather than shipped silently (the discipline of CLAUDE.md §9 2026-09-03).
"""

from __future__ import annotations

from typing import Optional, Tuple

from src.models.action import AttackAction, SpellAction
from src.models.damage import DamageType
from src.models.entity import Entity
from src.utils.dice import parse_dice_formula

# A natural 20 always hits and a natural 1 always misses, so any single d20 attack lands
# between these bounds regardless of the bonus/AC gap.
MIN_HIT_CHANCE = 0.05
MAX_HIT_CHANCE = 0.95

# The chance a single straight d20 shows a natural 20 (a critical hit).
_CRIT_FACE_CHANCE = 1.0 / 20.0

# A stand-in armour class for *threat* estimation, when we score how dangerous an enemy
# is in the abstract (its expected damage per turn) rather than against a concrete target.
TYPICAL_AC = 14


def _single_roll_hit_prob(attack_bonus: int, target_ac: int) -> float:
    """P(hit) for one straight d20, honouring nat-20 auto-hit / nat-1 auto-miss.

    A face ``r`` in 2..19 hits when ``r >= target_ac - attack_bonus``; the natural 20
    always hits and the natural 1 always misses. The result therefore falls in
    ``[MIN_HIT_CHANCE, MAX_HIT_CHANCE]`` by construction.
    """
    need = target_ac - attack_bonus
    lo = max(2, need)
    normal_faces = max(0, 19 - lo + 1)  # faces in [lo, 19] that hit
    winning = normal_faces + 1  # + the guaranteed natural 20
    return winning / 20.0


def hit_chance(
    attack_bonus: int,
    target_ac: int,
    *,
    advantage: bool = False,
    disadvantage: bool = False,
) -> float:
    """Probability an attack lands, folding advantage/disadvantage.

    Advantage and disadvantage together cancel to a straight roll (5e), matching the
    engine. The returned value includes the critical-hit face (a nat 20 is a hit).
    """
    p = _single_roll_hit_prob(attack_bonus, target_ac)
    if advantage and not disadvantage:
        return 1.0 - (1.0 - p) ** 2
    if disadvantage and not advantage:
        return p * p
    return p


def crit_chance(*, advantage: bool = False, disadvantage: bool = False) -> float:
    """Probability of a natural 20 (critical hit), folding advantage/disadvantage."""
    if advantage and not disadvantage:
        return 1.0 - (1.0 - _CRIT_FACE_CHANCE) ** 2
    if disadvantage and not advantage:
        return _CRIT_FACE_CHANCE**2
    return _CRIT_FACE_CHANCE


def _formula_parts(formula: str) -> Tuple[float, float]:
    """Split a dice formula into ``(expected_dice_total, flat_total)``.

    Each ``NdS`` term contributes ``N * (S + 1) / 2`` to the dice mean; flat modifiers
    sum into the flat total. Splitting them lets :func:`expected_attack_damage` double
    only the dice on a crit, exactly as the engine does.
    """
    dice_mean = 0.0
    flat = 0.0
    if not formula:
        return 0.0, 0.0
    for count, sides, is_dice in parse_dice_formula(formula):
        if is_dice:
            dice_mean += count * (sides + 1) / 2.0
        else:
            flat += count
    return dice_mean, flat


def expected_formula(formula: str) -> float:
    """The mean total of a dice formula (the deterministic twin of ``roll_formula``)."""
    dice_mean, flat = _formula_parts(formula)
    return dice_mean + flat


def damage_multiplier(defender: Entity, damage_type: DamageType) -> float:
    """The resistance/immunity/vulnerability multiplier *defender* applies to a type.

    ``0`` for immunity, ``0.5`` for resistance, ``2`` for vulnerability, else ``1``.
    These live on the ``StatBlock`` and are not exposed in the observation, so a caller
    scoring damage to an *enemy under hidden information* should pass
    ``apply_resistance=False`` rather than peek at knowledge the agent shouldn't have.
    """
    block = defender.stat_block
    if damage_type in block.damage_immunities:
        return 0.0
    if damage_type in block.damage_resistances:
        return 0.5
    if damage_type in block.damage_vulnerabilities:
        return 2.0
    return 1.0


def _damage_ev(dice_mean: float, flat: float, p_normal: float, p_crit: float) -> float:
    """Expected damage of one hit-gated component: crit doubles the dice, not the flat."""
    return p_normal * (dice_mean + flat) + p_crit * (2.0 * dice_mean + flat)


def expected_attack_damage(
    attack: AttackAction,
    defender: Entity,
    *,
    advantage: bool = False,
    disadvantage: bool = False,
    apply_resistance: bool = True,
) -> float:
    """Expected damage of a weapon attack against *defender*.

    Folds hit chance and the crit uplift (nat-20 doubles the dice) over every entry in
    the attack's flat ``damage`` list. ``apply_resistance`` gates the type multiplier so
    a hidden-information caller can decline to use resistances it shouldn't know.
    """
    p_hit = hit_chance(
        attack.bonus_to_hit,
        defender.ac,
        advantage=advantage,
        disadvantage=disadvantage,
    )
    p_crit = crit_chance(advantage=advantage, disadvantage=disadvantage)
    p_normal = max(0.0, p_hit - p_crit)  # hits that are not crits
    total = 0.0
    for d in attack.damage:
        dice_mean, flat = _formula_parts(d.formula or str(d.amount))
        ev = _damage_ev(dice_mean, flat, p_normal, p_crit)
        if apply_resistance:
            ev *= damage_multiplier(defender, d.damage_type)
        total += ev
    return total


def attack_ev_vs_ac(
    attack: AttackAction,
    target_ac: int,
    *,
    advantage: bool = False,
    disadvantage: bool = False,
) -> float:
    """Expected damage of an attack against a bare AC (no resistance).

    Used for *threat* estimation — how dangerous a creature is in the abstract — where
    there is no concrete defender, only a stand-in :data:`TYPICAL_AC`.
    """
    p_hit = hit_chance(
        attack.bonus_to_hit,
        target_ac,
        advantage=advantage,
        disadvantage=disadvantage,
    )
    p_crit = crit_chance(advantage=advantage, disadvantage=disadvantage)
    p_normal = max(0.0, p_hit - p_crit)
    total = 0.0
    for d in attack.damage:
        dice_mean, flat = _formula_parts(d.formula or str(d.amount))
        total += _damage_ev(dice_mean, flat, p_normal, p_crit)
    return total


def save_fail_prob(
    defender: Entity,
    ability: str,
    dc: int,
    *,
    advantage: bool = False,
    disadvantage: bool = False,
) -> float:
    """Probability *defender* fails a saving throw against *dc*.

    Uses the defender's real save bonus (``StatBlock.get_saving_throw_bonus``). This
    engine applies no nat-1/nat-20 auto rules to saves, so the estimate is a plain
    threshold. Advantage/disadvantage here favour the *defender* (a save is rolled by
    the target), so advantage lowers the fail probability.
    """
    bonus = defender.stat_block.get_saving_throw_bonus(ability)
    need = dc - bonus  # a face r succeeds when r >= need
    lo = max(1, min(21, need))
    success_faces = max(0, 21 - lo)  # faces in [lo, 20]
    p_success = success_faces / 20.0
    if advantage and not disadvantage:
        p_success = 1.0 - (1.0 - p_success) ** 2
    elif disadvantage and not advantage:
        p_success = p_success * p_success
    return 1.0 - p_success


def _to_damage_type(name: str) -> Optional[DamageType]:
    """Resolve a block's ``damage_type`` string to the enum, or ``None`` if unknown."""
    try:
        return DamageType[name.upper()]
    except KeyError:
        return None


def _unwrap_iterators(program: list) -> list:
    """Flatten a ``for_each_target`` iterator to its ``then`` body for per-target scanning.

    An AoE spell wraps its save/damage in ``for_each_target``; the body runs once per
    affected creature, so its per-target expected damage is the expected damage of that
    body. Non-iterator blocks pass through unchanged.
    """
    flat: list = []
    for block in program:
        if block.get("block") == "for_each_target":
            flat.extend(block.get("then", []))
        else:
            flat.append(block)
    return flat


def spell_expected_damage(
    spell: SpellAction,
    caster: Entity,
    defender: Entity,
    *,
    apply_resistance: bool = True,
) -> float:
    """Best-effort expected damage of a single-target spell against *defender*.

    Scans the spell's block ``program`` for a leading gate (``attack_roll`` or
    ``saving_throw``) and its ``damage`` blocks, and applies the same to-hit / crit /
    save-halving rules the engine uses. It covers the common single-target damage shapes
    (Fire Bolt: attack + hit-gated damage; Sacred Flame: save + no-damage-on-success) and,
    by unwrapping a ``for_each_target`` iterator to its ``then`` body, the *per-target*
    damage of an AoE spell (Fireball: save + half-on-success) — so an AoE placement search
    can sum this over the creatures a volume catches. Conditional/multi-gate spells fall
    back to a coarse sum of their ``damage`` blocks.
    """
    program = _unwrap_iterators(spell.program or [])
    p_hit: Optional[float] = None
    p_crit = 0.0
    p_fail: Optional[float] = None

    for block in program:
        kind = block.get("block")
        if kind == "attack_roll":
            spec = block.get("attack_bonus", 0)
            bonus = (
                caster.spell_attack_bonus if spec == "use_caster_bonus" else int(spec)
            )
            p_hit = hit_chance(bonus, defender.ac)
            p_crit = crit_chance()
        elif kind == "saving_throw":
            spec = block.get("dc", 0)
            dc = caster.spell_save_dc if spec == "use_caster_dc" else int(spec)
            ability = block.get("attribute", "")
            p_fail = save_fail_prob(defender, ability, dc) if ability else 1.0

    total = 0.0
    for block in program:
        if block.get("block") != "damage":
            continue
        dice_mean, flat = _formula_parts(block.get("formula", ""))
        full = dice_mean + flat
        if block.get("requires_hit"):
            if p_hit is None:
                ev = full  # malformed program: no gate to read, assume it lands
            else:
                ev = _damage_ev(dice_mean, flat, max(0.0, p_hit - p_crit), p_crit)
        elif block.get("save_result") and p_fail is not None:
            on_success = block["save_result"].get("on_success")
            if on_success == "half_damage":
                ev = p_fail * full + (1.0 - p_fail) * (full / 2.0)
            elif on_success == "no_damage":
                ev = p_fail * full
            else:
                ev = full
        else:
            ev = full  # unconditional damage
        if apply_resistance:
            dtype = _to_damage_type(block.get("damage_type", "GENERIC"))
            if dtype is not None:
                ev *= damage_multiplier(defender, dtype)
        total += ev
    return total
