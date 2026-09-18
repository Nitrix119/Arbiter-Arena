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
- [~] Choose two models, check tool support, top up OpenRouter if using free models.
      _(Top-up done; throughput unconstrained. Slate tentative; tool support still to preflight.)_
- [x] Check whether any scenario exercises AoE, and decide whether to keep the expressivity question.
- [x] Decide the licence (keep PolyForm NC and call it "source-available", or move to MIT/Apache-2.0).
- [~] Decide the name (keep, or neutral name plus "SRD 5.1-compatible" and a non-affiliation note).
- [ ] Review, then merge `feat/agent-arena` and `feat/deterministic-rng` to `main`.
      Bump to `0.2.0` per the branch workflow.
- [ ] Add GitHub Actions: `pytest`, `black --check` (pinned 23.12.1), `flake8`, on 3.11/3.13.
- [ ] Create branch `feat/interface-study`.
- [ ] Fill in `docs/PREREGISTRATION.md` from §3 as a draft. Freeze it in Phase 2.

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
- [ ] Typed error codes on `ToolExecutor` results (the §3.4 taxonomy), with a test per code.
- [ ] Capture token usage and latency in both adapters. Log per decision in the transcript.
- [ ] Log the **raw model output** per decision (text or tool call) and the parsed action.
      Scrub secrets; never log keys.
- [ ] Fix the OpenRouter empty-`choices` crash (CODEBASE_REVIEW A1) as a provider error, not a
      model failure.
- [ ] Manifest record in `match_start`: commit, scenario, seed, condition, model string, temperature,
      prompt hash, schema versions (`observation.v1`, `legal_action.v1`, `match_record.v1`).
- [ ] **Canonical state hash** per `turn_end` (sorted keys, normalised numbers).
- [ ] **`ReplayVerifier`**: re-execute recorded accepted actions with the same seed, no model, and
      compare hashes. Tests cover a scripted match and a match with rejected actions (does a
      rejection consume RNG?).

The three conditions:
- [ ] Refactor the action section of the prompt into a per-condition **`ActionInterface`** strategy
      (prompt text, tools, response decoder). Keep one `decide_one_action` skeleton, so there is no
      second agent loop (CLAUDE.md §2.7).
- [ ] **C1:** grammar, deterministic parser, prompt examples. Tests include adversarial and
      near-miss text.
- [ ] **C2:** the current tools with the menu stripped from the observation.
- [ ] **C3:** `enumerate_legal_actions` with stable deterministic IDs and a neutral candidate rule,
      plus a `choose(action_id)` tool. Every listed ID must execute successfully (a property test).
- [ ] **C2+M:** the current path, labelled as a condition.

Runner and analysis:
- [ ] Batch runner CLI (`python -m src.arena.study run --grid grid.yaml`): resumable, preflight,
      rate-limit backoff, spend cap, per-cell transcripts.
- [ ] Analysis script (`… study report`): transcripts to one CSV per decision and per match, plus a
      Markdown table and 2–3 plots. **Claude reads only this summary, never raw JSONL.**
- [ ] Offline smoke: all conditions × all scenarios with a **mocked** model, green in CI.

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
