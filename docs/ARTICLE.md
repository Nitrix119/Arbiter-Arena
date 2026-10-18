# Show, don't make them guess: how the action interface shapes LLM agents in a tactical game

*Logan Nilson, October 2026. Code, data and pre-registration: [github.com/Nitrix119/Arbiter-Arena](https://github.com/Nitrix119/Arbiter-Arena).*

## 1. Background and motivation

The plan for this project was always to have LLMs interact with an SRD-compatible combat
engine, but the focus was initially far different to what it became. My original vision
was a tool that would simply simulate battles with realistic, well-coordinated tactics,
so that a game master could quickly simulate how an encounter might play out. But while
building it, I realised how many questions there were to answer to get to the point of
an LLM playing the game. And rather than rush a solution, I wanted to explore those
questions.

The first of these, naturally, was how a model interacted with the engine and the world
model. I had heard that the latest paradigm was that the harnesses and interfaces were
far more important than the model itself, but I wanted to test for myself what impact
the interface could have upon the way these models interact with the same underlying
system: where and why they failed, and what influence the interface alone could have
over it.

The setting itself (effectively Dungeons & Dragons combat) was a perfect fit that I felt
I knew well enough to be deeply invested in building and exploring. An environment that
is deterministic for the harness, but full of uncertainty and long-term planning for the
model, which must contend with it solely by making tool calls and individual decisions
from an observation. It mirrors many of the elements of real, high-stakes use cases for
LLMs today, across areas involving autonomous control: a model that is asked to take
action, based on a set of potentially imperfect observations, and within the confines of
what it is able to and permitted to do.

The way I came to see it, a tool-using agent fails either by choosing badly, or by
proposing an action which the system cannot accept. The second of these tends to be
blamed on the model, but the way in which a model is able to act is decided by whoever
designed the system, and the model has no say in it. It might be asked to write free
text for a parser, fill in a tool call's raw parameters, or pick from a list of actions
which have already been checked as legal. With this in mind, I chose to hold the model
fixed and vary only that one decision.

Going in, I expected the interface to prove extremely impactful, as the paradigm
suggested, and for each new element introduced to make taking action easier, I
anticipated that there would be a clear payoff visible in the metrics.

**Related work.** The closest work to this one is *DungeonBench* (Ismayilov, Kara and
Oktay, 2026), a far broader benchmark of D&D combat. It covers most of the SRD's combat
rules, links fights together into whole adventuring days, and evaluates five frontier
models. Its models always act by choosing from an indexed list of legal options, which
is effectively this study's C3 (§3). It was published in July, and I only found it while
verifying citations at the study freeze (§4), so the two designs converged
independently. This did not come as a great surprise, given how popular D&D is and how
simple its combat is compared with other tabletop games, and I suspect we are the same
kind of enthusiast, each wanting to try our own ideas for LLMs and D&D.

I see DungeonBench as complementary to this study rather than competing with it. It
covers far more of the rules and links fights into whole adventuring days, but always
gives its models a menu, while this study looks only at that one choice. The results
here support its use of a menu, since the menu was the most reliable interface tested
for every model, and nothing in it appears to challenge them. They also show, however,
that this choice shapes both the scores and the way the models behave, which means a
benchmark's numbers are partly a property of the interface it uses. Its much finer
movement enumeration is an idea I would like to try in future, though it would need care
to balance resolution against a list too long to be useful.

## 2. Architecture

![One decision: the observation goes through the interface to the model; the engine validates and executes what it proposes, and the recorder keeps everything](https://raw.githubusercontent.com/Nitrix119/Arbiter-Arena/v1.0.0/docs/figures/architecture.png)

Every action a model proposes is either accepted as legal, or refused with a typed
reason (`destination_blocked`, `action_economy_spent`, `out_of_range`, …), which means
that validity is something the engine measures directly rather than something which has
to be judged. When an action is refused, the referee's reason is fed back to the model,
and it may try again. A failure budget of 3 consecutive or 5 total refusals ends any
turn which is going nowhere.

## 3. The four interface conditions

| Condition | How the model acts | What it sees |
|---|---|---|
| **C1, free text** | One line, `ACTION: attack raider-1 with Longbow`, read by a deterministic grammar | The state |
| **C2, raw tool calls** | `attack(action_name, defender_id)`, `move(x, z)`, … | The state |
| **C2+M, tool calls plus menu** | The same raw tool calls | The state **plus** the list of legal actions |
| **C3, menu choice** | `choose(action_id)` from the list | The state plus the list |

C2+M uses the same raw tool calls as C2, but with the list of legal actions visible, and
serves as the control between C2 and C3.

**What I decided, and why.** Avoiding an LLM parser for C1 was a clear and important
decision to me, despite it being initially considered. The heart of that choice was
simple: a non-deterministic factor parsing the model's action would leave doubt about
whether the outcome was solely because of the interface itself, or influenced by the LLM
performing parsing. This want for authenticity was carried into the way the study was
conducted, and my choice to pre-register and freeze the project was guided by a strong
trust in the scientific method. I truly believe that regardless of the scope or
importance of a study, it will benefit from an honest, proper methodology.

I realised that I needed to add the fourth interface condition of C2+M when first seeing
a chart of what each of the first three interfaces contained, and noting that there were
distinctly two changes between C2 and C3 - the menu, and the action selection format. If
one were to prove superior, I realised I could not truly be sure which of these two
changes had caused it, and to what extent, so a middle ground was necessary.

When I realised during the pilot that Gemini had all but solved the four scenarios, I
chose not to change them for honesty and to value the answer that it came with: for a
powerful enough LLM, in a simple enough setting, the interface barely matters - it will
find the way. I felt that this was worth reporting as it stood, and making the scenarios
harder would have only been likely to degrade the results for the other two models which
had not solved them. Ultimately, it was not a study on how hard of a scenario it took to
confound the models.

I felt proudest about how neutral and fair I feel the menus are, particularly when
offering AoE targeting: unique sets of targets are provided, but little guidance on what
the model actually wants to hit. Beyond naming its moves (which, as §8 notes, is itself
a small hint), nowhere does a menu truly guide the model to do something more clever,
and it is only by having its options laid out plainly that Sonnet was seen to perform
distinctly better when provided with it, despite doing little reasoning of its own.

## 4. Setup and reproducibility

- **Models**, each at the lowest reasoning setting its provider allows, on one pinned
  host, through OpenRouter:

  | Model | Class | Host | Reasoning |
  |---|---|---|---|
  | Nemotron 3.5 Lightning | Small open-weight | CoreWeave | Off |
  | Gemini 3.8 Flash | Fast commercial | Google AI Studio | Low |
  | Claude Sonnet 5.5 | Flagship commercial | Google Vertex | Low |

  These describe the class of product each model belongs to, and are not intended as a
  ranking of their capability.
- **Scenarios:** `kiting` (an archer against a slower brute), `alpha_strike` (a 2v2
  melee), `protect_squishy` (keep a fragile ally alive) and `aoe_placement` (a Fireball
  caster among allies and enemies), each against a fixed scripted opponent.
- **Design:** 3 models × 4 conditions × 4 scenarios × 10 paired seeds = 480 matches,
  plus 120 baseline matches (random, scripted and a utility-scoring heuristic).
- **Pre-registered** before any confirmatory data and tagged `study-freeze`:
  hypotheses, metrics, exclusions, decision rules, seeds and prompt hashes. Every later
  change is a dated deviation in the pre-registration.
- **Cost and integrity:** 18,023 model decisions and about 31M tokens, with $24.30 billed
  ($29.90 at list price, the difference being due to prompt caching). There were no
  infrastructure exclusions, and every match replayed exactly (100% replay).

## 5. Results

### 5.1 Validity across the four interfaces

The table below shows each model's first-attempt valid-action rate, measured over fresh
decisions (first attempts only, not retries after a refusal).

| Model | C1 | C2 | C2+M | C3 |
|---|---|---|---|---|
| Nemotron 3.5 Lightning | 0.33 | 0.58 | 0.85 | 1.00 |
| Gemini 3.8 Flash | 0.99 | 0.99 | 1.00 | 1.00 |
| Claude Sonnet 5.5 | 0.98 | 0.89 | 0.98 | 1.00 |

![First-attempt validity by condition for each model, with 95% intervals](https://raw.githubusercontent.com/Nitrix119/Arbiter-Arena/v1.0.0/docs/figures/validity.png)

Nemotron, the small model, supported all three of the hypotheses with registered
decision rules (H1–H3), with the full ordering of C3 > C2+M > C2 > C1 and a clear gap at
each step. It won 13 of its 40 matches in C1 and 25 of 40 in C3, and in the protection
scenario its fragile ally survived 6 times in 10 in C3, compared with only 1–2 in 10 in
the other conditions.

The registered verdicts for each hypothesis are given in the table below. These are the
report's paired cluster-bootstrap verdicts over the 40 shared (scenario, seed) pairs for
each model, where *Supported* means that the 95% interval of the contrast lies entirely
above zero.

| Model | H1 (C3 > C2+M > C2 > C1) | H2 (the deficit is spatial) | H3 (constraint buys legality more than tactics) |
|---|---|---|---|
| Nemotron | Supported | Supported | Supported |
| Gemini | Only C2+M > C2 (tiny; ceiling) | Supported (small effect) | Not supported (wins at the ceiling in 3 of 4 scenarios) |
| Sonnet | C3 > C2+M > C2 supported; **C2 < C1, reversed** | Supported | Not supported |

H2 should be read in terms of rates rather than counts. It asks whether the validity
deficit in C1 and C2 is concentrated in spatial actions (moving, and aiming area spells)
rather than in attacks or ending the turn, which depends on how often each type of
action fails. This is why it can be supported for Sonnet even though its most common
single error was in bookkeeping (§5.2): in C2, only 65% of its moves were valid at the
first attempt, compared with 85% of its attacks.

### 5.2 How validity fails

Breaking the refusals down by type showed a different pattern for each model. Nemotron's
failures were a mix of spatial and bookkeeping errors, the most common of which were as
follows:

1. In C2, attempting to "move" to the position where it already stood (754 times)
2. In C1, moving onto occupied ground (638 times)
3. In C1, acting after its action had already been spent (308 times)

Sonnet's failures in C2 were mostly bookkeeping, with 56 attacks made after its action
had already been spent. The menu removed whole categories of error outright, and C3 had
no refusals of any kind for any model. (Every count can be found in the report's
`summary.md`.)

Interestingly, however, validity and effectiveness did not always move together.
Nemotron's validity was higher in C2 than in C1 (0.58, compared with 0.33), yet its win
rate fell from 0.33 in C1 to only 0.05 in C2. Of its 1,614 fresh decisions in C2, 1,460
were moves, and it appears that the tool-call format pulled it into wandering around the
map rather than fighting.

### 5.3 Sonnet and the bare tool call

Sonnet's first-attempt validity was 0.98 in C1, 0.89 in C2, 0.98 in C2+M and 1.00 in C3,
and its tactical results followed the same pattern, dipping noticeably in C2 alone:

| Sonnet | C1 | C2 | C2+M | C3 |
|---|---|---|---|---|
| Win rate | 0.80 | **0.60** | 0.78 | 0.83 |
| Kiting: archer survives | 10/10 | **4/10** | 9/10 | 10/10 |

![Claude Sonnet 5.5's matches won, HP left, kiting survival and time out of melee, by condition](https://raw.githubusercontent.com/Nitrix119/Arbiter-Arena/v1.0.0/docs/figures/sonnet_tactics.png)

Bare C2 was the only condition in which the flagship model visibly struggled, and the
way in which it failed was very specific. Of its 56 refusals for acting after its action
had already been spent, 52 came immediately after an attack which the engine had just
accepted, meaning that it had tried to attack a second time in the same turn, a mistake
which it never made once in C1.

In C1, free text seemed to invite Sonnet to work through its turn in prose before
committing to an action. It wrote a line of reasoning alongside around 53% of its C1
commands, compared with 24–27% in every other condition, and that reasoning was largely
spatial bookkeeping done out loud, such as "edge to edge that is 0 ft, so I'm already in
melee range".

Being shown the options (C2+M and C3) also prevented the mistake, but in a different
way. C2 and C2+M use the same tool-call format and have a near-identical prose rate (26%
and 24%), so the only difference between them is the visible list of legal actions. That
list alone took Sonnet from 0.89 to 0.98 validity, and from 4 to 9 kiting survivals in
10.

My reading of why this affected Sonnet and not Gemini comes down to how each model
treats its reasoning setting. At "low" effort, Gemini still thinks briefly on almost
every turn, while Sonnet's adaptive thinking mostly skips it altogether: in the pilot,
only 19 of 663 requests returned any reasoning at all. The menu and free text each
appear to put back, in their own way, the deliberation that Sonnet skipped. It is worth
noting however that this is an exploratory reading of the results, and was not a
registered hypothesis.

This echoes the findings of Tam et al. (*Let Me Speak Freely?*, EMNLP 2024), who found
that format restrictions hurt reasoning by squeezing out the model's working, rather
than through any failures in parsing. In this study the restrictive format is the bare
tool call, and what this study tentatively adds is that simply showing the model its
legal options appeared to compensate for this, even without restricting it to them.

### 5.4 What the menu costs, and what it buys (H4)

A menu can only ever offer the options which someone thought to list, and this cost was
measured before any model was run (H4a), across the positions which real matches pass
through. The aiming menu reaches at least 75% of the distinct sets of creatures a
Fireball could catch (with a median of 92%). The movement menu offers only a few named
destinations per creature, such as closing in, retreating, or kiting to range, and
reaches as little as 33% of the positions that free movement can. This suggested that
the menu should cost a little on area spells and a lot on movement. In practice,
however, neither of these costs appeared in the results.

#### Area spells

The table below shows the number of allies caught per Fireball cast.

| Model | C1 | C2 | C2+M | C3 |
|---|---|---|---|---|
| Sonnet | 0.68 | 0.79 | 0.06 | 0.00 |
| Gemini | 0.13 | 0.18 | 0.00 | 0.00 |
| Nemotron | 1.30 | — | 1.46 | 0.13 |

(Nemotron made no area casts at all in C2, so there is nothing to report in that cell.)

Each placement in the menu lists every creature it would catch, with each marked as an
ally or an enemy. Gemini and Sonnet both made use of that list even in C2+M, where they
still had to aim by raw coordinates, while Nemotron saw the same list and still caught
1.46 allies per cast. For Nemotron, it was only by choosing from the menu (C3) that
friendly fire all but ended, with 2 allies caught across its 15 casts, while Gemini and
Sonnet caught no allies at all in C3. The number of enemies caught stayed roughly the
same throughout (1.4–1.9 per cast), which means that on area spells an enumerated aim
did not cost any expressivity, and in fact did better than free aiming at avoiding
allies. H4b originally predicted that C3 would do no better than C2 here, however before
any data was collected this was revised (as a dated deviation) to predict that C3 might
do better on area spells, since C2 has to compute coordinates and can get them wrong.
This result supports the revised direction.

![Allies caught per area cast by condition for each model, with the number of casts](https://raw.githubusercontent.com/Nitrix119/Arbiter-Arena/v1.0.0/docs/figures/friendly_fire.png)

#### Movement

The registered prediction for movement was that C3 would do no better than free
movement. Kiting is the scenario which rewards movement the most, and its score is the
share of the match which the archer spends out of melee (10 matches per cell):

| Kiting: time out of melee | C1 | C2 | C2+M | C3 |
|---|---|---|---|---|
| Nemotron | 0.18 | 0.15 | 0.72 | 0.76 |
| Gemini | 0.98 | 0.98 | 0.98 | 0.98 |
| Sonnet | 0.89 | 0.73 | 0.92 | 0.98 |

This prediction did not hold. For every model, C3 kited at least as well as any
condition with free movement, and better than all of them for Nemotron and Sonnet. In
C3, Sonnet matched the hand-built heuristic agent's 0.98, as Gemini did in every
condition, and its archer finished with 16.1 of 18 HP on average. Although the menu
offers only a few positions, "step back to range" is one of them, and this is the move
which kiting relies upon.

The loss which H4a measured is therefore real, but it appears that none of these
scenarios ever needed the positions the menu had lost. Testing this properly would
require a scenario which rewards a single precise position, such as a flank, a doorway
or a piece of cover, and none of the four scenarios do so. It should also be noted that
H4 has no registered decision rule, and so this result can only be described here, with
no verdict attached.

### 5.5 Cost

Measured per accepted action at list price, free text was the cheapest interface for
Sonnet ($0.0041, compared with $0.0069 in C2), as its prompt carries no tool definitions
and it rarely needed to retry. For the other two models the menu was cheapest instead,
with Gemini writing fewer output tokens when choosing from a list, and Nemotron no
longer paying for retries ($0.00012 in C3, compared with $0.00042 in C2).

### 5.6 Did the parser decide the result?

It did not, and this was checked twice. C1 is scored in three ways (a strict reading,
the live parser, and a lenient one), and all three agree exactly for every model, with
no response being unreadable. A blind human audit of 200 C1 responses also found only 2
disagreements (1.0%, interval 0.3–3.6%), neither of which was a fault in the parser: one
was a typo in a label, and the other was a response whose reasoning and committed action
disagreed. Even at the worst-case error rate, every verdict still stands.

**Doing the audit.** Labelling 200 responses was a mix of tedious and interesting,
solely based on which model I was labelling. Sonnet's reasoning prose was interesting to
read and occasionally quite charming, while labelling plain tool calls was fairly
tedious after dozens of very similar labels. Blind labelling definitely felt different,
however, because I fully believed the parser to be infallible. Were it to have made a
genuine mistake, or in the case where Sonnet's reasoning was inconsistent but its action
properly formatted, I would have been too likely to not question it had I been able to
see the parser's label. Finding that one of the two disagreements was my own error felt
mildly annoying, but ultimately was a mark of honest human labelling.

Overall, the experience did change my views of free text as an interface in a small way.
I had assumed that any form of free response would be plagued by inconsistent wording
causing parser errors, so I was pleasantly surprised to find how well even the weakest
model adopted the simple action syntax.

## 6. A failure story: Sonnet, kiting, seed 108

The clearest single example of how the menu helped comes from a pair of kiting matches
played by the same model, on the same seed, and with the same tool-call format, where
the only difference is whether the legal actions are listed. In both, an archer (18 HP,
40 ft of movement, and a longbow) faces a slower Bruiser (45 HP, with a greatsword), and
the winning play is to shoot and then step back every turn.

In C2, the archer shoots, then immediately tries to shoot again, and is refused because
its action has already been spent. After being told why, it retreats, however in rounds
2 and 3 it shoots and then ends its turn without moving at all, allowing the Bruiser to
close the gap. In round 4, with the Bruiser now next to it, it explains its reasoning:

> "The Bruiser is 5.5 ft away, so it's adjacent. I have no opportunity attacks to worry
> about, so I'll kite. First I'll move away to get distance, then shoot next turn. I
> can't do both in one action, so I'll attack now."

It then shoots and ends its turn while still in melee, having confused the prompt's rule
of 'one tool call per response' with a belief that it could only do one thing per turn,
either moving or attacking but not both. From round 5 onwards it goes back to moving and
shooting, but by then it has already taken too much damage, and the archer dies in round
10 with the Bruiser still on 14 of 45 HP, largely because of those three turns spent
standing still.

![Seed 108 in C2: the archer shoots and stays put while the Bruiser closes in, and the archer dies](https://raw.githubusercontent.com/Nitrix119/Arbiter-Arena/main/docs/figures/seed108_C2.gif)

In C2+M, the difference is visible from the very first turn. After shooting, the archer
reads its action count off the list and does not attempt a second shot ("My action count
is 0, so I can't attack this turn."), and from round 2 onwards it shoots and then
retreats on almost every turn:

> "Actions are 0, so I can't attack. I'll retreat to keep my distance from the Bruiser and
> stay in longbow range."

It wins in round 16 with 12 of 18 HP remaining, and in C3, on the same seed, it wins at
full health.

![Seed 108 in C2+M: the archer shoots and steps back every turn, keeps its distance, and wins](https://raw.githubusercontent.com/Nitrix119/Arbiter-Arena/main/docs/figures/seed108_C2M.gif)

In C2 the model stated quite plainly that it should kite, so it knew what it wanted to
do, but it had misread the rule of one tool call per response as allowing only one thing
per turn. In C2+M it could read its remaining actions off the list, and it stopped
making that mistake.

Both matches are included in the repository and can be watched directly. In a clone,
run `uvicorn web.app:app` and open
`http://localhost:8000/playback?match=sonnet_kiting_seed108_C2.jsonl&step=21` to see the
"I can't do both" turn, with the model's words displayed beside the board.

## 7. Implications for tool-using agents

The broadest implication of these results is that the interface should be measured along
with the model. A single "valid action rate" for a model means very little without
knowing the interface it was given, and in this study one model ranged from 33% to 100%
depending on the interface alone. Showing a model what is legal also appears to help,
even without restricting it to those options. C2+M, which gave raw tool calls along with
a visible list, recovered most of the gap for both Sonnet and Nemotron, and listing the
options in this way is cheap to do, while enforcing them remains a separate choice.

For Sonnet at least, the slips were in bookkeeping, namely keeping track of what it had
already done in a turn and what it still had left. Gemini did not make the same mistake,
so this may not apply to every capable model, but surfacing that state rather than
leaving the model to track it for itself appears to be a cheap way to help.

**What surprised me.** The result that surprised me the most was, without a doubt, that
Sonnet performed worse with bare tool calls than free text. The only instance of a model
becoming less reliable as the interface became more structured came from the model I
believed to be the best, which was greatly unexpected, and the way it lost track of what
it had already done was not a regression I had considered would occur.

Gemini, on the other hand, completely exceeded my expectations. To find that it hardly
mattered which interface it got was almost worrying, before I accepted that it does not
harm the study as a whole.

It goes without saying that I also could not have expected how strikingly different
"low" reasoning actually is between vendors, to the degree that Sonnet skipped it
entirely most of the time while Gemini only tried to keep it short.

As for whether the idea that the interface matters more than the model actually held up,
the answer depended almost entirely on which model was being tested. It held very
clearly for Nemotron, while it barely applied to Gemini at all, and for Sonnet the
interface only seemed to matter when it took away both its room to reason and its view
of the options.

## 8. Limitations

- **One environment**, four scenarios, three models, 10 seeds per cell.
- **No multiplicity correction** across the seven contrasts per model. Nemotron's
  ordering, Sonnet's C2 reversal and the friendly-fire gap are robust to this, although
  a borderline interval such as Gemini's C2+M > C2 is weaker as a result.
- **Exploratory analyses.** The reasoning-effort explanation, the between-model
  comparison and Nemotron's wandering were all exploratory, and none of them were
  registered in advance.
- **Sampling and reasoning differ between models.** Only Nemotron ran at temperature 0
  with a seed. Sonnet accepts neither, and Google advises against lowering Gemini's
  temperature. And "low" reasoning effort means a different amount of thinking per
  vendor (§5.3), so the between-model comparison mixes capability with both.
- **One neutral prompt.** Every condition shares a prompt that scripts no tactics, and it
  was not tuned to any model. A prompt engineered for each model might narrow the gaps.
- **Menu discretisation.** The movement menu reaches as little as a third of the
  positions free movement can (§5.4), and no scenario rewards a precise position, so
  this cost has been measured but has not yet been tested.
- **Ceiling effects.** Gemini saturates validity and tactics, so H3 was not supported for
  it, largely because there was no room left for any interface to improve on.
- **Format and affordance confound.** The menu also carries tactical hints in its labels,
  such as "retreat". C2+M separates seeing the options from being restricted to them,
  however it cannot separate the hint from the list itself.
- **Engine simplifications.** Moves are not blocked by creatures in the way (only by
  where they end), and opportunity attacks are not modelled. Both apply equally to every
  condition, but they make escaping in the positioning scenarios easier than the rules
  intend.
- **One author.** I built the engine, the interfaces and the scenarios myself. The
  pre-registration and the blind parser audit limit how much that can shape the results,
  but they cannot remove it entirely.

## 9. Reproduce it

```
pip install -e ".[web,dev]"
python -m src.arena.study run examples/study/demo.toml --out results/demo   # no API key
# download the data bundle (below) and unzip it into the repository root, then:
python -m src.arena.study verify results/final   # must be 100%
python -m src.arena.study report results/final   # rebuilds the report byte for byte
```

The data is available as [`arbiter-arena-study-1.0.0.zip`](https://github.com/Nitrix119/Arbiter-Arena/releases/download/v1.0.0/arbiter-arena-study-1.0.0.zip) from the
[v1.0.0 release](https://github.com/Nitrix119/Arbiter-Arena/releases/tag/v1.0.0), and contains every transcript, the report, the
blind audit, each condition's exact prompt, and the pre-registration, both as it was
frozen at the `study-freeze` tag and as it stands now with its dated deviations.
