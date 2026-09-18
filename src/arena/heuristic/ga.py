"""A self-play genetic algorithm that tunes :class:`HeuristicWeights`.

The genome is a weight vector; fitness is how well a :class:`HeuristicAgent` carrying it
plays the *skill* side of the benchmark scenarios (:data:`~src.arena.scenarios.SCENARIOS`)
against the fixed :class:`~src.arena.agent.ScriptedAgent` yardstick. Evaluating against a
**fixed** opponent (not every other individual) keeps a generation O(pop × scenarios ×
seeds), not O(pop²) — the efficiency the all-pairs duel would lose — and anchors fitness to
an absolute reference (HEURISTIC_PLAN §5).

Design choices baked in here (all tunable via :class:`GAConfig`):

* **Fairness by shared seeds.** Every individual in a generation is evaluated on the *same*
  list of seeds, drawn fresh each generation from the GA's own RNG — a paired comparison
  (low variance), and new seeds each generation so weights generalise rather than overfit.
* **Reproducible battles.** Each match assigns deterministic entity ids and seeds the dice,
  so ``(weights, scenario, seed)`` fully determines the battle — the exact fight can be
  regenerated (:func:`regenerate_match`) without logging its blow-by-blow.
* **Parallel.** Individuals are evaluated across processes (the engine is fast and the GIL
  would otherwise bottleneck); ``processes <= 1`` runs serially (used by the test suite).
* **Thorough logging.** Every generation, every individual's full weight vector and
  fitness, and every match's seed and outcome are written to a JSONL log. Blow-by-blow
  battle logs are *not* logged — they regenerate from weights + seed.
"""

from __future__ import annotations

import json
import os
import random
from dataclasses import asdict, dataclass, fields as dataclass_fields
from datetime import datetime
from multiprocessing import Pool
from typing import cast, Dict, List, Optional, Tuple, TYPE_CHECKING

from src.arena.agent import Agent, ScriptedAgent
from src.arena.match import run_match
from src.arena.scenarios import SCENARIOS
from src.utils import dice

from .agent import HeuristicAgent
from .score import DEFAULT_WEIGHTS, HeuristicWeights

if TYPE_CHECKING:
    from src.arena.match import MatchResult
    from src.arena.transcript import Transcript

# Per-gene ranges for random initialisation and mutation clamping. Must name exactly the
# fields of HeuristicWeights — tests/arena/test_heuristic_ga.py checks that, so a new weight
# without a bound here is caught rather than silently un-evolved.
WEIGHT_BOUNDS: Dict[str, Tuple[float, float]] = {
    "damage": (0.0, 3.0),
    "kill": (0.0, 3.0),
    "exposure": (0.0, 3.0),
    "engagement": (0.0, 3.0),
    "friendly_fire": (0.0, 4.0),
    "control": (0.0, 3.0),
    "resource": (0.0, 2.0),
    "aggression": (0.1, 3.0),
    "end_turn_threshold": (0.0, 0.2),
}

# Fitness composition. Win-rate dominates; the margin and speed terms only break ties
# between equal win-rates (their magnitudes can never flip a win above a loss).
DRAW_SCORE = 0.5
MARGIN_WEIGHT = 0.3  # reward remaining-HP margin (in [-1, 1])
SPEED_WEIGHT = 0.005  # mild preference for faster wins (rounds)


# ---------------------------------------------------------------------------
# Genome operations
# ---------------------------------------------------------------------------


def random_weights(rng: random.Random) -> HeuristicWeights:
    """A weight vector with each gene drawn uniformly from its bound."""
    return HeuristicWeights(
        **{k: rng.uniform(lo, hi) for k, (lo, hi) in WEIGHT_BOUNDS.items()}
    )


def _clamp(name: str, value: float) -> float:
    lo, hi = WEIGHT_BOUNDS[name]
    return min(hi, max(lo, value))


def crossover(
    a: HeuristicWeights, b: HeuristicWeights, rng: random.Random
) -> HeuristicWeights:
    """Uniform crossover: each gene taken from one parent or the other at random."""
    return HeuristicWeights(
        **{
            k: (getattr(a, k) if rng.random() < 0.5 else getattr(b, k))
            for k in WEIGHT_BOUNDS
        }
    )


def mutate(
    weights: HeuristicWeights, rng: random.Random, *, rate: float, sigma: float
) -> HeuristicWeights:
    """Gaussian mutation: perturb each gene with probability *rate*, clamped to its bound."""
    out: Dict[str, float] = {}
    for name, (lo, hi) in WEIGHT_BOUNDS.items():
        value = getattr(weights, name)
        if rng.random() < rate:
            value = _clamp(name, value + rng.gauss(0.0, sigma * (hi - lo)))
        out[name] = value
    return HeuristicWeights(**out)


# ---------------------------------------------------------------------------
# Fitness evaluation
# ---------------------------------------------------------------------------


def _play(
    weights: HeuristicWeights,
    scenario_name: str,
    seed: int,
    *,
    transcript: Optional["Transcript"] = None,
) -> "MatchResult":
    scenario = SCENARIOS[scenario_name]
    # Build entities under the seed so their ids are reproducible too (ids feed Entity
    # hashing and tie-breaks). run_match then reseeds combat.rng for the roll stream, so
    # ``(weights, scenario, seed)`` fully determines the fight — no id-stabilising patch.
    with dice.using_rng(dice.new_rng(seed)):
        combat = scenario.build()
    agents: Dict[Optional[str], Agent] = {
        scenario.llm_team: HeuristicAgent(
            "candidate", scenario.llm_team, combat, weights=weights
        ),
        scenario.heuristic_team: ScriptedAgent("yardstick", scenario.heuristic_team),
    }
    return run_match(combat, agents, seed=seed, transcript=transcript)


def _match_record(
    weights: HeuristicWeights, scenario_name: str, seed: int
) -> Dict[str, object]:
    scenario = SCENARIOS[scenario_name]
    result = _play(weights, scenario_name, seed)
    llm_hp = result.hp_fraction.get(scenario.llm_team, 0.0)
    heur_hp = result.hp_fraction.get(scenario.heuristic_team, 0.0)
    return {
        "scenario": scenario_name,
        "seed": seed,
        "winner": result.winner,
        "llm_won": result.winner == scenario.llm_team,
        "margin": llm_hp - heur_hp,
        "rounds": result.rounds,
        "reason": result.reason,
    }


def _match_score(match: Dict[str, object]) -> float:
    if match["llm_won"]:
        base = 1.0
    elif match["winner"] is None:
        base = DRAW_SCORE
    else:
        base = 0.0
    margin = cast(float, match["margin"])
    rounds = cast(int, match["rounds"])
    return base + MARGIN_WEIGHT * margin - SPEED_WEIGHT * rounds


def evaluate(
    weights: HeuristicWeights, scenario_names: List[str], seeds: List[int]
) -> Tuple[float, List[Dict[str, object]]]:
    """Play every ``(scenario, seed)`` and return ``(mean fitness, per-match records)``."""
    matches = [
        _match_record(weights, name, seed) for name in scenario_names for seed in seeds
    ]
    fitness = sum(_match_score(m) for m in matches) / len(matches) if matches else 0.0
    return fitness, matches


def _evaluate_task(
    args: Tuple[HeuristicWeights, List[str], List[int]],
) -> Tuple[float, List[Dict[str, object]]]:
    """Top-level worker (picklable) so a process Pool can map individuals across cores."""
    weights, scenario_names, seeds = args
    return evaluate(weights, scenario_names, seeds)


def regenerate_match(
    weights: HeuristicWeights,
    scenario_name: str,
    seed: int,
    *,
    transcript: Optional["Transcript"] = None,
) -> "MatchResult":
    """Replay the exact battle a logged ``(weights, scenario, seed)`` produced.

    Because ids are stabilised and the dice are seeded, this reproduces the recorded
    outcome — pass a :class:`~src.arena.transcript.Transcript` to capture the blow-by-blow
    that the GA log deliberately omits.
    """
    return _play(weights, scenario_name, seed, transcript=transcript)


# ---------------------------------------------------------------------------
# The GA loop
# ---------------------------------------------------------------------------


@dataclass
class GAConfig:
    """Knobs for a training run (all easy to tune later)."""

    scenario_names: Tuple[str, ...] = ("kiting", "alpha_strike", "protect_squishy")
    population_size: int = 48
    generations: int = 20
    seeds_per_gen: int = 6
    tournament_k: int = 3
    elitism: int = 3
    mutation_rate: float = 0.3
    mutation_sigma: float = 0.15
    processes: int = 0  # <= 1 runs serially; > 1 uses a process Pool
    ga_seed: int = 0
    seed_the_default: bool = (
        True  # seed generation 0 with the hand-tuned DEFAULT_WEIGHTS
    )
    out_dir: str = "training"


@dataclass
class GAResult:
    best_weights: HeuristicWeights
    best_fitness: float
    generations: int
    log_path: str


def run_ga(config: GAConfig, *, log_path: Optional[str] = None) -> GAResult:
    """Evolve weights for ``config.generations`` and return the best-ever individual.

    Logs every generation, individual (full weights + fitness), and match (seed + outcome)
    to a JSONL file. The champion is the best individual by its own generation's fitness;
    because elites are re-evaluated on each generation's fresh seeds, a champion earns its
    place on new dice rather than lucky ones.
    """
    rng = random.Random(config.ga_seed)
    population = _init_population(config, rng)
    logger = _RunLogger(config, log_path)
    champion: Optional[Tuple[HeuristicWeights, float, int]] = None
    try:
        logger.run_start()
        for gen in range(config.generations):
            seeds = [rng.randrange(2**31) for _ in range(config.seeds_per_gen)]
            logger.generation(gen, seeds)

            evaluated = _evaluate_population(population, config, seeds)
            for index, (weights, fitness, matches) in enumerate(evaluated):
                logger.individual(gen, index, weights, fitness, matches)

            evaluated.sort(key=lambda item: item[1], reverse=True)
            best_weights, best_fitness, _ = evaluated[0]
            if champion is None or best_fitness > champion[1]:
                champion = (best_weights, best_fitness, gen)
            logger.champion(gen, best_weights, best_fitness)

            population = _next_generation(evaluated, config, rng)

        assert champion is not None  # generations >= 1
        logger.run_end(champion[0], champion[1])
        return GAResult(champion[0], champion[1], config.generations, logger.path)
    finally:
        logger.close()


def _init_population(config: GAConfig, rng: random.Random) -> List[HeuristicWeights]:
    population: List[HeuristicWeights] = []
    if config.seed_the_default:
        population.append(DEFAULT_WEIGHTS)
    while len(population) < config.population_size:
        population.append(random_weights(rng))
    return population


def _evaluate_population(
    population: List[HeuristicWeights], config: GAConfig, seeds: List[int]
) -> List[Tuple[HeuristicWeights, float, List[Dict[str, object]]]]:
    tasks = [(w, list(config.scenario_names), seeds) for w in population]
    if config.processes and config.processes > 1:
        with Pool(processes=config.processes) as pool:
            results = pool.map(_evaluate_task, tasks)
    else:
        results = [_evaluate_task(task) for task in tasks]
    return [
        (population[i], results[i][0], results[i][1]) for i in range(len(population))
    ]


def _next_generation(
    evaluated: List[Tuple[HeuristicWeights, float, List[Dict[str, object]]]],
    config: GAConfig,
    rng: random.Random,
) -> List[HeuristicWeights]:
    """Elitism + tournament selection + crossover + mutation. ``evaluated`` is sorted desc."""
    nxt: List[HeuristicWeights] = [
        weights for weights, _, _ in evaluated[: config.elitism]
    ]
    while len(nxt) < config.population_size:
        p1 = _tournament(evaluated, config.tournament_k, rng)
        p2 = _tournament(evaluated, config.tournament_k, rng)
        child = mutate(
            crossover(p1, p2, rng),
            rng,
            rate=config.mutation_rate,
            sigma=config.mutation_sigma,
        )
        nxt.append(child)
    return nxt


def _tournament(
    evaluated: List[Tuple[HeuristicWeights, float, List[Dict[str, object]]]],
    k: int,
    rng: random.Random,
) -> HeuristicWeights:
    contenders = [rng.choice(evaluated) for _ in range(k)]
    return max(contenders, key=lambda item: item[1])[0]


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


class _RunLogger:
    """Appends typed JSONL records; one file per run, flushed after every write."""

    def __init__(self, config: GAConfig, path: Optional[str]) -> None:
        os.makedirs(config.out_dir, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.path = path or os.path.join(config.out_dir, f"ga_{stamp}.jsonl")
        self._config = config
        self._file = open(self.path, "w", encoding="utf-8")

    def _write(self, record: Dict[str, object]) -> None:
        self._file.write(json.dumps(record) + "\n")
        self._file.flush()

    def run_start(self) -> None:
        self._write({"kind": "run_start", "config": asdict(self._config)})

    def generation(self, gen: int, seeds: List[int]) -> None:
        self._write({"kind": "generation", "gen": gen, "seeds": seeds})

    def individual(
        self,
        gen: int,
        index: int,
        weights: HeuristicWeights,
        fitness: float,
        matches: List[Dict[str, object]],
    ) -> None:
        self._write(
            {
                "kind": "individual",
                "gen": gen,
                "index": index,
                "weights": asdict(weights),
                "fitness": fitness,
                "matches": matches,
            }
        )

    def champion(self, gen: int, weights: HeuristicWeights, fitness: float) -> None:
        self._write(
            {
                "kind": "champion",
                "gen": gen,
                "weights": asdict(weights),
                "fitness": fitness,
            }
        )

    def run_end(self, weights: HeuristicWeights, fitness: float) -> None:
        self._write({"kind": "run_end", "weights": asdict(weights), "fitness": fitness})

    def close(self) -> None:
        if not self._file.closed:
            self._file.close()


def weight_bound_names() -> Tuple[str, ...]:
    """The HeuristicWeights field names, for the drift guard in the tests."""
    return tuple(f.name for f in dataclass_fields(HeuristicWeights))
