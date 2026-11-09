# Article 2: outline

A working framework, not a draft. `[Logan: ...]` marks what only you can answer. Everything
else comes from the repo, your dissertation or our work on the first article.

**Working titles**
- Building an agent harness with an agent
- What building an LLM benchmark with an LLM taught me
- I studied how AI agents fail, with an AI agent

## A possible through-line

The first article found that an agent's reliability depends on the system around it. This one
could show the same thing from the inside: you were designing an interface for a model the
whole time, once for the study and once for your own coding agent. `CLAUDE.md`, the tests and
the load-time validator do for Claude Code what the menu and typed refusals do for Sonnet.

That gives the personal story a point that readers building agents can use, and it links the
two articles without repeating the first. `[Logan: does this match how it felt, or is it too
neat?]`

## Sections

**Core** sections carry the article. **Optional** ones could be folded in or saved for later.

### 1. Opening (core)

Three candidates:
- **The spliced quote.** Two reviews read the first article closely and it was published. A
  third checked it against the data and found a quote that no model ever wrote, spliced from
  two responses by the AI helping to write it, in an article about how AI agents slip.
- **The parallel.** Sonnet could see "0 actions" in its state and still tried to attack again.
  Then you describe your agent doing an equivalent thing. `[Logan: is there a moment that
  stands out?]`
- **A plain start.** "I built a 335-commit project with an AI coding agent, and here is what
  I would tell you about it."

My pick is the spliced quote. It is honest, a little funny, and shows the discipline straight
away.

### 2. From a GM tool to a study (core, short)

The route from "simulate an encounter" to a pre-registered study. The first article covers it
briefly, so this should only add the turning point.
- `[Logan: what was the moment the question changed?]`

### 3. What working with a coding agent was actually like (core)

- **The numbers:** 335 commits from March to November, 267 of them co-authored with Claude, and
  about 1,800 tests.
- `[Logan: what did it do far better than you expected?]`
- `[Logan: what could you not hand over?]`
- `[Logan: how did your own role change over those eight months?]`
- `[Logan: was there a point where you nearly lost track of your own codebase?]`

### 4. Building the harness for my own agent (core)

Where the through-line lands. Each item is a guard added because of a real failure:
- **`CLAUDE.md` with a dated lessons log:** each mistake became a rule, so the same agent would
  not repeat it in a later session with no memory.
- **Declaring and checking:** hand-written schemas rot, so tests read the code and compare.
- **Failing loudly at load:** a run-time failure is usually invisible, as when a typo in a guard
  simply reads as "did not fire".
- **Gates on exit codes:** a failing type check once reached a commit because the check was
  piped through `tail`.

### 5. The mistakes that mattered (core)

Pick three or four of the 20 lessons. These are the strongest, as each threatened the study's
meaning and none was caught by a failing test:
- **The test that defended a bug:** adjacent creatures were refused as overlapping, and a unit
  test asserted exactly that. Only the free-coordinate conditions could be refused for it, so
  it quietly biased the study towards its own hypotheses.
- **The identifier tax:** random hex ids had to be retyped in some conditions and not others,
  which made them an unintended variable.
- **The 100% measured on the wrong board:** menu coverage read 9/9 at the opening position, a
  formation built by hand, and 75% at worst across real matches. It was already written into
  the pre-registration.
- **The cost that could not fail:** missing token counts were coerced to zero, so the spend cap
  could never bind and "$0.00" would have been published as a result.
- **Green CI while every page returned 500:** no test requested a page.

`[Logan: which of these do you remember most? Is there one that never made it into the log?]`

### 6. Why pre-register a solo project? (core)

Your contact's question: did it actually change any decision? There is good evidence:
- It forced the 9/9 correction to be recorded in public.
- The movement prediction failed, and it had to be reported as failing.
- It also shows the limits: Gemini met the opponent-switching threshold and nobody noticed
  until a final audit. You can tell that story yourself, which is more credible than leaving
  it for someone else to find.

`[Logan: did you ever want to change something after seeing data, and hold back?]`

### 7. Writing it with AI, in my own voice (optional, but distinctive)

- A reader noticed the voices jumping between your sections and mine, and that the AI style was
  tiring.
- You built a skill from your dissertation, then tested it by comparing paragraphs.
- Generic "avoid AI tells" lists would have been wrong, because some tells are yours.
- Your own quirks came up too: "agentive", "want for authenticity", and "however" as your main
  connective.
- **The audits:** the first two judged how it read, and the third checked whether it was true.
- Why you are open about all of this.

`[Logan: did using a skill like this feel like cheating, like tooling, or something else?]`

### 8. How my views changed (core, and probably the heart of it)

**What you want to work on.** Your contact's suggestion, and likely the part employers read most
closely.
- **Then:** your honours project, a local Llama 3.1 tool for verifying student contributions,
  and an interest in general AI and educational uses of LLMs.
- **Now:** a strong interest in agentic work.
- `[Logan: what actually moved you? Was it the study's results, the building, or watching
  Claude Code work?]`
- `[Logan: what do you still value from the educational side?]`
- `[Logan: what kind of work are you looking for now? Stay as specific as you are comfortable
  being.]`

**What you believed about models.** These are already on record in the first article:
- You expected interface to matter hugely, and found it depends on the model.
- You believed Sonnet would be the best, and it was the only one less reliable with more
  structure.
- You assumed free text would be plagued by parser errors, and even the weakest model adopted
  the syntax.
- `[Logan: which of these changed how you actually work?]`

**A thread back to your dissertation.** There you noticed that 93.68% accuracy on artificial
data was "a suspicious result", and your tutors' labels went unverified because of time. In
this project you ran a blind audit of your own parser. `[Logan: is this a real line of growth
as you see it, or am I reading too much into it?]`

### 9. What I would do differently (core, short)

- `[Logan: what would you change first?]`
- Your contact's prompt: what would you tell someone starting their first agent evaluation?
- **Candidates from the record:** check against source data from the start, measure before
  building on an assumption, and run more than one model early.

### 10. What it cost (optional, or fold into section 3)

- **Money:** the final run was $24.30 billed, plus the pilots (Gemini's alone was $1.86).
- `[Logan: what did you spend on Claude Code, and how many hours did this take?]`
- Sub-agents hit usage limits on one large fan-out, which changed how you ran them.

### 11. Close (core, short)

Where it goes next: richer agentic studies, without promising specifics. One sentence pointing
back to the first article and the replay.

## Keeping it focused

This is more than one article should hold. If it needs narrowing, I would keep 1, 3, 4, 5, 6 and
8, and fold 2, 9 and 10 into those. Section 7 could be its own short post, since it would appeal
to a different audience.

## Before publishing

Same rule as the first article: check every number and quotation against the source, and write
it from your notes through `logan-voice`, so your experiences stay yours.
