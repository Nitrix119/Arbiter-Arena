"""A non-LLM battle replays bit-for-bit from a single seed.

These exercise the real resolution path end-to-end (build → initiative → run to a
result), the property the per-instance seeded RNG exists to guarantee.
"""

from src.arena.heuristic import ga
from src.arena.heuristic.score import DEFAULT_WEIGHTS
from src.arena.scenarios import SCENARIOS
from src.utils import dice

SCEN = "alpha_strike"


def _entity_ids_built_under(seed):
    with dice.using_rng(dice.new_rng(seed)):
        combat = SCENARIOS[SCEN].build()
    return [e.entity_id for e in combat.combatants]


class TestBattleDeterminism:
    def test_same_seed_replays_identically(self):
        r1 = ga.regenerate_match(DEFAULT_WEIGHTS, SCEN, seed=123)
        r2 = ga.regenerate_match(DEFAULT_WEIGHTS, SCEN, seed=123)
        # MatchResult is a dataclass; equality covers winner, rounds, survivors (by
        # entity_id) and hp fractions — so identical ids *and* identical rolls.
        assert r1 == r2

    def test_entity_ids_are_reproducible(self):
        assert _entity_ids_built_under(123) == _entity_ids_built_under(123)

    def test_arena_entity_ids_no_longer_depend_on_the_seed(self):
        """Arena ids are derived from the roster, so the seed does not move them.

        This inverts what this test asserted before stable ids: the id stream used to
        come from the RNG, so two seeds had to diverge. Now ids are a property of the
        roster — which is the point, since it lets a paired-seed analysis join on
        entity across conditions, and lets a replay rebuild without the seed.
        Seeded id *generation* is still exercised below, where it is still used.
        """
        assert _entity_ids_built_under(1) == _entity_ids_built_under(2)

    def test_dice_new_id_is_still_seeded_for_entities_built_outside_the_arena(self):
        """The web layer and standalone entities still draw ids from the RNG."""
        with dice.using_rng(dice.new_rng(1)):
            first = [dice.new_id() for _ in range(3)]
        with dice.using_rng(dice.new_rng(1)):
            again = [dice.new_id() for _ in range(3)]
        with dice.using_rng(dice.new_rng(2)):
            other = [dice.new_id() for _ in range(3)]

        assert first == again
        assert first != other

    def test_a_seed_that_changes_the_battle_changes_the_result(self):
        # Not every seed pair must differ, but across a spread at least one outcome
        # (winner / rounds / hp fractions) must move — proving the seed governs the fight.
        results = [ga.regenerate_match(DEFAULT_WEIGHTS, SCEN, seed=s) for s in range(6)]
        assert (
            len(
                {
                    (r.winner, r.rounds, tuple(sorted(r.hp_fraction.items())))
                    for r in results
                }
            )
            > 1
        )
