# Pilot observations: reasoning effort, menus and output format

> **Status: exploratory, recorded 2026-10-01, before the final run.** These notes come
> from the three Phase 2 pilots (`results/pilot-2`, `results/pilot-gemini`,
> `results/pilot-sonnet`). The pilot is **not data** (prereg §4.4): 8 matches per
> condition, and 2 per scenario per condition. Nothing here is a result. It is a
> pattern worth checking against the final run, which records reasoning and prose on
> every call, and a hypothesis-generating note for the write-up.

## What was seen

| | Gemini 3.8 Flash (`low`) | Claude Sonnet 5.5 (`low`) |
|---|---|---|
| Requests that returned reasoning | most turns, ~180–320 output tokens per decision | 19 of 663 (2,773 tokens in all) |
| First-attempt validity, C1 / C2 / C2+M / C3 | 0.99 / 0.98 / 0.995 / 1.00 | 0.99 / 0.90 / 1.00 / 1.00 |
| Win rate by condition | 0.875 everywhere | 0.50–0.75 |
| Kiting survived (out of 2), C1 / C2 / C2+M / C3 | 2 / 2 / 2 / 2 | 1 / 0 / 1 / 2 |
| C1 responses with prose around the command | rare | 97 of 172 |

## A reading of it

**1. "Low" is two different contracts.** Gemini's `low` is a smaller thinking
*budget*: it still deliberates briefly every turn. Sonnet 5.5's thinking is
*adaptive*: at `low` the model decides whether a turn warrants thought, and it judged
almost none of these turns to. Same label; one is "think a little, always", the other
"think only if it seems needed".

**2. The turns are less simple than they look.** Kiting turns on a small calculation
each turn: the bruiser moves 30 ft, the archer 40 ft, so after shooting the archer must
end far enough away. A couple of hundred tokens of thought catches that; none misses
it. The one reasoning sample captured from Sonnet in kiting is exactly this
calculation:

> "…I can retreat to put 60 ft between us — since its speed is likely 30, it won't be
> able to close the gap and reach me."

On the rare turn it chose to think, it got it right.

**3. The menu stood in for deliberation.** Sonnet kited perfectly only in C3. C3's menu
offers a precomputed "retreat" move, which is that calculation packaged as an option.
A model that deliberates anyway (Gemini) gained nothing from the menu, since it
already played at the ceiling. So how much offered options help may depend less on
*capability* than on how much a model *chooses to think*. Sonnet is clearly capable of
the reasoning; at `low` it mostly did not do it.

**4. In C1, Sonnet thinks out loud, and the tool-call format removes that.** Its hidden
reasoning field was nearly always empty, but in C1 it usually wrote a line of working
before its command:

> "Fighter B1 is at x=15, and I'm at x=10. Both creatures are 5 ft in size, so the
> edge-to-edge gap is 0 ft and I can attack without moving."

> "My position is (10,10) and fighter-b2 is at (15,10), 5 ft away center to center.
> Edge to edge that is 0 ft, so I'm already in melee range…"

In C2 the response is a bare tool call, with no room for that working. That was the
one condition where Sonnet slipped: second attacks after its action was used, 10
times. The result, C1 0.99 against C2 0.90, runs opposite to H1's predicted C2 > C1.

**Link to prior work.** This matches Tam et al., *Let Me Speak Freely?* (EMNLP 2024,
arXiv 2408.02442). Restrictive output formats degrade reasoning, and not through
parsing failures, but because they squeeze out the model's working. Here the
restrictive format is the tool call, and what it squeezed out was Sonnet's incidental
reasoning.

**Why this matters for the framework.** The difference between the two models looks
like a real nuance in how vendors implement "effort", not a sign that the interfaces
are too restrictive. The same harness, prompts and scenarios let Gemini play at the
ceiling everywhere.

## What to check in the final run

- Does Sonnet's C1 > C2 hold over 10 seeds, and are its C2 misses spread across
  matches or concentrated in a few?
- Is Sonnet's tactical score still highest in C3, and specifically on kiting?
- Across all models, does visible prose (C1) or recorded reasoning go with first-attempt
  validity within a condition? Both are recorded per request, and `study show` prints
  them.
- Exploratory only (prereg §3): none of this may alter a registered verdict.

## For another study, not this one

A small prompt nudge to deliberate briefly before acting might close Sonnet's gap
entirely. It is clearly capable, and it reasons well when it does reason. Testing that
means changing the shared prompt, which the freeze forbids for this study. It would be
its own clean experiment: the same harness, with the prompt, or the effort setting
(`medium`), as the variable. Anthropic's own benchmarks show an unusually large jump
from `low` to `medium`, which would make the effort-setting version a natural first
test.
