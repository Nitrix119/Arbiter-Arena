# CLAUDE.md

Guidance for AI agents (and humans) working in this repository. Read this file in
full before making changes. It is the source of truth for **how** we build here;
the code is the source of truth for **what** currently exists.

For the deeper design intent behind the spell/combat engine, read
[docs/current/SPELL_SYSTEM_VISION.md](docs/current/SPELL_SYSTEM_VISION.md). For the current health
of the codebase and the open repair roadmap, read
[docs/current/CODEBASE_REVIEW.md](docs/current/CODEBASE_REVIEW.md). For **what's genuinely left in the
spell/combat rework** — remaining deletions, carried deviations to not lose, and known
awkwardness worth refining — read
[docs/current/SPELL_SYSTEM_REMAINING.md](docs/current/SPELL_SYSTEM_REMAINING.md).

---

## 0. How to use and maintain this file

This document is designed to **grow over time**. When a mistake is made and a
lesson is learned, the fix is not only in the code — it is also a new rule here so
the mistake is not repeated.

- Keep entries **short, imperative, and scannable**. Prefer a one-line rule over a
  paragraph; if a rule needs justification, add a parenthetical _(why: ...)_.
- **Do not delete history.** Supersede a rule by editing it and noting the change,
  rather than silently rewriting the project's reasoning.
- New durable lessons go in [§9 Lessons Learned](#9-lessons-learned-append-only) as
  dated, append-only entries. Promote stable lessons up into the relevant section.
- Keep the commands in [§7](#7-stack--commands) exact — agents rely on them. Fix a
  wrong command the moment you find it.
- If two rules conflict, the more specific one wins; flag the conflict to the user.

---

## 1. Project overview

**Arbiter Arena** (formerly D&D Auto-Battler) — an SRD 5.1-compatible combat simulator
and a deterministic evaluation harness for tool-using LLM agents. The engine is
**Python** (`src/`), usable as a library or through a FastAPI web app (`web/`) with a
browser JS client (`web/static/js/`). **Creatures, spells, and rules are JSON data** — most content is
added without touching Python.

The ambition (see [the vision doc](docs/current/SPELL_SYSTEM_VISION.md)): a **massively
flexible, generic engine** that can express the vast, messy diversity of D&D combat
through composable, data-defined effects rather than per-spell special-casing.

**Domain boundaries / principles:**

- **Data-driven first.** A new spell should be a JSON file; a new *mechanic* a small,
  registered effect handler — never a branch on a spell's name.
- **Model the rules honestly, and where you can't yet, decline loudly** rather than
  fake it (an unsupported step logs and is skipped; an image-only case should say so).
- **Determinism on demand.** All randomness flows through one seedable RNG
  (`dice.seed_rng`) so a battle can be reproduced exactly.

---

## 2. Core principles

Non-negotiable. Every change should be justifiable against these.

1. **Modularity first.** Small, single-responsibility units with narrow, well-named
   interfaces. A reader should understand a module without reading the whole system.
2. **Flexibility over hard-coding.** The engine's value is its generic pipeline. Reach
   for a new composable effect + a schema entry before you special-case a spell. If a
   mechanic can only be expressed by naming a specific spell, the abstraction is wrong.
3. **Test-driven.** No behaviour change without a test that demanded it — and for the
   pipeline, a test that *executes* it, not one that only inspects JSON shape
   ([§4](#4-test-driven-development-tdd), and §9 2026-08-08).
4. **Design for failure.** Where a system breaks matters as much as where it works.
   Enumerate the unhappy paths — malformed JSON, missing fields, dead targets,
   concentration loss, both-advantage-and-disadvantage — and decide each deliberately.
5. **Fail loudly, early, and specifically.** Validate at boundaries (the JSON loaders);
   raise precise errors that name the bad value and the valid options. Every spell, weapon
   and rule `program` goes through `src/spells/validate.py`, which rejects: an unregistered
   block, an **undeclared arg** (with a did-you-mean), a value of the wrong kind or outside
   its domain, an arity error, a `context.X` key nothing writes, an `event.<field>` the
   enclosing `trigger`'s event does not carry, an expression that will not parse or leaves
   the sandbox, and a `then` on a block that never runs one. Content that is not a block
   `program` does not load at all. _(Why this matters more than it looks: a failure at run
   time is usually **invisible** — an unknown arg is ignored, and a trigger guard that
   raises is swallowed as "did not fire". See §9 2026-09-03.)_
   - **A block's args are declared, not implied.** Adding an arg to a handler means adding
     a `Field` to its `BlockContract` — `tests/test_block_schema_drift.py` reads the
     handlers' real `block.get` calls and fails if the two disagree.
6. **Small, reversible changes.** Many small, well-tested commits over one large one.
   Keep `main` clean; do non-trivial work on a branch.
7. **Debt and convolution are first-class.** In an engine whose whole value is modular
   flexibility to absorb new mechanics, technical debt and tangle are not side concerns —
   they are the thing that kills that flexibility. Treat a change's effect on them as a
   design factor on par with correctness. Prefer the option that *removes* debt/convolution;
   when a change adds either, that is a deliberate, justified trade, not an accident. Name
   it explicitly (see [§6](#6-agent-working-agreement)). Watch especially for **inverted
   dependencies** (new code depending on legacy), **duplicated vocabularies/engines**, and
   **silent coupling** — the recurring smells this rework exists to remove.

---

## 3. Architecture & modularity rules

- **One resolution path for everything.** Spells, weapon attacks and rules are all a block
  **`program`**: a list of blocks keyed by `block`, parsed by `block.parse_program`, validated
  at load by `spells.validate.validate_program`, and run by the block **evaluator**
  (`src/spells/evaluator.py`) over a shared ephemeral `context` — earlier blocks write results
  (`context.hit`, `context.damage_dealt`, `context.save_success`), later blocks read them.
  There is **no translation layer**: `EffectPipeline`, `fold.py` and `adapter.py` are all
  deleted, and no second effect vocabulary exists. A weapon keeps its concise flat authoring
  form (`bonus_to_hit` + `damage`), from which `AttackResolver._default_program` builds the
  implied `[attack_roll, damage…]`; it may author a `program` instead when it needs more.
  Never add a second resolution path.
- **The authoring reference is generated.** `docs/current/BLOCK_REFERENCE.md` is rendered from the
  block `REGISTRY` (`python -m src.spells.reference`) and drift-tested, so it cannot fall
  behind the code. Adding a block means writing its docstring and contract, then regenerating.
- **`src/rules` is data; `src/spells` is the engine.** `src/rules` defines a rule (`Rule`),
  loads it (`RuleLoader`), catalogues it (`EffectRegistry`) and evaluates expressions.
  *Installing* a rule is `src/spells/rules.py`. Never let the data layer reach into the
  engine — that inversion is what `RuleEngine` was, and it is deleted.
- **Registry, never `if/elif` on type.** New block type → add a handler under
  `src/spells/blocks/` and register it in the block `REGISTRY` (`src/spells/registry.py`),
  dispatched on the block's type. New spell → drop a JSON file in `examples/spells/`
  (auto-scanned at startup). Do **not** branch on a spell's name. The block `REGISTRY` is the
  **only** effect vocabulary — the legacy `BUILTIN_EFFECTS` `action`-verb registry is deleted.
- **Rules are block programs too.** A rule (`rules/global/*`, `rules/entity_effects/**`) is a
  `program` of `trigger` blocks; `src/spells/rules.py` loads and installs them.
  There is no second rule vocabulary and no legacy `triggers`/`effects` shape — such a file
  now fails at load, naming itself.
- **Cross-cutting behaviour rides the EventBus.** Resolvers emit typed events
  (`ATTACK_DECLARED`, `ATTACK_ROLLED`, `SAVING_THROW_DECLARED`, `DAMAGE_INCOMING`,
  `DAMAGE_DEALT`, `SPELL_HIT`, …). Rules and entity effects subscribe and may modify or
  cancel the event. Add reactive mechanics as subscribers, not inline branches.
- **Immutable template, mutable state.** `StatBlock` is a shared, immutable template;
  all per-battle state (HP, conditions, modifiers, position, concentration) lives on
  `Entity`. Never mutate a `StatBlock` during combat.
- **Pure core, imperative shell.** Keep dice/geometry/expression evaluation
  deterministic and side-effect-free; push I/O (WebSocket, disk, clock) to the web
  layer. Seed randomness through `dice.seed_rng` rather than reaching for `random`.
- **Explicit data contracts.** JSON is validated at the loader boundary and trusted
  within. Enum/format errors must name the bad value and the valid set
  (`_enum_lookup`, `_validate_formula`).
- **Name for intent, not implementation.** `spell_attack_bonus`, not `calc2`.
- **Sandbox stays a sandbox.** JSON expressions run under `src/rules/expressions.py`
  (AST whitelist, `__builtins__={}`, no imports/dunder). Anything a rule author can
  type must remain inside it — never widen it for convenience.

---

## 4. Test-Driven Development (TDD)

TDD is the default workflow, not an afterthought. The suite is a genuine strength
(550+ tests) — keep it that way.

**Testing rules:**

- **Bug fixes start with a failing test that reproduces the bug** _(why: proves the fix,
  prevents regression)_.
- **Test behaviour, not structure — especially for the pipeline.** A test that only
  asserts which steps a spell JSON parses into does **not** prove the steps *run*. New
  step types and effects need a test that executes the pipeline and checks the outcome
  (see §9 2026-08-08 — a structure-only test hid a hard crash).
- **Prove wiring end-to-end.** A model field + a rule can both exist while nothing
  populates the field from JSON. When you add data-driven content, assert it takes
  effect in a real resolution, not just in a hand-built object.
- **Cover the unhappy paths.** Malformed JSON, unknown enums, dead targets, empty AoE,
  failed saves, concentration drops, advantage+disadvantage cancelling.
- **Deterministic.** Seed with `dice.seed_rng(...)` or patch the roll functions; never
  rely on real randomness. No network in the suite.
- **The suite must be green before any task is done.** Report failures honestly.

---

## 5. Coding conventions

- Let the **formatter and linter** be the authority: `black`, `flake8`, `mypy`
  ([§7](#7-stack--commands)). Keep changed files clean.
- **88 characters, enforced.** Black is pinned `==26.5.1` and both it and flake8 are configured
  to 88 in-repo (`[tool.black]`, `.flake8`), so every environment and CI agree. `black` will not
  wrap comments or docstrings — **wrapping prose is your job**. The tree is at zero E501 and CI
  holds that line; do not reintroduce one, and reach for `# noqa: E501` only for a genuinely
  unwrappable line (a long URL, an unsplittable literal), with a reason.
- **`mypy src/` is clean (0 errors) — keep it that way.** Prefer narrowing that names the real
  invariant over a blanket `# type: ignore`; where an ignore is unavoidable, scope it to the code
  (`[arg-type]`) and comment why. _(Why: the 2026-09-19 sweep found a live bug — float movement
  costs spent against an int budget — hiding behind what looked like a typing nit.)_
- **Type annotations** throughout; prefer named structures (`NamedTuple`/dataclass) over
  bare positional tuples for anything with more than two fields.
- **Comments explain _why_, not _what_.** Delete commented-out code — it belongs in git
  history, not the source (see §9 2026-08-08 on the reconnection cleanup).
- **No magic values.** Name constants; if one must be duplicated across the Python/JS
  boundary (`CELL_FEET`), comment both copies to keep them in sync.
- **Handle errors with intent.** No bare/blanket catches that hide failures.

---

## 6. Agent working agreement

1. **Understand before changing.** Read the relevant modules *and their tests*; match
   existing patterns.
2. **Plan non-trivial work.** State the approach before large or cross-cutting changes;
   prefer the smallest change that solves the problem.
3. **Account for debt and convolution — explicitly** ([§2.7](#2-core-principles)). When
   planning a non-trivial change, include a short **debt & convolution note**: name where it
   *removes* or *adds* technical debt and tangle, and why (e.g. "removes an inverted
   dependency: the block engine no longer imports from the legacy module"; "collapses two
   resolution paths into one"). Quantify when you can (lines/files/paths/errors deleted). This
   is a first-class part of the plan and the commit message, not an afterthought — it is how
   this modular engine keeps its flexibility. If a change *adds* debt, say so and justify it as
   a deliberate trade, and record follow-up in [CODEBASE_REVIEW.md](docs/current/CODEBASE_REVIEW.md).
4. **Work test-first** per [§4](#4-test-driven-development-tdd).
5. **Keep the tree green.** Run the formatter, linter, and full suite before declaring a
   task done. If tests fail or a step was skipped, say so with the output.
6. **Don't expand scope silently.** Note adjacent problems (in
   [CODEBASE_REVIEW.md](docs/current/CODEBASE_REVIEW.md)); don't fold unrelated fixes in.
7. **Update docs with code.** Behaviour/command/structure changes update this file, the
   README, and the relevant guide in the same change.
8. **Capture lessons.** When a non-obvious mistake is found and fixed, append to
   [§9](#9-lessons-learned-append-only).
9. **Branch, don't touch `main`.** Do work on a feature branch; commit/push only when
   asked; write commit messages that explain the _why_.

---

## 7. Stack & commands

| Task | Command |
|---|---|
| Install (core + web + dev) | `pip install -e ".[web,dev]"` |
| Run the web UI | `uvicorn web.app:app --reload` → `http://localhost:8000` (`serve.bat` on Windows) |
| Run all tests | `pytest tests/ -q` |
| Run one test | `pytest tests/test_spells.py::TestX::test_y -q` |
| Format | `black src/ web/ tests/` |
| Lint | `flake8 src/ web/` |
| Type-check | `mypy src/` |
| Run a study grid (resumable) | `python -m src.arena.study run GRID.toml --out results/<name>` (`--dry-run` to preview) |
| Report on a study bundle | `python -m src.arena.study report results/<name>` |
| Verify a bundle replays (must be 100%) | `python -m src.arena.study verify results/<name>` |
| Read one match, decision by decision | `python -m src.arena.study show <transcript.jsonl> [--refused]` |
| No-key demo of the whole pipeline | `python -m src.arena.study run examples/study/demo.toml --out results/demo` |
| C1 parser audit | `python -m src.arena.audit sample results/<name> --out audit/` → `… label audit/` → `… score audit/ --report results/<name>/report` |

- **Check exit codes, not tails.** In a chained command, never pipe a check through `tail`/`head`
  unless `set -o pipefail` is on: the pipe reports the *last* command's status, so a failing
  `mypy` would read as success (§9 2026-09-24).

- **RNG:** all randomness flows through a single **context-scoped** `random.Random` in
  `src/utils/dice.py` (a `contextvars.ContextVar`), so each battle can own its own seed
  without any roll call site changing. `dice.py` is the only module that touches `random`.
  - `CombatSystem(seed=…)` gives a battle its **own** private, seeded RNG — reproducible and
    isolated from every other battle in the process (concurrent web sessions included). No
    seed → the battle **inherits the ambient** RNG, so `dice.seed_rng(n)` still seeds a whole
    single-battle run process-wide (back-compat). The instance's methods bind their RNG
    (`dice.using_rng`) so `combat.rng` is authoritative regardless of caller.
  - Entity ids come from the seeded RNG too (`entity_id = dice.new_id()`), so a seeded run
    reproduces ids (which feed `Entity` hashing/tie-breaks). Build entities *under* the seed
    (`with dice.using_rng(dice.new_rng(seed)): …`) when you need id reproducibility.

---

## 8. Project structure

An agent should know where a new file belongs without guessing — read the tree
(`src/` is the engine, `web/` the FastAPI app, `examples/` and `rules/` the JSON
content). Note `tests/` mirrors the engine; ignore `build/lib/` (stale untracked copy).
`src/arena/` is the headless agent-vs-agent harness (LLM benchmarking) — a *driver* over
the engine, not part of it; it depends on `src/combat`/`src/models`, never the reverse. See
[docs/current/AGENT_ARENA_PLAN.md](docs/current/AGENT_ARENA_PLAN.md). `src/arena/heuristic/` is the
utility-scoring `HeuristicAgent` — the arena's strong, tunable yardstick opponent (a pure,
read-only consumer of the engine; scores whole-turn plans by expected value). See
[docs/current/HEURISTIC_DECISION_MODEL.md](docs/current/HEURISTIC_DECISION_MODEL.md).

**Content invariants:**

- Coordinate axis swap: frontend cell units (x east, y south) ↔ backend feet
  (x east, y **up**, z south), `CELL_FEET = 5`. Conversions live in
  `web/routers/combat.py`; the constant is mirrored in `state.js` — keep both in sync.
- Adding a spell = a JSON file in `examples/spells/`; adding an entity effect = a JSON
  file in `rules/entity_effects/`. Both are scanned at startup.

---

## 9. Lessons Learned (append-only)

Durable lessons from real mistakes. **Append; do not rewrite.** Newest at the top. When
an entry stabilises into a general rule, promote it into the relevant section above and
leave a brief note here.

**Entry template:**

```
### YYYY-MM-DD — <short title>
- **Context:** what we were doing.
- **What went wrong:** the mistake or surprise.
- **Rule going forward:** the concrete, testable rule.
```

### 2026-09-24 — A mock that only speaks well-formed output proves nothing about real models
- **Context:** The Phase 1 review, before the first live pilot. The offline smoke ran every
  condition x scenario through the real runner with a mock model, and was green.
- **What went wrong:** the mock only ever wrote well-formed calls (plus one tidy "stumble"
  per condition). Fed the shapes real models and hosts actually send, the harness broke:
  - `""` or `"{bad json"` as tool arguments raised `JSONDecodeError` in the adapter.
  - `null` for an optional argument raised `TypeError` in the executor.
  - Both escaped as "harness bugs", which the study runner, by design, stops the whole
    grid on.
  - A move by menu `option_id` was accepted in C2+M. The schema no longer offered it, but
    the executor still honoured it, and hosts do not enforce schemas.

  Every test passed, because no test spoke like a real model.
- **Rule going forward:** a boundary that accepts model output must be tested with
  **realistic malformed payloads**, not only with the happy path and one designed slip.
  Test through the real path, and let a hostile mock run in the offline smoke. A guard
  expressed only in a schema or a prompt is a request, not a guarantee: enforce it where
  the value is consumed.

### 2026-09-24 — A check piped through `tail` cannot fail
- **Context:** Committing slice 3 of the interface study, chaining
  `black --check && flake8 && mypy src/ | tail -1 && pytest | tail -1 && git commit`.
- **What went wrong:** mypy found an error, but a pipeline's exit status is its *last*
  command's, and `tail` succeeded. The chain carried on, and the commit went in with a type
  error. The output did show "Found 1 error", but nothing acted on it.
- **Rule going forward:** in any chain that gates a commit, either run the check unpiped or
  `set -o pipefail` first. More generally, a gate is only as good as the exit status it reads;
  a check whose failure cannot stop anything is a comment.

### 2026-09-21 — Measuring at the configuration you designed measures your design, not the system
- **Context:** Quantifying how much the enumerated action menu's discretisation costs, by comparing
  the options it offers against the options a fine sweep proves reachable. Measured on the AoE
  scenario and registered the result in the pre-registration: **coverage 9/9 = 100%**, i.e. the menu
  is outcome-complete and costs nothing.
- **What went wrong:** that number was taken at the scenario's **opening position** — which is the
  formation its author deliberately arranged so the intended decision would be available. It is the
  single least representative board in the match. Sampling across the formations a match actually
  produces gave **75% minimum, 92% median**: the menu *does* lose options, just not in the tableau
  it was tested on. The figure was already written into the pre-registration, and had data been
  collected first, correcting it afterwards would have been indistinguishable from moving the
  goalposts. Nothing failed; every test passed; the measurement was simply of the wrong population.
- **Rule going forward:** a measurement over states must **sample the states the system will really
  be in**, and report the distribution — minimum, median, n — not a single frame. Prefer the
  *worst* case as the registered claim, because "this loses nothing" has to hold at the tightest
  moment, not on average. Be most suspicious when the sampled state is one you constructed: a
  fixture, a scenario opening, a hand-built example. Corollary, and the reason this is worth the
  entry: the metric was honest and the code correct — the error was entirely in *which* board it
  ran on, which no test can catch for you.

### 2026-09-21 — An identifier the model must retype is part of the interface under test
- **Context:** Building the recording layer for the action-interface study. Entity ids were 16
  random hex characters (`c735df5ef7697fb9`), drawn from the seeded RNG. The problem surfaced as a
  replay nuisance — two same-seed runs hashed differently because ids differed — and the first fix
  was to rebuild entities under the recorded seed.
- **What went wrong:** that fix was correct and beside the point. The study compares interface
  conditions, and under two of them the model must **emit** an entity id to name a target, while
  under the enumerated-menu condition it picks a short option id and never types one. An opaque hex
  id is therefore a transcription tax charged to some conditions and not others, and the failures it
  causes land in `unknown_target` — one of the very categories the headline hypothesis is stated in
  terms of. Part of the menu's "advantage" would have been that it spared the model a copying
  chore. Nothing in the tests could have caught this: every test passed, the ids were unique and
  reproducible, and the confound lives entirely in what the data would later *mean*.
- **Rule going forward:** when something is measured across conditions, audit every artefact the
  conditions **do not share** — not just the one you deliberately varied. An identifier, a
  formatting quirk, a field ordering: if one arm has to reproduce it and another does not, it is an
  independent variable whether you intended it or not. Fix it before the data exists, because
  afterwards it is a limitation rather than a control. (Second instance in this repo: the
  2026-09-15 raw-coordinate confound, where agents guessing feet produced 12–37 illegal moves a
  match until legal candidates were offered. Same shape, different surface.) Corollary: a
  *reproducibility* problem and a *validity* problem can have the same symptom; solving the first
  does not touch the second, so ask which one you actually have.

### 2026-09-21 — A guard that runs before the field it guards is a comment
- **Context:** Capturing per-decision telemetry. `RequestRecord.__post_init__` scrubbed API-key
  shapes out of the model's raw output before it reached the transcript.
- **What went wrong:** adapters construct the record with the timing and token counts they have,
  then assign `raw_output` as they parse the rest of the response. So the scrub ran at construction,
  against a field that was still `None`, and the real value — assigned a moment later — was never
  touched. An echoed key reached the saved JSONL. The code read as obviously correct; only a test
  that wrote a real transcript and grepped it for the secret exposed it.
- **Rule going forward:** put a sanitiser at the **serialisation boundary**, not in the
  constructor — the boundary is the one place every value must pass through and cannot be bypassed
  by a later mutation. More generally, when a guard and the data it guards are separated in time,
  test the guard *through the path that actually produces the data*, never by constructing the
  object the way the guard expects. (Same family as 2026-08-08's "shipped feature unreachable at
  the wiring seam" — the mechanism existed and looked complete, but nothing real ever reached it.)

### 2026-09-17 — A richer policy lost to a trivial one because a penalty had no counter-force
- **Context:** Benchmarking the utility-scoring `HeuristicAgent` against the weak `ScriptedAgent`
  yardstick. On the symmetric 2v2 melee scenario (`alpha_strike`) the heuristic won only ~35%,
  *worse* than scripted-vs-scripted's ~50-55% side baseline — the sophisticated agent lost to the
  dumb one.
- **What went wrong:** the exposure penalty (expected incoming damage at a position) is a **sum over
  every enemy that can reach you**, while the engagement reward that keeps a unit in the fight is a
  **max over enemies**. In a multi-enemy melee the sum dwarfs the max, so *after a melee unit spent
  its action attacking* — with no offense term left to anchor it — retreating (exposure→0) always
  outscored holding, and units backpedalled out of their own melee every turn, bleeding tempo. A
  low-HP self-preservation clause made it worse: cornered units fled a fight they couldn't escape.
  None of the unit tests caught it because they scored single decisions in 1v1s, where one enemy's
  exposure is small enough that engaging still wins.
- **Rule going forward:** when a scoring term *penalises the very thing a unit must do to be useful*
  (here, be in melee range), there must be a counter-force of comparable magnitude, or the action
  must not be offered at all. The fix gates disengage plans: a healthy pure-melee unit is never
  offered retreat/kite plans (it holds ground); only a ranged unit, or one hurt *and* able to
  actually outrun its pursuers, may open range. **And benchmark every heuristic against the trivial
  baseline on the scenario built to test it** — "beats Random" is not "beats a three-line if/elif."
  A policy that loses to the scripted agent on the scenario meant to showcase it is the loudest
  possible signal of a scoring bug.

### 2026-09-25 — A metric that cannot fail is not a metric
- **Context:** Pre-pilot review of the arena's measurement code. Two separate findings turned
  out to be the same mistake.
- **What went wrong:** `telemetry._sum_or_none` deliberately returns `None` — not `0` — when a
  provider reports no token usage, with a docstring explaining that "free" and "not reported"
  are different facts. Both consumers then wrote `telemetry.get("input_tokens") or 0`. So an
  unbilled cell cost `$0.0000`, the study's hard spend cap could never bind, and the cost metric
  would have published `0.000000` as a *result*. Separately, C1's parse layer folded "how much
  tolerance did the command need" together with "did the model also write prose", which made the
  best layer unreachable for any realistic response — so a registered bound read ~0 by
  construction and could not have come out any other way.
- **Rule going forward:** When you add a measurement, ask what value would falsify it and check
  that value is reachable. A number that can only come out one way — a cost that is always zero, a
  bound that is always nil, a guard that never trips — is telling you about the instrument, not the
  subject. Two specific corollaries: (1) a layer that preserves a distinction is worthless if its
  consumer coerces it away, so follow the value to every reader (same seam-auditing lesson as
  2026-08-08 and 2026-08-31); (2) one function must answer one question — `_layer` answering two
  made the cheaper answer silently win.

### 2026-09-03 — A hand-written schema needs a machine-checked link to the code it describes
- **Context:** Building the per-field block schema (`BlockContract.fields`) that lets the loader
  reject an unknown or malformed arg. The declarations are written by hand, next to each handler.
- **What went wrong (in waiting):** nothing yet — but a hand-maintained schema *always* rots, and
  here it rots dangerously in both directions. Add `block.get("x")` without declaring it and the
  validator rejects the arg you just added; declare a field nothing reads and the generated
  reference documents a lie. Neither shows up in ordinary tests.
- **Rule going forward:** when a declaration describes code, add a test that reads the code and
  compares. `tests/test_block_schema_drift.py` AST-parses the handlers for literal
  `block.get("...")` keys and checks both directions against the declared fields; a companion
  test fails if anyone introduces a *dynamic* key, since that would silently make the guard
  incomplete. Same pattern as `EXPRESSION_ROOTS` (checked against a real `eval_context`) and
  `CONTEXT_KEYS` (derived from `seed_context`). **Declare, then verify against reality** — a
  declaration nobody checks is a comment.

### 2026-09-03 — Deleting a validator with its legacy shape silently dropped a live check
- **Context:** Removing the legacy `RuleEngine` dispatch and the `triggers`/`effects` rule shape
  (SPELL_SYSTEM_REMAINING §1). `RuleLoader._validate_event_field_refs` — the load-time `event.<field>`
  typo check (E6) — validated that shape, so it went with it.
- **What went wrong:** I reasoned it protected nothing, because a native rule carries no top-level
  `condition` or `effects`. Wrong: a native rule's event references live *inside* its `trigger` blocks
  (`when`, `bindings`, nested block args). And at fire time `triggers._passes` catches `AttributeError`
  and returns `False` — so a typo is indistinguishable from "the guard was false". The deletion would
  have shipped a silent regression of exactly the bug E6 exists to prevent. Porting the check onto the
  block program found a live instance immediately: `petrified`'s DAMAGE_INCOMING trigger guarded on
  `event.attacker`, which that event does not carry, so its damage halving had **never fired**.
- **Rule going forward:** When deleting a validator along with the shape it validated, first ask what
  the *successor* shape can express that the check covered — a guarantee must be re-homed, not assumed
  redundant. And treat "the new form has no top-level X" as a claim to verify against the new form's
  nesting, not a conclusion. Corollary: a guard that swallows an exception to mean "didn't match" can
  never report a typo at run time, so its inputs must be validated at load.

### 2026-09-02 — A load-time validator needed the block catalogue, which nothing had imported
- **Context:** Building `spells.validate.validate_program`, the loader-boundary validator for native block
  `program`s (Phase 3 §5a). It checks each block against the process-global block `REGISTRY`.
- **What went wrong:** The full test suite passed, but a *loader-first* process (load a native spell before
  anything imports the evaluator/adapter) raised "unknown block type … registered: (none)". The block
  catalogue only populates when `src.spells.blocks` is imported (each block module self-registers on import);
  the evaluator and adapter do this via `from . import blocks`, but `validate.py` did not — so in the suite it
  worked only because some *other* import had already registered the catalogue. A registry-dependent module
  must not assume someone else populated the registry.
- **Rule going forward:** Any module that reads the block `REGISTRY` must itself import the catalogue
  (`from . import blocks as _blocks  # noqa: F401`) so it is self-sufficient regardless of import order. Smoke-
  test new loader/validation paths in a **fresh, minimal process** (a one-off script), not only via the full
  suite whose broad imports mask missing self-registration.

### 2026-08-31 — A condition's marker and its mechanics were joined only by a name string
- **Context:** Wiring conditions to apply in production (Phase 3 §3). A condition has two parts: a
  `Condition` marker (inert data on `entity.conditions`) and a reactive rule
  (`rules/entity_effects/conditions/<name>.json`) that makes it *do* something.
- **What went wrong:** `apply_condition` added only the marker; nothing installed the reactive rule. The
  two shared nothing but a name string, so every applied condition except charm was mechanically dead in
  production — yet it looked complete (marker model + full rule library + passing tests), because the tests
  installed the *rule* directly via `apply_effect` and never exercised `apply_condition`. Charm worked only
  because it bypassed `apply_condition` entirely (via `add_entity_effect` → the rule).
- **Rule going forward:** When one representation of a thing (a marker/flag/record) is meant to trigger
  behaviour defined elsewhere (a rule/handler), verify the code path that creates it also installs the
  behaviour — a shared *name* is not a wire. Test the real entry point (`apply_condition`), not the
  behaviour-half in isolation. (Same seam-auditing lesson as 2026-08-08; this is a fresh instance.)

### 2026-08-31 — On the block path a weapon's `pipeline_effects` is empty at fire time
- **Context:** Migrating Colossus Slayer to a native `ATTACK_HIT` trigger. The rider deals the *weapon's
  own* damage type via `event.action.primary_damage_type`, which reads `Action.pipeline_effects`.
- **What went wrong:** `AttackResolver._resolve_via_blocks` builds the `[attack_roll, damage…]` steps on the
  fly and passes the **raw** `AttackAction` to the evaluator — it never assigns them to
  `action.pipeline_effects` (deliberately, to avoid mutating the shared template). So at fire time the
  action's `pipeline_effects` is `[]` and `primary_damage_type` returned `None`, silently degrading the
  rider's damage to `GENERIC`. The legacy path had hidden this because it ran on a *copy* whose
  `pipeline_effects` was populated.
- **Rule going forward:** A reactive block reading off `event.action` at fire time must not assume the action
  was compiled into steps — a weapon's flat `damage`/`bonus_to_hit` list is the source of truth
  on the block path. `Action.primary_damage_type` now falls back to `damage[0]`. When a rider reads any
  action field, verify it is populated on the *raw* action the evaluator receives, not just on a compiled copy.
- _(2026-09-03: `pipeline_effects` is deleted; `primary_damage_type` reads `program` with the same
  flat-`damage` fallback, so the rule stands unchanged — a weapon's program is still built at resolve time
  and never assigned to the action.)_

### 2026-08-29 — Black must be version-pinned; the repo predates the 2024 style
- **Context:** Running `black src/ …` on files touched during the spell rework produced huge
  whole-file reformats (even on files with no functional change), inflating every diff.
- **What went wrong:** `pyproject.toml` only floored `black>=23.0`, so a fresh env resolved to
  Black 26.x. The repo is formatted to Black's **2023 stable style**; Black 24.0 changed the
  stable style (e.g. a blank line after a class docstring, import re-explosion), so any 24.0+
  Black rewraps the *entire tree* — nothing to do with the edit. `black --check` wants to
  reformat files never touched; the drift is version-driven, not line-length-driven (churns at
  any `--line-length`).
- **Rule going forward:** Black is now pinned `==23.12.1` in `pyproject.toml` — do **not** bump it
  without a deliberate, standalone "reformat the whole repo" commit. If your environment has a
  newer Black, **do not run it on modified files**; hand-match the surrounding style instead, and
  keep the commit to the functional change. (E501 is not enforced here — the tree has ~460 lines
  >79 chars; match neighbours, not flake8's default width.)
- _(2026-09-19 — **superseded, deliberately.** The 23.12.1 pin stopped holding: fresh envs kept
  resolving a modern Black, so `black --check` was permanent noise and the pin protected nothing.
  Taken via exactly the escape hatch this entry names — one standalone whole-repo reformat
  (`7c5b85c`), machine-verified behaviour-neutral (AST identical, string constants identical,
  docstring diffs trailing-whitespace only). Black is now pinned `==26.5.1`, and `[tool.black]`
  plus `.flake8` pin line length to **88** in-repo so no environment can disagree again.
  **E501 is now enforced**: all 246 over-length lines were wrapped and flake8 is clean, so the
  rule holds from a green baseline. The lesson itself stands — never bump Black incidentally; do
  it alone, verified, and re-pin exactly.)_

### 2026-08-08 — A structure-only test passed while the feature crashed
- **Context:** Reviewing the spell pipeline; the `grant_temporary_hp` step was documented
  and had a test.
- **What went wrong:** The step called a non-existent `Entity.gain_temporary_hp` and
  raised `AttributeError` on every use. It went unnoticed because the only test asserted
  the *JSON structure* the step parsed into and never executed the pipeline branch, and
  the one temp-HP spell reached temp HP through a different (entity-effect) path.
- **Rule going forward:** For any pipeline step or effect handler, write a test that
  **runs the pipeline and asserts the outcome** — parsing/shape assertions do not prove
  execution. Cross-check that each documented step type has an execution test.

### 2026-08-08 — A shipped feature was silently unreachable at the wiring seam
- **Context:** Per-creature damage resistance/immunity/vulnerability — the rules and
  multipliers existed, were unit-tested against hand-built `StatBlock`s, and were
  documented in the creature guide.
- **What went wrong:** `StatBlockLoader` never parsed those fields, so **no creature
  loaded from JSON could ever trigger them.** The feature looked done (model + rules +
  docs + tests) but was dead in real play because one wiring step was missing.
- **Rule going forward:** When a model field and its rules both exist, **prove the loader
  populates it and it fires in a real resolution**, end-to-end — don't trust unit tests on
  hand-built objects. Audit the *seams* between layers, not just each layer.

### 2026-08-08 — "Disabled" is not "broken" — check before deleting
- **Context:** WebSocket reconnection: the backend `rejoin_combat` handler was commented
  out, so a reconnect returned an "unknown command" error.
- **What went wrong:** It was easy to read as fundamentally broken, but the session store
  underneath was live and working — the feature was *disabled*, not defective, and likely
  would have worked if re-enabled. Deleting it discarded recoverable work.
- **Rule going forward:** Before characterising or removing code as dead, verify its
  *actual* state (git history, the other side of the wire). Half-wired features that can
  only error should be **either finished or removed with the decision recorded** — not
  left commented in place. Recoverable work lives in git history, so note the commit.
