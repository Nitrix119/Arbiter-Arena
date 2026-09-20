"""The engine's typed refusal — a rejected action carries a machine-readable *code*.

When the engine declines an action it has always said **why** in a message. A human
reads that message; a *measurement* cannot. The action-interface study reports which
category of illegal action survives each interface (``docs/current/V1_PLAN.md`` §3.4),
so "why was this refused" has to be a stable value, not prose.

:class:`RuleViolation` subclasses ``ValueError`` deliberately: every existing caller —
the web layer's ``_HANDLERS``, the arena's :class:`~src.arena.tools.ToolExecutor`, the
engine's own tests — already catches ``ValueError``, so adding the code breaks nothing
and reading it is opt-in.

**Why the codes live here, at the top of ``src/``.** ``src/combat``, ``src/spatial`` and
``src/models`` all refuse actions, and ``src/arena`` reads the refusals. This module
imports nothing, so every one of them may depend on it and none of them gain a
dependency on each other (``range_check.py`` in particular exists to stay out of
``src/combat``).

The set declared here is checked against the code's real ``raise`` sites by
``tests/arena/test_error_codes.py`` — a declaration nobody verifies is a comment
(CLAUDE.md §9, 2026-09-03).
"""

#: It is not this entity's turn.
NOT_YOUR_TURN = "not_your_turn"
#: The action's own economy (action / bonus action / reaction) is already spent.
ACTION_ECONOMY_SPENT = "action_economy_spent"
#: A consumable is exhausted — movement feet, or a spell slot.
INSUFFICIENT_RESOURCE = "insufficient_resource"
#: The actor has no such action, attack or spell.
UNKNOWN_ACTION = "unknown_action"
#: The named target does not exist, or no target was given where one is required.
UNKNOWN_TARGET = "unknown_target"
#: The target exists but is not a legal target for this action (wrong relation,
#: illegal parameter combination such as a slot below the spell's base level).
INVALID_TARGET_RELATION = "invalid_target_relation"
#: The target is beyond the action's reach.
OUT_OF_RANGE = "out_of_range"
#: The destination is occupied by another creature.
DESTINATION_BLOCKED = "destination_blocked"

#: Every code the **engine** can raise. The arena adds its own (agent-side) codes on
#: top of these; see :mod:`src.arena.error_codes`.
ENGINE_ERROR_CODES = frozenset(
    {
        NOT_YOUR_TURN,
        ACTION_ECONOMY_SPENT,
        INSUFFICIENT_RESOURCE,
        UNKNOWN_ACTION,
        UNKNOWN_TARGET,
        INVALID_TARGET_RELATION,
        OUT_OF_RANGE,
        DESTINATION_BLOCKED,
    }
)


class RuleViolation(ValueError):
    """An action the engine refused, tagged with a stable :data:`code`.

    Subclasses ``ValueError`` so existing handlers are unaffected; the message is
    unchanged prose for humans, and ``code`` is the value metrics group by.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
