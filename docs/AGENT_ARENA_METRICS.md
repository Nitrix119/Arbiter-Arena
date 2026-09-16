# Agent Arena — Benchmark Metrics (design catalogue)

> **Purpose.** A deliberately *broad* catalogue of metrics for benchmarking how well an
> agent (LLM or scripted policy) plays 5e combat in the arena. This is a **design
> document to scrutinise and trim**, not a build spec — right now more candidate metrics
> are better; we will cut and sharpen later. Read alongside
> [AGENT_ARENA_PLAN.md](AGENT_ARENA_PLAN.md) (the harness), [HEURISTIC_PLAN.md](HEURISTIC_PLAN.md)
> (the yardstick opponent), and the 2026-09-15 diagnostic findings that motivate several of
> these. The **batch runner that would aggregate these across many matches is deliberately
> out of scope here** — this doc defines *what we measure*; a later doc defines *how we run
> enough matches to measure it*.

---

## 0. What we learned that shapes these metrics

The first live diagnostic (2026-09-15, three scenarios) taught three lessons that the whole
catalogue is built around:

1. **Win/loss is not skill.** `protect_squishy` scored a *win* while the unit it was meant to
   protect died — the tank brute-forced it. A benchmark that reports only win-rate rewards the
   wrong thing. → We need **objective- and process-level metrics**, not just outcomes.
2. **Protocol failure must be separated from tactical failure.** A model that loses because it
   emits invalid tool calls is failing at a *different* thing than one that loses tactically. →
   **Conformance metrics** are reported as a distinct family and used to *gate* the tactical ones.
3. **Single matches are high variance.** The environment is seeded and reproducible; the model is
   not. → Every metric is defined *per match* but only *meaningful in aggregate* over many seeds,
   with an explicit spread, and ideally **normalised against the fixed heuristic yardstick**.

---

## 1. Principles for a good metric here

- **Computed from the transcript, never by re-running the model** (E2). The JSONL transcript is
  already benchmark-grade — see [§9](#9-transcript-fields-each-metric-reads) for the exact record
  shapes each metric reads.
- **Deterministic and replayable.** A metric run twice on the same transcript yields the same
  number. No randomness in scoring.
- **Separable by family.** Conformance ≠ outcome ≠ tactical quality. Never blend them into one
  score; a reader must be able to see *why* a model ranks where it does.
- **Normalised or baseline-relative wherever possible.** Raw "damage dealt" depends on the roster;
  "damage dealt vs. what the heuristic dealt in the same seed" is comparable across scenarios. Many
  tactical metrics are only interpretable **relative to the heuristic yardstick** or **normalised
  per action / per available opportunity**.
- **Aggregated with a spread, not just a mean** ([§8](#8-aggregation--reporting)). A mean win-rate
  with no confidence interval is a trap given the variance.
- **Honest about what the engine models.** Some metrics need mechanics not yet simulated (reactions,
  concentration, cover); those are catalogued but flagged **needs-engine-support**
  ([§10](#10-deferred--needs-engine-support)).

Each metric below states three things, as requested: **Quantifies** (what it measures),
**Why** (why it matters for benchmarking), and **How measured & tested** (the computation from
transcript fields, the validation test, and — where relevant — the scenario that exercises it).

---

## 2. Family A — Conformance & protocol

*Can the model operate the harness at all? These gate the tactical families: a model with a high
illegal-action rate has tactical scores that are noise. Report these first, always.*

### A1. Illegal-action rate
- **Quantifies:** fraction of the model's tool calls the referee rejected (`result.ok == false`),
  per turn and per match; optionally split by tool (`move` / `attack` / `cast_spell`).
- **Why:** the dominant confound the 2026-09-15 diagnostic exposed (12/31/37 illegal moves per
  match). A benchmark that ignores it measures coordinate-guessing luck. With legal move candidates
  now offered, residual illegal actions signal a model that ignores the menu or mishandles the schema.
- **How measured & tested:** count `action` records with `result.ok == false` ÷ total `action`
  records. Validation: a hand-built transcript with a known mix of ok/rejected calls asserts the
  exact rate. Exercised by any scenario; most visible in crowded (2v2+) fights.

### A2. Protocol-failure (no-tool-call) rate
- **Quantifies:** how often the model returned no parseable tool call (prose only), surfaced as the
  `NoToolCallError` path / `(no_tool_call)` action.
- **Why:** distinct from an *illegal* call — it's a failure to use the tool interface at all, a pure
  conformance defect that says nothing about tactics. Weak/free models do this (seen in the
  diagnostic); it must not be scored as a tactical loss.
- **How measured & tested:** count actions whose rejection reason is the no-tool-call sentinel ÷
  total decisions. Test: a mock agent that returns `None` once per turn produces a known rate.

### A3. Forfeit / budget-exhaustion rate
- **Quantifies:** fraction of *turns* auto-ended by the failure budget (3 consecutive / 5 total
  failures) and fraction of *matches* effectively lost to protocol breakdown rather than combat.
- **Why:** a turn burned to the failure budget is a wasted turn that hands initiative to the
  opponent — a loss cause we must attribute to conformance, not tactics. Lets us report "model X
  lost 40% of its matches to forfeits, not play."
- **How measured & tested:** from `turn_end`/driver outcome, count `forced_end` turns; a match is a
  "protocol loss" when the losing side's forced-end turns exceed a threshold. Test: the existing
  failure-budget turn-driver fixtures already produce known `forced_end` outcomes; assert the metric
  over a transcript built from them.

### A4. Self-correction rate
- **Quantifies:** of illegal/rejected actions, the fraction where the model's *next* action in the
  same turn was legal (it read the `rejected_actions` feedback and adapted) vs. repeated the same
  mistake.
- **Why:** measures whether a model can *use referee feedback* — a core agentic competence separate
  from getting it right first time. A model that never repeats a rejected move is robust even if it
  fumbles occasionally.
- **How measured & tested:** walk each turn's action sequence; for every rejected action, check
  whether the subsequent action succeeded (and was different). Test: a scripted sequence
  reject→success vs reject→same-reject gives 100% vs 0%.

### A5. Wasted-action ratio (turn efficiency)
- **Quantifies:** rejected actions ÷ total actions within a turn, i.e. how much of the model's
  decision budget was spent on moves that did nothing.
- **Why:** even self-corrected turns are inefficient if they take five tries; this captures the
  *cost* of fumbling, which in a real (reaction-enabled) game would be punished harder.
- **How measured & tested:** per-turn ratio, averaged over the match. Test: hand-built turn with
  k rejects and m successes asserts k/(k+m).

### A6. Invalid-target rate (sub-type of A1)
- **Quantifies:** rejected/degenerate actions aimed at an illegal or pointless target: a dead
  entity, an out-of-range target, or (menu-only friendly-fire) an *ally* weapon-attacked.
- **Why:** target confusion is a specific, diagnosable failure distinct from spatial illegality;
  friendly-fire in particular is a red flag the diagnostic caught (A2 attacked A1). Since the referee
  permits a raw ally attack, this metric is how we *see* it happening.
- **How measured & tested:** classify each attack/spell action by target relation (from the roster
  in `match_start`) and target liveness (from the latest `turn_end` snapshot). Test: a transcript
  with a logged ally-attack and a dead-target attack asserts both are counted.

---

## 3. Family B — Outcome & efficiency of victory

*Did it win, how decisively, how fast? The classic layer — necessary but, per lesson 1,
insufficient alone.*

### B1. Win rate
- **Quantifies:** fraction of matches the agent's team won, over many seeds (and, in symmetric
  scenarios, over both side assignments).
- **Why:** the headline benchmark number; the ultimate integrator of skill *when the opponent and
  roster are held fixed*. Only meaningful in aggregate with a confidence interval.
- **How measured & tested:** `match_end.winner == agent's team`, aggregated. Test: a set of
  transcripts with known winners asserts the rate and its Wilson interval.

### B2. Stalemate / round-cap rate
- **Quantifies:** fraction of matches that hit the round cap with both sides alive (`reason ==
  "round_cap"`) rather than ending by a kill (`last_standing`).
- **Why:** a high stalemate rate means matches were decided on an HP-fraction tiebreak, which is a
  *noisy* proxy for skill — and often a symptom of passive or stuck play. We want to *see* and
  minimise this, and treat round-cap wins as lower-confidence than kills.
- **How measured & tested:** count `reason` values from `match_end`. Test: transcripts with each
  reason assert the split.

### B3. Victory margin (surviving HP fraction & survivor count)
- **Quantifies:** the winning team's remaining HP fraction and number of surviving combatants
  (`match_end.hp_fraction`, `survivors`).
- **Why:** a 5-survivor curbstomp and a 1-HP squeaker are both "wins" but reflect very different
  play quality; margin turns a binary into a graded signal and is a strong tiebreak between models
  with similar win rates.
- **How measured & tested:** read directly from `match_end`. Test: assert on a recorded transcript.

### B4. Speed of victory (rounds- and turns-to-win)
- **Quantifies:** rounds (and active turns) elapsed before the match ended, for won matches.
- **Why:** faster kills mean less incoming damage and better action-economy pressure; among wins,
  quicker is strictly better play. Also calibrates the round cap.
- **How measured & tested:** `match_end.rounds`; turns counted from `turn_start` records. Test:
  count records in a fixture transcript.

### B5. Time-to-first-blood / time-to-first-kill
- **Quantifies:** rounds until the agent lands its first hit, and until it scores its first kill.
- **Why:** measures how quickly a model converts position into pressure; a slow first kill often
  means dithering or poor target reach. Especially diagnostic in alpha-strike setups.
- **How measured & tested:** first `action` with `result.hit == true`; first drop of an enemy's
  `hp` to 0 in a `turn_end` snapshot. Test: fixture with a scripted kill on a known round.

---

## 4. Family C — Tactical quality: offense

*How well did it deal damage and remove enemies, independent of whether it ultimately won? These
are the metrics that make a losing match still informative.*

### C1. Damage per action / per turn
- **Quantifies:** total damage dealt ÷ productive actions (and ÷ turns).
- **Why:** raw throughput of the model's offense, normalised so roster size doesn't dominate. Low
  values flag wasted turns or poor attack selection.
- **How measured & tested:** sum `result.damage` (and spell `results[].damage`) ÷ action count.
  Test: fixture with known damage values.

### C2. Attack-selection quality (realised vs. best-available EV)
- **Quantifies:** each turn, the expected value (hit-chance × mean damage) of the attack the model
  chose ÷ the EV of the *best* attack it could legally have made.
- **Why:** directly measures whether the model picks its strongest option rather than a random legal
  one — the core of competent offense. A value near 1.0 is optimal weapon/target choice.
- **How measured & tested:** reconstruct the legal options at the decision point (from the state
  snapshot + stat blocks, or from a logged per-decision options digest — see
  [§9](#9-transcript-fields-each-metric-reads)), compute EV per option from damage formulas and
  known/`assumed` AC, compare to the chosen one. Test: a hand-built decision where a clearly-best
  attack exists asserts the ratio flags a suboptimal pick. *(Under hidden AC this uses an assumed
  AC — see F-family.)*

### C3. Focus-fire index
- **Quantifies:** how concentrated the team's damage was on individual enemies rather than spread
  thin — e.g. a Herfindahl concentration of damage-by-target, or "rounds until the first enemy
  drops" in an NvN.
- **Why:** concentrating fire to delete a combatant a turn early removes its whole action economy —
  the single biggest tactical lever with equal pieces (the alpha-strike skill). Spreading damage is
  a classic weak-play tell.
- **How measured & tested:** aggregate damage per target from `action` results; compute the
  concentration index and/or first-kill round. Test: two synthetic transcripts (all-damage-on-one vs
  evenly-spread) assert the index separates them. **Scenario:** a symmetric NvN melee (the
  `alpha_strike` family) where focusing is decisive and coordination is the variable under test.

### C4. Kill-securing rate
- **Quantifies:** fraction of decision points where a *lethal* option was available (an attack whose
  min or expected damage ≥ a reachable enemy's remaining HP) and the model took a lethal blow.
- **Why:** finishing a low-HP enemy is near-always correct (removes an actor); missing easy kills is
  a strong weak-play signal and cheap to detect.
- **How measured & tested:** at each decision, cross the reachable enemies' HP (from the latest
  snapshot) against available attack damage; check whether a kill was available and whether one was
  landed that turn. Test: a fixture where a 3-HP enemy is in reach of a d8 attacker asserts the
  opportunity is counted and (un)taken.

### C5. Overkill waste
- **Quantifies:** damage dealt beyond a target's remaining HP (summed, and as a fraction of total
  damage).
- **Why:** damage past lethal is wasted economy that could have pressured another target; high
  overkill with multiple live enemies signals poor target switching.
- **How measured & tested:** for each damaging action, `max(0, damage − target_hp_before)` from the
  pre-action snapshot. Test: fixture with a 2-HP target hit for 9 asserts 7 overkill.

### C6. Threat-prioritisation quality
- **Quantifies:** correlation between the model's target choice and a *threat ranking* of enemies
  (high damage output, low effort-to-kill, dangerous abilities) rather than raw lowest-HP or nearest.
- **Why:** deleting the glass cannon before the tank is higher-value than chipping whatever's
  closest; this separates threat-aware models from greedy ones. It's also where a smart model should
  *beat* the lowest-HP heuristic yardstick.
- **How measured & tested:** define a threat score per enemy from its stat block (expected damage
  per turn, HP), rank, and measure how often the model targeted the top-ranked reachable threat.
  Test: a fixture with a fragile high-damage enemy and a tanky low-damage one asserts the metric
  rewards hitting the former. **Scenario:** a mixed roster pairing a "glass cannon" (high damage, low
  HP/AC) with a "bruiser" (low damage, high HP) so the correct priority is unambiguous.

---

## 5. Family D — Tactical quality: defense & positioning

*Did it avoid damage and hold good ground for its role? Positioning is where the diagnostic's weak
model most clearly failed (it planted at melee and traded).*

### D1. Damage taken per round
- **Quantifies:** HP the agent's team lost per round, absolute and normalised to max HP.
- **Why:** the defensive complement to C1; a model can out-damage yet lose by taking sloppy hits.
  Low damage-taken with equal offense is strictly better play.
- **How measured & tested:** diff team HP across consecutive `turn_end` snapshots. Test: fixture
  with a known HP trajectory.

### D2. Preferred-range adherence (kiting quality)
- **Quantifies:** for a ranged unit, the fraction of *enemy* turns it spent outside enemy melee
  reach while still within its own weapon range; equivalently, average end-of-turn distance to the
  nearest melee threat vs. that threat's reach.
- **Why:** kiting is "attack *then* be unreachable"; the diagnostic's archer had fine aim but stood
  in melee for 7 rounds and died. This metric captures the multi-step positioning skill a myopic
  scorer misses — and is the cleanest test of whether the new move candidates translate into skilled
  play.
- **How measured & tested:** from `turn_end` positions and reach (size + weapon range from stat
  blocks), compute distance-vs-reach each round. Test: two synthetic position tracks (kept-distance
  vs stood-in-melee) separate cleanly. **Scenario:** a fast ranged unit vs a slower melee chaser
  (the `kiting` family); the signal is HP taken by the ranged unit — a skilled model wins nearly
  untouched.

### D3. Melee-engagement adherence (for melee units)
- **Quantifies:** the inverse of D2 — a melee unit's fraction of turns *in* reach of a valid target
  (not stranded out of position).
- **Why:** a melee bruiser that ends its turn out of reach wasted it; measures whether melee units
  close and stay engaged. Complements D2 so "good positioning" is role-aware, not a single bias.
- **How measured & tested:** distance-vs-reach for melee actors from snapshots. Test: fixture with a
  melee unit stranded 20 ft away asserts low adherence.

### D4. Exposure / surrounded-ness
- **Quantifies:** how many enemies can reach the agent's units on the enemies' following turn
  (average count of threats within `enemy_speed + enemy_reach`), especially for fragile units.
- **Why:** being surrounded multiplies incoming damage; good play limits how many enemies can strike
  a squishy. A forward-looking (1-ply) exposure measure captures positioning foresight.
- **How measured & tested:** from `turn_end` positions + enemy speed/reach, count reachable
  threats per friendly unit. Test: a fixture placing a unit within two enemies' reach asserts a
  count of 2. **Scenario:** the `protect_squishy` family (a tank + a fragile ranged unit vs two
  melee raiders) — the skill is interposing and keeping the fragile unit's exposure at zero.

### D5. Protected-unit survival & untouched-ness *(scenario metric)*
- **Quantifies:** whether a designated fragile unit survived, and how much HP it took — the *true
  objective* of a protect scenario, independent of win/loss.
- **Why:** the sharpest lesson from the diagnostic — `protect_squishy` was "won" while the squishy
  died. This metric measures the thing the scenario actually tests, and would have flagged that
  false positive.
- **How measured & tested:** track the designated unit's HP curve to match end. Test: a recorded
  `protect_squishy` transcript asserts survival flag + HP-taken. **Scenario:** any setup with a
  designated must-survive unit; the metric is defined per-scenario via a "protected entity" tag.

### D6. Retreat / self-preservation appropriateness *(scenario metric)*
- **Quantifies:** whether a unit that is low on HP *and* outmatched chose to disengage/retreat vs.
  stood and died.
- **Why:** knowing when a fight is lost and preserving a combatant (or the action economy) is real
  tactical maturity; suicidal aggression is a common LLM failure. A tunable-aggression axis.
- **How measured & tested:** detect low-HP outmatched states from snapshots; check whether
  subsequent moves increased distance from threats. Test: fixture with a 2-HP unit next to two
  enemies asserts retreat-vs-stay is classified. **Scenario:** a deliberately losing matchup with an
  escape lane (open board, higher-speed fragile unit) where retreat is the correct line.

---

## 6. Family E — Resource & action economy

*Did it use its limited resources — spell slots, action economy, big abilities — wisely? Mostly
needs spellcasters/limited-use abilities in the roster.*

### E1. Action-economy utilisation
- **Quantifies:** fraction of available actions / bonus actions / movement actually spent on
  productive (non-rejected) effects each turn.
- **Why:** leaving a bonus action or half your movement unused is silently sub-optimal; measures
  whether the model exploits its full turn. Complements A5 (which counts *wasted* actions) with
  *unused* capacity.
- **How measured & tested:** compare resources spent (from action results / snapshot `resources`
  deltas) to the per-turn defaults from the stat block. Test: fixture where a bonus action went
  unused asserts <100% utilisation.

### E2. Spell-slot efficiency
- **Quantifies:** value extracted per spell slot spent, weighted by slot level — e.g. damage/kills
  per slot, and a penalty for spending a high slot on a trivial target.
- **Why:** blowing a top slot on a near-dead minion is a classic waste; conserving big guns for
  worthy targets is skilled resource play. **Scenario-dependent** (needs a caster with a scarce
  high slot).
- **How measured & tested:** from `cast_spell` results + the `slot_level` used, relate slot cost to
  outcome. Test: fixture casting a level-3 slot on a 2-HP target flags waste. **Scenario:** a caster
  with one strong high-level slot facing a mix of many weak enemies and one strong one — the correct
  play saves the slot for the strong target.

### E3. Limited-use / signature-ability timing
- **Quantifies:** whether limited-use or high-impact abilities (recharge, per-day, eventually
  legendary) were used at high-value moments vs. dumped early or hoarded to death.
- **Why:** timing burst resources is a distinct competence; both premature use and never-using are
  failures. **Needs roster support** (abilities with real usage caps).
- **How measured & tested:** track uses of capped actions against the battle state when used. Test:
  fixture with a once-per-battle nuke used on a full-HP swarm vs a lone strong target.

### E4. Concentration discipline *(needs-engine-support / scenario)*
- **Quantifies:** whether the model maintained a valuable concentration effect and avoided
  overwriting it with a weaker one.
- **Why:** concentration management is a core 5e caster skill. Flagged **needs-engine-support** —
  requires concentration mechanics wired into resolution and the transcript.
- **How measured & tested:** once concentration is modelled, track concentration starts/breaks in the
  transcript. **Scenario:** a caster with two concentration options of differing value.

---

## 7. Family F — Information sensitivity

*The arena's first-class experiment: how does play change when enemy facts are hidden? These are
paired metrics — the same tactical metric under `FULL_INFORMATION` vs a restrictive
`InformationPolicy`.*

### F1. Skill degradation under hidden information
- **Quantifies:** the drop in any headline metric (win rate, C2 attack-selection, D2 kiting) when
  enemy HP/AC/actions are hidden vs. fully revealed, same seeds and roster.
- **Why:** measures how much a model *depends* on perfect information — i.e. its ability to play well
  under uncertainty, as at a real table. A small degradation is a strong, generalisable model.
- **How measured & tested:** run the identical seeded matches under two policies (a one-line
  `InformationPolicy` change), diff the metric. Test: the metric-diff harness on two transcript sets
  with a known gap. *(The experiment run is batch-runner work; the metric definition is here.)*

### F2. Inference accuracy under hidden HP
- **Quantifies:** whether the model behaves *as if* it correctly infers hidden enemy state — e.g. it
  stops attacking an enemy that is actually dead/downed under hidden HP, or switches off an
  over-killed target.
- **Why:** hidden-info play rewards inference from observable cues (damage dealt, the combat log);
  this checks whether the model tracks likely enemy HP rather than flailing blind.
- **How measured & tested:** compare the model's target-switching behaviour to ground-truth HP (from
  the ungated `turn_end` snapshot, which the transcript always records). Test: a hidden-HP fixture
  where an enemy is secretly at 0 asserts continued attacks on it count against inference accuracy.

### F3. Over-cautious vs. over-aggressive bias under uncertainty
- **Quantifies:** directional change in aggression (attacks attempted, distance closed) when
  information is hidden — does the model freeze, or charge blindly?
- **Why:** reveals a model's uncertainty *style*; both extremes are failures and are interesting to
  compare across models.
- **How measured & tested:** diff aggression proxies (attacks/turn, average distance-to-enemy)
  between policy conditions. Test: two transcript sets with a constructed aggression gap.

---

## 8. Family G — Consistency, variance & generalisation

*Is the skill real and repeatable, or lucky? These operate over a **set** of matches, not one.*

### G1. Win-rate variance / confidence interval
- **Quantifies:** the spread of the win rate across seeds (Wilson/Clopper–Pearson interval; variance
  across seed-blocks).
- **Why:** given single-match high variance, a mean with no interval is meaningless; two models with
  55% and 60% may be indistinguishable. This is the guardrail on every outcome metric.
- **How measured & tested:** standard interval math over per-match outcomes. Test: known
  win/loss vectors assert the interval bounds.

### G2. Cross-scenario generalisation
- **Quantifies:** the variance (or min) of a model's performance across *different* scenarios/rosters
  — does it play well broadly, or only on one map?
- **Why:** the arena's goal is "plays *any* stat block pragmatically" (HEURISTIC_PLAN §0); a model
  that only wins one matchup isn't generally skilled. Reward breadth, penalise overfitting to a
  single fight.
- **How measured & tested:** aggregate a metric per scenario, report the spread and the worst case.
  Test: per-scenario vectors assert the summary.

### G3. Side-bias (fairness / consistency check)
- **Quantifies:** in a *symmetric* scenario, the win-rate difference between playing team A and team
  B (with the roster/positions mirrored).
- **Why:** a large side-bias means either the harness has a positional/initiative asymmetry
  (a bug to fix) or the model is inconsistent. Either way it's a confound that must be measured and,
  for symmetric scenarios, *cancelled by running both assignments*.
- **How measured & tested:** compare A-side vs B-side win rates over mirrored matches. Test:
  transcripts with swapped sides assert the delta. **Scenario:** any symmetric setup (the
  `alpha_strike` mirror is the canonical one).

### G4. Behavioural determinism / stability
- **Quantifies:** for a fixed model+seed, how much its actions vary across repeat runs (sampling
  noise), and how sensitive outcomes are to small state perturbations.
- **Why:** contextualises all other variance — separates environment variance from the model's own
  sampling variance. High action-instability suggests a model with no real policy.
- **How measured & tested:** repeat identical seeded matches; measure action-sequence divergence.
  Test: a deterministic (scripted) agent must show zero divergence — a built-in sanity anchor.

---

## 9. Family H — Cost & practicality

*What does the skill cost to obtain? Directly informs the free-vs-paid model question.*

### H1. Tokens per turn / per match *(needs instrumentation)*
- **Quantifies:** prompt + completion tokens the model consumed per decision, turn, and match.
- **Why:** the practical budget for benchmarking and for real use; a model that plays slightly
  better at 10× the tokens may not be worth it.
- **How measured & tested:** the LLM adapters must log per-request token usage into the transcript
  (a small instrumentation add — not currently recorded). Test: a mock adapter emitting known usage
  asserts the sum.

### H2. API calls per match & latency *(needs instrumentation)*
- **Quantifies:** number of model round-trips (≈ actions, one per decision) and wall-clock latency
  per decision/match.
- **Why:** determines how many matches fit a rate-limited budget (the free tier affords ~25
  matches/day); latency shapes iteration speed. Ties directly to batch-runner sizing.
- **How measured & tested:** count decisions from the transcript; log timestamps per request. Test:
  count records; assert latency stats on a timestamped fixture.

### H3. Cost-normalised skill (skill per token / per dollar)
- **Quantifies:** a headline metric (e.g. win rate over the heuristic) divided by tokens or dollars
  spent.
- **Why:** the actual decision criterion for choosing a benchmark/production model — exactly the
  "good-value paid model vs free" question. Surfaces models that are Pareto-optimal on skill-vs-cost.
- **How measured & tested:** combine B1/G1 with H1. Test: known skill + known cost asserts the ratio.

### H4. Decision verbosity
- **Quantifies:** completion tokens spent per action (reasoning length), and whether more verbosity
  correlates with better play for a given model.
- **Why:** helps tune thinking-effort settings for cost; a model that plays no better with 5× the
  reasoning can be run cheaper.
- **How measured & tested:** completion-token-per-action from H1, correlated with tactical metrics.
  Test: fixture with known completion sizes.

---

## 10. Family I — Oracle / regret metrics (vs. the heuristic yardstick)

*The most powerful family once the utility-scoring `HeuristicAgent` exists: score each decision
against what a competent reference policy would have done. Turns "did it win" into "how good was
each choice."*

### I1. Per-decision regret vs. the heuristic
- **Quantifies:** at each decision point, the utility gap between the model's chosen action and the
  action the heuristic's scoring function ranked best (the argmax), summed/averaged over the match.
- **Why:** a dense, per-move quality signal that doesn't depend on the match outcome — a model can
  lose to variance while making near-zero-regret choices, and this reveals that. It's the bridge
  between the heuristic work and metrics.
- **How measured & tested:** replay the transcript's decision points through the heuristic's scorer
  (it's deterministic and reads the same observation), compare chosen-action utility to the max.
  Test: a decision where the heuristic strongly prefers action X but the model chose Y asserts a
  positive regret. **Depends on:** the `HeuristicAgent` scorer (HEURISTIC_PLAN) existing as an
  importable function — this metric is the reason to build the scorer in a reusable form.

### I2. Agreement rate with the heuristic
- **Quantifies:** fraction of decisions where the model's action matches the heuristic's top choice
  (or top-k).
- **Why:** a coarse, interpretable companion to I1 ("the model agreed with a competent baseline 72%
  of the time"), and a quick way to spot models that play *differently but better* (low agreement,
  low regret, high win-rate — the interesting quadrant).
- **How measured & tested:** compare argmax actions per decision. Test: constructed decisions with
  known agreement.

### I3. Skill-over-baseline (win-rate lift)
- **Quantifies:** the model's win rate against the heuristic, relative to the heuristic's own
  mirror-match baseline (50%) — how far above a competent bar it plays.
- **Why:** anchors the benchmark to an *absolute* reference rather than only model-vs-model, exactly
  the fixed-yardstick design of the arena. The three-rung ladder (Random floor → Scripted → tuned
  Heuristic) gives graded difficulty.
- **How measured & tested:** win rate vs each rung of the ladder. Test: aggregate over transcripts
  vs each baseline.

---

## 11. Scenario-specific metrics — summary

Several metrics above are only meaningful in a scenario built to elicit the skill. Rather than bake
in fixed maps, each is defined against an **abstract scenario shape**; the concrete rosters live in
[scenarios.py](../src/arena/scenarios.py) and grow over time.

| Metric | Skill under test | Abstract scenario shape |
|---|---|---|
| D2 preferred-range (kiting) | range control / kiting | fast fragile ranged unit vs slower melee chaser |
| C3 focus-fire | coordination with equal pieces | symmetric NvN melee (identical fighters) |
| C6 threat-prioritisation | target selection | mixed roster: fragile high-damage "cannon" + tanky low-damage "bruiser" |
| D4 exposure / D5 protected-survival | role positioning / protection | tank + fragile ranged unit vs multiple melee raiders, with a tagged "must-survive" entity |
| D6 retreat appropriateness | self-preservation / knowing a lost fight | deliberately losing matchup with an escape lane |
| E2 spell-slot efficiency | resource conservation | caster with one scarce high slot vs many weak enemies + one strong |
| E3 signature-ability timing | burst timing | unit with a once-per-battle high-impact ability |
| (future) AoE placement | area targeting | clustered enemies with an ally among them, an AoE caster |
| E4 concentration discipline *(needs-engine-support)* | concentration management | caster with two concentration options of differing value |

Each scenario should be **asymmetric-by-design where possible** so the *heuristic* can faithfully
play the "dumb but correct" side (e.g. "advance and swing"), isolating the skill on the agent's
side — the pattern already used in `kiting`/`protect_squishy`.

---

## 12. Transcript fields each metric reads

The current JSONL transcript (see [transcript.py](../src/arena/transcript.py)) already carries almost
everything. Record kinds and the fields the catalogue depends on:

- **`match_start`** — `seed`, `teams`, `combatants[]` with full stat blocks (`max_hp`, `ac`,
  `actions`, `known_spells`, abilities, `speed`). *Powers:* rosters, threat scores (C6), reach/speed
  for positioning (D-family), EV baselines (C2).
- **`turn_start`** — `entity_id`, `round`, `turn`. *Powers:* turn/round counts (B4), whose decision.
- **`action`** — `actor_id`, `call{name, arguments}`, `result{ok, ...}`; attacks carry
  `hit`, `damage`, `roll{attack_roll, attack_total, attack_bonus, target_ac}`; spells carry
  `results[]` with per-target `hit`/`damage`/`healing`. *Powers:* all conformance (A), damage (C),
  most tactical metrics.
- **`turn_end`** — `state.entities[]` full snapshot: `hp`, `max_hp`, `position`, `ac`, `conditions`,
  `resources`. Ground truth, ungated. *Powers:* HP curves (D1, B3), positions (D2–D4), overkill (C5),
  inference-accuracy ground truth (F2).
- **`match_end`** — `winner`, `reason`, `rounds`, `survivors`, `hp_fraction`. *Powers:* B-family, G1.

**Instrumentation to add (small, additive):**
1. **Per-request token usage & latency** in the LLM adapters → the H-family. Not currently logged.
2. **A per-decision "legal options digest"** (the menu the agent saw) on each `action` record →
   makes C2/C6/kill-securing robust without reconstructing the menu from snapshots. Optional but
   recommended; reconstruction from the state snapshot is the fallback.
3. **Scenario tags** (e.g. `protected_entity`, `must-retreat unit`) in `match_start` → let
   scenario-specific metrics (D5, D6) find their subject generically rather than by name.

---

## 13. Aggregation & reporting

- **Per match → per cell → leaderboard.** A "cell" is one (model × scenario × info-policy). Compute
  each metric per match, aggregate to the cell with a **mean and a confidence interval / spread**,
  then present cells as a leaderboard.
- **Same seeds across models.** Hold the seed set fixed across models so dice are a controlled
  variable, not a difference (paired comparison — much lower variance than independent samples).
- **Report conformance alongside tactics, never merged.** A cell shows, e.g., "win-rate 0.61
  [0.52–0.69]; illegal-action rate 0.03; forfeit rate 0.00" so a reader can trust the tactical
  number *because* conformance is clean — or discount it when it isn't.
- **Prefer baseline-relative headline numbers.** "Win-rate lift over the tuned heuristic" (I3) is
  more portable across scenarios than raw win-rate.

---

## 14. Deferred / needs-engine-support

Catalogued now so we don't forget them; each needs a mechanic the engine (or transcript) doesn't yet
provide:

- **E4 concentration discipline** — needs concentration modelled in resolution + logged.
- **Reaction / opportunity-attack usage** — reactions fire on *other* turns, outside the milestone-1
  own-turn loop (AGENT_ARENA_PLAN §10); metrics on using them wait on that.
- **Legendary-action timing** — same; a later tool + metric.
- **Cover / terrain positioning** — the board is currently open; cover metrics need terrain.
- **H-family (tokens/latency/cost)** — needs the adapter instrumentation in §12.

---

## 15. Suggested first slice (for when we build, not now)

When we do implement (after scrutiny), a high-value minimal slice that needs **no new engine work**
and reads only existing transcript fields: **A1 illegal-action rate, A3 forfeit rate, B1 win-rate +
G1 interval, B2 stalemate rate, B3 margin, C1 damage/turn, C5 overkill, D1 damage-taken, D2
kiting-adherence, D5 protected-survival.** That already turns the three existing scenarios into real,
defensible benchmark numbers and would have correctly flagged the `protect_squishy` false positive.
Everything else layers on top — the oracle/regret family (I) once the heuristic scorer lands, the
information-sensitivity family (F) once the batch runner can sweep policies, and the cost family (H)
once the adapters log usage.
