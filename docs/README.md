# Documentation

Most of what is in this folder is the working record of how the project was built. If
you only want to understand the study and how to check it, three documents are enough.

## Start here

- [ARTICLE.md](ARTICLE.md): the write-up of the action-interface study, covering what was
  tested, what was found, and what it means for anyone building tool-using agents.
- [ARCHITECTURE.md](ARCHITECTURE.md): a short overview of the two layers, namely the
  combat engine that knows the rules and the arena that runs models against it.
- [current/PREREGISTRATION.md](current/PREREGISTRATION.md): the hypotheses, metrics and
  decision rules, as frozen at the `study-freeze` tag before any confirmatory data, with
  every later change recorded as a dated deviation.

## The study's working record

- [current/FINAL_RUN_FINDINGS.md](current/FINAL_RUN_FINDINGS.md): the findings as they
  were first written up from the final run, before the article.
- [current/V1_PLAN.md](current/V1_PLAN.md): the plan for v1.0.0 and the log of how it
  was carried out.
- [current/PILOT_OBSERVATIONS.md](current/PILOT_OBSERVATIONS.md): what the pilot showed
  about reasoning effort, menus and output format.
- [current/C1_PARSER_OPTIONS.md](current/C1_PARSER_OPTIONS.md): how the free-text
  condition is parsed, and why a deterministic grammar was chosen over an LLM parser.
- [current/AGENT_ARENA_METRICS.md](current/AGENT_ARENA_METRICS.md): the catalogue of
  metrics the arena can measure.
- [current/AGENT_ARENA_PLAN.md](current/AGENT_ARENA_PLAN.md) and
  [current/AGENT_ARENA_LLM_SETUP.md](current/AGENT_ARENA_LLM_SETUP.md): how the arena was
  planned, and how to run it with a real model.
- [current/HEURISTIC_DECISION_MODEL.md](current/HEURISTIC_DECISION_MODEL.md): how the
  hand-built heuristic baseline agent chooses its moves.
- [current/RELEASE_NOTES_v1.0.0.md](current/RELEASE_NOTES_v1.0.0.md): the v1.0.0 release
  notes.

## The combat engine

- [current/SPELL_SYSTEM_VISION.md](current/SPELL_SYSTEM_VISION.md): the design intent
  behind spells as programs of composable blocks.
- [current/BLOCK_REFERENCE.md](current/BLOCK_REFERENCE.md): the authoring reference for
  every block, generated from the code (`python -m src.spells.reference`).
- [current/SPELL_SYSTEM_REMAINING.md](current/SPELL_SYSTEM_REMAINING.md),
  [current/COMPOSITE_DAMAGE_DESIGN.md](current/COMPOSITE_DAMAGE_DESIGN.md) and
  [current/ENTITY_LIFECYCLE_DECISIONS.md](current/ENTITY_LIFECYCLE_DECISIONS.md): open
  design work on the engine.
- [current/CODEBASE_REVIEW.md](current/CODEBASE_REVIEW.md): the health of the codebase and
  the ledger of known issues.

## Archive

[archive/](archive/) holds plans and drafts that have been completed or superseded,
kept for the record.
