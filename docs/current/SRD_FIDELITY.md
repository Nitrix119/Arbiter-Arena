# SRD 5.1 Fidelity — where the engine differs from the core combat rules

> **For agents.** This is the work list for moving the engine toward rules-as-written
> (RAW) SRD 5.1 combat. Each entry is one unit of work: an SRD citation, what the engine
> does today, and testable acceptance criteria. Pick an entry, follow §0, close it.
> Baseline audited: `main` after v1.0.1 (commit `951641a`), 2026-10-26.

## 0. How to use this document

### 0.1 Reading the SRD

- The source is the **CC-BY-4.0 edition of SRD 5.1**, kept locally at
  `docs/SRD_CC_v5.1.pdf` (gitignored; download it from
  https://dnd.wizards.com/resources/systems-reference-document if it is missing).
- `python tools/extract_srd.py` turns it into `docs/reference/srd_5.1.txt` (also
  gitignored; needs Poppler's `pdftotext`). Every page starts with `=== p.N ===`.
- **`SRD p.N` means the same page everywhere.** In this edition the PDF page number is
  the number printed on the page, so the text, a PDF viewer and paper all agree.
- Citations give page, section heading and a short quote. To read the full rule:
  `grep -n "=== p.95 ===" docs/reference/srd_5.1.txt`, then read from that line; or
  grep the quote. Read the whole section, not only the quote, before implementing.

### 0.2 Working an entry

1. **Read the RAW text** at the cited pages, then the entry's `Current behaviour` refs.
   The audit is a snapshot: confirm the behaviour still holds before you change it.
   `Evidence` quotes the output of an audit script. The scripts live in
   `.srd_work/probes/<AREA>/` on the maintainer's machine (gitignored). Where present, a
   script is a ready-made starting point for the failing test; the quoted output is the
   evidence either way.
2. **Check `Depends on`.** If a dependency is open, do that one first, or narrow your
   change so it does not build a second mechanism the dependency will replace.
3. **Write the acceptance criteria as failing tests** (CLAUDE.md §4). Tests must *run a
   real resolution* through `CombatSystem`, not inspect JSON shape. A test that pins a
   rule names the SRD rule it encodes (CLAUDE.md §9 2026-09-30), e.g.
   `# SRD p.95 "Opportunity Attacks": leaving reach provokes`.
4. **Fix the tests listed under `Tests pinning current behaviour`.** They assert today's
   behaviour and are expected to change. Update them deliberately, citing the entry ID.
5. **Handle `Arena impact`.** `src/arena` encodes today's rules in its tools, menus,
   observation, heuristic and prompt text. A rules fix that leaves the arena telling
   models "not modelled" is half done.
6. **An open question (Appendix B) is closed by a ruling, not code.**
   - Write the decision in its `Ruling` field, dated, with a line on why.
   - Set `Status: ruled (YYYY-MM-DD)`.
   - Update the acceptance criteria of every entry it unblocks, so they test the ruling.
   - If the ruling deliberately departs from RAW, also add an Appendix A entry.
   - Only the maintainer makes rulings. An agent may draft options, never decide.
7. **Close the entry here, in the same change.** Set `Status: closed (<commit>)` and add
   one line on what was done. Do **not** delete a closed entry. If you deliberately
   stop short of RAW, move it to Appendix A with the reason.

### 0.3 IDs, types and severity

- **IDs** are `<AREA>-<TYPE>-<NN>` (e.g. `MOVE-M-03`), stable forever. Use them in branch
  names, commit messages and test docstrings.
  - **AREA:** `TURN` turn structure and action economy, `MOVE` movement and position,
    `ATK` attacks, damage and hit points, `SPELL` spellcasting, `COND` conditions, checks
    and vision, `MON` stat blocks and legendary creatures.
  - **TYPE:** `M` missing, `D` deviation, `Q` open question (Appendix B), `I` intentional
    (Appendix A).
  - **Numbers are not priorities, and some are missing.** A gap is a duplicate retired
    during the audit, merged into the entry the other area kept: COND-D-02 into TURN-D-01,
    COND-D-05 into SPELL-D-08, MON-D-09 into SPELL-D-17, and an old MON magical-damage
    draft into ATK-M-13. TURN-D-02 was reused, and now means initiative ties.
- **Missing** = the engine has no implementation, or a correct but partial one.
  **Deviation** = the engine implements it and gets it wrong.
- **Severity**, the sort order within each area. A silent wrong answer always ranks
  above an honest refusal (CLAUDE.md §1, "decline loudly"):
  - **S1:** silently wrong in ordinary play (no error; wrong numbers or wrong legality).
  - **S2:** a core rule that changes most fights is absent, or silently wrong in an
    uncommon situation.
  - **S3:** an edge rule, or one needed only by some content.
  - **S4:** rare, cosmetic, or narrative-only in a simulator.
- **Size:** S (hours), M (a focused branch), L (a new subsystem; design first).

### 0.4 Scope

- **In scope:** the SRD 5.1 core combat rules: ability checks and saves (pp.76–84),
  adventuring rules that bear on combat (pp.84–89), the Combat chapter (pp.90–99),
  Spellcasting rules (pp.100–104), weapons and armor rules (pp.62–66), monster
  stat-block rules and legendary creatures (pp.254–260), and Conditions (pp.358–359).
- **Light-touch:** content (individual spells, monsters, class features). Each area
  ends with a short "content blocked" list naming the mechanic that blocks it; content
  is easy to add once the mechanic exists.
- **Out of scope:** variant rules that are not in SRD 5.1 (grid, flanking, facing),
  out-of-combat play, and the 2024 rules (SRD 5.2).
- **DM-adjudicated rules** are listed in Appendix B for the maintainer to rule on, not
  decided here.
- **Versioning.** Fixing these changes combat outcomes, so v1.0.x study bundles will
  no longer replay on newer code. That is expected: the published study is reproducible
  from its `1.0.x` tag.

## 1. Summary

The engine was built as an MVP for an agentic study, so the gaps are expected. 137
findings from a rule-by-rule audit of the core rules, each confirmed against the code and,
for every deviation but two, by a script that runs the real engine:

| Area | Missing | Deviations | Open questions | Intentional |
|---|---|---|---|---|
| TURN — turn structure, action economy | 13 | 2 | 3 | – |
| MOVE — movement and position | 17 | 4 | 3 | 2 |
| ATK — attacks, weapons, damage, hit points | 13 | 7 | 2 | – |
| SPELL — spellcasting | 9 | 21 | 1 | – |
| COND — conditions, checks, vision | 12 | 4 | 3 | – |
| MON — stat blocks, legendary creatures | 12 | 8 | 1 | – |
| **Total** | **76** | **46** | **13** | **2** |

By severity: 7 S1, 44 S2, 51 S3, 20 S4 among missing features and deviations (open
questions and intentional entries are graded too, but don't count here).

**The S1 entries: silently wrong in ordinary play.** Fix these first; each is small or
medium.

- **TURN-D-01:** incapacitated, stunned, paralyzed, petrified and unconscious creatures
  have their turn skipped entirely, so their conditions never expire and no
  start/end-of-turn effect runs for them.
- **MOVE-D-01:** a move can pass straight through a hostile creature (CODEBASE_REVIEW A30).
- **ATK-M-02:** ranged attacks made next to a hostile don't get disadvantage.
- **SPELL-D-01:** spells aimed at creatures are not range-checked unless an aim point is
  also passed (a Fire Bolt hit a goblin 1,000 ft away through the arena tool).
- **SPELL-D-02:** "Range: Self" is treated as unlimited range.
- **SPELL-D-07:** concentration doesn't end when the caster is incapacitated, or when it
  drops to 0 HP but passes the save.
- **SPELL-D-13:** the number of targets per cast is never checked (a 1st-level Magic
  Missile fired 12 darts).

**Themes worth knowing before you start:**

- **"Alive" means four things.** `Entity.is_alive()` is used for "has HP", "can act", "is on
  the battlefield" and "counts for victory". So an unconscious creature at full HP is
  treated as dead, while a creature at 0 HP with no condition still takes turns and
  attacks. Most 0-HP and incapacitation entries are one fix (§2, foundation F1).
- **The loader drops what it doesn't understand.** Unknown keys, unknown action types,
  abbreviated ability names and SRD-style save names all load silently as defaults
  (MON-D-07, MON-D-08, ATK-M-06, MOVE-D-04). A creature copied from the SRD loads as a
  different creature. Fix this early: every later MISSING entry adds keys to the schema.
- **Only attacks and spells can resolve.** Dash, Dodge, Disengage, Help, Hide, Ready,
  Search, Use an Object, Multiattack and every non-spell feature have no path
  (TURN-M-13).
- **Nothing happens off-turn.** No reactions, opportunity attacks, readied actions or
  legendary-action window (TURN-M-01 and its dependents).
- **Several rules live only in the arena.** The arena refuses things the engine would allow
  (an over-range aim, a 0-HP creature acting), and its menus guarantee ranges the engine
  doesn't check. Move each rule into the engine and let the arena rely on it.

## 2. Roadmap

Ordered so that each step builds on the last. Within a phase, items can be worked in
parallel unless one is listed as depending on another. Everything here is a pointer; the
entry holds the detail.

### Phase 0: rulings needed first (Appendix B)

These decide what the code should do, so settle them before the work they block.

| Ruling | Blocks |
|---|---|
| ATK-Q-01: which creatures die at 0 HP, and which fall unconscious | F1, ATK-M-10, ATK-M-11 |
| MOVE-Q-03: whether a 0-HP or dead creature still occupies its space | F1 (MOVE-D-03) |
| SPELL-Q-01: how much of a creature must be inside an area | SPELL-D-05 |
| MOVE-Q-02: how a mid-turn speed change alters movement left | F3 |
| MOVE-Q-01: what happens when forced movement is blocked | MOVE-M-08 |
| MON-Q-01: legendary actions per turn end | MON-M-01 |
| ATK-Q-02: how cover is determined | ATK-M-04 |
| COND-Q-01, COND-Q-02, COND-Q-03, TURN-Q-01, TURN-Q-02, TURN-Q-03 | their own entries; none blocks a foundation |

### Phase 1: independent fixes

No open dependencies. Mostly size S. Ordered by severity.

- **Spellcasting:** SPELL-D-01, SPELL-D-02, SPELL-D-13 (a fixed per-spell count first;
  slot- and level-based counts come with SPELL-M-05 and SPELL-M-04), SPELL-D-03,
  SPELL-D-04, SPELL-D-08, SPELL-D-09 (fixes CODEBASE_REVIEW A36), SPELL-D-12,
  SPELL-D-14, SPELL-D-16, SPELL-D-18, SPELL-D-05 (after SPELL-Q-01), SPELL-D-06,
  SPELL-D-21, SPELL-M-02.
- **Loader strictness:** MON-D-07, MON-D-08, MOVE-D-04, ATK-D-07, MON-M-09, MON-M-11.
- **Legendary-action guards:** MON-D-03, MON-D-04, MON-D-05 (the timing and incapacitation
  guards, MON-D-01 and MON-D-02, need F1 and F7).
- **Saves and crits:** COND-M-01, ATK-D-05.
- **Small corrections:** TURN-D-02, MOVE-D-02, ATK-D-04, ATK-D-06.

### Phase 2: foundations

Each foundation unlocks a cluster of entries. Suggested order F1 → F9; F2, F3, F5 and F6
are independent of each other.

- **F1. Alive, can act, present, defeated.**
  - **Start:** ATK-Q-01, then COND-M-05 (one "is incapacitated" check), COND-D-01,
    ATK-D-01, ATK-D-02, TURN-D-01.
  - **Then:** MOVE-D-03, SPELL-D-07, SPELL-D-20, SPELL-D-11, MON-D-02, MON-D-06.
  - **After that:** ATK-M-10 (death saves), ATK-M-11, TURN-Q-02.
  - See also `ENTITY_LIFECYCLE_DECISIONS.md` ("downed but present").
- **F2. Attack typing and distance on attack events.**
  - **Start:** ATK-M-01.
  - **Then:** ATK-M-02, SPELL-M-06, ATK-M-03, COND-M-02, COND-M-03, ATK-M-07.
- **F3. Current speed, separate from movement left.**
  - **Start:** MOVE-M-03, with MOVE-Q-02 decided.
  - **Then:** MOVE-M-05, MOVE-M-04, COND-M-04 → MOVE-M-06, MOVE-M-07.
- **F4. A resolution path for actions that are neither attacks nor spells.**
  - **Start:** TURN-M-13 (with MON-D-07).
  - **Then:**
    - TURN-M-05 (Dash, also needs F3), TURN-M-07 (Dodge), TURN-M-08 (Help);
    - TURN-M-02 with MON-M-05 (the Attack action and Multiattack);
    - MON-M-04 (traits), MON-M-02 (Limited Usage, which also needs F1's TURN-D-01);
    - MON-M-06, MON-M-07.
- **F5. Move paths and a movement event.**
  - **Start:** MOVE-D-01.
  - **Then:** MOVE-M-02, MOVE-M-08 (with MOVE-Q-01).
  - The movement event is also what F7's opportunity attacks need.
- **F6. Ability checks and contests.**
  - **Start:** COND-M-06.
  - **Then:** TURN-M-03 (initiative as a DEX check), ATK-M-08 (grapple, shove), COND-M-08,
    MON-M-08.
- **F7. Decisions outside your own turn.**
  - **Start:** TURN-M-01. One mechanism serves reactions and the legendary window alike.
  - **Then:**
    - MOVE-M-01 (opportunity attacks; needs F5), TURN-M-06 (Disengage);
    - SPELL-M-03 (reaction spells), TURN-M-10 (Ready);
    - MON-D-01, MON-M-01 (with MON-Q-01), MON-M-10, TURN-M-04 (surprise).
  - **Arena work:** the turn driver must be able to ask a non-active agent for a decision,
    and the prompt's "not modelled" text in `src/arena/interfaces.py` changes.
- **F8. Damage-modifier pipeline.**
  - **Start:** ATK-D-03, with `COMPOSITE_DAMAGE_DESIGN.md`.
  - **Then:** COND-D-03, ATK-M-13, COND-M-10.
- **F9. Spell effect identity and scaling.**
  - **Start:** SPELL-D-19 (combining effects), SPELL-D-10, SPELL-D-17 with MON-M-03.
  - **Then:** SPELL-M-04 (caster level), SPELL-M-05.
  - SPELL-M-05 is the deferred upcasting design, which the maintainer wants to discuss
    first.

### Phase 3: larger subsystems (design before building)

- **Vision and obstruction:** COND-M-07 first; then ATK-M-04 (cover, with ATK-Q-02),
  SPELL-M-01 (clear path), COND-M-09 (hiding, with COND-Q-02), COND-D-06, TURN-M-09
  (Hide), TURN-M-11 (Search). COND-D-04 (charm legality, with COND-Q-01) fits here too.
- **Equipment and derived statistics:** ATK-M-05, ATK-M-06, ATK-M-12, ATK-M-09,
  SPELL-M-07, SPELL-M-08, COND-M-11, TURN-M-12.
- **Environment and three-dimensional movement:** MOVE-M-09 (fly, swim, climb, burrow),
  MOVE-M-10, MOVE-M-11, MOVE-M-12, MOVE-M-13, MOVE-M-14, MOVE-M-15, MOVE-M-16, MOVE-M-17,
  SPELL-M-09 (cylinder height, which needs vertical positions).
- **Time beyond one fight:** SPELL-D-15 (long casting times), COND-M-12 (rests).
- **Narrative fields:** MON-M-12.

## 3. Missing features

### TURN — Turn structure and action economy (SRD pp.84, 87, 90–94)

#### TURN-M-01 — Add a reaction framework: off-turn responses to a trigger
- **Status:** open
- **Type / severity:** MISSING (partial) — S2
- **SRD:** p.91 "Reactions": "A reaction is an instant response to a trigger of some kind, which can occur on your turn or on someone else's." "When you take a reaction, you can't take another one until the start of your next turn. If the reaction interrupts another creature's turn, that creature can continue its turn right after the reaction."
- **Current behaviour:** the *resource* exists and is correct: `ActionResources.reactions` (`src/models/action_resources.py:47`), refilled on the owner's own `TURN_START` (`rules/global/action_economy_refill.json`), spent by any action whose cost has `reactions` (a spell with `casting_time.type: "reaction"` derives `REACTION_COST`, `src/models/action.py:159-175`). What is missing is everything that makes it a reaction:
  - **No off-turn decision path.** Every resolver begins with `_assert_active` (`src/combat/combat_system.py:631-646`), which refuses anyone but the current creature (`NOT_YOUR_TURN`). The only off-turn entry is `resolve_legendary_action` (`:452`), which is not a reaction, spends no reaction, and has no timing guard (MON-D-01).
  - **No trigger binding.** `CastingTime.reaction_trigger` (`src/models/spell_properties.py:140`) is a display string only; nothing offers the reaction when that trigger happens.
  - **Reaction-cost actions are usable proactively on the owner's own turn**, with no trigger at all (loud refusal on others' turns, silent acceptance on one's own).
  - `trigger` blocks (`src/spells/blocks/triggers.py`) do fire off-turn, but automatically: they never ask the holder, never spend a reaction, and have no once-per-round guard. So an author could only fake a reaction as a free, always-on passive.
  - No event exists for leaving reach / moving (needed by opportunity attacks, MOVE-M-01) or "a creature you can see casts a spell" (Counterspell, SPELL-M-03).
  - "Incapacitated → can't take reactions" (`rules/entity_effects/conditions/incapacitated.json` `_note`: "pending reaction system") and surprise's "can't take a reaction until that turn ends" (TURN-M-04) have nothing to bind to.
- **Evidence:** `.srd_work/probes/TURN/p05_reaction_framework.py`:
  ```
  derived cost: ActionCost(actions=0, bonus_actions=0, reactions=1, movement=0.0)
  current: A
  B's reaction on A's turn refused: not_your_turn
  B cast the reaction spell on its own turn, untriggered: damage 16 | B reactions left: 0 | actions left: 1
  ```
  Searches: `grep -rni reaction src rules examples` — only the resource, the cost constant, `CastingTimeType.REACTION`, `reaction_trigger`, the arena prompt's "not modelled" line, and the `incapacitated` TODO. No `ENTITY_MOVED`/`MOVE_*`/`LEAVE_REACH` event in `src/combat/events.py`; `docs/current/BLOCK_REFERENCE.md` §Events lists none.
- **Gap:** RAW a reaction is taken in response to a perceivable trigger, on any creature's turn, at most once until the start of the reactor's next turn, and it can interrupt the triggering turn, which then resumes.
- **Acceptance criteria:**
  1. A creature holding a reaction-cost action bound to a trigger (e.g. "is hit by an attack") is offered it when that trigger occurs on another creature's turn; taking it spends its reaction and resolves before the triggering turn continues.
  2. Having spent its reaction on round N, it cannot react again until its own next `TURN_START` (already true of the counter; must hold for the new path).
  3. On its own turn, with no trigger pending, a reaction-only action is refused with a specific code (today it resolves).
  4. An incapacitated creature (COND-M-05) is never offered a reaction.
- **Depends on / unblocks:** needs a decision point that can call a controller (human/agent) mid-turn — the arena's agents act only on their own turn (`src/arena/turn_driver.py`). Shares that off-turn decision point with MON-M-01 / MON-D-01 (legendary-action phase). Dependents: **MOVE-M-01** (opportunity attacks), **SPELL-M-03** (reaction-time spells: Shield, Counterspell, Hellish Rebuke, Feather Fall), TURN-M-10 (Ready), TURN-M-06 (Disengage's meaning), TURN-M-04 (surprise's reaction clause).
- **Tests pinning current behaviour:** `tests/test_action_economy.py::TestActionCostField::test_spell_reaction_cost` (cost derivation — keep). No test pins own-turn reaction casting.
- **Arena impact:** large. `src/arena/interfaces.py:75` tells models reactions are "not modelled"; that line and its byte-identity test (`tests/arena/test_interfaces.py`) change. The turn driver needs an off-turn decision call; transcripts/metrics need an off-turn decision record; menus (`action_space.legal_actions`, `enumeration.py`) must stop offering reaction-cost actions on the owner's turn (today they are offered whenever affordable); the heuristic must value holding a reaction.
- **Known in:** CODEBASE_REVIEW §4.3 ("nothing triggers a reaction off the event bus"); `incapacitated.json` `_note`.
- **Size:** L — a new subsystem: trigger-bound reaction actions, a "reaction window" in the resolvers / event bus that can suspend and resume a turn, a controller callback, plus the arena plumbing.

#### TURN-M-02 — Track the Attack action as a turn state, so one action can hold several attacks with movement between
- **Status:** open
- **Type / severity:** MISSING — S2
- **SRD:** p.93 "Attack": "With this action, you make one melee or ranged attack. … Certain features, such as the Extra Attack feature of the fighter, allow you to make more than one attack with this action." p.91 "Moving between Attacks": "If you take an action that includes more than one weapon attack, you can break up your movement even further by moving between those attacks."
- **Current behaviour:** one `resolve_attack` = one attack roll = one whole `ActionCost(actions=1)` (`src/combat/combat_system.py:300-339`; `AttackAction` default cost). There is no notion of "the Attack action is in progress, N attacks remain", and no record that the creature *took the Attack action* this turn. `grep -rni "multiattack\|extra.attack\|attacks_per_action" src examples rules` → only CODEBASE_REVIEW §4.4. The only way to make two attacks is `resource_defaults.actions: 2`, which also allows two spells, two Dashes, etc. Loud in form (a second attack is refused `action_economy_spent`), but every shipped martial character silently fights with half its attacks: `examples/creatures/characters/fighter.json` (proficiency 3, level 5+) has `Longsword {'actions': 1}`, `Handaxe {'actions': 1}` and gets one attack per turn.
- **Evidence:** the searches above; `fighter.json` read.
- **Gap:** RAW the Attack action contains a number of attacks set by features; the creature may move between them, and the remaining attacks belong to that action (they cannot be traded for a spell). Several rules key off "you took the Attack action" (two-weapon fighting, grapple/shove replacing one attack, loading).
- **Acceptance criteria:**
  1. A creature with "2 attacks per Attack action" can `resolve_attack` twice for one action (actions 1 → 0 after the first; the second allowed; a third refused).
  2. Between those attacks it can `move_entity`, and the second attack's range is checked from the new position.
  3. After one attack it cannot spend the rest of the Attack action on a spell.
  4. A turn-scoped "took the Attack action" fact is readable by rules (for ATK-M-09 two-weapon fighting) and cleared at `TURN_START`.
- **Depends on / unblocks:** MON-M-05 (Multiattack — the monster-side composition of the same machinery). Unblocks ATK-M-08 (grapple/shove replace one attack), ATK-M-09 (two-weapon fighting), ATK-M-06 (loading), Haste's "one weapon attack only" action (SPELL), Extra Attack content.
- **Tests pinning current behaviour:** `tests/test_action_economy.py::TestCombatSystemResourceEnforcement::test_resolve_attack_fails_without_resources` (a second attack is refused — still right for a one-attack creature; keep and add the multi-attack case).
- **Arena impact:** menus/enumeration must offer "next attack of this action" and moves between attacks; the heuristic's whole-turn planner (`src/arena/heuristic/plan.py`) would need multi-attack plans; observation should show attacks remaining.
- **Known in:** CODEBASE_REVIEW §4.4 (Multiattack); MON-M-05; ATK cross-area note ("no 'took the Attack action this turn' fact").
- **Size:** M — attack-action state on `Entity.resources` (attacks remaining, committed action), a stat-block field for attacks per Attack action, loader support.

#### TURN-M-05 — Add the Dash action
- **Status:** open
- **Type / severity:** MISSING — S2
- **SRD:** p.93 "Dash": "When you take the Dash action, you gain extra movement for the current turn. The increase equals your speed, after applying any modifiers."
- **Current behaviour:** absent. `grep -rni "dash" src rules examples --include=*.py --include=*.json` → only `free_text.py` typographic-dash handling. No action, block or tool. A data workaround (a self-targeted "spell" whose program is `add_resource movement = entity.stat_block.resource_defaults['speed']`) loads and runs, but it is a spell (TURN-M-13) and can read only the stat-block base speed: speed modifiers exist only as `TURN_START` top-ups of the movement budget (Longstrider), so "speed after modifiers" is unreadable (MOVE-M-03).
- **Evidence:** `.srd_work/probes/TURN/p06_dash_as_data.py`:
  ```
  A movement at turn start with Longstrider: 40
  after workaround Dash: 70.0 (RAW: 40 + 40 = 80)
  SPELL_CAST events emitted: 2 (the Dash counted as a spell)
  ```
- **Gap:** an action (or a bonus action, via features) that adds the creature's current speed to its movement for this turn.
- **Acceptance criteria:**
  1. Speed 30: after Dash, movement available this turn is 60 (minus anything already spent: move 10, Dash → 50 left).
  2. With Longstrider (+10), Dash adds 40.
  3. With speed reduced to 15, Dash adds 15; with speed 0, Dash adds 0.
  4. Dash costs the action (or the bonus action when a feature grants it), and the extra movement is gone at the next `TURN_START`.
- **Depends on / unblocks:** TURN-M-13 (a non-spell action path), MOVE-M-03 (current speed). Unblocks Cunning Action, Expeditious Retreat, Haste's Dash option.
- **Tests pinning current behaviour:** none.
- **Arena impact:** a new tool/menu option; the kiting scenario changes materially (the Bruiser could close a 40-ft kite by dashing); heuristic planner needs dash plans.
- **Known in:** ENGINE_MAP lead; MOVE cross-area note.
- **Size:** S once TURN-M-13 and MOVE-M-03 exist.

#### TURN-M-03 — Make initiative a Dexterity check that features can modify
- **Status:** open
- **Type / severity:** MISSING (partial) — S3
- **SRD:** p.90 "Initiative": "every participant makes a Dexterity check to determine their place in the initiative order." p.9 Feral Instinct: "you have advantage on initiative rolls." p.12 Jack of All Trades: "add half your proficiency bonus, rounded down, to any ability check you make that doesn't already include your proficiency bonus."
- **Current behaviour:** `InitiativeTracker.add_entity` rolls `d20 + DEX mod + initiative_modifier` (`src/combat/initiative.py:45-64`). `initiative_modifier` is an `add_combatant` argument only (`src/combat/combat_system.py:249-260`): no stat-block field, no loader key (`grep -rni initiative src/loaders src/models examples/creatures` → only `Entity.initiative_roll`), no stat modifier, no advantage/disadvantage. The arena's `_reroll_initiative` (`src/arena/match.py:61`) re-adds every entity with **no** modifier, silently discarding any passed at setup. Because no ability-check system exists (COND-M-06), check-wide modifiers (Jack of All Trades, Remarkable Athlete, exhaustion's disadvantage on ability checks, COND-M-04) cannot reach initiative. Cosmetic: `Entity.initiative_roll` stores the raw d20 and the web UI shows that as "initiative" (`web/routers/combat.py:145`), not the total that set the order.
- **Evidence:** the searches above; code read.
- **Gap:** initiative is a DEX ability check: anything that modifies DEX checks, or initiative specifically (flat bonus, advantage), applies.
- **Acceptance criteria:**
  1. A creature whose JSON declares an initiative bonus (+5) rolls d20+DEX+5, and keeps it through the arena's seeded re-roll.
  2. A creature with advantage on initiative rolls 2d20 and keeps the higher (seeded test).
  3. Once COND-M-06 lands, a DEX-check modifier (or exhaustion's disadvantage) applies to initiative.
  4. The displayed initiative is the total.
- **Depends on / unblocks:** COND-M-06 (ability checks), COND-M-04 (exhaustion). Unblocks Feral Instinct, lair actions on count 20 (MON-M-01).
- **Tests pinning current behaviour:** `tests/rules/entity_effects/conditions/test_blinded.py` uses `initiative_modifier=100` to force order (keep the parameter or migrate).
- **Arena impact:** `_reroll_initiative` must carry modifiers. None otherwise.
- **Known in:** COND cross-area note (initiative is `roll_d20() + DEX mod`, routing through checks is TURN's call); otherwise new.
- **Size:** S–M — a stat-block/loader field and an adv/dis path in `add_entity`; full DEX-check routing waits on COND-M-06.

#### TURN-M-04 — Model surprise at the start of an encounter
- **Status:** open
- **Type / severity:** MISSING — S3
- **SRD:** p.90 "Surprise": "Any character or monster that doesn't notice a threat is surprised at the start of the encounter. If you're surprised, you can't move or take an action on your first turn of the combat, and you can't take a reaction until that turn ends."
- **Current behaviour:** absent. `grep -rni surpris src web rules examples` → no hits (only prose in `docs/current/ARTICLE_DRAFT.md`). No "surprised" flag on `Entity`, no scenario field, no stealth-vs-passive-perception comparison (no ability checks, COND-M-06). `CombatSystem.start_combat` (`src/combat/combat_system.py:263-298`) has no pre-combat step.
- **Evidence:** the grep above; code read.
- **Gap:** step 1 of "Combat Step by Step" (p.90): determine surprise. A surprised creature gets its first turn but can't move or act in it, and has no reaction until that turn ends.
- **Acceptance criteria:**
  1. A combatant marked surprised at `start_combat` has, on its first turn, its moves and actions/bonus actions refused; on its second turn it acts normally.
  2. Its reaction is unavailable until the end of its first turn (observable once TURN-M-01 exists).
  3. Optionally: surprise set by DEX (Stealth) of hiders vs passive WIS (Perception) of each opponent (COND-M-06, COND-M-09).
- **Depends on / unblocks:** TURN-M-01 (reaction clause), COND-M-06/TURN-M-09 (stealth). Unblocks MON-D-02's "surprised legendary creature" clause, Feral Instinct, Thief's Reflexes, assassin-style content.
- **Tests pinning current behaviour:** none.
- **Arena impact:** a scenario field and an observation flag; menus empty (except `end_turn`) on a surprised turn.
- **Known in:** MON-D-02 notes surprise is absent; otherwise new.
- **Size:** S for a scenario-set flag (a TURN_START/TURN_END rider pair); M with stealth vs perception.

#### TURN-M-06 — Add the Disengage action
- **Status:** open
- **Type / severity:** MISSING — S3 (S2 once opportunity attacks exist)
- **SRD:** p.93 "Disengage": "If you take the Disengage action, your movement doesn't provoke opportunity attacks for the rest of the turn."
- **Current behaviour:** absent (`grep -rni disengage src rules examples` → none). Today it would have no effect, since opportunity attacks are absent (MOVE-M-01), and the arena prompt tells models OAs are not modelled.
- **Evidence:** the grep above.
- **Gap:** an action (bonus action via features) that sets a turn-scoped "movement doesn't provoke OAs" flag.
- **Acceptance criteria:**
  1. After Disengage, leaving a hostile's reach on that turn offers no opportunity attack; on the next turn it does again.
  2. Disengage costs the action (or bonus action via Cunning Action / Nimble Escape).
- **Depends on / unblocks:** MOVE-M-01, TURN-M-01, TURN-M-13. Unblocks Cunning Action, Nimble Escape (goblin), Haste's Disengage option.
- **Tests pinning current behaviour:** none.
- **Arena impact:** new tool/menu option, meaningful only with OAs; prompt text.
- **Known in:** MOVE-M-01 dependents; ENGINE_MAP lead.
- **Size:** S once OAs exist.

#### TURN-M-07 — Add the Dodge action
- **Status:** open
- **Type / severity:** MISSING — S3
- **SRD:** p.93 "Dodge": "Until the start of your next turn, any attack roll made against you has disadvantage if you can see the attacker, and you make Dexterity saving throws with advantage. You lose this benefit if you are incapacitated … or if your speed drops to 0."
- **Current behaviour:** absent (`grep -rni dodge src rules examples` → none). Existing blocks can nearly express it, but only as a spell (TURN-M-13): a permanent `lifetime` with an `ATTACK_DECLARED` → `grant_disadvantage` rider and a `TURN_START` → `end_lifetime` rider on the dodger. The obvious authoring, `duration_rounds: 1`, gives **no** protection at all: a lifetime held by its caster ticks on the caster's `TURN_END`, so it expires at the end of the very turn it was taken (the "until the start of your next turn" anchor is SPELL-D-11's territory). Missing pieces: "if you can see the attacker" (COND-M-07), "lose it if incapacitated or speed drops to 0" (COND-M-05, MOVE-M-03).
- **Evidence:** `.srd_work/probes/TURN/p08_dodge_as_data.py`:
  ```
  Dodge (workaround): B's attack on A had disadvantage — during A's dodge: True, after A's next turn began: False
  Dodge (duration_rounds 1): B's attack on A had disadvantage — during A's dodge: False, after A's next turn began: False
  ```
- **Gap:** an action granting the above until the start of the dodger's next turn.
- **Acceptance criteria:**
  1. A dodges; B attacks A before A's next turn → disadvantage; after A's next `TURN_START` → none.
  2. A dodging creature's DEX save on that interval has advantage.
  3. If A becomes incapacitated, or its speed drops to 0, before its next turn, the benefit ends.
  4. An attacker A cannot see gets no disadvantage from the Dodge (once COND-M-07 exists).
- **Depends on / unblocks:** TURN-M-13; COND-M-05, COND-M-07, MOVE-M-03; SPELL-D-11 (a "until the start of your next turn" duration anchor would make this a one-liner).
- **Tests pinning current behaviour:** none.
- **Arena impact:** new tool/menu option; heuristic needs a dodge plan (relevant to the "protect the squishy" scenario).
- **Known in:** new.
- **Size:** S once TURN-M-13 exists.

#### TURN-M-08 — Add the Help action (attack form)
- **Status:** open
- **Type / severity:** MISSING — S3
- **SRD:** p.93 "Help": "you can aid a friendly creature in attacking a creature within 5 feet of you. … If your ally attacks the target before your next turn, the first attack roll is made with advantage."
- **Current behaviour:** absent (`grep -rnwi help src/combat src/spells rules examples` → none). Blocks could express the effect (an `ATTACK_DECLARED` rider: attacker = chosen ally and defender = chosen target → `grant_advantage`, then `end_lifetime`), but an action needs two chosen creatures (ally + enemy within 5 ft of the helper), which no action/targeting shape offers, and there is no non-spell action path (TURN-M-13). The ability-check form needs checks (COND-M-06) and a ruling (COND-Q-03).
- **Evidence:** the grep above; `TargetingType` (`src/models/spell_properties.py:53-59`) has no "ally + enemy" shape.
- **Gap:** an action that marks (ally, target): the ally's first attack roll against that target before the helper's next turn has advantage; the target must be within 5 ft of the helper.
- **Acceptance criteria:**
  1. H helps ally X against E (E within 5 ft of H); X's next attack on E before H's next turn has advantage; X's second attack does not.
  2. Help with E more than 5 ft from H is refused with a specific code.
  3. If H's next turn starts before X attacks, the advantage is gone.
- **Depends on / unblocks:** TURN-M-13 (with two-creature targeting); COND-M-06 / COND-Q-03 for the check form.
- **Tests pinning current behaviour:** none.
- **Arena impact:** new tool/menu option with two targets; coordination scenarios (alpha_strike) gain a cooperative action.
- **Known in:** COND-Q-03 (check form); new for the attack form.
- **Size:** S–M.

#### TURN-M-09 — Add the Hide action (the action shell; hiding itself is COND's)
- **Status:** open
- **Type / severity:** MISSING — S3
- **SRD:** p.93 "Hide": "When you take the Hide action, you make a Dexterity (Stealth) check in an attempt to hide, following the rules for hiding."
- **Current behaviour:** absent (`grep -rnwi "hide\|hidden" src/combat src/spells rules examples` → none; arena "hidden" hits are about information policy). There is no Stealth check to make (COND-M-06) and no hidden state for it to set (COND-M-09).
- **Evidence:** the grep above.
- **Gap:** an action (bonus action via Cunning Action / Nimble Escape) that rolls DEX (Stealth) and, on success, applies COND-M-09's hidden state.
- **Acceptance criteria:**
  1. Taking Hide costs the action (or bonus action via a feature) and rolls a Stealth check through COND-M-06's path.
  2. Its result is recorded on the creature for COND-M-09's rules to consume.
- **Depends on / unblocks:** COND-M-06, COND-M-09, COND-Q-02 (when hiding is allowed), TURN-M-13.
- **Tests pinning current behaviour:** none.
- **Arena impact:** new tool/menu option; information policy must hide the hidden creature's position (today "Position is never hidden in v1", `src/arena/information_policy.py:10`).
- **Known in:** COND-M-09 / COND-Q-02.
- **Size:** S once COND-M-09 exists.

#### TURN-M-10 — Add the Ready action (including readied spells held by concentration)
- **Status:** open
- **Type / severity:** MISSING — S3
- **SRD:** p.93-94 "Ready": "you decide what perceivable circumstance will trigger your reaction. Then, you choose the action you will take in response to that trigger, or you choose to move up to your speed in response to it." "When you ready a spell, you cast it as normal but hold its energy … To be readied, a spell must have a casting time of 1 action, and holding onto the spell's magic requires concentration."
- **Current behaviour:** absent (`grep -rni "ready\|readied" src/combat src/spells rules examples` → none). Every prerequisite is missing except concentration, which exists (`Entity.begin_concentration`, `src/models/entity.py:312`): no reaction framework (TURN-M-01), no trigger a controller can name, no off-turn move.
- **Evidence:** the grep above.
- **Gap:** an action that stores (trigger, response action or move) until the start of the readier's next turn; when the trigger occurs the readier may spend its reaction to take the response. A readied spell spends its slot when readied, is held with concentration (dropping any other concentration), and is lost if concentration breaks or the reaction is not used.
- **Acceptance criteria:**
  1. A readies an attack against "an enemy comes within 5 ft"; E moves adjacent on its turn → A is offered the attack, spends its reaction, and E's turn then continues.
  2. A readied 1-action spell spends its slot at readying, ends A's other concentration, and is lost (slot still spent) if A fails a concentration save before releasing it.
  3. If the trigger never occurs, the readied action lapses at A's next `TURN_START`.
  4. A spell with a casting time other than 1 action cannot be readied.
- **Depends on / unblocks:** TURN-M-01 (reaction window), a movement event (MOVE-M-01 introduces one), TURN-M-13, SPELL concentration rules (SPELL-D-09).
- **Tests pinning current behaviour:** none.
- **Arena impact:** large for a model: a trigger vocabulary to choose from, and an off-turn decision.
- **Known in:** new.
- **Size:** L — mostly the reaction framework; the Ready action itself is M on top.

#### TURN-M-13 — Give class/feature/monster actions that are neither attacks nor spells a resolution path
- **Status:** open
- **Type / severity:** MISSING — S3
- **SRD:** p.93 "Actions in Combat": "you can take one of the actions presented here, an action you gained from your class or a special feature, or an action that you improvise. Many monsters have action options of their own in their stat blocks."
- **Current behaviour:** the engine resolves exactly two kinds of action: `AttackAction` (`resolve_attack`) and `SpellAction` (`resolve_spell`). The loader's fallback turns every other action into an `Action(ActionType.ABILITY)` with no program and no damage (`src/loaders/stat_block_loader.py:405-412`); `ActionType.ITEM` exists but nothing builds one. `Action.program` exists on the base class (`src/models/action.py:54`) but no resolver runs a base `Action`'s program: `resolve_attack`/`resolve_spell` crash on it with `AttributeError` (not a `RuleViolation`), and `resolve_legendary_action` only logs "uses X" (`src/combat/combat_system.py:554-556`). So Second Wind, Action Surge, Cunning Action, Dash/Disengage/Dodge/Help/Hide/Ready/Search/Use an Object (TURN-M-05..TURN-M-12) have no non-spell home; the only workaround is authoring them as a "spell" (which emits `SPELL_CAST`, sits in `known_spells`, and would be hit by spell rules such as SPELL-D-14). The loader's silent acceptance of an unknown `type` is MON-D-07.
- **Evidence:** `.srd_work/probes/TURN/p09_generic_action_inert.py`:
  ```
  'Second Wind' type='ability' -> Action action_type=ABILITY program=[] damage=[]
  'Bite' type='melee' -> Action action_type=ABILITY program=[] damage=[]
  resolve_attack -> AttributeError 'Action' object has no attribute 'range_ft'
  resolve_spell -> AttributeError 'Action' object has no attribute 'spell_level'
  ```
  (the `program` given to Second Wind in the JSON was dropped by the loader). `.srd_work/probes/TURN/p06_dash_as_data.py` shows the spell workaround: `SPELL_CAST events emitted: 2 (the Dash counted as a spell)`.
- **Gap:** a creature can take an action from a feature or stat block whose effect is a block program with its own cost (action / bonus action / reaction) and targeting, without being a spell.
- **Acceptance criteria:**
  1. A creature JSON action `{"type": "ability", "name": "Second Wind", "cost": {"bonus_actions": 1}, "program": [healing 1d10+5 on self]}` loads with its program (validated by `validate_program`) and resolves through one engine call, spending a bonus action and healing; no `SPELL_CAST` is emitted.
  2. Calling `resolve_attack`/`resolve_spell` with the wrong action kind raises a `RuleViolation` naming the kind, not `AttributeError`.
  3. The arena exposes such actions (tool / menu entry) once they exist.
- **Depends on / unblocks:** MON-D-07 (loader refusal of unknown types), MON-M-04 (traits). Unblocks every TURN-M-05..TURN-M-12 action, Cunning Action, Nimble Escape, Second Wind, Action Surge, breath weapons authored as non-spells.
- **Tests pinning current behaviour:** none found asserting the ABILITY fallback is inert.
- **Arena impact:** a fifth tool (or a generic `use_action`) plus menu entries; the prompt's tool list changes in every condition.
- **Known in:** MON-D-07 (loader side); new for the resolution path.
- **Size:** M — a `resolve_action` path running a base `Action`'s program with cost, targeting and range checks, plus loader support for `program` on non-attack actions.

#### TURN-M-11 — Add the Search action
- **Status:** open
- **Type / severity:** MISSING — S4
- **SRD:** p.94 "Search": "When you take the Search action, you devote your attention to finding something. Depending on the nature of your search, the GM might have you make a Wisdom (Perception) check or an Intelligence (Investigation) check."
- **Current behaviour:** absent (`grep -rnwi search src/combat src/spells rules examples` → none). Nothing in combat can be hidden (COND-M-09) and there are no checks (COND-M-06), so there is nothing to search for.
- **Evidence:** the grep above.
- **Gap:** an action that rolls Perception/Investigation and can reveal hidden creatures (and, in exploration, objects).
- **Acceptance criteria:** A searches with a Perception total ≥ a hidden creature's Stealth total → that creature is no longer hidden from A.
- **Depends on / unblocks:** COND-M-06, COND-M-09, TURN-M-13.
- **Tests pinning current behaviour:** none.
- **Arena impact:** none until hiding exists.
- **Known in:** COND-M-09 mentions Hide/Search.
- **Size:** S once hiding exists.

#### TURN-M-12 — Model objects: the free object interaction and the Use an Object action
- **Status:** open
- **Type / severity:** MISSING — S4
- **SRD:** p.91 "Other Activity on Your Turn": "You can also interact with one object or feature of the environment for free, during either your move or your action. … If you want to interact with a second object, you need to use your action." p.94 "Use an Object": "When an object requires your action for its use, you take the Use an Object action." p.87 "Interacting with Objects"; p.92 "Interacting with Objects Around You" (draw or sheathe a sword, withdraw a potion, open a door…).
- **Current behaviour:** the engine has no objects, items, inventory or equipped state: weapons are always in hand, there are no potions, doors or levers, and objects cannot be attacked. `ActionType.ITEM` (`src/models/action.py:29`) is never constructed. `grep -rni "inventory\|equip\|potion\|object_interaction\|sheathe" src rules examples` → none.
- **Evidence:** the grep above.
- **Gap:** a per-turn free object interaction (one), a Use an Object action for items that need it (potions, magic items) or for a second interaction, and drawing/stowing weapons. (Objects' AC/HP and always-failing STR/DEX saves (p.87) need objects as targets.)
- **Acceptance criteria:**
  1. A creature can draw a weapon as part of its move or attack for free once per turn; a second interaction that turn costs its action.
  2. Drinking a potion of healing costs the action (Use an Object) and heals.
  3. Attacking with an unequipped weapon without the free draw is refused.
- **Depends on / unblocks:** an item/inventory model (none exists), TURN-M-13. Unblocks potions, magic items, Fast Hands (Thief), haste's Use an Object option.
- **Tests pinning current behaviour:** none.
- **Arena impact:** none today (no items in scenarios).
- **Known in:** new.
- **Size:** L for items; the free-interaction counter alone is S.

### MOVE — Movement and position (SRD pp.84–86, 91–92, 95, 99)

#### MOVE-M-01 — Add opportunity attacks when a creature leaves a hostile's reach
- **Status:** open
- **Type / severity:** MISSING — S2
- **SRD:** p.95 "Opportunity Attacks": "You can make an opportunity attack when a hostile
  creature that you can see moves out of your reach. ... you use your reaction to make
  one melee attack against the provoking creature." Also p.92 "Moving Around Other
  Creatures": "If you leave a hostile creature's reach during your move, you provoke an
  opportunity attack."
- **Current behaviour:** `move_entity` (`combat_system.py:688-757`) emits **no event**,
  so no rule or reaction can observe movement at all; there is no reaction-taking path
  for a non-active creature (reactions refill at TURN_START via
  `rules/global/action_economy_refill.json`, but nothing ever spends one). The arena
  prompt tells models OAs are "not modelled" (`src/arena/interfaces.py:75`), so the
  omission is declared to LLM agents but is silent in the engine/web UI.
- **Evidence:** `.srd_work/probes/MOVE/p07_no_opportunity_attack.py` (a probe
  subscribes to every `EventType` and walks the runner 30 ft out of an adjacent guard's
  reach): `runner hp 30 | guard reactions left 1 | events emitted during the move: none`.
  Searched `src/` for `opportunit`, `reaction` (only the resource/casting-time enum and
  `installs_reactions` flags), and `src/combat/events.py` for any MOVE event: none.
- **Gap:** leaving reach on one's own movement (walk, not teleport or forced movement)
  must offer each hostile, sighted, non-incapacitated creature with a reaction one melee
  attack, resolved *before* the mover leaves reach (i.e. at the boundary point on the
  path). Disengage suppresses it for the turn.
- **Acceptance criteria:**
  1. Medium A adjacent to hostile B (B has a 5-ft melee attack and 1 reaction); A moves
     30 ft directly away → B's melee attack is resolved against A exactly once, B's
     reactions go 1→0, and the attack happens with A at the reach boundary.
  2. Same, B has 0 reactions left → no attack.
  3. Same, but A is moved by `push_entity` (forced) → no attack.
  4. A moves while staying within B's reach (circling) → no attack; A moves from outside
     to inside reach → no attack.
- **Depends on / unblocks:** needs a movement event (e.g. a MOVED/LEAVING_REACH event
  carrying the path) and a reaction-decision channel for the non-active creature
  (TURN area: reactions); melee-vs-ranged attack typing and reach (ATK area); Disengage
  action (TURN area); MOVE-D-01 path model. Unblocks Sentinel-style content, mount rules.
- **Tests pinning current behaviour:** none found that assert "no OA"; no test greps the
  "Not modelled" prompt sentence (searched `tests/arena/`).
- **Arena impact:** large: a reaction decision point for the non-active side (a new
  tool or an automatic policy), observation of reactions remaining, prompt text at
  `interfaces.py:75`, heuristic retreat/kite plans (`heuristic/plan.py`
  `_may_disengage`) must price the OA; menus would want to label provoking moves.
- **Known in:** CODEBASE_REVIEW §4 item 3 ("nothing triggers a reaction ... No Shield,
  no OA"); arena prompt `interfaces.py:75`.
- **Size:** L — new event + reaction subsystem; the OA rule itself is then a small
  rule program.

#### MOVE-M-02 — Charge difficult terrain, including other creatures' spaces
- **Status:** open
- **Type / severity:** MISSING — S2
- **SRD:** p.91 "Difficult Terrain": "Every foot of movement in difficult terrain costs 1
  extra foot. ... The space of another creature, whether hostile or not, also counts as
  difficult terrain." p.92: "Remember that another creature's space is difficult terrain
  for you." (p.85 restates the half-speed rule for travel.)
- **Current behaviour:** the movement cost is the straight-line distance, full stop
  (`combat_system.py:725-740`). There is no terrain model on the battlefield and no
  per-segment cost, so crossing an ally's space costs nothing extra — **silently**.
- **Evidence:** `.srd_work/probes/MOVE/p01_through_hostile.py`: `through an ally: moved
  to 20.0 movement left 10.0 (RAW: the 5 ft inside the ally's space is difficult terrain
  -> 25 ft)`. Searched `src/`, `rules/`, `examples/`, `web/routers/` for `difficult`
  (only "disadvantage"-adjacent hits in `saving_throw.py`), `terrain`: no terrain data,
  no loader field, no block.
- **Gap:** each foot moved inside difficult terrain (any creature's space, or authored
  terrain zones) costs 2 ft; multiple sources don't stack beyond that; crawling and
  squeezing add their own +1 on top (p.92: crawling in difficult terrain costs 3 ft).
- **Acceptance criteria:**
  1. Medium A at x=0, ally B (Medium) at x=10; A moves to x=20 → charged 25 ft
     (20 + 5 inside B's space), movement 30→5.
  2. A move that stays clear of every creature space and terrain zone costs its plain
     length (current behaviour preserved, incl. the 7.1-ft diagonal).
  3. With a scenario-authored difficult-terrain zone covering x∈[5,15], a 20-ft move
     across it costs 30 ft; two overlapping zones still cost 30 ft.
  4. A move whose surcharged cost exceeds the remaining budget is refused with the
     existing `insufficient_resource`-style shortfall code, nothing spent.
- **Depends on / unblocks:** MOVE-D-01 (path model); for authored terrain, a scenario /
  battlefield data model (none exists). Unblocks crawling (MOVE-M-04), squeezing,
  Spike Growth/Entangle-style content.
- **Tests pinning current behaviour:** `tests/test_movement.py::TestMoveEntity::
  test_move_cost_is_euclidean_distance` and `test_move_cost_is_continuous_not_rounded_
  to_a_grid` (keep passing: they have no creature on the path).
- **Arena impact:** menus' `_clear_option_along` budgets by straight distance and would
  need the true cost; observation should expose terrain if any is authored; prompt says
  "open battlefield" (`interfaces.py:65`), which stays true until terrain exists.
- **Known in:** new (ENGINE_MAP lead).
- **Size:** M for creature spaces (path-cost integration over MOVE-D-01's sweep); L for
  authored terrain (battlefield model + loader + observation).

#### MOVE-M-03 — Model a creature's current speed, with modifiers, separate from movement left
- **Status:** open
- **Type / severity:** MISSING (partial) — S2
- **SRD:** p.84 "Speed": "Every character and monster has a speed, which is the distance
  in feet that the character or monster can walk in 1 round." p.91 "Movement and
  Position": "On your turn, you can move a distance up to your speed." p.93 "Dash":
  "Any increase or decrease to your speed changes this additional movement by
  the same amount." Spell texts: Haste "the target's speed is doubled"; Ray of Frost
  "its speed is reduced by 10 feet until the start of your next turn".
- **Current behaviour:** there is no "speed" on `Entity`; only the per-turn budget
  `ActionResources.movement` (`src/models/action_resources.py:47`), reset each
  TURN_START to the stat-block constant by `Entity.refill_resources`
  (`src/models/entity.py:287-293`, `defaults.get("speed", 30)`). The only lever is the
  `add_resource` block (`src/spells/blocks/state.py:182-197`), which adds feet to the
  *budget*. So:
  - Longstrider (`examples/spells/longstrider.json`) works as a TURN_START budget top-up
    (40 ft next turn ✓), but casting it does not raise the current turn's allowance.
  - Haste (`examples/spells/haste.json`) adds an action but **does not double speed**.
  - Ray of Frost (`examples/spells/ray_of_frost.json`) has no speed step at all.
  - `add_modifier` with `stat: "speed"` validates and installs (the `stat` namespace is
    open by design, `state.py:273`), but no code reads a `speed` modifier
    (the readers are `ac`, `spell_save_dc`, `spell_attack_bonus` in `entity.py:385-412`,
    `saving_throw.<ability>` in `src/utils/saving_throw.py`, and a UI breakdown) — the natural way to
    author Ray of Frost is a silent no-op.
  - Nothing can halve, zero or multiply speed; the arena heuristic reads the raw
    stat-block number (`src/arena/heuristic/features.py:75-76`, `plan.py:200-204`).
  All of this is **silent**: the spells resolve and their movement clauses are dropped.
  (The shipped Wizard knows Haste, `examples/creatures/characters/wizard.json:12`.)
- **Evidence:** `.srd_work/probes/MOVE/p04_speed_spells.py` (real casts, global rules
  installed):
  `Longstrider: movement right after casting on self: 30.0 (RAW speed 40 now; 30 unspent)`
  `Longstrider: movement at next turn start: 40 (RAW 40)`
  `Haste: movement at next turn start: 30 actions: 2 (RAW speed doubled -> 60)`
  `Ray of Frost: hit = True ; foe movement on its next turn: 30 (RAW 30 - 10 = 20)`
  `.srd_work/probes/MOVE/p08_speed_modifier_noop.py`: `speed modifiers on entity:
  [('speed', -10)]` / `movement at next turn start: 30 (a -10 speed modifier -> 20)`.
- **Gap:** RAW needs an effective speed = base speed with ordered modifiers (additive
  bonuses/penalties, multipliers such as Haste ×2 and exhaustion ½, and "becomes 0"
  overrides that also block bonuses — grappled/restrained), recomputed whenever a
  modifier starts or ends; the turn's budget is that speed minus distance already moved
  (and Dash, stand-up, mount costs are fractions of *that* speed).
- **Acceptance criteria:**
  1. A 30-ft creature hasted on a previous turn starts its turn with 60 ft of movement;
     when Haste ends mid-round, its next turn has 30 ft.
  2. Ray of Frost hits a 30-ft target → on the target's next turn it has 20 ft; after
     the caster's following turn starts, 30 ft again.
  3. A creature that has moved 10 ft and then gains Longstrider (+10) may move 30 ft
     more this turn (40 − 10); one that has moved 10 ft and then has its speed reduced by
     10 may move 10 more (20 − 10). (See MOVE-Q-02 for the ruling.)
  4. Speed 0 overrides every bonus: a restrained creature with Longstrider has 0 ft.
- **Depends on / unblocks:** a speed-modifier mechanism (a modifier keyed `speed` on the
  entity, like the existing `saving_throw.<ability>` modifiers, and a block that adds
  it under a lifetime). Unblocks MOVE-M-04/05/06, Dash (TURN), stand-up cost, mounting,
  "Moving a grappled creature". Haste's ordering vs its own lifetime is already
  recorded (SPELL_SYSTEM_REMAINING §2).
- **Tests pinning current behaviour:** tests that build Longstrider's budget top-up
  (grep `longstrider` under `tests/`) — they should keep passing if the new modifier
  yields the same 40; `Entity.refill_resources` callers that expect the raw stat-block
  speed.
- **Arena impact:** observation exposes `"speed": dict(block.resource_defaults)`
  (`src/arena/observation.py:270`) — should expose effective speed; heuristic threat
  model and `_may_disengage` (`features.py:75`, `plan.py:200-208`) must read effective
  speed; menus already read `resources.movement` (fine).
- **Known in:** CODEBASE_REVIEW §4 item 7 ("speed variants"); condition `_note`s for
  grappled/restrained/exhaustion ("pending movement system").
- **Size:** M — an effective-speed property + a speed modifier block + refill reading
  it; then one-line data fixes to Haste and Ray of Frost.

#### MOVE-M-04 — Let a prone creature stand up (half speed) and make it crawl otherwise
- **Status:** open
- **Type / severity:** MISSING — S2
- **SRD:** p.91-92 "Being Prone": "You can drop prone without using any of your speed.
  Standing up ... costs an amount of movement equal to half your speed. ... You can't
  stand up if you don't have enough movement left or if your speed is 0. ... Every foot
  of movement while crawling costs 1 extra foot." p.359 "Prone": "A prone creature's only
  movement option is to crawl, unless it stands up and thereby ends the condition."
- **Current behaviour:** `move_entity` (`combat_system.py:688-757`) never consults
  conditions; a prone creature walks at full rate. There is no "stand up" (or "drop
  prone") operation anywhere: the only way a condition ends is disposal of the lifetime
  scope that applied it (SPELL_SYSTEM_REMAINING "No block removes a condition"), so a
  prone creature stays prone (keeping its attack disadvantage from
  `rules/entity_effects/conditions/prone.json`) until that scope expires, possibly
  never. **Silent.** No shipped content applies prone today, but any JSON can
  (`apply_condition` accepts `prone`).
- **Evidence:** `.srd_work/probes/MOVE/p05_condition_speed.py` (prone applied through the
  real `apply_condition` block with the shipped condition rules; target moves on its own
  turn): `prone conditions=['prone'] budget at turn start=30 -> moved 30 ft, 0.0 ft left
  [RAW: must crawl: 30 ft of crawling costs 60]`. Searched `src/`, `rules/`, `web/`,
  `src/arena/tools.py` for `stand`, `crawl` (only the `prone.json` `_note`), `prone`
  (only the condition enum/rule): no stand-up path.
- **Gap:** a prone creature must pay 2 ft per foot moved (3 in difficult terrain) or
  spend half its *current* speed to stand (ending prone); standing is impossible with
  speed 0 or insufficient movement; dropping prone is free.
- **Acceptance criteria:**
  1. Prone 30-ft creature at turn start: a 10-ft move costs 20 ft (movement 30→10) and
     it is still prone.
  2. Same creature stands up: movement 30→15, prone removed (its rider uninstalled), and a
     following 15-ft move costs 15.
  3. Stand up with 14 ft left (speed 30), or with speed 0 (restrained) → refused with a
     coded `RuleViolation`, nothing changes.
  4. Drop prone costs 0 movement and applies the condition.
- **Depends on / unblocks:** MOVE-M-03 (half of *current* speed); a way to end a condition
  by type (new block or engine op); melee-vs-ranged attack typing for the rest of prone
  (COND/ATK). Unblocks Shove (ATK), falling (MOVE-M-10), mount rules.
- **Tests pinning current behaviour:** none found that assert prone movement.
- **Arena impact:** a new `stand_up` (and possibly `drop_prone`) tool or a `move` flag;
  observation must show prone; menus must price moves at crawl cost; heuristic `plan.py`
  needs a stand-up step.
- **Known in:** `rules/entity_effects/conditions/prone.json` `_note` ("crawling costs
  double movement, standing up costs half speed (pending movement system)").
- **Size:** M — movement-cost multiplier hook + a stand-up operation/tool.

#### MOVE-M-05 — Enforce speed 0 for grappled and restrained creatures
- **Status:** open
- **Type / severity:** MISSING (partial) — S2
- **SRD:** p.358 "Grappled": "A grappled creature's speed becomes 0, and it can't benefit
  from any bonus to its speed." p.359 "Restrained": same sentence.
- **Current behaviour:** grappled is marker-only (`rules/entity_effects/conditions/
  grappled.json`, `"program": []`); restrained implements its attack/DEX-save effects but
  not speed. Movement refill (`entity.py:287-293`) and `move_entity` ignore both, so a
  grappled or restrained creature moves its full speed **silently**. Speed bonuses
  (Longstrider's TURN_START `add_resource`) would also still apply.
- **Evidence:** `.srd_work/probes/MOVE/p05_condition_speed.py`:
  `grappled conditions=['grappled'] budget at turn start=30 -> moved 30 ft, 0.0 ft left`
  and the same line for `restrained`.
- **Gap:** while either condition is present the creature's speed is 0 (no willing
  movement, no stand-up) and no speed bonus applies; forced movement still works.
- **Acceptance criteria:**
  1. Restrained 30-ft creature starts its turn → movement 0; `move_entity` 5 ft is
     refused with the shortfall code; nothing changes.
  2. Same with Longstrider active → still 0.
  3. Condition ends mid-turn (its scope disposed) → the creature may move its normal
     speed minus distance already moved (MOVE-Q-02).
  4. `push_entity` on a restrained creature still moves it.
- **Depends on / unblocks:** MOVE-M-03 (speed-0 override). Grappled's own end conditions
  (grappler incapacitated; moved out of reach) need grapple tracking (ATK/COND) and
  forced movement (MOVE-M-08).
- **Tests pinning current behaviour:** none found.
- **Arena impact:** observation should show speed 0 / conditions; menus already return
  `[]` when `movement < 1` (`action_space.py:373-375`), so they follow automatically.
- **Known in:** `grappled.json` and `restrained.json` `_note`s ("pending movement system").
- **Size:** S once MOVE-M-03 exists (a speed-override rule in each condition program).

#### MOVE-M-08 — Give forced movement (pushes, pulls) a data path from spells and rules
- **Status:** open
- **Type / severity:** MISSING — S2
- **SRD:** Thunderwave (spell text, `examples/spells/thunderwave.json` `description`): "On a
  failed save, a creature takes 2d8 thunder damage and is pushed 10 feet away from you."
  p.95 "Opportunity Attacks": "You also don't provoke an opportunity attack when ...
  someone or something moves you without using your movement, action, or reaction."
  p.358 "Grappled": the condition ends "when a creature is hurled away by the
  thunderwave spell."
- **Current behaviour:** `CombatSystem.push_entity` (`combat_system.py:759-783`) exists
  and is unit-tested (`tests/test_movement.py::TestPushEntity`), but nothing calls it:
  no block, rule, resolver, arena tool or web handler (only `move_entity` is called, from
  `src/arena/tools.py:549` and `web/routers/combat.py:485`). The block catalogue has no
  push/pull/teleport block (`src/spells/blocks/*`). So Thunderwave's push is **silently**
  dropped: the spell resolves, the damage lands, the target stays put. `push_entity`
  itself checks only the destination (raises on overlap) and lets `y` change with no
  falling (MOVE-M-10).
- **Evidence:** `.srd_work/probes/MOVE/p04_speed_spells.py` (real Thunderwave cast, failed
  save): `Thunderwave: result [('Foe', 13, {'total': 13, 'dc': 15, 'save_success':
  False})]` / `Thunderwave: foe position before (5.0, 0.0) after (5.0, 0.0) (RAW failed
  save -> pushed 10 ft away, to x=15)`. Callers: `grep -rn "push_entity\|move_entity"
  src web --include=*.py` → only the two `move_entity` call sites above.
- **Gap:** a block (e.g. `push`, `pull`, later `teleport`) that moves the current target a
  distance along a direction defined relative to the caster/origin, without spending the
  target's movement, provoking OAs, or being bound by its speed/conditions; with a
  declared outcome when the path is blocked (MOVE-Q-01).
- **Acceptance criteria:**
  1. Caster at x=0, Medium target at x=5 fails Thunderwave's save → target ends at x=15,
     its movement budget unchanged; on a success it stays at x=5.
  2. Two targets in the cube both fail → each is pushed directly away from the caster.
  3. A target whose push path is blocked behaves per MOVE-Q-01's ruling, never raising out
     of the spell (the damage already applied stays applied).
  4. A pushed creature that was grappled by a creature it is pushed out of reach of loses
     the grappled condition (once grapple tracking exists).
- **Depends on / unblocks:** MOVE-Q-01 ruling; a movement event so grapple/OA logic can
  tell forced from willing (MOVE-M-01). Unblocks Shove's push option (ATK),
  Eldritch Blast + Repelling Blast, Gust of Wind, etc.
- **Tests pinning current behaviour:** `tests/test_movement.py::TestPushEntity::
  test_push_still_checks_overlap` (pins "raise on overlap" — change if the ruling is
  "stop short").
- **Arena impact:** none today (only Fireball is in arena scenarios,
  `src/arena/scenarios.py:191-200`); a pushing spell later would need its predicted
  displacement in AoE menus/observation.
- **Known in:** CODEBASE_REVIEW §4 item 7 ("Forced movement (Thunderwave push)").
- **Size:** M — new block + direction resolution + blocked-path policy; Thunderwave JSON
  gains one step.

#### MOVE-M-06 — Halve speed at exhaustion level 2 and zero it at level 5
- **Status:** open
- **Type / severity:** MISSING — S3
- **SRD:** p.358 "Exhaustion": "Level ... 2 Speed halved ... 5 Speed reduced to 0" and "A
  creature suffers the effect of its current level of exhaustion as well as all lower
  levels."
- **Current behaviour:** `ConditionType.EXHAUSTION` has no level and
  `rules/entity_effects/conditions/exhaustion.json` is marker-only; movement is
  unaffected (**silent**).
- **Evidence:** `.srd_work/probes/MOVE/p05_condition_speed.py`: `exhaustion
  conditions=['exhaustion'] budget at turn start=30 -> moved 30 ft, 0.0 ft left`.
- **Gap:** speed must follow the exhaustion level (≥2 halved, ≥5 zero).
- **Acceptance criteria:**
  1. Exhaustion level 2, base speed 30 → 15 ft of movement at turn start.
  2. Level 2 + Haste → 30 (×2 and ×½).
  3. Level 5 → 0, and Longstrider does not help.
- **Depends on / unblocks:** exhaustion level tracking (COND area); MOVE-M-03.
- **Tests pinning current behaviour:** none found.
- **Arena impact:** observation of effective speed (see MOVE-M-03).
- **Known in:** `exhaustion.json` `_note`.
- **Size:** S after COND's level tracking and MOVE-M-03.

#### MOVE-M-07 — Stop a frightened creature from willingly moving closer to its fear source
- **Status:** open
- **Type / severity:** MISSING — S3
- **SRD:** p.358 "Frightened": "The creature can't willingly move closer to the source of
  its fear."
- **Current behaviour:** `frightened.json` implements only attack disadvantage; the
  condition records no source (no `bindings` like charm's `charmer`), and `move_entity`
  ignores it, so a frightened creature can walk straight up to its source (**silent**).
- **Evidence:** `.srd_work/probes/MOVE/p05_condition_speed.py` (`run_frightened`):
  `frightened victim moved from x=40 to x= 10.0 toward its fear source at x=0 [RAW:
  can't willingly move closer]`.
- **Gap:** a willing move that brings the creature closer to the source is refused;
  forced movement is exempt.
- **Acceptance criteria:**
  1. Source at x=0, frightened creature at x=40: move to x=10 → refused (coded), nothing
     spent; move to x=50 → allowed.
  2. `push_entity` toward the source → allowed.
  3. A frightened condition applied without a recorded source fails at load (validator
     demands the binding) or the movement guard declines loudly.
- **Depends on / unblocks:** source binding on the condition (COND); a movement
  pre-check hook (a cancellable movement event would serve MOVE-M-01 too). Sub-question
  needing a ruling: is "closer" measured at the endpoint only or at every point of the
  path, and centre-to-centre or nearest point? (RAW silent; most tables judge by the
  path — no step may reduce the distance.) State the choice in the test.
- **Tests pinning current behaviour:** none found.
- **Arena impact:** menus would drop `toward_melee:<source>` options; observation should
  name the fear source.
- **Known in:** `frightened.json` `_note` ("Cannot willingly move closer to fear source
  (pending movement system)").
- **Size:** S-M — a binding plus a movement guard.

#### MOVE-M-09 — Add flying, swimming, climbing and burrowing speeds and switching between them
- **Status:** open
- **Type / severity:** MISSING — S3
- **SRD:** p.91 "Using Different Speeds": "If you have more than one speed, such as your
  walking speed and a flying speed, you can switch back and forth between your speeds
  during your move. Whenever you switch, subtract the distance you've already moved from
  the new speed." p.92 "Flying Movement": "If a flying creature is knocked prone, has its
  speed reduced to 0, or is otherwise deprived of the ability to move, the creature
  falls, unless it has the ability to hover or it is being held aloft by magic".
- **Current behaviour:** one speed only: `StatBlock.resource_defaults["speed"]`
  (`src/models/stat_block.py:21,39`). The loader merges `resource_defaults` with no key
  check (`src/loaders/stat_block_loader.py:152-154`), so `"fly": 60` is accepted and
  ignored (**silent at load**). A willing move that changes altitude is refused
  **loudly** (`combat_system.py:716-726`, `DESTINATION_BLOCKED`, "cannot fly"); a
  creature already off the ground (placed or pushed) walks through the air at that
  height (`test_a_creature_placed_off_the_ground_moves_at_its_own_height`). No hover
  flag; no Fly spell.
- **Evidence:** `.srd_work/probes/MOVE/p06_air_and_size.py`: `resource_defaults with
  'fly': accepted silently -> {..., 'speed': 30, 'fly': 60}` and `walked 20 ft through
  the air at y = 60.0 hp = 50 movement left 10.0`. Searched `src/`, `rules/`,
  `examples/`, `web/routers/` for `fly`, `flying`, `swim`, `climb`, `burrow`, `hover`:
  no hits in models/loader/blocks.
- **Gap:** per-mode speeds loaded from JSON (with unknown keys rejected), a move declaring
  (or implying) its mode, the switch rule above, vertical moves allowed only with a fly
  speed, and the flying-creature fall trigger (prone / speed 0 / incapacitated) unless
  it hovers.
- **Acceptance criteria:**
  1. Loader: `resource_defaults: {"speed": 30, "fly": 60}` loads a fly speed of 60; an
     unknown key (`"flly"`) raises naming the valid keys.
  2. A creature with fly 60 moves from y=0 to y=20 (cost = 3D distance); without one the
     move is refused as today.
  3. Speed 30, fly 60: fly 20, then walk 10 (remaining walk 0), then fly 30 → allowed;
     a further 1-ft fly → refused (60 − 60).
  4. A non-hovering flyer at y=30 that becomes prone → falls to the ground (MOVE-M-10).
- **Depends on / unblocks:** MOVE-M-03 (speeds as effective values); MOVE-M-10.
  Unblocks Fly, flying monsters (e.g. SRD dragons, harpies), aquatic creatures.
- **Tests pinning current behaviour:** `tests/test_movement.py::TestMoveEntity::
  test_a_voluntary_move_cannot_change_altitude` (keep for creatures without fly) and
  `test_a_creature_placed_off_the_ground_moves_at_its_own_height` (contradicts RAW for a
  non-flyer: it should fall).
- **Arena impact:** `move` already accepts an optional `y` (`tools.py:249-263`); prompt
  says y is 0 unless off the ground (`interfaces.py:67-69`); menus generate ground-plane
  options only; observation would need per-mode speeds.
- **Known in:** CODEBASE_REVIEW §4 item 7 ("speed variants/senses"); the `move_entity`
  comment at `combat_system.py:717-722`.
- **Size:** M — loader fields, a speed-mode model, a mode argument on moves.

#### MOVE-M-15 — Halve speed while dragging or carrying a grappled creature
- **Status:** open
- **Type / severity:** MISSING — S3
- **SRD:** p.96 "Moving a Grappled Creature": "When you move, you can drag or carry the
  grappled creature with you, but your speed is halved, unless the creature is two or
  more sizes smaller than you."
- **Current behaviour:** there is no grapple action and no grappler↔grappled link
  (grappled is a marker-only condition, `grappled.json`); `move_entity` moves only the
  mover. Nothing to drag.
- **Evidence:** searched `drag`, `grappl` in `src/` (only the condition enum and
  `grappled.json`), `src/arena/tools.py` (no grapple tool).
- **Gap:** when a grappler moves, the grappled creature moves with it (forced movement,
  no OA, stays within reach), and the grappler's speed is halved unless the grappled
  creature is ≥ 2 sizes smaller.
- **Acceptance criteria:**
  1. Medium grappler (speed 30) grappling a Medium creature moves 15 ft (OK) and the
     grappled creature ends adjacent at the same relative offset; a 16-ft move is refused.
  2. Same grappling a Tiny creature → full 30 ft.
  3. Releasing the grapple restores full speed minus distance already moved (MOVE-Q-02).
- **Depends on / unblocks:** grapple (ATK), MOVE-M-03 (speed halving), MOVE-M-08
  (moving the grappled creature without its movement), a size ordinal (MOVE-D-01).
- **Tests pinning current behaviour:** none.
- **Arena impact:** a grapple tool and its observation (ATK); moves of a grappler would
  need to preview the dragged creature.
- **Known in:** `grappled.json` `_note` (grappler tracking pending).
- **Size:** M.

#### MOVE-M-10 — Make unsupported creatures fall and take falling damage
- **Status:** open
- **Type / severity:** MISSING — S4
- **SRD:** p.86 "Falling": "At the end of a fall, a creature takes 1d6 bludgeoning damage
  for every 10 feet it fell, to a maximum of 20d6. The creature lands prone, unless it
  avoids taking damage from the fall."
- **Current behaviour:** nothing ever lowers `y`; a creature at y > 0 without flight
  stays aloft and keeps walking there (**silent**). Today it can only get there via
  scenario placement or a direct `push_entity` call (no data path, MOVE-M-08), so it does
  not arise in ordinary play.
- **Evidence:** `.srd_work/probes/MOVE/p06_air_and_size.py`: `after push to y=60: y = 60.0
  hp = 50` / `walked 20 ft through the air at y = 60.0 hp = 50 ... [RAW: falls 60 ft,
  6d6 bludgeoning, lands prone]`. Searched for `fall`/`falling` in `src/`, `rules/`
  (only "fall back"/"falls back" prose).
- **Gap:** a creature left unsupported (no fly speed, or a flyer per MOVE-M-09's trigger)
  drops to the ground, takes 1d6 bludgeoning per full 10 ft (max 20d6) through the
  normal damage path, and is prone if it took damage.
- **Acceptance criteria:**
  1. Non-flyer pushed to y=60 → ends at y=0, takes 6d6 bludgeoning (seeded), is prone.
  2. A 9-ft fall → 0 dice, not prone.
  3. A 250-ft fall → 20d6.
- **Depends on / unblocks:** MOVE-M-08 (only data path that lifts a creature), MOVE-M-09
  (fly/hover), MOVE-M-04 (prone). Ground is y=0 (no terrain heights).
- **Tests pinning current behaviour:** `test_a_creature_placed_off_the_ground_moves_at_its_own_height`.
- **Arena impact:** none today.
- **Known in:** new.
- **Size:** S-M — a post-move/post-push support check emitting damage.

#### MOVE-M-11 — Charge extra for climbing and swimming without the matching speed
- **Status:** open
- **Type / severity:** MISSING — S4
- **SRD:** p.85 "Climbing, Swimming, and Crawling": "While climbing or swimming, each foot
  of movement costs 1 extra foot (2 extra feet in difficult terrain), unless a creature
  has a climbing or swimming speed."
- **Current behaviour:** no surfaces, water or walls exist in the battlefield model and no
  climb/swim speeds are loaded (see MOVE-M-09); every move is open-ground walking.
- **Evidence:** searches as in MOVE-M-02/MOVE-M-09 (`terrain`, `climb`, `swim`, `water`: no
  model, loader field or block).
- **Gap:** needs terrain (MOVE-M-02's battlefield model) before it can apply.
- **Acceptance criteria:** with a water zone authored, a 10-ft swim by a creature with no
  swim speed costs 20 ft; with swim 30 it costs 10.
- **Depends on / unblocks:** battlefield/terrain model (MOVE-M-02), per-mode speeds.
- **Tests pinning current behaviour:** none.
- **Arena impact:** none.
- **Known in:** new.
- **Size:** M (after terrain exists).

#### MOVE-M-12 — Support long and high jumps
- **Status:** open
- **Type / severity:** MISSING — S4
- **SRD:** p.85 "Jumping": "you cover a number of feet up to your Strength score if you
  move at least 10 feet on foot immediately before the jump. When you make a standing
  long jump, you can leap only half that distance." High jump: "3 + your Strength
  modifier".
- **Current behaviour:** no jump operation; with no obstacles or terrain and `y` locked,
  there is nothing for a jump to cross, so its absence changes no outcome today.
- **Evidence:** searched `jump` in `src/`, `rules/`, `examples/`, `web/routers/`: none.
- **Gap:** only meaningful once terrain/obstacles (MOVE-M-02) or difficult terrain zones
  exist (a jump clears difficult terrain at 1 ft per ft).
- **Acceptance criteria:** STR 15 creature with a 10-ft run-up long-jumps 15 ft across a
  difficult-terrain zone paying 15 ft (not 30); standing, max 7 ft.
- **Depends on / unblocks:** MOVE-M-02, ability checks (landing in difficult terrain:
  DC 10 DEX (Acrobatics)) — ATK/MON area.
- **Tests pinning current behaviour:** none.
- **Arena impact:** none.
- **Known in:** new.
- **Size:** M.

#### MOVE-M-13 — Allow a Gargantuan space larger than 20 ft
- **Status:** open
- **Type / severity:** MISSING (partial) — S4
- **SRD:** p.92 "Size Categories": "Gargantuan ... 20 by 20 ft. or larger".
- **Current behaviour:** `CreatureSize.size_ft` is a fixed table
  (`src/models/creature_size.py:5-12`); the docstring admits "truly larger creatures still
  use this value as a floor". No per-creature space override exists.
- **Evidence:** code read; loader reads only `size` (`stat_block_loader.py:156`).
- **Gap:** a creature's space should be authorable above 20 ft for Gargantuan (e.g. a
  `space_ft` field, validated ≥ 20 and only for Gargantuan).
- **Acceptance criteria:** a Gargantuan creature loaded with `space_ft: 30` has a 30-ft
  footprint in `bounding_box`, occupancy and reach; any other size with `space_ft` is
  rejected at load.
- **Depends on / unblocks:** none. Content: the largest SRD monsters (e.g. a kraken,
  tarrasque) — the SRD stat blocks don't state larger spaces, so this is mostly for
  homebrew/precision.
- **Tests pinning current behaviour:** `tests/test_entity_position.py::TestCreatureSize::
  test_gargantuan_footprint` (stays true for the default).
- **Arena impact:** none.
- **Known in:** `creature_size.py` docstring.
- **Size:** S.

#### MOVE-M-14 — Let a creature squeeze through a space one size smaller
- **Status:** open
- **Type / severity:** MISSING — S4
- **SRD:** p.92 "Squeezing into a Smaller Space": "A creature can squeeze through a space
  that is large enough for a creature one size smaller than it. ... must spend 1 extra
  foot for every foot it moves there, and it has disadvantage on attack rolls and
  Dexterity saving throws. Attack rolls against the creature have advantage".
- **Current behaviour:** there are no walls or passages, so no space is ever "smaller";
  the only constraint is creature occupancy, which a squeeze does not relax.
- **Evidence:** searched `squeez` across `src/`, `rules/`, `examples/`, `web/routers/`:
  none; no battlefield geometry model.
- **Gap:** needs static obstacles (terrain model) first.
- **Acceptance criteria:** with two walls 5 ft apart, a Large creature may pass, paying
  double while inside, and while there has attack/DEX-save disadvantage and is attacked
  with advantage; a Huge creature may not.
- **Depends on / unblocks:** battlefield obstacle model (MOVE-M-02), MOVE-D-01 path model.
- **Tests pinning current behaviour:** none.
- **Arena impact:** none.
- **Known in:** new.
- **Size:** M (after obstacles exist).

#### MOVE-M-16 — Support mounted combat
- **Status:** open
- **Type / severity:** MISSING — S4
- **SRD:** p.99 "Mounted Combat" — "Once during your move, you can mount a creature that
  is within 5 feet of you or dismount. Doing so costs an amount of movement equal to half
  your speed." Controlled mounts share initiative and may only Dash, Disengage, Dodge;
  forced-movement/prone falls (DC 10 DEX save); an OA provoked may target rider or mount.
- **Current behaviour:** no rider/mount relationship, no shared position, no mount tool.
- **Evidence:** searched `mount`/`dismount`/`rider` (only "amount" substrings) in `src/`,
  `rules/`, `web/routers/`, `src/arena/`: none.
- **Gap:** the whole subsystem.
- **Acceptance criteria:** a rider (speed 30) mounts an adjacent willing Large creature for
  15 ft of movement; thereafter moving the mount moves the rider; a forced move of the
  mount triggers the rider's DC 10 DEX save or dismount prone within 5 ft.
- **Depends on / unblocks:** MOVE-M-03, MOVE-M-08, MOVE-M-04, MOVE-M-01, Dash/Disengage/
  Dodge (TURN), initiative changes (TURN).
- **Tests pinning current behaviour:** none.
- **Arena impact:** new tools/observation; none today.
- **Known in:** new.
- **Size:** L.

#### MOVE-M-17 — Apply underwater combat rules
- **Status:** open
- **Type / severity:** MISSING — S4
- **SRD:** p.99 "Underwater Combat": melee weapon attack without a swimming speed "has
  disadvantage on the attack roll unless the weapon is a dagger, javelin, shortsword,
  spear, or trident"; "A ranged weapon attack automatically misses a target beyond the
  weapon's normal range"; "Creatures and objects that are fully immersed in water have
  resistance to fire damage."
- **Current behaviour:** no environment state (no water zones, no "immersed" flag), no
  weapon identity/properties on `AttackAction` (only `bonus_to_hit`, `damage`,
  `range_ft`), no swim speed.
- **Evidence:** searched `underwater`, `immersed`, `water` in `src/`, `rules/`: none;
  `AttackAction` fields in `src/models/action.py`.
- **Gap:** environment flag per creature/zone, swim speeds (MOVE-M-09), weapon kind/
  thrown/normal-range data (ATK), then three small rules on ATTACK_DECLARED /
  DAMAGE_INCOMING.
- **Acceptance criteria:** with an "underwater" battlefield: a longsword attack by a
  creature without swim speed rolls with disadvantage, a spear attack does not; a
  shortbow shot beyond normal range auto-misses; an immersed creature takes half fire
  damage.
- **Depends on / unblocks:** ATK (weapon typing, normal/long range), MOVE-M-09, an
  environment model.
- **Tests pinning current behaviour:** none.
- **Arena impact:** none.
- **Known in:** new.
- **Size:** M (rules are small once their inputs exist).

### ATK — Attacks, weapons, armor, damage and hit points (SRD pp.62–66, 94–98)

#### ATK-M-02 — Impose disadvantage on ranged attacks made within 5 ft of a hostile
- **Status:** open
- **Type / severity:** MISSING — S1
- **SRD:** p.95 "Ranged Attacks in Close Combat": "you have disadvantage on the attack roll if you are within 5 feet of a hostile creature who can see you and who isn't incapacitated." It covers "a ranged attack with a weapon, a spell, or some other means".
- **Current behaviour:** No rule anywhere grants this disadvantage. `attack_roll` takes advantage/disadvantage only from `ATTACK_DECLARED` handlers (`src/spells/blocks/rolls.py:62-65`), and the only handlers that set them are the condition rules. A bow or a ranged spell attack made point-blank therefore rolls a straight d20. This is **silent**, and it comes up in ordinary play: any archer or caster with an enemy next to it.
- **Evidence:** `.srd_work/probes/ATK/p02_ranged_rules.py` (seeded), through a real `CombatSystem` with `rules/global` installed:
  ```
  adjacent hostile (gap 0 ft): R1T1 [Archer] attacked Target with Shortbow. Attack: 18+4=22 vs AC 10. Hit! Damage: 3
  Fire Bolt at adjacent hostile: ATTACK_DECLARED disadvantage=False advantage=False
  ```
  The attack log prints `(disadvantage)` when the flag is set (`src/combat/attack_resolver.py:98-102`), and it does not here.
- **Gap:** RAW gives disadvantage to every ranged attack (weapon or spell) when any hostile creature within 5 ft of the attacker can see it and is not incapacitated.
- **Acceptance criteria:**
  1. An archer with an un-incapacitated hostile at edge gap 0 ft makes a ranged weapon attack → the attack rolls with disadvantage (two d20s, take the lower).
  2. The same with Fire Bolt (a ranged spell attack) → disadvantage.
  3. The hostile is 10 ft away, or is incapacitated/paralyzed/stunned/unconscious, or the adjacent creature is an ally → no disadvantage from this rule.
  4. A melee attack with a hostile adjacent → no disadvantage from this rule.
- **Depends on / unblocks:** needs ATK-M-01 (attack kind + distance on the event). "Who can see you" needs vision/blinded handling (COND). Until that lands, the rule could treat a blinded hostile as not imposing it, which is an approximation to record.
- **Tests pinning current behaviour:** none found.
- **Arena impact:** large, and it bears on the study design. The `kiting` scenario (`src/arena/scenarios.py`, Archer with a Longbow vs a melee Bruiser) and `protect_squishy` (Sharpshooter) let a ranged unit shoot point-blank at full odds, so today stepping away carries no RAW value. The heuristic's hit-chance estimates (`src/arena/heuristic/estimate.py:57`) would need the new disadvantage source, and the prompt text in `interfaces.py` may want a line about it.
- **Known in:** ENGINE_MAP lead ("no ranged-in-melee disadvantage"); new as a work item.
- **Size:** S once ATK-M-01 exists. A global rule on `ATTACK_DECLARED` needs a way to ask "is a hostile within 5 ft of the attacker", either a new expression helper or a small engine-side check emitting the flag.

#### ATK-M-01 — Type every attack as melee or ranged (and weapon vs spell)
- **Status:** open
- **Type / severity:** MISSING — S2
- **SRD:** p.94 "Attack Rolls": "The ability modifier used for a melee weapon attack is Strength, and the ability modifier used for a ranged weapon attack is Dexterity."; p.64 "Weapons": "Every weapon is classified as either melee or ranged."; p.95 "Melee Attacks" / "Ranged Attacks".
- **Current behaviour:** An attack is an `AttackAction` with one `range_ft` (`src/models/action.py:116`), and nothing records whether it is a melee or a ranged attack, or a weapon or a spell attack. `attack_roll` (`src/spells/blocks/rolls.py:41-102`) emits `ATTACK_DECLARED`/`ATTACK_ROLLED`/`ATTACK_HIT`, and their data classes (`src/combat/event_data.py:86-137`) carry attacker, defender, action, roll and flags, but no kind and no distance. Every rule that depends on the kind is therefore inexpressible. The condition files say so in their own `_note`s: `rules/entity_effects/conditions/prone.json:13`, `paralyzed.json:14`, `unconscious.json:14`. A ranged attack simply behaves like a melee attack with a longer reach. This is **silent**: the attack resolves with no modifier.
- **Evidence:** `grep -rni "melee\|ranged" src/spells src/combat src/models rules` finds only docstrings (`attack_resolver.py:44`, `action.py:105`) and the three `_note` TODOs. `.srd_work/probes/ATK/p03_loader_drops_weapon_fields.py`: a weapon authored with `"attack_kind": "ranged"` loads without error, and the key is dropped (`AttackAction fields: [... 'range_ft', 'recharge', ...]`, with no kind field). The expression sandbox (`src/rules/expressions.py:14-16`, which exposes only `max`, `min`, `abs`) has no distance helper, so a trigger cannot even approximate "within 5 ft".
- **Gap:** RAW keys a lot of rules on the attack's kind. They include ranged attacks in close combat, long range, prone (melee attacks against it have advantage, ranged attacks disadvantage), auto-crits within 5 ft on paralyzed/unconscious targets, opportunity attacks (melee only), knocking a creature out (melee only), thrown weapons and unarmed strikes.
- **Acceptance criteria:**
  1. Every `AttackAction` loaded from JSON has a kind (`melee`/`ranged`) and a source (`weapon`/`spell`). An unknown value is rejected at load, naming the valid set. A spell attack's kind comes from the spell (e.g. Fire Bolt → ranged spell attack).
  2. `ATTACK_DECLARED`, `ATTACK_ROLLED` and `ATTACK_HIT` carry the kind and the edge-to-edge attacker–defender distance in feet, and both are listed in `docs/current/BLOCK_REFERENCE.md` §Events.
  3. A trigger with `when: "event.attack_kind == 'melee'"` fires for a scimitar and not for a shortbow, in a real `CombatSystem.resolve_attack`.
- **Depends on / unblocks:** unblocks ATK-M-02, ATK-M-03, ATK-M-07 (unarmed strike), ATK-M-08 (grapple/shove are special melee attacks) and ATK-M-11 (knock-out), the prone/paralyzed/unconscious TODOs (COND), and opportunity attacks (TURN).
- **Tests pinning current behaviour:** none found. `tests/test_weapon_program.py` and `tests/test_attack_parity.py` build kind-less `AttackAction`s, so they will need the new field or a default.
- **Arena impact:** `src/arena/observation.py` and the menus (`action_space.py`) should show each attack's kind. The heuristic's `expected_attack_damage` callers (`src/arena/heuristic/`) will need the kind to fold in the new advantage/disadvantage sources.
- **Known in:** condition `_note`s (prone, paralyzed, unconscious); ENGINE_MAP leads.
- **Size:** M. A loader field plus a model field, the event fields, and the default kind for existing creature/spell JSON (all content needs one).

#### ATK-M-03 — Support a weapon's normal and long range
- **Status:** open
- **Type / severity:** MISSING (partial) — S2
- **SRD:** p.95 "Range": "The smaller number is the normal range, and the larger number is the long range. Your attack roll has disadvantage when your target is beyond normal range, and you can't attack a target beyond the long range." Also p.65 "Range" (weapon property), and p.65 "Improvised Weapons": "An improvised thrown weapon has a normal range of 20 feet and a long range of 60 feet."
- **Current behaviour:** `AttackAction.range_ft` is a single number (`src/models/action.py:116`, loaded at `src/loaders/stat_block_loader.py:314`). `check_attack_range` refuses anything beyond it, **loudly** (`src/spatial/range_check.py:80-86`). An author has two choices, and both are wrong. Using the normal range refuses legal long-range shots. Using the long range lets the creature shoot at long range with no disadvantage, which is **silent**. A long-range key is silently dropped by the loader.
- **Evidence:** `.srd_work/probes/ATK/p02_ranged_rules.py`: `gap 100 ft (beyond normal, within SRD long 320): REFUSED: Archer cannot use Shortbow: Target is out of range (100.0 ft, max 80 ft)`. `.srd_work/probes/ATK/p03_loader_drops_weapon_fields.py`: `"long_range_ft": 600` loads without error, and no such field exists on the model.
- **Gap:** RAW allows a two-range attack between normal and long range, with disadvantage, and refuses it beyond long range. Single-range attacks (most spells) keep today's behaviour.
- **Acceptance criteria:**
  1. A shortbow authored as 80/320 against a target at a 100 ft gap → the attack resolves with disadvantage.
  2. The same at a 330 ft gap → refused with `OUT_OF_RANGE`, naming 320 as the maximum.
  3. At a 60 ft gap → a straight roll.
  4. A weapon authored with only one range → unchanged behaviour (it is both normal and long range).
- **Depends on / unblocks:** best done with ATK-M-01 (range applies to ranged attacks; a thrown melee weapon has both a reach and a range). Unblocks thrown weapons (ATK-M-06).
- **Tests pinning current behaviour:** range-refusal tests in `tests/test_combat.py` still hold for single-range weapons. None pins the absence of long range.
- **Arena impact:** `action_space.py` (`_in_reach`, `_max_attack_range_ft`) and the heuristic's threat model use `range_ft` as the single maximum. Targets in the long band would become legal and should be marked "at disadvantage" in menus/observation. `kiting` would gain a long-range band.
- **Known in:** ENGINE_MAP lead ("no long range"); new as a work item.
- **Size:** S. Add a loader field and a model field (`long_range_ft`, optional), have the range check use it, and set a disadvantage flag on `ATTACK_DECLARED` when the gap exceeds the normal range.

#### ATK-M-04 — Model cover (half, three-quarters, total)
- **Status:** open
- **Type / severity:** MISSING — S2
- **SRD:** p.96 "Cover": "A target with half cover has a +2 bonus to AC and Dexterity saving throws." "…three-quarters cover has a +5 bonus to AC and Dexterity saving throws." "A target with total cover can't be targeted directly by an attack or a spell". "…only the most protective degree of cover applies". p.94 "Making an Attack" step 2: "The GM determines whether the target has cover".
- **Current behaviour:** There is no cover concept. AC is `stat_block.armor_class` plus `stat_modifiers` with `stat == "ac"` (`src/models/entity.py:388-391`). `attack_roll` compares the total against `defender.ac` (`src/spells/blocks/rolls.py:90`). Saves add only `saving_throw.<ability>` modifiers (`src/utils/saving_throw.py`). There are no obstacles, terrain or line-of-sight in the spatial model. The only things on the battlefield are creature bounding boxes (`src/spatial/`). This is **silent**: a target behind another creature takes no AC or DEX-save bonus.
- **Evidence:** `grep -rni "obstacle\|terrain\|\bwall\b\|\bcover\b\|line.of.sight" src rules` → no hits except `frightened.json`'s `_note` ("pending line-of-sight tracking"). Nothing in `src/spatial/aoe.py` or `range_check.py` tests an attack line against intervening boxes. The `ATTACK_DECLARED`/`SAVING_THROW_DECLARED` data (`src/combat/event_data.py:86-101,179-192`) has no AC-bonus or save-bonus field a cover rule could write, only advantage/disadvantage flags.
- **Gap:** RAW adds +2/+5 to the target's AC and DEX saves for half/three-quarters cover, takes only the best degree, and forbids direct targeting under total cover (an area effect can still reach the target). Creatures provide cover ("…or a creature, whether that creature is an enemy or a friend"), so the rule applies even on today's obstacle-free battlefield.
- **Acceptance criteria:**
  1. An effect (or the referee) marks a defender as having half cover against one attacker, and a d20 total of exactly AC+1 misses; with no cover the same roll hits.
  2. A creature with three-quarters cover from a Fireball's point of origin makes its DEX save at +5.
  3. Half cover from one source plus three-quarters from another → +5, not +7.
  4. A target with total cover from the attacker → the attack or single-target spell is refused with a specific error code; an AoE that reaches it still applies.
- **Depends on / unblocks:** how cover is *determined* is ATK-Q-02. Needs an AC/save-bonus channel on the roll events (today's events only carry advantage flags). It ties to the SPELL area's "clear path to the target".
- **Tests pinning current behaviour:** none found.
- **Arena impact:** observation and menus would show cover per target. The heuristic's hit/save estimates need the bonus. In `protect_squishy` the Tank screens the Sharpshooter, and the Sharpshooter's shots pass the Tank, which RAW is half cover.
- **Known in:** new. CODEBASE_REVIEW does not list it; ENGINE_MAP lead ("no cover").
- **Size:** L. Add cover-degree data on attack and save resolution, an AC-bonus/save-bonus path on the events, and a geometry query (attacker→target line vs intervening creature boxes) if ATK-Q-02 is answered "derive it".

#### ATK-M-10 — Add dying: death saving throws, stabilizing, instant death
- **Status:** open
- **Type / severity:** MISSING — S2
- **SRD:** p.98 "Instant Death": "When damage reduces you to 0 hit points and there is damage remaining, you die if the remaining damage equals or exceeds your hit point maximum." p.98 "Death Saving Throws": "Whenever you start your turn with 0 hit points, you must make a special saving throw… If the roll is 10 or higher, you succeed… On your third success, you become stable… On your third failure, you die." "Rolling 1 or 20… a 1… counts as two failures. If you roll a 20 on the d20, you regain 1 hit point." "Damage at 0 Hit Points. If you take any damage while you have 0 hit points, you suffer a death saving throw failure. If the damage is from a critical hit, you suffer two failures instead. If the damage equals or exceeds your hit point maximum, you suffer instant death." p.98 "Stabilizing a Creature": "DC 10 Wisdom (Medicine) check… A stable creature doesn't make death saving throws… It… must start making death saving throws again, if it takes any damage."
- **Current behaviour:** None of this exists. `Entity` has no death-save, stable or dead state (`src/models/entity.py:18-61`). Overkill damage is discarded by the `max(0, …)` in `take_damage` (`entity.py:110`). It is reported in `DamageProcessor`'s total (`damage_processor.py:41-44`), but no rule compares it with the HP maximum. Damage to a 0-HP creature just re-floors at 0, and a second attack on it is accepted with no effect. No first-aid action exists.
- **Evidence:** `.srd_work/probes/ATK/p04_zero_hp.py`:
  ```
  18 dmg to 6/12 HP victim: … hp=0 alive=False … deaths=['Victim']   (SRD: 12 remaining ≥ max 12 → instant death)
  attack on 0-HP victim accepted: (True, 3, {...}) deaths now ['Victim']
  has death-save state on Entity? []
  ```
  `grep -rni "death_save\|stable\|stabiliz\|instant death\|massive" src rules` → no hits.
- **Gap:** for creatures that use the PC rules (ATK-Q-01), RAW needs a dying state with death saves at turn start, nat 1 / nat 20 handling, failures from damage (two on a crit), instant death from massive damage (both on the drop to 0 and while at 0), stabilization (an action plus a DC 10 Medicine check), and resets on regaining HP or becoming stable.
- **Acceptance criteria:**
  1. A PC-rules creature with max 12 / current 6 takes 18 damage → dead (instant death). Taking 17 → dying, 0 HP, unconscious.
  2. A dying creature starts its turn and rolls (patched) 10 → one success. With three successes it is stable and makes no further saves. A 1 → two failures. A 20 → 1 HP, conscious, and the counters reset.
  3. A dying creature takes 3 damage → one failure. Damage from a critical hit → two. Damage ≥ its HP max → dead.
  4. Healing a dying creature → it has the healed HP, is no longer unconscious from 0 HP, and its counters are at zero.
- **Depends on / unblocks:** ATK-Q-01, ATK-D-01. Death saves at turn start need the turn to *happen* for an unconscious creature: today `_SKIP_CONDITIONS` skips it entirely, with no `TURN_START` (TURN area). Stabilizing needs an ability-check system (COND) and an action (TURN). The crit flag must reach `DAMAGE_INCOMING`/`DAMAGE_DEALT` data (it is on `ATTACK_HIT` only).
- **Tests pinning current behaviour:** none assert the absence. 0-HP-is-dead tests are listed under ATK-D-01.
- **Arena impact:** large if arena creatures use PC rules. Matches would not end at 0 HP, observation needs death-save state, and the heuristic needs a "finish the downed" target value. If ATK-Q-01 rules that arena creatures die at 0, the arena is unaffected.
- **Known in:** CODEBASE_REVIEW §4 item 5; ENGINE_MAP lead.
- **Size:** L. Dying state on `Entity`, a death-save rule on turn start, massive-damage checks in `DamageProcessor`, a first-aid action, and event-data additions.

#### ATK-M-05 — Derive weapon attack bonus and damage modifier from ability and proficiency
- **Status:** open
- **Type / severity:** MISSING (partial) — S3
- **SRD:** p.94 "Modifiers to the Roll": "the two most common modifiers to the roll are an ability modifier and the character's proficiency bonus. When a monster makes an attack roll, it uses whatever modifier is provided in its stat block." p.96 "Damage Rolls": "When attacking with a weapon, you add your ability modifier—the same modifier used for the attack roll—to the damage." p.64 "Weapon Proficiency": "If you make an attack roll using a weapon with which you lack proficiency, you do not add your proficiency bonus". p.77 "Proficiency Bonus": "Your proficiency bonus can't be added to a single die roll or other number more than once."
- **Current behaviour:** A weapon's to-hit is the literal `bonus_to_hit` int (`src/loaders/stat_block_loader.py:310`, `src/combat/attack_resolver.py:29`). Its damage is a literal formula string with any modifier baked in (`attack_resolver.py:35`). Neither reads `ability_scores` or `proficiency_bonus`, and there is no proficiency flag on a weapon. Spell attacks *are* derived (`Entity.spell_attack_bonus`, `src/models/entity.py:405-413`, `prof + spellcasting mod`). For monsters, hand-authored numbers are RAW. For characters they are not: a change to STR/DEX, or a weapon swap, never moves the numbers. This is **silent**.
- **Evidence:** Shipped content shows the drift that hand-authoring invites:
  - `examples/creatures/goblin.json`: Scimitar `"formula": "1d6"` and Shortbow `"1d6"`. SRD p.315 Goblin: "Hit: 5 (1d6 + 2) slashing damage" / "5 (1d6 + 2) piercing damage".
  - `examples/creatures/characters/ranger.json`: DEX 16 Shortsword `SLASHING 1d6`, Shortbow `1d6`, both missing the +3 DEX that RAW adds to damage (and the SRD shortsword is piercing, p.66).

  `grep -rn "proficien" src/models/action.py src/loaders/stat_block_loader.py` finds nothing for weapons. `StatBlock.get_skill_bonus` exists, but nothing derives attack bonuses.
- **Gap:** for characters (and for monsters whose stat block derives its numbers), the to-hit should be the ability mod (STR melee, DEX ranged, either for finesse) plus proficiency if proficient, and damage should add the same ability mod. Monster stat-block literals remain legal.
- **Acceptance criteria:**
  1. A weapon authored as `{"ability": "strength", "proficient": true, "damage": "1d8"}` on a STR 18 / prof +3 creature resolves at +7 to hit and `1d8+4` damage (crit: `2d8+4`).
  2. The same weapon with `"proficient": false` → +4 to hit, `1d8+4`.
  3. A temporary STR change (a stat modifier) changes both numbers on the next attack.
  4. A weapon authored with a literal `bonus_to_hit` and full formula → unchanged (the monster path).
- **Depends on / unblocks:** ATK-M-01 (melee → STR, ranged → DEX defaults) and ATK-M-06 (finesse, thrown). Unblocks two-weapon fighting's "don't add the ability modifier" (ATK-M-09).
- **Tests pinning current behaviour:** none pin the absence. `tests/test_weapon_program.py` asserts `_default_program` copies `bonus_to_hit` literally, which stays valid for the literal path.
- **Arena impact:** none required. Arena scenarios (`src/arena/scenarios.py:_attack`) author literal bonuses, which is a fine monster-style choice. The heuristic reads `bonus_to_hit` directly and would need to read the derived value.
- **Known in:** CODEBASE_REVIEW §4 item 8 ("Damage `bonus_to_hit`/`amount` are hand-authored"). The goblin and ranger content errors are new.
- **Size:** M. Optional loader fields, then derive at resolve time in `_default_program` (or as an `attack_bonus` expression the `attack_roll` block resolves).

#### ATK-M-06 — Model weapon properties, and reject the weapon fields the loader drops
- **Status:** open
- **Type / severity:** MISSING — S3
- **SRD:** p.64-65 "Weapon Properties": Ammunition, Finesse ("use your choice of your Strength or Dexterity modifier… same modifier for both rolls"), Heavy ("Small creatures have disadvantage on attack rolls with heavy weapons"), Light, Loading ("you can fire only one piece of ammunition from it when you use an action, bonus action, or reaction"), Range, Reach ("adds 5 feet to your reach"), Special, Thrown, Two-Handed, Versatile. p.65 "Improvised Weapons" ("deals 1d4 damage"; a ranged weapon used in melee is improvised).
- **Current behaviour:** `AttackAction` has no property list (`src/models/action.py:103-116`). Reach is expressible only by authoring a larger `range_ft`. Versatile is expressible only as two separate actions. Finesse, heavy, loading, thrown, two-handed, ammunition and improvised use have no representation. The loader **silently drops** unknown action keys, so a creature authored with `"properties": [...]`, `"reach_ft"`, `"ability"` or `"proficient"` loads cleanly and behaves as if they were absent. That goes against CLAUDE.md §2.5 ("Fail loudly… Validate at boundaries").
- **Evidence:** `.srd_work/probes/ATK/p03_loader_drops_weapon_fields.py`:
  ```
  loaded OK, no error. AttackAction fields: ['action_type', 'bonus_to_hit', 'cost', 'damage', 'damage_half_on_save', 'description', 'legendary_action_cost', 'name', 'program', 'range_ft', 'recharge', 'source_effect']
  ```
  The input had `long_range_ft`, `attack_kind`, `properties`, `ability`, `proficient` and `reach_ft`. `src/loaders/stat_block_loader.py:275-316` reads only `type`, `name`, `description`, `recharge`, `cost`, `legendary_action_cost`, `damage`, `program`, `bonus_to_hit` and `range_ft` for an attack. Separately, `AttackAction.damage_half_on_save` (`action.py:115`) is never populated by the loader, only serialised (`stat_block_loader.py:468`), and never read by any resolver: a dead field.
- **Gap:** RAW properties change to-hit (finesse, heavy for Small wielders), reach, the range bands (thrown, ammunition), how many attacks one action allows (loading), and damage dice (versatile).
- **Acceptance criteria:**
  1. Loading a creature whose attack has an unknown key fails, naming the key and the valid keys (the same standard `validate_program` applies to blocks).
  2. A `finesse` weapon on a STR 10 / DEX 16 creature uses +3 for both to-hit and damage (with ATK-M-05).
  3. A Small creature attacking with a `heavy` weapon rolls with disadvantage.
  4. A `reach` melee weapon on a Medium creature can hit a target at an edge gap of 10 ft and not at 15 ft.
- **Depends on / unblocks:** ATK-M-01, ATK-M-03 (thrown/ammunition ranges), ATK-M-05 (finesse). Loading/ammunition need the multiattack/Attack action (TURN area).
- **Tests pinning current behaviour:** none found. No test in `tests/test_loader_validation.py` loads an attack with extra keys and expects success, but recheck it when strict keys land.
- **Arena impact:** observation could show properties. Reach changes `action_space._in_reach` only through `range_ft`, so it is consistent if reach is folded into `range_ft` at load.
- **Known in:** new. The dead `damage_half_on_save` field is new too.
- **Size:** M. A closed property enum on the loader, strict-key validation for actions (a loud behaviour change), and per-property effects. Finesse/heavy/reach are small; loading/ammunition are larger.

#### ATK-M-07 — Give every creature an unarmed strike
- **Status:** open
- **Type / severity:** MISSING — S3
- **SRD:** p.95 "Melee Attacks": "you can use an unarmed strike… On a hit, an unarmed strike deals bludgeoning damage equal to 1 + your Strength modifier. You are proficient with your unarmed strikes."
- **Current behaviour:** A creature can attack only with the `AttackAction`s on its stat block or granted to it (`src/arena/tools.py:432-436`, `CombatSystem.get_affordable_actions` at `src/combat/combat_system.py:652-654`). There is no built-in unarmed strike. The sample wizard (`examples/creatures/characters/wizard.json`) has no attack actions at all, so when no spell is usable it cannot attack.
- **Evidence:** `grep -rni "unarmed" src rules examples` → no hits.
- **Gap:** RAW lets any creature make a melee unarmed strike: proficient, to-hit STR mod + prof, damage `1 + STR mod` bludgeoning (never negative, p.96 "Damage Rolls").
- **Acceptance criteria:**
  1. A creature with no authored attacks can `resolve_attack` with an "Unarmed Strike" against an adjacent target: to-hit = STR mod + proficiency, damage = 1 + STR mod, bludgeoning.
  2. STR 8 → damage 0 on a hit, and not negative.
  3. On a crit the damage is unchanged (there are no dice to double).
  4. An unarmed strike counts as a melee weapon attack for every rule keyed on that (ATK-M-01).
- **Depends on / unblocks:** ATK-M-01, ATK-M-05.
- **Tests pinning current behaviour:** none found.
- **Arena impact:** menus and observation would list an extra attack for every creature, so scenario decision sets change. Possibly opt-in per scenario, to keep the study's action spaces stable.
- **Known in:** new.
- **Size:** S. Synthesise an implicit `AttackAction` per entity (not on the immutable `StatBlock`).

#### ATK-M-08 — Add grapple and shove (special melee attacks resolved by contests)
- **Status:** open
- **Type / severity:** MISSING — S3
- **SRD:** p.95 "Grappling": "a Strength (Athletics) check contested by the target's Strength (Athletics) or Dexterity (Acrobatics) check (the target chooses the ability to use)." "The target of your grapple must be no more than one size larger than you". "Escaping a Grapple. A grappled creature can use its action to escape". p.96 "Moving a Grappled Creature": "your speed is halved, unless the creature is two or more sizes smaller than you." p.96 "Shoving a Creature": "If you win the contest, you either knock the target prone or push it 5 feet away from you."
- **Current behaviour:** There is no grapple or shove action and no ability-check/contest roll (`StatBlock.get_skill_bonus`, `src/models/stat_block.py:77`, has no caller in `src/`). `rules/entity_effects/conditions/grappled.json` is "Marker-only: no implementable combat effects" (its `_note`). The arena tools are only `attack`, `cast_spell`, `move` and `end_turn`.
- **Evidence:** `grep -rni "grappl\|shove\|contest\|ability_check\|athletics" src rules examples` → only the `GRAPPLED` enum, the marker rule and a heuristic weight (`src/arena/heuristic/features.py:54`).
- **Gap:** RAW: either can replace one attack of the Attack action, needs the target within reach and at most one size larger, and is resolved by a contested check. Grapple applies grappled (speed 0), and escape costs an action. Shove gives prone, or a 5-ft push away from the attacker.
- **Acceptance criteria:**
  1. A grapple against an adjacent target one size larger: attacker Athletics vs target's Athletics or Acrobatics (the target chooses; the referee needs a deterministic choice policy, e.g. the higher modifier), and on a win the target gains grappled with the grappler recorded.
  2. A grapple against a target two sizes larger → refused, naming the size rule.
  3. A shove win with "push" moves the target 5 ft directly away, through the forced-movement path, without provoking. A shove win with "prone" applies prone.
  4. A grappled creature's escape action runs the contest the other way, and success removes the condition.
- **Depends on / unblocks:** an ability-check and contest roll (COND area), ATK-M-01 (special melee attack), the Attack action / multiattack (TURN), forced movement `push_entity` (MOVE), and grappled speed 0 (COND/MOVE).
- **Tests pinning current behaviour:** none found.
- **Arena impact:** a new tool or attack mode, menu entries, observation of grappled-by, and prompt text.
- **Known in:** `grappled.json` `_note`; ENGINE_MAP lead.
- **Size:** L. Contest roll, two special attacks, grapple bookkeeping (grappler reference, end-on-incapacitate/out-of-reach), and drag-speed halving.

#### ATK-M-09 — Support two-weapon fighting
- **Status:** open
- **Type / severity:** MISSING — S3
- **SRD:** p.95 "Two-Weapon Fighting": "When you take the Attack action and attack with a light melee weapon that you're holding in one hand, you can use a bonus action to attack with a different light melee weapon… You don't add your ability modifier to the damage of the bonus attack, unless that modifier is negative."
- **Current behaviour:** An attack can be authored with `"cost": {"bonus_actions": 1}` (`StatBlockLoader._parse_cost`), so a bonus-action attack is expressible. Nothing ties it to having taken the Attack action with a light weapon that turn, nothing knows "light" (ATK-M-06), and the damage modifier is baked into the formula (ATK-M-05). An author can therefore give a creature an always-available bonus-action attack, which is more than RAW allows, with no error (**silent**).
- **Evidence:** `grep -rni "two.weapon\|off.hand" src rules examples` → no hits. No per-turn "took the Attack action" record exists on `Entity` or `ActionResources` (`src/models/action_resources.py`).
- **Gap:** RAW gates the bonus attack on (1) the Attack action taken this turn, (2) a light melee weapon in each hand, and (3) the off-hand attack having no positive ability modifier to damage.
- **Acceptance criteria:**
  1. After an Attack action with a light weapon, a bonus-action off-hand attack with a different light weapon is allowed, and its damage omits a positive ability mod (with ATK-M-05).
  2. Without a prior Attack action that turn → refused with a specific code.
  3. With a non-light weapon in either hand → refused.
  4. A negative ability mod is still applied to the off-hand damage.
- **Depends on / unblocks:** ATK-M-05, ATK-M-06 (light), and the Attack action as a turn-state fact (TURN area).
- **Tests pinning current behaviour:** none found.
- **Arena impact:** a menu entry for the bonus attack after an attack, and the heuristic's whole-turn plans.
- **Known in:** new.
- **Size:** M.

#### ATK-M-12 — Derive AC from armor and shield (characters)
- **Status:** open
- **Type / severity:** MISSING (partial) — S3
- **SRD:** p.62 "Armor Class (AC)": "The armor (and shield) you wear determines your base Armor Class." p.63 "Light Armor": "add your Dexterity modifier"; "Medium Armor": "Dexterity modifier, to a maximum of +2"; "Heavy Armor": "doesn't let you add your Dexterity modifier". "Shields… increases your Armor Class by 2. You can benefit from only one shield at a time." p.63 "Heavy Armor": "reduces the wearer's speed by 10 feet unless the wearer has a Strength score equal to or higher than the listed score." p.62 "Armor Proficiency": without it, "disadvantage on any ability check, saving throw, or attack roll that involves Strength or Dexterity, and you can't cast spells". p.94: "the AC of a monster is in its stat block."
- **Current behaviour:** AC is the literal `armor_class` int (`src/loaders/stat_block_loader.py:169`) plus `stat_modifiers` with stat `"ac"` (`src/models/entity.py:387-391`, used by Shield of Faith). No armor or shield model exists, and the loader silently ignores `armor`/`shield` keys. A DEX change never moves AC. The Strength-requirement speed penalty and the non-proficiency penalties do not exist. For monsters, the literal AC is RAW.
- **Evidence:** `.srd_work/probes/ATK/p03_loader_drops_weapon_fields.py`: `armor_class: 12 (no armor/shield derivation; 'armor'/'shield' keys ignored)`. `grep -rni "armor\b\|shield\b" src/models src/loaders` → only `armor_class`.
- **Gap:** a character's AC should follow armor type + DEX (capped) + shield + modifiers. Heavy armor should apply a −10 ft speed below its STR score, and armor without proficiency should apply its penalties. The stealth disadvantage belongs to COND checks.
- **Acceptance criteria:**
  1. A character with `"armor": "chain_shirt"` and DEX 16 → AC 15 (13 + 2, capped); with a shield → 17.
  2. `"armor": "plate"`, STR 13 → speed 20 (30 − 10); STR 15 → 30. AC 18 regardless of DEX (including negative DEX).
  3. No armor → 10 + DEX modifier. The SRD core text doesn't state this base outright: it is implied by e.g. Unarmored Defense (p.8) and "a duplicate's AC equals 10 + your Dexterity modifier", so record the ruling. A literal `armor_class` with no `armor` key → unchanged (the monster path).
  4. An unknown armor name → loader error naming the valid set.
- **Depends on / unblocks:** speed variants (MOVE area) for the STR penalty; ability checks (COND) for the stealth and proficiency penalties.
- **Tests pinning current behaviour:** none.
- **Arena impact:** none required (scenarios author literal AC).
- **Known in:** new.
- **Size:** M. An armor table (data), loader fields, and a derived `Entity.ac` base.

#### ATK-M-13 — Mark damage as magical/silvered so "nonmagical" resistances can be expressed
- **Status:** open
- **Type / severity:** MISSING — S3
- **SRD:** p.65 "Silvered Weapons": "Some monsters that have immunity or resistance to nonmagical weapons are susceptible to silver weapons". p.97 example: "resistance to all nonmagical damage". (SRD monster stat blocks list e.g. "bludgeoning, piercing, and slashing from nonmagical attacks that aren't adamantine".)
- **Current behaviour:** `Damage` is `(damage_type, amount, formula)` (`src/models/damage.py:26-44`), and stat-block resistances are a list of bare `DamageType`s (`src/models/stat_block.py:59-61`). Neither the damage nor the attack records magical, silvered or adamantine, so a resistance that depends on the source cannot be authored. Authors must either grant full B/P/S resistance or immunity (wrong against magic or silvered weapons) or none (wrong against mundane ones).
- **Evidence:** `grep -rni "magical\|silver\|adamant" src rules examples --include=*.py --include=*.json` → no hits. `examples/creatures/stone_golem.json` lists only `["POISON", "PSYCHIC"]` immunities. SRD p.317 Stone Golem also has immunity to "bludgeoning, piercing, and slashing from nonmagical attacks that aren't adamantine", which cannot be expressed.
- **Gap:** damage needs source qualifiers, and resistances/immunities need qualifier conditions.
- **Acceptance criteria:**
  1. A creature resistant to "slashing from nonmagical attacks" takes half from a mundane longsword and full from a weapon flagged magical.
  2. Immunity to "nonmagical B/P/S that aren't silvered" is bypassed by a silvered weapon.
  3. An unknown qualifier in creature JSON → loader error.
- **Depends on / unblocks:** ATK-D-03 (the modifier-resolution stage); `COMPOSITE_DAMAGE_DESIGN.md`.
- **Tests pinning current behaviour:** none.
- **Arena impact:** none today.
- **Known in:** new.
- **Size:** M.

#### ATK-M-11 — Let a melee attacker knock a creature out instead of killing it
- **Status:** open
- **Type / severity:** MISSING — S4
- **SRD:** p.98 "Knocking a Creature Out": "When an attacker reduces a creature to 0 hit points with a melee attack, the attacker can knock the creature out… The creature falls unconscious and is stable."
- **Current behaviour:** no attacker choice at 0 HP. Every drop to 0 is the same state (ATK-D-01).
- **Evidence:** `grep -rni "knock\|nonlethal\|non_lethal" src rules` → no hits.
- **Gap:** RAW gives the attacker an option, at the moment a melee attack takes the target to 0, to leave it unconscious and stable rather than dead or dying.
- **Acceptance criteria:**
  1. A melee attack declared non-lethal that reduces a dies-at-zero creature to 0 → the target is unconscious and stable, not dead, and `ENTITY_DIES` is not emitted.
  2. The same option on a ranged attack or spell → refused or ignored, as the ruling picks.
- **Depends on / unblocks:** ATK-M-01 (melee), ATK-Q-01, ATK-M-10 (stable state).
- **Tests pinning current behaviour:** none.
- **Arena impact:** none in combat-only matches (a knocked-out foe is out either way), unless scenarios reward capture.
- **Known in:** new.
- **Size:** S once the dying/stable state exists. It is a flag on the attack call.

### SPELL — Spellcasting (SRD pp.100–104)

#### SPELL-M-04 — Give casters a level, and scale cantrips (damage and beam count) with it
- **Status:** open
- **Type / severity:** MISSING — S2
- **SRD:** p.101 "Cantrips" (no scaling text there); each damaging cantrip says, e.g. Fire Bolt: "This spell's damage increases by 1d10 when you reach 5th level (2d10), 11th level (3d10), and 17th level (4d10)." Eldritch Blast: "The spell creates more than one beam when you reach higher levels".
- **Current behaviour:** there is no character/caster level anywhere: `StatBlock` carries proficiency, abilities and slots but no level or CR (`src/models/stat_block.py`; `grep -rni "character_level\|caster_level\|challenge_rating" src/` → nothing), and the loader reads none. The only scaling input a `damage` block has is `slot_level` (`src/spells/scaling.py`, `blocks/damage.py`), which is 0 for a cantrip. So every cantrip deals its 1st-level damage at every level. **Silent.** Example: the shipped `examples/creatures/characters/wizard.json` has 3rd-level slots (a 5th-level wizard) but casts 1d10 Fire Bolt, not 2d10.
- **Evidence:** the greps above; `examples/spells/firebolt.json` program `[{"block":"attack_roll"…},{"block":"damage","formula":"1d10"…}]` with no scaling input; `scaling` subfields are only `per_slot_above`/`add_dice` (`blocks/damage.py` contract).
- **Gap:** cantrip damage dice (and Eldritch Blast's beam count) step up at caster levels 5, 11, 17 (for a monster, its spellcaster level).
- **Acceptance criteria:**
  1. A caster of level 5 casting Fire Bolt rolls 2d10 (patch `roll_formula` and assert the formula); level 4 rolls 1d10; level 17 rolls 4d10.
  2. Eldritch Blast for a level-5 caster accepts 2 beams and refuses 3 (with SPELL-D-13).
  3. The level loads from creature JSON; a missing level fails loudly or defaults explicitly (documented).
- **Depends on / unblocks:** SPELL-D-13 (beam count); the deferred upcasting design (count scaling); MON (monster spellcaster level).
- **Tests pinning current behaviour:** tests asserting cantrip damage ranges at 1d10 etc. (grep `Fire Bolt` in `tests/`).
- **Arena impact:** observation/menu could show the scaled dice; heuristic expected-damage numbers change.
- **Known in:** CODEBASE_REVIEW §4 item 7 ("cantrip auto-scaling by level").
- **Size:** M — a caster-level field on `StatBlock` (+ loader), a `caster_level` scaling input for `damage` (and a count input for iterators).

#### SPELL-M-06 — Type spell attacks as melee or ranged, and apply the ranged-in-melee disadvantage
- **Status:** open
- **Type / severity:** MISSING — S2
- **SRD:** p.103 "Attack Rolls": "Most spells that require attack rolls involve ranged attacks. Remember that you have disadvantage on a ranged attack roll if you are within 5 feet of a hostile creature that can see you and that isn't incapacitated."
- **Current behaviour:** the `attack_roll` block has one arg, `attack_bonus` (`src/spells/blocks/rolls.py:103-115`); nothing marks a spell attack melee (Inflict Wounds, Vampiric Touch, Chill Touch is ranged) or ranged, and `ATTACK_DECLARED` carries no such field (`src/combat/event_data.py:86-101`). No rule grants disadvantage for a ranged attack with a hostile within 5 ft. So Fire Bolt fired at an adjacent goblin rolls normally. **Silent.**
- **Evidence:** `.srd_work/probes/SPELL/p16_ranged_spell_attack_in_melee.py` (goblin adjacent):
  ```
  ATTACK_DECLARED fields: ['action', 'advantage', 'attacker', 'critical_hit', 'critical_miss', 'defender', 'disadvantage']
  advantage: False | disadvantage: False
  ```
- **Gap:** each spell attack is melee or ranged; a ranged spell attack within 5 ft of a hostile, non-incapacitated creature that can see the caster has disadvantage; melee/ranged also matters for prone (adv within 5 ft / dis beyond), paralyzed/unconscious auto-crits (melee within 5 ft), and cover.
- **Acceptance criteria:**
  1. Fire Bolt (`ranged`) at a target with a hostile creature adjacent to the caster → `ATTACK_DECLARED.disadvantage` is True.
  2. Same with the adjacent hostile incapacitated → no disadvantage.
  3. Inflict Wounds (`melee`) against a prone target within 5 ft → advantage.
  4. Validation rejects an `attack_roll` on a spell without an attack kind (or defaults it explicitly per the shipped spell's text).
- **Depends on / unblocks:** ATK's melee/ranged typing for weapon attacks (shared event field and rule); COND prone/paralyzed rules.
- **Tests pinning current behaviour:** none found.
- **Arena impact:** the heuristic's expected-hit estimates and any prompt text about attacks; positioning of casters matters more.
- **Known in:** ENGINE_MAP lead (ATK "no melee/ranged distinction").
- **Size:** S/M — an `attack_kind` field on `attack_roll` (+ `ATTACK_DECLARED`), and one global rule for ranged-in-melee.

#### SPELL-M-01 — Require a clear path to a spell's target, and block area lines with total cover
- **Status:** open
- **Type / severity:** MISSING — S3
- **SRD:** p.102 "A Clear Path to the Target": "To target something, you must have a clear path to it, so it can't be behind total cover." p.103 "Areas of Effect": "If no unblocked straight line extends from the point of origin to a location within the area of effect, that location isn't included in the spell's area. To block one of these imaginary lines, an obstruction must provide total cover."
- **Current behaviour:** the engine has no obstruction model at all — no walls, terrain objects, or cover values — so a spell target is never behind total cover and an area is never blocked. Neither `check_single_target_range` (`src/spatial/range_check.py:92-118`) nor `get_targets_in_aoe` (`src/combat/combat_system.py:844-871`) consults anything but distance/shape. Creatures provide only half cover RAW, so they correctly never block a spell; the gap only bites once the board has obstacles.
- **Evidence:** `grep -rni "cover\b|total_cover|obstacle|line_of_sight|line of sight|terrain"` over `src/ rules/ examples/ web/routers/` finds no cover/obstacle model — only prose (Sacred Flame's description, a `frightened.json` `_note` saying line of sight is pending). `StatBlock`/`Entity` have no cover field; the loader reads no map/terrain data; no block or event carries cover.
- **Gap:** once obstructions exist, (a) a creature or point behind total cover cannot be targeted; (b) a location in an area with no unblocked line from the origin is excluded; (c) an area aimed at an unseen point behind an obstruction originates on the near side of it.
- **Acceptance criteria:** (after an obstruction model exists)
  1. A wall between caster and target: Fire Bolt at the target is refused (`INVALID_TARGET_RELATION` or a new `NO_CLEAR_PATH` code).
  2. Fireball centred so a creature is inside the radius but behind a wall from the origin: that creature is not affected; one on the open side is.
  3. Sacred Flame's "no benefit from cover" stays expressible (half / three-quarters cover ignored for its save).
- **Depends on / unblocks:** needs an obstruction/terrain model (shared with ATK cover and line-of-sight). Unblocks "a creature you can see" target restrictions (see Cross-area notes).
- **Tests pinning current behaviour:** none.
- **Arena impact:** observation would need to describe obstacles; menus (`_spell_targets`, `aim_candidates`) would filter by clear path; the heuristic's placement search likewise. No study scenario has obstacles, so today nothing changes.
- **Known in:** new (frightened `_note` mentions line of sight).
- **Size:** L — new spatial subsystem (obstacles + ray tests), then a clear-path check in targeting and a per-location occlusion test in each AoE volume.

#### SPELL-M-03 — Let reaction-time spells be cast on their trigger, outside the caster's turn
- **Status:** open
- **Type / severity:** MISSING — S3
- **SRD:** p.101 "Reactions": "Some spells can be cast as reactions. These spells take a fraction of a second to bring about and are cast in response to some event. If a spell can be cast as a reaction, the spell description tells you exactly when you can do so."
- **Current behaviour:** `CastingTimeType.REACTION` loads and maps to `REACTION_COST` (`src/models/action.py:162-175`), and `reaction_trigger` is stored as free text (`src/models/spell_properties.py:131-140`). But `resolve_spell` starts with `_assert_active(caster)` (`src/combat/combat_system.py:385`), so a reaction spell can only be cast on the caster's own turn (spending the reaction), never in response to its trigger. No event hook offers a reaction window. **Loud** off-turn (refused as not your turn).
- **Evidence:** `.srd_work/probes/SPELL/p13_casting_time.py`: `reaction casting time -> 1 reaction (when hit) | cost: … reactions=1 …` and `cast a reaction spell on another creature's turn -> RuleViolation It is not Cleric's turn (active: Goblin)`. `grep -rn "reaction_trigger" src` finds only the model, loader and `__str__`.
- **Gap:** a spell with a reaction casting time can be cast when its trigger occurs (e.g. "when you are hit by an attack", "when you see a creature … casting a spell", "when you or a creature within 60 feet of you falls"), on any creature's turn, using the caster's reaction, and its effect can modify the triggering event (Shield's +5 AC applies to the triggering attack).
- **Acceptance criteria:**
  1. A reaction spell whose trigger is "hit by an attack" can be cast during the attacker's turn, between `ATTACK_ROLLED` and the hit decision; the caster's reaction is spent; a +5 AC effect turns that hit into a miss.
  2. Casting it on the caster's own turn with no trigger is refused.
  3. A caster with no reaction left cannot cast it.
- **Depends on / unblocks:** the general reaction/interrupt subsystem (cross-area: ATK/TURN opportunity attacks and reactions). Content: Shield, Counterspell, Feather Fall, Hellish Rebuke.
- **Tests pinning current behaviour:** none found.
- **Arena impact:** needs an out-of-turn decision point for agents (the prompt says reactions are "not modelled", `src/arena/interfaces.py` ~L75).
- **Known in:** CODEBASE_REVIEW §4 item 3 (reactions in general).
- **Size:** L — structured triggers on reaction spells plus an interrupt window in the resolvers.

#### SPELL-M-05 — Finish upcasting: healing dice, extra darts/rays/targets, and data for the ten shipped spells (partial)
- **Status:** open
- **Type / severity:** MISSING (partial) — S3
- **SRD:** p.100 "Casting a Spell at a Higher Level": "When a spellcaster casts a spell using a slot that is of a higher level than the spell, the spell assumes the higher level for that casting. … Some spells, such as magic missile and cure wounds, have more powerful effects when cast at a higher level".
- **Current behaviour:** the slot is chosen and spent correctly (`resolve_spell(slot_level=…)`, `src/combat/combat_system.py:392-409`; refuses a slot below the spell's level), and a `damage` block can add dice per slot level (`scaling`, `src/spells/scaling.py`). Missing: `healing` has no `scaling` arg; nothing scales a target/projectile count (Magic Missile darts, Scorching Ray rays, Hold Person targets) or a duration; and ten shipped spells carry prose `higher_level_scaling` but no `scaling` data, so they behave at base level when upcast. **Silent** (an upcast just costs more).
- **Evidence:** CODEBASE_REVIEW **A39** (the ten spells listed there); `blocks/healing.py` contract has no `scaling` field; no count field on `SpellAction` (see SPELL-D-13 evidence).
- **Gap:** the effects each spell describes for higher slots.
- **Acceptance criteria:** as in A39 — e.g. Fireball at slot 4 rolls 9d6; Cure Wounds at slot 2 heals 2d8 + mod; Magic Missile at slot 2 fires 4 darts.
- **Depends on / unblocks:** the deferred upcasting framework (user's design pending, memory "upcasting framework pending"); SPELL-D-13.
- **Tests pinning current behaviour:** `tests/test_upcasting.py` (covers the working damage path).
- **Arena impact:** A39 notes the arena already offers upcasting; no upcast occurred in `results/final`.
- **Known in:** CODEBASE_REVIEW A39; SPELL_SYSTEM_REMAINING (upcasting deferred).
- **Size:** S for the damage-only data fixes; M for healing/count scaling.

#### SPELL-M-07 — Enforce spell components (V, S, M), including costly and consumed materials
- **Status:** open
- **Type / severity:** MISSING — S3
- **SRD:** p.101 "Components": "If you can't provide one or more of a spell's components, you are unable to cast the spell." p.101-102: gagged / silence blocks V; S needs "free use of at least one hand"; M: "if a cost is indicated for a component, a character must have that specific component … If a spell states that a material component is consumed by the spell, the caster must provide this component for each casting".
- **Current behaviour:** `SpellComponents` (verbal, somatic, material: list of strings) is loaded and serialised (`src/models/spell_properties.py:233-263`, `src/loaders/stat_block_loader.py:253-260`) but read by nothing at cast time. There is no hands/held-item model, no inventory or focus, no silence/gagged state, and material components have no cost or consumed flag. A caster under a (future) silence effect, or with both hands full, casts normally. **Silent** (but no shipped content can create the blocking situations today).
- **Evidence:** `grep -rn "components\|\.verbal\|\.somatic\|requires_material" src web` → only the loader and the model; `grep -rni "silence\|gagged\|free_hand\|hands\|inventory\|equipment\|focus" src` → no model.
- **Gap:** a cast is refused if the caster cannot speak (V), has no free hand (S; M needs a hand too, possibly the same one), or lacks a costed material component; consumed components are removed per casting.
- **Acceptance criteria:**
  1. A caster with a "cannot speak" state (e.g. in a silence area) cannot cast a V spell; can cast a spell with no V.
  2. A caster with no free hand cannot cast an S spell.
  3. A spell with a costed, consumed material component is refused without it and consumes it on a successful cast.
- **Depends on / unblocks:** an equipment/hands model (ATK weapon properties, two-handed) and an area-effect model for Silence. Content: Silence, Counterspell interactions, Revivify/Raise Dead (costed).
- **Tests pinning current behaviour:** none.
- **Arena impact:** observation would need held items / silence; low value for the current study.
- **Known in:** CODEBASE_REVIEW §4 item 7 ("component enforcement").
- **Size:** M/L — mostly the prerequisites (hands, inventory); the check itself is small.

#### SPELL-M-02 — Let a caster end concentration at will
- **Status:** open
- **Type / severity:** MISSING — S4
- **SRD:** p.102 "Concentration": "You can end concentration at any time (no action required)."
- **Current behaviour:** `Entity.end_concentration` exists (`src/models/entity.py:332`) but no `CombatSystem` method, web handler or arena tool exposes it.
- **Evidence:** `grep -rn "end_concentration" src web` → only `entity.py` and `blocks/global_effects.py`; the arena's four tools are `attack`, `cast_spell`, `move`, `end_turn` (`src/arena/tools.py`); web handlers in `web/routers/combat.py` have no such command.
- **Gap:** a free, any-time "drop concentration" choice (useful e.g. to end Haste deliberately, or a self-damaging effect).
- **Acceptance criteria:** 1. `combat.end_concentration(caster)` (any time, no resource cost) ends the caster's concentrated spell and its grants. 2. It is legal outside the caster's turn.
- **Depends on / unblocks:** none.
- **Tests pinning current behaviour:** none.
- **Arena impact:** would need a tool or an `end_turn` argument; prompt text change. Low value for the study.
- **Known in:** new.
- **Size:** S.

#### SPELL-M-08 — Casting in armor you are not proficient with
- **Status:** open
- **Type / severity:** MISSING — S4
- **SRD:** p.100 "Casting in Armor": "you must be proficient with the armor you are wearing to cast a spell."
- **Current behaviour:** there is no armor model: AC is a flat `armor_class` on `StatBlock` (`src/models/stat_block.py`) plus `ac` modifiers (`src/models/entity.py:388-391`); no worn-armor item or armor proficiency exists, so the rule cannot arise.
- **Evidence:** `grep -rni "armor_type\|armor_proficien\|equipment" src` → nothing.
- **Gap:** with an armor model, a caster wearing armor they lack proficiency in cannot cast.
- **Acceptance criteria:** once armor exists: a wizard in heavy armor without proficiency → cast refused.
- **Depends on / unblocks:** an equipment model (ATK/MON).
- **Tests pinning current behaviour:** none.
- **Arena impact:** none.
- **Known in:** new.
- **Size:** S after an equipment model exists.

#### SPELL-M-09 — Give cylinders their own height, and let them descend from the top (partial)
- **Status:** open
- **Type / severity:** MISSING (partial) — S4
- **SRD:** p.103 "Cylinder": "The circle must either be on the ground or at the height of the spell effect. … The spell's effect then shoots up from the base or down from the top, to a distance equal to the height of the cylinder. A cylinder's point of origin is included in the cylinder's area of effect."
- **Current behaviour:** `CylinderVolume` is an upright cylinder from `origin.y` upward (`src/spatial/aoe.py:178-217`); its height is `aoe.height_ft` or, when absent, the radius (`src/combat/combat_system.py:883-891`). `height_ft` is never loaded from JSON (CODEBASE_REVIEW **A38**), so every cylinder is as tall as its radius (Moonbeam: 5 ft radius, 40 ft high → 5 ft high). There is no "down from the top" orientation; since every aim is at ground level (SPELL-D-04), a cylinder placed in the air cannot be expressed. Origin inclusion and the radius test are correct. No shipped spell is a cylinder. **Silent** for authored heights.
- **Evidence:** A38 (loader reads only `shape` and `size_ft`, `src/loaders/stat_block_loader.py:333-339`); code reading of `_build_aoe_volume`.
- **Gap:** load `height_ft` (A38) and allow a top-anchored cylinder (origin circle at the effect's height, extending down).
- **Acceptance criteria:** 1. A cylinder spell authored with `height_ft: 40`, radius 5, catches a creature 30 ft above its ground-level centre (once flight exists) and its loaded `aoe.height_ft == 40`. 2. A top-anchored cylinder at height 40 catches a ground creature under it.
- **Depends on / unblocks:** A38; vertical positions (MOVE: flying).
- **Tests pinning current behaviour:** cylinder tests in `tests/test_aoe*.py` that rely on the height default.
- **Arena impact:** none.
- **Known in:** CODEBASE_REVIEW A38.
- **Size:** S.

### COND — Conditions, ability checks, saves, vision and hiding (SRD pp.76–87, 93–94, 358–359)

Severity note: only one shipped spell applies any condition (Charm Person, known only
by `examples/creatures/debug_wizard.json`). Gaps in other conditions therefore do not
arise with shipped content today, so they are graded S2 ("silent wrong outcome in an
uncommon situation") rather than S1; each becomes S1 the moment content applying that
condition ships (Hold Person, Sleep, a shove, a poison bite).

#### COND-M-01 — Make paralyzed, stunned, unconscious and petrified creatures auto-fail STR and DEX saves
- **Status:** open
- **Type / severity:** MISSING (partial) — S2 (silent)
- **SRD:** p.358 "Paralyzed": "The creature automatically fails Strength and Dexterity
  saving throws." Same bullet under Stunned and Unconscious (p.359) and Petrified
  (p.359).
- **Current behaviour:** the four condition rules
  (`rules/entity_effects/conditions/{paralyzed,stunned,unconscious,petrified}.json`)
  only cancel the holder's own attacks and grant advantage to attackers. The
  `saving_throw` block (`src/spells/blocks/rolls.py:134-169`) emits
  `SAVING_THROW_DECLARED`, whose data carries only `advantage`/`disadvantage`
  (`src/combat/event_data.py:179-192`); there is no flag a rule can set to force a
  failure, and `roll_saving_throw` (`src/utils/saving_throw.py:34-47`) always rolls.
  Silent: the save is rolled normally.
- **Evidence:** `.srd_work/probes/COND/autofail_saves.py` (Sacred Flame, DEX save, target
  DEX 30 so its minimum total 11 beats DC 10):
  ```
  paralyzed    caster DC=10 target DEX save bonus=+10  failed saves: 0/20  (RAW: 20/20)
  stunned      caster DC=10 target DEX save bonus=+10  failed saves: 0/20  (RAW: 20/20)
  unconscious  caster DC=10 target DEX save bonus=+10  failed saves: 0/20  (RAW: 20/20)
  petrified    caster DC=10 target DEX save bonus=+10  failed saves: 0/20  (RAW: 20/20)
  ```
- **Gap:** a STR or DEX save by a creature with any of the four conditions must fail
  without regard to the roll; other abilities' saves are unaffected.
- **Acceptance criteria:**
  1. Target paralyzed (or stunned / unconscious / petrified), DEX +10, DC 10 Sacred Flame
     → `save_success` False on every seed; damage dealt every cast.
  2. Same target, a WIS-save spell (Charm Person) → rolled normally (can succeed).
  3. A STR save is auto-failed the same way (a STR-save program on a paralyzed target).
  4. Ending the condition (scope disposed) restores normal saves.
- **Depends on / unblocks:** a new event-modifier block (e.g. `force_save_outcome`) or a
  field on `SAVING_THROW_DECLARED` that `saving_throw` honours. Unblocks Hold Person,
  Sleep-style content. Should also apply to the concentration save once it uses the shared path (SPELL-D-08).
- **Tests pinning current behaviour:** none found.
- **Arena impact:** heuristic save-damage estimates (`src/arena/heuristic/estimate.py`)
  assume a rolled save; they should treat these targets as certain failures.
- **Known in:** condition `_note`s ("Auto-fail STR and DEX saving throws (pending save
  system)" — the save system now exists, so the note is stale about the reason);
  CODEBASE_REVIEW §4 item 9.
- **Size:** S — one event field or event-modifier block + four rule JSON edits.

#### COND-M-02 — Make hits within 5 ft on a paralyzed or unconscious creature critical hits
- **Status:** open
- **Type / severity:** MISSING (partial) — S2 (silent)
- **SRD:** p.359 "Paralyzed": "Any attack that hits the creature is a critical hit if the
  attacker is within 5 feet of the creature." Same bullet under "Unconscious".
- **Current behaviour:** neither rule touches `ATTACK_ROLLED`/`ATTACK_HIT`; the only crit
  sources are the nat-20 rule (`rules/global/critical_hit.json`) and an explicit
  `force_critical`. `attack_roll` reads `critical_hit` from `ATTACK_ROLLED`
  (`src/spells/blocks/rolls.py:85-90`). Silent: hits deal normal damage.
- **Evidence:** `.srd_work/probes/COND/autocrit_and_prone.py` (1d1 weapon: crit = 2,
  normal = 1; target AC 1):
  ```
  paralyzed    edge gap    0 ft: hits 40/40, crits 2/40, final adv 40/40, final dis 0/40
  unconscious  edge gap    0 ft: hits 40/40, crits 2/40, final adv 40/40, final dis 0/40
  None         edge gap    0 ft: hits 40/40, crits 2/40, ...
  ```
  (RAW for the first two rows: crits 40/40.)
- **Gap:** a hit from an attacker within 5 ft of a paralyzed or unconscious target is a
  critical hit; a hit from farther away is not (only nat 20).
- **Acceptance criteria:**
  1. Attacker adjacent (edge gap 0) to a paralyzed target, hit on a non-20 roll →
     `critical_hit` True and damage dice doubled.
  2. Same with an unconscious target.
  3. Attacker 30 ft away (ranged attack) on a paralyzed target, non-20 hit → not a crit.
  4. A miss stays a miss (the rule converts hits, it does not cause them).
- **Depends on / unblocks:** needs an attacker–defender distance readable in a rule
  expression at `ATTACK_ROLLED`/`ATTACK_HIT` time (edge-to-edge, the same measure as
  `check_attack_range`), e.g. a `distance_ft` event field or expression helper. The
  "within 5 feet" test is distance, not melee/ranged typing, so it does not need ATK's
  attack-type work (ATK-M-01), but shares the distance primitive with COND-M-03 (prone).
  Needs **ATK-D-05** if the rule is written on `ATTACK_DECLARED` (a crit forced there is
  ignored today); writing it on `ATTACK_ROLLED` would instead force a *hit*, which is
  wrong for a miss. Also needs COND-D-01 (an unconscious creature must be attackable).
- **Tests pinning current behaviour:** none found.
- **Arena impact:** heuristic expected-damage on paralyzed/unconscious targets should
  double dice for adjacent attackers; menus unchanged.
- **Known in:** paralyzed.json and unconscious.json `_note` ("pending melee/ranged
  distinction and auto-crit logic").
- **Size:** S–M — a distance field/helper + two rule edits.

#### COND-M-03 — Give attacks against a prone creature advantage within 5 ft and disadvantage beyond, and let prone end
- **Status:** open
- **Type / severity:** MISSING (partial) — S2 (silent)
- **SRD:** p.359 "Prone": "An attack roll against the creature has advantage if the
  attacker is within 5 feet of the creature. Otherwise, the attack roll has
  disadvantage." and "...unless it stands up and thereby ends the condition."
  Unconscious (p.359): "The creature drops whatever it's holding and falls prone."
- **Current behaviour:** `rules/entity_effects/conditions/prone.json` gives only the prone
  creature's own attacks disadvantage. Attacks *against* it are unmodified at any
  distance. Nothing can end prone except a duration or dispel: no stand-up action exists
  (`src/arena/tools.py` exposes only attack/cast_spell/move/end_turn; no block ends a
  condition by type, and `Entity.remove_condition*` (`src/models/entity.py:168-194`) have
  no production callers — grep of `src/` and `web/`). The unconscious rule does not apply
  prone. Silent.
- **Evidence:** `.srd_work/probes/COND/autocrit_and_prone.py`:
  ```
  prone        edge gap    0 ft: ... final adv 0/40, final dis 0/40   (RAW adv 40/40)
  prone        edge gap   30 ft: ... final adv 0/40, final dis 0/40   (RAW dis 40/40)
  ```
  `.srd_work/probes/COND/unconscious_is_dead.py` shows an unconscious creature's
  conditions as `['unconscious']` (no prone). The unconscious `_note`'s blocker is
  **stale**: `.srd_work/probes/COND/unconscious_onset_prone.py` loads a variant rule
  (`rules_variant/conditions/unconscious.json`, a `CONDITION_ADDED` trigger applying
  prone to `self`) and prints `after onset: ['unconscious', 'prone']` /
  `after unconscious removed: ['prone']` — the onset-prone rule is expressible today and
  prone correctly outlives the unconscious condition.
- **Gap:** distance-dependent advantage/disadvantage against prone targets; unconscious
  onset applies prone; a creature can end prone by standing up.
- **Acceptance criteria:**
  1. Prone target, attacker edge gap 0 → advantage; edge gap 30 ft → disadvantage.
  2. Prone attacker who is also attacked at 30 ft by a blinded attacker → disadvantage
     only (all sources collapse to one flag; adv+dis cancel).
  3. Applying unconscious adds prone; removing unconscious leaves prone.
  4. A stand-up command ends prone (its movement cost is MOVE's to define).
- **Depends on / unblocks:** the distance primitive from COND-M-02 (RAW is "within 5
  feet", so ATK-M-01's melee/ranged typing is not strictly required, though a reach-10
  melee attack from 10 ft gets disadvantage under RAW). Standing up and crawling are
  **MOVE-M-04**; this entry owns only the attack modifiers and the onset-prone rule.
  Shove is ATK-M-08. Unblocks Thunderwave-style knock-downs and falling (MOVE-M-10).
- **Tests pinning current behaviour:** none found (`tests/test_block_parity.py:94` applies
  prone but only checks the marker).
- **Arena impact:** observation already lists conditions; a stand-up tool/menu option
  and prompt text are needed once prone can be applied; heuristic should value
  closing to 5 ft vs a prone target and keeping range from a prone archer.
- **Known in:** prone.json `_note` (says "requires distinguishing attack type (melee vs.
  ranged)"; RAW keys on distance, not attack type), unconscious.json `_note`.
- **Size:** M — distance helper (shared) + rule edits + a stand-up action.

#### COND-M-05 — Model "incapacitated" as one predicate that every action path checks, and let a rule stop a spell
- **Status:** open
- **Type / severity:** MISSING (partial) — S2 (silent)
- **SRD:** p.358 "Incapacitated": "An incapacitated creature can't take actions or
  reactions." p.102 "Concentration": "You lose concentration on a spell if you are
  incapacitated or if you die." p.260 "Legendary Actions": "it can't use them while
  incapacitated or otherwise unable to take actions." p.358 "Grappled": "The condition
  ends if the grappler is incapacitated".
- **Current behaviour:** incapacitation is enforced only by (a) skipping the creature's
  own turn (`src/combat/turn_manager.py:14-27`) and (b) each of the five rules cancelling
  `ATTACK_DECLARED` when the holder attacks (incapacitated/paralyzed/stunned/petrified/
  unconscious JSON). Gaps:
  - `resolve_legendary_action` checks no condition (`src/combat/combat_system.py:452-557`):
    a stunned creature's legendary *spell* resolves in full; a legendary attack is
    cancelled only after the point is spent. (Owned by **MON-D-02**.)
  - Nothing subscribes to `CONDITION_ADDED` (grep `CONDITION_ADDED` in `src/`, `rules/`):
    becoming incapacitated does not end concentration. (Owned by **SPELL-D-07**.)
  - The skipped turn itself is **TURN-D-01** (it also freezes condition durations and
    end-of-turn repeat saves; corroborated by `.srd_work/probes/COND/skipped_turn_duration.py`:
    a `duration: 1` stun is still present after 5 rounds, 0 `TURN_END` events for the
    holder).
  - `SpellResolver.resolve` ignores a cancelled `SPELL_CAST`
    (`src/combat/spell_resolver.py:60-65`), so a rule cannot stop a cast — every
    condition `_note` saying "SPELL_CAST cancellation (pending ...)" is waiting on this.
  - The "includes incapacitated" relation is copied by hand into four rule files and
    `_SKIP_CONDITIONS`; nothing else that might check INCAPACITATED would see a
    paralyzed creature (grep `INCAPACITATED` in `src/`: only `turn_manager.py`).
  - Grappled-ends-when-grappler-incapacitated: no grappler reference (COND-M-08).
  Silent throughout.
- **Evidence:** `.srd_work/probes/COND/incapacitated.py`:
  ```
  (b) hero concentrating before stun: True, AC 12
  (b) hero concentrating after stun:  True, AC 12  (RAW: False, AC back to base)
  (a) stunned dragon legendary points: 3
  (a) legendary Tail attack -> (False, 0, None); points left 2
  (a) 2x legendary Sacred Flame -> hero hp 100 -> 92; points left 0  (RAW: refused, can't take actions)
  (c) with SPELL_CAST cancelled, 3x Sacred Flame -> hero hp 92 -> 89
  ```
- **Gap:** one "is incapacitated" predicate (true for incapacitated, paralyzed, stunned,
  petrified, unconscious) that the referee checks before any action, bonus action,
  reaction or legendary action, and whose onset ends concentration; and a working
  `SPELL_CAST` cancel so condition rules can stop casting the same way they stop attacks.
  This entry owns the predicate and the cancel; the three consumers above are fixed
  under their own IDs and should read this predicate.
- **Acceptance criteria:**
  1. Stunned legendary creature → `resolve_legendary_action` raises `RuleViolation`;
     no legendary point spent.
  2. Concentrating caster gains paralyzed (or any incapacitating condition) →
     concentration ends and its grants (Shield of Faith's +2 AC) are revoked.
  3. A `cancel` on `SPELL_CAST` stops the spell before any effect and before (or with a
     refund of) its cost — or, if the design prefers refusal, a validator rejects
     `cancel` under a `SPELL_CAST` trigger so it cannot silently no-op.
  4. A helper `is_incapacitated(entity)` is true for all five conditions and is what the
     turn skip, the attack cancel and the legendary guard read.
- **Depends on / unblocks:** unblocks MON-D-02, SPELL-D-07, TURN-D-01 (all should read the
  predicate), and reactions/opportunity attacks (MOVE-M-01) when they exist. Charmed's
  harmful-spell refusal (COND-D-04) also wants the SPELL_CAST hook or a pre-spend check.
- **Tests pinning current behaviour:** `tests/rules/entity_effects/conditions/test_petrified.py::test_petrified_creature_cannot_attack`
  (asserts cancellation; compatible).
- **Arena impact:** legendary actions are not exposed to agents today, so the arena is
  unaffected until they are; concentration loss changes heuristic value of control.
- **Known in:** incapacitated/paralyzed/stunned/petrified/unconscious `_note`s
  ("SPELL_CAST cancellation", "Reactions cannot be taken (pending reaction system)").
- **Size:** M — predicate + referee guards + a `CONDITION_ADDED` concentration rule +
  honour SPELL_CAST cancel.

#### COND-M-06 — Add ability checks, contests and skills (with passive scores and help)
- **Status:** open
- **Type / severity:** MISSING — S2
- **SRD:** p.77 "Ability Checks": "roll a d20 and add the relevant ability modifier. As with
  other d20 rolls, apply bonuses and penalties, and compare the total to the DC." p.77
  "Contests": "compare the totals of their two checks ... If the contest results in a
  tie, the situation remains the same as it was before the contest." p.78 "Skills":
  "proficiency in a skill means an individual can add his or her proficiency bonus to
  ability checks that involve that skill." p.78 "Passive Checks": "10 + all modifiers
  that normally apply to the check. If the character has advantage on the check, add 5.
  For disadvantage, subtract 5." p.79 "Working Together": "can make an ability check with
  advantage". p.79 "Group Checks": "If at least half the group succeeds, the whole group
  succeeds."
- **Current behaviour:** there is no ability-check path anywhere. No block, event or
  resolver rolls a check (block list in `docs/current/BLOCK_REFERENCE.md`: no check or
  contest block; `EventType` has no check event). `StatBlock.get_skill_bonus`
  (`src/models/stat_block.py:77-84`) is called only by `tests/test_models.py`. The
  creature loader never reads `skills` (`src/loaders/stat_block_loader.py:133-194`; the
  key is silently dropped, MON-D-07), so every loaded creature has no skill proficiency.
  `StatBlock.__post_init__` fills `skills` from a shallow `STANDARD_SKILLS.copy()` only
  when the dict is empty (`stat_block.py:68-69`), so a creature given one proficient
  skill loses all the others (`get_skill_bonus("stealth")` raises "Unknown skill"), and
  default stat blocks share the module's `Skill` objects. Initiative is a bare
  `roll_d20() + DEX mod` (`src/combat/initiative.py:55-57`), not a DEX check (so no
  adv/dis or check modifiers reach it).
- **Evidence:** searches: `grep -rniE "ability_check|skill_check|contest|passive|ABILITY_CHECK|get_skill_bonus"`
  over `src/ web/ rules/ examples/` → only the `get_skill_bonus` definition (and unrelated
  JS `passive:` listener options); `grep '"skills"' src/loaders` → none.
- **Gap:** a check roll (d20 + ability mod + skill proficiency/expertise + modifiers,
  adv/dis via a declared event, auto-fail hooks) against a DC; a contest between two
  creatures' checks (tie = status quo); passive score = 10 + mods ±5; loadable skill
  proficiencies merged over the 18 standard skills. Every condition bullet that mentions
  checks hangs on this: blinded/deafened auto-fail checks needing sight/hearing, charmer's
  advantage on social checks, frightened/poisoned/exhaustion-1 disadvantage on checks.
- **Acceptance criteria:**
  1. A `check` roll for STR (Athletics) with proficiency PB 2, STR 16 → d20 + 5; with
     EXPERT → d20 + 7; emits a declare event on which a poisoned creature gets
     disadvantage.
  2. A contest: equal totals → neither side wins (the caller sees "tie").
  3. Creature JSON `skills: {"stealth": "proficient", "perception": "expert"}` loads;
     other skills still resolve; an unknown skill name raises at load.
  4. Passive Perception = 10 + WIS mod + proficiency; +5 with advantage, -5 with
     disadvantage.
- **Depends on / unblocks:** unblocks grapple/shove (**ATK-M-08**) and escaping a grapple
  (COND-M-08), Hide/Search (COND-M-09, TURN), the Help action's check form (TURN), check
  bullets of blinded/deafened/charmed/frightened/poisoned/exhaustion. Initiative as a DEX
  check is TURN's call (it changes initiative only via adv/dis or check modifiers).
- **Tests pinning current behaviour:** `tests/test_models.py::test_skill_bonus_*` (assert
  the skill math; still valid).
- **Arena impact:** observation/menus gain check-based actions (grapple, shove, hide)
  when those land; prompt text lists them.
- **Known in:** condition `_note`s ("pending ability check system").
- **Size:** M — a `check`/`contest` block pair + declare event + loader field.

#### COND-M-04 — Track exhaustion as a level (1-6) with its cumulative effects
- **Status:** open
- **Type / severity:** MISSING — S3
- **SRD:** p.358 "Exhaustion": "Exhaustion is measured in six levels." Table: 1
  disadvantage on ability checks; 2 speed halved; 3 disadvantage on attack rolls and
  saving throws; 4 hit point maximum halved; 5 speed reduced to 0; 6 death. "A creature
  suffers the effect of its current level of exhaustion as well as all lower levels."
  "An effect that removes exhaustion reduces its level ..."
- **Current behaviour:** `rules/entity_effects/conditions/exhaustion.json` has an empty
  program (marker only). `Condition` has no level field (`src/models/condition.py:31-52`);
  each `apply_condition` adds another independent marker. `Entity.max_hp` reads only the
  stat block (`src/models/entity.py:379-381`), so the `max_hp` StatModifier convention
  documented in `src/models/stat_modifier.py` is not honoured either. Silent: exhausted
  creatures fight at full strength.
- **Evidence:** `.srd_work/probes/COND/misc_conditions.py`:
  ```
  (3) exhaustion applied 4x: markers=['exhaustion', 'exhaustion', 'exhaustion', 'exhaustion'], B attacks -> (False, False) (RAW level 4: dis), max_hp=100 (RAW 50)
  (3) with a max_hp -50 StatModifier: max_hp=100
  ```
- **Gap:** one exhaustion level per creature (0-6), raised and lowered by an amount;
  cumulative effects by level; level 6 kills; removal reduces the level.
- **Acceptance criteria:**
  1. Applying exhaustion twice (1 level each) → level 2, one marker/one level, not two
     markers.
  2. Level 3 → the creature's attacks and saves have disadvantage (through
     `ATTACK_DECLARED` and `SAVING_THROW_DECLARED`); level 2 does not.
  3. Level 4 → `max_hp` halved (round down), `current_hp` clamped to it; reducing to
     level 3 restores the maximum (not current HP).
  4. Level 6 → the creature dies (ENTITY_DIES).
- **Depends on / unblocks:** speed effects (levels 2, 5) are **MOVE-M-06** (needs MOVE-M-03);
  level 1 needs ability checks (COND-M-06); level 4 needs a modifiable HP maximum (also
  wanted by content such as Aid / Vampiric Touch-style max-HP reduction); exhaustion
  immunity is MON-M-06; long-rest reduction is out of combat (COND-M-12).
- **Tests pinning current behaviour:** none found.
- **Arena impact:** observation shows conditions as a list of names; it should show the
  level. Heuristic `CONTROL_SEVERITY` has no exhaustion entry (default 0.3).
- **Known in:** exhaustion.json `_note` (lists every level as pending).
- **Size:** M — a level-carrying condition (a field on `Condition` or a counted resource)
  + a rule keyed on level + an HP-max modifier.

#### COND-M-07 — Model vision: light, obscurement and senses (darkvision, blindsight, truesight), and "can see"
- **Status:** open
- **Type / severity:** MISSING — S3
- **SRD:** p.86 "Vision and Light": "A heavily obscured area ... blocks vision entirely. A
  creature effectively suffers from the blinded condition ... when trying to see something
  in that area." Darkvision: "can see in darkness as if the darkness were dim light".
  Blindsight: "can perceive its surroundings without relying on sight, within a specific
  radius." Truesight: "see invisible creatures and objects". p.358 "Invisible": "impossible
  to see without the aid of magic or a special sense."
- **Current behaviour:** no light levels, obscured areas, senses, or "can A see B"
  predicate exist. `StatBlock` has no senses field and the loader reads none
  (`src/models/stat_block.py:42-64`, `src/loaders/stat_block_loader.py:133-194`). The
  blinded and invisible rules therefore apply their adv/dis unconditionally
  (`blinded.json`, `invisible.json`): an invisible creature keeps advantage against a
  creature with blindsight or truesight, and a blinded creature with blindsight still
  attacks at disadvantage. Every battle is effectively in bright light with no obstacles.
- **Evidence:** searches: `grep -rniE "darkvision|blindsight|truesight|tremorsense|senses|obscur|line_of_sight|can_see|light_level"`
  over `src/ rules/ examples/ web/` → no hits (only the invisible `_note`).
- **Gap:** a per-creature senses list (type + range), an environment notion of light /
  obscurement (even if only "magical darkness" areas from spells), and a single
  `can_see(observer, target)` predicate that blinded, invisible, unseen-attacker rules,
  frightened's line of sight and "a creature you can see" spell targeting all read.
- **Acceptance criteria:**
  1. Invisible attacker vs a defender with blindsight 30 ft at 10 ft → no advantage
     (and the defender's attacks back have no disadvantage).
  2. Blinded attacker with blindsight 10 ft attacking a target 5 ft away → no
     disadvantage; at 20 ft → disadvantage.
  3. Truesight 60 ft sees an invisible creature at 30 ft.
  4. Creature JSON `senses: {"darkvision": 60}` loads; an unknown sense raises.
- **Depends on / unblocks:** obstruction / line-of-sight model shared with ATK-M-04/ATK-Q-02
  (cover) and SPELL-M-01 (clear path). Unblocks COND-M-09 (hiding), COND-D-06 (fear LoS),
  ATK-M-02's "hostile creature who can see you", "a creature you can see" spell targeting.
- **Tests pinning current behaviour:** `tests/rules/entity_effects/conditions/test_blinded.py`
  (unconditional adv/dis; stays valid for creatures without senses).
- **Arena impact:** observation would need per-viewer visibility (an unseen enemy's
  position hidden or approximate) — a large change to `observation.py` and the
  information policy, which today never hides position.
- **Known in:** CODEBASE_REVIEW §4.7 ("speed variants/senses"); invisible.json `_note`.
- **Size:** L — senses are S, but light/obscurement and LoS are a new spatial subsystem.

#### COND-M-08 — Track the grappler, and end grappled when the grappler is incapacitated or the target leaves its reach
- **Status:** open
- **Type / severity:** MISSING (partial) — S3
- **SRD:** p.358 "Grappled": "The condition ends if the grappler is incapacitated" and
  "also ends if an effect removes the grappled creature from the reach of the grappler or
  grappling effect".
- **Current behaviour:** `rules/entity_effects/conditions/grappled.json` is an empty
  program. Nothing records who grapples whom; nothing ends the condition except duration
  or dispel. Silent.
- **Evidence:** `.srd_work/probes/COND/misc_conditions.py`:
  `(4) grappler A stunned; B conditions = ['grappled'] (RAW: grappled ends)`.
- **Gap:** a grappled instance carries its grappler (a binding, as charmed does) and the
  grappler's reach; it ends when the grappler becomes incapacitated (COND-M-05 predicate)
  or when the target is moved beyond that reach (including forced movement).
- **Acceptance criteria:**
  1. Grappler A gains stunned → B's grappled instance from A ends; a grappled instance
     from another creature C remains.
  2. B pushed 15 ft away from A (5-ft reach) → grappled from A ends.
  3. A moves away, dragging B (MOVE-M-15), → grapple persists.
- **Depends on / unblocks:** the grapple action itself is **ATK-M-08** (contest via
  COND-M-06); speed 0 is **MOVE-M-05**; dragging is MOVE-M-15; forced movement MOVE-M-08;
  incapacitated predicate COND-M-05.
- **Tests pinning current behaviour:** none found.
- **Arena impact:** escape-grapple action/menu once grapples exist.
- **Known in:** grappled.json `_note`.
- **Size:** S–M once ATK-M-08 exists (binding + two end triggers).

#### COND-M-09 — Add hiding and the unseen-attacker rules (hidden state, reveal on attack, guessing a location)
- **Status:** open
- **Type / severity:** MISSING — S3
- **SRD:** p.93 "Hide": "you make a Dexterity (Stealth) check in an attempt to hide ... If
  you succeed, you gain certain benefits". p.94 "Unseen Attackers and Targets": "When you
  attack a target that you can't see, you have disadvantage on the attack roll ... If the
  target isn't in the location you targeted, you automatically miss ... When a creature
  can't see you, you have advantage on attack rolls against it. If you are hidden ... you
  give away your location when the attack hits or misses." p.80-81 "Hiding": the Stealth
  total "is contested by the Wisdom (Perception) check of any creature that actively
  searches", and compared to passive Perception.
- **Current behaviour:** no Hide action (`src/arena/tools.py`: attack, cast_spell, move,
  end_turn), no hidden state on `Entity`, no Stealth/Perception rolls (no checks at all,
  COND-M-06). The only "unseen" effects are the blinded/invisible flag rules, which give
  adv/dis but never: reveal an invisible attacker's location, require guessing where an
  unseen target is, or auto-miss a wrong guess. Attacks always name an entity id, so the
  attacker always "knows" the location. The invisible `_note` ("Treated as heavily
  obscured for hiding (pending stealth/hiding system)") is accurate.
- **Evidence:** searches: `grep -rniE "hidden|\bhide\b|stealth|perception"` over
  `src/ rules/ examples/` → only `src/models/skill.py` skill names, the invisible `_note`
  and unrelated "hidden information" arena wording.
- **Gap:** a hidden state per observer (set by a successful Stealth check against
  passive Perception / active Search), cleared by attacking (hit or miss), noise, or being
  found; attacks against a hidden/unseen target pick a location and auto-miss if wrong;
  attacker unseen by its target gets advantage.
- **Acceptance criteria:**
  1. Hide (Stealth 18) vs an enemy with passive Perception 12 → hidden from that enemy;
     its next attack from hiding has advantage, and the attacker is no longer hidden
     afterwards, hit or miss.
  2. Attacking a hidden creature by aiming at the wrong point → automatic miss, reported
     only as "miss".
  3. Attacking an invisible but not hidden creature at its known position →
     disadvantage, can hit.
- **Depends on / unblocks:** COND-M-06 (checks/passives), COND-M-07 (can-see, obscurement
  so there is somewhere to hide), the Hide/Search actions in TURN. Judgement calls are
  COND-Q-02.
- **Tests pinning current behaviour:** none found.
- **Arena impact:** large: observation must hide positions per viewer, tools need a hide
  action and location-targeted attacks; the information policy states position is never
  hidden in v1 (`src/arena/information_policy.py:10`).
- **Known in:** invisible.json `_note`.
- **Size:** L — new per-observer awareness state on top of COND-M-06/COND-M-07.

#### COND-M-10 — Let a condition grant immunities: petrified is immune to poison and disease
- **Status:** open
- **Type / severity:** MISSING (partial) — S3
- **SRD:** p.359 "Petrified": "The creature is immune to poison and disease, although a
  poison or disease already in its system is suspended, not neutralized."
- **Current behaviour:** petrified.json halves all damage (so poison damage is halved, not
  zeroed) and does nothing about the poisoned condition: `apply_condition` adds any
  condition unconditionally (`src/spells/blocks/state.py:99-137`), and an existing
  poisoned condition keeps working while petrified. Silent.
- **Evidence:** code reading of petrified.json (no poison handling) and `apply_condition`
  (no immunity check); MON's probe `.srd_work/probes/MON/probe_type_immunity.py` shows the
  same absence for creature condition immunities.
- **Gap:** while petrified: poison damage → 0; poisoned cannot be applied; an existing
  poisoned instance is suspended (no effect, duration paused) until petrified ends.
- **Acceptance criteria:**
  1. Petrified creature takes 10 poison → 0.
  2. Applying poisoned to a petrified creature → refused/no marker.
  3. Poisoned then petrified → its attacks no longer get poisoned's disadvantage (moot
     while it can't attack, but the check/duration are suspended); petrified ends →
     poisoned resumes.
- **Depends on / unblocks:** creature condition immunities are **MON-M-06** (needs the same
  pre-apply hook; this entry adds "immunity granted by a condition" on top); poison damage
  immunity can be written today as `modify_damage multiplier 0 damage_type POISON` in the
  rule, but it then compounds with the 0.5 (ATK-D-03 ordering). Diseases have no engine
  representation (out of scope beyond this line).
- **Tests pinning current behaviour:** none found.
- **Arena impact:** none.
- **Known in:** petrified.json `_note` ("Immune to poison and disease (pending condition
  immunity system)").
- **Size:** S after MON-M-06.

#### COND-M-11 — Represent the narrative condition bullets that have mechanical knock-ons (can't speak, unaware, drops what it holds)
- **Status:** open
- **Type / severity:** MISSING — S4
- **SRD:** p.358 "Paralyzed": "can't move or speak". p.359 "Petrified": "can't move or
  speak, and is unaware of its surroundings". "Stunned": "can speak only falteringly".
  "Unconscious": "The creature drops whatever it's holding".
- **Current behaviour:** none of these is represented. Their combat consequences are small
  today because the creatures concerned are already turn-skipped and cannot act:
  "can't speak" matters for verbal components (spell components are not enforced —
  SPELL area), "drops what it's holding" for equipment (no inventory or held-item
  model), "unaware" for surprise/perception (no checks). "Can't move" is MOVE's.
- **Evidence:** searches: `grep -rniE "verbal|speak|holding|inventory|equipped"` in
  `src/` → only `SpellComponents.verbal` data (`src/models/action.py:151`, loader
  `src/loaders/stat_block_loader.py:256,359`), never checked at cast time; no held-item
  model.
- **Gap:** once components and held items exist, these conditions must block verbal
  casting and drop held items.
- **Acceptance criteria:**
  1. (With component enforcement) a paralyzed creature cannot cast a V spell even out of
     turn (e.g. a reaction).
  2. (With held items) gaining unconscious moves the held weapon to the ground.
- **Depends on / unblocks:** SPELL component enforcement; an equipment model (ATK).
- **Tests pinning current behaviour:** none.
- **Arena impact:** none.
- **Known in:** new.
- **Size:** S each, once the host subsystems exist.

#### COND-M-12 — (Out of combat) Short and long rests, and suffocation
- **Status:** open
- **Type / severity:** MISSING — S4
- **SRD:** p.87 "Short Rest": "spend one or more Hit Dice"; "Long Rest": "regains all lost
  hit points ... regains spent Hit Dice, up to ... half". p.358 Exhaustion: "Finishing a
  long rest reduces a creature's exhaustion level by 1". p.86 "Suffocating": "it can
  survive for a number of rounds equal to its Constitution modifier (minimum of 1 round).
  At the start of its next turn, it drops to 0 hit points and is dying".
- **Current behaviour:** no rest operation, no Hit Dice on `StatBlock`/`Entity`, no breath
  tracking. Battles are single encounters, so this only matters for multi-encounter runs
  (resource attrition: slots, HP, limited uses — MON-M-02 notes recharge-on-rest).
- **Evidence:** `grep -rniE "rest\b|short_rest|long_rest|hit_dice|breath|suffocat"` over
  `src/` → no rest/suffocation code; the only rest-shaped piece is `SpellSlots.refill`
  ("Restore all slots to their maximum (long rest)", `src/models/spell_slots.py:46-48`),
  which nothing calls (`grep "\.refill()"` finds only the legendary-action refill).
- **Gap:** a between-encounter rest operation (HP, Hit Dice, slots, exhaustion −1,
  rest-recharging uses); suffocation as a per-turn countdown is content for environments
  (water, Stinking Cloud-style effects) and needs ATK-M-10 dying.
- **Acceptance criteria:**
  1. Long rest on a creature at 3/20 HP with exhaustion 2 → 20/20 HP, exhaustion 1, slots
     refilled.
  2. Short rest spending one d8 Hit Die with CON +2 → HP rises by d8+2.
- **Depends on / unblocks:** COND-M-04 (levels), MON-M-02 (rest recharge), ATK-M-10.
- **Tests pinning current behaviour:** none.
- **Arena impact:** none for single-match study; matters only for campaign-style runs.
- **Known in:** new.
- **Size:** M — an out-of-combat operation; not needed for the arena.

### MON — Monster stat blocks and legendary creatures (SRD pp.254–260)

#### MON-M-02 — Implement Limited Usage: Recharge X–Y, X/Day, recharge after a rest
- **Status:** open
- **Type / severity:** MISSING — S2
- **SRD:** p.259 "Limited Usage": "At the start of each of the monster's turns, roll a d6.
  If the roll is one of the numbers in the recharge notation, the monster regains the use
  of the special ability." Also "X/Day" and "Recharge after a Short or Long Rest".
- **Current behaviour:** `recharge` is loaded as a free string
  (`src/loaders/stat_block_loader.py:287`) into `Action.recharge`
  (`src/models/action.py:46`) and never read again: `grep -rn recharge` over `src/` and
  `web/` finds only the model field, the loader, and the serializer. No use is tracked,
  no d6 is rolled, nothing refuses a second use. The guide calls it a "Recharge condition
  shown in UI" (`CREATURE_DEFINITION_GUIDE.md`, attack-field table), but the browser
  client does not show it either (`grep -rn recharge web/static web/templates`: no
  hits). An author who writes the SRD notation gets an at-will ability **silently**.
- **Evidence:** `.srd_work/probes/MON/probe_recharge_loader.py`:
  ```
  Fire Breath ('Recharge 5-6'): used 10/10 rounds, every attempt allowed
  Big Spit ('1/Day'): used 10/10 rounds, every attempt allowed
  ```
- **Gap:** per-action limited uses on the entity (not the immutable `StatBlock`), a d6
  recharge roll at the start of the holder's turn, X/Day counters, and refusal when spent.
  Rests are out of scope for a single combat but the counter must exist.
- **Acceptance criteria:**
  1. A "Recharge 5-6" action used on turn 1 is refused (RuleViolation, resource not
     spent) on turn 2 if the seeded start-of-turn d6 rolls 1-4, and allowed if it rolls
     5-6; the roll goes through `dice` and is reproducible under a seed.
  2. A "1/Day" action is refused on its second use in the same combat.
  3. A malformed recharge string (`"Recharge 7"`, `"sometimes"`) raises at load.
  4. The arena menu / observation do not offer a spent ability (and expose "recharging").
- **Depends on / unblocks:** TURN_START must fire for every creature (**TURN-D-01**) or the recharge roll is lost when a creature is stunned. Unblocks breath
  weapons, Slow, Web, Frightful Presence-style abilities, innate X/day (MON-M-03).
- **Tests pinning current behaviour:** none found.
- **Arena impact:** `action_space` / `enumeration` / observation must hide or flag a
  spent ability; the heuristic must value a recharge ability's availability.
- **Known in:** CODEBASE_REVIEW §4 item 7 ("innate/limited-use abilities"); ENGINE_MAP
  lead.
- **Size:** M — a per-entity uses ledger (like `spell_slots`), a parsed recharge model,
  a TURN_START recharge roll, a guard in the resolve paths.

#### MON-M-04 — Give a creature JSON a way to carry special traits (entity rules)
- **Status:** open
- **Type / severity:** MISSING — S2
- **SRD:** p.258 "Special Traits": "characteristics that are likely to be relevant in a
  combat encounter".
- **Current behaviour:** the engine *can* run a per-creature reactive rule —
  `src.spells.rules.apply_entity_rule` → `install_entity_effect`
  (`src/spells/entity_effects.py:28-`) — and Colossus Slayer is one
  (`rules/entity_effects/colossus_slayer.json`). But no creature file can declare one:
  the loader has no traits/features key (`src/loaders/stat_block_loader.py:124-195`),
  `StatBlock` has no field for it, and `grep -rn apply_entity_rule src web` finds no
  production caller (only tests, e.g. `tests/test_attack_parity.py:98`, and the
  apply_condition path). Even `ranger.json` does not get Colossus Slayer from its own
  file. A trait key in JSON is silently dropped (MON-D-07).
- **Evidence:** the greps above; probe `probe_recharge_loader.py` shows unknown keys are
  dropped.
- **Gap:** an SRD monster's traits (Pack Tactics, Magic Resistance, Keen Smell, Regeneration,
  Undead Fortitude, Sunlight Sensitivity, Aggressive, Amphibious, Spider Climb, Legendary
  Resistance …) need a data path from the creature file to installed rules on the
  entity when it enters combat. Several also need event fields the bus lacks today:
  - Magic Resistance ("advantage on saving throws against spells and other magical
    effects"): `SAVING_THROW_DECLARED` carries only `defender, ability, dc, advantage,
    disadvantage` (docs/current/BLOCK_REFERENCE.md §Events) — no caster/action/source, so
    "against spells" cannot be tested.
  - Pack Tactics ("an ally … within 5 feet of the creature and the ally isn't
    incapacitated"): needs a way for an expression to ask about *other* creatures near
    the defender.
  - Legendary Resistance: see MON-M-10.
- **Acceptance criteria:**
  1. A creature JSON lists trait rules (by name or inline program); loading
     `ranger.json`-style content and starting combat installs them on the entity with no
     test-only call.
  2. An unknown trait name raises at load.
  3. A trait authored as a rule fires in a real resolution (e.g. Colossus Slayer from
     the ranger's own file adds its die on a hit against a wounded target).
- **Depends on / unblocks:** `CombatSystem.add_combatant`/`start_combat` installing them;
  richer event data for Magic Resistance / nonmagical damage (ATK-M-13; `DAMAGE_INCOMING`
  carries no attacker/action, `src/combat/event_data.py:199-203`); TURN-M-01 for
  reaction traits. Unblocks most SRD monsters (see content table).
- **Tests pinning current behaviour:** none (tests install rules by hand, which is fine).
- **Arena impact:** observation could describe traits; the heuristic does not account for
  them (it would need to, e.g. Pack Tactics advantage).
- **Known in:** CODEBASE_REVIEW §4 item 7 ("monster traits (Pack Tactics, regeneration)").
- **Size:** M — loader key + `StatBlock` field + install at combat entry; L counting the
  event-field additions.

#### MON-M-05 — Implement Multiattack
- **Status:** open
- **Type / severity:** MISSING — S2
- **SRD:** p.259 "Multiattack": "A creature that can make multiple attacks on its turn has
  the Multiattack action. A creature can't use Multiattack when making an opportunity
  attack, which must be a single melee attack."
- **Current behaviour:** no field, block or handler; an action with `type: "multiattack"`
  loads as a no-op ABILITY (MON-D-07). The only approximation is
  `resource_defaults.actions: 2`, which is wrong in a different way: it grants two whole
  Actions (two spells, two Dashes, a spell and an attack, any two attacks with any
  weapons) — the debug wizard uses `actions: 9` (`examples/creatures/debug_wizard.json:22`).
- **Evidence:** `grep -rniE "multiattack|extra attack"` over `src/`, `rules/`, `examples/`,
  `web/`: no hits in code. CODEBASE_REVIEW §4 item 4: "no field or handler; not in any
  creature JSON."
- **Gap:** one Action that resolves a fixed (sometimes alternative) set of attacks —
  "two claw attacks and one bite", "one with its beak and one with its claws", or "uses
  Frightful Presence, then three attacks" — each attack independently targeted (and
  choosable target per attack), and not usable as an opportunity attack.
- **Acceptance criteria:**
  1. An owlbear-like creature with Multiattack (Beak + Claws) spends one action and
     makes both attacks; each attack may name a different target in reach.
  2. After Multiattack, a further weapon attack in the same turn is refused (no action
     left), and a spell is not castable with a "second action".
  3. Multiattack is not offered as an opportunity attack (once OA exists).
  4. A Multiattack naming an action the creature lacks fails at load.
- **Depends on / unblocks:** per-attack targeting in the arena tool API; opportunity
  attacks (MOVE-M-01, TURN-M-01). Shares the "Attack action makes several attacks" machinery with
  the Extra Attack class feature (ATK/TURN).
- **Tests pinning current behaviour:** none found.
- **Arena impact:** large — the `attack` tool takes one defender; Multiattack needs either
  a multi-target call or a "remaining attacks this action" state the observation and
  menus expose; the heuristic plans whole turns and would need to score it.
- **Known in:** CODEBASE_REVIEW §4 item 4.
- **Size:** M-L — a multiattack action model + a per-turn "attacks remaining" state.

#### MON-M-06 — Load and enforce condition immunities
- **Status:** open
- **Type / severity:** MISSING — S2
- **SRD:** p.257 "Vulnerabilities, Resistances, and Immunities": "In addition, some
  creatures are immune to certain conditions."
- **Current behaviour:** no field (`StatBlock`, `src/models/stat_block.py:42-64`), no
  loader key (dropped silently, MON-D-07), and the `apply_condition` block adds any
  condition unconditionally (`src/spells/blocks/state.py:99-137`); there is no cancellable
  pre-condition event (CONDITION_ADDED fires after the fact). So Charm Person charms the
  shipped stone golem (SRD: immune to charmed — and a construct, not a humanoid).
  **Silent.**
- **Evidence:** `.srd_work/probes/MON/probe_type_immunity.py`:
  ```
  seed 0: Charm Person on Stone Golem -> golem conditions ['CHARMED']
  ```
  `grep -rniE "condition_immun|immune_to_condition"` over `src/ rules/ examples/ web/`: no hits.
- **Gap:** a creature immune to a condition is never given it (the effect that would
  apply it does nothing to that creature; damage riders still apply).
- **Acceptance criteria:**
  1. `condition_immunities: ["charmed"]` loads (unknown condition names raise, via the
     `ConditionType` enum).
  2. Charm Person against such a creature leaves `conditions == []` and installs no charm
     rule, whatever the save.
  3. A spell that deals damage *and* applies poisoned still deals its damage to a
     poison-condition-immune creature.
  4. Exhaustion immunity blocks exhaustion levels (once COND models levels).
- **Depends on / unblocks:** MON-D-07. Sibling of **COND-M-10** (an immunity granted by a
  *condition*, e.g. petrified → poisoned); both need the same guard in `apply_condition`,
  fed from two sources (stat block here, active conditions there). Unblocks
  undead/constructs/elementals/fiends.
- **Tests pinning current behaviour:** none found.
- **Arena impact:** heuristic value of condition spells should drop to 0 vs immune targets;
  observation may hide or reveal immunities under the information policy.
- **Known in:** new.
- **Size:** S — field + loader + a guard in `apply_condition`.

#### MON-M-01 — Give legendary creatures a legendary-action phase (and lair actions)
- **Status:** open
- **Type / severity:** MISSING (partial) — S3
- **SRD:** p.260 "Legendary Actions" (above); "Lair Actions": "On initiative count 20
  (losing all initiative ties), it can use one of its lair action options. It can't do so
  while incapacitated…"
- **Current behaviour:** what exists is a correct pool (`src/models/legendary_actions.py`:
  `count_per_round`, `spend`, `refill`), a loader field
  (`legendary_actions.count_per_round`, `src/loaders/stat_block_loader.py:177-179`), an
  entity instance (`src/models/entity.py:79-85`) and the refill at TURN_START. Missing:
  any point in the turn loop where a legendary creature is *offered* the choice, any
  agent/arena tool for it (`src/arena/tools.py` has only attack/cast_spell/move/end_turn;
  the prompt says "not modelled", `src/arena/interfaces.py:75-76`), and the heuristic /
  scripted agents never use one. Lair actions do not exist at all: no loader key, no
  model, no initiative-count-20 entry in `InitiativeTracker`, no "lair" anywhere.
  Note for prioritising: SRD 5.1 itself ships **no** lair-action options for any monster
  (`grep -n -i "lair action" docs/reference/srd_5.1.txt` finds only the p.260 rule and
  shape-change exclusions), so the lair half is needed only for non-SRD content; the
  legendary half is needed by every SRD dragon, the lich, kraken, mummy lord, etc.
- **Evidence:** searches `grep -rniE "lair|initiative_count|count 20"` over `src/`,
  `web/routers`, `rules/`, `examples/` (py+json): no hits. `grep -rn legendary src/arena`:
  only the prompt line. Probe `.srd_work/probes/MON/probe_recharge_loader.py`:
  `legendary_actions.options / lair_actions / legendary_resistance: accepted silently`
  (the keys are ignored, see MON-D-07).
- **Gap:** RAW legendary creatures act between other creatures' turns, and lair creatures
  act on initiative 20 (losing ties).
- **Acceptance criteria:**
  1. In a match with a legendary creature, after each other creature's `end_turn` the
     driver asks the legendary creature's controller whether to use a legendary option
     (MON-D-01 window); declining is allowed.
  2. A creature JSON can declare `lair_actions`; a combat with one inserts a lair turn at
     initiative 20 that sorts after any creature that rolled 20, and the lair creature
     picks one option (not the same one two rounds running only if a content rule says
     so — that is per-monster text).
  3. Lair actions are refused while the creature is incapacitated.
- **Depends on / unblocks:** MON-D-01, and the reactions framework **TURN-M-01** — the
  shared dependency: both are decisions taken outside one's own turn, so one off-turn
  decision mechanism should serve reactions, opportunity attacks (MOVE-M-01) and
  legendary actions. Lair actions also need an initiative-20 entry that loses all ties (initiative
  tie-breaking is TURN-D-02). Unblocks every
  legendary SRD monster (dragons, lich, kraken…).
- **Tests pinning current behaviour:** none found.
- **Arena impact:** large — a new off-turn tool or decision request, observation of the
  remaining pool, menu enumeration for legendary options, heuristic support, and the
  prompt line at `interfaces.py:75-76` changes. Any study using a legendary creature
  becomes a new condition.
- **Known in:** ENGINE_MAP lead ("not exposed to agents"); interfaces.py prompt.
- **Size:** L — new turn phase + new tool/decision type; lair initiative entry is a
  separable S-M follow-up.

#### MON-M-03 — Model innate spellcasting (at will, X/day each, fixed level, no material)
- **Status:** open
- **Type / severity:** MISSING — S3
- **SRD:** p.258 "Innate Spellcasting" (above); "If a monster has a cantrip where its level
  matters and no level is given, use the monster's challenge rating." p.258
  "Spellcasting": "The spellcaster level is also used for any cantrips".
- **Current behaviour:** a creature has one flat `known_spells` list, one
  `spellcasting_ability`, and one slot table (`src/models/stat_block.py:54-60`). There is
  no per-spell frequency (at will / 3/day each / 1/day each), no per-list casting ability
  (some monsters have Innate Spellcasting *and* Spellcasting with different abilities),
  no "self only" restriction, no spellcaster level and no CR (MON-M-09) to drive cantrip
  scaling. The only way to author an innate caster today is `known_spells` with no
  `spell_slots`, which casts levelled spells without limit — that bug is **SPELL-D-17**
  (`src/combat/combat_system.py:403`, `:436`; `src/models/entity.py:77-78`). The MON-only
  addition: the same slotless caster also *upcasts* at will, because nothing bounds
  `slot_level` when there is no slot table.
- **Evidence:** `grep -rniE "innate|caster_level|character_level|per_day|/day"` over
  `src/`, `rules/`, `examples/` (py+json): only a docstring hit
  (`src/arena/action_space.py:317`, "innate + granted" meaning stat-block actions).
  `.srd_work/probes/MON/probe_innate.py` (creature with `known_spells: ["Fireball"]`, no
  slots):
  ```
  caster.spell_slots = None
  round 1: Fireball at slot level 3 -> damage [29]
  round 2: Fireball at slot level 9 -> damage [16]
  ...
  round 5: Fireball at slot level 9 -> damage [11]
  ```
  Arena asymmetry: the menu condition lists no slot levels for a slotless caster
  (`src/arena/action_space.py:303-307` returns `[]`), while the free-text/raw tools pass
  `slot_level` straight through (`src/arena/tools.py:491-497`).
- **Gap:** see SRD text.
- **Acceptance criteria:**
  1. A creature JSON can declare innate spells grouped by frequency; a "1/day" innate
     Fireball casts once at level 3 with no slot and is refused the second time.
  2. An innate spell cannot be cast at a higher `slot_level` (raises).
  3. An at-will innate spell casts every turn.
  4. A cantrip cast by a monster scales with its spellcaster level (or CR for innate) —
     shared with SPELL-M-04.
  5. A slotless creature's `resolve_spell(..., slot_level=9)` for a level-3 spell raises
     (with SPELL-D-17's fix, it raises for any levelled spell not declared innate).
- **Depends on / unblocks:** MON-M-02 (uses ledger), SPELL-D-17 (slotless casting),
  SPELL-M-04 (caster level / cantrip scaling), MON-M-09 (CR). Unblocks Drow, Deep Gnome,
  Djinni, Rakshasa, etc.
- **Tests pinning current behaviour:** none found.
- **Arena impact:** observation/menus must show uses left per innate spell.
- **Known in:** CODEBASE_REVIEW §4 item 7.
- **Size:** M — loader schema + uses ledger + cast-path check.

#### MON-M-07 — Load creature type and tags, and let effects test them
- **Status:** open
- **Type / severity:** MISSING — S3
- **SRD:** p.254 "Type": "Certain spells, magic items, class features, and other effects in
  the game interact in special ways with creatures of a particular type." p.255 "Tags".
- **Current behaviour:** no type/tag field anywhere (`StatBlock`, loader, expressions).
  Shipped spells whose RAW depends on type cannot honour it: Charm Person ("a humanoid")
  charms the construct golem (MON-M-06 probe) and Cure Wounds ("no effect on undead or
  constructs") heals it. **Silent.**
- **Evidence:** `.srd_work/probes/MON/probe_type_immunity.py`:
  ```
  Cure Wounds on Stone Golem (construct): HP 100 -> 113 healing = 13
  ```
  `grep -rniE "creature_type|humanoid|undead|construct"` over `src/`, `rules/`: no hits
  (only the two spells' `description` prose).
- **Gap:** a creature needs a type (one of the 14 SRD types) and optional tags; spells and
  traits need to filter/branch on it (target restriction "humanoid only", "no effect on
  undead or constructs", Turn Undead, Protection from Evil and Good, Hunter's Mark-style
  riders).
- **Acceptance criteria:**
  1. `type: "construct"` loads; an unknown type raises listing the 14 types.
  2. Cure Wounds on a construct or undead heals 0 (and says so in the log).
  3. Charm Person targeting a non-humanoid is refused (or has no effect — decide which,
     RAW says it targets "a humanoid", so refusal at targeting is the closer reading).
- **Depends on / unblocks:** an expression root or target filter for the target's type
  (sandbox stays a sandbox — expose a field, not code).
- **Tests pinning current behaviour:** check `tests/test_spells.py` Cure Wounds / Charm
  Person tests use type-less fixtures (they will still pass if untyped = "no
  restriction"; decide the default).
- **Arena impact:** menus/enumeration should not offer a humanoid-only spell against a
  construct; heuristic healing estimates.
- **Known in:** new.
- **Size:** S-M — field + loader + expression root + spell JSON updates.

#### MON-M-08 — Support grapple-on-hit monster attacks with an escape DC
- **Status:** open
- **Type / severity:** MISSING (partial) — S3
- **SRD:** p.259 "Grapple Rules for Monsters": "When a monster hits with such an attack, it
  doesn't need to make an additional ability check to determine whether the grapple
  succeeds" … "it must succeed on a Strength (Athletics) or Dexterity (Acrobatics) check
  against the escape DC in the monster's stat block. If no escape DC is given, assume the
  DC is 10 + the monster's Strength (Athletics) modifier."
- **Current behaviour:** the *apply* half works: a weapon `program` can run
  `apply_condition` for `grappled` (and `restrained`, for constrictor-style attacks) gated
  on `context.hit`. Everything after is missing: there is no escape-DC field (an
  `escape_dc` key on an attack is silently dropped, `src/loaders/stat_block_loader.py:297-317`),
  no escape action, no ability check to roll against it (COND-M-06), the condition does not
  record its grappler (`Condition.source` stays `''`), and `grappled` is a marker with no
  mechanics (`rules/entity_effects/conditions/grappled.json` `_note`), so nothing ends it
  when the grappler is incapacitated or moves away. A grappled target is therefore held
  until the condition's duration (none here → permanent). **Silent.**
- **Evidence:** `.srd_work/probes/MON/probe_grapple_attack.py`:
  ```
  escape_dc key: accepted and dropped (no field on AttackAction)
  hit/damage: (True, 4)
  target conditions: ['GRAPPLED', 'RESTRAINED']
  grappler recorded on the condition? source=''
  after grappler at 0 HP and a turn passes: ['GRAPPLED', 'RESTRAINED']
  ```
- **Gap:** monster grapples skip the contest (correct today) but need an escape DC, a
  grappler reference and an escape action that rolls Athletics/Acrobatics against it.
- **Acceptance criteria:**
  1. An attack declaring "grapple on hit, escape DC 13" applies grappled with the grappler
     recorded and no contest roll.
  2. The grappled creature's escape action rolls max(Athletics, Acrobatics) (or the
     chosen one) vs 13; success removes grappled (and the attack's restrained rider).
  3. No escape DC given → DC = 10 + the monster's Athletics modifier.
  4. The grapple ends when the grappler is incapacitated (COND-M-05).
- **Depends on / unblocks:** **ATK-M-08** (the player-side grapple/escape machinery — build
  one escape path for both), COND-M-06 (checks), COND-M-05. Unblocks Giant Constrictor
  Snake, Giant Octopus, Mimic, Roper, Kraken, many beasts.
- **Tests pinning current behaviour:** none found.
- **Arena impact:** an "escape" action needs a tool/menu entry; observation should show
  grappled-by.
- **Known in:** `grappled.json` `_note`; new for the escape DC.
- **Size:** M on top of ATK-M-08 — an `escape_dc` on the attack/condition and the grappler
  reference.

#### MON-M-09 — Load challenge rating and derive proficiency bonus from it
- **Status:** open
- **Type / severity:** MISSING (partial) — S3
- **SRD:** p.256 "Saving Throws": proficiency bonus "is determined by the monster's
  challenge rating (as shown in the Proficiency Bonus by Challenge Rating table)"; p.258
  "Challenge" (and XP by CR); p.258 innate cantrips scale by CR.
- **Current behaviour:** `proficiency_bonus` is hand-authored and **silently defaults to 2**
  when omitted (`src/loaders/stat_block_loader.py:170`); there is no CR field. A CR 17
  monster written without the key gets +2 on its proficient saves and its spell DC
  (`src/models/stat_block.py:86-91`, `Entity.spell_save_dc`). The shipped stone golem
  shows the drift risk: it is CR 10 in the SRD (p.317) → +4, but the JSON says
  `"proficiency_bonus": 5` (no effect today, since it has no save proficiencies or spells).
- **Evidence:** `grep -rniE "challenge|\bcr\b"` over `src/`, `rules/`, `examples/` (py+json):
  no hits. Probe `probe_recharge_loader.py`: `challenge_rating=5` accepted and dropped.
- **Gap:** PB should follow the CR table (or a mismatch should be refused); CR is also what
  innate cantrips scale with (MON-M-03) and what an encounter budget would use.
- **Acceptance criteria:**
  1. `challenge_rating: "10"` with no `proficiency_bonus` → PB 4; `"1/4"` → 2; `"17"` → 6;
     `"30"` → 9 (full p.256 table).
  2. `challenge_rating: "10"` with `proficiency_bonus: 5` → load error naming the expected
     value (or an explicit override flag, if the project wants one).
  3. A creature with neither CR nor PB → load error (not a silent 2); player characters
     keep an explicit PB (or a level, per SPELL-M-04).
- **Depends on / unblocks:** MON-D-07. Unblocks MON-M-03 criterion 4.
- **Tests pinning current behaviour:** many fixtures build `StatBlock` without PB and rely
  on the dataclass default 2 (`src/models/stat_block.py:46`); keep the dataclass default and
  enforce at the loader only.
- **Arena impact:** none (scenarios set PB in Python).
- **Known in:** new (CODEBASE_REVIEW §4 item 8 is about attack bonuses, see ATK-M-05).
- **Size:** S — loader field + table.

#### MON-M-10 — Make Legendary Resistance expressible ("choose to succeed instead")
- **Status:** open
- **Type / severity:** MISSING — S3
- **SRD:** trait in legendary stat blocks, e.g. p.287 Adult Red Dragon: "Legendary
  Resistance (3/Day). If the dragon fails a saving throw, it can choose to succeed
  instead."
- **Current behaviour:** cannot be authored. The only save hook is `SAVING_THROW_DECLARED`,
  emitted *before* the roll with `defender, ability, dc` (`src/spells/blocks/rolls.py:148-162`);
  the result is computed in `roll_saving_throw` (`src/utils/saving_throw.py:34-47`) and
  written straight into `context.save_success` with no post-roll event a rule could
  override. There is no per-day counter (MON-M-02), no trait data path (MON-M-04), and no
  way for the creature's controller to *choose* (an off-turn decision, as in MON-M-01).
- **Evidence:** code reading above; `grep -rniE "legendary_resist"` over `src/ rules/
  examples/`: no hits; the `legendary_resistance` key is silently dropped (probe
  `probe_recharge_loader.py`).
- **Gap:** a post-roll save event (failed save → may be turned into a success) plus a
  3/Day counter and a choice policy.
- **Acceptance criteria:**
  1. A creature with Legendary Resistance 3/Day fails a save; with "use" chosen, the
     outcome becomes success, the counter drops to 2, and the spell's success branch runs
     (e.g. half damage, no condition).
  2. The fourth failure in the same combat stays a failure.
  3. A "decline" choice leaves the failure in place and the counter unchanged.
- **Depends on / unblocks:** MON-M-02 (uses), MON-M-04 (traits), a `SAVING_THROW_ROLLED`-style
  event (also useful for Bardic-Inspiration/Lucky-style rerolls), and a decision hook
  for the controller (MON-M-01 / TURN-M-01's off-turn decision mechanism). Unblocks every
  legendary SRD monster.
- **Tests pinning current behaviour:** none found.
- **Arena impact:** a new decision for the agent controlling the creature, or a fixed
  policy (e.g. "always use against a disabling effect") the study must declare.
- **Known in:** new.
- **Size:** M — event + counter + decision policy.

#### MON-M-11 — Let a creature declare its hit dice (average or rolled HP)
- **Status:** open
- **Type / severity:** MISSING (partial) — S4
- **SRD:** p.255-256 "Hit Points": "A monster's hit points are presented both as a die
  expression and as an average number"; Hit Dice by Size table; CON modifier × Hit Dice.
- **Current behaviour:** HP is a flat integer (`hit_points_max` / `hit_points`,
  `src/loaders/stat_block_loader.py:164`); `StatBlock` has no hit-dice field. Using the
  average is RAW-compatible, so nothing is wrong today; rolling HP per creature (the
  SRD's other option, useful for varied goblin packs) is not possible, and an author's
  HP is not cross-checked against size/CON.
- **Evidence:** no `hit_dice` key in the loader/model (`grep -rn "hit_dice" src`: none).
- **Gap:** optional `hit_dice: "2d6"`; HP = average unless the combat asks for rolled HP
  (through the seeded RNG).
- **Acceptance criteria:**
  1. `hit_dice: "17d10+85"` with no HP → `hit_points_max == 178`.
  2. With a "roll HP" option and a seed, each entity gets a reproducible rolled HP within
     [17+85, 170+85].
  3. A die that does not match the size (d8 on a Large) → load warning or error, per the
     project's choice.
- **Depends on / unblocks:** none.
- **Tests pinning current behaviour:** none.
- **Arena impact:** none unless a scenario opts into rolled HP (it would change seeds'
  meaning).
- **Known in:** new.
- **Size:** S.

#### MON-M-12 — Narrative stat-block fields (alignment, languages, telepathy, XP)
- **Status:** open
- **Type / severity:** MISSING — S4
- **SRD:** p.255 "Alignment"; p.257 "Languages", "Telepathy"; p.258 "Experience Points".
- **Current behaviour:** none of these exist; their keys are silently dropped (MON-D-07).
  None affects combat resolution in the engine's scope (telepathy and languages matter
  only for communication; alignment only for a few spells such as detect/protection
  effects keyed to type, not alignment, in 5.1).
- **Evidence:** `grep -rniE "alignment|language|telepath|\bxp\b"` over `src/ rules/
  examples/` (py+json): no hits.
- **Gap / Acceptance criteria:** once MON-D-07 makes keys strict, accept these as inert,
  documented descriptive fields so SRD transcriptions load; no mechanics required.
- **Depends on / unblocks:** MON-D-07.
- **Tests pinning current behaviour:** none. **Arena impact:** none (could feed an
  observation's flavour text). **Known in:** new. **Size:** S.

## 4. Deviations and inaccuracies

### TURN — Turn structure and action economy (SRD pp.84, 87, 90–94)

#### TURN-D-01 — Give incapacitated creatures their turn instead of skipping it
- **Status:** open
- **Type / severity:** DEVIATION — S1
- **SRD:** p.90 "The Order of Combat": "During a round, each participant in a battle takes a turn." Appendix PH-A "Incapacitated": "An incapacitated creature can't take actions or reactions." (moving is not forbidden; stunned/paralyzed/petrified/unconscious add "can't move" separately). p.90 "Your Turn": "You can forgo moving, taking an action, or doing anything at all on your turn."
- **Current behaviour:** `src/combat/turn_manager.py:14-27` (`_SKIP_CONDITIONS` = unconscious, incapacitated, paralyzed, stunned, petrified) and `:115-134` advance past such a creature without emitting `TURN_START` or `TURN_END` for it. Every per-turn mechanism keyed to those events is therefore frozen for that creature, **silently**:
  - durations: a non-concentration lifetime belongs to its target and ticks only on the target's `TURN_END` (`src/spells/blocks/lifetime.py:65-67`, `src/spells/blocks/state.py:125-135`, `src/combat/lifetime_clock.py`, `Entity.tick_lifetimes` `src/models/entity.py:341`). So `apply_condition` of a skip-condition with `duration: N` never expires;
  - "repeat the save at the end of each of its turns" riders (a `TURN_END` trigger on the holder) can never fire for the paralyzed/stunned holder;
  - start-of-turn riders (`TURN_START`: resource refill `rules/global/action_economy_refill.json`, legendary-action refill (MON-D-06), Haste/Longstrider top-ups, recharge rolls (MON-M-02), any "takes N damage at the start of its turn", and future death saves (ATK-M-10)) never fire;
  - a creature that is *only* incapacitated loses its movement, which RAW does not take away.
- **Evidence:** `.srd_work/probes/TURN/p01_skip_freezes_duration.py` — `stunned` duration 1 vs `poisoned` duration 1, 9 `end_turn`s (4+ rounds):
  ```
  order: ['A', 'C', 'B']
  turn starts over 9 end_turns: ['C', 'A', 'C', 'A', 'C', 'A', 'C', 'A', 'C']
  round: 5
  B conditions (stunned, duration=1): ['STUNNED']
  C conditions (poisoned, duration=1): []
  ```
  COND's probe `.srd_work/probes/COND/skipped_turn_duration.py` confirms it per condition:
  ```
  blinded      duration=1, after 5 rounds (round now 6): []; TURN_END events for B: 6
  stunned      duration=1, after 5 rounds (round now 6): ['stunned']; TURN_END events for B: 1
  paralyzed    duration=1, after 5 rounds (round now 6): ['paralyzed']; TURN_END events for B: 1
  ```
  `.srd_work/probes/TURN/p02_incapacitated_loses_move.py` — plain `incapacitated`:
  ```
  B conditions: ['INCAPACITATED']
  TURN_START after A's end_turn: ['A'] | current: A | round: 2
  B move refused: not_your_turn - It is not B's turn (active: A)
  ```
  No shipped spell applies a skip-condition yet (only Charm Person uses `apply_condition`), so today's content does not reach it; any stun/paralysis/sleep content would.
- **Gap:** RAW every participant takes a turn; the conditions restrict *what* can be done in it (no actions, bonus actions or reactions; no movement only for the conditions that say so). Turn boundaries, and everything hung on them, still happen.
- **Acceptance criteria:**
  1. A creature with `stunned` applied with `duration: 1` loses it at the end of its next turn (same as the `poisoned` control in p01).
  2. Each `end_turn` that reaches an incapacitated creature emits `TURN_START` and then (after its turn ends) `TURN_END` with that creature as `entity`; a `TURN_END` save rider on it fires.
  3. On its turn an `incapacitated`-only creature can `move_entity` (speed intact) but `resolve_attack`/`resolve_spell` are refused with a specific code; a `stunned`/`paralyzed`/`petrified`/`unconscious` creature's moves are refused too (can't move).
  4. The arena turn driver handles such a turn without asking an LLM for a decision it cannot make (or offers only `move`/`end_turn`), and the all-incapacitated guard (`turn_manager.py:121-122`) is replaced by something that still terminates (TURN-Q-02).
- **Depends on / unblocks:** COND-M-05 (the single "is incapacitated" predicate every action path checks — the enforcement point that replaces the skip) and a can't-move mechanism (MOVE-M-05's speed-0 shape). Unblocks MON-D-06 (fixing this fixes it), Hold Person–style "save at end of each turn", Sleep, stun durations, ATK-M-10 death saves at turn start. SPELL-D-11 (how a duration counts rounds) is separate but touches the same clock.
- **Tests pinning current behaviour:** none found (no test asserts a skipped turn; `tests/arena/test_turn_driver.py::test_dead_actor_turn_is_skipped` is about 0 HP, ATK-D-01).
- **Arena impact:** `turn_driver.run_turn` would start receiving turns for incapacitated creatures; it must auto-end or restrict them. Observation should show the condition. Menus (`action_space.legal_actions`) must drop actions for such a creature.
- **Known in:** COND retired its own skipped-turn duration entry in favour of this one (COND-M-05 cites it); MON-D-06; CODEBASE_REVIEW §2 describes the "condition-based skip" as design, not as a deviation; ENGINE_MAP lead.
- **Size:** M — remove the skip in `TurnManager`; route action denial through COND-M-05 and a can't-move rule for the conditions that say so; adapt the arena driver.

#### TURN-D-02 — Break exact initiative ties by roll-off, not insertion order
- **Status:** open
- **Type / severity:** DEVIATION — S3
- **SRD:** p.90 "Initiative": "If a tie occurs, the GM decides the order among tied GM-controlled creatures, and the players decide the order among their tied characters. … Optionally, the GM can have the tied characters and monsters each roll a d20 to determine the order, highest roll going first."
- **Current behaviour:** `InitiativeEntry.__lt__` (`src/combat/initiative.py:22-29`) breaks a tie on DEX modifier, and an equal DEX modifier falls through to Python's stable sort — the order creatures were added (`add_combatant`). Deterministic, silent. In the arena every scenario adds team `a` first (`src/arena/scenarios.py:129-200`), gives every creature the same abilities (`_ABILITIES`, DEX 14), and `_reroll_initiative` re-adds in combatant order (`src/arena/match.py:50-62`), so **team `a` wins every exact tie** — and team `a` is the LLM's side in every scenario (`llm_team="a"`).
- **Evidence:** `.srd_work/probes/TURN/p04_initiative_ties.py` (alpha_strike, seeds 0–1999, cross-team ties between adjacent slots):
  ```
  cross-team exact ties won, by team: {'a': 355}
  ```
- **Gap:** RAW leaves ties to the GM / players, with a d20 roll-off as the SRD's own option. The user has already chosen roll-off for the engine: "if a tie occurs, just roll-off until it's resolved" (`docs/current/ENTITY_LIFECYCLE_DECISIONS.md` C1, "Your answer", written for summons' ties). The DEX-modifier tiebreak is not SRD text (common table practice); the insertion-order fallback is neither, and is a side bias.
- **Acceptance criteria:**
  1. Two creatures with equal initiative total and equal DEX: across seeds, each goes first about half the time, with no dependence on `add_combatant` order.
  2. The roll-off goes through `dice` (replays stay bit-identical) and repeats until the tie breaks.
  3. Whether the DEX-modifier step stays before the roll-off is decided and pinned by a test that says which ruling it encodes.
- **Depends on / unblocks:** none. Should land before any study reads side bias.
- **Tests pinning current behaviour:** none found asserting tie order (`grep -rn initiative tests/` → only `initiative_modifier=100` setups in `tests/rules/entity_effects/conditions/test_blinded.py`).
- **Arena impact:** changes turn order (and so outcomes) for seeded matches with ties; recorded study bundles would not replay identically under the new code (`study verify`), so version the change. Removes a small systematic advantage for team `a` (the LLM side).
- **Known in:** new (the user's tie ruling is in ENTITY_LIFECYCLE_DECISIONS C1).
- **Size:** S — a tie-break roll stored on `InitiativeEntry`.

### MOVE — Movement and position (SRD pp.84–86, 91–92, 95, 99)

#### MOVE-D-01 — Refuse a move whose path crosses a hostile creature's space
- **Status:** open
- **Type / severity:** DEVIATION — S1
- **SRD:** p.92 "Moving Around Other Creatures": "you can move through a hostile
  creature's space only if the creature is at least two sizes larger or smaller than you."
- **Current behaviour:** `move_entity` (`src/combat/combat_system.py:688-757`) treats a
  move as a straight segment and validates only its **destination**
  (`_check_movement_overlap`, `:811-837`, called at `:752`). The path is never examined,
  so a creature walks straight through any enemy, of any size, **silently**. The arena
  menus are built from the same occupancy test (`is_destination_clear`, `:785-809`;
  `src/arena/action_space.py:_clear_option_along` and `move_candidates` `:365-436`), so
  they offer retreat/kite destinations that are only reachable by passing through a foe.
  `CreatureSize` (`src/models/creature_size.py`) has no ordinal, so "two sizes larger or
  smaller" is not even computable today.
- **Evidence:** `.srd_work/probes/MOVE/p01_through_hostile.py`:
  `before: 0.0 movement 30` / `after: 20.0 movement 10.0 -> passed through a same-size
  hostile; charged plain 20 ft, no difficult terrain` (Medium mover from x=0 to x=20
  across a Medium hostile centred at x=10).
- **Gap:** RAW forbids entering a hostile's space unless the size difference is ≥ 2
  categories; the space of a nonhostile creature may be crossed (as difficult terrain,
  see MOVE-M-02). Ending in any creature's space stays forbidden (already enforced).
- **Acceptance criteria:**
  1. Medium A at x=0, Medium hostile B at x=10 (z=0): `move_entity(A, 20, 0, 0)` raises
     `RuleViolation(DESTINATION_BLOCKED)` naming B; A's position and movement unchanged.
  2. Same, but B is Huge (two sizes larger) → the move succeeds (and the cost includes
     the difficult-terrain surcharge for the stretch inside B's space, MOVE-M-02).
  3. Same, but B is an ally → the move succeeds.
  4. A move that passes alongside B without entering its space (touching only, A29
     strict-overlap semantics) succeeds.
- **Depends on / unblocks:** needs a size ordering on `CreatureSize`; a swept-footprint
  (capsule/box sweep) vs AABB intersection in `src/spatial/`. Unblocks MOVE-M-02 (cost of
  crossing allies) and MOVE-M-01 (a path is also what decides *where* a creature leaves
  reach). Arena `move_candidates` must use the same path test.
- **Tests pinning current behaviour:** none assert passing-through directly;
  `tests/arena/test_action_space.py::test_move_candidates_are_all_legal` and
  `tests/arena/test_heuristic_plan.py::test_every_move_used_is_a_legal_candidate` will
  start exercising the new rule (they should keep passing if menus use the path test).
- **Arena impact:** large. `move_candidates` (retreat/kite/toward lines) must drop or
  re-route options that cross a foe; registered menu-coverage figures (PREREGISTRATION
  §9/§10) would change; the heuristic's retreat plans (`heuristic/plan.py`) get fewer
  legal options; kiting/protect_squishy scenarios get harder to escape, as A30 notes.
  Prompt text "You cannot move onto another creature" (`interfaces.py:71`) needs a
  "nor through an enemy" clause.
- **Known in:** CODEBASE_REVIEW A30 (open, accepted for the study; PREREGISTRATION
  §9/§10). This entry is its single home in the fidelity doc.
- **Size:** M — a path-sweep occupancy check in `src/spatial/`, a size ordinal, and
  menu regeneration; decide straight-line-only vs waypoint moves (a refused straight
  line could be split by the mover into two legs, which RAW allows).

#### MOVE-D-02 — Stop micro-steps from moving farther than the movement they are charged
- **Status:** open
- **Type / severity:** DEVIATION — S3
- **SRD:** p.91 "Movement and Position": "you deduct the distance of each part of your move
  from your speed until it is used up".
- **Current behaviour:** each move is charged `round(distance, FEET_DP)` with `FEET_DP =
  1` (`combat_system.py:728`, `action_resources.py:18`), i.e. rounded *to nearest* per
  segment. Any segment of length in [0.05, 0.15) ft is charged 0.1 ft, so repeated
  0.149-ft moves travel ~1.49× the speed. **Silent.** (Segments < 0.05 ft are refused as
  `NO_EFFECT`, ledger A31.) Practical reach is small in the arena (`MAX_ACTIONS_PER_TURN
  = 20`, `src/arena/turn_driver.py:36`), but the engine/web path has no cap.
- **Evidence:** `.srd_work/probes/MOVE/p02_micro_steps.py`: `speed 30 ft; 300 moves of
  0.149 ft; travelled 44.70 ft; movement left 0.0`.
- **Gap:** the sum of distances actually travelled in a turn must never exceed the
  movement available.
- **Acceptance criteria:**
  1. Speed 30: 300 successive moves of 0.149 ft cannot all succeed; total distance
     travelled ≤ 30.0 ft (± 0.1 display rounding).
  2. A single 5-ft diagonal still costs 7.1 ft (keep
     `test_move_cost_is_continuous_not_rounded_to_a_grid`).
  3. 30 − 7.1 − 7.1 still reads 15.8 exactly (keep the float-drift test).
- **Depends on / unblocks:** none. Shape options: charge the ceiling to 0.1 ft, or track
  exact distance moved and display rounded.
- **Tests pinning current behaviour:** `tests/test_movement.py::TestMoveEntity::
  test_a_move_too_short_to_cost_anything_is_refused` (0.04 ft → `NO_EFFECT`; with a
  ceiling charge it would instead cost 0.1 — the A31 semantics need restating) and
  `test_the_shortest_chargeable_move_is_allowed`.
- **Arena impact:** none material (menus move whole feet); keep `movement_remaining`
  display at 0.1 ft.
- **Known in:** new.
- **Size:** S — the charge function.

#### MOVE-D-03 — Treat an unconscious (or otherwise non-"alive") creature's space as occupied
- **Status:** open
- **Type / severity:** DEVIATION — S3
- **SRD:** p.92 "Moving Around Other Creatures": "Whether a creature is a friend or an
  enemy, you can't willingly end your move in its space." (No exception for an
  unconscious or incapacitated creature.)
- **Current behaviour:** occupancy iterates `get_alive_entities()`
  (`combat_system.py:648-650`, used at `:803` and `:831`), and `Entity.is_alive()`
  (`src/models/entity.py:144-149`) is False for any creature with the UNCONSCIOUS
  condition, even at full HP. So a sleeping creature's space is free: a mover can end its
  move exactly on top of it (**silent**), and the two then overlap when it wakes. No
  shipped spell applies unconscious today (Sleep isn't shipped), but `apply_condition`
  accepts it.
- **Evidence:** `.srd_work/probes/MOVE/p03_unconscious_space.py`: `sleeper hp: 30
  is_alive(): False` / `destination clear on sleeper's centre: True` / `mover ended its
  move at 10.0 == sleeper at 10.0 -> ended a willing move inside another creature's
  space`.
- **Gap:** every creature still on the battlefield occupies its space for the end-of-move
  rule, whatever its conditions; whether a 0-HP/dead body does is MOVE-Q-03.
- **Acceptance criteria:**
  1. Creature B at x=10 with 30 HP and UNCONSCIOUS: `move_entity(A, 10, 0, 0)` raises
     `DESTINATION_BLOCKED`; `is_destination_clear` is False.
  2. B paralyzed/stunned/petrified (also non-acting) → same.
  3. Corpse behaviour follows MOVE-Q-03 (today `test_dead_entity_does_not_block_movement`).
- **Depends on / unblocks:** separating "on the battlefield" from "able to act"
  (`is_alive` conflates them; the same conflation drives AoE targeting and turn skipping —
  see Cross-area notes). ENTITY_LIFECYCLE_DECISIONS "downed but present".
- **Tests pinning current behaviour:** `tests/test_movement.py::TestMoveEntity::
  test_dead_entity_does_not_block_movement` (0 HP corpse — fine to keep, pending MOVE-Q-03).
- **Arena impact:** menus share `is_destination_clear`, so they follow; no scenario applies
  unconscious today.
- **Known in:** new.
- **Size:** S — an occupancy roster that includes present-but-incapacitated creatures.

#### MOVE-D-04 — Reject an unknown creature size instead of loading it as Medium
- **Status:** open
- **Type / severity:** DEVIATION — S3
- **SRD:** p.92 "Creature Size": the Size Categories table (Tiny 2½ by 2½ ft ...
  Gargantuan 20 by 20 ft or larger).
- **Current behaviour:** `StatBlockLoader.from_dict` maps a size string through
  `CreatureSize[size_str.upper()]` and on `KeyError` silently falls back to MEDIUM
  (`src/loaders/stat_block_loader.py:156-161`). A typo (`"Lrage"`) gives a Large monster
  a 5-ft space: wrong occupancy, reach-edge distances and AoE footprint, **silently**.
  This contradicts CLAUDE.md §2.5 ("Enum/format errors must name the bad value and the
  valid set", `_enum_lookup` exists in the same file, `:44`).
- **Evidence:** `.srd_work/probes/MOVE/p06_air_and_size.py`: `size 'Lrage' loaded as:
  CreatureSize.MEDIUM (no error)`.
- **Gap:** an unknown size must fail at load naming the value and the six valid sizes.
- **Acceptance criteria:**
  1. `from_dict({"size": "Lrage", ...})` raises `ValueError` whose message contains
     `Lrage` and `gargantuan`.
  2. Missing `size` still defaults to Medium; `"LARGE"`/`"large"` both load Large.
- **Depends on / unblocks:** none.
- **Tests pinning current behaviour:** none found asserting the fallback (grep
  `CreatureSize.MEDIUM` in loader tests before changing).
- **Arena impact:** none (scenarios construct `StatBlock` directly).
- **Known in:** new.
- **Size:** S — use `_enum_lookup`.

### ATK — Attacks, weapons, armor, damage and hit points (SRD pp.62–66, 94–98)

#### ATK-D-01 — Make a creature at 0 HP unconscious, and stop the referee letting it act
- **Status:** open
- **Type / severity:** DEVIATION — S2
- **SRD:** p.97 "Dropping to 0 Hit Points": "When you drop to 0 hit points, you either die outright or fall unconscious". p.98 "Falling Unconscious": "If damage reduces you to 0 hit points and fails to kill you, you fall unconscious… This unconsciousness ends if you regain any hit points." p.96 "Hit Points": "The loss of hit points has no effect on a creature's capabilities until the creature drops to 0 hit points."
- **Current behaviour:** Reaching 0 HP is recorded only as `current_hp == 0`. `Entity.take_damage` floors at 0 (`src/models/entity.py:99-111`). `DamageProcessor` emits `ENTITY_DIES` when `is_alive()` flips (`src/combat/damage_processor.py:32,57-61`). No condition is applied: neither unconscious nor dead. The referee does not act on 0 HP either:
  - `TurnManager` skips only creatures with a `_SKIP_CONDITIONS` condition (`src/combat/turn_manager.py:14-27,76`), so a 0-HP creature still gets `TURN_START` (resources refill) and `TURN_END`.
  - `CombatSystem.resolve_attack`/`resolve_spell` check only that it is the creature's turn (`_assert_active`, `src/combat/combat_system.py:631-646`), so a 0-HP creature can attack and cast through the engine API.

  This is **silent**. Only the arena guards it (`src/arena/turn_driver.py:75`, "a downed creature takes no turn"). The web layer and any direct library caller do not. The model also runs the other way: `Entity.is_alive()` returns False for any `UNCONSCIOUS` creature at full HP (`entity.py:144-149`). So a creature put to sleep counts as down for `sides_standing` (combat can end on it, `turn_manager.py:30-43`), and if it is then damaged to 0, no `ENTITY_DIES` fires, because `was_alive` was already False.
- **Evidence:** `.srd_work/probes/ATK/p04_zero_hp.py` (real `CombatSystem` + `rules/global`):
  ```
  18 dmg to 6/12 HP victim: hit=True dmg=18 hp=0 alive=False conditions=[] deaths=['Victim']
  0-HP creature attacks on its turn: (True, 4) T hp 46
  0-HP creature has UNCONSCIOUS condition? False
  ```
- **Gap:** RAW: at 0 HP a creature is either dead or unconscious (the unconscious condition: incapacitated, can't move or speak, drops what it holds, falls prone, auto-fails STR/DEX saves, attacks against it have advantage, hits within 5 ft are crits). Either way it takes no actions. Being unconscious at positive HP (sleep) is not being down for good.
- **Acceptance criteria:**
  1. Damage that reduces a creature to 0 HP and does not kill it (ATK-M-10, ATK-Q-01) gives it the `UNCONSCIOUS` condition through the same path as `apply_condition`, so the condition's rule is installed.
  2. A 0-HP creature's `resolve_attack`/`resolve_spell` call is refused with a specific code, in the engine, not only in the arena turn driver.
  3. Healing a 0-HP unconscious (not dead) creature removes the unconsciousness that 0 HP caused.
  4. A creature made unconscious by an effect at positive HP is not "dead". `ENTITY_DIES` fires if damage then takes it to 0 and it dies (whichever death rule ATK-Q-01 picks), and `sides_standing` tells "out of the fight" apart from "dead" as decided there.
- **Depends on / unblocks:** ATK-Q-01 (who dies outright), ATK-M-10 (dying), the unconscious condition rule (COND). Unblocks paralyzed/unconscious auto-crits being meaningful against downed PCs.
- **Tests pinning current behaviour:** `tests/arena/test_turn_driver.py:147,303` (a 0-HP creature is skipped by the driver; keep). `tests/test_aoe_casting.py::test_dead_entities_not_targeted` and `tests/test_movement.py` (`corpse.current_hp = 0`) treat 0 HP as dead; they stay valid for monsters under ATK-Q-01. Any test relying on `is_alive()` being False for a sleeping creature needs revisiting.
- **Arena impact:** `observation.py` reports `alive` from `is_alive()`. `sides_standing` decides match end, and the study's win/loss metrics read it. A dying-but-not-dead state changes when a match ends; ATK-Q-01 should decide this for the arena explicitly (e.g. all arena creatures follow "Monsters and Death").
- **Known in:** CODEBASE_REVIEW §4 item 5 ("`is_alive()` is binary at 0 HP"); ENGINE_MAP lead. The engine-API hole (0-HP creature can act) and the sleep/`ENTITY_DIES` interaction are new.
- **Size:** M. A 0-HP state transition in `DamageProcessor`, an engine-side "can act" guard, and an `is_alive` split into "dead" and "incapacitated/down".

#### ATK-D-02 — Refuse healing to a creature that has died
- **Status:** open
- **Type / severity:** DEVIATION — S2
- **SRD:** p.97 "Healing": "A creature that has died can't regain hit points until magic such as the revivify spell has restored it to life."
- **Current behaviour:** `Entity.heal` adds HP with no state check (`src/models/entity.py:113-116`). The `healing` block calls it for any target (`src/spells/blocks/healing.py:51-54`). `resolve_spell` range-checks single targets but never checks that they are alive (`src/combat/combat_system.py:425-434`). A 0-HP creature that has had `ENTITY_DIES` emitted is therefore restored by Cure Wounds and is back in the fight (`is_alive()` True). This is **silent**. AoE spells do skip 0-HP creatures (`get_targets_in_aoe` uses alive entities; `tests/test_aoe_casting.py::test_dead_entities_not_targeted`), and the arena menus offer only living targets (`src/arena/action_space.py:259,284`). The `cast_spell` tool's free id lookup (`src/arena/tools.py:404-427`), the web layer and the engine API do not.
- **Evidence:** `.srd_work/probes/ATK/p04_zero_hp.py` (seeded):
  ```
  18 dmg to 6/12 HP victim: … hp=0 alive=False … deaths=['Victim']
  Cure Wounds on 0-HP victim: hp=11 alive=True result=(True, 11)
  ```
- **Gap:** after `ENTITY_DIES`, a dead creature must not regain HP until it is raised. A dying (PC-rules) creature *may* be healed, which is RAW and is how it gets back up. The engine cannot tell the two apart today (ATK-Q-01).
- **Acceptance criteria:**
  1. A creature that died (dies-at-zero creature at 0 HP, or a PC-rules creature after three failures or instant death) targeted by Cure Wounds → refused with a specific code, or a no-op recorded as `healing=0`. The ruling picks which, and HP stays 0.
  2. A dying PC-rules creature targeted by Cure Wounds → regains HP (and ATK-D-01 criterion 3 applies).
  3. Single-target damage spells and weapon attacks against a dead creature are refused, or explicitly allowed as attacks on an object/corpse; the ruling picks which.
- **Depends on / unblocks:** ATK-Q-01, ATK-D-01 (a dead state).
- **Tests pinning current behaviour:** none found that heal a 0-HP creature.
- **Arena impact:** `tools.py` `_cast_spell`/`_attack` would surface the new refusal code to models. Menus already exclude dead targets.
- **Known in:** ENGINE_MAP lead ("Healing a 0-HP creature?"); new as a finding.
- **Size:** S once a dead state exists.

#### ATK-D-03 — Count multiple resistances once, and apply resistance after all other damage modifiers, then vulnerability
- **Status:** open
- **Type / severity:** DEVIATION — S3
- **SRD:** p.97 "Damage Resistance and Vulnerability": "Resistance and then vulnerability are applied after all other modifiers to damage." "Multiple instances of resistance or vulnerability that affect the same damage type count as only one instance."
- **Current behaviour:** Resistance, immunity and vulnerability are independent `DAMAGE_INCOMING` triggers, each multiplying the live amounts with `int()` truncation (`src/spells/blocks/event_mod.py:38-57`). The stat-block rules are `rules/global/damage_{immunity,resistance,vulnerability}_rule.json`, all at priority 0. Any other effect granting resistance is another such trigger: `rules/entity_effects/conditions/petrified.json:14-20` (`modify_damage` ×0.5). So:
  - two sources of resistance to one type multiply (×0.25);
  - the order is subscription order. The stat-block rules are installed in filename sort order (`src/spells/rules.py:50-58`), which happens to give resistance before vulnerability. Petrified is installed later, so its halving runs *after* the stat-block doubling.

  There is no damage-modifier stage before resistance: no flat-reduction block, and no priority band reserved for "other modifiers". This is **silent**.
- **Evidence:** `.srd_work/probes/ATK/p06_resist_vuln.py` (real `CombatSystem`, `rules/global`, petrified applied via `apply_condition`):
  ```
  resist+vuln fire, 25 -> 24 (SRD halve then double: 24)
  petrified alone, 25 -> 12 (SRD 12)
  petrified + resist fire, 25 -> 6 (SRD: instances count once -> 12)
  petrified + vuln fire, 25 -> 25 (SRD resist then vuln -> 24)
  ```
- **Gap:** RAW applies to each damage type, in order: (1) all other modifiers, then (2) at most one halving (any number of resistances), then (3) at most one doubling, with immunity as 0. The result must not depend on which rule happened to subscribe first.
- **Acceptance criteria:**
  1. A creature resistant to fire *and* petrified takes 12 from 25 fire, not 6.
  2. A creature vulnerable to fire *and* petrified takes 24 from 25 fire (halve, round down, then double), not 25.
  3. A −5 flat reduction (any future modifier) plus resistance on 25 bludgeoning → 10 (SRD's own example).
  4. Renaming or reordering the rule files does not change any of these results.
- **Depends on / unblocks:** composite / per-type modifier design (`docs/current/COMPOSITE_DAMAGE_DESIGN.md`), which proposes resolving modifiers per component. This entry adds the stacking and ordering requirements to that design. Unblocks resistance-granting content (Stoneskin, rage-like features, "resistance to all damage").
- **Tests pinning current behaviour:** `tests/rules/entity_effects/conditions/test_petrified.py::TestPetrifiedDamageResistance` (the halving alone is correct and stays). `tests/test_damage_modifiers.py`, `tests/test_global_rules_via_blocks.py` (single-source cases stay).
- **Arena impact:** `src/arena/heuristic/estimate.py:111-126` (`damage_multiplier`) returns 0.5 for resist+vuln on the same type, where the engine and RAW give ≈1.0. Align it with the engine resolver when this is fixed.
- **Known in:** `COMPOSITE_DAMAGE_DESIGN.md` (per-type scope, `damage_list[0]` gating). The stacking and ordering defects are new.
- **Size:** M. Replace the three multiplier triggers with one modifier-resolution step that gathers resistance/immunity/vulnerability *sources* (stat block plus effects) per type and applies them once, in RAW order, after an explicit pre-resistance modifier stage.

#### ATK-D-04 — Stop a temp-HP grant's expiry from deleting or restoring other temp HP
- **Status:** open
- **Type / severity:** DEVIATION — S3
- **SRD:** p.98 "Temporary Hit Points": "they can't be added together. If you have temporary hit points and receive more of them, you decide whether to keep the ones you have or to gain the new ones. For example, if a spell grants you 12 temporary hit points when you already have 10, you can have 12 or 10, not 22."
- **Current behaviour:** `Entity.add_temporary_hp` keeps `max(current, new)` (correct, and a reasonable automatic "you decide"). It returns a revoke handle that, when the granting spell's lifetime ends, sets temp HP back to the value *before* this grant whenever the current value is still higher (`src/models/entity.py:118-138`). The handle knows nothing about later grants or about which pool is current. As a result:
  - when an earlier grant expires, it wipes a later, larger grant from a different source;
  - when a replacing grant expires, the replaced pool comes back, which RAW says was given up.

  This is **silent**. Grants register the handle when made inside a `lifetime` block (`src/spells/blocks/state.py:44-51,170-179`); `examples/spells/rime_ward.json` is the shipped example.
- **Evidence:** `.srd_work/probes/ATK/p05_temp_hp.py`:
  ```
  A=5 then B=8, A's spell ends -> temp=0 (SRD: B's 8 remain; A's were replaced)
  10, replaced by 12, hit for 1, 12's spell ends -> temp=10 (SRD: 0; the 10 were given up)
  ```
  The other RAW points pass: `5 temp + 7 dmg -> temp=0 hp=18`, `10 then 12 -> temp=12`, healing leaves temp HP alone, and temp HP at 0 HP does not restore consciousness.
- **Gap:** temp HP is one pool owned by its latest accepted grant. Ending grant A should remove only what is left *of A's pool*, and only if A's pool is the current one. It must never resurrect a pool that was replaced.
- **Acceptance criteria:**
  1. Grant A=5 (lifetime), then B=8 (another source), then A's lifetime ends → temp HP 8.
  2. Grant 10 (permanent), then 12 (lifetime), take 1 → 11, then the lifetime ends → temp HP 0.
  3. Grant 12 (lifetime), take 1 → 11, then the lifetime ends → 0 (today's behaviour, keep it).
  4. Grant 12 (lifetime), then a smaller 5 → stays 12 (the larger is kept), and later ending the 5's lifetime → still 12.
- **Depends on / unblocks:** none.
- **Tests pinning current behaviour:** `tests/test_entity_lifetimes.py::test_temp_hp_handle_clears_its_grant` (single grant; stays valid).
- **Arena impact:** none (no arena scenario grants temp HP).
- **Known in:** ENGINE_MAP lead ("revoke semantics on spell end?"); new as a finding.
- **Size:** S. Track the owner of the current pool (e.g. a grant token) on `Entity`, and have revoke check it.

#### ATK-D-05 — Honour a critical hit forced on ATTACK_DECLARED
- **Status:** open
- **Type / severity:** DEVIATION — S3
- **SRD:** p.96-97 "Critical Hits" (crit damage). The hook is needed by the unconscious/paralyzed conditions (Appendix PH-A): "Any attack that hits the creature is a critical hit if the attacker is within 5 feet of the creature."
- **Current behaviour:** the `force_critical` block's docstring says it "sets `critical_hit` on the live `ATTACK_ROLLED`/`ATTACK_DECLARED` event" (`src/spells/blocks/event_mod.py:60-74`). `attack_roll` reads only advantage/disadvantage from the declared event, and reads `critical_hit` only from `ATTACK_ROLLED` (`src/spells/blocks/rolls.py:62-65,85-90`). A crit forced at declaration is silently dropped, and `AttackDeclaredData` even has a `critical_hit` field (`src/combat/event_data.py:100`). No shipped rule uses it yet (only `rules/global/critical_hit.json` and `critical_miss.json` use `force_critical`, both on `ATTACK_ROLLED`). This is latent, and **silent** when someone writes the auto-crit rule on the event that carries the needed data.
- **Evidence:** `.srd_work/probes/ATK/p07_declared_crit_and_heal_report.py` installs a global trigger `ATTACK_DECLARED → force_critical(hit)` on a real `CombatSystem`:
  ```
  (a) ATTACK_DECLARED force_critical, d20=12+0 vs AC10: hit=True formula=['1d8+3'] (crit would be 2d8+3)
  ```
- **Gap:** RAW's auto-crit is "an attack that hits is a critical hit". A crit flagged before the roll should make a *hit* a crit (dice doubled), and should not turn a miss into a hit. Note this differs from `force_critical` on `ATTACK_ROLLED`, which also forces the hit (correct for nat 20).
- **Acceptance criteria:**
  1. A trigger on `ATTACK_DECLARED` setting `critical_hit`, then a d20 that hits → damage formula `2d8+3`, and `ATTACK_HIT.critical_hit` is True.
  2. The same with a d20 that misses → a miss, no damage (the declared crit does not force a hit).
  3. The `force_critical` docstring and `BLOCK_REFERENCE.md` match the behaviour.
- **Depends on / unblocks:** unblocks the paralyzed/unconscious auto-crit (COND), which also needs ATK-M-01 (within-5-ft distance).
- **Tests pinning current behaviour:** none found. `tests/test_critical_hits.py` covers only nat 20/1.
- **Arena impact:** the heuristic's `crit_chance` (`src/arena/heuristic/estimate.py:77`) would need the extra source when it lands.
- **Known in:** new. The condition `_note`s mention the auto-crit as pending.
- **Size:** S. Read `declared.data["critical_hit"]` in `attack_roll` and apply it as "crit if hit".

#### ATK-D-06 — Report healing as the hit points actually regained
- **Status:** open
- **Type / severity:** DEVIATION — S4
- **SRD:** p.97 "Healing": "A creature's hit points can't exceed its hit point maximum, so any hit points regained in excess of this number are lost… the ranger regains 6 hit points from the druid, not 8."
- **Current behaviour:** HP is capped correctly (`src/models/entity.py:113-116`). The *reported* amount is the rolled value, though. The `healing` block emits `HEALING_APPLIED(amount=rolled)` and writes `context["healing_amount"]` and `inv.healing_total` from it (`src/spells/blocks/healing.py:51-60`). That flows into `SpellTargetResult.healing` (`src/combat/combat_system.py:446`) and the arena tool's per-target `"healing"` (`src/arena/tools.py:500-508`). This is **silent**: a rider keyed on `HEALING_APPLIED.amount`, and the model reading the tool result, see HP that was never regained.
- **Evidence:** `.srd_work/probes/ATK/p07_declared_crit_and_heal_report.py`:
  ```
  (b) ally 19/20 healed by 8: hp=20, SpellTargetResult.healing=8, HEALING_APPLIED amount=[8] (SRD regains 1)
  ```
- **Gap:** "hit points regained" is the capped amount.
- **Acceptance criteria:**
  1. Cure Wounds rolling 8 on a 19/20 ally → `SpellTargetResult.healing == 1`, `HEALING_APPLIED.amount == 1`, and the tool result `healing == 1`.
  2. On a 10/20 ally → all three report 8.
- **Depends on / unblocks:** none.
- **Tests pinning current behaviour:** none. The Vampiric Touch tests in `tests/test_spells.py` (~L905-L982) assert `healing` equals the HP actually gained, which agrees with the fix.
- **Arena impact:** `tools.py` per-target `healing` becomes the regained amount, so feedback to models changes.
- **Known in:** new.
- **Size:** S. Have `Entity.heal` return the delta, and use it.

#### ATK-D-07 — Reject a damage type that resolves to nothing, instead of dealing untyped damage
- **Status:** open
- **Type / severity:** DEVIATION — S4
- **SRD:** p.97 "Damage Types": "Different attacks, damaging spells, and other harmful effects deal different types of damage… other rules, such as damage resistance, rely on the types." (Thirteen types; there is no untyped damage.)
- **Current behaviour:** the `damage` block's `damage_type` may be an expression (`allow_expr=True`, `src/spells/blocks/damage.py:118-126`), so that a rider can deal the weapon's own type. If the expression raises, or yields something that is not a type name, `_resolve_damage_type` returns `DamageType.GENERIC` (`damage.py:29-54`). No resistance, immunity or vulnerability can name `GENERIC`. The load-time validator accepts the expression because it parses. This is **silent**, and it bypasses CLAUDE.md §2.5's "fail loudly" rule. `Action.primary_damage_type` returning `None` (an action with no damage) takes the same path.
- **Evidence:** `.srd_work/probes/ATK/p08_damage_type_fallback.py` (a creature whose weapon `program` has `"damage_type": "'POI' + 'SN'"` attacks a poison-immune target):
  ```
  loaded: damage_type expression accepted at load
  poison-immune target lost 10 HP (damage became GENERIC, no error)
  ```
- **Gap:** every damage instance should carry one of the SRD types. One that can't be resolved should be refused, loudly.
- **Acceptance criteria:**
  1. A `damage_type` expression evaluating to a non-type → the damage block raises (or the cast is refused) with an error naming the expression and the valid types.
  2. A literal `"GENERIC"` in content is rejected at load, unless the team decides to keep it as a deliberate engine-internal type (then documented as non-SRD).
  3. `event.action.primary_damage_type` on a weapon with damage still resolves its type (regression guard, CLAUDE.md §9 2026-08-31).
- **Depends on / unblocks:** none.
- **Tests pinning current behaviour:** none found (`grep -rn GENERIC tests` shows only tests that construct `GENERIC` damage directly, which criterion 2 would need to revisit if `GENERIC` is removed from the enum).
- **Arena impact:** none.
- **Known in:** new (CLAUDE.md §9 2026-08-31 describes the earlier GENERIC degradation of the Colossus rider).
- **Size:** S.

### SPELL — Spellcasting (SRD pp.100–104)

#### SPELL-D-01 — Range-check every single-target and multi-target spell, with or without a target point
- **Status:** open
- **Type / severity:** DEVIATION — S1
- **SRD:** p.101 "Range": "The target of a spell must be within the spell's range. For a spell like magic missile, the target is a creature."
- **Current behaviour:** `CombatSystem.resolve_spell` (`src/combat/combat_system.py:426-433`) range-checks the defenders of a non-AoE spell **only** `if target is not None`, i.e. only when the caller also passes an aim point. Neither real caller does for a creature-targeted spell: the arena's `cast_spell` tool passes `target=` only when the model sent a `target_point` (`src/arena/tools.py:475-497`), and the web client sends only `target_ids` for a single-target spell (`web/static/js/input.js:92-99` → `web/routers/combat.py:422-437`). So Fire Bolt, Magic Missile, Eldritch Blast, Scorching Ray, Cure Wounds, Inflict Wounds (touch), Vampiric Touch (touch) … resolve against a creature at any distance. **Silent.** The same gap is in `resolve_legendary_action` (`combat_system.py:523-525`).
- **Evidence:** `.srd_work/probes/SPELL/p01_single_target_range.py` — wizard at x=0, goblin at x=1000:
  ```
  Fire Bolt range: 120 ft. | distance to target: 1000 ft
  engine, no target point -> [('Far Goblin', False, 0)]
  arena tool, no target point -> {'ok': True, 'action': 'cast_spell', 'spell': 'Fire Bolt', 'results': [{'target_id': 'far-goblin', 'hit': True, 'damage': 8, ...}]}
  engine, with target point -> RuleViolation Fire Bolt: Far Goblin is out of range (997.5 ft, max 120 ft)
  ```
- **Gap:** every creature a spell targets must be within range (touch = within reach) whether or not an aim point is supplied; an out-of-range target must be refused before any resource or slot is spent.
- **Acceptance criteria:**
  1. Caster at x=0, target at x=500, Fire Bolt (120 ft), `resolve_spell(caster, [target], fire_bolt)` with no `target=` raises `RuleViolation(OUT_OF_RANGE)`; caster's action and slots unchanged.
  2. Same for a multi-target spell: Magic Missile with one in-range and one out-of-range dart target raises, nothing resolves.
  3. Touch spell (Inflict Wounds) on a target 20 ft away raises with no `target=`.
  4. Arena `cast_spell` with `target_ids` only, target out of range → `{"ok": False, "code": "out_of_range"}`.
- **Depends on / unblocks:** SPELL-D-02 (self range) uses the same check.
- **Tests pinning current behaviour:** `tests/test_aoe_casting.py::TestSingleTargetRange::test_no_target_kwarg_skips_range_check` ("Backward compat: omitting target= skips range check") — must be inverted.
- **Arena impact:** large for the raw-parameter conditions (C1/C2): today an out-of-range spell target is *accepted* there, while the menu condition only offers in-range targets (`src/arena/action_space.py:_spell_targets`, which already calls `check_single_target_range`). That is a between-condition asymmetry in exactly the spatial-error category the study measures; fixing it changes refusal counts for C1/C2. Heuristic agent unaffected if it uses the menu.
- **Known in:** new (the pinning test calls it "backward compat").
- **Size:** S — call `check_single_target_range` for every defender of a non-AoE spell unconditionally (and in `resolve_legendary_action`); update the pinning test.

#### SPELL-D-02 — Make "Range: Self" mean the caster: refuse other targets, anchor self areas on the caster
- **Status:** open
- **Type / severity:** DEVIATION — S1
- **SRD:** p.101 "Range": "Other spells, such as the shield spell, affect only you. These spells have a range of self. Spells that create cones or lines of effect that originate from you also have a range of self, indicating that the origin point of the spell's effect must be you".
- **Current behaviour:** `effective_range_ft` returns `None` for `RangeType.SELF` (`src/spatial/range_check.py:35-37`), and `None` means "no limit" everywhere it is read:
  - a single-target Self spell passes `check_single_target_range` for any creature (`range_check.py:104-105`), so Rime Ward (Self) can be cast on an enemy 500 ft away;
  - for a Self **cube** (Thunderwave, "Self (15-foot cube)"), `derive_aoe_origin` skips clamping and uses the aim point as the cube's face centre wherever it is (`range_check.py:150-156`), so the cube can be dropped anywhere on the map. Only cones and lines are anchored on the caster (`range_check.py:146-148`).
  - The arena's own guard returns early for the same `None` (`src/arena/tools.py:336-338`), and the area menu sweeps the whole board for it (`src/arena/action_space.py:486-503`).
  **Silent** in all three.
- **Evidence:** `.srd_work/probes/SPELL/p02_self_range.py`:
  ```
  Rime Ward range: Self targeting: single_target
  enemy 500 ft away temp HP after caster's Rime Ward: 5 | caster temp HP: 0
  Thunderwave range: Self Cube (15 ft. side)
  Thunderwave aimed at (500,0,0): hit ['Enemy'] | enemy hp 40 -> 40   (its 5 temp HP absorbed the 2)
  arena tool, Thunderwave at x=500 -> {'ok': True, ... 'results': [{'target_id': 'enemy', 'hit': True, 'damage': 2, ...}]}
  ```
  `.srd_work/probes/SPELL/p02b_self_cube_menu.py` (goblin 60 ft away): the menu offers `aim:goblin (45.0, -5.0)` and `aim:wizard (0.0, 0.0)` for Thunderwave.
- **Gap:** a Self spell with no area affects only the caster; a Self area (cone, line, *and* cube, e.g. Thunderwave; also Self spheres/radius effects centred on the caster) has its point of origin on the caster. For a cube, RAW puts the origin "anywhere on a face", so the caster chooses only which way the cube faces and where along the face it sits — never a distant point.
- **Acceptance criteria:**
  1. `resolve_spell(caster, [other], rime_ward)` raises `RuleViolation(INVALID_TARGET_RELATION or OUT_OF_RANGE)`; `resolve_spell(caster, [caster], rime_ward)` grants the caster 5 temp HP.
  2. Thunderwave aimed at a point 500 ft away resolves with the cube adjacent to the caster (face touching the caster's space, extending toward the aim direction): a goblin 500 ft away is unaffected; a goblin 10 ft away in that direction is affected.
  3. Arena `aim_candidates` for Thunderwave offers only caster-anchored placements (no option whose cube is detached from the caster).
- **Depends on / unblocks:** SPELL-D-03 (caster in own area), SPELL-D-01.
- **Tests pinning current behaviour:** none found asserting a far self cube; check `tests/test_aoe_casting.py` cube tests when changing `derive_aoe_origin`.
- **Arena impact:** `aim_candidates` / `_sweep_bounds` (menu), `_refuse_out_of_range_aim` (tools), the heuristic's own placement search (`src/arena/heuristic/`), and any scenario using Thunderwave or a Self buff. None of the study scenarios cast Thunderwave or Rime Ward (only `aoe_placement` wires Fireball), so `results/final` is unaffected.
- **Known in:** new.
- **Size:** S/M — treat SELF as range 0 anchored on the caster in `effective_range_ft` callers; give `derive_aoe_origin` a SELF branch for cubes (origin on the caster's boundary facing the aim direction); single-target SELF spells resolve on the caster only.

#### SPELL-D-07 — End concentration when the caster is incapacitated or killed
- **Status:** open
- **Type / severity:** DEVIATION — S1
- **SRD:** p.102 "Concentration": "Being incapacitated or killed. You lose concentration on a spell if you are incapacitated or if you die."
- **Current behaviour:** `Entity.end_concentration` (`src/models/entity.py:332-339`) has exactly two callers: the failed CON save in `force_concentration_check` (`src/spells/blocks/global_effects.py:31-44`) and the duration clock (`entity.py:348-349`). Nothing subscribes to `ENTITY_DIES` (`grep ENTITY_DIES` finds only its emitter in `src/combat/damage_processor.py:57-61`) or to `CONDITION_ADDED` for the incapacitating conditions. So a caster who drops to 0 HP keeps concentrating whenever the killing blow's concentration save happens to succeed (a 1-damage finisher is DC 10), and a stunned, paralyzed, unconscious, petrified or incapacitated caster always keeps it: Haste, Shield of Faith, Vampiric Touch and any condition-imposing concentration spell stay up. **Silent.**
- **Evidence:** `.srd_work/probes/SPELL/p07_concentration_breaks.py` (Shield of Faith on an ally):
  ```
  after cast: ally AC 14 | caster concentrating: True
  caster STUNNED (incapacitated): concentrating: True | ally AC 14
  seed 0: caster HP 0, is_alive False, still concentrating True, ally AC 14
  ```
  (The probe's 999-damage case ends concentration only because its DC 499 save fails, not because of the death.)
- **Gap:** concentration ends the moment the caster gains any condition that includes incapacitated (incapacitated, paralyzed, petrified, stunned, unconscious) or drops to 0 HP / dies, regardless of any save.
- **Acceptance criteria:**
  1. Caster concentrating on Shield of Faith (ally AC 14) is stunned via `apply_condition` → caster `has_concentration` is False, ally AC 12.
  2. Caster at 1 HP takes 1 damage (concentration save rigged to succeed) → caster at 0 HP, concentration ended, ally AC 12.
  3. A caster frightened or charmed (not incapacitating) keeps concentration.
- **Depends on / unblocks:** COND (which conditions include incapacitated) and TURN/dying work (0 HP = unconscious). Best expressed as a global rule on `ENTITY_DIES` and `CONDITION_ADDED`.
- **Tests pinning current behaviour:** none found asserting concentration survives these.
- **Arena impact:** observation of who is concentrating / buffed changes; heuristic value of killing or stunning a concentrating caster rises. No study scenario uses a concentration spell.
- **Known in:** new (`LifetimeKind.CONCENTRATION` docstring in `src/models/lifetime.py` already *claims* "or death").
- **Size:** S — a global rule (or two) calling `end_concentration` on `ENTITY_DIES` and on `CONDITION_ADDED` of an incapacitating condition.

#### SPELL-D-13 — Enforce how many targets (darts, beams, creatures) one cast may choose
- **Status:** open
- **Type / severity:** DEVIATION — S1
- **SRD:** p.102 "Targets": "A typical spell requires you to pick one or more targets to be affected by the spell's magic. A spell's description tells you whether the spell targets creatures, objects, or a point of origin". (Counts come from each spell: Fire Bolt "a creature or object"; Magic Missile "three glowing darts … one more dart for each slot level above 1st"; Eldritch Blast "more than one beam when you reach higher levels"; Scorching Ray "three rays".)
- **Current behaviour:** `resolve_spell` resolves every entry of `defenders` for a non-AoE spell (`src/combat/combat_system.py:426-441`); `SpellAction` has no target-count field for either `SINGLE_TARGET` or `MULTI_TARGET` (`src/models/action.py:118-175`, `src/models/spell_properties.py:51-59`), and `for_each_target` loops whatever it is given (`src/spells/blocks/iterators.py:50-61`). So a single-target spell hits several creatures, a 1st-level Magic Missile fires any number of darts, a level-1 Eldritch Blast fires any number of beams, all for one action and one slot. An empty `defenders` list is also accepted: the action (and slot) is spent and nothing happens. The arena forwards whatever list the model writes (`src/arena/tools.py:266-274`, `472`). **Silent.**
- **Evidence:** `.srd_work/probes/SPELL/p14_target_count.py`:
  ```
  Magic Missile (1st level: three darts) given 12 dart targets -> 12 darts resolved, total damage 47
  Fire Bolt (one target) given two targets -> [('Goblin', True), ('Goblin 2', True)]
  Eldritch Blast (1 beam below 5th level) given 4 beams -> 4 attack rolls
  Fire Bolt with no target -> [] | action left: 0
  arena tool: Fire Bolt with two target_ids -> True [('goblin', False, 0), ('goblin-2', False, 0)]
  arena tool: Magic Missile with eight dart targets -> True 8 darts
  ```
- **Gap:** each spell declares how many targets/projectiles it takes (a number that may scale with slot level or caster level); a cast with more (or, for a targeted spell, zero) is refused before resources are spent. Projectiles may repeat a target where the spell allows.
- **Acceptance criteria:**
  1. Fire Bolt with `[gob, gob2]` raises `RuleViolation` (a target-count code); nothing spent.
  2. Magic Missile at slot 1 with 4 dart targets raises; with 3 (repeats allowed) resolves 3 darts; at slot 2, 4 darts resolve.
  3. Eldritch Blast for a caster below 5th level with 2 beams raises.
  4. Any targeted spell with `defenders=[]` raises `UNKNOWN_TARGET` and spends nothing.
- **Depends on / unblocks:** count scaling by slot (deferred upcasting framework, CODEBASE_REVIEW A39) and by caster level (SPELL-M-04, cantrip scaling). A fixed per-spell count can land first.
- **Tests pinning current behaviour:** none found asserting extra targets are accepted; arena tests for multi-target allocation (`src/arena/enumeration.py` notes N projectiles) should be checked.
- **Arena impact:** C1/C2 can currently fire unbounded darts/beams or hit two creatures with a single-target spell; the menu condition cannot (no multi-target menu). A refusal code would land in the study's error categories. No study scenario gives a model a non-AoE spell, so `results/final` is unaffected.
- **Known in:** new.
- **Size:** S/M — a `target_count` field (int, or an expression over slot/caster level) on `SpellAction`, loaded and validated, checked in `resolve_spell`.

#### SPELL-D-03 — Keep the caster out of a cone/line/cube that originates from them (unless they choose otherwise)
- **Status:** open
- **Type / severity:** DEVIATION — S2
- **SRD:** p.103 "Cone": "A cone's point of origin is not included in the cone's area of effect, unless you decide otherwise." Same sentence for "Cube" and "Line". p.102 "Targeting Yourself": "If you are in the area of effect of a spell you cast, you can target yourself."
- **Current behaviour:** for Self-origin areas the origin is placed on the caster's boundary (`derive_aoe_origin`, `src/spatial/range_check.py:146-148`), and whether the caster is then "in" the area depends on the aim:
  - cube/line use a SAT test whose separation check is strict `>` plus an `EPSILON` padding (`src/spatial/aoe.py:69-125`), so a volume whose face merely *touches* the caster's box counts as overlapping it;
  - the cone samples the caster's own face centre, which coincides with the apex when the aim is axis-aligned and level (`aoe.py:241-263`).
  The only exclusion is a per-spell opt-in flag, `cannot_cause_self_damage` (`src/combat/combat_system.py:424-425`), set on Cone of Cold and Lightning Bolt only; Burning Hands and Thunderwave do not set it. **Silent.**
- **Evidence:** `.srd_work/probes/SPELL/p03_caster_in_own_area.py` / `p03b_cone_self.py`:
  ```
  Thunderwave, face on caster's edge, hits: [('Wizard', 9), ('Goblin', 4)]
  Burning Hands  aim (10, 2.5, 0): caster caught = True
  Burning Hands  aim (0, 2.5, -10): caster caught = True
  Burning Hands  aim (10, 0, 0): caster caught = False
  Thunderwave    aim (2.5, 0, 0): caster caught = True
  ```
  `p05_line_tilt.py`: Lightning Bolt's raw target set contains `'Wizard'` for every aim (removed afterwards only by the per-spell flag).
- **Gap:** the point of origin of a cone, cube or line is excluded by default, so a caster whose space only holds the origin is not affected; RAW lets the caster opt in. Inclusion must not depend on whether the aim happens to be axis-aligned. Spheres and cylinders *do* include their origin (correct today).
- **Acceptance criteria:**
  1. Burning Hands aimed at (10, 2.5, 0) and at (10, 0, 0): caster not in the resolved target list in either case.
  2. Thunderwave aimed due east from the caster: caster not affected; a creature adjacent on the east is.
  3. A test spell with a Self line and no `cannot_cause_self_damage` flag does not affect its caster.
  4. Fireball centred on the caster still affects the caster (sphere includes its origin).
- **Depends on / unblocks:** SPELL-D-02 (Self cube anchoring), SPELL-D-05 (touching vs overlapping). Makes `cannot_cause_self_damage` redundant for the shape rule.
- **Tests pinning current behaviour:** `tests/arena/test_aim_candidates.py` (~L237, the flag must be honoured by the menu) and `tests/arena/test_scenarios.py:169` (`assert not fireball.cannot_cause_self_damage`) assert the flag mechanism; re-check them when the default changes.
- **Arena impact:** `aim_candidates` already filters by the flag (`src/arena/action_space.py:515-516`); with the shape rule in the engine, the menu stops offering e.g. `aim:wizard` for Thunderwave. Heuristic placement scores self-hits as ally hits, so its choices shift.
- **Known in:** new (the flag is the existing partial workaround).
- **Size:** S — exclude the caster from Self-origin cone/cube/line target sets in `resolve_spell` by shape, with an optional per-cast "include me" choice.

#### SPELL-D-04 — Aim lines, cones and cubes horizontally from a ground-level aim point
- **Status:** open
- **Type / severity:** DEVIATION — S2
- **SRD:** p.103 "Line": "A line extends from its point of origin in a straight path up to its length and covers an area defined by its width." p.103 "Cone": "A cone extends in a direction you choose from its point of origin."
- **Current behaviour:** `derive_aoe_origin` takes the direction as the unit vector from the caster's **box centre** (mid-height, y = 2.5 ft for a Medium caster) to the aim point (`src/spatial/range_check.py:136-148`). Both front ends always aim at ground level: the web converts every click to `y = 0` (`web/routers/combat.py:64-66`); the arena tool defaults `y` to 0 (`src/arena/tools.py:478-482`) and the menu sweeps `Point3D(x, 0.0, z)` (`src/arena/action_space.py:500`). So every line/cone/cube points *downward*, steeply when the aim point is close. A 5-ft-wide, 100-ft Lightning Bolt aimed at the nearest enemy dives into the ground and misses creatures standing behind it on the same bearing. **Silent.**
- **Evidence:** `.srd_work/probes/SPELL/p05_line_tilt.py` (orcs at x=10 and x=40 on the caster's bearing):
  ```
  aim (10, 0, 0): origin y=1.89 dir=(0.97,-0.24,0.00) -> ['Wizard', 'Near Orc', 'Touching Orc']
  aim (40, 0, 0): origin y=2.34 dir=(1.00,-0.06,0.00) -> ['Wizard', 'Near Orc', 'Far Orc', 'Touching Orc']
  aim (10, 2.5, 0): origin y=2.50 dir=(1.00,0.00,0.00) -> ['Wizard', 'Near Orc', 'Far Orc', 'Touching Orc']
  ```
- **Gap:** the caster chooses a direction; aiming a line "at" a creature 10 ft away must not cut its effective reach to ~20 ft. With every creature on the ground (y locked, CODEBASE_REVIEW A21), a ground-level aim point should give a horizontal direction (or the aim should be lifted to the origin's height) unless a vertical aim is explicitly requested.
- **Acceptance criteria:**
  1. Lightning Bolt from a caster at the origin aimed at (10, 0, 0) affects creatures at (40, 0, 0) and (95, 0, 0).
  2. Burning Hands aimed at (5, 0, 0) affects a creature at (14, 0, 0).
  3. The resolved target set for a line/cone is identical for aim points (10, 0, 0) and (40, 0, 0) (same bearing).
- **Depends on / unblocks:** SPELL-D-03, SPELL-D-05.
- **Tests pinning current behaviour:** none found that assert a downward tilt; re-run `tests/test_aoe_casting.py` cone/line tests.
- **Arena impact:** `aim_candidates` derives its options from the engine, so options change (more creatures per line option). Free-coordinate conditions (C1/C2) that aim a line at the nearest enemy's coordinates currently catch fewer creatures than the menu's swept options — a between-condition asymmetry in the spatial category. Heuristic placement search likewise. (No study scenario casts a line or cone; `aoe_placement` uses Fireball, a sphere, which is unaffected.)
- **Known in:** new.
- **Size:** S — project the direction onto the horizontal plane (or lift the aim to the origin height) in `derive_aoe_origin`.

#### SPELL-D-08 — Roll the concentration save through the normal saving-throw path
- **Status:** open
- **Type / severity:** DEVIATION — S2
- **SRD:** p.102 "Concentration": "Whenever you take damage while you are concentrating on a spell, you must make a Constitution saving throw to maintain your concentration."
- **Current behaviour:** `force_concentration_check` rolls `roll_d20() + target.stat_block.get_saving_throw_bonus("constitution")` itself (`src/spells/blocks/global_effects.py:40-43`). It bypasses `roll_saving_throw` (`src/utils/saving_throw.py`), so it ignores every `saving_throw.constitution` / `saving_throw.all` stat modifier, never emits `SAVING_THROW_DECLARED`, and so never gets advantage/disadvantage from any rule or condition. Every other save in the engine goes through that path (`blocks/rolls.py:150-170`). **Silent.**
- **Evidence:** `.srd_work/probes/SPELL/p08_concentration_save_mods.py` (caster with +20 to CON saves takes 40 damage, DC 20):
  ```
  ordinary CON save with the +20 vs DC 20: (30, True)
  concentration lost in 48/50 seeds despite +20 to CON saves (DC 20)
  SAVING_THROW_DECLARED events emitted for concentration saves: 0
  ```
- **Gap:** the concentration check is an ordinary CON saving throw: it must include save modifiers and honour advantage/disadvantage raised on `SAVING_THROW_DECLARED`, exactly like a spell's save.
- **Acceptance criteria:**
  1. A concentrating caster with a `saving_throw.constitution +20` modifier who takes 40 damage (DC 20) keeps concentration on every seed.
  2. A rule granting advantage on CON saves via `SAVING_THROW_DECLARED` is consulted by the concentration save (event observed, two d20s rolled).
  3. DC stays `max(10, damage // 2)`.
- **Depends on / unblocks:** content such as Bless (d4 to saves), Paladin auras, War Caster-like features.
- **Tests pinning current behaviour:** tests that patch `src.spells.blocks.global_effects.roll_d20` to drive the check (grep before changing) will need the patch target moved.
- **Arena impact:** none directly.
- **Known in:** new.
- **Size:** S — call `roll_saving_throw` after emitting `SAVING_THROW_DECLARED`, like `blocks/rolls.saving_throw`.

#### SPELL-D-09 — Drop the old concentration when the new concentration spell is cast, not after it resolves
- **Status:** open
- **Type / severity:** DEVIATION — S2
- **SRD:** p.102 "Concentration": "Casting another spell that requires concentration. You lose concentration on a spell if you cast another spell that requires concentration. You can't concentrate on two spells at once."
- **Current behaviour:** whether a spell "requires concentration" is not read from the spell at all: `SpellAction.duration.concentration` is display-only (no reader outside the loader/serialiser; `grep "\.concentration\b"` in `src/`), and nothing in `src/spells/validate.py` checks it against the program. Concentration starts only when a `lifetime` block with `kind: "concentration"` runs, and `begin_concentration` disposes the previous concentration **after** that block's `then` has run (`src/spells/blocks/lifetime.py:52-63`, `src/models/entity.py:312-330`). Consequences:
  - the old concentration's riders are still live while the new spell's earlier blocks resolve — the root cause of CODEBASE_REVIEW **A36** (Vampiric Touch recast heals twice);
  - a concentration spell whose `lifetime` block is skipped (e.g. guarded on a failed save, or after a missed attack) never ends the old concentration;
  - a spell whose metadata says concentration but whose program uses a `rounds` lifetime is silently not concentration (and vice versa).
  **Silent.**
- **Evidence:** `.srd_work/probes/SPELL/p10_recast_concentration_order.py` (Vampiric Touch recast at 1 HP):
  ```
  recast: [('DAMAGE_DEALT', 10, 'old scope live')] | reported healing 5 | caster HP 1 -> 11
  ```
  The new cast's damage fires while the first cast's scope (and its healing rider) is still live, so the caster heals 5 (spell) + 5 (old rider).
- **Gap:** casting a spell whose Duration says Concentration ends any current concentration at the start of the cast, before any of the new spell's effects, and whether or not the new spell then succeeds; the flag on the spell and the program's lifetime kind must agree.
- **Acceptance criteria:**
  1. `test_vampiric_touch_recast_heals_once` (strict xfail, A36) passes: recast reports 4 healing and the caster gains exactly 4.
  2. Caster concentrating on Shield of Faith casts a concentration spell whose effect is gated on a failed save; the target saves → Shield of Faith has still ended.
  3. Loading a spell with `duration.concentration: true` but no `lifetime` of kind concentration (or the reverse) fails validation, naming the spell.
- **Depends on / unblocks:** fixes A36; SPELL-D-10.
- **Tests pinning current behaviour:** `tests/test_spells.py::...::test_vampiric_touch_recast_heals_once` (strict xfail — flips to pass).
- **Arena impact:** none in the study (no concentration spells in scenarios).
- **Known in:** CODEBASE_REVIEW A36 (symptom; cause identified here).
- **Size:** S/M — in `resolve_spell` (or the resolver), end the caster's concentration before running the program when `duration.concentration` is set; add the load-time consistency check.

#### SPELL-D-10 — Let one concentration spell hold effects on several targets
- **Status:** open
- **Type / severity:** DEVIATION — S2
- **SRD:** p.102 "Concentration": "If you lose concentration, such a spell ends." (One spell, all of its targets; e.g. Bless "up to three creatures of your choice", Hold Person upcast.)
- **Current behaviour:** a multi-target spell fans out with `for_each_target`, and each target's `lifetime` block calls `caster.begin_concentration(scope)` (`src/spells/blocks/lifetime.py:59-63`), which disposes the previous target's scope (`src/models/entity.py:327`). Only the last target keeps the effect. There is no way to author one concentration scope spanning the whole target set (`lifetime` is `TargetArity.SINGLE`). **Silent.**
- **Evidence:** `.srd_work/probes/SPELL/p09_concentration_multi_target.py` (a validated, Bless-shaped test spell: +2 AC to three allies):
  ```
  AC after one concentration cast on three allies: {'Ally 1': 12, 'Ally 2': 12, 'Ally 3': 14} (base 12)
  ```
- **Gap:** all effects one cast creates on all its targets belong to one concentration; losing it ends them all, and the cast itself must not end its own earlier targets' effects.
- **Acceptance criteria:**
  1. The probe's spell on three allies → all three at AC 14; caster `has_concentration`.
  2. Caster then fails a concentration save → all three back to AC 12.
  3. Casting a different concentration spell afterwards ends all three.
- **Depends on / unblocks:** SPELL-D-09; content Bless, Bane, Hold Person (upcast), Hex-like riders.
- **Tests pinning current behaviour:** none found.
- **Arena impact:** none today (no shipped multi-target concentration spell).
- **Known in:** new.
- **Size:** M — a cast-level concentration scope (opened once per cast, joined by each target's grants), or a set-arity `lifetime`.

#### SPELL-D-12 — Force a concentration save for damage dealt by triggers and riders, not only by casts and attacks
- **Status:** open
- **Type / severity:** DEVIATION — S2
- **SRD:** p.102 "Concentration": "Whenever you take damage while you are concentrating on a spell, you must make a Constitution saving throw to maintain your concentration … If you take damage from multiple sources … you make a separate saving throw for each source of damage."
- **Current behaviour:** the concentration rule listens to `DAMAGE_DEALT` (`rules/global/concentration.json`). The `damage` block applies damage with `emit_dealt=False` (`src/spells/blocks/damage.py:94-100`) and leaves the emission to `run_target`'s orchestration (`src/spells/runner.py:64-94`). A trigger's body runs through plain `run_program` (`src/spells/blocks/triggers.py:141`), which has no such orchestration, so damage dealt by any rider — Rime Ward's reflected cold today; any start-of-turn aura, ongoing-damage condition or on-hit rider tomorrow — emits no `DAMAGE_DEALT`. No concentration save is rolled, and every other `DAMAGE_DEALT` subscriber (Rime Ward's own end check, Vampiric Touch's healing rider) misses it too. **Silent.** (Casts and weapon attacks are fine: one `DAMAGE_DEALT` per target per resolution, so one save per source — checked.)
- **Evidence:** `.srd_work/probes/SPELL/p12_rider_damage_no_conc_check.py` (an enemy concentrating on Shield of Faith stabs a Rime-Warded creature):
  ```
  enemy caster HP 40 -> 35 (Rime Ward reflected cold)
  DAMAGE_DEALT events: [('Warden', 1)]
  enemy caster still concentrating (no save was ever rolled): True
  ```
- **Gap:** every instance of damage taken — whatever block or rider dealt it — is a source that triggers its own concentration save (DC max(10, half)).
- **Acceptance criteria:**
  1. In the probe's set-up, the 5 reflected cold damage emits one `DAMAGE_DEALT` (defender = the attacker, total 5) and rolls one DC 10 concentration save.
  2. A trigger that deals damage to two creatures emits one `DAMAGE_DEALT` per creature.
  3. Rime Ward's attack-plus-reflection still produces exactly one `DAMAGE_DEALT` for the warden (no double emission).
- **Depends on / unblocks:** ongoing-damage content (Spirit Guardians, Heat Metal, Moonbeam-like auras); also matters for COND riders that deal damage.
- **Tests pinning current behaviour:** none found asserting the absence.
- **Arena impact:** none in the study.
- **Known in:** new (the runner's docstring notes trigger firings run "minus the orchestration").
- **Size:** S — emit `DAMAGE_DEALT` from trigger firings that dealt damage (or from the `damage` block when not under `run_target`).

#### SPELL-D-14 — Forbid a second non-cantrip spell in a turn in which a bonus-action spell is cast
- **Status:** open
- **Type / severity:** DEVIATION — S2
- **SRD:** p.101 "Bonus Action": "You must use a bonus action on your turn to cast the spell, provided that you haven't already taken a bonus action this turn. You can't cast another spell during the same turn, except for a cantrip with a casting time of 1 action."
- **Current behaviour:** a bonus-action spell costs `BONUS_ACTION_COST` (`src/models/action.py:162-175`) and `resolve_spell` checks only resources and slots (`src/combat/combat_system.py:386-409`). Nothing records spells cast this turn, so a bonus-action spell plus a levelled action spell (in either order) is accepted. **Silent.**
- **Evidence:** `.srd_work/probes/SPELL/p13_casting_time.py`:
  ```
  Shield of Faith casting time: 1 bonus action cost: ActionCost(actions=0, bonus_actions=1, reactions=0, movement=0.0)
  same turn: bonus-action Shield of Faith, then 1st-level Magic Missile -> accepted, damage 9 | slots left {1: 2}
  ```
  `grep -rn "spells_cast\|cast_this_turn" src` finds no per-turn spell record.
- **Gap:** in a turn in which the caster casts a bonus-action spell, the only other spell they may cast is a cantrip whose casting time is 1 action — whichever order the two are cast in. (A reaction spell on another creature's turn is unaffected.)
- **Acceptance criteria:**
  1. Shield of Faith (bonus) then Magic Missile (action, level 1) in one turn → second cast raises `RuleViolation`; slot not spent.
  2. Magic Missile then Shield of Faith in one turn → the bonus-action cast raises.
  3. Shield of Faith then Fire Bolt (cantrip, 1 action) → allowed.
  4. The restriction resets at the caster's next turn.
- **Depends on / unblocks:** a per-turn "spells cast" record on `Entity`, cleared on `TURN_START` (the refill rule is the natural home).
- **Tests pinning current behaviour:** `tests/test_action_economy.py` may cast bonus + action spells in one turn; check before changing.
- **Arena impact:** menu/enumeration (`legal_actions`) must drop levelled spells after a bonus-action spell (and vice versa); the heuristic's turn planner must respect it; prompt text could state the rule. No study scenario includes a bonus-action spell.
- **Known in:** new (ENGINE_MAP lead).
- **Size:** S.

#### SPELL-D-17 — Don't let a creature with no slot table cast levelled spells without limit
- **Status:** open
- **Type / severity:** DEVIATION — S2
- **SRD:** p.100 "Spell Slots": "Regardless of how many spells a caster knows or prepares, he or she can cast only a limited number of spells before resting." "Some characters and monsters have special abilities that let them cast spells without using spell slots."
- **Current behaviour:** every slot check in `resolve_spell` and `resolve_legendary_action` is guarded by `caster.spell_slots is not None` (`src/combat/combat_system.py:403`, `436`, `528-537`), and `Entity.spell_slots` is `None` whenever the stat block has no `spell_slots` table (`src/models/entity.py:77-78`). So a creature JSON that lists `known_spells` but omits `spell_slots` casts Fireball (or anything) every turn, unlimited. There is no per-day / innate-use limit to express the RAW alternative ("3/day each"). **Silent.**
- **Evidence:** `.srd_work/probes/SPELL/p15_slots.py`: `caster with known_spells but no spell_slots: Fireball cast 5 times, spell_slots = None`. `grep -rni "per_day\|/day\|innate\|uses_per" src/` finds no limited-use model.
- **Gap:** a levelled spell needs a slot of its level or higher unless the caster has an explicit slot-free source (innate "at will", "N/day", pact-style feature), which must be declared and counted.
- **Acceptance criteria:**
  1. A creature with `known_spells: ["Fireball"]` and no `spell_slots` cannot cast Fireball (refused `INSUFFICIENT_RESOURCE`) unless the spell is declared at-will or limited-use for it.
  2. A creature declaring Fireball as "1/day" casts it once, then is refused.
  3. Cantrips stay unlimited with no slot table.
- **Depends on / unblocks:** MON (innate spellcasting / limited-use abilities — CODEBASE_REVIEW §4 item 7).
- **Tests pinning current behaviour:** tests that build spell-casting entities without slots and cast levelled spells (e.g. in `tests/test_spells.py`, `tests/test_aoe_casting.py`'s `_make_entity` has no slot table and casts level-3 Fireball) will need slots or an at-will flag.
- **Arena impact:** scenario builders must give casters slots or at-will declarations (the `aoe_placement` caster has `spell_slot_defaults` — check before changing).
- **Known in:** new.
- **Size:** M — an innate/limited-use declaration on the stat block, and a hard "no slot source → refuse" default.

#### SPELL-D-19 — Don't stack the same spell's effects on one target; apply the most potent
- **Status:** open
- **Type / severity:** DEVIATION — S2

- **SRD:** p.104 "Combining Magical Effects": "The effects of the same spell cast multiple times don't combine, however. Instead, the most potent effect—such as the highest bonus—from those castings applies while their durations overlap."

- **Current behaviour:** every cast installs its own grants: `add_modifier` appends a `StatModifier` (`src/spells/blocks/state.py:155-166`) and `Entity.ac` sums all `ac` modifiers (`src/models/entity.py:388-391`); a `TURN_START` rider (Longstrider, Haste) is subscribed once per cast. Nothing compares a new grant with an existing one from the same spell. So two clerics' Shield of Faith give +4 AC, and two Longstriders (from two casters, or one caster recasting the non-concentration spell) give +20 ft. **Silent.**

- **Evidence:** `.srd_work/probes/SPELL/p18_combining_effects.py`:

  ```

  Shield of Faith from two clerics: fighter AC 16 (base 12; RAW 14)

  Longstrider from two clerics: fighter movement at its turn start [50] (speed 30; RAW 40)

  Longstrider twice from one cleric: [50] (RAW 40)

  ```

  (This answers MOVE's question: yes, Longstrider stacks.)

- **Gap:** while durations overlap, a creature benefits from (or suffers) one instance of a given spell's effect — the most potent (e.g. the highest-level casting's numbers); when that one ends, the next-most-potent still running takes over. Different spells still add together.

- **Acceptance criteria:**

  1. Shield of Faith from two casters on one target → AC 14; the first caster loses concentration → still 14; both lose it → 12.

  2. Longstrider cast twice on one target → movement 40 at its turn start.

  3. Shield of Faith + a different +AC spell on one target → both apply.

- **Depends on / unblocks:** a spell identity on every grant (the scope `source` exists — `LifetimeScope.source`, `src/models/lifetime.py:94-108`); "most potent" needs a comparable magnitude per grant. Also COND: the same condition from two sources is a COND question, not this one.

- **Tests pinning current behaviour:** none found asserting stacking.

- **Arena impact:** heuristic buff valuation (it would value a repeat buff at 0); none in the study (no buff spells in scenarios).

- **Known in:** new (raised as a question by the MOVE audit).

- **Size:** M — de-duplicate grants by (spell, target, stat) at grant time with "keep the max, re-expose on revoke", or resolve at read time.

#### SPELL-D-20 — Let area spells catch unconscious and 0-HP creatures, and single-target spells reach them
- **Status:** open
- **Type / severity:** DEVIATION — S2

- **SRD:** p.102 "Areas of Effect": "Spells such as burning hands and cone of cold cover an area, allowing them to affect multiple creatures at once." (Each spell: "Each creature in a 20-foot-radius sphere".) p.359 "Unconscious": "An unconscious creature is incapacitated (see the condition), can't move or speak, and is unaware of its surroundings" — still a creature in the area.

- **Current behaviour:** `get_targets_in_aoe` filters on `get_alive_entities()` (`src/combat/combat_system.py:871`, `648-650`), and `Entity.is_alive()` is False both at 0 HP and while UNCONSCIOUS (`src/models/entity.py:144-153`). So a creature that is merely unconscious (e.g. Sleep-like effect, at full HP) is skipped by every area spell, and a 0-HP creature (which RAW is unconscious and dying — damage to it causes death-save failures) is skipped too. For single-target spells the engine accepts a 0-HP target (Cure Wounds revives it), but the arena menu builds targets from the same alive list (`src/arena/action_space.py:283`), so a downed ally can never be offered for healing. **Silent.**

- **Evidence:** `.srd_work/probes/SPELL/p19_unconscious_targets.py`:

  ```

  Fireball centred between an unconscious (full HP) orc and an awake orc -> ['Awake Orc'] | sleeping orc HP 30

  menu targets for Cure Wounds with an ally at 0 HP adjacent: ['Wizard']

  engine: Cure Wounds on the 0-HP ally -> HP 5 is_alive True

  ```

- **Gap:** an area affects every creature in it, conscious or not, and a creature at 0 HP that is not dead is a valid target for spells (healing it is the standard way to bring it back). Whether a 0-HP creature is "dead" or "dying" belongs to the TURN/COND dying model; this entry only requires that targeting and area collection use "present and not dead", not `is_alive()`.

- **Acceptance criteria:**

  1. Fireball catching an UNCONSCIOUS orc at full HP: the orc makes the save and takes damage.

  2. Arena `_spell_targets` for Cure Wounds includes an adjacent ally at 0 HP (once the dying model says it is not dead).

  3. A creature that is actually dead (per the dying model) is excluded from both.

- **Depends on / unblocks:** TURN/COND dying, death saves and the "downed but present" lifecycle (`docs/current/ENTITY_LIFECYCLE_DECISIONS.md`). The unconscious-at-full-HP case is independent of that and can be fixed first.

- **Tests pinning current behaviour:** `tests/test_aoe_casting.py` tests named for "alive" entities in the area (grep `alive` there) and arena menu tests built on `get_alive_entities`.

- **Arena impact:** menus (`_spell_targets`, `aim_candidates`), observation of downed creatures, the heuristic (healing a downed ally becomes a candidate), and `sides_standing`/win detection interplay.

- **Known in:** new (raised by the MOVE audit lead agent).

- **Size:** S for the area collection; M including the menu and dying interplay.

#### SPELL-D-05 — Use one consistent "creature is in the area" test for every shape
- **Status:** open
- **Type / severity:** DEVIATION — S3
- **SRD:** p.102 "Areas of Effect": "A spell's description specifies its area of effect, which typically has one of five different shapes". How much of a creature must be inside is not stated — see SPELL-Q-01.
- **Current behaviour:** the engine's convention is "the creature's box overlaps the area" (`get_targets_in_aoe`, `src/combat/combat_system.py:844-871`), but the shapes implement it differently:
  - **Cone** tests only 14 sample points per creature (8 corners + 6 face centres, `src/spatial/aoe.py:260-263`), so a creature genuinely overlapping the cone is missed when the cone passes between samples, most often for Large/Huge creatures.
  - **Cube/Line** SAT treats a shared face as overlap (strict `>` plus `EPSILON`, `aoe.py:69-125`), so a creature merely touching the edge is included.
  - **Sphere/Cylinder** use `<=` on distance (touching included).
  This is inconsistent with the 2026-09-30 ruling that touching is not overlapping (CODEBASE_REVIEW A29, `BoundingBox.overlaps`). **Silent.**
- **Evidence:** `.srd_work/probes/SPELL/p04_cone_sampling.py` (Burning Hands cone; random creatures vs a 13x13x13-lattice ground truth): `creatures overlapping the cone but reported outside: 1380` of 12 000; `MEDIUM misses: 138 max fraction inside: 0.08`, `LARGE misses: 367`, `HUGE misses: 875 max fraction inside: 0.17 | misses with >=5% of volume inside: 245`. `p05_line_tilt.py`: `'Touching Orc'` (box z 2.5–7.5, line edge at z = 2.5) is caught by Lightning Bolt.
- **Gap:** whatever partial-overlap rule is chosen (SPELL-Q-01), all five shapes must apply it exactly and identically.
- **Acceptance criteria:**
  1. Cone: a Huge creature whose box overlaps the cone by >= 5% of its volume is in the target set (pick a case printed by `p04_cone_sampling.py`).
  2. Line: a creature whose box only touches the line's side face (zero-volume intersection) is not in the target set.
  3. Cube: same as 2 for a cube face.
- **Depends on / unblocks:** SPELL-Q-01 decides the rule; SPELL-D-03 relies on touching != inside.
- **Tests pinning current behaviour:** none found by name asserting boundary-touch inclusion; re-run `tests/test_aoe*.py`.
- **Arena impact:** `aim_candidates`/`aim_coverage` consume the same test, so menus and coverage numbers shift slightly.
- **Known in:** new.
- **Size:** S/M — an exact cone-vs-box test (or a much denser sample) and a strict-overlap SAT.

#### SPELL-D-06 — Enforce self-targeting restrictions in the engine, with the RAW default (self allowed)
- **Status:** open
- **Type / severity:** DEVIATION — S3
- **SRD:** p.102 "Targeting Yourself": "If a spell targets a creature of your choice, you can choose yourself, unless the creature must be hostile or specifically a creature other than you."
- **Current behaviour:** `SpellAction.can_target_self` defaults to `False` (`src/models/action.py:154`; loader default `src/loaders/stat_block_loader.py:396`), the reverse of RAW's default. And the flag is enforced by **nobody** in the engine: `resolve_spell` never reads it (only `cannot_cause_self_damage`, `src/combat/combat_system.py:424`). It is read only by the arena menu (`src/arena/action_space.py:285`) and the web client's click handler (`web/static/js/input.js:83-85`). So the engine accepts a spell on its own caster even when the spell forbids it (Vampiric Touch: "siphon life force from others"), while the menu hides self for every spell that did not opt in (Magic Missile, Fire Bolt, Charm Person …). **Silent.**
- **Evidence:** `.srd_work/probes/SPELL/p06_target_self.py`:
  ```
  Vampiric Touch can_target_self = False | menu offers: ['Goblin']
  arena tool, Vampiric Touch on self -> True [{'target_id': 'wizard', 'hit': False, ...}]
  ```
- **Gap:** default: the caster may target themselves with a "creature of your choice" spell; a spell that requires a hostile creature or "a creature other than you" (or "others") must refuse its caster, in the engine, not only in a menu.
- **Acceptance criteria:**
  1. A spell flagged as excluding the caster (Vampiric Touch) cast at the caster raises `RuleViolation(INVALID_TARGET_RELATION)` with no slot spent.
  2. A spell with no restriction loaded from JSON without the flag can be cast on the caster (engine and menu agree).
  3. Arena `_spell_targets` and the engine give the same answer for every shipped single-target spell.
- **Depends on / unblocks:** SPELL-D-02 (Self range is the other self rule). A "must be hostile" restriction needs a hostility notion (team is the available proxy).
- **Tests pinning current behaviour:** web/arena tests that build menus for spells without the flag (e.g. `tests/arena/test_action_space*.py` if they assert the caster is absent); none found asserting engine acceptance.
- **Arena impact:** menu `_spell_targets` gains the caster for unrestricted spells (longer menus; changes menu-length telemetry); the tools layer gains a refusal for forbidden self-targets.
- **Known in:** new.
- **Size:** S — rename/invert to a "target restriction" field (`any` / `not_self` / `hostile_only`), enforce it in `resolve_spell`, migrate the JSON (Cure Wounds/Haste/Longstrider/Shield of Faith become default; Vampiric Touch → `not_self`).

#### SPELL-D-11 — Make a timed spell last its full duration (10 rounds = 10 of every creature's turns)
- **Status:** open
- **Type / severity:** DEVIATION — S3
- **SRD:** p.102 "Duration": "A spell's duration is the length of time the spell persists. A duration can be expressed in rounds, minutes, hours, or even years." p.90 "The Order of Combat": "A round represents about 6 seconds in the game world." (so 1 minute = 10 rounds)
- **Current behaviour:** a `lifetime` with `duration_rounds: N` is ticked on its holder's `TURN_END`, and the tick on the casting turn itself counts (`src/combat/lifetime_clock.py`, `LifetimeScope.tick`, `src/models/lifetime.py:119-128`). A concentration scope is held by the caster (`lifetime.py:59-63`), so Haste (`duration_rounds: 10`) expires at the end of the caster's turn in round 10 — before every creature after the caster in initiative gets its round-10 turn. A non-concentration duration is held by the *target* (`lifetime.py:64-67`), so its length depends on where the target sits in initiative. **Silent.**
- **Evidence:** `.srd_work/probes/SPELL/p11_duration_length.py` (Haste on an ally who acts after the caster):
  ```
  Haste cast in round 1
  ally turns with the extra action, by round: [1, 2, 3, 4, 5, 6, 7, 8, 9] -> 9 turns
  ```
- **Gap:** a spell lasting N rounds ends at the same initiative point N rounds after it was cast (common practice: the start of the caster's turn N rounds later), so every creature gets N turns under it.
- **Acceptance criteria:**
  1. Haste cast in round 1 on an ally acting after the caster: the ally gets the extra action on exactly 10 turns (rounds 1-10) and not in round 11.
  2. Same on an ally acting *before* the caster: rounds 2-11, i.e. still 10 turns.
  3. A 1-round effect cast on the caster's turn lasts until the start of the caster's next turn.
- **Depends on / unblocks:** TURN (skipped turns never emit `TURN_END`, so a skipped holder's scope never ticks — see cross-area note).
- **Tests pinning current behaviour:** lifetime-clock tests in `tests/` asserting expiry on the Nth `TURN_END` (grep `tick_lifetimes` / `duration_rounds`) will need updating.
- **Arena impact:** none in the study.
- **Known in:** new.
- **Size:** S/M — count rounds from the cast's initiative point (tick at the start of the *caster's* turn, starting the next round) rather than at the holder's turn end.

#### SPELL-D-15 — Refuse (or model) casting times longer than one action instead of treating them as one action
- **Status:** open
- **Type / severity:** DEVIATION — S3
- **SRD:** p.101 "Longer Casting Times": "When you cast a spell with a casting time longer than a single action or reaction, you must spend your action each turn casting the spell, and you must maintain your concentration while you do so".
- **Current behaviour:** `SpellAction.__post_init__` maps only ACTION / BONUS_ACTION / REACTION to a cost and falls back to `ACTION_COST` for everything else (`src/models/action.py:162-175`), so a 1-minute, 10-minute or 1-hour casting time (and `count` > 1 actions) resolves instantly for a single action. **Silent.**
- **Evidence:** `.srd_work/probes/SPELL/p13_casting_time.py`: `10-minute casting time -> 10 minutes | cost: ActionCost(actions=1, bonus_actions=0, reactions=0, movement=0.0)`.
- **Gap:** a spell with a longer casting time takes the caster's action on each turn of the casting time, requires concentration throughout (failure: spell fails, slot not spent), and takes effect only at the end. In a simulator that cannot sensibly run minutes of casting, the engine should at least refuse such casts in combat rather than collapse them to one action.
- **Acceptance criteria:**
  1. Loading/casting a spell with casting time `minute`/`hour` (or `action` with `count` > 1) in combat raises a named `RuleViolation` (or starts a multi-turn cast) — never resolves for one action.
  2. If modelled: a 2-round cast spends the action on two consecutive turns; a failed concentration save in between cancels it with no slot spent.
- **Depends on / unblocks:** SPELL-D-09 (concentration plumbing). Rituals (p.101) depend on this.
- **Tests pinning current behaviour:** none found.
- **Arena impact:** none (no shipped spell has a longer casting time).
- **Known in:** new.
- **Size:** S to refuse; L to model.

#### SPELL-D-16 — Never spend a spell slot on a cantrip
- **Status:** open
- **Type / severity:** DEVIATION — S3
- **SRD:** p.101 "Cantrips": "A cantrip is a spell that can be cast at will, without using a spell slot and without being prepared in advance. … A cantrip's spell level is 0."
- **Current behaviour:** `resolve_spell` validates the slot floor only `if action.spell_level` is non-zero, then spends a slot whenever `cast_level > 0` (`src/combat/combat_system.py:394-409`, `435-437`). A cantrip cast with `slot_level=3` (which the arena's `cast_spell` accepts, `src/arena/tools.py:277-284`, and the web forwards, `web/routers/combat.py:436`) silently burns a 3rd-level slot, and `ctx["slot_level"]` becomes 3 for any `scaling` in its program. **Silent.**
- **Evidence:** `.srd_work/probes/SPELL/p15_slots.py`: `Fire Bolt (cantrip) cast with slot_level=3 -> slots now {1: 4, 3: 1}`.
- **Gap:** a cantrip never consumes a slot and cannot be cast "at a higher level"; a slot level other than 0/None for a cantrip is refused (or ignored).
- **Acceptance criteria:**
  1. Fire Bolt with `slot_level=3` raises `RuleViolation(INVALID_TARGET_RELATION)` (or resolves as level 0) and spends no slot.
  2. Fire Bolt with `slot_level=None` or `0` resolves and spends no slot.
- **Depends on / unblocks:** none.
- **Tests pinning current behaviour:** none found.
- **Arena impact:** C1/C2 models could waste slots this way today; the menu offers only `[0]` for cantrips (`src/arena/action_space.py:297-313`), so it is a raw-condition-only path.
- **Known in:** new.
- **Size:** S.

#### SPELL-D-18 — Refuse an area aimed beyond range instead of silently moving it to the edge
- **Status:** open
- **Type / severity:** DEVIATION — S3

- **SRD:** p.101 "Range": "The target of a spell must be within the spell's range. … For a spell like fireball, the target is the point in space where the ball of fire erupts."

- **Current behaviour:** for a ranged sphere/cylinder/cube, `derive_aoe_origin` clamps an over-range aim point onto the edge of range (`clamp_to_range`, `src/spatial/range_check.py:41-58`, `150-153`) and `resolve_spell` casts there, spending the slot (`src/combat/combat_system.py:414-437`). The arena refuses such an aim before calling the engine (`_refuse_out_of_range_aim`, `src/arena/tools.py:323-346`), and the web client only sends in-range clicks (`web/static/js/input.js:69-80`), so the engine's own contract is the odd one out. **Silent** at the engine.

- **Evidence:** `.srd_work/probes/SPELL/p17_aoe_clamp.py`: `Fireball (150 ft) aimed at x=400 -> [('Orc at 150 ft', 27)] | slots {3: 1}`.

- **Gap:** an area's point of origin must be within range; an over-range aim is an illegal cast (refused, nothing spent), as it already is for creature targets with a point.

- **Acceptance criteria:**

  1. Fireball (150 ft) aimed 400 ft away raises `RuleViolation(OUT_OF_RANGE)`; slot and action unspent.

  2. Aimed exactly at range + half the caster's size → resolves at that point.

- **Depends on / unblocks:** lets the arena drop its duplicate guard (`_refuse_out_of_range_aim`) and the menu comment about clamping (`src/arena/action_space.py:503-506`).

- **Tests pinning current behaviour:** `tests/test_aoe_casting.py::...::test_target_beyond_range_is_clamped` (asserts clamping) — must be inverted.

- **Arena impact:** none in behaviour (the arena already refuses); removes a duplicated rule.

- **Known in:** ENGINE_MAP note; arena docstring (`tools.py:326-330`, review 2026-09-24 H-4).

- **Size:** S.

#### SPELL-D-21 — Let a cube be placed with its origin anywhere on a face, not only centred and facing away
- **Status:** open
- **Type / severity:** DEVIATION — S4

- **SRD:** p.103 "Cube": "You select a cube's point of origin, which lies anywhere on a face of the cubic effect."

- **Current behaviour:** `CubeVolume` puts the origin at the centre of the near face and extends the cube along the caster→aim direction (`src/spatial/aoe.py:266-305`, `derive_aoe_origin`, `src/spatial/range_check.py:155-156`). The caster cannot slide the cube sideways along its face (e.g. a Thunderwave flush to one side) or orient a ranged cube independently of where they stand.

- **Evidence:** code reading of `CubeVolume._build` (centre = origin + forward·half); no orientation/offset input exists on `resolve_spell` (`src/combat/combat_system.py:343-351`).

- **Gap:** cube placement = a point of origin on any face (offset within the face) plus a facing; for a Self cube the origin must lie on the caster (SPELL-D-02).

- **Acceptance criteria:** 1. Thunderwave can be placed so its origin is at a face corner region (offset half a side), catching a creature 7 ft to the caster's side that the centred cube misses. 2. The centred placement remains available.

- **Depends on / unblocks:** SPELL-D-02, SPELL-D-04.

- **Tests pinning current behaviour:** cube tests in `tests/test_aoe*.py` assume face-centred origin.

- **Arena impact:** menu option count for cubes grows.

- **Known in:** new.

- **Size:** S/M — an optional in-face offset on the aim.

### COND — Conditions, ability checks, saves, vision and hiding (SRD pp.76–87, 93–94, 358–359)

#### COND-D-01 — Stop treating the unconscious condition as death
- **Status:** open
- **Type / severity:** DEVIATION — S2 (silent)
- **SRD:** p.359 "Unconscious": "Attack rolls against the creature have advantage. Any
  attack that hits the creature is a critical hit if the attacker is within 5 feet".
  An unconscious creature is a live, attackable creature.
- **Current behaviour:** `Entity.is_alive()` returns False whenever an UNCONSCIOUS marker is
  present, at any HP (`src/models/entity.py:144-149`). Consequences:
  `CombatSystem.get_enemies`/`get_alive_entities` drop it
  (`src/combat/combat_system.py:648-669`); `sides_standing` counts its side as gone
  (`src/combat/turn_manager.py:30-43`), so the fight ends; the arena never offers it as
  a target (`src/arena/action_space.py:639-641`, heuristic `features.py:139,180,216`).
  `resolve_attack` itself does not check `is_alive`, so the engine would accept the
  attack if asked. Silent.
- **Evidence:** `.srd_work/probes/COND/unconscious_is_dead.py`:
  ```
  B hp=100/100 conditions=['unconscious']
  B.is_alive() = False
  enemies of A = []
  combat state after A ends turn = ENDED
  log tail = 'R1T1 [A] wins the battle!'
  ```
- **Gap:** an unconscious creature at >0 HP (Sleep, a knockout) stays an enemy that can
  be targeted, and does not by itself end the fight. Whether a side whose every member
  is unconscious has lost is a **design decision** for the simulator (no SRD rule ends
  combat); it belongs with the 0-HP "downed but present" work in
  `docs/current/ENTITY_LIFECYCLE_DECISIONS.md` and ATK-Q-01. This entry is about the
  **condition** at >0 HP; the 0-HP state (a creature at 0 HP should *gain* unconscious,
  and must not act) is ATK-D-01/ATK-D-02, and the occupied-space consequence is
  MOVE-D-03.
- **Acceptance criteria:**
  1. Apply unconscious to a full-HP enemy → it remains in `get_enemies(attacker)`.
  2. An attack on it from 5 ft resolves with advantage (and, with COND-M-02, crits).
  3. The match does not end on the unconscious condition alone unless the recorded
     win-condition decision says so (test pins whichever is decided).
  4. A creature at 0 HP is unaffected by this change (still handled by ATK lifecycle).
- **Depends on / unblocks:** ATK-D-01 / ATK-Q-01 (decide `is_alive` vs "can act" vs "is
  defeated" as separate predicates; once 0 HP applies unconscious, `is_alive` cannot
  mean "not unconscious" any more). MOVE-D-03 shares the predicate. Unblocks COND-M-02's
  unconscious half.
- **Tests pinning current behaviour:** none found that apply the UNCONSCIOUS marker
  (grep `unconscious` in `tests/`); arena tests assert `not is_alive()` only after 0 HP
  (`tests/arena/test_match.py:138,183,200`).
- **Arena impact:** `action_space.py` attackable filter, heuristic `is_alive` guards and
  the observation `alive` field must use the new "defeated" predicate.
- **Known in:** ATK-D-01/ATK-Q-01 touch the same predicate from the 0-HP side; CODEBASE_REVIEW
  §4.5 mentions binary `is_alive()` only for 0 HP.
- **Size:** M — split the predicate; audit every `is_alive()` caller (engine + arena).

#### COND-D-04 — Refuse a charmed creature's attack or harmful spell at its charmer instead of wasting it
- **Status:** open
- **Type / severity:** DEVIATION — S2 (silent)
- **SRD:** p.358 "Charmed": "A charmed creature can't attack the charmer or target the
  charmer with harmful abilities or magical effects."
- **Current behaviour:** `charmed.json` cancels `ATTACK_DECLARED` when the defender is the
  bound charmer. (1) `resolve_attack` spends the action *before* resolving
  (`src/combat/combat_system.py:323-336`) and a cancelled attack returns
  `(False, 0, None)` with no log line (`src/combat/attack_resolver.py:68-71`): the
  illegal attack is paid for and reported as a miss. (2) Spell attacks (Fire Bolt) are
  cancelled the same way after the slot/action is spent. (3) Save-based harmful spells
  aimed at the charmer (Sacred Flame) resolve in full — no rule sees them, and a
  `cancel` on `SPELL_CAST` is ignored anyway (`src/combat/spell_resolver.py:60-65`
  discards the emit result; see COND-M-05).
- **Evidence:** `.srd_work/probes/COND/charmed.py`:
  ```
  weapon attack on charmer -> result=(False, 0, None), actions 1->0, new log lines=[]
  10x Sacred Flame at charmer -> charmer hp 100 -> 78
  Fire Bolt (spell attack) at charmer -> hit=False damage=0 actions left=0
  ```
- **Gap:** targeting the charmer with an attack or a harmful single-target ability is
  illegal: refuse it at the referee (a `RuleViolation`, nothing spent), like other
  illegal actions.
- **Acceptance criteria:**
  1. Charmed creature `resolve_attack` on its charmer → `RuleViolation`, action not spent.
  2. Same for a single-target harmful spell (attack or save): refused, slot not spent.
  3. Attacking a different creature, or a non-charmed creature attacking the charmer,
     is unaffected.
  4. A beneficial spell on the charmer (Cure Wounds) is allowed.
- **Depends on / unblocks:** a pre-spend legality hook (a "declare" check the referee runs
  before paying costs) and a notion of "harmful" for spells (does the program deal
  damage / impose a condition / force a save). AoE inclusion is COND-Q-01.
- **Tests pinning current behaviour:** `tests/rules/entity_effects/conditions/test_charmed.py::test_attack_against_charmer_is_cancelled`,
  `tests/test_condition_wiring.py::test_charm_binding_cancels_attack_on_the_charmer`
  (event-level cancellation; may stay valid if the referee also refuses).
- **Arena impact:** menus (`action_space.py`/`enumeration.py`) should not offer the charmer
  as a target; the free-text/raw conditions get a refusal code (a new taxonomy code or
  `invalid_target_relation`). The prompt says illegal actions are rejected
  (`src/arena/interfaces.py` "A referee enforces the rules") — today this one is not.
- **Known in:** charmed.json `_note` (social-check part only); new for the waste/spell
  parts.
- **Size:** M — pre-spend legality check + "harmful" classification.

#### COND-D-03 — Make petrified's resistance one instance that does not stack
- **Status:** open
- **Type / severity:** DEVIATION — S3 (silent)
- **SRD:** p.359 "Petrified": "The creature has resistance to all damage." p.358: "If
  multiple effects impose the same condition on a creature, each instance of the
  condition has its own duration, but the condition's effects don't get worse." p.97
  "Damage Resistance and Vulnerability": "Multiple instances of resistance or
  vulnerability that affect the same damage type count as only one instance."
- **Current behaviour:** petrified's rider multiplies every `DAMAGE_INCOMING` entry by 0.5
  (`rules/entity_effects/conditions/petrified.json`, `modify_damage` in
  `src/spells/blocks/event_mod.py:38-57`). Each application installs its own rider, and
  the global `damage_resistance_rule` applies a separate 0.5. Multipliers compound.
- **Evidence:** `.srd_work/probes/COND/petrified_stacking.py` (flat 20 slashing):
  ```
  petrified once               (RAW 10)      hit=True damage=10
  petrified twice (2 sources)  (RAW 10)      hit=True damage=5
  resistant + petrified        (RAW 10)      hit=True damage=5
  ```
- **Gap:** resistance is a property (has / hasn't, per damage type), applied once; two
  petrify sources, or petrified plus innate resistance, still halve once.
- **Acceptance criteria:**
  1. Petrified twice, 20 slashing → 10.
  2. Slashing-resistant and petrified, 20 slashing → 10.
  3. Petrified and vulnerable to slashing, 20 → 20 (resistance and vulnerability both
     apply once: ×0.5 ×2).
- **Depends on / unblocks:** **ATK-D-03** (count resistances once, fixed order) owns the
  general fix, including the petrified-plus-innate-resistance case; this entry keeps the
  condition-specific half: two instances of petrified must not stack (p.358 "effects
  don't get worse"), and petrified should *grant* resistance into the set ATK-D-03's
  rule reads instead of multiplying on its own. See also
  `docs/current/COMPOSITE_DAMAGE_DESIGN.md`.
- **Tests pinning current behaviour:** `tests/rules/entity_effects/conditions/test_petrified.py::TestPetrifiedDamageResistance`
  (asserts the 0.5 rider; single-instance, so still correct after the fix).
- **Arena impact:** heuristic damage estimates against petrified/resistant targets.
- **Known in:** ATK-D-03 (stacking with innate resistance).
- **Size:** S–M — depends on how ATK lands per-entity granted resistances.

#### COND-D-06 — Bind frightened to its source and apply its disadvantage only while the source is in line of sight
- **Status:** open
- **Type / severity:** DEVIATION — S3 (silent)
- **SRD:** p.358 "Frightened": "A frightened creature has disadvantage on ability checks
  and attack rolls while the source of its fear is within line of sight." "The creature
  can't willingly move closer to the source of its fear."
- **Current behaviour:** `rules/entity_effects/conditions/frightened.json` grants
  disadvantage on every attack the holder makes, unconditionally. No source is bound
  (unlike charmed's `charmer` binding), so neither the line-of-sight test nor the
  movement restriction can ever be written. Silent: disadvantage persists when the source
  is dead, gone, or behind a wall.
- **Evidence:** `.srd_work/probes/COND/misc_conditions.py`:
  `(2) frightened B attacks A (no fear source bound) -> (False, True)`; the rule JSON has no
  `instance_fields`/`bindings` reference.
- **Gap:** the frightened instance records its source; disadvantage applies only while
  that source is within line of sight of the holder (and, if the source is dead/removed,
  not at all).
- **Acceptance criteria:**
  1. `apply_condition frightened` with `bindings: {source: event.caster}` → holder has
     disadvantage attacking anyone while the source is visible.
  2. Source dies (or leaves the battlefield) → no disadvantage.
  3. Two frightened instances from two sources → disadvantage while either is in sight.
  4. (Once LoS exists) an obstruction between holder and source → no disadvantage.
- **Depends on / unblocks:** line of sight (COND-M-07 / SPELL-M-01's obstruction model;
  until then "in line of sight" can be approximated as "source alive and present", a
  recorded simplification). The movement half is **MOVE-M-07**, which needs this
  binding. Ability-check half needs COND-M-06.
- **Tests pinning current behaviour:** none found.
- **Arena impact:** none beyond heuristic severity.
- **Known in:** frightened.json `_note` ("implemented unconditionally; RAW ... line of
  sight").
- **Size:** S for the binding + source-alive guard; LoS is part of COND-M-07.

### MON — Monster stat blocks and legendary creatures (SRD pp.254–260)

#### MON-D-01 — Enforce legendary-action timing: only at the end of another creature's turn
- **Status:** open
- **Type / severity:** DEVIATION — S2
- **SRD:** p.260 "Legendary Actions": "Only one legendary action option can be used at a
  time and only at the end of another creature's turn."
- **Current behaviour:** `CombatSystem.resolve_legendary_action`
  (`src/combat/combat_system.py:452-556`) checks only that the entity has a pool, that the
  action is tagged (`legendary_action_cost > 0`) and that the pool can afford it
  (`:483-492`). It deliberately skips `_assert_active` and has no notion of *whose* turn
  it is, whether that turn is ending, or whether combat has even started. It succeeds
  **silently** on the legendary creature's own turn, in the middle of another creature's
  turn, and in `CombatState.SETUP` before `start_combat`. The turn loop
  (`src/combat/turn_manager.py:80-147`) has no end-of-turn window in which a legendary
  action could be offered; the only caller is the web WebSocket handler
  (`web/routers/combat.py:503-596`), which forwards one at any moment. (The browser
  client never sends that message: `grep -rn "legendary" web/static web/templates` finds
  nothing, so today only the library API and a hand-written WS message reach it. This
  is why the entries below are S2, not S1.)
- **Evidence:** `.srd_work/probes/MON/probe_legendary.py` (shipped `stone_golem.json`):
  ```
  current turn: Stone Golem
  1 own-turn legendary Slam: ALLOWED -> (True, 10, {...})
  current turn: Goblin
  2 mid-goblin-turn legendary Slam x3 in a row: ALLOWED -> [True, True, True]
  6 legendary Slam before start_combat (state=CombatState.SETUP): ALLOWED -> (True, 10, {...})
  ```
- **Gap:** RAW permits a legendary action only after another creature's turn ends (before
  the next turn starts), never on the creature's own turn, and only during combat.
- **Acceptance criteria:**
  1. With the golem active, `resolve_legendary_action(golem, …)` raises `RuleViolation`
     (NOT_YOUR_TURN-style code) and the pool is unchanged.
  2. Before `start_combat`, it raises.
  3. During the goblin's turn, before `end_turn`, it raises; in the window opened by the
     goblin's `end_turn` (after TURN_END, before the next TURN_START) it succeeds.
  4. See MON-Q-01 for how many may be used in one window.
- **Depends on / unblocks:** needs an "end-of-turn window" in the turn loop — the same
  off-turn decision point the reactions framework needs (**TURN-M-01**, shared
  dependency; opportunity attacks MOVE-M-01 ride on it). Unblocks MON-M-01.
- **Tests pinning current behaviour:** none found (no test mentions `legendary`).
- **Arena impact:** none today (legendary actions are not an arena tool; the prompt says
  "not modelled", `src/arena/interfaces.py:75-76`). Becomes the arena's first off-turn
  decision point when MON-M-01 lands.
- **Known in:** ENGINE_MAP lead ("no such guard"); new as a recorded entry.
- **Size:** M — a turn-phase state on `TurnManager`/`CombatSystem` (e.g. "between turns,
  after X's turn") that `resolve_legendary_action` checks.

#### MON-D-02 — Refuse legendary actions from an incapacitated, dead or surprised creature
- **Status:** open
- **Type / severity:** DEVIATION — S2
- **SRD:** p.260 "Legendary Actions": "it can't use them while incapacitated or otherwise
  unable to take actions. If surprised, it can't use them until after its first turn in
  the combat."
- **Current behaviour:** `resolve_legendary_action` (`src/combat/combat_system.py:483-494`)
  never inspects conditions or HP. A stunned golem and a golem at 0 HP
  (`is_alive() == False`) both act **silently**.
- **Evidence:** `.srd_work/probes/MON/probe_legendary.py`:
  ```
  3 stunned golem legendary Slam: ALLOWED -> (True, 10, {...})
  4 0-HP golem legendary Slam (is_alive=False): ALLOWED -> (True, 10, {...})
  ```
- **Gap:** incapacitated (and anything that implies it: paralyzed, petrified, stunned,
  unconscious) or dead → no legendary actions; surprised → none until after its first
  turn.
- **Acceptance criteria:**
  1. Golem with STUNNED (or INCAPACITATED / PARALYZED / PETRIFIED / UNCONSCIOUS) →
     `resolve_legendary_action` raises; pool unchanged.
  2. Golem at 0 HP → raises.
  3. (After surprise exists) a surprised golem cannot use one before its first turn ends.
- **Depends on / unblocks:** surprise is absent (TURN-M-04). Use the single "is
  incapacitated / can take actions" predicate of **COND-M-05** rather than a local list,
  and the 0-HP rule of ATK-D-01.
- **Tests pinning current behaviour:** none found.
- **Arena impact:** none today.
- **Known in:** new.
- **Size:** S — one guard using COND-M-05's predicate.

#### MON-D-03 — Range-check legendary attacks like ordinary attacks
- **Status:** open
- **Type / severity:** DEVIATION — S2
- **SRD:** p.259 "Melee and Ranged Attacks" (an attack has its listed reach/range); p.260
  legendary action options are ordinary attacks/actions taken off-turn.
- **Current behaviour:** the attack branch of `resolve_legendary_action`
  (`src/combat/combat_system.py:496-506`) calls `_attack_resolver.resolve` directly and
  never calls `check_attack_range`, which `resolve_attack` does at `:322`. A 5-ft
  "Legendary Slam" **silently** hits a target 200 ft away. (Spell branch: range is
  checked only when a `target` point is passed, `:523-525` — the same shape as
  `resolve_spell`; see cross-area note.)
- **Evidence:** `.srd_work/probes/MON/probe_legendary.py`:
  ```
  5 reach-5 legendary Slam at 200 ft: ALLOWED -> (True, 10, {...})
  5b same range via normal resolve_attack (Slam): REFUSED (RuleViolation: Stone Golem cannot use Slam: Goblin is out of range (192.5 ft, max 5 ft))
  ```
- **Gap:** a legendary attack must obey the attack's reach/range.
- **Acceptance criteria:**
  1. Golem at x=0, goblin at x=200: legendary "Legendary Slam" raises the same
     out-of-range `RuleViolation` as `resolve_attack`, and the pool is unchanged.
  2. Goblin adjacent: it resolves.
- **Depends on / unblocks:** —
- **Tests pinning current behaviour:** none found.
- **Arena impact:** none today.
- **Known in:** new.
- **Size:** S — route the legendary attack through the same validation as `resolve_attack`
  (ideally one shared validate-then-resolve path, so the two cannot drift again).

#### MON-D-05 — Stop legendary-only options being used as ordinary actions
- **Status:** open
- **Type / severity:** DEVIATION — S2
- **SRD:** p.260 "Legendary Actions": legendary actions are "special actions … outside its
  turn"; the option list is separate from the Actions section (p.259 "Actions").
- **Current behaviour:** `Action.legendary_action_cost` is documented as "> 0 → usable only
  as a legendary action" (`src/models/action.py:55`; also
  `CREATURE_DEFINITION_GUIDE.md` attack-field table), but nothing enforces it.
  `resolve_attack` (`src/combat/combat_system.py:297-338`) accepts the stone golem's
  "Rock Hurl" on the golem's own turn for an ordinary action; such an action also gets
  the default 1-action cost because the loader only overrides cost when `cost` is
  authored (`src/loaders/stat_block_loader.py:288-295`). The arena's attack tool lists
  every `AttackAction` including these (`src/arena/tools.py:434-438`;
  `src/arena/action_space.py:316-318`), so an arena golem could pick them. **Silent.**
- **Evidence:** `.srd_work/probes/MON/probe_legendary.py`:
  ```
  Rock Hurl legendary_action_cost: 2 cost: ActionCost(actions=1, ...)
  7 legendary-only Rock Hurl via resolve_attack on own turn: ALLOWED -> ((True, 18, {...}), 'resources now', ActionResources(actions=0, ...))
  ```
- **Gap:** a legendary option is not one of the creature's actions; the engine should
  refuse it on the normal path (a legendary option that *is* an ordinary action —
  "The dragon makes a tail attack" — is expressed by pointing at that action, not by
  making the legendary copy usable as an action).
- **Acceptance criteria:**
  1. `resolve_attack(golem, goblin, rock_hurl)` on the golem's turn raises; resources
     unchanged.
  2. The arena attack menu/tool for the golem does not list "Legendary Slam" or
     "Rock Hurl".
  3. `resolve_legendary_action` still accepts them (subject to MON-D-01..MON-D-04).
- **Depends on / unblocks:** MON-M-01 (a proper legendary-option list would make the flag
  unnecessary).
- **Tests pinning current behaviour:** none found.
- **Arena impact:** the attack tool, `action_space._owned_attacks`, `enumeration` and the
  heuristic would need to filter legendary-only actions (or the model should keep them
  in a separate list). No current scenario uses a legendary creature.
- **Known in:** new.
- **Size:** S — a guard in the ordinary attack/spell paths plus a filter in the arena.

#### MON-D-07 — Make the creature loader reject what it does not understand
- **Status:** open
- **Type / severity:** DEVIATION — S2
- **SRD:** pp.254-259 (a stat block's Size, Speed, Skills, Senses, Condition Immunities,
  Actions … are all rules-bearing). Project rule: CLAUDE.md §2.5 "Fail loudly, early, and
  specifically … at the JSON loaders".
- **Current behaviour:** `StatBlockLoader.from_dict` (`src/loaders/stat_block_loader.py:124-195`)
  reads a fixed set of keys with `data.get(...)` and never looks at the rest, so every
  SRD field the engine lacks is accepted and dropped **silently**:
  - any unknown top-level key (`speed`, `skills`, `senses`, `condition_immunities`,
    `challenge_rating`, `type`, `lair_actions`, `legendary_resistance`, a typo …);
  - unknown or abbreviated ability keys (`"str": 19`) → the score defaults to 10
    (`:134-142`);
  - an unknown `size` string → MEDIUM (`:157-161`; already its own entry, **MOVE-D-04**),
    unlike every other enum in the loader,
    which goes through `_enum_lookup` and raises;
  - an action whose `type` is not `attack`/`spell` (`"melee"`, `"multiattack"`, a typo)
    becomes a generic `Action(ActionType.ABILITY)` with **no damage and no program**
    (`:405-412`) — a no-op that nothing can resolve except
    `resolve_legendary_action`'s log line (`src/combat/combat_system.py:554-556`), and
    which the arena never lists (`src/arena/tools.py:434-438` filters to `AttackAction`).
  - `legendary_actions` keys other than `count_per_round` (`:177-179`).
- **Evidence:** `.srd_work/probes/MON/probe_recharge_loader.py` and
  `probe_loader_abbrev.py`:
  ```
  size 'Hgue' -> CreatureSize.MEDIUM (no error)
  unknown/SRD keys accepted silently; perception bonus = 0 (SRD block says +4) | walking speed = 30 (SRD says 40)
  action 'Multiattack' loaded as Action / ActionType.ABILITY, program=[], damage=[]
  action 'Bite' loaded as Action / ActionType.ABILITY, program=[], damage=[]
  legendary_actions.options / lair_actions / legendary_resistance: accepted silently
  abilities {'str':19,'dex':8,'con':16} -> AbilityScores(strength=10, dexterity=10, constitution=10, ...)
  ```
- **Gap:** a creature transcribed from the SRD loads as a different creature with no
  warning (wrong scores, no attacks, no immunities). Until each SRD field is supported,
  the loader should refuse it by name, so the gap is visible (CLAUDE.md §1 "decline
  loudly").
- **Acceptance criteria:**
  1. `from_dict({... "speed": 40})` (or any key not in the declared schema) raises
     `ValueError` naming the key and listing the accepted keys; keys starting `_` stay
     allowed as commentary (the block-program convention).
  2. `size: "Hgue"` raises naming the valid sizes.
  3. `abilities: {"str": 19}` raises naming the six valid keys.
  4. An action with `type: "melee"` raises naming the valid types (`attack`, `spell`, and
     any explicit no-op type the project chooses to keep).
- **Depends on / unblocks:** each MISSING entry then adds its key to the schema. Action-level
  strict keys overlap **ATK-M-06** (weapon keys dropped); `skills` overlaps COND-M-06 and
  `senses` COND-M-07; size is MOVE-D-04. This entry is the creature-level umbrella: do
  the top-level key schema and the abilities/action-`type` checks here, and let the
  others land their own fields.
  Model on `spells.validate` (declared fields, did-you-mean).
- **Tests pinning current behaviour:** none found for the fallbacks. Check that every
  shipped creature and the guide examples (`tests/test_authoring_guides.py:79`) still
  load: today's shipped files use only known keys (checked: all ten JSONs under
  `examples/creatures/`).
- **Arena impact:** none (scenarios build stat blocks in Python, `src/arena/scenarios.py`).
- **Known in:** CODEBASE_REVIEW E4 fixed enum/JSON errors, not unknown keys; new.
- **Size:** S-M — a declared key schema for the creature/action dicts.

#### MON-D-08 — Validate saving-throw proficiency names (SRD writes "Dex +5")
- **Status:** open
- **Type / severity:** DEVIATION — S2
- **SRD:** p.256 "Saving Throws": "A saving throw bonus is the sum of a monster's relevant
  ability modifier and its proficiency bonus".
- **Current behaviour:** the loader stores each `saving_throws` entry verbatim
  (`src/loaders/stat_block_loader.py:192-193`), and
  `StatBlock.get_saving_throw_bonus` adds proficiency only when the *exact lower-case
  full* name is a key (`src/models/stat_block.py:86-91`). `"DEX"`, `"Dexterity"` or
  `"con"` load without error and never add proficiency. **Silent** wrong numbers on every
  save that creature makes (`src/utils/saving_throw.py:40`) and in the heuristic's save
  estimate (`src/arena/heuristic/estimate.py:209`).
- **Evidence:** `.srd_work/probes/MON/probe_recharge_loader.py`:
  ```
  saving_throws ['DEX','Wisdom','con'] stored as {'DEX': 1, 'Wisdom': 1, 'con': 1} -> dex save bonus 0 wis 0 con 0 (prof 3 expected on each)
  ```
- **Gap:** the proficiency the author declared must apply, or the load must fail.
- **Acceptance criteria:**
  1. `saving_throws: ["dexterity"]`, PB 3, DEX 10 → `get_saving_throw_bonus("dexterity") == 3`
     (today's behaviour, keep).
  2. `saving_throws: ["DEX"]` either normalises to `dexterity` (bonus 3) or raises naming the
     six valid names — never loads with bonus 0.
  3. `saving_throws: ["dexterity", "dexterity"]` or `["luck"]` raises.
- **Depends on / unblocks:** MON-D-07 (same validation style).
- **Tests pinning current behaviour:** none found.
- **Arena impact:** none directly; heuristic save estimates become correct for such content.
- **Known in:** new. (The guide lists the valid values but nothing checks them.)
- **Size:** S.

#### MON-D-04 — Validate a legendary action before spending the pool
- **Status:** open
- **Type / severity:** DEVIATION — S3
- **SRD:** p.260 "Legendary Actions" (a creature spends legendary actions by *using* an
  option).
- **Current behaviour:** `entity.legendary_actions.spend(...)` runs at
  `src/combat/combat_system.py:494`, **before** the attack branch raises "Legendary attack
  action requires a defender" (`:497-498`), before the AoE "requires a target point"
  error (`:512-516`) and before the spell-slot check (`:527-537`). A refused legendary
  action still drains the pool. Loud (raises), but with a silent side effect.
- **Evidence:** `.srd_work/probes/MON/probe_legendary.py`:
  ```
  8 legendary attack with defender=None: REFUSED (ValueError: Legendary attack action requires a defender)
  8 pool before=3 after=1
  ```
- **Gap:** an action that is refused must not consume a resource (the same invariant
  `resolve_spell` documents at `:410-411`).
- **Acceptance criteria:**
  1. `resolve_legendary_action(golem, rock_hurl)` with no defender raises and
     `legendary_actions.remaining` stays 3.
  2. Same for an AoE spell with no target point, and for a levelled spell with no slot.
- **Depends on / unblocks:** fold into the MON-D-03 shared validation path.
- **Tests pinning current behaviour:** none found.
- **Arena impact:** none.
- **Known in:** new.
- **Size:** S — move the `spend` after validation.

#### MON-D-06 — Refill legendary actions when the creature's turn comes round even if it can't act
- **Status:** open
- **Type / severity:** DEVIATION — S3
- **SRD:** p.260 "Legendary Actions": "A creature regains its spent legendary actions at
  the start of its turn."
- **Current behaviour:** the refill subscriber is on TURN_START
  (`src/combat/combat_system.py:276-286`), but `TurnManager.end_turn` skips a creature
  with a `_SKIP_CONDITIONS` condition without emitting TURN_START for it
  (`src/combat/turn_manager.py:12-27`, `:115-133`). A legendary creature that was stunned
  through its turn never refills; when the stun ends it continues with whatever was left.
  **Silent.**
- **Evidence:** `.srd_work/probes/MON/probe_legendary.py` case 9:
  ```
  9 pool after Rock Hurl on goblin's turn: 1
  9 now current: Goblin round 2
  9 pool after golem's (skipped) turn passed: 1 (RAW: regained at start of its turn -> 3)
  ```
- **Gap:** an incapacitated creature still has a turn (it just cannot act), so its
  start-of-turn effects — including the refill — still happen.
- **Acceptance criteria:**
  1. Golem spends 2 legendary actions, is stunned before its turn, its turn passes:
     `remaining == 3` afterwards.
- **Depends on / unblocks:** **TURN-D-01** (incapacitated creatures get no
  TURN_START/TURN_END because their turn is skipped); fixing that fixes this. Do not special-case it here.
- **Tests pinning current behaviour:** none found for legendary; skip behaviour is pinned
  by turn-manager tests (see TURN findings).
- **Arena impact:** none today.
- **Known in:** ENGINE_MAP lead (skipped turns); new for legendary.
- **Size:** S once the TURN fix lands.

## Appendix A. Intentional deviations (do not fix)

#### MOVE-I-01 — Measure movement continuously in feet (no grid; Euclidean diagonals)
- **Status:** open
- **Type / severity:** INTENTIONAL — S4
- **SRD:** p.91 "Movement and Position": "you can move a distance up to your speed"; SRD
  5.1 contains no grid rules (the 5-ft square / diagonal counting is a PHB variant
  sidebar not in the SRD).
- **Current behaviour:** `move_entity` charges the straight-line Euclidean distance,
  held to 0.1 ft (`combat_system.py:695-702,727-740`); a 5-ft diagonal costs 7.1 ft.
- **Evidence:** `tests/test_movement.py::TestMoveEntity::
  test_move_cost_is_continuous_not_rounded_to_a_grid`.
- **Gap:** none against SRD 5.1; recorded so nobody "fixes" it toward the grid variant.
- **Acceptance criteria:** n/a (keep the tests above green).
- **Depends on / unblocks:** MOVE-D-02 (rounding of the charge).
- **Tests pinning current behaviour:** the continuous-cost and float-drift tests.
- **Arena impact:** none (prompt states "there is no grid", `interfaces.py:65`).
- **Known in:** settled 2026-09-19 — `src/models/action_resources.py` module docstring,
  `move_entity` docstring, ENGINE_MAP "Already-recorded rulings".
- **Size:** —

#### MOVE-I-02 — Treat touching creatures as adjacent, not overlapping (strict overlap)
- **Status:** open
- **Type / severity:** INTENTIONAL — S4
- **SRD:** p.92 "Moving Around Other Creatures": "you can't willingly end your move in its
  space" (only ending *in* a space is forbidden; standing next to one is ordinary).
- **Current behaviour:** `BoundingBox.overlaps` is strict with `OVERLAP_EPSILON_FT = 1e-6`
  (`src/spatial/geometry.py`); a Medium creature may stand 5 ft centre-to-centre from
  another.
- **Evidence:** `tests/test_movement.py::TestMoveEntity::test_move_adjacent_to_a_creature_is_allowed`,
  `test_adjacent_to_a_large_creature_is_allowed`, `test_adjacency_survives_float_noise`,
  `test_a_small_real_overlap_still_blocks`.
- **Gap:** none; recorded decision (the fix that made it match RAW).
- **Acceptance criteria:** n/a.
- **Depends on / unblocks:** MOVE-D-01's path test must reuse the same strict semantics
  (grazing a creature's edge is not entering its space).
- **Tests pinning current behaviour:** those above.
- **Arena impact:** menus use the same test (A29 re-measured coverage).
- **Known in:** CODEBASE_REVIEW A29 (fixed 2026-09-30); CLAUDE.md §9 2026-09-30.
- **Size:** —

## Appendix B. Open questions (need a ruling before implementation)

#### TURN-Q-01 — Decide whether identical creatures share one initiative roll
- **Status:** open
- **Ruling:** _pending: the maintainer fills this in._
- **Type / severity:** OPEN QUESTION — S4
- **SRD:** p.90 "Initiative": "The GM makes one roll for an entire group of identical creatures, so each member of the group acts at the same time."
- **Current behaviour:** every combatant rolls separately (`src/combat/initiative.py:55`). Grouping is not expressible (no group id), and "act at the same time" has no meaning in a one-actor-at-a-time engine (`active_entity_ids` is a singleton, `src/combat/combat_system.py:615-629`; its docstring anticipates a "Phase 2" of simultaneous allied turns).
- **Evidence:** code read.
- **Decision needed:** (a) keep individual rolls (common table practice for small groups, and fairer for a benchmark); (b) one roll per identical group, members acting consecutively in an order the controller picks; (c) a scenario-level option. Precedent: the user already requires a shared roll for group summons like Conjure Woodland Beings ("a small extra field on the summoning block", ENTITY_LIFECYCLE_DECISIONS C1). Most VTTs default to individual rolls with an optional group toggle (common practice, not RAW).
- **Acceptance criteria:** once decided, e.g. "two goblins tagged as one group always have the same initiative total and adjacent slots".
- **Depends on / unblocks:** summoning (`ENTITY_LIFECYCLE_DECISIONS.md`).
- **Tests pinning current behaviour:** none.
- **Arena impact:** turn order in multi-creature scenarios; none under (a).
- **Known in:** ENTITY_LIFECYCLE_DECISIONS C1 (summons only).
- **Size:** S.

#### TURN-Q-02 — Decide what ends a fight in which no creature can act
- **Status:** open
- **Ruling:** _pending: the maintainer fills this in._
- **Type / severity:** OPEN QUESTION — S4
- **SRD:** p.90 "The Order of Combat": "Once everyone has taken a turn, the fight continues to the next round if neither side has defeated the other." p.90 "Combat Step by Step" 5: "Repeat step 4 until the fighting stops."
- **Current behaviour:** when every creature due a turn has a skip-condition, `TurnManager.end_turn` ends the combat (`src/combat/turn_manager.py:118-122`, log "Combat ended", no winner), even when all are conscious and at full HP and their conditions would expire. Today this guard is also the only way out of a mutual stun, because durations never expire while turns are skipped (TURN-D-01). (The related case — a side whose only creatures are *unconscious* at full HP counting as defeated — is COND-D-01, with the win-condition decision there and in ATK-Q-01.)
- **Evidence:** `.srd_work/probes/TURN/p07_unconscious_ends_fight.py` (second scenario; the first corroborates COND-D-01):
  ```
  B hp: 30 is_alive: False
  state after A's end_turn: ENDED
  log tail: ['Combat started!', 'wins the battle!']
  both stunned (both alive, HP full): state ENDED | log tail: Combat ended
  ```
- **Decision needed:** once TURN-D-01 gives incapacitated creatures their turns, the engine no longer needs this guard for termination. Options: (a) keep cycling turns (durations expire, saves are retried) and let the caller's round cap end a true deadlock (the arena already has one: `_decide_result` `reason = "round_cap"`, `src/arena/match.py:81-93`); (b) end the fight as a draw when no creature can act and no timed effect is pending; (c) keep today's immediate end. Common practice: a fight in which everyone is held is not over; the GM narrates until someone recovers.
- **Acceptance criteria:** once decided, e.g. "both sides stunned for 1 round → both recover and combat is still ACTIVE in round 2", and "both permanently paralyzed → the arena's round cap ends it as a draw".
- **Depends on / unblocks:** TURN-D-01.
- **Tests pinning current behaviour:** none found for the all-skipped branch (`tests/arena/test_match.py::test_round_cap_ends_a_stalemate_as_a_draw` covers the arena cap).
- **Arena impact:** match outcome (`result.reason`) in rare mutual-disable states.
- **Known in:** new.
- **Size:** S once decided.

#### TURN-Q-03 — Decide whether (and how) improvised actions are allowed
- **Status:** open
- **Ruling:** _pending: the maintainer fills this in._
- **Type / severity:** OPEN QUESTION — S4
- **SRD:** p.93 "Actions in Combat": "When you describe an action not detailed elsewhere in the rules, the GM tells you whether that action is possible and what kind of roll you need to make, if any, to determine success or failure."
- **Current behaviour:** no improvised actions: every action must be a stat-block `AttackAction` or a known `SpellAction` (`src/arena/tools.py` four tools; C1's grammar `src/arena/free_text.py` rejects any other verb as `UNKNOWN_ACTION`).
- **Evidence:** code read.
- **Decision needed:** this is GM adjudication by definition. Options: (a) not supported, and say so in the arena prompt (today the shared prompt invites models to "use your own judgment and knowledge of 5e", `src/arena/interfaces.py:78-79`, without listing which 5e actions exist); (b) a fixed menu of common improvisations (shove an object, throw sand…) as data; (c) an LLM-as-GM adjudicator (breaks determinism; out of scope for the benchmark). Common practice in simulators/VTTs: (a).
- **Acceptance criteria:** under (a), the arena prompt names the standard actions that are not available (Dash, Disengage, Dodge, Help, Hide, Ready, Search, Use an Object) alongside the existing "Not modelled" line.
- **Depends on / unblocks:** none.
- **Tests pinning current behaviour:** `tests/arena/test_interfaces.py` (prompt byte-identity across conditions).
- **Arena impact:** prompt text only under (a).
- **Known in:** new.
- **Size:** S under (a).

#### MOVE-Q-01 — Decide what happens when forced movement is blocked
- **Status:** open
- **Ruling:** _pending: the maintainer fills this in._
- **Type / severity:** OPEN QUESTION — S3
- **SRD:** Thunderwave: "is pushed 10 feet away from you" (no rule for obstacles). p.92
  "Moving Around Other Creatures": "you can't willingly end your move in its space" (the
  only occupancy rule, and it is about willing moves).
- **Current behaviour:** `push_entity` raises `RuleViolation(DESTINATION_BLOCKED)` if the
  final footprint overlaps a creature (`combat_system.py:780`, `_check_movement_overlap`)
  and ignores everything on the way.
- **Evidence:** code read; `tests/test_movement.py::TestPushEntity::test_push_still_checks_overlap`.
- **Gap / decision needed:** when a push is blocked by a creature (or later a wall), does
  the target (a) stop at the last unoccupied point along the push line, (b) not move at
  all, (c) pass through to the first clear point, or (d) the push fails loudly (today)?
  Common table practice (not RAW): (a) — the creature moves as far as it can and stops;
  "pushed up to N feet" wordings (e.g. Shove's "5 feet away") are read the same way.
  Also: does a push need a clear *path* (MOVE-D-01) or only a clear endpoint?
- **Acceptance criteria:** once ruled, a test per case: target at x=5 pushed 10 ft
  toward a creature at x=12 → ends at the ruled point; never raises mid-spell.
- **Depends on / unblocks:** MOVE-M-08.
- **Tests pinning current behaviour:** `test_push_still_checks_overlap`.
- **Arena impact:** none until a push spell is in a scenario.
- **Known in:** new.
- **Size:** S once ruled.

#### MOVE-Q-02 — Decide how a mid-turn speed change alters the movement left this turn
- **Status:** open
- **Ruling:** _pending: the maintainer fills this in._
- **Type / severity:** OPEN QUESTION — S3
- **SRD:** p.91 "Movement and Position": "you can move a distance up to your speed ...
  you deduct the distance of each part of your move from your speed". p.91 "Using
  Different Speeds": "subtract the distance you've already moved from the new speed. The
  result determines how much farther you can move." p.93 "Dash": "Any increase or
  decrease to your speed changes this additional movement by the same amount."
- **Current behaviour:** the budget is set once per turn from the stat block
  (`entity.py:287-293`); a speed change mid-turn either does nothing (Longstrider cast on
  self leaves 30 ft, probe p04) or, via `add_resource`, adds a flat amount.
- **Evidence:** `.srd_work/probes/MOVE/p04_speed_spells.py`: `Longstrider: movement right
  after casting on self: 30.0 (RAW speed 40 now; 30 unspent)`.
- **Gap / decision needed:** model "movement left" as *(current speed [+ Dash
  increments]) − distance moved this turn* (recomputed when speed changes — the reading
  the two quoted rules support by analogy), or keep a budget that is only adjusted by
  explicit deltas. Precedent: most tables (and the Dash wording) apply the delta
  immediately; a speed drop below distance already moved leaves 0, not negative.
- **Acceptance criteria:** with the ruling stated, e.g.: speed 30, moved 10, gains +10 →
  30 left; speed 30, moved 25, Ray-of-Frost-style −10 → 0 left (not −5); restrained
  after moving 10 → 0 left.
- **Depends on / unblocks:** MOVE-M-03 (it decides the data model); Dash (TURN).
- **Tests pinning current behaviour:** `tests/rules/entity_effects/test_longstrider.py`
  (TURN_START top-up shape).
- **Arena impact:** `movement_remaining` in tool results (`tools.py:553`) and menus
  follow whichever model is chosen.
- **Known in:** new.
- **Size:** S (decision) — implementation is part of MOVE-M-03.

#### MOVE-Q-03 — Decide whether a 0-HP or dead creature still occupies its space
- **Status:** open
- **Ruling:** _pending: the maintainer fills this in._
- **Type / severity:** OPEN QUESTION — S3
- **SRD:** p.92 "Space": "A creature's space is the area in feet that it effectively
  controls in combat". The SRD gives no rule for a body; a dead creature is no longer a
  creature for most purposes (it is treated as an object by e.g. spells that target
  "a corpse"). A 0-HP PC is unconscious and dying, not dead (p.97 "Dropping to 0 Hit
  Points").
- **Current behaviour:** a creature at 0 HP leaves the occupancy roster
  (`is_alive()` False, `entity.py:149`), so others may stand in its space.
- **Evidence:** `tests/test_movement.py::TestMoveEntity::test_dead_entity_does_not_block_movement`;
  code read.
- **Gap / decision needed:** (a) dead bodies don't block (today) — common practice, often
  with the space counting as difficult terrain at the DM's option; (b) a *dying* (0-HP,
  not dead) creature is still a creature and blocks like MOVE-D-03; this matters only
  once dying/death saves exist (TURN/COND area — today 0 HP = out of the fight, see
  ENTITY_LIFECYCLE_DECISIONS).
- **Acceptance criteria:** after the ruling: a dead (not merely dying) body at x=10 → A
  may end at x=10 (or not); a dying 0-HP creature → blocked.
- **Depends on / unblocks:** dying/death saves (TURN/COND).
- **Tests pinning current behaviour:** `test_dead_entity_does_not_block_movement`.
- **Arena impact:** menus follow `is_destination_clear`.
- **Known in:** ENTITY_LIFECYCLE_DECISIONS ("downed but present") is the related decision
  record.
- **Size:** S once ruled.

#### ATK-Q-01 — Decide which creatures die at 0 HP and which fall unconscious
- **Status:** open
- **Ruling:** _pending: the maintainer fills this in._
- **Type / severity:** OPEN QUESTION — S2
- **SRD:** p.98 "Monsters and Death": "Most GMs have a monster die the instant it drops to 0 hit points, rather than having it fall unconscious and make death saving throws. Mighty villains and special nonplayer characters are common exceptions; the GM might have them fall unconscious". p.98 "Knocking a Creature Out" (an attacker's choice).
- **Current behaviour:** every creature is treated the same: at 0 HP it is out of the fight (`is_alive()` False), but nothing marks it dead (ATK-D-01) and healing brings it back (ATK-D-02). In practice this is "everyone follows Monsters and Death, except they can be healed".
- **Evidence:** `src/models/entity.py:144-149`; `.srd_work/probes/ATK/p04_zero_hp.py`. The sample content mixes PC-style sheets (`examples/creatures/characters/*.json`) and monsters (`goblin.json`, `stone_golem.json`), with no field telling them apart.
- **Gap / decision needed:** RAW leaves this to the GM. Options:
  - (a) **A per-creature flag** (e.g. `death_rule: "dies_at_zero" | "death_saves"`). Default monsters to dies-at-zero and characters to death-saves. This follows the SRD's own default and its stated exception.
  - (b) **Everyone dies at 0.** Simplest, and fits a short-fight simulator and the arena's current win condition. A deliberate deviation for PCs, to record in Appendix A.
  - (c) **Everyone uses death saves.** Most faithful for PCs. It lengthens fights and changes arena match-end semantics.

  Common table practice is (a). The decision also has to say what ends a match (all of a side dead, or all of it at 0 HP).
- **Acceptance criteria:** the ruling is recorded (Appendix A or a decision doc), and ATK-D-01 / ATK-D-02 / ATK-M-10 are written against it.
- **Depends on / unblocks:** unblocks ATK-D-01, ATK-D-02, ATK-M-10, ATK-M-11.
- **Tests pinning current behaviour:** see ATK-D-01.
- **Arena impact:** decides whether the arena changes at all. `PREREGISTRATION`'s win/loss and HP metrics assume 0 HP = out.
- **Known in:** related to `docs/current/ENTITY_LIFECYCLE_DECISIONS.md` (death vs dismissal, "downed but present"), which records the user's note that "a creature reaching 0HP by any means almost always means death".
- **Size:** S to decide.

#### ATK-Q-02 — Decide how cover is determined from the battlefield
- **Status:** open
- **Ruling:** _pending: the maintainer fills this in._
- **Type / severity:** OPEN QUESTION — S2
- **SRD:** p.94 "Making an Attack": "The GM determines whether the target has cover". p.96 "Cover": "A target has half cover if an obstacle blocks at least half of its body." "…a creature, whether that creature is an enemy or a friend." "…only when an attack or other effect originates on the opposite side of the cover."
- **Current behaviour:** not modelled (ATK-M-04). The battlefield is continuous feet with no grid (settled ruling 2026-09-19, ENGINE_MAP). Creatures are axis-aligned boxes, and nothing else occupies space.
- **Evidence:** see ATK-M-04.
- **Gap / decision needed:** RAW leaves the degree of cover to the GM, so an automated referee needs an explicit, deterministic rule. Options:
  - (a) **Derive from geometry.** Trace from the attacker to the target and measure how much of the target's box intervening creature boxes hide. Map ≥ ½ to half and ≥ ¾ to three-quarters. For precedent, the DMG's optional grid method traces lines from one corner of the attacker's square to the corners of the target's square, with 1–2 lines blocked giving half cover and 3–4 giving three-quarters. That method is a grid variant, though, and out of scope under the no-grid ruling. It could be adapted to box corners.
  - (b) **Creatures-only half cover.** Any creature whose box intersects the line between centres grants half cover, never more. Simple, deterministic, and close to common table practice for "shooting past a creature".
  - (c) **Authored terrain only.** Cover comes from authored obstacles with a declared degree; creatures never grant it. This departs from RAW, which names creatures.

  Precedent: RAW and common table practice treat cover as a GM judgement. The DMG grid method is the only published mechanical aid, and it is a variant (not RAW, not SRD).
- **Acceptance criteria:** the ruling is recorded (CODEBASE_REVIEW or Appendix A), and ATK-M-04's tests are written against it.
- **Depends on / unblocks:** unblocks ATK-M-04's determination half. Related to line of sight / "can see" (COND).
- **Tests pinning current behaviour:** none.
- **Arena impact:** whatever rule is chosen must be explainable in `interfaces.py` prompt text, because models reason about it.
- **Known in:** new.
- **Size:** S to decide. M to L to implement, depending on the option.

#### SPELL-Q-01 — Decide how much of a creature must be inside an area to be affected
- **Status:** open
- **Ruling:** _pending: the maintainer fills this in._
- **Type / severity:** OPEN QUESTION — S3
- **SRD:** p.102-103 "Areas of Effect": "Every area of effect has a point of origin … A spell's effect expands in straight lines from the point of origin." Spells say "each creature in a 20-foot-radius sphere" without defining partial occupancy.
- **Current behaviour:** any positive overlap of the creature's bounding box counts (`get_targets_in_aoe`, `src/combat/combat_system.py:844-871`); touching also counts for most shapes (SPELL-D-05).
- **Evidence:** a rules decision; the shape inconsistency is evidenced under SPELL-D-05.
- **Gap / decision needed:** SRD 5.1 has no grid (ruling 2026-09-19) and no rule for a creature partly inside an area. Common interpretations: (a) **any part of the creature's space inside** the area → affected (the engine's choice; also common gridless table practice and the DMG "templates" convention, which is not in the SRD); (b) the creature's **centre point** inside; (c) a threshold such as half its space. Zero-area contact (touching) is excluded under all three.
- **Acceptance criteria:** once decided, state the rule in `aoe.py`'s module docstring and pin it with one boundary test per shape (inside by a sliver → in/out per the rule; touching → out).
- **Depends on / unblocks:** SPELL-D-05.
- **Tests pinning current behaviour:** none specific.
- **Arena impact:** menu option sets (`aim_candidates`) depend on it.
- **Known in:** new.
- **Size:** S once decided.

#### COND-Q-01 — Decide whether a charmed creature may include its charmer in an area effect
- **Status:** open
- **Ruling:** _pending: the maintainer fills this in._
- **Type / severity:** OPEN QUESTION — S3
- **SRD:** p.358 "Charmed": "can't attack the charmer or target the charmer with harmful
  abilities or magical effects."
- **Current behaviour:** no check; a charmed caster's Fireball catches the charmer
  normally (AoE targets are collected by geometry in `get_targets_in_aoe`).
- **Evidence:** code reading of `src/combat/combat_system.py` `resolve_spell` AoE branch
  and `charmed.json` (only `ATTACK_DECLARED`).
- **Gap / decision needed:** whether choosing an area that includes the charmer counts as
  "targeting" it. Common interpretations: (a) strict RAW reading — an area spell targets
  a point, not creatures, so it is allowed; (b) common table practice — a charmed
  creature won't knowingly catch its charmer, so the aim is illegal (or the charmer is
  excluded). The SRD text does not settle it (it never defines "target" for areas
  here); this is a maintainer ruling.
- **Acceptance criteria:** once ruled, a test aims a charmed caster's Fireball to include
  the charmer and asserts either a refusal or normal resolution.
- **Depends on / unblocks:** COND-D-04.
- **Tests pinning current behaviour:** none found.
- **Arena impact:** AoE aim enumeration would filter aims that include the charmer under
  (b).
- **Known in:** new.
- **Size:** S once ruled.

#### COND-Q-02 — Decide when a creature may hide, and when hiding survives approaching
- **Status:** open
- **Ruling:** _pending: the maintainer fills this in._
- **Type / severity:** OPEN QUESTION — S3
- **SRD:** p.80 "Hiding": "The GM decides when circumstances are appropriate for hiding."
  "You can't hide from a creature that can see you clearly". p.81: "if you come out of
  hiding and approach a creature, it usually sees you. However, under certain
  circumstances, the GM might allow you to stay hidden as you approach a creature that is
  distracted".
- **Current behaviour:** no hiding (COND-M-09).
- **Evidence:** RAW text above.
- **Gap / decision needed:** (1) what makes hiding possible in a simulator — common table
  practice: only while heavily obscured, invisible, or out of line of sight / behind
  total or three-quarters cover from that observer; (2) whether moving toward an enemy
  ends hiding automatically (common practice: yes, unless the observer can't see the path,
  e.g. darkness without darkvision); (3) whether "distracted" ever applies (common
  simulator practice: never). These are labelled table practice, not RAW.
- **Acceptance criteria:** once ruled, tests encode each rule (e.g. "Hide refused while
  in plain view of an enemy without obstruction").
- **Depends on / unblocks:** COND-M-07, COND-M-09.
- **Tests pinning current behaviour:** none.
- **Arena impact:** determines whether Hide appears in menus at a given position.
- **Known in:** new.
- **Size:** S once ruled (the ruling shapes COND-M-09).

#### COND-Q-03 — Decide when the Help action's ability-check form applies
- **Status:** open
- **Ruling:** _pending: the maintainer fills this in._
- **Type / severity:** OPEN QUESTION — S4
- **SRD:** p.79 "Working Together": "A character can only provide help if the task is one
  that he or she could attempt alone ... a character can help only when two or more
  individuals working together would actually be productive." p.93 "Help": "the
  creature you aid gains advantage on the next ability check it makes to perform the task
  you are helping with".
- **Current behaviour:** no Help action, no ability checks (COND-M-06).
- **Evidence:** RAW text above.
- **Gap / decision needed:** which checks in the simulator can be helped (common practice:
  any check the helper could itself make — e.g. Athletics to escape a grapple — and not
  contests the helper isn't party to, though tables differ on grapple escape). The attack
  form of Help (advantage on an ally's first attack vs a target within 5 ft of the
  helper) is mechanical and belongs to TURN.
- **Acceptance criteria:** once ruled, a test helps an ally's grapple-escape check and
  asserts advantage (or refusal).
- **Depends on / unblocks:** COND-M-06; TURN's Help action.
- **Tests pinning current behaviour:** none.
- **Arena impact:** whether Help-with-a-check is ever offered.
- **Known in:** new.
- **Size:** S once ruled.

#### MON-Q-01 — Decide how many legendary actions may be used at one turn's end
- **Status:** open
- **Ruling:** _pending: the maintainer fills this in._
- **Type / severity:** OPEN QUESTION — S3
- **SRD:** p.260 "Legendary Actions": "Only one legendary action option can be used at a
  time and only at the end of another creature's turn."
- **Current behaviour:** unlimited; the probe used three in a row mid-turn (MON-D-01 case 2).
- **Evidence:** as MON-D-01.
- **Gap / decision needed:** "one at a time" can be read as (a) one legendary action per
  other creature's turn end, or (b) any number at a turn's end, resolved one after
  another (not simultaneously). Common published guidance (Sage Advice / designer
  commentary, not RAW) and most table practice take reading (a): one legendary action at
  the end of each other creature's turn. Reading (b) lets a creature dump its whole pool
  after a single turn.
- **Acceptance criteria:** once decided, e.g. under (a): after the goblin's turn ends, the
  first legendary action succeeds and a second in the same window raises.
- **Depends on / unblocks:** MON-D-01 (the window must exist first).
- **Tests pinning current behaviour:** none found.
- **Arena impact:** shapes how many off-turn decisions an agent gets.
- **Known in:** new.
- **Size:** S once the window exists.

## Appendix C. Rules verified correct (don't 'fix' these)

### TURN
- Round/turn cycle: `ROUND_START` → turns in initiative order → `ROUND_END`, order fixed from round to round (`src/combat/turn_manager.py:61-113`; `InitiativeTracker` sorts once at `add_entity`, `src/combat/initiative.py:45-64`).
- Initiative roll = d20 + DEX modifier, highest first (`src/combat/initiative.py:22-29,55-62`) — modifiers and ties aside (TURN-M-03, TURN-D-02).
- Your turn: move and action in either order, movement split freely before/after the action — movement is a per-turn budget spent by any number of `move_entity` calls (`src/combat/combat_system.py:688-757`, `src/models/action_resources.py`). Forgoing everything: `end_turn` is always legal (`src/arena/action_space.py:215` `can_end_turn = True`).
- One action per turn by default: `ActionResources.actions = 1`, enforced by `can_afford` before `resolve_attack`/`resolve_spell` spend (`combat_system.py:323-330,385-391`), refusal code `action_economy_spent` (`_shortfall_code`, `:53-69`).
- Bonus actions: only actions that declare a `bonus_actions` cost consume one; one per turn; the default counter of 1 is harmless because nothing without a bonus-action feature can spend it (`src/models/action_resources.py:46`, loader `_parse_cost`).
- Reaction counter: one, regained at the start of the owner's own turn (not at round start) — `rules/global/action_economy_refill.json` on `TURN_START` with `rebind_target: event.entity`.
- Refill timing: actions, bonus actions, reactions and movement reset to stat-block defaults at the creature's own `TURN_START`; unspent movement does not carry over (`Entity.refill_resources`, `src/models/entity.py:287-293`). Turn-start top-ups (Haste, Longstrider) run after the refill (rider priority −10 vs global 0, `src/spells/blocks/triggers.py:92-95`; `EventBus` higher priority first, `src/combat/event_bus.py`).
- Casting time → cost: action, bonus action and reaction casting times map to the right cost (`src/models/action.py:159-175`); longer casting times are SPELL-D-15.
- Turn ownership: every on-turn action path refuses a creature whose turn it is not (`_assert_active`, `combat_system.py:631-646`, code `not_your_turn`).
- Combat end: the fight ends as soon as at most one side is left — after an action (`_decides_fight`), and after end-of-turn and start-of-turn effects (`turn_manager.py:94-97,112-113,143-144`) — consistent with "the fight continues … if neither side has defeated the other" (who counts as defeated: COND-D-01, ATK-Q-01, TURN-Q-02).

### MOVE
- Speed is the walking distance per round; the budget refills to the stat-block speed at
  each TURN_START and unspent movement does not carry over (`entity.py:287-293`,
  `rules/global/action_economy_refill.json`; probe p09: `next turn movement: 30`).
- Movement can be split freely before and after the action (p.91 "Breaking Up Your
  Move"): `move_entity` and `resolve_attack` spend independent resources (probe p09:
  `moved 10, attacked, moved 20: movement left 0.0 actions left 0`).
- Each part of a move is deducted from the budget and a move beyond it is refused with
  nothing spent (`combat_system.py:740-750`;
  `tests/test_movement.py::test_move_fails_insufficient_movement`).
- Only the active creature can move (`_assert_active`, `combat_system.py:715`).
- Cannot willingly end a move in another (conscious) creature's space, friend or foe;
  touching is legal (`_check_movement_overlap`, strict `BoundingBox.overlaps`, A29;
  MOVE-I-02).
- Size → space table matches p.92 exactly: Tiny 2.5, Small 5, Medium 5, Large 10, Huge 15,
  Gargantuan 20 (`src/models/creature_size.py:5-12`;
  `tests/test_entity_position.py::TestCreatureSize`). Larger creatures block more space
  (`test_large_entity_blocks_more_space`).
- A creature without a fly speed cannot move up through the air — refused loudly, not
  silently (`combat_system.py:716-726`; `test_a_voluntary_move_cannot_change_altitude`).
- Forced movement (`push_entity`) costs no movement and ignores turn order, as forced
  movement should (`combat_system.py:759-783`; `TestPushEntity`) — it only lacks callers
  (MOVE-M-08).
- Distance costs are continuous Euclidean feet with no float drift
  (`action_resources.py:61-70`; MOVE-I-01).
- Longstrider's +10 ft applies at the start of each of the target's turns, after the
  refill (probe p04: `movement at next turn start: 40`).
- Arena move enumeration (`src/arena/action_space.py:365-436`) only offers destinations
  that `is_destination_clear` accepts and the budget affords, and returns no options at
  < 1 ft of movement; it is a *subset* of legal moves by design, so it encodes no extra
  rule — every MOVE fix that lands in `move_entity`/`is_destination_clear` flows into it,
  except path legality and true cost (MOVE-D-01, MOVE-M-02), which `_clear_option_along`
  must adopt explicitly. The `move` tool passes straight to `move_entity`
  (`tools.py:549`).

### ATK
- p.94 Attack hits when d20 + bonus ≥ AC (`total >= defender.ac`, `src/spells/blocks/rolls.py:90`). Advantage and disadvantage together cancel to one d20 (`rolls.py:30-38`).
- p.94 Nat 20 always hits and is a critical hit; nat 1 always misses, whatever the bonus or AC (`rules/global/critical_hit.json`, `critical_miss.json`, read at `rolls.py:85-90`). Probe `p01_crit_formula.py`: `nat20 vs AC30 -> hit: True`, `nat1 +50 vs AC1 -> hit: False`. Pinned by `tests/test_critical_hits.py`, weapons and spells.
- p.94 Spell attack bonus = proficiency + spellcasting ability mod (+ modifiers) (`Entity.spell_attack_bonus`, `src/models/entity.py:405-413`). Spell save DC = 8 + prof + mod (`entity.py:393-402`).
- p.94 Monster attack bonuses as literal stat-block values (`bonus_to_hit`) are RAW for monsters. Only characters need derivation (ATK-M-05).
- p.94 "Choose a target… within your attack's range": an attack beyond `range_ft` is refused loudly with `OUT_OF_RANGE` (`src/spatial/range_check.py:62-86`), before resources are spent (`combat_system.py:322`).
- p.95 Reach is measured edge to edge between footprints, so a Large creature's size does not eat into its reach. The 5-ft default is `range_ft=5.0` (`range_check.py:62-80`, `src/models/action.py:116`). Touching is adjacency (A29).
- p.96 "Damage Rolls": damage is never negative. A formula that totals ≤ 0 deals nothing and creates no `Damage` (`src/spells/blocks/damage.py:90-91`; `Damage` rejects negatives, `src/models/damage.py:41-44`).
- p.96 "roll the damage once for all of them": the area spells shipped (Fireball, Burning Hands, Cone of Cold, Lightning Bolt, Thunderwave) use `roll_once` inside `for_each_target`, so one roll is shared (`src/spells/blocks/iterators.py`, `damage.py:64-71`). This depends on the author writing it (see the cross-area note and A37).
- p.96-97 Critical hits double all damage dice and add flat modifiers once (`multiply_formula` doubles dice terms only, `src/utils/dice.py:176-193`). Probe `p01`: `1d8+3` on a nat 20 rolls `2d8+3`. On-hit rider dice (e.g. Colossus Slayer) double too, because the trigger seeds `critical_hit` into its context (`src/spells/blocks/triggers.py:124-131`). An AoE shared roll never crits (correct: no attack roll).
- p.97 Damage types: `DamageType` has all 13 SRD types (`src/models/damage.py:8-23`). The loader rejects an unknown type with the valid list (`_enum_lookup`, `src/loaders/stat_block_loader.py:44-56`). The non-SRD `GENERIC` member is an engine fallback; see ATK-D-07.
- p.97 Resistance halves rounding down (`int(x*0.5)`, `src/spells/blocks/event_mod.py:57`); vulnerability doubles; immunity zeroes. A stat-block resistance + vulnerability to one type resolves halve-then-double (25 → 24), because the rule files install in sorted filename order. Correct, but fragile (ATK-D-03). Probe `p06`.
- p.97 Per-type modifiers on mixed damage: each `damage` block (one per weapon damage entry) is its own `DAMAGE_INCOMING` with one entry, so resistance/immunity/vulnerability apply per type on today's only path. Probe `p07` (c): 10 slashing + 6 fire vs immune-slashing/vulnerable-fire → 12. The `damage_list[0]` gating in `COMPOSITE_DAMAGE_DESIGN.md` is therefore latent, not live.
- p.97 Save-for-half halves rounding down (`amount // 2`, `damage.py:85-86`) before resistance applies (resistance runs later, on `DAMAGE_INCOMING`). That is RAW order.
- p.97 Healing adds to current HP and cannot exceed the maximum (`Entity.heal`, `src/models/entity.py:113-116`). Only the *reported* amount is wrong (ATK-D-06).
- p.96 HP lies in [0, max]: `take_damage` floors at 0 (`entity.py:110`); `heal` caps at max.
- p.98 Temporary HP: absorbed before HP with overflow carrying over; not added together (the higher is kept, a reasonable automatic "you decide"); not restored by healing; may exceed max HP; does not revive a 0-HP creature (`entity.py:99-138`). Probe `p05` lines 1, 2 and 5. Only the expiry semantics are wrong (ATK-D-04).
- p.63 Shield-like AC bonuses stack additively through `stat_modifiers` with stat `ac` (`entity.py:387-391`; Shield of Faith +2 works).
- p.77 Proficiency bonus is added once to spell attacks and DCs (never doubled anywhere).

### SPELL
- Spell level 0-9 validated at construction (`src/models/action.py:162-164`).
- Slot accounting: a slot of the cast level is spent; a slot below the spell's level is refused; an exhausted level is refused loudly **before** targeting, and an out-of-range/missing-target error spends nothing (`src/combat/combat_system.py:392-437`; probe `p20_correct_checks.py`: "Cannot cast Fireball (level 3) with a level-2 slot", "no level-3 spell slots remaining", 5th-level slot untouched). Using a higher slot is the caller's explicit choice (`slot_level`); the arena menu enumerates every affordable level (`src/arena/action_space.py:297-313`). Not an error that a level-3 cast with no 3rd-level slot is refused rather than auto-upcast.
- "Spell assumes the higher level": the cast level is threaded as `slot_level` into the program (`src/spells/context.py` `seed_context`) and drives `damage.scaling` (`src/spells/scaling.py`); `tests/test_upcasting.py` covers it.
- Known spells: `get_spell_for_entity` refuses a spell the creature does not know (`src/combat/combat_system.py:200-224`); both front ends go through it.
- Spell save DC = 8 + proficiency + spellcasting mod (+ `spell_save_dc` modifiers) (`src/models/entity.py:393-402`); spell attack bonus = proficiency + mod (+ modifiers) (`entity.py:404-413`). Probe: INT 16, prof 2 → DC 13, +5.
- Spell saves go through `SAVING_THROW_DECLARED` + `roll_saving_throw` with adv/dis cancelling and save modifiers (`src/spells/blocks/rolls.py:136-170`, `src/utils/saving_throw.py`) — only the concentration save bypasses it (SPELL-D-08).
- Spell attacks: d20 + bonus vs AC, adv/dis cancel, nat 20 / nat 1 via the global crit rules, `ATTACK_HIT` emitted (`src/spells/blocks/rolls.py:41-100`).
- Area damage is rolled once and shared by every target (`roll_once`, `src/spells/blocks/iterators.py:32-61`); half on a successful save rounds down and is applied before resistance (`blocks/damage.py:82-88`, then `DamageProcessor`); probe: 27 → 13, resistant 6.
- Sphere: radius from the point of origin, origin included, caster included if inside (`src/spatial/aoe.py:150-175`; probe: Fireball centred on the caster catches the caster) — matches p.103 "A sphere's point of origin is included".
- Cone width at distance d equals d (half-angle atan 0.5, `aoe.py:220-240`); length from the caster's edge; cones/lines always anchored on the caster (`src/spatial/range_check.py:146-148`). (Inclusion test issues: SPELL-D-03/04/05.)
- Line default width 5 ft and length from the caster's edge (`src/combat/combat_system.py:911-918`).
- Cylinder radius test exact in the ground plane, origin included (`aoe.py:178-217`); height issue is A38 / SPELL-M-09.
- Spell range measured from the caster's edge to the nearest point of the target (`check_single_target_range`, `src/spatial/range_check.py:92-118`), Touch = 5 ft reach — correct whenever it runs (it doesn't always: SPELL-D-01).
- Concentration DC = max(10, damage // 2) using the damage actually taken (after resistance, including any absorbed by temp HP) (`rules/global/concentration.json`, `DamageProcessor.apply_damage` total); one `DAMAGE_DEALT`, hence one save, per target per cast or attack, so separate sources (each Magic Missile dart, each Scorching Ray) each force their own save — matches "a separate saving throw for each source" (except rider damage, SPELL-D-12).
- A failed concentration save disposes the whole granted subtree (modifiers, riders, conditions) via the lifetime scope (`src/models/entity.py:332-369`); casting a second concentration spell does end the first (timing aside, SPELL-D-09).
- Instantaneous effects: damage/healing blocks outside a `lifetime` leave nothing to dispel (`blocks/state.py:_own` drops the handle) — matches p.102 "Instantaneous".
- Temporary HP from spells don't stack (keep the higher) and their revoke only strips what is left (`src/models/entity.py:118-138`).
- `cannot_cause_self_damage` exclusion is applied identically by the engine and the menu (`combat_system.py:424-425`, `action_space.py:515-516`) — the mechanism is sound; its default is the problem (SPELL-D-03).
- Rituals (p.101): out-of-combat (+10 minutes casting time); not modelled and not needed in combat — no entry beyond SPELL-D-15 (longer casting times).
- Known and Prepared Spells (p.100, light): `known_spells` is the single "fixed in mind" list; preparation is a between-rests activity outside combat — no entry.

### COND
- Ability modifier = (score − 10) // 2, scores validated 1–30
  (`src/models/ability.py:93-117`).
- Advantage/disadvantage: multiple sources collapse to one flag and any adv + any dis
  cancel to one d20, for attacks (`src/spells/blocks/rolls.py:30-38,62-74`) and saves
  (`src/utils/saving_throw.py:34-39`); `grant_advantage`/`grant_disadvantage` set booleans
  (`src/spells/blocks/event_mod.py:77-96`). `roll_with_advantage`/`disadvantage` keep the
  higher/lower of two d20s (`src/utils/dice.py:196-211`).
- Proficiency bonus added once to a proficient save (`src/models/stat_block.py:86-91`);
  skill expertise doubles it, no proficiency adds 0 (`src/models/skill.py:29-44`).
- Saving throw: d20 + ability mod (+ PB if proficient) + `saving_throw.<ability>` /
  `saving_throw.all` modifiers, success on total ≥ DC; no auto-success on a natural 20 or
  auto-fail on a 1, correct for SRD 5.1 saves (`src/utils/saving_throw.py:40-47`);
  `SAVING_THROW_DECLARED` lets rules grant adv/dis (`src/spells/blocks/rolls.py:148-163`).
- Conditions preamble: each application is its own `Condition` instance with its own
  scope/duration, removed by identity (`src/models/entity.py:155-166`,
  `src/spells/blocks/state.py:121-137`); two instances do not worsen flag-based effects,
  and ending one leaves the other working (`.srd_work/probes/COND/misc_conditions.py`
  (1): `(False, True)` with 2 markers and still `(False, True)` after one expired). The
  exception is petrified's multiplier (COND-D-03). Concentration-owned conditions end with
  concentration (`tests/test_condition_wiring.py::test_removed_when_concentration_drops`).
- Blinded: holder attacks with disadvantage, attackers have advantage (`blinded.json`);
  correct for creatures without special senses (senses are COND-M-07).
- Invisible: holder attacks with advantage, attackers have disadvantage (`invisible.json`);
  correct absent senses (COND-M-07) and hiding (COND-M-09).
- Charmed: the charmer is bound per application (`bindings: {charmer: event.caster}`), so
  two charmed creatures each refuse only their own charmer
  (`tests/rules/entity_effects/conditions/test_charmed.py::test_each_charmed_entity_tracks_own_charmer`).
  (Waste-vs-refuse and spells are COND-D-04.)
- Poisoned: holder's attacks have disadvantage (`poisoned.json`); the check half waits on
  COND-M-06. A poison effect can apply `poisoned` via `apply_condition` with a duration,
  and damage-over-time poisons can be written as a TURN_START/TURN_END trigger — the
  poisoned-condition interface to Poisons (pp.199-204) is adequate; diseases are not
  modelled (out of combat).
- Restrained: holder attacks with disadvantage, attackers have advantage, holder has
  disadvantage on DEX saves (`restrained.json`; `tests/test_save_advantage.py`). Speed 0 is
  MOVE-M-05.
- Paralyzed / stunned / petrified / unconscious / incapacitated: attacks *by* the holder are
  cancelled and attacks *against* the four non-plain ones have advantage (rule JSON;
  `.srd_work/probes/COND/autocrit_and_prone.py` shows adv 40/40 against paralyzed and
  unconscious).
- Petrified: a single petrified instance halves damage, rounding down via `int()` on
  non-negative amounts (`src/spells/blocks/event_mod.py:54-57`;
  `.srd_work/probes/COND/petrified_stacking.py` "petrified once" → 10 of 20).
- Deafened: marker only is correct today — its only bullet is ability checks needing
  hearing (COND-M-06).
- Condition riders are holder-agnostic (installed on the conditioned entity whatever the
  caster) (`src/spells/blocks/state.py:71-96`; `tests/test_condition_holder_agnostic.py`).

### MON
- p.254 Size Categories: Tiny 2.5, Small 5, Medium 5, Large 10, Huge 15, Gargantuan 20 ft
  (`src/models/creature_size.py:5-12`); the space feeds the bounding box and edge-to-edge
  reach (A29).
- p.255 Armor Class: a monster's AC is a listed number, so the flat `armor_class` int
  (`src/loaders/stat_block_loader.py:169`) is RAW for monsters; negative AC is rejected
  (`src/models/stat_block.py:74-75`). Character armor math is ATK-M-12.
- p.255 Hit Points: using the stated average as max HP is one of the two SRD options;
  HP < 1 is rejected (`stat_block.py:71-72`); current HP lives on `Entity`.
- p.256 Ability Scores: six scores, 1–30 enforced (`src/models/ability.py:27-40`);
  modifier `(score-10)//2` floors correctly (9 → −1, 1 → −5).
- p.256 Saving Throws: bonus = ability mod + PB when proficient (`stat_block.py:86-91`),
  plus `saving_throw.<ability>`/`.all` modifiers (`src/utils/saving_throw.py:40-46`) —
  correct given full lower-case names (MON-D-08) and a correct PB (MON-M-09).
- p.257 Damage vulnerability/resistance/immunity by type: loaded with a friendly enum error
  (`stat_block_loader.py:59-64`, `:180-188`; `tests/test_loader_damage_modifiers.py`) and
  applied per damage entry (rounding/order: ATK found-correct list).
- p.258 Spellcasting: slot table per level; spell save DC = 8 + PB + mod and spell attack =
  PB + mod (`src/models/entity.py:393-413`, cross-checked by ATK); casting with a higher
  slot the creature has is allowed and a slot below base level is refused
  (`src/combat/combat_system.py:394-407`).
- p.259 Psionics: "typically doesn't require any components" — no components are enforced
  for anyone (SPELL-M-07), so psionic casters behave correctly by default.
- p.259 "Hit"/"Miss" notation: a weapon `program` expresses a save-gated hit rider and a
  miss effect. Probe `.srd_work/probes/MON/probe_hit_riders.py` (Wolf bite, DC 11 STR or
  prone, plus a test-only "Miss: 3 acid"): `seed 0: hit=True damage=10 target
  conditions=['PRONE']`; `seed 1: hit=False damage=3 target conditions=[]`;
  `seed 3: hit=True damage=4 target conditions=[]` (saved). Literal monster `bonus_to_hit`
  is RAW for monsters (ATK found-correct). "Take average or roll": a damage entry with only
  `amount` deals the fixed average, one with `formula` rolls (`src/models/action.py:96-100`,
  `src/combat/attack_resolver.py:35`).
- p.259 Ammunition: "A monster carries enough ammunition to make its ranged attacks" —
  unlimited ammunition matches; the 2d4/2d10 count is an optional "you can assume".
- p.259 Equipment: "assume that it has the material components it needs" — consistent with
  components not being tracked.
- p.260 Legendary pool: integer pool with per-option cost, refused when the cost exceeds
  what remains (`src/models/legendary_actions.py:30-45`), refilled at the start of the
  creature's own turn (`combat_system.py:276-286`) — correct whenever that TURN_START fires
  (MON-D-06). A legendary action does not spend the creature's own action economy.

## Appendix D. Content blocked by missing mechanics (notes)

### TURN
- Fighter Extra Attack (`examples/creatures/characters/fighter.json`, level 5+) → TURN-M-02.
- Fighter Second Wind / Action Surge → TURN-M-13 (non-spell feature actions).
- Rogue Cunning Action (`characters/rogue.json`) → TURN-M-05/TURN-M-06/TURN-M-09 + TURN-M-13 (bonus-action Dash/Disengage/Hide).
- Goblin Nimble Escape (`goblin.json`) → TURN-M-06/TURN-M-09 + TURN-M-13.
- Barbarian Feral Instinct (advantage on initiative; acting while surprised) → TURN-M-03, TURN-M-04.
- Thief's Reflexes (two turns in round 1, second at initiative − 10, p.41) → initiative holds one slot per creature (`src/combat/initiative.py`).
- Expeditious Retreat (Dash as a bonus action) → TURN-M-05.
- Haste's extra action restricted to Attack (one weapon attack), Dash, Disengage, Hide, Use an Object → TURN-M-02, TURN-M-05, TURN-M-06, TURN-M-09, TURN-M-12 (today `examples/spells/haste.json` grants an unrestricted action — SPELL's call).
- Potions and magic items → TURN-M-12.
- Shield, Counterspell, Hellish Rebuke, Feather Fall → TURN-M-01 + SPELL-M-03.
- Opportunity attacks, Sentinel-like features, Polearm-style reactions → TURN-M-01 + MOVE-M-01.
- Lair actions on initiative count 20 (losing ties) → MON-M-01, TURN-D-02 (tie rule), TURN-M-03.
- Hold Person / Sleep / stun effects with timed or save-ended durations → TURN-D-01.

### MOVE
- Thunderwave's push (shipped spell, push silently dropped) → forced-movement block (MOVE-M-08).
- Ray of Frost's −10 ft speed (shipped cantrip, silently dropped) → speed modifiers (MOVE-M-03).
- Haste's doubled speed (shipped spell, known by the shipped Wizard) → speed multipliers (MOVE-M-03).
- Entangle, Web, Hold-style restraint; any grapple-applying monster → speed 0 enforcement (MOVE-M-05).
- Shove / trip attacks (wolf Bite "knocked prone") → stand-up / crawl (MOVE-M-04) + push (MOVE-M-08).
- Fear, Cause Fear, dragons' Frightful Presence → frightened movement guard (MOVE-M-07).
- Fly spell, any flying/swimming/climbing monster (harpy, dragons, sahuagin) → per-mode speeds (MOVE-M-09).
- Spike Growth, Grease, Plant Growth (difficult terrain zones) → terrain model (MOVE-M-02).
- Misty Step / Dimension Door (teleport) → a teleport block that skips path checks and OAs (MOVE-M-08 family).
- Expeditious Retreat / Cunning Action (Dash as bonus action) → Dash (TURN) + effective speed (MOVE-M-03).

### ATK
- Longbow, shortbow, crossbows, sling, and thrown weapons (dagger, handaxe, javelin, spear) → two-range bands, ATK-M-03; thrown melee-or-ranged use, ATK-M-01/ATK-M-06.
- Finesse, versatile, reach, heavy, loading, two-handed and ammunition weapons (most of the p.66 Weapons table) → ATK-M-06.
- Net (restrains on hit; one attack per action) → ATK-M-06 (special/loading-style limit) and a restrain-with-escape mechanic (ATK-M-08).
- Stone Golem (p.317) and many SRD monsters' "B/P/S from nonmagical attacks (that aren't silvered/adamantine)" resistances or immunities → ATK-M-13.
- Grappler feat (p.75), and grapple-with-escape-DC monster attacks (e.g. the Mimic's Adhesive, constrictor-style attacks) → ATK-M-08.
- Sneak Attack (needs a finesse or ranged weapon) → ATK-M-01 + ATK-M-06. Crit doubling of its dice already works through on-hit riders.
- Acid vial and Alchemist's Fire (improvised ranged attacks, 20 ft) → ATK-M-03 + ATK-M-06 (improvised).
- Mage Armor, Unarmored Defense (p.8), armor-wearing NPC sheets → ATK-M-12.
- Stoneskin, Rage and other resistance grants that may overlap a stat-block resistance → ATK-D-03.
- False Life, Heroism and other timed temp-HP grants from more than one source → ATK-D-04.
- Revivify / Raise Dead (raise a dead creature) → a dead state, ATK-D-01/ATK-D-02. Spare the Dying, healer's kit → ATK-M-10.

### SPELL
- Acid Splash ("one creature, or two creatures within 5 feet of each other") → no per-spell target count/adjacency constraint (SPELL-D-13); shipped as single-target.
- Cantrip damage (Acid Splash, Chill Touch, Eldritch Blast beams, Fire Bolt, Poison Spray, Ray of Frost, Sacred Flame) → no caster level (SPELL-M-04); the shipped 5th-level wizard's Fire Bolt stays 1d10.
- Chill Touch "can't regain hit points until the start of your next turn" and undead disadvantage → no heal-prevention effect and no creature types (`grep creature_type|humanoid|undead src` → nothing).
- Charm Person "a humanoid", "advantage if you or your companions are fighting it", ends "if you … do anything harmful to it", upcast extra targets → no creature types; no save-advantage-by-situation hook in the spell; no "harmed by caster's side" end trigger in `charmed.json` (COND); count scaling (SPELL-M-05).
- Cure Wounds "no effect on undead or constructs"; healing upcast → no creature types; `healing` has no `scaling` (A39 / SPELL-M-05).
- Guiding Bolt "the next attack roll made against this target before the end of your next turn has advantage" → expressible in principle (trigger + `grant_advantage` + lifetime) but not authored; no engine blocker beyond the duration-clock timing (SPELL-D-11).
- Haste: +2 AC, advantage on DEX saves and doubled speed are not authored (speed: MOVE-M-03); the extra action is a full generic action (`add_resource actions +1`), so it can cast a spell or make a full multi-attack → no restricted-action resource ("Attack (one weapon attack only), Dash, Disengage, Hide, Use an Object"); end-of-spell lethargy → no "can't move or act until after its next turn" effect on lifetime end.
- Longstrider, Ray of Frost speed effects → MOVE-M-03; Longstrider stacking → SPELL-D-19.
- Magic Missile / Scorching Ray / Eldritch Blast projectile counts → SPELL-D-13, SPELL-M-04, SPELL-M-05 (A39).
- Shield of Faith "up to 10 minutes", Longstrider / Rime Ward "1 hour" → their `lifetime` blocks set no `duration_rounds`, so they never expire by time (only by concentration loss / end_lifetime); harmless inside one fight, wrong if a match runs past 100 rounds. Data fix, no engine blocker (but see SPELL-D-11 for the clock).
- Thunderwave push 10 ft → MOVE-M-08; Thunderwave's Self cube can be dropped anywhere → SPELL-D-02.
- Lightning Bolt / Cone of Cold authored with `spell_range: feet 100/60`; SRD says "Self (100-foot line)" / "Self (60-foot cone)" → cosmetic (cones/lines are always caster-anchored by `derive_aoe_origin`), but the displayed range is wrong; `aoe.width_ft: 5` on Lightning Bolt is ignored (A38; default is also 5).
- Vampiric Touch recast heals twice → A36, root cause SPELL-D-09.
- Rime Ward → not an SRD 5.1 spell (project custom content); nothing to compare.
- Spells "that you can see" (Charm Person, Haste, Magic Missile…) → no vision/line-of-sight model (SPELL-M-01, cross-area).
- Bless/Bane/Hold Person (not shipped) → SPELL-D-10 (multi-target concentration) and SPELL-D-08 (save bonuses on the concentration save).
- Shield, Counterspell, Feather Fall (not shipped) → SPELL-M-03 (reaction casting).
- Revivify/Raise Dead (not shipped) → costed/consumed material components (SPELL-M-07) and the dying/dead model.
- Moonbeam/Spirit Guardians-style ongoing areas (not shipped) → cylinder height (SPELL-M-09, A38), rider damage not triggering concentration (SPELL-D-12), persistent emitters (ENTITY_LIFECYCLE_DECISIONS).

### COND
- Hold Person / Hold Monster → paralyzed auto-fail saves (COND-M-01), auto-crit (COND-M-02),
  end-of-turn repeat save on a skipped creature (TURN-D-01).
- Sleep → unconscious-at->0-HP treated as dead (COND-D-01); onset prone (COND-M-03).
- Shove / Thunderwave knock-prone / Trip-style attacks → prone attack modifiers and stand
  up (COND-M-03, MOVE-M-04), contests (COND-M-06, ATK-M-08).
- Grapple, Web, Entangle escape checks → ability checks/contests (COND-M-06), grappler
  tracking (COND-M-08).
- Cause Fear / Fear / dragon Frightful Presence → frightened source binding (COND-D-06).
- Invisibility / Greater Invisibility vs truesight/blindsight monsters, Darkness, Fog
  Cloud, Devil's Sight-style senses → vision model (COND-M-07).
- Rogue Cunning Action Hide, Skulker-style play → hiding (COND-M-09).
- Ghoul paralysis, Basilisk/Medusa petrification → COND-M-01, COND-M-02, COND-M-10.
- Halfling Lucky, Portent-style rerolls → no reroll hook: adv/dis rolls keep only the
  chosen die (`src/utils/dice.py:196-211`), so "reroll one of the two dice" cannot be
  written.
- Bless / Bane / Resistance (cantrip) on concentration checks → SPELL-D-08.
- Sickening Radiance, starvation, Berserker Frenzy → exhaustion levels (COND-M-04).

### MON
#### Shipped creatures vs SRD (engine-caused gaps vs authoring errors)
- **Goblin** (`examples/creatures/goblin.json`, SRD p.315). *Authoring errors* (fix the
  JSON, not the engine): AC 12 → SRD 15 (leather armor, shield); STR 10 → 8; Scimitar and
  Shortbow `1d6` → `1d6+2` (a flat formula gets no ability modifier added,
  `src/combat/attack_resolver.py:35`; from ATK's cross-area notes). *Engine-caused*:
  Shortbow 80/320 has one range (ATK-M-03); Nimble Escape needs bonus-action
  Disengage/Hide (TURN-M-06/MON-M-09 plus a bonus-action grant); Stealth +6 (COND-M-06);
  darkvision (COND-M-07); type humanoid (goblinoid) (MON-M-07).
- **Stone Golem** (`examples/creatures/stone_golem.json`, SRD p.317). *Authoring errors*:
  STR 20 → 22; `proficiency_bonus` 5 → +4 at CR 10 (MON-M-09); its legendary actions
  ("Legendary Slam", "Rock Hurl", `count_per_round: 3`) are invented — the SRD stone golem
  has none. It is the guide's legendary demo (`CREATURE_DEFINITION_GUIDE.md`); label it
  as non-SRD or move the demo to a made-up creature. *Engine-caused*: B/P/S immunity from
  nonmagical non-adamantine attacks (ATK-M-13); condition immunities
  charmed/exhaustion/frightened/paralyzed/petrified/poisoned (MON-M-06); Immutable Form,
  Magic Resistance, Magic Weapons (MON-M-04, ATK-M-13); Multiattack (MON-M-05); Slow
  (Recharge 5–6, MON-M-02) and its no-reactions / half-speed / one-attack /
  action-or-bonus-action effects (new effect blocks); darkvision (COND-M-07); construct
  type (MON-M-07).
- **Characters** (from ATK's cross-area notes, recorded here as owner of creature
  content; verified against the files): `characters/ranger.json` Shortsword is
  `SLASHING 1d6` (SRD: piercing, and `1d6+3` with DEX 16) and Shortbow `1d6` (→ `1d6+3`);
  `characters/paladin.json` "Sacred Flame" is an `attack` with `bonus_to_hit: 6` and
  `1d8+3` damage — RAW it is a DEX-save cantrip with no damage modifier, and not on the
  paladin list. All authoring errors; ATK-M-05 (derived bonuses) would prevent the
  missing-modifier class.

#### SRD monster coverage (what each needs that the engine lacks)
| Monster (SRD page) | Missing mechanics |
|---|---|
| Goblin (p.315) | Nimble Escape (bonus-action Disengage/Hide, TURN-M-06/MON-M-09); long range (ATK-M-03) |
| Wolf (p.393) | Pack Tactics (MON-M-04 + an ally-proximity query); Keen Hearing and Smell (COND-M-06). The prone-on-failed-save bite is expressible (found-correct probe); prone's effects are COND-M-03 |
| Ogre (p.336) | Javelin melee-or-ranged 30/120 (ATK-M-01, ATK-M-03); otherwise expressible |
| Owlbear (p.339-340) | Multiattack beak + claws (MON-M-05) |
| Giant Spider (p.379) | Web: Recharge 5–6 (MON-M-02), restrained with a DC 12 STR-check escape and a destructible web (COND-M-06, MON-M-08-style escape); Bite's "stable but poisoned … paralyzed" at 0 HP (ATK-M-10); climb (MOVE-M-09); blindsight (COND-M-07) |
| Ghoul (p.312) | Condition immunities (MON-M-06); Claws' paralysis "other than an elf or undead" (MON-M-07 type test) with an end-of-turn repeat save (not probed; a paralyzed holder gets no TURN_END, TURN-D-01) |
| Bandit Captain (p.397) | Multiattack with alternatives (MON-M-05); Dagger melee-or-thrown (ATK-M-01/MON-M-03); Parry reaction (TURN-M-01 + a hook to raise AC against a hit) |
| Mage (p.400) | 9th-level caster for cantrips (SPELL-M-04); Shield/Counterspell reaction spells (SPELL-M-03); most of its list is unshipped content |
| Young Red Dragon (p.288) | Multiattack (MON-M-05); Fire Breath Recharge 5–6 (MON-M-02); fly/climb (MOVE-M-09); blindsight (COND-M-07). Reach 10 is expressible via `range_ft` |
| Adult Red Dragon (p.287) | All of the above, plus Legendary Resistance 3/Day (MON-M-10); Frightful Presence inside Multiattack (MON-M-05 + a 24-hour immunity); legendary actions Detect / Tail Attack / Wing Attack (MON-D-01, MON-M-01; Detect needs COND-M-06; Wing Attack's half-fly-speed move needs MOVE-M-09) |
| Stone Golem (p.317) | See "Shipped creatures" above |

#### Other content
- Every legendary SRD monster (dragons, lich, kraken, mummy lord, vampire …) → MON-M-01, MON-D-01..MON-D-06, MON-M-10.
- Innate casters (Deep Gnome, Drow, Oni, Djinni, Rakshasa …) → MON-M-03 (+ SPELL-D-17).
- Constrict/grab attacks (Giant Constrictor Snake, Giant Octopus, Couatl, Mimic, Roper) → MON-M-08.
- Undead, constructs, elementals with condition immunities → MON-M-06.
- Lycanthropes, golems, gargoyles, most fiends ("nonmagical" resistances) → ATK-M-13.
- Breath weapons, Web, Slow, Petrifying Breath, every "(Recharge X–Y)" / "X/Day" ability → MON-M-02.

## Appendix E. Smaller observations not filed as entries

Rules-related notes the audit made in passing. Each is small or rides on an entry named
here; promote one to a full entry if it grows. (Code-hygiene and documentation findings
went to the `CODEBASE_REVIEW.md` §8 ledger instead.)

- **Durations are authored twice.** A spell's `duration` (e.g. `unit: minute, count: 1`)
  is display-only; its real length is a separate, hand-authored `duration_rounds`, and
  nothing converts or cross-checks the two (`src/models/spell_properties.py`). A mismatch
  loads silently. SRD p.84 "Time": a round is 6 seconds, so 1 minute = 10 rounds. Fix with
  SPELL-D-11.
- **Haste's lethargy is absent.** When Haste ends, the target "can't move or take actions
  until after its next turn". Needs MOVE-M-03 (a speed-0 override) and COND-M-05.
- **Haste's extra action is unrestricted.** RAW it allows only Attack (one weapon attack),
  Dash, Disengage, Hide or Use an Object (`examples/spells/haste.json` grants any action).
  Needs TURN-M-02 and TURN-M-13.
- **Charm Person has no duration** and never ends when the caster or its companions harm
  the target; nor does the target get advantage on the save while the caster's side is
  fighting it (`examples/spells/charm_person.json`). Rides on COND-D-04.
- **"A creature you can see" is unenforced.** Charm Person, Sacred Flame and Hold
  Person-style targeting accept targets a blinded caster can't see. Needs COND-M-07.
- **Magic Missile rolls each dart separately.** SRD 5.1 does not say whether the darts
  share one roll; the common reading (Sage Advice) is one roll for all darts. Decide
  alongside SPELL-D-13.
- **Legendary spell actions skip the casting checks.** `resolve_legendary_action` always
  spends a base-level slot, cannot upcast, and skips the range, cantrip, self-range and
  target-count checks that `resolve_spell` should make (`src/combat/combat_system.py`
  ~L508–552). Fold into MON-D-03 and the SPELL-D-01/02/13 fixes.
- **`DAMAGE_INCOMING` carries no attacker or action** (`src/combat/event_data.py`), so a
  rule can't inspect the damage's source (Magic Resistance, a golem's "Magic Weapons",
  nonmagical resistance). Needed by ATK-M-13 and MON-M-04.
- **No modifier reaches weapon attacks.** `add_modifier`'s `stat` namespace is read only
  for `ac`, `spell_save_dc`, `spell_attack_bonus` and `saving_throw.<ability>`; a "+1 to
  weapon attacks" modifier would be inert. Rides on ATK-M-05.
- **The arena heuristic's resistance arithmetic** (`src/arena/heuristic/estimate.py`
  `damage_multiplier`) returns the first of immunity/resistance/vulnerability, so
  resistance plus vulnerability scores 0.5 where RAW gives about 1. Fix with ATK-D-03.
