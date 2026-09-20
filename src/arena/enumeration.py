"""Flatten the legal-action menu into a choosable list — the C3 vocabulary.

The enumerated condition (V1_PLAN §3.1) shows the model *every* action it may take,
each with an id, and takes back one ``choose(action_id)``. That needs a different shape
from the menu the other conditions read: not "here are your attacks, and separately your
targets", but one flat list of concrete, individually executable things.

It is derived entirely from :func:`~src.arena.action_space.legal_actions`, so the
enumerated condition and the menu conditions cannot disagree about what is legal
(CLAUDE.md §2.7 — no second vocabulary). It lives in its own module rather than in
``action_space`` because it needs :mod:`src.arena.tools`, which already imports
``action_space``; keeping it here leaves that dependency running one way.

**Ids are part of the interface under test.** The model copies them, so they are
readable and derived from the action rather than opaque — the same reasoning that made
entity ids readable, and for the same reason: an identifier a model must reproduce is a
transcription cost, and a cost paid unevenly across conditions is a confound.

**Known gap, declared rather than hidden: multi-target spells.** A spell that assigns
several projectiles across targets (Magic Missile, Scorching Ray, Eldritch Blast) has
neither a single target list nor aim points, so it is enumerated *nowhere* and an agent
under this condition cannot cast one. Enumerating it properly means listing every
allocation of N projectiles over the reachable targets, which is combinatorial and
needs its own design. No study scenario casts one, so this is not currently a live
expressivity loss — but it is exactly the kind that would otherwise be attributed to
the condition rather than to the harness, so
:func:`multi_target_spells_not_enumerated` makes it visible and a test pins it.
"""

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from src.arena.action_space import SpellOption, legal_actions
from src.arena.tools import (
    TOOL_ATTACK,
    TOOL_CAST_SPELL,
    TOOL_END_TURN,
    TOOL_MOVE,
    ToolCall,
)
from src.models.entity import Entity

if TYPE_CHECKING:  # avoid importing the whole combat stack at module load
    from src.combat.combat_system import CombatSystem

#: Safety valve on menu length (§3.1's cost covariate). Set well above what the study's
#: scenarios produce; a truncation is reported by :func:`enumerate_legal_actions`'s
#: caller rather than hidden.
DEFAULT_MAX_ACTIONS = 64


def _slug(name: str) -> str:
    """Readable token for an id (``"Magic Missile"`` → ``magic-missile``)."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "action"


@dataclass(frozen=True)
class EnumeratedAction:
    """One concrete thing an entity may do, named by a stable id.

    ``call`` is the real :class:`~src.arena.tools.ToolCall` the id resolves to, so the
    listed action and the executed action are one object and cannot drift apart.
    """

    action_id: str
    label: str
    call: ToolCall

    def to_dict(self) -> dict:
        """The agent-facing view.

        The underlying call is deliberately **not** shown: under this condition the id
        *is* the action, and exposing raw parameters alongside would hand the model
        C2's format as well, collapsing the distinction the condition exists to test.
        """
        return {"action_id": self.action_id, "label": self.label}


def _spell_args(
    spell: SpellOption,
    level: int,
    *,
    target_ids: Optional[List[str]] = None,
    target_point: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """Arguments for a ``cast_spell`` call, omitting a slot level that is the base."""
    args: Dict[str, Any] = {"spell_name": spell.name}
    if target_ids is not None:
        args["target_ids"] = target_ids
    if target_point is not None:
        args["target_point"] = target_point
    if level != spell.spell_level:
        args["slot_level"] = level
    return args


def multi_target_spells_not_enumerated(
    combat: "CombatSystem", entity: Entity
) -> List[str]:
    """Names of *entity*'s castable spells this module cannot enumerate (see above).

    Non-empty means the enumerated condition is quietly less expressive than the
    raw-parameter conditions for this roster, which would bias a between-condition
    comparison. Call it when building a scenario; it should be empty.
    """
    return [
        spell.name
        for spell in legal_actions(combat, entity).spells
        if not spell.targets and not spell.aim_points
    ]


def enumerate_legal_actions(
    combat: "CombatSystem",
    entity: Entity,
    *,
    max_actions: int = DEFAULT_MAX_ACTIONS,
) -> List[EnumeratedAction]:
    """Every legal action for *entity*, flattened into one choosable list.

    Sources, all from the existing menu: attacks × targets, single-target spells ×
    targets, area spells × aim points, each spell at every castable slot level, move
    candidates, and ending the turn.

    Ordered deterministically by id. That ordering carries **no quality signal** on
    purpose — ranking a menu nudges the choice this study measures, the same reason
    aim points are sorted lexicographically rather than by enemies caught.

    Every listed action must execute successfully; ``tests/arena/test_enumeration.py``
    proves it by running each through the real ``ToolExecutor`` (V1_PLAN §3.1).
    """
    menu = legal_actions(combat, entity)
    out: List[EnumeratedAction] = []

    for attack in menu.attacks:
        for target in attack.targets:
            out.append(
                EnumeratedAction(
                    action_id=f"attack:{_slug(attack.name)}:{target.entity_id}",
                    label=f"Attack {target.name} with {attack.name}",
                    call=ToolCall(
                        TOOL_ATTACK,
                        {"action_name": attack.name, "defender_id": target.entity_id},
                    ),
                )
            )

    for spell in menu.spells:
        for level in spell.castable_levels or [spell.spell_level]:
            # The slot level is part of the id, so upcasting is not silently
            # unavailable under this condition — that would be an expressivity loss
            # introduced by the interface rather than measured by it.
            suffix = "" if level == spell.spell_level else f"@{level}"
            at = f" at level {level}" if suffix else ""
            for target in spell.targets:
                out.append(
                    EnumeratedAction(
                        action_id=(
                            f"cast:{_slug(spell.name)}:{target.entity_id}{suffix}"
                        ),
                        label=f"Cast {spell.name} on {target.name}{at}",
                        call=ToolCall(
                            TOOL_CAST_SPELL,
                            _spell_args(spell, level, target_ids=[target.entity_id]),
                        ),
                    )
                )
            for aim in spell.aim_points:
                caught = ", ".join(f"{t.name} ({t.relation})" for t in aim.hits)
                out.append(
                    EnumeratedAction(
                        action_id=f"cast:{_slug(spell.name)}:{aim.option_id}{suffix}",
                        label=f"Cast {spell.name}{at}, catching {caught}",
                        call=ToolCall(
                            TOOL_CAST_SPELL,
                            _spell_args(
                                spell,
                                level,
                                target_point={"x": aim.x, "y": aim.y, "z": aim.z},
                            ),
                        ),
                    )
                )

    for move in menu.moves:
        # Resolved to coordinates here rather than passed as an option_id: the
        # executor's option lookup is for the deterministic baselines, and a
        # condition that emitted menu ids into the *move* tool would be C3's
        # affordance wearing C2's format.
        out.append(
            EnumeratedAction(
                action_id=f"move:{move.option_id}",
                label=f"{move.label} ({move.cost_ft:g} ft)",
                call=ToolCall(TOOL_MOVE, {"x": move.x, "y": move.y, "z": move.z}),
            )
        )

    out.append(
        EnumeratedAction(
            action_id="end_turn",
            label="End your turn",
            call=ToolCall(TOOL_END_TURN, {}),
        )
    )

    out.sort(key=lambda action: action.action_id)
    return out[:max_actions]
