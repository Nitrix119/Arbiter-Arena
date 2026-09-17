# A Strong, Tunable Heuristic Opponent — Plan & Thoughts

> **Purpose.** Design notes for replacing the naive `ScriptedAgent` with a *good* — ideally
> nasty — generic heuristic: the fixed, deterministic yardstick that LLMs are benchmarked
> against (see [AGENT_ARENA_PLAN.md](../current/AGENT_ARENA_PLAN.md), [AGENT_ARENA_DECISIONS.md](AGENT_ARENA_DECISIONS.md)).
> This captures the plan and my reasoning; nothing here is built yet. Recorded at the user's
> request as the end-of-session note for the heuristic work.
>
> **Companion:** this doc settles the *strategy* (scoring policy + GA); the precise *mechanism* —
> what unit is scored, over what candidate set, with what EV math and factors — is worked out in
> [HEURISTIC_DECISION_MODEL.md](../current/HEURISTIC_DECISION_MODEL.md).

---

## 0. Goal, in one breath

A **utility-scoring** policy that plays *any* stat block pragmatically — no per-creature
special-casing — is **legal by construction**, **deterministic**, and **cheap** (thousands of
matches/hour, no network). Its behaviour is governed by a vector of **weights** (damage vs
kills vs healing vs status vs positioning vs resource-conservation…), which can be hand-tuned
and then optimised by **self-play with a genetic algorithm** until it's respectably mean. Not
perfection — a predictable, competent bruiser we can throw at arbitrary entities.

## 1. Why the current heuristic isn't enough

`ScriptedAgent` is a fixed if/elif ladder ("attack lowest-HP reachable enemy, else move to
nearest, else end"). This session surfaced concrete failures:

- **Gets stuck moving into occupied space.** In the 2v2 (`alpha_strike`) it repeatedly targets
  a standoff point already occupied by a third body, the referee rejects it, and turns are
  wasted to the round cap — the *same* mistake the weak LLM made. (It doesn't check the
  destination against other entities.)
- **Can't kite.** A ranged attacker it controls just walks into melee.
- **Targets by raw HP, not threat.** It'll chip the tank instead of deleting the glass cannon.
- **No resource sense.** It has no notion of saving a big spell slot or securing a kill.

A priority ladder can't be tuned or generalised. A **scoring function** can.

## 2. Architecture — a utility-scoring agent

`HeuristicAgent(Agent)` whose `decide()` does:

1. **Enumerate candidate actions** from the observation's legal menu
   ([`legal_actions`](../../src/arena/action_space.py) already gives affordable, in-range
   attacks/spells + movement budget). Add a small, **discretised** set of move candidates
   (toward / away from each enemy; to melee standoff; to a ranged "preferred distance"; a
   flank) — movement is continuous feet, so we score a handful of sensible destinations rather
   than optimise over the plane. **Every candidate is legal** (overlap/range checked up front),
   so the agent never needs the failure budget — illegal-move rate ≈ 0 by construction.
2. **Score each candidate** = weighted sum of features (§3).
3. **Pick the argmax**, with a deterministic tie-break (e.g. by `entity_id`) so replays
   reproduce. End the turn when no candidate scores above an `end_turn_threshold`.

This drops cleanly onto the existing `Agent` seam — no engine or `run_match` changes. It reads
capabilities off the entity (attacks, `known_spells`, resources), never branches on a name
(CLAUDE.md §2.2), so it's generic.

## 3. Feature set (the things we score)

Mapping the user's list — damage / kills / healing / status / other:

| Feature | Rough value |
|---|---|
| **Expected damage** | `hit_chance × avg_damage` (from the damage formula, to-hit vs known AC). The backbone. |
| **Secure a kill** | large bonus when `EV ≥ target.hp_remaining` — removing a combatant deletes its whole action economy. |
| **Overkill waste** | penalty for damage far beyond what kills (spend it elsewhere). |
| **Threat-weighted targeting** | prefer high-output / low-effort-to-kill / dangerous-ability targets over raw lowest-HP. |
| **Healing** | HP restored × ally endangerment (heal the ally about to drop, ignore scratches). |
| **Status / control** | per-condition severity table (stun/paralyse ≫ prone ≫ minor); data-driven, extensible. |
| **Positioning** | reach a high-EV target; hold *preferred range* (ranged wants distance = kiting, melee wants adjacency); avoid being surrounded; AoE placement (hit many, spare allies). |
| **Resource economy** | penalty for spending a scarce/high-level slot or limited-use/legendary ability, scaled by scarcity — saves the big guns for when they pay off. |
| **Self-preservation** | when low and outmatched, value disengage/retreat (tunable aggression). |
| **End turn** | a threshold so it doesn't burn actions on near-zero-value moves. |

The **hard** features are positioning and control — see §6.

## 4. Tunable weights = the GA genome

A frozen `HeuristicWeights` dataclass of floats: `damage`, `kill_bonus`, `overkill_penalty`,
`threat`, `heal`, `heal_urgency`, `status`, `positioning`, `kite_bias`,
`resource_conservation`, `aggression`, `end_turn_threshold`, … The default is **hand-set** to
something already competent; the GA then searches for a nastier vector.

**Self-play GA (offline, pure engine — no LLM, no tokens):**
- Population of weight vectors; **fitness = win-rate** over many seeds *and* several
  scenarios/rosters (so it generalises, not overfits one map), with tie-breakers: HP margin,
  turns-to-win.
- Tournament selection + blend/uniform crossover + Gaussian mutation + elitism; seeded GA RNG
  for reproducibility.
- Runs for hours on the user's PC: `run_match` is fast and deterministic, so thousands of games
  per generation are feasible.

## 5. Fitness design — avoid the self-play traps

- **Anchor the fitness.** Pure self-play chases its own tail (strategy cycling, overfitting the
  current population). Always include **fixed opponents** — today's `ScriptedAgent` (weak) and
  `RandomAgent` (floor) — plus a **hall of fame** of past champions, so fitness has an absolute
  reference, not just relative.
- **Diverse evaluation.** Randomise rosters (HP/AC/damage/reach/speed within ranges) and rotate
  scenarios, or the weights overfit one matchup.
- **Generalisation is the objective**, not peak play on one map — that's the "throw it at
  arbitrary entities" requirement.
- Metrics we already log (win-rate, HP-remaining, turns-to-win) feed fitness directly from
  transcripts — no bespoke instrumentation.

## 6. The real risk: features > optimiser, and myopia

- **A GA can't invent tactics the features can't express.** Getting the *feature set* right is
  the hard part; the optimiser only weights what's there.
- **Greedy one-action-at-a-time scoring is myopic.** Some skills are inherently multi-step —
  kiting is "attack *then* retreat"; a myopic scorer may not value the retreat. Two cheap
  mitigations: (a) an explicit **"maintain preferred range"** positioning feature (so a ranged
  agent is rewarded for ending its turn out of enemy reach), and/or (b) a shallow **1-ply
  lookahead** (does this action let an enemy reach me next turn?). Full search is overkill.
- **Team coordination.** The heuristic controls a whole team; naive per-creature scoring won't
  focus-fire. A cheap fix: a shared per-turn **"focus target"** (the team agrees on the
  best kill target and everyone weights it up) — captures most of the `alpha_strike` skill.
- **Hidden information.** Under a restrictive `InformationPolicy` (no enemy HP/AC), the scorer
  must fall back to estimates (assume a default AC; treat unknown HP as full or bucketed). How
  well it copes is itself an interesting axis.

## 7. Build order

1. ✅ **`HeuristicAgent` with hand-set weights** that already fix the known flaws: legal-only move
   candidates (kills the stuck-on-occupied bug), preferred-range positioning (kiting),
   threat-weighted targeting, kill-securing, resource conservation. This alone is a far better
   yardstick and unblocks `alpha_strike`. Keep `ScriptedAgent` as the *weak* baseline and
   `RandomAgent` as the floor — a three-rung ladder. _(Built — `src/arena/heuristic/`, Phases A–C;
   see [HEURISTIC_DECISION_MODEL.md](../current/HEURISTIC_DECISION_MODEL.md).)_
2. ✅ **Parameterise weights + a headless self-play GA harness** — `src/arena/heuristic/ga.py`
   (`python -m examples.arena_train_heuristic`). Fitness = an individual playing each scenario's
   *skill* side against the fixed `ScriptedAgent` (O(pop × scenarios × seeds), not all-pairs);
   generation-shared seeds for fairness; tournament + uniform crossover + Gaussian mutation +
   elitism, `DEFAULT_WEIGHTS` seeded into gen 0; multiprocessing over individuals. Thorough JSONL
   logging (every generation / individual / weights / seed / match outcome); battles regenerate
   from `(weights, seed)` via `regenerate_match` (deterministic entity ids + seeded dice), so the
   blow-by-blow is never logged.
3. **Freeze a tuned "nasty" weight-set** as the default benchmark opponent; keep the GA harness
   for re-tuning as the engine grows.

## 8. Constraints (carry these into implementation)

- **Generic, never name-based** — read capabilities off the entity (CLAUDE.md §2.2).
- **Legal by construction** — score only legal actions; the heuristic should never trip the
  failure budget (unlike an LLM).
- **Deterministic** — seeded, stable tie-breaks, so seeded matches replay exactly.
- **Cheap & offline** — the whole point is that the GA can run millions of engine-only games.
- **Fold-back** — the tuned agent becomes the fixed yardstick; scoring work (win-rate,
  illegal-move rate, etc.) lands first so we can *measure* "nastier".

## 9. My honest take

The GA is the fun part but not where the difficulty lives — a **well-chosen feature set with
carefully hand-tuned weights will already be "respectably mean"**, and I'd get that working and
benchmarked *before* spending PC-hours evolving. The optimiser then squeezes the last 10–20% and
occasionally finds a non-obvious weighting (e.g. how much to over-value kills, or how much
kite-bias is too much). Sequence: **scoring/metrics → hand-tuned `HeuristicAgent` → GA.** The
myopia around multi-step positioning is the thing most likely to disappoint; the preferred-range
feature is the cheapest strong lever against it.
