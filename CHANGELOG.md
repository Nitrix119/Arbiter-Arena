# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [1.0.0] — Unreleased

The release that ships the action-interface study.

### Added
- The action-interface study harness: four interface conditions (C1 free text,
  C2 tool calls, C2+M tool calls with a menu, C3 enumerated menu) over one
  observation contract, with typed rejection codes and a failure budget.
- A resumable study runner (`python -m src.arena.study run|report|verify|show`),
  a no-API-key demo grid (`examples/study/demo.toml`), and the C1 parser audit
  (`python -m src.arena.audit`).
- Per-request telemetry: tokens, cache reads and writes, latency, cost, and the
  model's reasoning text, scrubbed for secrets at the serialisation boundary.
- `ReplayVerifier`: every recorded match is re-run from its actions and checked
  state by state.
- The pre-registration (`docs/current/PREREGISTRATION.md`), frozen at the
  `study-freeze` tag before the final run.

### Changed
- Licensed under Apache-2.0 (was PolyForm Noncommercial 1.0.0). SRD 5.1
  attribution and the trademark notice are in `NOTICE`.

### Fixed
- Adjacent creatures were refused as overlapping (A29).
- A move to the creature's own position was a free, valid action; it is now
  refused as `no_effect` (A31).

## [0.2.0] — 2026-09-19

### Added
- The agent arena: observation contract, action space, tool executor, match
  runner and JSONL transcripts, browser playback, and metrics.
- Random, Scripted and utility-scoring Heuristic agents; Claude and OpenRouter
  LLM adapters.
- Context-scoped, seedable RNG: `CombatSystem(seed=…)` reproduces a battle
  exactly.

### Changed
- Renamed from D&D Auto-Battler to Arbiter Arena.
- One resolution path: spells, weapon attacks and rules are all block
  `program`s, validated at load.

## [0.1.0]

The original SRD 5.1 combat engine and web UI.
