"""Tests for the seedable shared RNG (E11) and multi-term formula rolling."""

from src.utils import dice


class TestContextScopedRng:
    """Per-instance RNGs bound via ``using_rng`` are isolated and reproducible."""

    def test_seeded_instances_are_isolated_and_reproducible(self):
        # Two RNGs on the same seed, whose rolls are *interleaved*, must each yield the
        # same stream they would in isolation — one battle's draws never perturb another.
        r1, r2 = dice.new_rng(42), dice.new_rng(42)
        a1 = _roll_under(r1)
        _roll_under(r2)  # interleave a draw from the other instance
        a2 = _roll_under(r1)

        s1, s2 = dice.new_rng(42), dice.new_rng(42)
        b1 = _roll_under(s1)
        b2 = _roll_under(s1)  # no interleaving
        assert (a1, a2) == (b1, b2)
        # And the interleaved second RNG matched the first at step 1.
        assert _roll_under(s2) == b1

    def test_using_rng_restores_the_previous_binding(self):
        dice.seed_rng(1)
        expected = dice.roll_d20()
        dice.seed_rng(1)
        with dice.using_rng(dice.new_rng(999)):
            dice.roll_d20()  # consume from the bound RNG, not the ambient one
        # The ambient stream is untouched by the with-block.
        assert dice.roll_d20() == expected

    def test_new_id_is_reproducible_under_a_seed(self):
        with dice.using_rng(dice.new_rng(7)):
            first = [dice.new_id() for _ in range(5)]
        with dice.using_rng(dice.new_rng(7)):
            second = [dice.new_id() for _ in range(5)]
        assert first == second
        assert len(set(first)) == 5  # ids are distinct

    def teardown_method(self):
        dice.seed_rng(None)


def _roll_under(rng):
    with dice.using_rng(rng):
        return dice.roll_d20()


class TestSeedRng:
    def test_seeding_makes_rolls_reproducible(self):
        dice.seed_rng(1234)
        a = [dice.roll_d20() for _ in range(10)]
        dice.seed_rng(1234)
        b = [dice.roll_d20() for _ in range(10)]
        assert a == b

    def test_different_seeds_differ(self):
        dice.seed_rng(1)
        a = [dice.roll_d20() for _ in range(20)]
        dice.seed_rng(2)
        b = [dice.roll_d20() for _ in range(20)]
        assert a != b

    def test_roll_dice_is_seeded_too(self):
        dice.seed_rng(99)
        a = dice.roll_dice(5, 6)
        dice.seed_rng(99)
        b = dice.roll_dice(5, 6)
        assert a == b

    def test_reseed_none_restores_nondeterminism(self):
        # Sanity: seeding with None should not raise and returns valid rolls.
        dice.seed_rng(None)
        assert 1 <= dice.roll_d20() <= 20

    def teardown_method(self):
        # Leave the RNG unseeded so other tests are unaffected.
        dice.seed_rng(None)


class TestMultiTermFormulas:
    def test_multi_term_formula_rolls_in_range(self):
        dice.seed_rng(7)
        # 2d6+1d8+5 → min 2+1+5=8, max 12+8+5=25
        total = dice.roll_formula("2d6+1d8+5")
        assert 8 <= total <= 25

    def test_seeded_multi_term_is_reproducible(self):
        dice.seed_rng(42)
        a = dice.roll_formula("3d8+6")
        dice.seed_rng(42)
        b = dice.roll_formula("3d8+6")
        assert a == b

    def teardown_method(self):
        dice.seed_rng(None)
