"""The self-play GA: genome ops, fitness, reproducibility, and a small end-to-end run."""

import json
import random

from src.arena.heuristic import ga
from src.arena.heuristic.score import DEFAULT_WEIGHTS, HeuristicWeights


# --- genome operations -------------------------------------------------------


def test_weight_bounds_cover_every_weight_field():
    """A new HeuristicWeights field without a bound here would go un-evolved — guard it."""
    assert set(ga.WEIGHT_BOUNDS) == set(ga.weight_bound_names())


def test_random_weights_within_bounds():
    rng = random.Random(1)
    for _ in range(50):
        w = ga.random_weights(rng)
        for name, (lo, hi) in ga.WEIGHT_BOUNDS.items():
            assert lo <= getattr(w, name) <= hi


def test_crossover_takes_each_gene_from_a_parent():
    a = HeuristicWeights(damage=1, kill=1, exposure=1, engagement=1, friendly_fire=1,
                         control=1, resource=1, aggression=1, end_turn_threshold=0.01)
    b = HeuristicWeights(damage=2, kill=2, exposure=2, engagement=2, friendly_fire=2,
                         control=2, resource=2, aggression=2, end_turn_threshold=0.02)
    child = ga.crossover(a, b, random.Random(3))
    for name in ga.WEIGHT_BOUNDS:
        assert getattr(child, name) in (getattr(a, name), getattr(b, name))


def test_mutate_is_deterministic_and_bounded():
    base = ga.random_weights(random.Random(7))
    first = ga.mutate(base, random.Random(11), rate=1.0, sigma=0.3)
    second = ga.mutate(base, random.Random(11), rate=1.0, sigma=0.3)
    assert first == second  # same rng seed -> same mutation
    for name, (lo, hi) in ga.WEIGHT_BOUNDS.items():
        assert lo <= getattr(first, name) <= hi


# --- fitness -----------------------------------------------------------------


def test_default_weights_beat_the_scripted_yardstick_on_kiting():
    fitness, matches = ga.evaluate(DEFAULT_WEIGHTS, ["kiting"], [1, 2, 3, 4])
    assert all(m["llm_won"] for m in matches)  # the archer kites the bruiser to death
    assert fitness > 1.0  # win (1.0) + positive HP-margin


def test_evaluate_reports_one_record_per_scenario_seed():
    _, matches = ga.evaluate(DEFAULT_WEIGHTS, ["kiting", "alpha_strike"], [1, 2])
    assert len(matches) == 4
    assert {m["scenario"] for m in matches} == {"kiting", "alpha_strike"}


# --- reproducibility ---------------------------------------------------------


def test_match_is_reproducible_from_weights_and_seed():
    """(weights, scenario, seed) fully determines the battle — the log-regeneration promise."""
    a = ga.regenerate_match(DEFAULT_WEIGHTS, "alpha_strike", 42)
    b = ga.regenerate_match(DEFAULT_WEIGHTS, "alpha_strike", 42)
    assert (a.winner, a.rounds, a.hp_fraction) == (b.winner, b.rounds, b.hp_fraction)


# --- end-to-end GA -----------------------------------------------------------


def test_small_ga_run_completes_and_logs(tmp_path):
    log_path = str(tmp_path / "ga.jsonl")
    config = ga.GAConfig(
        scenario_names=("kiting",),
        population_size=6,
        generations=3,
        seeds_per_gen=2,
        processes=1,
        ga_seed=0,
        out_dir=str(tmp_path),
    )
    result = ga.run_ga(config, log_path=log_path)

    assert isinstance(result.best_weights, HeuristicWeights)
    assert result.generations == 3

    records = [json.loads(line) for line in open(log_path, encoding="utf-8")]
    kinds = {r["kind"] for r in records}
    assert {"run_start", "generation", "individual", "champion", "run_end"} <= kinds

    # Every individual of every generation is logged with its full weight vector, fitness,
    # and one match record per (scenario, seed).
    individuals = [r for r in records if r["kind"] == "individual"]
    assert len(individuals) == 6 * 3
    sample = individuals[0]
    assert set(sample["weights"]) == set(ga.WEIGHT_BOUNDS)
    assert len(sample["matches"]) == 1 * 2  # one scenario, two seeds
    assert {"scenario", "seed", "winner", "llm_won", "margin", "rounds", "reason"} <= set(
        sample["matches"][0]
    )


def test_ga_is_reproducible_under_its_seed(tmp_path):
    def run():
        config = ga.GAConfig(
            scenario_names=("kiting",), population_size=5, generations=2,
            seeds_per_gen=2, processes=1, ga_seed=99, out_dir=str(tmp_path),
        )
        return ga.run_ga(config, log_path=str(tmp_path / "r.jsonl")).best_fitness

    assert run() == run()  # same GA seed -> same evolution -> same best fitness
