# The Heuristic's Decision Procedure — How It Actually Chooses

> **Purpose.** [HEURISTIC_PLAN.md](HEURISTIC_PLAN.md) settles the *strategy* — a utility-scoring
> agent, a weight genome, a self-play GA. This document settles the **mechanism**: given one
> entity on its turn, *precisely* how does the agent turn the observation into a chosen action?
> What is the thing we score, over what candidate set, using what numbers, weighing which
> factors? It is the design I would build against — grounded in the real
> [`action_space`](../src/arena/action_space.py) / [`observation`](../src/arena/observation.py)
> data and the engine's real to-hit/damage/save math — and the reusable scorer the oracle/regret
> metrics ([AGENT_ARENA_METRICS.md](AGENT_ARENA_METRICS.md) family I) will call. Nothing here is
> built yet.

---

## 0. In one breath

The agent scores **whole-turn plans**, not isolated actions — a plan is *"(maybe) reposition →
act → (maybe) bonus-act → (maybe) reposition"* — computes each plan's **expected end-of-turn
utility** by a deterministic, side-effect-free estimate (no dice rolled, no engine state
mutated), takes the argmax, and **emits only the first step** of the winner. Next call, it
re-plans from the new observation. Utility is a weighted sum of features; its offensive core is
one principled quantity — **threat-weighted effective-HP removed** — that unifies damage,
kill-securing, overkill and target-priority, with positioning scored as a **1-ply exposure
lookahead**. Planning at turn granularity while acting one step at a time is what cures the
myopia that a purely greedy scorer suffers.

---

## 1. The central question: what is the unit we score?

The engine takes **one action per call** (AGENT_ARENA_PLAN B2): `move`, `attack`, `cast_spell`,
`end_turn`. The naive design scores those atoms greedily and emits the best one each call. It is
the obvious design and it is **wrong for anything multi-step**, because value is not local to a
single atom:

- **A move has no immediate payoff.** Closing to melee, or falling back to kite range, scores
  ~0 on damage this instant — so a greedy damage scorer never repositions unless a hand-tuned
  "positioning" bonus happens to out-argue "attack now". Kiting is definitionally *attack **then**
  retreat*; a scorer that can't see the retreat's purpose (staying unreachable next turn) won't
  value it. This is the exact failure the 2026-09-15 diagnostic's archer showed — good aim,
  stood in melee, died.
- **An action's value depends on positioning done first.** "Cast Fireball" is worthless until
  you've scored *where* to stand so it catches three enemies and no ally.

So the atom is the wrong unit. **The unit we score is a turn-plan**: a short sequence spending
this turn's action economy, evaluated by the *state it leaves the board in* at end-of-turn. We
still respect the one-action-per-call engine seam by committing only the plan's **first step**
and re-planning next call — cheap (plans are re-scored on fresh, cheap estimates) and robust
(if a roll goes badly, the re-plan adapts). This is the single most important design decision in
this document; everything else serves it.

> **Why not full game-tree search / rollouts?** Because the scorer must run *millions* of times
> in the GA (HEURISTIC_PLAN §4) and inside the regret metric on every logged decision. It has to
> be **deterministic and O(candidates)**, not a stochastic simulation. We buy almost all of the
> multi-step benefit with a **1-ply** lookahead (what can reach me after this plan?) folded into
> the terminal-state utility, and stop there. Deeper search is explicitly out of scope.

---

## 2. The decision loop (the precise algorithm)

```
decide(observation, weights) -> ToolCall:
    if not observation.is_my_turn:            # defensive; driver shouldn't call us otherwise
        return end_turn
    plans = enumerate_plans(observation)      # §3  — bounded set of turn-plans
    if not plans:
        return end_turn
    best = argmax(plans, key = lambda p: score(p, observation, weights))   # §5
    if score(best) <= weights.end_turn_threshold:
        return end_turn                        # nothing worth doing
    return first_step(best)                     # emit ONE tool call; re-plan next turn
```

`score` is a **pure function of `(plan, combat, entity, policy, weights)`** — no RNG, no combat
mutation. That purity is a hard requirement, for three reasons: the GA needs determinism to
compare genomes; the regret metric (I1) replays it and must get the same number we got live; and
cheapness is what makes both feasible. It lives in an importable module (`src/arena/heuristic/`,
§11), *not* buried in the agent class, precisely so the metric can call it.

> **Implementation note (what actually feeds the scorer).** The policy-gated observation dict does
> not carry the numbers the EV math needs — save bonuses, ability scores, speed/reach, damage
> formulas, resistances. Since the heuristic is always **in-process**, it is bound to the live
> `CombatSystem` and reads `Entity`/`StatBlock` objects directly (read-only), applying the
> `InformationPolicy` *itself* when it consults enemy facts (§9) so a hidden-information match still
> degrades correctly. The observation's `legal_actions` menu is still the *candidate substrate*
> (already legal-by-construction). No engine change is needed — all reads use existing public
> helpers. For the regret metric to replay this later, its scorer input is reconstructed from the
> transcript's logged stat blocks + snapshots, not the thin observation.

Because we re-plan every call, the loop naturally produces a multi-action turn: call 1 emits
`move`; the engine applies it and hands back a new observation with movement spent; call 2 now
finds "attack" is the best *remaining* plan and emits it; call 3 finds nothing beats
`end_turn_threshold` and ends. The agent never needs to "remember" its plan between calls — the
board state carries the intent.

---

## 3. The plan space (bounded by construction)

A turn in 5e interleaves movement and actions almost arbitrarily. We do **not** enumerate that
freely — we enumerate a small **template** that covers the tactics that matter:

```
Plan = [ pre_move? , main_action? , bonus_action? , post_move? ]
```

- **`pre_move`** — one of the named destinations from
  [`move_candidates`](../src/arena/action_space.py) (`toward_melee:<e>`, `retreat:<e>`,
  `kite_range:<e>`), plus **stay**. These are already *legal by construction* (overlap-checked
  via `CombatSystem.is_destination_clear`, clamped to the movement budget), so we inherit the
  fix for the "stuck moving onto an occupied cell" bug for free. For AoE we add **placement
  points** (§3.1).
- **`main_action`** — one affordable attack or spell from `legal_actions`, aimed at a target
  reachable *from the plan's end position* (not the current one — re-range-check after `pre_move`).
- **`bonus_action`** — an affordable action whose cost is a bonus action (off-hand attack, some
  cantrips/spells). Enumerated only when one exists.
- **`post_move`** — the *kite tail*: spend leftover movement to `retreat`/`kite_range` **after**
  acting. This is the piece a greedy scorer structurally cannot express, and the cheapest lever
  for real kiting.

The combinatorics stay small because each slot draws from a handful of options: destinations are
discretised to O(enemies) named points, and for a given position the **best** attack/spell against
a given target is a max, not a cross-product to enumerate. In practice the plan set per turn is
tens, not thousands — trivially scoreable.

Two practical rules:

1. **Range is re-checked at the plan's positions**, using the same
   [`range_check`](../src/spatial/range_check.py) helpers the engine uses (edge-to-edge for
   attacks, nearest-point for spells) — so a plan that says "close to melee then swing" only
   offers the swing if the swing is actually in reach after the move.
2. **Every plan is legal by construction on the *legality* the menu already guarantees**
   (affordability, slots, overlap-free destinations). The referee is still the authority; the
   heuristic simply should never trip the failure budget (its defining advantage over an LLM).

### 3.1 AoE placement search (a permitted helper)

`move_candidates` says nothing about where to *aim* an area spell, and `_spell_targets` returns
`[]` for non-single-target spells by design. So an AoE plan needs a small **placement search** —
exactly the kind of helper the brief invites ("computing a position that hits the maximum number
of targets"). It works only from data the agent may know (enemy positions, the spell's shape/size
from `AOEProperties`, the geometry in [`derive_aoe_origin`](../src/spatial/range_check.py)):

- **Candidate origins:** each enemy's position, and the centroid of every enemy *cluster* (pairs
  or triples within the AoE's footprint). For CONE/LINE, candidate *directions* toward each enemy
  or cluster centroid (origin is fixed at the caster per `derive_aoe_origin`).
- **Score each origin** by the modelled hit set: `Σ value(enemy in volume) − friendly_fire_weight
  · Σ value(ally in volume)`, where "in volume" reuses the engine's own shape test so the
  heuristic and the engine agree on who gets hit. Clamp to range (`clamp_to_range`).
- The best origin becomes the `target_point` of a `cast_spell` plan; its utility feeds §5 like any
  other action, but with the multi-target damage summed.

Keep this behind a flag/subroutine so single-target scoring stays cheap when no AoE is in hand.

---

## 4. Evaluation primitives (grounded in the engine's real math)

Every feature reduces to a few expected-value estimates. These must **mirror the engine's actual
resolution** (the same parity discipline the metrics doc demands for C2), so the scorer's ranking
matches what really happens. From the code:

**Hit chance** ([`rolls.attack_roll`](../src/spells/blocks/rolls.py)): a d20, `hit = total >= AC`,
with **nat-20 always hits** and **nat-1 always misses**. For attack bonus `B` vs armour class
`AC`, on a straight roll:

```
need      = AC - B                                  # the face you must meet on the die
p_normal  = count(r in 2..19 : r >= need) / 20      # ordinary hits
p_crit    = 1/20                                    # the natural 20
p_hit     = clamp(p_normal + p_crit, 0.05, 0.95)    # nat-1 caps at 0.95, nat-20 floors at 0.05
```

Advantage/disadvantage (surfaced by `ATTACK_DECLARED` subscribers): `p_adv = 1−(1−p)²`,
`p_dis = p²`, and the crit chance itself rises/falls (`1−(19/20)²` vs `(1/20)²`) — fold both,
because advantage is worth more than it looks once crits double dice.

**Average damage** from a formula (`dice.parse_dice_formula`): `E[NdS] = N·(S+1)/2`, flats added
as-is. A new tiny pure helper `expected_formula(formula)` — the analytic twin of `roll_formula`.
Crucially, the engine **doubles dice (not flat mods) on a crit** (`damage.py` →
`multiply_formula(f, 2)`), so:

```
E[dmg] = p_normal·(E_dice + flat) + p_crit·(2·E_dice + flat)
```

**Save spells** ([`rolls.saving_throw`](../src/spells/blocks/rolls.py) + `damage` block's
`save_result`): no crit on saves. `p_fail = P(d20 + save_bonus < DC)` against the caster's
`spell_save_dc`; `E[dmg] = p_fail·full + p_save·(full//2 or 0)` per the spell's `on_success`.

**Effective HP.** Damage is throttled by target resistance/immunity/vulnerability in the
`damage_processor`. The scorer applies the multiplier **only when it can see the target's
modifiers** — true for `self`/allies, generally *not* for enemies (the observation doesn't expose
enemy damage mods). Against enemies it assumes ×1 and notes the blind spot; a smarter later pass
could infer resistance from observed under-damage in the combat log.

> **Parity rule (carry into code):** these estimates and the engine's rollers read the *same*
> authoring fields and the *same* crit/save rules. When one changes, the other must — a drift test
> (compare `expected_formula` mean against a large sampled `roll_formula` average) keeps them
> honest, in the spirit of CLAUDE.md §9 2026-09-03.

---

## 5. The utility function

A **weighted linear sum** of features (the GA genome weights them). But rather than a flat bag of
loosely-related bonuses, the offensive core is **one principled quantity**, with the softer
concerns layered around it.

### 5.1 The offensive core — threat-weighted effective-HP removed

HEURISTIC_PLAN lists *expected damage*, *secure-a-kill*, *overkill-waste*, and *threat-weighted
targeting* as four separate features. They are really **one** idea, and modelling them separately
invites the weights to fight each other. The unifying quantity: **how much threat you remove from
the board this turn.**

For a plan dealing expected `d` to enemy `e` with remaining HP `h`:

```
useful      = min(d, h)                       # overkill past h is free to no one  → overkill falls out
progress    = useful / effective_hp(e)        # fraction of e's staying-power removed
kill_bonus  = KILL if d >= h (expected lethal) else 0     # removing the whole actor NOW, not next round
value(e)    = threat(e) · (progress + kill_bonus)         # threat scales everything  → priority falls out
```

- **Overkill** needs no separate penalty — `min(d, h)` caps it; damage past lethal simply adds
  nothing, so a plan that splashes a near-dead target scores below one that switches.
- **Target priority** needs no separate feature — multiplying by `threat(e)` (§7) means the same
  damage is worth more against the glass cannon than the tank, automatically.
- **Kill-securing** is the one genuinely discontinuous term (crossing HP to 0 deletes a whole
  action economy *this* round rather than next), so it keeps an explicit bonus — but expressed in
  threat units, so finishing a dangerous foe outranks finishing a harmless one.
- **Focus fire** is emergent: as `h` falls, each point of `useful` damage is a larger `progress`
  fraction and edges closer to `kill_bonus`, so the team piles onto a wounded high-threat target
  without any global rule (sharpened by §8's ledger).

This single term already reproduces four of the plan's listed features *coherently*. The GA then
only tunes `KILL` and the threat scaling, not four mutually-cancelling knobs.

### 5.2 The full feature vector

| Feature | Reads | Precise value | Notes |
|---|---|---|---|
| **Offense (core)** | enemy HP; own attack/spell formulas & bonuses; enemy AC/saves | `Σ_e value(e)` from §5.1 | The backbone; AoE sums over the hit set (§3.1). |
| **Healing** | ally `hp`/`max_hp`; heal formula | `heal_amount · urgency(ally)` where `urgency = 1 − hp/max_hp`, spiked if the ally is *lethally* exposed next turn (§6) | Heal the ally about to drop; ignore scratches. Capped at missing HP (no overheal value). |
| **Control / status** | spell's applied condition; target threat | `severity(condition) · threat(target) · p_apply` | `p_apply = p_fail_save`. `severity` is a small data table (stun/paralyse ≫ restrain/prone ≫ minor); data-driven, not name-keyed. |
| **Exposure (defense)** | end position; enemy positions, speed, reach, EV | `−Σ_e reachable_next_turn(e) · EV(e→me) · fragility(me)` | The 1-ply lookahead, §6. The term that makes kiting pay. |
| **Positioning (offense)** | end position; own best target reachability | small bonus for ending in reach of a high-`value` target | Rewards `pre_move` that sets up next turn even when this turn can't reach. |
| **Resource economy** | slot level used; ability recharge/limited uses | `−cost_scarcity(resource)` scaled by how much the plan *needed* it (a cantrip alternative existing raises the penalty) | Don't spend a 3rd-level slot to chip a minion a cantrip would kill. |
| **Self-preservation** | own `hp`, exposure, team HP balance | `retreat_value` when low-HP **and** outmatched; a tunable `aggression` scales it | Keeps a unit (and its action economy) alive when the fight's lost locally. |
| **End-turn threshold** | — | a plan must clear `end_turn_threshold` to beat stopping | Prevents burning actions on ~0-value moves. |

Every row is computed from data the entity is *allowed* to know (§9 handles the hidden-info
degradation), and none branches on a creature's name (CLAUDE.md §2.2) — `threat`, `severity`,
`fragility` are all read off stats and a small data table.

### 5.3 Normalisation (so weights are meaningful)

Features live on wildly different scales — damage in HP, kills boolean, distance in feet — and a
linear sum across raw scales makes the GA's weights uninterpretable and its search ill-conditioned.
So each feature is normalised to a **dimensionless ~[0,1] (or [−1,0]) magnitude** *before*
weighting:

- damage/heal → **fraction of the relevant creature's max HP** (already dimensionless in §5.1's
  `progress`),
- exposure → fraction of *own* max HP expected to be lost,
- resource cost → fraction of that resource pool spent.

Then `score = Σ weight_i · feature_i`. This is what lets a single weight vector generalise across
rosters of very different HP totals (the "plays *any* stat block" requirement), instead of
overfitting the absolute numbers of one scenario.

---

## 6. Positioning & exposure — the hard feature, made precise

Positioning is where a heuristic usually disappoints, so it gets the most concrete treatment. We
score the **quality of the position a plan ends in** as a 1-ply lookahead: *who can hurt me next
turn from here, and how much?*

For the plan's end position `P` and each enemy `e`:

```
reach_e   = e.speed + e.max_weapon_reach          # how far e can close-and-hit next turn
can_reach = dist(P, e) <= reach_e                 # edge-to-edge, via range_check geometry
exposure += can_reach · EV(e → me at P)           # e's best-attack EV vs my AC (§4)
```

- **`fragility(me)`** weights the whole sum by `1 − hp/max_hp`-adjusted survivability, so a
  low-HP squishy flees exposure that a full-HP tank shrugs off. This is why we need **no separate
  `kite_bias` knob** in principle — a ranged unit is usually the fragile one, so minimising
  exposure *is* kiting — though keeping a small explicit bias term is a cheap hedge if emergence
  disappoints.
- **Ranged vs melee falls out of the same term.** A melee unit's own best plan requires being
  *in* reach (its offense term rewards adjacency); a ranged unit can score high offense from a
  distant `kite_range` point where exposure is ~0. No role flag needed — the geometry decides.
- **Surrounded-ness** is just exposure with `can_reach` true for several enemies at once; the sum
  naturally punishes standing where three foes converge (the `protect_squishy`/`exposure` skill,
  metrics D4).
- **1-ply only.** We ask "can they reach me next turn", not "and then the turn after" — bounded,
  deterministic, cheap. It is the entire multi-step-positioning payoff for O(enemies) work.

This same lookahead feeds *offense* on allies' behalf (heal-urgency spikes for an ally whose
exposure implies a likely drop) and *self-preservation* (retreat when own exposure ≫ own offense).

---

## 7. Target valuation — what "threat" actually means

`threat(e)` must be a principled number, not "lowest HP" (the current `ScriptedAgent`'s rule, and
a known weak-play tell). The value of *removing* an enemy is the future damage you prevent:

```
dpr(e)     = expected damage e deals per turn = EV of e's best attack vs a typical AC
threat(e)  = dpr(e)                              # danger per round it stays alive
```

Then §5.1's `value(e) = threat(e) · (progress + kill_bonus)` says: damage matters in proportion
to how dangerous the victim is, and *killing* is worth removing all of that danger a round sooner.
Refinements, in rough priority order:

- **Effort-to-kill.** A target that dies to one blow this turn is worth more than equal threat
  spread over a target that survives two rounds — already captured by `kill_bonus` firing when
  `d >= h`, and sharpenable by dividing threat by rounds-to-kill.
- **Dangerous abilities.** A control/AoE caster is worth more than its raw `dpr` suggests; a small
  data-table multiplier on threatening capability types (again, capability-typed, not name-keyed)
  can lift such targets. Deferred until the roster has them.
- **Reachability discount.** An enemy you can't reach this turn contributes to *positioning* value
  (move to threaten it) but not to this turn's offense term.

This is where a strong LLM *should* be able to beat the yardstick (metrics C6): the heuristic's
threat model is a good approximation, not perfect foresight.

---

## 8. Team coordination — a shared damage ledger

One agent controls the whole team (AGENT_ARENA_PLAN B1), but it decides **one unit at a time in
initiative order**, not simultaneously — so "focus fire" can't be a single global optimisation. The
cheap, correct mechanism that fits one-action-at-a-time:

- Maintain a per-round, per-team **intended-damage ledger**: as each unit commits a plan, record
  the expected damage it will do to each target.
- Later units in the initiative order **read the ledger** and treat a target's *remaining* HP as
  `h − already_intended`. This makes two right things emergent:
  1. **Finish what's started** — a target the first unit brought to near-death now trips the second
     unit's `kill_bonus`, concentrating fire.
  2. **Avoid overkill switching** — a target already lethally committed shows `h_effective ≤ 0`, so
     `min(d, h_effective)` is ~0 and the next unit looks elsewhere on its own.

It needs no simultaneity and no new engine hooks — just a scratchpad the team agent owns across its
units' turns within a round. It captures most of the `alpha_strike` skill (metrics C3) for almost
nothing.

---

## 9. Playing with less than full information

The scorer reads live entity state but **applies the `InformationPolicy` itself** on enemy facts
(mirroring what [`_serialize_enemy`](../src/arena/observation.py) would hide), so it degrades
gracefully and stays usable under any policy (and so the regret metric can score hidden-info
matches). In Phase A+B, `reveal_enemy_actions` gates enemy capabilities and doubles as the proxy
for "do we know this enemy's defensive profile" (resistances have no dedicated policy flag):

| Hidden field | Fallback |
|---|---|
| Enemy **HP** exact | Use the **bucket midpoint** when bucketed; treat as **full HP** when fully hidden (conservative — won't hallucinate a kill). `kill_bonus` simply won't fire on a guess. |
| Enemy **AC** | Assume a **level/CR-typical AC baseline** for hit-chance; the estimate degrades gracefully rather than refusing to score. |
| Enemy **actions/known_spells** | Assume a **generic melee threat** (a default `dpr` and reach) for `threat`/exposure, until the combat log reveals real capabilities (you learn a foe's attacks by being hit). |
| Enemy **conditions/slots** | Ignore (no bonus/penalty modelled). |

Own units and allies are always full-information (`_serialize_ally`), so heal-urgency, exposure of
*your* squishy, and resource economy are always exact. How gracefully the *heuristic* copes with
hidden info is itself a benchmark axis (metrics F) and a reason to get these fallbacks sane.

---

## 10. Determinism & tie-breaks

- **Stable argmax.** Ties in `score` break by a fixed order: action-type (attack < spell < move <
  end), then target `entity_id`, then `option_id` — lexicographic, so a seeded replay reproduces
  exactly (the same discipline `move_candidates` already uses when it sorts enemies by `entity_id`).
- **No RNG in scoring.** All randomness is *modelled* as expectation (§4), never sampled. The only
  RNG in the whole agent is `RandomAgent`'s, which this design doesn't touch.
- **End-turn is a real candidate**, scored at `end_turn_threshold`, so "do nothing" competes on the
  same axis and wins when it should (a slightly-negative-EV desperation swing shouldn't be forced).

---

## 11. What to reuse, what to build, and where it lives

**Reuse (no changes):** `legal_actions` / `move_candidates` (the candidate substrate),
`range_check` (edge-to-edge attack range, nearest-point spell range, `effective_range_ft`,
`clamp_to_range`, `derive_aoe_origin`), `CombatSystem.is_destination_clear`, `dice.parse_dice_formula`,
and the observation/policy layer.

**Build (new, pure, importable):** a `src/arena/heuristic/` package —

- `estimate.py` — the §4 primitives: `hit_chance`, `expected_formula`, `expected_attack_damage`,
  `attack_ev_vs_ac`, `save_fail_prob`, `spell_expected_damage`. Pure; drift-tested against sampled
  rolls. *(Built, Phase A.)*
- `plan.py` — `enumerate_plans(combat, entity, policy)` (§3) and the AoE `_aoe_plans` placement
  search (§3.1), which asks the engine's own `derive_aoe_origin` + `get_targets_in_aoe` who each
  candidate aim point would catch. *(Built, Phases B–C.)*
- `features.py` — the §5 feature extractors and `threat` (§7): the unified offensive core (with the
  team damage-ledger threaded in), a range-aware **engagement** gradient (saturates once the target
  is in your own reach — melee closes, ranged holds, no role flag), `aoe_offense` (with a
  friendly-fire term), `control` (a `CONTROL_SEVERITY` table × threat × p_apply), and `resource_cost`
  (slot-level economy). *(Built, Phases B–C.)*
- `score.py` — `score(plan, combat, entity, policy, weights, committed)` and `HeuristicWeights` (the
  GA genome: damage, kill, exposure, engagement, friendly_fire, control, resource, aggression,
  end_turn_threshold).
- `agent.py` — `HeuristicAgent(Agent)`: the §2 loop plus the §8 per-round team damage-ledger (reset
  on round change; reserves committed damage so allies focus-fire without overkill). *(Built,
  Phases B–C.)*

The split matters because **the regret/oracle metrics (I1/I2) import `score` and `enumerate_plans`
directly** to replay each logged decision through the same policy — the reason HEURISTIC_PLAN insists
the scorer exist "as an importable function", not welded inside the agent. Same code scores live
play *and* judges the LLMs.

**Debt & convolution note (CLAUDE.md §2.7):** this *removes* the `if/elif` ladder that
`ScriptedAgent` is, replacing it with a data-driven scorer that reads capabilities off the entity;
it adds **no** engine dependency (pure consumer of `observation` + read-only helpers), keeping the
correct dependency direction (`arena → combat/models`, never the reverse). The one deliberate cost
is a genuinely new subsystem (the estimator/planner/scorer) — justified because it is the shared
substrate for *both* the yardstick opponent and the entire oracle metric family, not a one-off.

---

## 12. What to prove first (build order for the mechanism)

Mirroring HEURISTIC_PLAN §7's "features before optimiser", but at the mechanism level:

1. ✅ **`estimate.py` + a parity test** — the EV math must match the engine before anything trusts it.
   *(Phase A.)*
2. ✅ **`enumerate_plans` (no AoE) + the §5.1 offensive core + §6 exposure**, hand-weighted. This
   alone fixes the four `ScriptedAgent` failures (stuck-move, no-kite, HP-not-threat targeting, no
   kill-securing) and is a far better yardstick — benchmarked against `ScriptedAgent` (a fast kiter
   wins 20/20). *(Phase B.)*
3. ✅ **AoE placement, control, resources, the §8 ledger** — layered in. *(Phase C.)*
4. ✅ **Self-play GA over the weights** — `src/arena/heuristic/ga.py` evolves `HeuristicWeights`
   against the scripted yardstick on the scenarios (fixed-opponent fitness, shared per-generation
   seeds, parallel, fully logged; battles regenerate from weights + seed). *(Phase D — see
   [HEURISTIC_PLAN.md](HEURISTIC_PLAN.md) §7.)*
5. **Expose `score`/`enumerate_plans` to the regret metric** (I1) — the payoff that makes the whole
   scorer double as the benchmark's judge. *(Next.)*

Only then does the GA (HEURISTIC_PLAN §4) have a feature set worth optimising — because, as that doc
rightly says, *the optimiser only weights what the features can express*, and this document is about
making the features express the right things.
```
