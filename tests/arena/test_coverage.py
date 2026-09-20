"""Interface completeness, measured across match states rather than one frame.

The distinction this file exists to enforce: coverage measured at a scenario's opening
position is coverage of *the configuration its designer arranged*, which is the least
representative board in the match. Sampling across real formations changed the area
figure from "100%, lossless" to "75% at worst" — and that difference is the whole
content of H4's area arm.
"""

import pytest

from src.arena.action_space import move_coverage
from src.arena.coverage import CoverageDistribution, sample_coverage
from src.arena.scenarios import SCENARIOS

from .conftest import force_turn


def _at_turn(scenario_name, entity_id):
    combat = SCENARIOS[scenario_name].build()
    combat.start_combat()
    entity = next(e for e in combat.combatants if e.entity_id == entity_id)
    force_turn(combat, entity)
    return combat, entity


# -- movement coverage: H4's live arm ----------------------------------------


def test_named_destinations_do_not_span_the_movement_space():
    """The finding that makes H4 worth testing at all.

    Three named destinations per enemy cannot express every distinct tactical
    position, so the enumerated condition really does give something up here — unlike
    the area menu, which turned out outcome-complete at the opening and near-complete
    in play.
    """
    combat, entity = _at_turn("protect_squishy", "sharpshooter")
    coverage = move_coverage(combat, entity)

    assert coverage.achievable > coverage.offered
    assert coverage.coverage < 1.0
    assert coverage.missing, "a shortfall with nothing named is not actionable"


def test_coverage_names_the_classes_it_missed():
    combat, entity = _at_turn("protect_squishy", "sharpshooter")
    coverage = move_coverage(combat, entity)

    assert coverage.achievable - coverage.offered == len(coverage.missing)
    for entry in coverage.missing:
        assert any(part.startswith("attack:") for part in entry)
        assert any(part.startswith("threatened:") for part in entry)


def test_standing_still_is_always_an_available_class():
    """Holding position is a real option and must never count as unreachable."""
    combat, entity = _at_turn("kiting", "archer")
    assert move_coverage(combat, entity).offered >= 1


def test_measuring_coverage_leaves_the_board_untouched():
    """It probes positions by moving the entity; a leak would corrupt the match."""
    combat, entity = _at_turn("alpha_strike", "fighter-a1")
    before = [(e.entity_id, e.x, e.y, e.z, e.current_hp) for e in combat.combatants]

    move_coverage(combat, entity)

    assert [
        (e.entity_id, e.x, e.y, e.z, e.current_hp) for e in combat.combatants
    ] == before


def test_an_entity_that_cannot_move_has_only_its_current_class():
    combat, entity = _at_turn("kiting", "archer")
    entity.resources.movement = 0.0

    coverage = move_coverage(combat, entity)
    assert coverage.achievable == 1
    assert coverage.coverage == 1.0


# -- the distribution --------------------------------------------------------


def test_the_opening_frame_overstates_area_coverage():
    """Registering the opening figure would have been registering a lucky frame.

    At the opening the aim menu is outcome-complete (9/9). Once the scripted match
    moves people about it is not — which is exactly the sort of thing a single-frame
    claim hides, and the reason the registered number is a minimum.
    """
    distribution = sample_coverage(SCENARIOS["aoe_placement"].build, seeds=range(2))
    aim = distribution["aim"]

    assert aim.n > 1
    assert aim.minimum < 1.0
    assert aim.minimum <= aim.median
    assert aim.worst_at and "round" in aim.worst_at


def test_the_distribution_reports_where_the_worst_case_was():
    """ "75%" is an argument; "75% at seed2:round1:mage" is something to go and look
    at."""
    distribution = sample_coverage(SCENARIOS["aoe_placement"].build, seeds=range(2))

    for axis in ("aim", "move"):
        if distribution[axis].n:
            assert distribution[axis].worst_at


def test_movement_is_sampled_for_every_scenario():
    for name in ("kiting", "alpha_strike"):
        distribution = sample_coverage(
            SCENARIOS[name].build, seeds=range(1), round_cap=2
        )
        assert distribution["move"].n > 0
        assert 0.0 < distribution["move"].minimum <= 1.0


def test_a_scenario_with_no_area_spell_reports_no_aim_samples():
    distribution = sample_coverage(
        SCENARIOS["kiting"].build, seeds=range(1), round_cap=1
    )
    assert distribution["aim"].n == 0


def test_an_empty_distribution_does_not_divide_by_zero():
    empty = CoverageDistribution([])
    assert empty.minimum == 1.0
    assert empty.median == 1.0
    assert empty.to_dict()["n"] == 0


def test_the_distribution_serialises_for_the_record():
    data = CoverageDistribution([0.5, 0.75, 1.0], worst_at="seed0:round1:x").to_dict()
    assert data == {"n": 3, "min": 0.5, "median": 0.75, "worst_at": "seed0:round1:x"}


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_sampling_is_deterministic(name):
    """The registered number must not move between runs."""
    first = sample_coverage(SCENARIOS[name].build, seeds=range(1), round_cap=2)
    second = sample_coverage(SCENARIOS[name].build, seeds=range(1), round_cap=2)

    for axis in ("aim", "move"):
        assert first[axis].samples == second[axis].samples
