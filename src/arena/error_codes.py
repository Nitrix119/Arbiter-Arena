"""The full invalid-action taxonomy — the study's headline measurement.

``docs/current/V1_PLAN.md`` §3.4 asks not just *how often* an agent proposes an illegal
action but *which kind* of illegal action survives each interface condition (H2 predicts
the free-text deficit concentrates in **spatial** failures). That question only has an
answer if every rejection carries a stable category.

Two sources, joined here:

* **Engine codes** (:mod:`src.errors`) — the referee's own reasons, raised as a
  :class:`~src.errors.RuleViolation` deep in ``src/combat`` and ``src/spatial`` and read
  back by :class:`~src.arena.tools.ToolExecutor`. The arena never re-derives them from
  the message text; a second copy of the engine's legality vocabulary would drift
  (CLAUDE.md §2.7).
* **Agent-side codes** (below) — failures the engine never sees because the proposal
  never became a call it could refuse: no tool call at all, an unparseable one, a tool
  that does not exist, a provider returning a broken envelope.

:data:`ALL_CODES` is checked against the real ``raise`` sites by
``tests/arena/test_error_codes.py``.
"""

from src.errors import ENGINE_ERROR_CODES

#: The model answered, but not in a form that can be executed: a call missing a
#: required argument, or, under the free-text condition, a line the grammar parser
#: could not read.
MALFORMED_OUTPUT = "malformed_output"
#: The model produced no action at all — prose or silence instead of a call.
NO_TOOL_CALL = "no_tool_call"
#: The provider itself failed — an empty/error payload, not a model decision. These are
#: the §3.5 pre-declared exclusions: infra, never bad model behaviour.
PROVIDER_ERROR = "provider_error"
#: The engine refused with a plain exception carrying no code. Should stay empty in
#: practice; a non-zero count means a refusal path is untyped and needs a code.
ENGINE_ERROR = "engine_error"

#: Codes the arena raises itself, before or instead of reaching the engine.
AGENT_ERROR_CODES = frozenset(
    {MALFORMED_OUTPUT, NO_TOOL_CALL, PROVIDER_ERROR, ENGINE_ERROR}
)

#: Every code that can appear on a rejected action in a transcript.
ALL_CODES = ENGINE_ERROR_CODES | AGENT_ERROR_CODES
