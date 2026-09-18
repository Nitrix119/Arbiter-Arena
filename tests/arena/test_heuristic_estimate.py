"""Expected-value primitives — parity with the engine and exact analytic values.

The parity test (``expected_formula`` vs a large sample of ``roll_formula``) is the guard
that keeps an estimate honest against the real roller; the rest pin the exact to-hit /
crit / save math the scorer depends on, using the real spell programs from
``examples/spells``.
"""

import pytest

from src.arena.heuristic import estimate
from src.models.damage import DamageType
from src.utils import dice

from .conftest import load_spell, melee_attack


# ---------------------------------------------------------------------------
# expected_formula — parity with roll_formula, and exact means
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "formula,expected",
    [("1d8", 4.5), ("2d6+3", 10.0), ("3d6", 10.5), ("1d10", 5.5), ("5", 5.0), ("2d6-2", 5.0)],
)
def test_expected_formula_exact(formula, expected):
    assert estimate.expected_formula(formula) == pytest.approx(expected)


@pytest.mark.parametrize("formula", ["1d8", "2d6+3", "3d6", "1d10+4", "4d4"])
def test_expected_formula_parity_with_roller(formula):
    """The analytic mean matches the sampled mean of the real roller."""
    dice.seed_rng(20260917)
    n = 40000
    total = sum(dice.roll_formula(formula) for _ in range(n))
    sampled_mean = total / n
    assert sampled_mean == pytest.approx(estimate.expected_formula(formula), abs=0.05)


# ---------------------------------------------------------------------------
# hit_chance / crit_chance
# ---------------------------------------------------------------------------


def test_hit_chance_midrange():
    # +5 vs AC 15 → need 10 on the die → faces 10..19 (10) + nat-20 = 11/20.
    assert estimate.hit_chance(5, 15) == pytest.approx(0.55)


def test_hit_chance_clamps_to_nat_bounds():
    assert estimate.hit_chance(50, 15) == pytest.approx(estimate.MAX_HIT_CHANCE)  # nat-1 misses
    assert estimate.hit_chance(0, 40) == pytest.approx(estimate.MIN_HIT_CHANCE)  # nat-20 hits


def test_advantage_beats_straight_beats_disadvantage():
    straight = estimate.hit_chance(5, 15)
    adv = estimate.hit_chance(5, 15, advantage=True)
    dis = estimate.hit_chance(5, 15, disadvantage=True)
    assert dis < straight < adv


def test_advantage_and_disadvantage_cancel():
    both = estimate.hit_chance(5, 15, advantage=True, disadvantage=True)
    assert both == pytest.approx(estimate.hit_chance(5, 15))


def test_crit_chance_values():
    assert estimate.crit_chance() == pytest.approx(0.05)
    assert estimate.crit_chance(advantage=True) == pytest.approx(1 - (0.95 ** 2))
    assert estimate.crit_chance(disadvantage=True) == pytest.approx(0.05 ** 2)


# ---------------------------------------------------------------------------
# expected_attack_damage — crit uplift and resistance
# ---------------------------------------------------------------------------


def test_attack_ev_includes_crit_uplift(make_entity):
    # +5 vs AC 15: p_hit 0.55, p_crit 0.05, p_normal 0.50; 1d8 (dice mean 4.5, no flat).
    # EV = 0.50*4.5 + 0.05*(2*4.5) = 2.25 + 0.45 = 2.70.
    defender = make_entity("D", ac=15)
    ev = estimate.expected_attack_damage(melee_attack(), defender)
    assert ev == pytest.approx(2.70)


def test_attack_ev_resistance_and_immunity(make_entity):
    defender = make_entity("D", ac=15)
    base = estimate.expected_attack_damage(melee_attack(), defender)

    defender.stat_block.damage_resistances.append(DamageType.SLASHING)
    assert estimate.expected_attack_damage(melee_attack(), defender) == pytest.approx(base / 2)

    defender.stat_block.damage_resistances.clear()
    defender.stat_block.damage_immunities.append(DamageType.SLASHING)
    assert estimate.expected_attack_damage(melee_attack(), defender) == pytest.approx(0.0)


def test_attack_ev_ignores_resistance_when_asked(make_entity):
    """A hidden-info caller can decline to use resistances it shouldn't know."""
    defender = make_entity("D", ac=15)
    base = estimate.expected_attack_damage(melee_attack(), defender)
    defender.stat_block.damage_resistances.append(DamageType.SLASHING)
    unaware = estimate.expected_attack_damage(melee_attack(), defender, apply_resistance=False)
    assert unaware == pytest.approx(base)


# ---------------------------------------------------------------------------
# save_fail_prob
# ---------------------------------------------------------------------------


def test_save_fail_prob_exact(make_entity):
    # Defender DEX mod +2, no proficiency → save bonus +2. DC 13 → need 11 → 10 success
    # faces → p_success 0.5 → p_fail 0.5.
    defender = make_entity("D")
    assert estimate.save_fail_prob(defender, "dexterity", 13) == pytest.approx(0.5)


def test_save_fail_prob_monotonic_in_dc(make_entity):
    defender = make_entity("D")
    fails = [estimate.save_fail_prob(defender, "dexterity", dc) for dc in range(5, 25)]
    assert fails == sorted(fails)  # higher DC never lowers the fail chance


def test_save_advantage_lowers_fail(make_entity):
    defender = make_entity("D")
    straight = estimate.save_fail_prob(defender, "dexterity", 15)
    adv = estimate.save_fail_prob(defender, "dexterity", 15, advantage=True)
    assert adv < straight


# ---------------------------------------------------------------------------
# spell_expected_damage — real programs (attack-roll and save shapes)
# ---------------------------------------------------------------------------


def test_spell_ev_attack_roll_shape(make_entity):
    # Fire Bolt: use_caster_bonus. Caster INT +1, prof +2 → spell attack +3.
    # vs AC 15 → need 12 → faces 12..19 (8) + nat-20 = 9/20 = 0.45 hit, 0.05 crit,
    # 0.40 normal. 1d10 (mean 5.5): EV = 0.40*5.5 + 0.05*11 = 2.20 + 0.55 = 2.75.
    caster = make_entity("C", spellcasting_ability="intelligence")
    defender = make_entity("D", ac=15)
    firebolt = load_spell("firebolt.json")
    assert estimate.spell_expected_damage(firebolt, caster, defender) == pytest.approx(2.75)


def test_spell_ev_save_shape(make_entity):
    # Sacred Flame: save DC = 8 + prof 2 + INT 1 = 11. Defender DEX save +2 → need 9 →
    # 12 success faces → p_success 0.6 → p_fail 0.4. 1d8 (4.5), no_damage on success:
    # EV = 0.4 * 4.5 = 1.8.
    caster = make_entity("C", spellcasting_ability="intelligence")
    defender = make_entity("D")
    sacred_flame = load_spell("sacred_flame.json")
    assert estimate.spell_expected_damage(sacred_flame, caster, defender) == pytest.approx(1.8)
