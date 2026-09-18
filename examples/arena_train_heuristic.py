"""Train HeuristicWeights by self-play GA against the scripted yardstick.

    python -m examples.arena_train_heuristic                 # defaults (parallel)
    python -m examples.arena_train_heuristic --generations 40 --population 64
    python -m examples.arena_train_heuristic --processes 1   # serial

Evolves a weight vector on the benchmark scenarios, prints the champion and how it compares
to the hand-tuned DEFAULT_WEIGHTS on a fresh held-out seed set, and writes a full JSONL log
(every generation, individual, and match outcome) under ``training/``. Any logged match
regenerates exactly from its weights + seed via ``heuristic.ga.regenerate_match``.
"""

import argparse
import multiprocessing
import os
from dataclasses import asdict

from src.arena.heuristic import ga
from src.arena.heuristic.score import DEFAULT_WEIGHTS


def _held_out_fitness(weights, scenario_names, base_seed=10_000, n=12):
    """Mean fitness on a seed set disjoint from any the GA trained on."""
    seeds = [base_seed + i for i in range(n)]
    fitness, _ = ga.evaluate(weights, list(scenario_names), seeds)
    return fitness


def main() -> None:
    parser = argparse.ArgumentParser(description="Self-play GA for HeuristicWeights.")
    parser.add_argument("--population", type=int, default=48)
    parser.add_argument("--generations", type=int, default=20)
    parser.add_argument("--seeds-per-gen", type=int, default=6)
    parser.add_argument("--processes", type=int, default=os.cpu_count() or 1)
    parser.add_argument("--ga-seed", type=int, default=0)
    parser.add_argument(
        "--scenarios", nargs="+",
        default=["kiting", "alpha_strike", "protect_squishy"],
    )
    args = parser.parse_args()

    config = ga.GAConfig(
        scenario_names=tuple(args.scenarios),
        population_size=args.population,
        generations=args.generations,
        seeds_per_gen=args.seeds_per_gen,
        processes=args.processes,
        ga_seed=args.ga_seed,
    )
    print(f"Training: pop={config.population_size} gens={config.generations} "
          f"seeds/gen={config.seeds_per_gen} procs={config.processes} "
          f"scenarios={list(config.scenario_names)}")

    result = ga.run_ga(config)

    print(f"\n=== Done in {result.generations} generations ===")
    print(f"Log: {result.log_path}")
    print(f"Champion fitness (its own generation's seeds): {result.best_fitness:.4f}")

    # Fair comparison on a fresh, held-out seed set neither the GA nor the baseline saw.
    base = _held_out_fitness(DEFAULT_WEIGHTS, config.scenario_names)
    champ = _held_out_fitness(result.best_weights, config.scenario_names)
    print("\nHeld-out fitness (fresh seeds):")
    print(f"  hand-tuned default: {base:.4f}")
    print(f"  evolved champion:   {champ:.4f}  ({'+' if champ >= base else ''}{champ - base:.4f})")

    print("\nChampion weights:")
    for name, value in asdict(result.best_weights).items():
        print(f"  {name:20s} {value:.4f}")


if __name__ == "__main__":
    multiprocessing.freeze_support()  # safe no-op except on frozen Windows builds
    main()
