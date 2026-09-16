"""The utility-scoring heuristic agent and its supporting machinery.

A pure, in-process consumer of the engine: it reads ``Entity``/``StatBlock`` state and
the arena's read-only helpers (``legal_actions``, ``move_candidates``, ``range_check``,
``CombatSystem`` queries) and never mutates combat. Nothing in ``src/combat`` or
``src/models`` imports this package — the dependency runs one way (arena → engine).

Layout:

* :mod:`~src.arena.heuristic.estimate` — deterministic expected-value primitives (the
  twins of the engine's dice rollers): hit chance, expected damage, save-fail probability.
* :mod:`~src.arena.heuristic.plan` — bounded turn-plan enumeration.
* :mod:`~src.arena.heuristic.features` — feature extractors + threat valuation.
* :mod:`~src.arena.heuristic.score` — the weighted utility function + the weight genome.
* :mod:`~src.arena.heuristic.agent` — :class:`HeuristicAgent`, the scoring policy.

See ``docs/HEURISTIC_DECISION_MODEL.md`` for the design.
"""
