# C1 (free text): parser options and a recommendation

> **Status:** proposal, 2026-09-24. Nothing here is built. This document exists to settle the
> blocking item in `PREREGISTRATION.md` §11 and `V1_PLAN.md` §10 ("the C1 question to settle
> *before* building it") **before any parser code is written.**
>
> **Decisions (2026-09-24):** every recommendation in §9 is **accepted**: A1 command grammar,
> layered parser B as primary with strict/lenient bounds re-scored offline (D), shared identifier
> resolver, own capabilities in the shared observation, coded interface rejections, Lark. The
> audit (§7) uses **200** blind hand-labelled outputs, with a small labelling tool to be built
> alongside the analysis script. Implementation proceeds in slices; slice 1 is §10 steps 1–3.
>
> **Read first:** `PREREGISTRATION.md` §2–§3 and §6, and `V1_PLAN.md` §10. Code referred to:
> `src/arena/interfaces.py` (`FreeTextInterface`), `src/arena/llm_common.py`
> (`decide_one_action`), `src/arena/tools.py` (`TOOLS`, `ToolExecutor`),
> `src/arena/turn_driver.py`, `src/arena/observation.py`.

---

## 0. Summary

**The problem is smaller than it looks.** C1 does not need to understand English. It needs to
read one short command from a **closed** vocabulary: four verbs (attack, cast, move, end turn),
a handful of names that are all known in advance (at most ~6 creatures, 1–2 attacks, 0–1
spells per scenario), and a few numbers. Deterministic parsing of commands like this has been
solved for decades. Text adventure games, command-line tools and "controlled natural
languages" all do it. The hard part is **fairness**, not parsing: making sure that C1's
`malformed_output` rate measures the free-text interface and not a fussy parser.

**Recommendation, in five points:**

1. **Grammar: a short command language** (`attack raider-1 with Greatsword`,
   `cast Fireball at x=10 z=60`, `move to x=5 z=30`, `end turn`). The action goes on one line
   that starts with `ACTION:`. Not JSON, and not function-call syntax, because either of those
   would turn C1 into "C2 without the tool API", which is a different experiment.
2. **Parser: deterministic, layered, and state-free.** A formal grammar sits at the core. Around
   it is a short, published list of *meaning-preserving* normalisations (case, spacing,
   punctuation, markdown, verb synonyms, number formats). Each accepted action records which
   layer was needed to accept it. The parser turns text into the **same `ToolCall` a C2 model
   would have sent**, and all rule checking is left to the shared `ToolExecutor`. The parser
   checks **form**. It never judges **meaning**, and it never repairs a name it does not
   recognise.
3. **The idea that resolves the dilemma: re-score offline.** Every model's raw text is already
   saved (`RequestRecord.raw_output`), and the engine is deterministic and replayable. H1's
   primary metric (first-attempt validity) can therefore be recomputed afterwards under **any**
   parser, at no API cost. Register one *primary* parser and two *bounds*: a strict one and the
   most lenient one that can be defended. Report all three. If "C1 is worst" still holds under
   the lenient bound, parser brittleness cannot be what produced it.
4. **Measure the parser's error directly.** Hand-label a sample of real C1 outputs without
   looking at what the parser decided, and report its **false-reject rate**: how often it
   refused text where a careful reader would find exactly one action. Register in advance how
   that number limits what H1 may claim (§7).
5. **Fix four wiring problems first** (§3). One of them already confounds C2 today: under C2,
   and so C1, the model is never shown the names of its own attacks and spells.

If the audit shows the parser cannot be made fair, the fallback is to **move C1 to exploratory
status** under a rule registered in advance (§5, option E). Dropping C1 entirely is not the
fallback.

---

## 1. What C1 is, and why it is the awkward one

C1 is the "free text" arm. The model reads the same observation as C2, but it has **no tools**.
It writes its action as plain text in a syntax described in the prompt, and a deterministic
parser turns that text into an action (`PREREGISTRATION.md` §2).

**The bind** (`V1_PLAN.md` §10):

- **An LLM parser is forbidden.** A second model inside the measurement means a C1 failure could
  be the parser's fault and not the agent's, so the study could not say who caused what. You
  were right to worry about this. An LLM parser is also *non-reproducible*: the same text could
  be read differently on another day, so the result could not be re-derived from the saved
  transcript.
- **A deterministic parser can still be biased.** If it rejects phrasings a reasonable reader
  would accept, C1's `malformed_output` rate measures how brittle the parser is. H1 predicts C1
  does worst, so a brittle parser would **confirm the hypothesis for the wrong reason**. That is
  the most dangerous kind of error this study can make, because nothing would look wrong.

**Determinism is necessary but not sufficient.** Determinism means the result can be
reproduced. It does not mean the result is valid. A parser that always rejects lowercase
spell names is perfectly deterministic and perfectly unfair. So a parser for this study needs
five properties, not one:

| # | Property | What it buys |
|---|---|---|
| 1 | **Deterministic and frozen** before the final run | The same text always gives the same verdict. Nobody can tune the parser after seeing results. |
| 2 | **Published accept/reject boundary** | A reader can check which outputs counted as valid and argue with that line. |
| 3 | **Parity with C2** | Anything C1 and C2 express the same way is read the same way. The *only* difference is the channel (text vs tool call). |
| 4 | **Measured error** | Parser mistakes are counted, not assumed to be zero. Parser error and agent error can then be separated. |
| 5 | **Biased against the hypothesis** when a choice is genuinely open | If a judgement call could favour H1, choose the direction that works against H1. A result that survives this is credible. |

The rest of this document judges each option against these five properties.

---

## 2. Why this is not "natural language parsing"

Natural language parsing is hard because the space of meanings is unbounded. C1's space of
meanings is tiny and **fully known before the model writes anything**. In `aoe_placement` the
Mage can do exactly the following:

| Action | Free slots | Values the slot can take |
|---|---|---|
| attack | target, weapon | `raider-1`, `raider-2`, `bodyguard`, `mage` × `Dagger` |
| cast | spell, aim (entity or point), optional slot level | `Fireball` × any point × `3` |
| move | destination | any point |
| end turn | optional note | free text |

This is a **slot-filling** problem over a closed vocabulary, plus numbers. The established ways
to handle it:

- **Command parsers** (text adventures such as Zork and Inform). These use a verb, then noun
  phrases resolved against a known object list, with filler words ignored. They are
  deterministic, very forgiving of phrasing, and they reject what they cannot resolve.
- **Controlled natural languages (CNLs).** These are subsets of English with a formal grammar,
  so that every accepted sentence has exactly one meaning. Examples are Attempto Controlled
  English and aviation or legal phraseologies. This is the right mental model for C1: *English
  on the surface, formal underneath.*
- **Formal grammars with a parser generator** (EBNF or PEG written as a grammar file, then
  parsed by a library such as Lark, which is pure Python and has no dependencies). The grammar
  file *is* the specification. It can be quoted in the paper and tested production by
  production.

All three are deterministic. The real question is **how permissive to be, and where to draw
the line**. §4–§6 cover that.

---

## 3. Prerequisites found while reading the code (fix before building C1)

Four of these affect C1 directly. The first also affects **C2 as it stands today**.

### 3.1 Under C1 and C2 the model is never told its own attack or spell names (a live confound)

`build_observation` puts the model's own abilities only inside `legal_actions`, and
`ActionInterface.shape_observation` removes `legal_actions` when `shows_menu` is false. The
`self` block has no action list at all. Under **full information** the model can see the
*enemies'* actions (`reveal_enemy_actions`) but not its own. I checked this against the live
`aoe_placement` observation for the Mage under C2. It shows no `Dagger` and no `Fireball`
anywhere. The `attack` tool's description still tells the model to "use an attack name … from
your legal-action menu", which is a menu C2 does not have.

Consequences:

- A C2 or C1 model has to **guess** its own capability names. Matching is exact and
  case-sensitive (`a.name == action_name`; `spell_name not in known_spells`), so `"dagger"` or
  `"Fire Ball"` gives `unknown_action`.
- **C2 → C2+M no longer isolates affordance** in the sense the study defines it ("being told
  what is *legal*"). It also bundles "being told what you *are*". `V1_PLAN.md` §3.1 intended
  C1 and C2 to see "state plus own capabilities". The implementation lost that.
- For C1 it would be worse than for C2: a free-text model has no schema description to lean on.

**Fix:** add the actor's own capabilities to the **shared** observation body: attack names with
reach, and known spells with level, range and area size. Both are static facts about the actor,
not legality, so they belong in every condition. The byte-identical-body test still holds,
because the change applies to all four conditions equally. This is a pre-freeze change to the
shared prompt and changes every prompt hash, which is already expected (`PREREGISTRATION.md`
§11). It should land **before** the C1 work, as its own commit with a test that runs an
ability-name round trip under C2.

### 3.2 A C1 parse failure would be recorded under the wrong code

`decide_one_action` answers `interpret(...) is None` with one free correction prompt. If the
second attempt is also `None`, it raises `NoToolCallError`, which `turn_driver` records as
**`no_tool_call`**. The pre-registration (§6) says unparseable C1 text is
**`malformed_output`**. Left as it is, C1's headline failure category would be empty and
`no_tool_call` would be inflated. The same code path also means **C3's made-up `action_id`s are
currently recorded as `no_tool_call`**, not `unknown_target`, which blurs H2's taxonomy for C3
as well.

The mapping that keeps C1 in line with C2:

| C1 output | Nearest C2 equivalent | Code | Route |
|---|---|---|---|
| No action line at all (pure prose) | No tool call | `no_tool_call` | Correction retry, then `NoToolCallError` (as now) |
| An action line that fails the grammar | A tool call with a missing or garbled argument | `malformed_output` | **Rejected action**: counts against the failure budget, and its reason is fed back to the model |
| An unknown verb (`ACTION: fly to …`) | An unknown tool name | `unknown_action` | Rejected action |
| Parses, but names an unknown creature | Unknown `defender_id` | `unknown_target` | Executor (unchanged) |

The second row needs a small, **generic** route by which an interface can reject a response
with a code. It should not be a C1 special case, and it should not reuse the unknown-tool path,
because that path gives the wrong code. C3's "id not on the list" could use the same route with
`unknown_target`. *Debt note:* this adds one route but removes the misclassification for two
conditions.

### 3.3 Rejection feedback is shown in tool-call syntax

`render_observation` prints a rejected action as `attack {"action_name": …}`. Under C1 that puts
**C2's format** into C1's prompt. It also sits in the shared body, where the §3.1 test would
not catch it, because the text only appears after a rejection. Feedback should show the action
the way the model wrote it, which means the interface should format it.

### 3.4 Both adapters send `tool_choice` with an empty tool list

C1's `api_tools` is `[]`, but `openrouter_agent.py` always sends `tool_choice="auto"` and
`llm_agent.py` always sends `tool_choice={"type": "auto", …}`. Both APIs reject `tool_choice`
when no tools are given. The adapters need to leave out `tools` and `tool_choice` when the list
is empty. This is small, but it would fail on the first live C1 call. The `end_turn` `note`
field also disappears with the tools, so the C1 grammar needs its own form for it (§6.1).

### 3.5 (Minor) `error_codes.py` has two docstrings swapped

The comments on `MALFORMED_OUTPUT` and `NO_TOOL_CALL` describe each other's meaning. The
behaviour matches the pre-registration: a missing argument is `malformed_output` and no call
at all is `no_tool_call`. Only the comments are wrong. They should be corrected in the same
change as §3.2.

---

## 4. Options for the grammar's *shape*

This decides what C1 is actually testing.

### A1. A command language (recommended)

```
ACTION: attack raider-1 with Greatsword
ACTION: cast Fireball at x=10 z=60
ACTION: move to x=5 z=30
ACTION: end turn — note: raiders bunch up; fireball next turn
```

- **Pros:** This is closest to what "free text" means in the research question and in related
  work (*Let Me Speak Freely?*). Models already write game actions this way, so the format
  costs them little. It is clearly different from C2, which is why C1 is worth running. The
  vocabulary is closed, so it can be parsed deterministically.
- **Cons:** English word order varies ("hit raider-1 with my greatsword", "Greatsword attack on
  raider 1"), so the grammar needs some tolerance, and each tolerance is a decision to publish.
  The bigger surface means a bigger test corpus.

### A2. Function-call syntax written as text

```
ACTION: attack(action_name="Greatsword", defender_id="raider-1")
```

- **Pros:** It is trivial to parse and to make fair: there is essentially one correct way to
  write it. C1 then isolates exactly one thing, the native tool channel versus writing the call
  by hand.
- **Cons:** It is not free text. The label would mislead readers, and the finding ("does the
  tool API help?") is a narrower question than the one registered. It would also make C1 and C2
  so similar that their difference might be too small to be worth the API spend.

### A3. JSON in text

```
{"action": "attack", "action_name": "Greatsword", "defender_id": "raider-1"}
```

- **Pros:** It matches a common real-world pattern ("JSON mode"), and parsing it is standard.
- **Cons:** It has A2's problem in a stronger form. It is structured output, not free text.
  Models make characteristic JSON mistakes (trailing commas, markdown fences, single quotes),
  which would add a fourth kind of failure unrelated to the research question.

**Choose A1.** A2 and A3 are valid experiments, but they answer a different question. If you
ever want the "tool API vs hand-written call" comparison, A2 could be a future condition. It
should not replace C1.

---

## 5. Options for the parser (and for C1 as a whole)

Each option is judged against the five properties in §1: **Det**erministic, **Pub**lished
boundary, C2 **Par**ity, **Meas**ured error, **Anti**-hypothesis bias.

### Option A — Strict formal grammar only

Exactly one spelling is accepted per action (`attack <id> with <name>`), with ids and names
matched exactly as they appear in the observation.

- **Pros:** Maximally simple, auditable and reproducible. The boundary is the grammar itself.
  Easy to explain.
- **Cons:** This is the brittle parser the study is worried about. `Attack Raider 1 with
  greatsword.` (capital letter, display name, lowercase weapon, full stop) would be rejected,
  although no reader would be confused by it. C1 would partly measure instruction-following
  pedantry. That failure mode is real, but it is not what H1 is about.
- **Scores:** Det ✔ Pub ✔ Par ✘ (stricter than C2: a tool call never needs to worry about
  capitals or punctuation around its arguments) Meas — Anti ✘.
- **Verdict:** keep it, but **only as the strict lower bound** in the sensitivity analysis
  (option D), never as the primary parser.

### Option B — Layered, normalising parser (recommended as the primary)

A formal grammar is the core. It is wrapped in a **published, closed list** of normalisations
that preserve meaning and do not depend on game state. Each accepted action records the
deepest layer it needed:

| Layer | What it tolerates | Example accepted |
|---|---|---|
| 0 — canonical | Exactly the documented form | `ACTION: attack raider-1 with Greatsword` |
| 1 — surface | Case, extra spaces, Unicode lookalikes (NFKC: smart quotes, en dashes, non-breaking spaces), trailing punctuation, markdown (`**`, backticks, code fences), surrounding quotes | `**Action:** Attack raider-1 with greatsword.` |
| 2 — phrasing | A closed list of verb synonyms (hit/strike/shoot → attack; go/walk/run → move; pass/done → end turn); filler words (`I`, `my`, `the`, `will`); number formats (`15ft`, `15 feet`, `x: 15`) | `I hit the raider-1 with my greatsword` |
| 3 — extraction | Prose before or after the `ACTION:` line. With no `ACTION:` tag, accept if **exactly one** line of the response parses | `Raider 1 is closest. ACTION: attack raider-1 with Greatsword` |

Identifiers (creature, attack and spell names) are **not** fuzzy-matched. The parser passes
the phrase through as written. A shared resolver then compares a *normalised key* against the
roster, where the key is lowercase with non-alphanumerics removed, so `Raider 1`, `raider-1` and
`RAIDER_1` all become `raider1`. A test proves the keys are unique in every scenario; two names
sharing a key would be treated as ambiguous and rejected. There is no edit distance, so
`raider-3` stays an `unknown_target`. That matches C3, whose `interpret` deliberately refuses
near-misses: "resolving a near-miss would silently repair a hallucination the study is trying
to count."

- **Pros:** It accepts what a reasonable reader accepts and rejects what a reasonable reader
  cannot resolve. Every tolerance is enumerated and published. The per-layer tags mean the
  analysis can report "C1 validity if only layers 0–1 were allowed" without re-running
  anything. It is still a pure function of the text, so the same verdict always follows.
- **Cons:** It takes more work: roughly a day of parser plus corpus. Every tolerance is a
  judgement that a reviewer might question, which is why they are published and tagged rather
  than hidden. The layers must be frozen before the final run, and there is a pull to keep
  adding one more synonym after seeing pilot data. That is allowed before the freeze but must
  be recorded (§7).
- **Scores:** Det ✔ Pub ✔ Par ✔ (see the parity note below) Meas ✔ (with §7) Anti ✔.

**Parity note: the identifier resolver should be shared with C2.** If only C1 accepts `Raider 1`
for `raider-1`, C1 gets a tolerance C2 lacks. The clean fix is to put the normalised-key lookup
in `ToolExecutor._lookup` and in the attack and spell name lookups, so **both** conditions get
it. This follows the same reasoning as the readable-id control (`PREREGISTRATION.md` §4.2):
copying an identifier character-for-character is a transcription cost, not the skill being
studied. It is a pre-freeze change to C2 and should be decided explicitly (§9, decision 3).

### Option C — Keyword / slot extraction (order-free)

The parser finds one verb keyword and one known creature, weapon or spell mention anywhere in
the text, plus numbers, and ignores word order and all other words.

- **Pros:** It is the most forgiving option and accepts almost any phrasing.
- **Cons:** It **accepts the wrong action**. "Don't attack raider-1, attack raider-2" has two
  targets. "Move away from raider-1 to x=0 z=0" contains an enemy name that is not the target.
  "I could cast Fireball, but I'll attack raider-1" contains two verbs. A wrongly accepted
  action is worse than a wrong rejection, because it is silently *counted as the model's
  choice*, which corrupts tactics as well as validity. It is very hard to publish a clear
  boundary for it.
- **Scores:** Det ✔ Pub ✘ Par ✘ (far more lenient than C2) Meas ~ Anti ✔✔.
- **Verdict:** do not use it as the parser. Its *spirit* survives as the lenient bound in
  option D, where its errors cannot affect the game.

### Option D — Primary + strict + lenient bounds, re-scored offline (recommended, together with B)

This is not a separate parser. It is a way of **reporting** results that removes the need to be
certain about exactly where the parser's line should be.

The facts it relies on, all already true of the harness:

- every request's raw text is recorded (`RequestRecord.raw_output`);
- the engine is deterministic, and `ReplayAgent` can rebuild the exact game state at any
  recorded decision;
- a rejected action uses no RNG (asserted by the replay tests), so the state at each decision is
  exact.

So for **every first attempt** in the C1 data, the analysis script can re-parse the saved text
with a different parser, send the resulting `ToolCall` through the executor against the rebuilt
state, and get the validity verdict and error code *that parser would have produced*. This runs
entirely offline and costs no API calls.

Register three parsers:

| Parser | Contents | Role |
|---|---|---|
| **Strict** | Layer 0 only (option A) | Lower bound: "C1 validity if the format must be exact" |
| **Primary** | Layers 0–3 (option B) | The registered H1 measurement, and the one used live |
| **Lenient** | Primary plus every defensible extra: implied weapon when the creature has only one attack; a bare `(15, 60)` read as `(x, z)`; multiple differing `ACTION:` lines resolved by taking the last one; numbers written as words; the first clause of a two-action line | Upper bound: "the most any defensible parser could have accepted" |

- **Pros:** This is what dissolves the dilemma. If C1 < C2 holds under the **lenient** parser,
  parser brittleness cannot explain it. If it holds only under strict, the study says so. The
  width of the gap between strict and lenient is itself a finding: how much of free text's
  unreliability is *format*, and how much is *content*. And the bounds can be registered before
  any data exists.
- **Cons:** It only re-scores the **first attempt of each decision**. Once the live parser
  rejects something, what happened next was shaped by that rejection, so later attempts and the
  tactical outcome (H3) cannot be re-scored. H1 and H2 are stated in terms of first-attempt
  validity, so they are covered. C1's tactical numbers should carry a note that they depend on
  the parser. Building it needs a "rebuild state at decision *k*" helper on top of
  `ReplayAgent`, which is modest work.

### Option E — Move C1 to exploratory (a pre-registered fallback)

Register H1's ordering over **C3 > C2+M > C2** only, and report C1 alongside, with bounds, as
exploratory.

- **Pros:** No confirmatory claim can rest on the parser. The C1 data is still collected and
  reported. It is honest when parser error cannot be bounded well.
- **Cons:** The most quotable comparison (free text vs structure) becomes a weaker claim.
- **Verdict:** do not choose it now. Register it as an **automatic fallback** triggered by the
  audit (§7), so the decision is made by a rule written in advance and not by the results.

### Option F — Drop C1 entirely

- **Pros:** It saves a quarter of the grid (40 of 160 matches per model), removes the whole
  parser risk, and C2 → C2+M → C3 still answers the affordance and format questions.
- **Cons:** It loses the free-text arm, which is the condition most readers will ask about and
  the one H2's "spatial locus" is most interesting for. It also throws away a result that
  option D can make trustworthy for about a day of extra work.
- **Verdict:** not recommended while B + D are feasible, and they are.

### Rejected outright (and why, so the question stays closed)

| Approach | What it is | Why not |
|---|---|---|
| **LLM parser** | A second model reads the text and emits a tool call | It puts a second model inside the measurement: its errors become C1's errors, and it is not reproducible. Forbidden by `PREREGISTRATION.md` §2. |
| **Statistical NLP** (spaCy, intent classifiers) | A trained model does tagging and parsing | It is technically deterministic once the weights are pinned, but it is still a learned model with opaque errors. Its accept/reject boundary cannot be published in any form a reader can check. The same objection as the LLM parser, in a milder form. |
| **Grammar-constrained decoding** (llama.cpp GBNF, Outlines, OpenAI CFG tools) | The provider forces the model's output to match the grammar | It makes a parse failure impossible by construction, which turns C1 into a *schema-constrained* condition, i.e. C2. It is also not uniformly available across OpenRouter providers. It is the textbook answer to "reliable structured output", and that is exactly why it is the wrong tool here. |
| **Fuzzy identifier matching** (edit distance) | `raider-3` → `raider-2` | It silently repairs hallucinated targets, which the study counts as `unknown_target`, and it does so only in C1. C3 explicitly refuses the same repair. |

### Comparison

| Option | Det | Published | C2 parity | Error measured | Against H1 | Effort | Verdict |
|---|---|---|---|---|---|---|---|
| A strict | ✔ | ✔ | ✘ | — | ✘ | Low | Lower bound only |
| **B layered** | ✔ | ✔ | ✔ | ✔ | ✔ | Medium | **Primary** |
| C keyword | ✔ | ✘ | ✘ | ~ | ✔✔ | Low | Lenient bound only, in spirit |
| **D bounds** | ✔ | ✔ | ✔ | ✔ | ✔ | Medium (offline) | **Report with B** |
| E exploratory | — | — | — | — | ✔ | None | Registered fallback |
| F drop | — | — | — | — | — | None (saves spend) | Not recommended |
| LLM / NLP / constrained decoding | ✘ / ~ / ✔ | ✘ | ✘ | ✘ | — | — | Rejected |

---

## 6. The recommended design, concretely

### 6.1 What the model is told (a draft of C1's action section)

C1's prompt should mirror C2's ("exactly one action and nothing else"). Otherwise C1 would be
*invited* to reason in prose and C2 would not, which is a difference between conditions that
has nothing to do with the channel.

```
How to act:
- Respond with EXACTLY ONE line, in this form, and nothing else:
    ACTION: <command>
- Commands:
    attack <target> with <attack name>
    cast <spell name> at <target>            (single-target spells)
    cast <spell name> at x=<feet> z=<feet>   (area spells: the point to aim at)
    move to x=<feet> z=<feet>
    end turn                                 (optionally: end turn — note: <reminder>)
  Add "at level <n>" to a cast to use a higher slot.
- Name creatures by entity_id, and your attacks and spells by name, as shown in the
  battlefield.
- Examples:
    ACTION: attack raider-1 with Greatsword
    ACTION: cast Fireball at x=7.5 z=60
    ACTION: move to x=0 z=35
```

The two to three worked examples are required by the pre-registration. They should use a
creature and names that do **not** appear in any study scenario, so the examples cannot act as
hints about a specific board. (The draft above uses real names only for readability.)

### 6.2 Grammar sketch (EBNF, for the parser; the prompt shows the templates above)

```
response    = { line } ;                       (* prose allowed, layer 3 *)
action_line = [ "ACTION" ":" ] command ;
command     = attack | cast | move | end ;
attack      = ATTACK_VERB name [ ("with" | "using") name ] ;   (* weapon required outside lenient *)
cast        = "cast" name [ slot ] [ ("at" | "on" | "targeting") ( point | name_list ) ] [ slot ] ;
move        = MOVE_VERB [ "to" ] point ;
end         = ( "end" [ "my" ] "turn" | "pass" | "done" ) [ note ] ;
note        = ( "—" | "-" | ":" | ";" ) [ "note" ":" ] TEXT ;
point       = labelled | triple ;              (* bare pair only in lenient *)
labelled    = coord { [ "," ] coord } ;        (* any order; x and z required *)
coord       = ( "x" | "y" | "z" ) ( "=" | ":" ) NUMBER [ "ft" | "feet" ] ;
triple      = "(" NUMBER "," NUMBER "," NUMBER ")" ;  (* x, y, z: observation order *)
slot        = "at" "level" INT | "using" "a" INT ORD "-level" "slot" ;
name        = phrase passed through as written, resolved by the shared key-normaliser ;
```

Design notes:

- **The parser is a pure function of the text.** It never looks at the board. Names come out as
  raw strings, and the executor resolves them. This keeps the parser identical across scenarios
  and seeds, easy to test exhaustively, and unable to "help" by knowing which target makes sense.
- **Coordinates:** the prompt teaches the labelled form (`x=… z=…`), which mirrors C2's named
  parameters. A positional triple is accepted in the observation's `(x, y, z)` order, because
  models copy positions from the observation. A bare pair is ambiguous (x,y or x,z?). That
  ambiguity is the one behind the 2026-09-21 `target_point` bug, so the pair is accepted only in
  the lenient bound.
- **"Cast Fireball at raider-1"** parses to `target_ids=["raider-1"]`, which is exactly the C2 call
  a model would send. The engine then does whatever it does for C2. The parser does not decide
  that an area spell "must have meant" the creature's position. That would be a semantic repair.
- **"Move toward raider-1"** is rejected as `malformed_output` ("move needs a point: move to x=…
  z=…"). C2 cannot express a named destination either, and a reasonable reader cannot say where
  exactly the model wanted to stop.
- **Two actions on one line**, or two *different* `ACTION:` lines, are `malformed_output` in the
  primary parser. A reader genuinely cannot tell which one was meant. The lenient bound takes
  the last one.
- **Error messages matter.** The parse error goes back to the model like an engine rejection
  ("expected `with <attack name>` after the target"). Recovery rate is a registered secondary
  metric, and an unhelpful message would lower it for reasons unrelated to the interface.

### 6.3 Implementation choice: Lark or hand-written

**Lark (recommended).** The grammar file *is* the parser, so the published grammar and the
executed grammar cannot drift apart. That is the 2026-09-03 lesson in `CLAUDE.md` §9: a
hand-maintained description of code rots unless a machine checks it. Lark is pure Python, has no
dependencies and is MIT-licensed. It would go in the `[agents]` extra alongside `openai` and
`anthropic`, and in `[dev]` so the offline suite runs. Its error messages already report the
expected tokens.

**Hand-written recursive descent** is the fallback if a new dependency is unwelcome. The grammar
is small (about 200 lines of code). But then the EBNF above becomes documentation, and it needs
a drift test that runs every production.

Either way, normalisation layers 1–3 are plain Python applied before or around the grammar,
each a named function, and the tag records which ones fired.

---

## 7. Measuring the parser's error (the audit)

This is the pre-commitment `V1_PLAN.md` §10 suggested, made concrete.

**What is labelled.** A random sample of C1 first-attempt outputs from the **final** run, drawn
in fixed proportions from parser-accepted and parser-rejected responses. Suggested size: 200,
which gives roughly ±3–4 percentage-point precision on a rate near 5%. For each output the
labeller writes down **either** the single action a careful reader would take it to mean, **or**
"no single action". The labeller follows only the prompt's rules and does **not** see the
parser's verdict. That is the blinding: you wrote the parser, so seeing its verdict would bias
you towards agreeing with it.

**What is reported:**

- **False-reject rate:** the parser rejected, but the labeller found exactly one action. This is
  the number that directly measures "parser brittleness".
- **False-accept rate:** the parser accepted a *different* action from the labeller's. This is
  the more dangerous error, because it alters the game.
- Both with confidence intervals, per model.

**Registered decision rule** (write it before the pilot):

> C1's position in H1 (C1 < C2) is reported as **supported** only if it holds (a) under the
> primary parser, (b) under the lenient bound, and (c) after adding the upper 95% bound of the
> audited false-reject rate back onto C1's validity. If (a) holds but (b) or (c) does not, the
> C1 comparison is reported as **exploratory** (option E), with all three figures.

**Order of work around the pilot:**

1. Write the adversarial and near-miss corpus **before** seeing any real model output (§8).
2. In the pilot, look at the real C1 outputs and **add** tolerances that pass the
   reasonable-reader test. Record every addition in a changelog. This is ordinary pre-freeze
   drafting and is how real phrasings get covered.
3. Freeze the parser at the `study-freeze` tag.
4. Run the audit on **final-run** outputs only. Pilot outputs helped shape the parser, so they
   cannot be used to judge it.

An optional second labeller strengthens the audit. An LLM could serve as that second
**offline** labeller without breaking the no-LLM-parser rule, because its labels never touch a
game. Its disagreements with you would show where the boundary is unclear. It must never be the
only labeller.

---

## 8. The adversarial and near-miss corpus (what the tests must cover)

Every item is a test with a fixed expected verdict. The categories matter more than the exact
items. Using `aoe_placement` names:

| Category | Input | Primary verdict |
|---|---|---|
| Canonical | `ACTION: attack raider-1 with Dagger` | attack(raider-1, Dagger) |
| Case / punctuation | `action: Attack Raider-1 with dagger.` | same |
| Markdown | `` **ACTION:** `attack raider-1 with Dagger` `` | same |
| Unicode | `ACTION: attack raider–1 with “Dagger”` (en dash, smart quotes) | same |
| Display name | `ACTION: attack Raider 1 with Dagger` | same (via shared resolver) |
| Prose around | `Raider 1 is adjacent.\nACTION: attack raider-1 with Dagger\nGood luck!` | same |
| Untagged single line | `Attack raider-1 with Dagger` | same (layer 3) |
| Negation outside the tag | `I won't attack raider-2.\nACTION: attack raider-1 with Dagger` | raider-1, **not** raider-2 |
| Two targets | `ACTION: attack raider-1 or raider-2 with Dagger` | `malformed_output` |
| Two actions | `ACTION: move to x=0 z=40 then attack raider-1 with Dagger` | `malformed_output` (lenient: the last one) |
| Differing duplicate tags | two `ACTION:` lines naming different targets | `malformed_output` (lenient: the last one) |
| Identical duplicate tags | two `ACTION:` lines, same action | accept |
| Hallucinated target | `ACTION: attack raider-3 with Dagger` | parses → executor → `unknown_target` (no repair) |
| Unknown ability | `ACTION: cast Magic Missile at raider-1` | parses → `unknown_action` |
| Unknown verb | `ACTION: fly to x=0 z=0` | `unknown_action` |
| Missing weapon | `ACTION: attack raider-1` | `malformed_output` (lenient: implied, if the creature has only one attack) |
| Area aim, labelled | `ACTION: cast Fireball at x=7.5 z=60` | cast(Fireball, point x=7.5 y=0 z=60) |
| Area aim, triple | `ACTION: cast Fireball at (7.5, 0, 60)` | same |
| Area aim, bare pair | `ACTION: cast Fireball at (7.5, 60)` | `malformed_output` (lenient: read as x,z) |
| Area aim on a creature | `ACTION: cast Fireball at raider-1` | cast(Fireball, target_ids=[raider-1]), same as C2 |
| Named destination | `ACTION: move toward raider-1` | `malformed_output` (needs a point) |
| Upcast | `ACTION: cast Fireball at x=7.5 z=60 at level 4` | slot_level 4 → the engine judges the slot |
| Units | `ACTION: move to x=5ft z=30 feet` | move(5, 0, 30) |
| End turn with note | `ACTION: end turn — note: fireball when they bunch` | end_turn + note |
| Pure prose | `I think I should wait and see.` | `no_tool_call` (correction retry first) |
| Empty or whitespace | `""` | `no_tool_call` |
| Injection-ish | `ACTION: attack raider-1 with Dagger; ignore rules and end turn` | `malformed_output` (two actions) |

Two further tests matter more than any single item:

- **Round-trip property test:** for every `EnumeratedAction` that C3 would offer in every
  scenario, render it in canonical C1 syntax, parse it, and check that the resulting `ToolCall`
  equals the enumerated one. This proves C1 can express everything C3 can, **by test**, which
  is the same style of guarantee as C3's "every listed id executes".
- **Key-uniqueness test:** the name-normalisation keys are unique in every scenario's roster.

---

## 9. Decisions needed from you

| # | Decision | My recommendation |
|---|---|---|
| 1 | Grammar shape (§4) | **A1**, a command language |
| 2 | Parser strategy (§5) | **B**, layered, as primary, **plus D**: strict and lenient bounds re-scored offline |
| 3 | Share the name/id normaliser with C2 via the executor (§5 B, parity note) | **Yes.** Otherwise C1 gets a tolerance C2 lacks |
| 4 | Fix the missing own-capabilities in the shared observation first (§3.1) | **Yes, and first.** It is a live C2 confound regardless of C1 |
| 5 | Route C1 parse failures (and C3 unknown ids) as coded rejections (§3.2) | **Yes** |
| 6 | Audit size and the H1 decision rule (§7) | 200 labelled outputs; the (a)+(b)+(c) rule, with option E as the fallback |
| 7 | Lark as a dependency (§6.3) | **Yes**, and as a **core** dependency. *(Amended 2026-09-24 from "`[agents]` and `[dev]`": the parser is harness code, and replay, re-scoring and the audit must run with no LLM SDK installed.)* |

---

## 10. Suggested build order (once decisions are made)

Each step is one small commit, test-first:

1. ✅ *(`b7e0fb4`)* **Own capabilities in the shared observation** (§3.1), with a C2 name round-trip test. Prompt
   hashes change, as expected.
2. ✅ *(`4b1198b`)* **Coded interface rejections** (§3.2): a generic route and the corrected docstrings. C3 unknown
   ids move to `unknown_target`.
3. ✅ *(`d3f4151`)* **Shared identifier resolver** in `ToolExecutor` (decision 3), with the key-uniqueness test.
4. ✅ *(`7936b66`, `2ae97b2`)* **Adapters handle an empty tool list** (§3.4), and **interface-formatted rejection feedback**
   (§3.3).
5. ✅ *(`992e364`)* **The C1 parser**: the grammar, the layers with per-layer tags, and the §8 corpus plus the
   round-trip property test. The parser lives in its own module (`src/arena/free_text.py`), and
   `FreeTextInterface` calls it. The tag goes into the transcript next to the action.
6. ✅ *(`68c5e14`, `1a7af3d`)* **The C1 action prompt** (§6.1). Update the prompt-difference test to cover C1.
7. **Offline re-scorer** for the bounds (§5 D), built with the analysis script: rebuild the state
   at decision *k* via `ReplayAgent`, re-parse, and send the result through the executor.
8. ✅ *(slice 2 close-out)* Update `PREREGISTRATION.md`: §2 (C1 row), §6 (the parser tag), §7 (bounds and the audit rule),
   and §11 (close the blocking item).

**Debt and convolution note.** This removes two misclassification paths (C1 parse failures and
C3 unknown ids both landing in `no_tool_call`) and one condition-specific leak into the shared
body (the rejection-feedback format). It adds one module (the parser) and one optional
dependency. It adds **no** second execution path: the parser only builds `ToolCall`s, and the
existing executor stays the single referee. The identifier resolver *moves* existing
exact-match lookups into one normalising function instead of adding a second copy.

---

## 11. Risks that remain

- **The reasonable-reader standard is still a judgement.** It is published, tagged, bounded and
  audited, which is as far as a deterministic parser can take it. Say so in threats to validity.
- **Tactics under C1 depend on the parser** (option D cannot re-score them). State this next to
  every C1 tactical figure.
- **Prose tolerance helps chatty models.** A model that ignores "nothing else" and reasons at
  length pays for it in output tokens, and that cost *is* measured. The parser should not also
  punish it with a rejection, because C2's channel tolerates text alongside a tool call too.
- **Over-fitting the parser to the pilot.** This is controlled by the changelog, the freeze and
  auditing on final-run data only (§7).

---

## Appendix — terms used above

- **Controlled natural language (CNL):** a subset of English with a formal grammar, so every
  accepted sentence has one meaning. Survey: Kuhn, *A Survey and Classification of Controlled
  Natural Languages*, Computational Linguistics 40(1), 2014 (*verify before citing*).
- **EBNF / PEG:** notations for writing a grammar down precisely. A parser generator turns the
  written grammar into a parser.
- **Lark:** a Python parser generator (Earley and LALR algorithms). Deterministic: the same input
  always gives the same parse or the same error.
- **Grammar-constrained decoding:** the model's output is restricted, token by token, to strings
  the grammar allows, so it cannot produce anything unparseable (llama.cpp GBNF, Outlines).
- **False reject / false accept:** the parser refusing text a careful human reads as one action,
  or accepting it as a *different* action from the one the human reads.
- **Sensitivity analysis:** re-computing a result under alternative reasonable choices to show
  whether a conclusion depends on one of them.
