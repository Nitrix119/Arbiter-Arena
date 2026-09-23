# V1.0.0 Plan — the Action-Interface Study

> **Status:** first draft, 2026-09-17. Supersedes the timeline in the external review
> (`DND_Auto_Battler_V1_Portfolio_and_Research_Review.md`, written against `d8c7072` — before
> the arena, heuristic, metrics, playback and seeded-RNG work existed).
>
> **V1 in one sentence:** *a stranger can clone the repo, run one command to reproduce a small
> published experiment on how an LLM's action interface affects its reliability, cost and tactics
> in a deterministic combat engine, and inspect why every action succeeded or failed.*

---

## 1. Where we actually are (gap analysis vs. the review)

| Review asked for | State today | Remaining |
|---|---|---|
| Per-match RNG, stable IDs | **Done** (`94e7a4a`: context-scoped RNG, `dice.new_id()`, `CombatSystem(seed=)`) | Merge to `main` |
| Observation contract | **Done** (`observation.py`, `InformationPolicy`) | Version tag (`observation.v1`) |
| Legal-action generation | **Mostly done** (`action_space.py`: targets w/ relation, move candidates) | Full enumeration with stable IDs for the menu condition (§3) |
| Agent interface, random + heuristic baselines | **Done** (Random, Scripted, utility `HeuristicAgent` + GA) | — |
| Engine validates & executes | **Done** (`ToolExecutor`, failure budget, rejection feedback) | Typed error **codes** (taxonomy), not just strings |
| Match runner, JSONL transcript | **Done** (`match.py`, `Transcript.save_auto`) | Batch runner; manifest fields |
| Browser replay | **Done** (`/playback`) | Show interface condition + raw model output |
| Metrics | **First slice done** (`metrics.py`) | Per-decision validity, recovery, cost; aggregation + CIs |
| LLM adapters | **Done** (Claude, OpenRouter) | Token/latency capture; empty-`choices` crash (CODEBASE_REVIEW A1); model preflight |
| Replay verification (state hashes) | **Not done** (GA regenerates from weights, not from recorded actions) | `ReplayVerifier` |
| CI, README, architecture doc, release | **Not done** | Phase 3 |
| Licence / SRD / trademark | **Undecided** (PolyForm NC; "D&D" in name) | Decision in Phase 0 |

Also note: `feat/agent-arena` (~25 commits) and `feat/deterministic-rng` are **not on `main`**.

**What that means:** you don't have a four-week build ahead of you. You have about a week of new
code (the three interfaces and the measurement around them), then API runs that are slow in
wall-clock time but cheap in Claude tokens, then writing.

---

## 2. The research question

**Working title:** *The Model Chooses, the Engine Decides: How Action-Interface Design Changes LLM
Agent Reliability in a Deterministic Tactical Environment*

**Primary question:** how do free-text, schema-constrained, and engine-enumerated action
interfaces affect an LLM agent's **first-attempt action validity**, **recovery**, **cost**, and
**tactical outcome**?

**Secondary questions**
- Does constraint improve tactics, or only formatting and legality?
- Which invalid-action categories survive each level of constraint?
- What does validator feedback buy in recovered actions, and at what token and latency cost?
- **Does enumeration hurt expressivity?** A menu discretises moves and AoE aim points, so it can
  take good options away. That trade-off is the most interesting and least-studied part of the
  question, so design for it (see §3.2).

**Why this isn't just D20Bench.** D20Bench *uses* a legal-action catalogue as its contract. This
study **ablates** that choice. Related work to read and cite before freezing the claim:
- D20Bench (github.com/bjedrzejewski/d20bench), including its `docs/ARCHITECTURE.md`.
- *Setting the DC: Tool-Grounded D&D Simulations to Test LLM Agents* (OpenReview).
- GameBench (arXiv 2406.06613) and SmartPlay (arXiv 2310.01557).
- Format-restriction effects on LLM reasoning: *Let Me Speak Freely?* (Tam et al., 2024).
  *Verify the citation.*
- Invalid-action masking in RL, e.g. Huang & Ontañón (2020). This is the classic
  "enumerate legal actions" precedent. *Verify.*
- Affordance grounding (SayCan) as the robotics analogue. *Optional.*

---

## 3. Experimental design — decisions to make carefully

### 3.1 The three conditions (proposed definitions)

| | **C1 FREE** | **C2 SCHEMA** | **C3 MENU** |
|---|---|---|---|
| Output | Plain text in a declared mini-grammar | Native tool call, raw params (names, entity ids, feet coords) | One tool: `choose(action_id)` |
| Legal menu shown? | No: state plus own capabilities only | No: state plus own capabilities only | Yes: every legal action, with stable IDs |
| Parser | **Deterministic** grammar parser. Never an LLM parser, which would add a second model. | Provider tool-calling plus engine validation | ID lookup plus engine revalidation |
| Can express arbitrary points? | Yes | Yes | No: discretised candidates only |

- **State observation is identical** in all three (same info policy, same JSON body). Only the
  *action section* of the prompt and the response channel differ. Hash every prompt variant.
- **The confound to name.** C3 changes two things at once: the output **format** and the
  **affordance** (the model is told what's legal). The existing production path (tool call *plus*
  the menu with `option_id`) is a natural 4th cell, **C2+M**, that splits the two. It costs no build
  time, only API calls. **Recommendation:** run it in the pilot. Keep it in the final run if the
  budget allows. Otherwise report it as a limitation.
- **C3 menu candidates must be generated by a neutral rule** (e.g. "move toward / away from each
  creature", "AoE centred on each creature"), **not** by the `HeuristicAgent`'s AoE search.
  Otherwise the menu smuggles in the heuristic's intelligence and inflates C3's tactics.
- **Menu size.** Enumerating attack × target, spell × target/point × slot and every move can
  get long. Cap and order it deterministically, and record menu length. It is a cost covariate
  (input tokens).
- **C1 grammar fairness.** Give the grammar and two or three examples in the prompt. A parse failure
  is the `malformed` category. Freeze the parser before the pilot and cover it with tests.

### 3.2 Everything else held fixed

| Factor | Proposed value | Why |
|---|---|---|
| Scenarios | Existing `kiting`, `alpha_strike`, `protect_squishy` | Already validated as skill-revealing; don't build new ones. **Check in Phase 0 whether any use an AoE spell.** If none do, the expressivity question (C3) can't show. Then add one small AoE scenario or drop that sub-question. |
| Opponent | Fixed non-LLM agent (`ScriptedAgent` or `HeuristicAgent`, chosen in the pilot) | Halves API calls and makes the opponent a controlled instrument. If the heuristic floors LLM win rate at 0%, use Scripted. |
| LLM side | Scenario's `llm_team`; plus a **side-swap** subset if budget allows | Controls side advantage |
| Information policy | One fixed policy (recommend current default) | Info sensitivity is a different study |
| Temperature | 0 (or provider minimum), recorded | Still not deterministic, so state that |
| Retry / failure budget | Existing 3-consecutive / 5-total, with rejection feedback | Report **first-attempt** *and* **eventual** validity |
| Round cap | Existing (~20) | — |
| Models | **2:** one free/cheap OpenRouter model plus one stronger paid model | Tests whether the effect depends on capability. Pin exact model strings; record the provider-returned model id. |
| Baselines | Random, Scripted, Heuristic through the **C3 path** (same executor) | Anchors the tactical metrics. Costs no API calls. |

### 3.3 Hypotheses (pre-register before the final run)
- **H1** First-attempt validity: C3 > C2 > C1.
- **H2** The C1/C2 validity deficit concentrates in **spatial** actions (move, AoE point) rather
  than attack or end-turn.
- **H3** Constraint improves validity **more than** it improves the scenario objective. The gap in
  tactical score between conditions is smaller than the gap in validity.
- **Exploratory, no direction predicted:** tokens and dollars per *accepted* action. C3 has a longer
  input menu but fewer retries.

### 3.4 Metrics (from the transcript; most already computable)
- **Primary:** first-attempt valid-action rate per decision.
- **Invalid-action taxonomy** (needs typed codes from the executor): `malformed_output`,
  `unknown_action`, `unknown_target`, `invalid_target_relation`, `out_of_range`,
  `destination_blocked`, `insufficient_resource`, `action_economy_spent`, `no_tool_call`.
- **Recovery rate:** P(valid on the next attempt | rejected).
- **Forfeit turns** (failure budget exhausted).
- **Cost:** input and output tokens per decision and per accepted action, latency, $ estimate.
- **Tactics:** scenario objective score (`kiting_adherence`, `protected_survival`, …), HP margin,
  win rate.
- **Replay verification rate:** should be 100%. It is a harness check, not a result.

### 3.5 Statistics and sizing
- Decisions within a match are **not independent**. Use a **cluster (match-level) bootstrap** for
  per-decision rates, and **Wilson** intervals for win rate. No Elo.
- Seeds are **paired** across conditions (same scenario and seed in every cell). LLM nondeterminism
  breaks pairing after the first differing decision, so say so.
- **Sizing:** ~35 LLM calls per match (2026-09-15 diagnostic).
  - 3 conditions × 3 scenarios × 10 seeds = 90 matches ≈ **3,200 calls per model**.
    Adding C2+M makes it 120 matches ≈ 4,200 calls.
  - OpenRouter free tier: 50 req/day unfunded, **1,000/day after a $10 top-up**. So a free model
    needs about **4 days** of background running. A paid model can finish in hours.
  - Validity effects are large and have hundreds of decisions per cell, so 10 seeds is plenty.
    Tactics differences will be **underpowered**. Report them honestly with CIs, as H3's
    "no clear tactical gain" reading rather than a strong claim.
- **Pre-declared exclusions:** a match is excluded **only** for provider/infra errors
  (HTTP 5xx, rate-limit abort), never for bad model behaviour. Re-run excluded seeds and report
  the count.

### 3.6 Risks to plan around
- **Free-model churn.** A pinned free model can vanish mid-run (it happened: `DEFAULT_MODEL` 404'd).
  Add a preflight before each batch. Prefer a model with a stable history, or accept a cheap paid one.
- **Tool-calling support varies**, which affects C2 and C3. Confirm both models support tools in
  preflight. C1 needs none.
- **Resumability.** A batch dies partway through a 4-day run. The runner must skip cells whose
  transcript already exists.
- **Claude Code token budget** (your binding constraint). See §6.

---

## 4. Phased plan and timeline

Tight but realistic. About **3 weeks to release**, plus a few days of buffer. "Session" means one
focused Claude Code work block. Phase 3 overlaps Phase 2's background runs on purpose.

| Phase | Dates (2026) | Claude-token intensity | Exit criterion |
|---|---|---|---|
| 0 Decide & consolidate | Fri 18 – Sat 19 Sep | Low | Branches on `main`, CI green, decisions recorded |
| 1 Build the study harness | Sun 20 – Fri 25 Sep | **High** | All 3 conditions run offline (mocked) end-to-end; replay verifies |
| 2 Pilot → freeze → final runs | Sat 26 Sep – Sun 4 Oct | Low (mostly waiting) | Frozen pre-registration; complete result bundle |
| 3 V1 hygiene (parallel with 2's runs) | Mon 28 Sep – Sun 4 Oct | Medium | README/architecture/licence/CI done |
| 4 Analyse, write, release | Mon 5 – Fri 9 Oct | Medium | `v1.0.0` tagged, article published |
| Buffer | Sat 10 – Tue 13 Oct | — | — |

### Phase 0 — Decide & consolidate (≈1–2 sessions)
- [x] Decide on the condition definitions (§3.1), including whether C2+M is in the final run.
      _(C2+M is **in** — 4 conditions. See the decisions log below.)_
- [x] Choose two models, check tool support, top up OpenRouter if using free models.
      _(Nemotron 3.5 + Gemini 3.8 confirmed, Claude Sonnet conditional on budget; **all via
      OpenRouter**. Tool-support preflight remains a Phase 1 build item.)_
- [x] Check whether any scenario exercises AoE, and decide whether to keep the expressivity question.
- [x] Decide the licence (keep PolyForm NC and call it "source-available", or move to MIT/Apache-2.0).
- [~] Decide the name (keep, or neutral name plus "SRD 5.1-compatible" and a non-affiliation note).
- [x] Review, then merge `feat/agent-arena` and `feat/deterministic-rng` to `main`.
      Bump to `0.2.0` per the branch workflow.
- [x] Add GitHub Actions: `pytest`, `black --check` (pinned **26.5.1**), `flake8`, **mypy**, on 3.11/3.13.
- [x] Create branch `feat/interface-study`.
- [x] Fill in `docs/current/PREREGISTRATION.md` from §3 as a draft. Freeze it in Phase 2.

#### Phase 0 decisions log (2026-09-19)

**Licence → Apache-2.0.** PolyForm NC was chosen early and arbitrarily; it is not OSI-approved and
works against a study whose value is that strangers can clone and re-run it. Apache-2.0 for the
patent grant and because it is the norm for research harnesses. Implementation (LICENSE, headers,
`NOTICE`, SRD attribution) lands in Phase 3.

**Name → change it.** "D&D Auto-Battler" is both a Wizards trademark risk and no longer accurate —
this is a benchmark harness, not an auto-battler. Direction: a neutral name plus an "SRD
5.1-compatible" descriptor and a non-affiliation note. Exact name still open; it is a Phase 3
deliverable, not a blocker.

**AoE / expressivity → keep the question, and build the support.** Finding: **no scenario uses any
spell at all** — `src/arena/scenarios.py` is weapon-attacks-only by design, so movement is currently
the sole discretised axis, and it is discretised because free movement was hurting a cheap model.
That makes C3's expressivity cost nearly invisible as things stand. Decision: design a proper AoE
schema and give it to the interfaces that should have it, with a **neutral candidate generator** —
sweep a moderate-resolution grid of aim points and keep one representative per distinct *set of
targets hit* (there is never a reason to offer two points that hit the same creatures). This keeps
§3.1's rule that the menu must not smuggle in `HeuristicAgent`'s AoE search. Scope lands in Phase 1,
and is assessed as **tractable**: the spell engine already resolves AoE thoroughly, so most of the
work is gathering and formatting information that exists and surfacing it to the agent, rather than
new mechanics.

> **Delivered 2026-09-21** (`9822c3b`, `09cefee`, `f83a41b`). `action_space.aim_candidates`
> implements the rule; `aoe_placement` is the scenario. The tractability assessment held — the
> work was surfacing information the engine already had. Two things the build changed:
> - **A live interface bug was found on the way.** `cast_spell`'s `target_point` schema required
>   `["x", "y"]` while the executor read `x`/`z`, so a model naming a ground point as x/y got a
>   `KeyError` → `malformed_output`. It fires in C1/C2/C2+M but never in C3, a between-condition
>   confound of the same class as the entity ids. Fixed in `6ad7dca`, along with stating the axis
>   convention in `SYSTEM_PROMPT` (a pre-freeze prompt change, since §3.1 hashes prompts).
> - **The rule turns out to be outcome-complete**, which changes what H4 can claim — see the
>   prereg §4.1.1 and the note below.

#### H4 measured, then corrected (2026-09-21)

Since 5e area damage has no falloff, the *set of creatures caught fully determines the outcome*,
so a menu offering every achievable target set would cost no expressivity at all. Whether it does
is a property of the grid resolution, so it was measured rather than argued.

**First answer, from the opening position: 9/9 = 100%.** That was registered, and it was wrong —
not arithmetically, but as a claim. A scenario's opening is the configuration its designer
arranged and therefore the least representative board in the match. Sampled across the formations
a match actually produces:

| Axis | Minimum | Median |
|---|---|---|
| Area aim points | **75%** | 92% |
| Move destinations | **33%** | 67–100% |

So enumeration costs a little on the area axis and a great deal on the movement axis. H4 is split
into **H4a** (the option-set ceiling, measured offline before any inference) and **H4b** (what
agents realise), with H4b's area direction *reversed* — free aiming can miscompute a coordinate
while a menu cannot, so C3 may beat C2 there. Both are registered in PREREGISTRATION §3, and the
superseded wording plus the corrected figure are logged in its §10.

The general lesson, which is also the contribution: **an action interface can be audited for
expressivity loss before a dollar of inference is spent — but the audit has to sample the states
the system will really be in, not the one you set up.**

**C2+M → in the study as a full condition (not pilot-only).** Definition: tool calls with raw params (C2's format)
*plus* the legal menu in the observation (C3's affordance), pinning one dial at a time so C3's
result can be attributed to format or to affordance rather than to both. It is **today's production
path** (`observation.py` always includes `legal_actions`; `tools.py` takes raw params), so it costs
no build time — C2 is the cell needing new work, by stripping the menu out. Rationale for including
it: without it, a C2/C3 difference has two candidate causes and the headline claim cannot be
attributed to either. Grid sizing therefore uses **4 conditions** (§3.5's 120-match figure, not 90).
Related: the `move` tool currently accepts *either* a menu `option_id` or raw `x`/`z`, letting the
model pick its own condition per decision; each interface must expose exactly one path. (Existing
transcripts predate this split and are functionality tests only — no data is lost by changing it.)

**Models → OpenRouter topped up ($15, 1,000 req/day).** Tentative slate: one cheap/free model
(Nemotron 3.5, slow), one strong model (Claude Sonnet/Opus), possibly Gemini 3.8 as a fast, cheap
middle point. Open: confirm **native tool-calling support for each** in preflight — C2, C2+M and C3
all require it, and a model without it can only run C1. Pin Claude to one route (direct adapter or
OpenRouter) and keep it fixed. **Throughput is not a constraint:** "free model" here means *a model
available on a free tier*, not one run for free — a paid Nemotron host costs cents per million
tokens and removes both the rate cap and the slow-host problem. So §3.5's "~4 days of background
running" does not apply; size the grid on cost and calls, not on the 1,000/day cap.

### Phase 1 — Build the study harness (≈5–7 sessions, TDD throughout)
Recording and instrumentation, first:
- [x] Typed error codes on `ToolExecutor` results (the §3.4 taxonomy), with a test per code.
      _(`src/errors.py`: `RuleViolation(ValueError)` carrying a code, raised at ~12 engine sites;
      `src/arena/error_codes.py` adds the agent-side codes. See the taxonomy note below.)_
- [x] Capture token usage and latency in both adapters. Log per decision in the transcript.
      _(`src/arena/telemetry.py`; `Agent.last_telemetry()`. Recorded **per request** and summed,
      since a decision takes two requests when the model is re-prompted — per-decision
      accounting would under-report exactly the decisions being compared. Also captures the
      provider-returned `served_model` (§3.1) and `finish_reason`. `Manifest.temperature` now
      has a source: `OpenRouterAgent(temperature=0.0)` per §3.2; the Claude adapter records
      `effort`, its actual sampling knob.)_
- [x] Log the **raw model output** per decision (text or tool call) and the parsed action.
      Scrub secrets; never log keys. _(Response content only — a request is never logged, so no
      key can reach a transcript by construction; `telemetry.scrub()` is defence in depth at the
      serialisation boundary.)_
- [x] Fix the OpenRouter empty-`choices` crash (CODEBASE_REVIEW A1) as a provider error, not a
      model failure. _(`ProviderError`, a `NoToolCallError` subclass → the `provider_error` code.)_
- [x] Manifest record in `match_start`: commit, scenario, seed, condition, model string, temperature,
      prompt hash, schema versions (`observation.v1`, `legal_action.v1`, `match_record.v1`).
      _(`src/arena/manifest.py`; `run_match(manifest=…)`. The seed stays the transcript's own
      field — one authority, not two copies that can disagree.)_
- [x] **Canonical state hash** per `turn_end` (sorted keys, normalised numbers).
- [x] **`ReplayVerifier`**: re-execute the recorded decisions with the same seed, no model, and
      compare hashes. _(`src/arena/replay.py`; `verify()` per match, `verify_bundle()` for §5.)_
      - **Built differently from this line's original wording, deliberately.** Re-executing only
        the *accepted* actions desyncs: a turn ended by the failure budget is ended by the driver
        calling `end_turn` directly, so it never appears as an action. A `ReplayAgent` instead
        feeds every recorded call — rejections included — back through the ordinary `run_match`,
        so the driver reproduces forced ends itself and there is still one execution path.
      - **Answered:** a rejection consumes **no** RNG — every engine validation precedes the
        first roll. Asserted by a test that replays a match full of rejections, not assumed.
      - The earlier note about rebuilding entities under the recorded seed is **obsolete**:
        entity ids are now derived from the roster, so a replay needs only the scenario.

#### Entity ids are a fairness control (2026-09-21) — belongs in the frozen method

Combatant ids are readable and roster-derived (`archer`, `fighter-a1`, `raider-2`) rather than
random hex. This is **not** cosmetic and not for replay's benefit. Under C1 and C2 the model must
*type* an entity id to name a target; under C3 it picks an `action_id` and never does. A
16-hex-character id therefore taxes some conditions and not others, and the resulting failures
land in `unknown_target` — one of the very §3.4 categories H2 is stated in terms of. Left alone,
part of C3's measured advantage would have been "it didn't have to copy a hex string" rather than
the affordance the study isolates. Same class as the 2026-09-15 raw-coordinate confound.
Record it in `PREREGISTRATION.md` as a control, not a note.

#### Taxonomy deviations from §3.4 (2026-09-21) — settle before the prereg freezes

The §3.4 draft list was written before the codes met the engine's real refusal sites. Three
changes, all made to keep the categories from blurring:

- **`not_your_turn` added.** `_assert_active` is "it is not your turn", which is not
  `action_economy_spent` ("you already acted"). Different mistakes.
- **"Cannot afford" splits by the actual shortfall**, not by the cost's shape: a spent action
  is `action_economy_spent`, spent movement or an exhausted slot is `insufficient_resource`.
  Lumping them would blur the two most common refusals.
- **`invalid_target_relation` widened** to cover an illegal *parameter combination* — today
  only "cast at a slot below the spell's base level", which fits no other category. If the
  pilot shows this firing often, split it out before the freeze.
- **`provider_error` and `engine_error` added** as non-model buckets: the first is the §3.5
  infra exclusion, the second should stay at zero and exists so an untyped refusal path is
  visible rather than silently joining a real category.

The three conditions:
- [x] Refactor the action section of the prompt into a per-condition **`ActionInterface`** strategy
      (prompt text, tools, response decoder). Keep one `decide_one_action` skeleton, so there is no
      second agent loop (CLAUDE.md §2.7). _(`src/arena/interfaces.py`; a test asserts the assembled
      prompts differ **only** in the action section.)_
- [x] **C1:** grammar, deterministic parser, prompt examples. Tests include adversarial and
      near-miss text. _(`src/arena/free_text.py`; the corpus is `tests/arena/test_free_text.py`.
      Built in two slices, 2026-09-24. See the §10 closing notes.)_
- [x] **C2:** the current tools with the menu stripped from the observation.
- [x] **C3:** `enumerate_legal_actions` with stable deterministic IDs and a neutral candidate rule,
      plus a `choose(action_id)` tool. Every listed ID must execute successfully (a property test).
      _(`src/arena/enumeration.py`; the property test runs every id through the real executor.)_
- [x] **C2+M:** the current path, labelled as a condition.
- [x] Measure what each menu's discretisation costs (`aim_coverage`, `move_coverage`,
      `sample_coverage`) — not on the original checklist; added because H4 is untestable without
      it. See §9.

Runner and analysis:
- [x] Batch runner CLI (`python -m src.arena.study run grid.toml --out …`): resumable, preflight,
      rate-limit backoff, spend cap, per-cell transcripts. _(The grid is **TOML**, read by the
      stdlib `tomllib`, not YAML, which would have added a dependency.)_
- [x] Analysis script (`python -m src.arena.study report …`): transcripts to one CSV per decision
      and per match, plus a Markdown summary. **Claude reads only this summary, never raw JSONL.**
      _(Plots deferred to Phase 4: ledger A11.)_
- [x] Offline smoke: all conditions × all scenarios with a **mocked** model, green in CI.

### Phase 2 — Pilot → freeze → final runs (≈2 sessions, then waiting)
- [ ] Pilot: 1 model × 4 conditions × 3 scenarios × 2 seeds (~24 matches).
- [ ] Fix **only** correctness and method issues (parser bugs, menu bugs, crashes), not results
      you dislike.
- [ ] Pick the opponent (Scripted vs Heuristic), decide on C2+M, confirm call counts and cost per match.
- [ ] **Freeze:** tag the commit (`study-freeze`), finalise `PREREGISTRATION.md` (hypotheses,
      metrics, exclusions, seeds, prompts plus hashes, models, settings).
- [ ] Launch the final grid in the background, outside Claude Code. Check once a day.
- [ ] Baselines through the C3 path (free, fast).
- [ ] 100% replay verification over the result bundle.

### Phase 3 — V1 hygiene (parallel with Phase 2 runs; ≈3 sessions, use a cheaper model)
- [ ] README rewrite: subtitle "a deterministic evaluation harness for tool-using LLM agents",
      60-second quick start, **no-API-key demo command**, result chart (placeholder), limitations.
      Remove stale `RuleEngine`/"future goals" text.
- [ ] `docs/ARCHITECTURE.md` (one page plus one diagram). Move superseded plans to `docs/archive/`
      with a "historical" banner.
- [ ] Licence change or wording; `NOTICE`/SRD attribution (CC BY 4.0 text); content provenance
      list; trademark non-affiliation statement.
- [ ] `CITATION.cff`, `CHANGELOG.md`.
- [ ] Playback page shows condition, raw model output and error code per action.
- [ ] Fresh-clone test on a clean venv: install, tests, demo command.

### Phase 4 — Analyse, write, release (≈3–4 sessions)
- [ ] Run the report on the frozen bundle, write up H1–H3 as confirmed or not, then exploratory
      findings.
- [ ] Pick **one failure story**, a replay that illustrates the headline (e.g. fluent reasoning
      leading to an impossible spatial action in C1, vs a legal but weaker choice in C3).
- [ ] Article (~2,500–3,500 words), structure below. **Write the motivation, the surprises and the
      "what I decided" sections in your own voice.** That is the ownership evidence the review
      stresses.
- [ ] Threats to validity: one environment; 2 models; format and affordance confound; menu
      discretisation; LLM nondeterminism; tactics underpowered; neutral-prompt choice.
- [ ] Release bundle: transcripts (non-sensitive), CSVs, prereg, prompts, report. Zenodo DOI optional.
- [ ] Bump to `1.0.0`, tag `v1.0.0`, GitHub release notes.
- [ ] Short demo GIF or video; update CV/LinkedIn with the **measured** numbers.

**Article outline:** (1) problem: models propose, software must preserve invariants; (2) why a
deterministic tactical engine is a good controlled environment; (3) architecture: observation →
interface → validator → executor → recorder; (4) the conditions; (5) setup and reproducibility;
(6) results, with the taxonomy not just win rate; (7) failure story; (8) implications for
production tool-using agents; (9) limitations; (10) reproduce it.

---

## 5. V1.0.0 definition of done
- [ ] `main` contains all arena, RNG and study work; CI green with a badge.
- [ ] `pip install -e ".[web,dev]"`, then one no-key command runs a match and writes a verifiable transcript.
- [ ] One documented command reproduces the report from the published bundle.
- [ ] Pre-registration frozen *before* the final-run commit (visible in git history).
- [ ] Replays verify 100%; transcripts contain no secrets.
- [ ] README, ARCHITECTURE and limitations match the code; historical docs labelled.
- [ ] Licence, SRD attribution and naming resolved.
- [ ] Article published and linked from the README; `v1.0.0` tagged.
- [ ] You can explain, without notes: one resolution path, block validation, the action-interface
      design, one real bug found by a test, and what Claude Code did vs. what you decided.

**Explicitly not V1:** leagues/Elo, LLM-vs-LLM, team coordination studies, hidden-information
studies, new spells/creatures/rules, hosting, more providers, GA tuning, the regret metric (Family I).

---

## 6. Working within the Claude Code token limits
- **One checklist item cluster per session.** Open with "Read `docs/current/V1_PLAN.md` §4 Phase N, do items
  X–Y", not "look around the repo". Exploration is the biggest hidden cost.
- **Trim always-loaded context.** `CLAUDE.md` is loaded every session, and §9 keeps growing.
  Consider moving §9's full entries to `docs/LESSONS.md` and leaving one-line rules in place.
  Moving superseded docs to `docs/archive/` stops agents reading them.
- **Match model to task.** Use Opus for the C3 enumeration, replay verifier and analysis
  design. Use Sonnet or Haiku for CI YAML, README, `CITATION.cff`, licence text and test scaffolding.
- **No subagents** unless you ask for one; they re-derive context from cold.
- **Targeted tests while iterating**, and the full suite once per session at the end.
- **Never have Claude watch or read long runs.** Launch batches in your own terminal. Claude reads
  the compact report only.
- **Mocked model for all build work.** Real API calls only in the Phase 2 pilot and final run, per
  the standing cost rule.
- **Heaviest token week is Phase 1.** Start it at the beginning of a weekly-limit window if you can.

---

## 7. Phase 0 closing note (2026-09-19)

Phase 0 is **complete** apart from two items deliberately carried into Phase 3 (the
final repository name, and implementing the Apache-2.0 relicence — both decided, not
yet executed).

Landed on `main`: the arena + deterministic-RNG merge (#4), `0.2.0`, and the toolchain
branch (#5) — whole-tree Black 26.5.1 reformat, **mypy 43 errors → 0**, **flake8 → 0
with E501 enforced at 88**, and GitHub Actions running tests on 3.11/3.13 plus
format/lint/types. First CI run was green on all three jobs.

One real bug was found on the way, by mypy, behind what looked like a typing nit:
`move_entity` spent fractional Euclidean movement costs against an `int` budget, so any
diagonal move drifted (`30 → 22.9 → 15.799999999999999`). The residue reached
`can_afford`, the web UI, and the movement budget shown to LLM agents. Fixed in
`2280157`; the SRD reasoning for continuous measurement is recorded in the code.

**Sizing changed.** Adding the AoE scenario makes the grid 4 conditions × **4**
scenarios × 10 seeds = **160 matches per model** (~5,600 calls), up a third from the
original 3-scenario figure in §3.5. Accepted deliberately: H4 (expressivity cost) is
untestable without a spell in play, since no existing scenario casts one.

Next: Phase 1, beginning with recording and instrumentation (typed error codes, token
and latency capture, raw model output, manifest, state hashes, `ReplayVerifier`) before
the three interfaces are built.

---

## 8. Phase 1 recording-cluster closing note (2026-09-21)

**The recording and instrumentation block is complete.** Everything a match does is now
recorded in a form the study can measure, and a recorded match can be proved to
reproduce. 1,050 tests green; flake8, mypy and Black clean throughout.

What landed, in order: typed error codes (`src/errors.py`, `src/arena/error_codes.py`);
the A1 provider-error fix; the `match_start` manifest and per-`turn_end` state hash
(`src/arena/manifest.py`); readable roster-derived entity ids (`src/arena/setup.py`);
per-decision telemetry (`src/arena/telemetry.py`); and `ReplayVerifier`
(`src/arena/replay.py`).

**Three decisions worth carrying forward.**

1. **Entity ids became a study control**, for the reason recorded in §4 above. This was
   not on the checklist — it surfaced from the replay work and turned out to matter more
   for validity than for replay. It must be in the pre-registration.
2. **The §3.4 taxonomy grew** (see the deviations note in §4). It freezes in Phase 2, so
   the one open question — whether `invalid_target_relation` should split — should be
   settled from pilot data.
3. **`ReplayVerifier` drives the real turn driver** rather than re-executing accepted
   actions, because forced turn ends are not recorded as actions. Anything later that
   re-runs a match should reuse `replay.ReplayAgent` rather than invent a second path.

**Two bugs the tests caught, both of the "looks done, does nothing" kind** that §9 of
CLAUDE.md keeps collecting:
- the secret scrub sat in `__post_init__` while adapters filled the guarded field in
  afterwards, so it protected nothing and a key reached the saved JSONL;
- the drift guard for error codes could not read a code chosen inside a helper, which
  would have silently stopped covering the two most common refusals.

---

## 9. AoE cluster closing note (2026-09-21)

**The AoE support and its scenario are done** — the last outstanding Phase 0 commitment.
1,089 tests green; flake8, mypy and Black clean. Landed in five commits: the
`target_point` contract fix (`6ad7dca`), `aim_candidates` (`9822c3b`), `aim_coverage`
(`09cefee`), the `aoe_placement` scenario (`f83a41b`) and a spell-slot key-type fix
(`2711f36`).

**Chosen ahead of the `ActionInterface` deliberately.** The dependency runs one way —
C3's enumerator must list aim points, while AoE needs nothing from the interface layer —
so building AoE second would have forced C3's candidate schema, ordering and cap policy
to be reopened, the cap especially, since it can only be calibrated against a real
candidate distribution. That judgement was vindicated twice over: the `target_point` bug
was found only because this work exercised a path no scenario had ever touched, and the
menu-length figure (9 aim points versus ~4 attack entries) is exactly the number a cap
has to be set against.

**What must not be lost before the freeze:**

1. **H4's area arm is null by design** (§ Phase 0 note above, prereg §4.1.1). Registered
   in advance with the measured coverage, so the null is a prediction rather than a
   post-hoc excuse. The live H4 test is the movement axis.
2. **The menu is neutral by construction and by test** — lexicographic ordering, no
   import of `heuristic/`, ally- and self-catching options offered and tagged rather
   than hidden. A future change that sorts by "most enemies hit" would silently make C3
   look smarter than it is.
3. **The `SYSTEM_PROMPT` axis sentence is part of the measured interface.** It was added
   pre-freeze on purpose; §3.1 hashes prompts, so editing it later is a deviation.

**Sizing is now as §7 anticipated:** 4 conditions × 4 scenarios × 10 seeds = 160 matches
per model.

---

## 10. ActionInterface cluster closing note (2026-09-21)

**Three of the four conditions are built.** 1,158 tests green; flake8, mypy and Black
clean. Six commits: the `ActionInterface` seam (`99557a5`), the move dual-path fix
(`17766eb`), C3 (`1dc8c0a`), coverage (`f77e3a6`) and docs.

`src/arena/interfaces.py` holds one strategy per condition — prompt section, observation
shaping, tool set, response decoding — behind a registry. `SYSTEM_PROMPT` split into a
shared world model plus a per-condition action section, and a test asserts the assembled
prompts differ **only** in that section: the §3.1 guarantee, machine-checked.

- **C2** — raw params, no menu. **C2+M** — raw params, menu shown. **C3** —
  `choose(action_id)` over `enumerate_legal_actions`, with every listed id proven to
  execute through the real `ToolExecutor`.
- **C1 is not built** and declines loudly rather than degrading. Its grammar and parser
  are the longest, least bounded item left and must be frozen and adversarially tested
  before the pilot. The seam is ready for it: `interpret` already receives
  `record.raw_output`, so C1 needs a parser, not a second agent loop.

**Two defects closed on the way.** The `move` tool accepted either a menu `option_id` or
raw coordinates, letting a model pick its own condition per decision — Phase 0 flagged
it and nothing had fixed it. And `render_observation`'s instruction line said "study the
battlefield and your legal options", condition-specific text sitting in the *shared*
body, false under C2.

**One gap declared rather than hidden:** multi-target spells (Magic Missile, Scorching
Ray) are enumerated nowhere, so a C3 agent cannot cast one. No study scenario casts one,
but `multi_target_spells_not_enumerated` makes it visible and a test keeps the scenarios
clear of it.

**What must survive to the freeze:** the prompt split changes every prompt hash (§3.1
records them); the menus' neutrality is enforced by tests, and a future sort by "most
enemies hit" would silently make C3 look smarter; and the corrected H4 figures in §9.

#### The C1 question to settle *before* building it (2026-09-21)

C1 is not just "the remaining condition" — it carries a tension the other three do not,
and it should be discussed before a line of parser is written.

**The constraint:** §3.1 forbids an LLM parser, because a second model inside the
measurement means a C1 failure could be the parser's rather than the agent's, and the
study could no longer attribute anything.

**The risk:** a fully deterministic grammar parser may not reach acceptable *fairness*.
If it rejects phrasings a reasonable reader would accept, C1's `malformed_output` rate
measures parser brittleness rather than the free-text interface — and H1 predicts C1 is
worst, so a brittle parser would *confirm the hypothesis for the wrong reason*. That is
the most dangerous shape of error available to this study.

**Options, none yet chosen:**
1. A permissive deterministic parser (synonyms, loose ordering, fuzzy entity matching),
   with an adversarial corpus written *before* the pilot and a documented accept/reject
   boundary.
2. A strict grammar with worked examples in the prompt, accepting that C1 partly
   measures instruction-following — and saying so as a limitation rather than a finding.
3. Drop C1, run three conditions, and report the free-text arm as out of scope.

**Whichever is chosen, the parser must be frozen before the pilot and its accept/reject
boundary published**, or C1's numbers are not interpretable. A useful pre-commitment:
hand-label a sample of real model outputs and report parser agreement with the labels,
so parser error and agent error are separable after the fact.

Next: settle the above, then **C1**, then the batch runner and the analysis script.

> **2026-09-24:** the options, a recommendation and four prerequisite wiring fixes are
> written up in [`C1_PARSER_OPTIONS.md`](C1_PARSER_OPTIONS.md). **Decided 2026-09-24:** every
> recommendation in its §9 accepted. Build order: slice 1 (parity prerequisites), then the parser.

#### C1 slice 1 closing note (2026-09-24) — parity prerequisites done

Three fixes to the **already-built** conditions, each one needed before a C1 parser could be fair.
1,198 tests green; flake8, mypy and Black clean.

- **Own capabilities in the shared body** (`b7e0fb4`). Under C1/C2 a creature's own attack and
  spell names lived only in the stripped menu. The Mage could see the raiders' Greatsword but not
  its own Dagger. That was a **live C2 confound**, and C2 → C2+M was measuring "being told what you
  are" as well as affordance. Kept out of the state snapshot so recorded hashes are unaffected.
- **Coded interface refusals** (`4b1198b`). A C3 invented `action_id` used to get an uncounted
  free retry and was then logged as `no_tool_call`. It is now `unknown_target`, counted and fed
  back exactly like a C2 executor refusal. Replay re-raises it by the same route. C1's
  unparseable lines will use this path as `malformed_output`.
- **Shared identifier resolver** (`d3f4151`). Tolerant of spelling (`Raider 1` = `raider-1`),
  strict about identity (no edit distance), with ambiguity refused. One resolver serves every
  raw-parameter condition, so C1 gets nothing C2 lacks. A scenario test keeps the study
  rosters free of key collisions.

All three change measured behaviour before the freeze, and all three are recorded in
PREREGISTRATION §4.2 and §6. Prompt hashes change, which is expected.

Next, slice 2: the adapters must handle an empty tool list, rejection feedback must be formatted
per interface, then the Lark grammar, the layered parser, the §8 corpus and the round-trip property
test.

#### C1 slice 2 closing note (2026-09-24) — all four conditions are built

C1 runs end to end offline. 1,287 tests green; flake8, mypy and Black clean. Six commits: the
issues ledger (`36194e4`), adapters with an empty tool list (`7936b66`), per-condition rejection
feedback (`2ae97b2`), the parser (`992e364`), the interface (`68c5e14`) and a whole offline C1
match (`1a7af3d`).

- **The parser** (`src/arena/free_text.py`) is a pure function of the text. Its Lark grammar is a
  module constant, so the published grammar and the executed one are the same string. The
  accept/reject boundary is a test table. Every accepted action records its parse layer, derived
  by comparing the text with the canonical rendering of what was read.
- **C1 can say everything C3 can list.** This is proved by a round-trip test over every
  enumerated action in every scenario, at the opening and through a scripted match.
- **A whole C1 match plays, records and replays at 100%.** A mocked model writes the scripted
  policy's decisions as text, and everything after that is the real path.
- **`lark` is a core dependency**, amended from the options doc's `[agents]` extra, because the
  parser is harness code.

Found on the way and logged in the CODEBASE_REVIEW §8 ledger, not fixed inline:

- **A3 checked.** An area spell aimed at a creature is a typed `unknown_target`, identical in C1
  and C2. That leaves only a taxonomy question.
- **A8.** A trailing justification ("…with Dagger since it's adjacent") is read into the name. It
  is pinned as a known boundary for the pilot to decide.
- **A9.** Call arguments reach the transcript unscrubbed, in every condition.

Also fixed: the prompt-identity tests had covered only C2 and C2+M, never C3. They now cover all
four conditions.

PREREGISTRATION now records the as-built C1 (§2), its refusal coding (§6), and the three-parser
reporting and the audit decision rule (§7).

Next, slice 3: the batch runner and the analysis script, with the offline strict/lenient
re-scorer, the first-attempt metric (ledger A2) and the audit labelling tool.

#### Slice 3 closing note (2026-09-24) — the pilot can run

The runner, a mock model and the report are built. 1,355 tests pass; flake8, mypy and Black
are clean. Split from the re-scorer and audit tool at the user's choice: those need real C1
output, and this slice is everything the Phase 2 pilot needs.

- **`src/arena/study.py`** runs every cell through the ordinary `run_match`:
  - Each transcript is written atomically to a fixed path, so a resume skips finished cells.
  - Cells run seed by seed, so an interrupted run leaves paired sets.
  - Infrastructure failures are set aside and retried with backoff. Any other exception is a
    bug and stops the run. A retry loop must never hide a defect.
  - Spend is recomputed from disk at start, so the cap survives a resume.
  - A preflight check fails a dead or tool-less model before the first cell.
  - Only `openrouter` and `mock` providers exist, per prereg §5.
- **`src/arena/mock_model.py`** lets the scripted policy decide, then writes each decision in
  the condition's own format, including deliberate stumbles, through the real decision path.
- **`src/arena/study_report.py`** produces the registered measurements with the standard
  library only, deterministically. Its definitions are now in PREREGISTRATION §6–§8.
- **A null control for the whole study.** The mock makes identical decisions in every
  condition, and a test requires identical outcomes on every paired scenario and seed. The
  harness can change what a decision costs, never what it does.

Found and fixed on the way: menu length was never recorded (ledger A10); `aoe_placement` was
missing from the metrics scope table; the report briefly imported `random` directly, against
CLAUDE.md §7. Logged: A11 (plots) and A12 (two older modules import `random`). A mypy error
reached one commit because a check was piped through `tail`, which hid its exit status. It
was fixed in the next commit, and CLAUDE.md §9 records the lesson.

Next, slice 4: the offline strict/lenient re-scorer and the terminal audit-labelling tool.
Then the Phase 2 pilot, with your go-ahead.
