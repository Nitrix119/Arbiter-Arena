# Final run findings: the action-interface study

> **Status: recorded 2026-10-04, straight after the final run, before the write-up.**
> This is the working record of what the data shows, kept so it survives session
> changes. The authoritative numbers are in `results/final/report/summary.md`, with CSVs
> beside it. The registered C1 parser audit is **done** (2026-10-05); see "The C1 parser
> audit".

## The run

- Frozen design: tag `study-freeze` (`52db99d`). The grid is
  `examples/study/final.toml`: 3 models × 4 conditions × 4 scenarios × seeds 101–110,
  plus 3 baselines, 600 matches in all.
- **Integrity: clean.**
  - 600/600 matches complete and 600/600 replay exactly (`study verify`).
  - No infrastructure exclusions, provider retries, responses cut at the token limit or
    unreported usage.
  - Each model was served by its single pinned host, under its registered name,
    throughout.
- **Cost:** $29.90 at list price (what the harness counts), $24.30 actually billed
  (Sonnet's prompt caching), against a ~$28.40 projection. About 31M tokens in all.
- **The C1 parser was not a factor.** Strict, primary and lenient scoring give
  identical C1 validity for every model, and no C1 response was unreadable. The
  study's original risk, a brittle parser making C1 look worse than it is (and so
  supporting H1 for the wrong reason), did not happen.

## Registered verdicts (prereg §7)

First-attempt validity, over fresh decisions:

| Model | C1 | C2 | C2+M | C3 |
|---|---|---|---|---|
| Nemotron 3.5 Lightning | 0.327 | 0.579 | 0.854 | 1.000 |
| Gemini 3.8 Flash | 0.991 | 0.986 | 0.999 | 1.000 |
| Claude Sonnet 5.5 | 0.981 | 0.893 | 0.979 | 1.000 |

| Model | H1 (C3 > C2+M > C2 > C1) | H2 (deficit is spatial) | H3 (constraint buys legality more than tactics) |
|---|---|---|---|
| Nemotron | **Supported: the full ordering**, every step clear | Supported (C1 and C2) | **Supported** (0.373 [0.212, 0.523]) |
| Gemini | Only C2+M > C2 (0.013, tiny); at the ceiling | Supported, small effect | Not supported (tactics saturated) |
| Sonnet | C3 > C2+M and C2+M > C2 supported; **C2 − C1 reversed: −0.088 [−0.117, −0.060]** | Supported (C1 and C2) | Not supported |

**Headline.** Constraining the action interface raises action validity exactly as
predicted, but the size of the effect depends on the model. For the weak model it is
transformative:
- Nemotron's validity goes from 33% in C1 to 100% in C3.
- Its win rate goes from 32% to 62%.
- In protect_squishy, the protected ally survives 6 times in 10 in C3, against 1–2 in
  10 elsewhere.

For a strong model it barely registers: Gemini is valid 99–100% of the time and wins
82–90% whatever the interface.

## The C1 parser audit (prereg §7, done 2026-10-05)

The audit was a blind hand-label of 200 fresh C1 first attempts. All were drawn from
accepted responses, because the parser refused none of the 2,966 (prereg §10,
2026-10-04). The sample was 74 from Nemotron, 71 from Gemini and 55 from Sonnet. The
report is `audit/audit_report.md`.

- **False reject:** zero by construction, since no response was refused.
- **False accept: 2 of 200, a rate of 0.010 [0.003, 0.036].** Neither shows a parser
  defect. Both are Sonnet, the only model that writes prose around its commands.
  1. **A dropped minus sign in the label.** The prose says "move west", and the command
     is `move to x=-38 z=0`, which is west. The parser read it correctly, and the label
     reads `x=38`.
  2. **A response that contradicts itself.** The prose weighs moving to (8, 3), then to
     (11, 4), and then commits to `move to x=10 z=4`. The labeller judged that no single
     action; the parser took the binding `ACTION:` line. Both readings are defensible.
- The registered rate is reported **as labelled**: 2 errors. Labels are not edited
  after the key is unsealed. The note above says that one is likely a labelling slip,
  which would put the parser's own error nearer 1 in 200.

**The decision rule for C1 < C2:**
- Nemotron: **supported** on all three checks (C1 0.327 against C2 0.579).
- Gemini: **not supported**.
- Sonnet: **not supported**. Its C1 is *above* C2.

Every C1 verdict in the table above therefore stands as registered.

**Sensitivity.** Even if C1 validity were overstated by the false-accept upper bound
(3.6 points), Sonnet's reversal would hold (0.981 − 0.036 = 0.945 > 0.893), as would
Nemotron's C1 < C2.

## Key findings

### 1. Sonnet: C2 is the one condition that hurts it, and the reason is specific

- **The reversal is robust.** Sonnet is *more* valid in free text (C1, 0.981) than with
  raw tool calls (C2, 0.893), the opposite of H1's prediction for that step, with the
  interval well clear of zero.
- **Most C2 misses are bookkeeping.** 56 times it attacked after its action was already
  spent, plus 36 moves onto occupied ground.
- **C2 is also Sonnet's worst condition tactically:**

  | | C1 | C2 | C2+M | C3 |
  |---|---|---|---|---|
  | Win rate | 0.800 | **0.600** | 0.775 | 0.825 |
  | Kiting survival | 10/10 | **4/10** | 9/10 | 10/10 |
  | Archer HP left after kiting | 6.6 | **2.1** | 9.7 | 16.1 |

- **What rescues it.** C2+M uses *exactly* C2's tool-call format but also shows the
  menu, and Sonnet is back to 0.979 validity and a 0.775 win rate. So the problem is not
  the tool-call format by itself. Sonnet does well if it can *either* reason in the open
  (C1) *or* see its options (C2+M, C3). Bare C2 removes both, and only there does it
  slip.
- **It reasons in the open in C1.** Sonnet wrote prose around 554 of its 918 C1
  commands. The prose is short working: distances, edge-to-edge gaps, whether it is in
  reach.
- **Its hidden reasoning was almost absent at `low` effort.** Its adaptive thinking
  judges these turns too simple to think about (see `PILOT_OBSERVATIONS.md`).
- **Link to prior work.** This fits Tam et al., *Let Me Speak Freely?* (EMNLP 2024,
  arXiv 2408.02442): restrictive output formats degrade reasoning by squeezing out the
  model's working, not through parsing failures. Our addition is that *showing the
  options* compensates for the lost working.

### 2. "Low" reasoning effort means different things per vendor

- Gemini at `low` deliberates briefly on most turns, at ~185–330 output tokens per
  accepted action.
- Sonnet at `low` rarely deliberates: in the pilot, 19 of 663 requests returned any
  reasoning.

This is a likely driver of finding 1, and of Gemini playing at the ceiling everywhere
while Sonnet's tactics depend on the interface. It was kept deliberately as a finding,
not normalised away (prereg §4, §9). The between-model comparison is exploratory:
capability, sampling and reasoning behaviour all differ between models.

### 3. The menu prevents friendly fire (H4b)

Allies caught per area-spell cast. Enemies caught per cast are similar across
conditions.

| Model | C1 | C2 | C2+M | C3 |
|---|---|---|---|---|
| Sonnet | 0.68 | 0.79 | 0.06 | **0.00** |
| Gemini | 0.13 | 0.18 | 0.00 | **0.00** |
| Nemotron | 1.30 | — | 1.46 | **0.13** |

The menu tags placements that would catch an ally, and models avoid them. Aiming
freely, they regularly hit their own side.
- This supports the *revised* H4b direction registered on 2026-09-21: on the area axis,
  enumerated aim can **beat** free aiming.
- Sonnet and Gemini benefit from the tag even in C2+M, where they still aim by raw
  coordinates.
- Nemotron in C2+M does not.

### 4. Nemotron's C2 is worse at winning than C1, despite better validity

- Win rate: C1 0.325, **C2 0.050**, C2+M 0.100, C3 0.625.
- In C2, 1,460 of its 1,614 fresh decisions were moves, including 754 refused
  moves to where it already stood (`no_effect`). In C1 it mostly attacked (600
  attack attempts, against 154 in C2).
- The tool-call format appears to pull the weak model into wandering rather than
  fighting. Validity and effectiveness come apart here.
- Nemotron also never ended its own turn in C1 or C2: the failure budget ended about
  78% of its turns there.

### 5. Gemini is at the ceiling, and the scenarios are solvable

- Validity is 0.99–1.00 in every condition.
- Its kiting is identical in every condition, and identical to the heuristic baseline's.
  That is because the outcome is fully determined once an agent shoots and retreats
  every turn on an unbounded battlefield; it was checked in the pilot and is not a bug.
- H3 cannot be tested for Gemini: its tactics are saturated.
- This was a deliberate design decision: the scenarios were not made harder after the
  pilot, since that would have been changing the study to suit the results. "Capable
  models do not need the options spelled out" is itself the result.

### 6. Cost

Dollars per *accepted* action, at list price:

| Model | C1 | C2 | C2+M | C3 |
|---|---|---|---|---|
| Nemotron | 0.000299 | 0.000415 | 0.000247 | **0.000118** |
| Gemini | 0.002115 | 0.002598 | 0.002309 | **0.001867** |
| Sonnet | **0.004118** | 0.006933 | 0.007173 | 0.004903 |

- For Nemotron, C3 is cheapest by far: no retries are wasted.
- For Sonnet, C1 is cheapest: no tool definitions in the prompt, and few retries.

### 7. Baselines, for scale

Win rate against the Scripted opponent:

| Baseline | Win rate |
|---|---|
| Heuristic | 0.800 |
| Scripted (its mirror match) | 0.475 |
| Random | 0.200 |

Gemini (0.82–0.90) plays at about the heuristic's level, as does Sonnet in C3 (0.825).

## Caveats for the write-up

- **No multiplicity correction** across the seven contrasts per model (prereg §9).
  These are robust:
  - Nemotron's full ordering
  - Sonnet's C2 reversal and its C2 tactical drop
  - the friendly-fire gap

  Treat a single borderline interval (e.g. Gemini's C2+M > C2, 0.013 [0.005, 0.025])
  lightly.
- **Exploratory, not registered:** the between-model comparison, the reasoning-effort
  explanation, and Nemotron's C2 wandering. They are observations with a plausible
  mechanism, not tested hypotheses.
- **Sampling differs between models** (prereg §9). Only Nemotron runs at temperature 0
  with a seed; Sonnet has no seed on any host.
- **Known limitation A30:** a move's path through a hostile creature is not checked.
  It applies equally to all conditions, but makes the positioning scenarios easier to
  escape.

## Still to do

1. ~~The C1 parser audit~~: **done** (see above).
2. **The write-up**, from `results/final/report/` (V1_PLAN Phase 4). Read *DungeonBench*
   (arXiv 2607.29577), which is close to this work.
3. **Tidy-ups:**
   - A34: the run header prints "6 models × 4 conditions × …" for 600 cells; the
     count is right, the bracketed breakdown misleads.
   - A33: show reasoning in the replay viewer.
   - A35: the audit's decision-rule table lists the three baselines as "not computable".
     They have no C1 or C2, so they should be left out.
   - Push the `study-freeze` tag.

## For a future study

A nudge to deliberate, either `medium` effort or a one-line prompt cue, may close
Sonnet's C2 gap entirely. It is the natural next experiment in the same harness. See
`PILOT_OBSERVATIONS.md`.
