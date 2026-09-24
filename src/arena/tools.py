"""Tool schemas and the executor that turns a chosen action into a refereed effect.

This is the arena's **single execution seam** — the mirror of the web layer's
``_HANDLERS`` dispatch. An agent (LLM or scripted) proposes an action as a
:class:`ToolCall`; :class:`ToolExecutor` validates it and dispatches to the existing
``CombatSystem.resolve_attack`` / ``resolve_spell`` / ``move_entity`` / ``end_turn``.
It never resolves combat itself (CLAUDE.md §3, one resolution path) and never mutates
state directly — the engine is the authority. An illegal call is caught and returned as
a structured error the agent can react to, not a crash.

**Provider-neutral (E4).** :data:`TOOLS` are plain JSON-Schema tool definitions in the
``{name, description, input_schema}`` shape. Claude consumes them directly; another
provider's adapter reshapes only the envelope. Positions and points are in **backend
feet** — the engine's own coordinates — matching the observation.

**Resolution transparency (C3).** A success result always states the outcome (hit/miss,
save success, damage) and the acting agent's *own* roll, but the target's defensive
numbers are gated by the actor's :class:`InformationPolicy`: the target's AC (and, for a
save, the target's save-roll value) appear only when ``reveal_enemy_ac`` is set. The
spell **save DC is the actor's own** stat and is always shown; the target's resulting HP
is never in the result (the next observation carries it, gated by ``reveal_enemy_hp``).
"""

import math
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from src.arena.action_space import move_candidates
from src.arena.error_codes import ENGINE_ERROR, MALFORMED_OUTPUT
from src.arena.identifiers import resolve
from src.arena.information_policy import FULL_INFORMATION, InformationPolicy
from src.errors import UNKNOWN_ACTION, UNKNOWN_TARGET, RuleViolation
from src.models.action import AttackAction
from src.models.entity import Entity
from src.spatial.geometry import Point3D

if TYPE_CHECKING:
    from src.combat.combat_system import CombatSystem


# Tool names — the arena's action vocabulary (mirrors the web _HANDLERS commands).
TOOL_ATTACK = "attack"
TOOL_CAST_SPELL = "cast_spell"
TOOL_MOVE = "move"
TOOL_END_TURN = "end_turn"


#: Provider-neutral JSON-Schema tool definitions handed to an agent each turn.
TOOLS: List[Dict[str, Any]] = [
    {
        "name": TOOL_ATTACK,
        "description": (
            "Make a weapon/attack action against one target. Use an attack `name` "
            "and a target `entity_id` from the battlefield."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action_name": {
                    "type": "string",
                    "description": (
                        "The attack's name, as listed under your capabilities."
                    ),
                },
                "defender_id": {
                    "type": "string",
                    "description": "entity_id of the target to attack.",
                },
            },
            "required": ["action_name", "defender_id"],
        },
    },
    {
        "name": TOOL_CAST_SPELL,
        "description": (
            "Cast a spell you know. Single-target/self spells take `target_ids`; "
            "area spells take a `target_point` (in feet) you aim at. "
            "Optionally cast at "
            "a higher `slot_level` to upcast."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "spell_name": {
                    "type": "string",
                    "description": (
                        "The spell's name, as listed under your capabilities."
                    ),
                },
                "target_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "entity_id(s) to target (single-target/self spells)."
                    ),
                },
                "target_point": {
                    "type": "object",
                    "properties": {
                        "x": {
                            "type": "number",
                            "description": "Aim point x, in feet (east).",
                        },
                        "y": {
                            "type": "number",
                            "description": "Aim point y, in feet (up); usually 0.",
                        },
                        "z": {
                            "type": "number",
                            "description": "Aim point z, in feet (south).",
                        },
                    },
                    # x and z are the ground plane; y is the vertical axis and defaults
                    # to 0. Requiring x/y here (as this did) asked for the one axis a
                    # ground-level aim never needs and made the one it does need
                    # optional.
                    "required": ["x", "z"],
                    "description": (
                        "Ground point in feet to aim an area spell at: `x` east, "
                        "`z` south, `y` up (omit unless aiming above ground)."
                    ),
                },
                "slot_level": {
                    "type": "integer",
                    "description": "Slot level to cast at (>= the spell's base level). "
                    "Omit to cast at its base level.",
                },
            },
            "required": ["spell_name"],
        },
    },
    {
        "name": TOOL_MOVE,
        # Raw coordinates only. The schema used to accept *either* a menu `option_id`
        # or raw x/z, which let the model pick its own experimental condition per
        # decision — that one tool spanned C2's format and C3's affordance, the very
        # distinction C2+M exists to isolate (V1_PLAN, Phase 0 decisions). The executor
        # still honours `option_id` for the deterministic baselines; see `_move`.
        "description": (
            "Move on the battlefield to a point given in feet. Costs movement equal "
            "to the straight-line distance; you cannot move onto another creature."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "x": {
                    "type": "number",
                    "description": "Destination x, in feet (east).",
                },
                "y": {
                    "type": "number",
                    "description": "Destination y, in feet (up); usually 0.",
                },
                "z": {
                    "type": "number",
                    "description": "Destination z, in feet (south).",
                },
            },
            "required": ["x", "z"],
        },
    },
    {
        "name": TOOL_END_TURN,
        "description": (
            "End your turn, passing to the next combatant. Take this when done acting."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
]


@dataclass
class ToolCall:
    """A provider-neutral action proposed by an agent.

    ``name`` is one of the :data:`TOOLS` names; ``arguments`` matches that tool's
    ``input_schema``. ``call_id`` carries a provider's correlation id (e.g. Claude's
    ``tool_use`` block id) when there is one, so the adapter can match the result back.
    """

    name: str
    arguments: Dict[str, Any] = field(default_factory=dict)
    call_id: Optional[str] = None


def _ok(**fields: Any) -> Dict[str, Any]:
    return {"ok": True, **fields}


def _error(code: str, message: str) -> Dict[str, Any]:
    """A refused action: a stable *code* for metrics, prose for the model to read."""
    return {"ok": False, "code": code, "error": message}


def _require(args: Dict[str, Any], key: str, tool: str) -> Any:
    """Return ``args[key]``, or refuse as malformed output.

    A missing required argument is the *model's* formatting failure, not a rule the
    engine declined — it belongs in a different taxonomy bucket, and it must not
    surface as a bare ``KeyError``. ``null`` counts as missing: it is how an
    OpenAI-style call says "not given".
    """
    if args.get(key) is None:
        raise RuleViolation(
            MALFORMED_OUTPUT, f"{tool} requires a {key!r} argument; none was given."
        )
    return args[key]


# Model-written arguments arrive as whatever JSON the model produced. These readers
# are the one place their *types* are checked, so a wrong type is a coded
# malformed_output rather than a TypeError that would stop the study grid as a harness
# bug (review 2026-09-24, C-2). A ``null`` optional argument is treated as absent — the
# OpenAI-style convention — never as an error.

#: A number as text, with an optional unit: the same forms C1's grammar reads
#: (``NUMBER`` then an optional ``ft``/``feet``), so C2 is allowed exactly what C1 is.
_NUMBER_TEXT = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*(?:ft|feet)?\s*$", re.IGNORECASE)


def _malformed(message: str) -> RuleViolation:
    return RuleViolation(MALFORMED_OUTPUT, message)


def _text(args: Dict[str, Any], key: str, tool: str) -> str:
    """A required name argument, which must be a string."""
    value = _require(args, key, tool)
    if not isinstance(value, str):
        raise _malformed(f"{tool}'s {key!r} must be a name (a string); got {value!r}.")
    return value


def _coordinate(value: Any, what: str) -> float:
    """A finite distance in feet, given as a number or as number text."""
    number: Optional[float] = None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
    elif isinstance(value, str):
        match = _NUMBER_TEXT.match(value)
        number = float(match.group(1)) if match else None
    if number is None or not math.isfinite(number):
        raise _malformed(f"{what} must be a number of feet; got {value!r}.")
    return number


def _point(args: Dict[str, Any], what: str) -> Point3D:
    """A point from ``x``/``z`` (required) and ``y`` (optional, default 0)."""
    missing = [axis for axis in ("x", "z") if args.get(axis) is None]
    if missing:
        raise _malformed(
            f"{what} requires both 'x' and 'z' (ground feet); missing "
            + " and ".join(repr(axis) for axis in missing)
            + "."
        )
    y = args.get("y")
    return Point3D(
        _coordinate(args["x"], f"{what} x"),
        0.0 if y is None else _coordinate(y, f"{what} y"),
        _coordinate(args["z"], f"{what} z"),
    )


def _target_ids(value: Any) -> List[str]:
    """Entity ids to target: a list of names, or one bare name (as C1 may write)."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return list(value)
    raise _malformed(f"cast_spell's 'target_ids' must be a list of ids; got {value!r}.")


def _slot_level(value: Any) -> Optional[int]:
    """A whole-number slot level, given as a number or as number text."""
    if value is None:
        return None
    level = _coordinate(value, "cast_spell's 'slot_level'")
    if not level.is_integer():
        raise _malformed(f"cast_spell's 'slot_level' must be whole; got {value!r}.")
    return int(level)


def _gate_roll(
    roll_detail: Optional[Dict[str, Any]], policy: InformationPolicy
) -> Optional[Dict[str, Any]]:
    """Reshape a resolver's ``roll_detail`` into an actor-facing roll, gating C3 fields.

    To-hit rolls (carry ``ac``) expose the actor's own d20/bonus/total; the target
    ``ac`` only under ``reveal_enemy_ac``. Save rolls (carry ``dc``) expose the
    actor's own ``save_dc`` and the outcome; the target's save-roll value only under
    ``reveal_enemy_ac`` (treated as the target's defensive internals).
    """
    if roll_detail is None:
        return None

    if "ac" in roll_detail:  # attacker/spell-attack to-hit roll
        out: Dict[str, Any] = {
            "attack_roll": roll_detail["d20"],
            "attack_total": roll_detail["total"],
        }
        if "bonus" in roll_detail:
            out["attack_bonus"] = roll_detail["bonus"]
        if policy.reveal_enemy_ac:
            out["target_ac"] = roll_detail["ac"]
        return out

    if "dc" in roll_detail:  # target's saving throw vs the actor's DC
        out = {
            "save_dc": roll_detail["dc"],
            "target_saved": roll_detail["save_success"],
        }
        if policy.reveal_enemy_ac:
            out["target_save_roll"] = roll_detail["total"]
        return out

    return dict(roll_detail)


class ToolExecutor:
    """Validates a :class:`ToolCall` and applies it via the ``CombatSystem`` referee.

    Bound to one combat; :meth:`apply` takes the acting entity and the actor's
    :class:`InformationPolicy` (defaults to :data:`FULL_INFORMATION`), so results are
    shaped from that actor's point of view.
    """

    def __init__(self, combat: "CombatSystem") -> None:
        self._combat = combat

    def apply(
        self,
        actor: Entity,
        call: ToolCall,
        policy: InformationPolicy = FULL_INFORMATION,
    ) -> Dict[str, Any]:
        """Execute *call* for *actor*, returning a structured result or error dict.

        Never raises for an illegal move: an engine ``ValueError`` (wrong turn,
        unaffordable, out of range, no slot, …) or a bad reference becomes
        ``{"ok": False, "error": ...}`` — the self-correction signal.
        """
        handlers = {
            TOOL_ATTACK: self._attack,
            TOOL_CAST_SPELL: self._cast_spell,
            TOOL_MOVE: self._move,
            TOOL_END_TURN: self._end_turn,
        }
        handler = handlers.get(call.name)
        if handler is None:
            return _error(UNKNOWN_ACTION, f"Unknown tool: {call.name!r}")
        if not isinstance(call.arguments, dict):
            return _error(
                MALFORMED_OUTPUT,
                f"{call.name}'s arguments must be an object of named fields.",
            )
        try:
            return handler(actor, call.arguments, policy)
        except RuleViolation as exc:
            return _error(exc.code, str(exc))
        except KeyError as exc:
            return _error(MALFORMED_OUTPUT, f"Missing or unknown key: {exc}")
        except (ValueError, RuntimeError, TypeError) as exc:
            # TypeError is a backstop: the argument readers above should leave none,
            # and one reaching here is counted where it can be seen rather than
            # stopping the study grid.
            # An untyped refusal — the engine declining something it cannot model
            # (an unsupported AoE shape) or a path that still needs a code. Counted
            # under its own bucket so a non-zero rate is visible, not silently
            # merged into a real category.
            return _error(ENGINE_ERROR, str(exc))

    # -- individual tools ------------------------------------------------------

    def _lookup(self, entity_id: str) -> Entity:
        """The combatant *entity_id* names — by id first, then by display name.

        Forgiving of spelling only (:mod:`src.arena.identifiers`): ``Raider 1`` finds
        ``raider-1``, ``raider-3`` finds nothing, and a spelling two creatures share is
        refused as ambiguous rather than guessed.
        """
        combatants = self._combat.combatants
        matches = resolve(
            entity_id,
            [
                [(e.entity_id, e) for e in combatants],
                [(e.name, e) for e in combatants],
            ],
        )
        if not matches:
            raise RuleViolation(UNKNOWN_TARGET, f"Unknown entity_id: {entity_id!r}")
        if len(matches) > 1:
            raise RuleViolation(
                UNKNOWN_TARGET,
                f"Ambiguous target {entity_id!r}: it could name any of "
                f"{sorted(e.entity_id for e in matches)}; use the entity_id.",
            )
        return matches[0]

    def _attack(
        self, actor: Entity, args: Dict[str, Any], policy: InformationPolicy
    ) -> Dict[str, Any]:
        action_name = _text(args, "action_name", TOOL_ATTACK)
        defender = self._lookup(_text(args, "defender_id", TOOL_ATTACK))
        attacks = [
            a
            for a in actor.stat_block.actions + actor.granted_actions
            if isinstance(a, AttackAction)
        ]
        matches = resolve(action_name, [[(a.name, a) for a in attacks]])
        if not matches:
            raise RuleViolation(
                UNKNOWN_ACTION, f"{actor.name} has no attack called {action_name!r}"
            )
        if len(matches) > 1:
            raise RuleViolation(
                UNKNOWN_ACTION,
                f"Ambiguous attack {action_name!r}: it could name any of "
                f"{[a.name for a in matches]}.",
            )
        action = matches[0]

        hit, damage, roll_detail = self._combat.resolve_attack(actor, defender, action)
        return _ok(
            action=TOOL_ATTACK,
            target_id=defender.entity_id,
            hit=hit,
            damage=damage,
            roll=_gate_roll(roll_detail, policy),
        )

    def _cast_spell(
        self, actor: Entity, args: Dict[str, Any], policy: InformationPolicy
    ) -> Dict[str, Any]:
        # Resolved to the known spell's real name here, so the engine's own
        # exact-match check stays strict and the arena alone owns the tolerance. A
        # name that spells no known spell passes through unchanged, so the refusal is
        # the engine's own (unknown_action, "does not know the spell").
        written = _text(args, "spell_name", TOOL_CAST_SPELL)
        known = resolve(written, [[(n, n) for n in actor.stat_block.known_spells]])
        if len(known) > 1:
            raise RuleViolation(
                UNKNOWN_ACTION,
                f"Ambiguous spell {written!r}: it could name any of {known}.",
            )
        spell_name = known[0] if known else written
        spell_action = self._combat.get_spell_for_entity(actor, spell_name)

        defenders = [self._lookup(tid) for tid in _target_ids(args.get("target_ids"))]

        target_point: Optional[Point3D] = None
        tp = args.get("target_point")
        if tp is not None:
            # x/z are the ground plane and are required; y (vertical) defaults to 0.
            if not isinstance(tp, dict):
                raise _malformed(
                    "cast_spell's 'target_point' must be an object with x and z; "
                    f"got {tp!r}."
                )
            target_point = _point(tp, "cast_spell target_point")

        results = self._combat.resolve_spell(
            actor,
            defenders,
            spell_action,
            target=target_point,
            slot_level=_slot_level(args.get("slot_level")),
        )
        per_target = []
        for entity, hit, damage, roll_detail, healing, healed in results:
            entry: Dict[str, Any] = {
                "target_id": entity.entity_id,
                "hit": hit,
                "damage": damage,
                "roll": _gate_roll(roll_detail, policy),
            }
            if healing:
                entry["healing"] = healing
                entry["healed_id"] = healed.entity_id if healed else None
            per_target.append(entry)

        return _ok(action=TOOL_CAST_SPELL, spell=spell_name, results=per_target)

    def _move(
        self, actor: Entity, args: Dict[str, Any], policy: InformationPolicy
    ) -> Dict[str, Any]:
        """Move to a raw point, or — for the deterministic baselines only — an option.

        ``option_id`` is deliberately **not** in the :data:`TOOLS` schema any more, so
        no LLM condition can reach it: a tool accepting both a menu id and raw
        coordinates would let the model choose its own condition per decision. The
        executor still resolves one because ``ScriptedAgent``/``RandomAgent`` move by
        option to stay overlap-clear without solving the geometry themselves
        (:func:`~src.arena.agent._move_option_toward`), and a baseline inventing
        illegal moves would corrupt the anchor the tactical metrics are read against.
        """
        option_id = args.get("option_id")
        if option_id:
            option = next(
                (
                    o
                    for o in move_candidates(self._combat, actor)
                    if o.option_id == option_id
                ),
                None,
            )
            if option is None:
                raise RuleViolation(
                    UNKNOWN_TARGET,
                    f"No move option {option_id!r} is available now; "
                    "choose a listed option_id or give raw x/z.",
                )
            x, y, z = option.x, option.y, option.z
        else:
            # The refusal names only x and z: option_id is the baselines' path, and
            # advertising it to a model would reopen the one it must not have.
            destination = _point(args, "move")
            x, y, z = destination.x, destination.y, destination.z
        self._combat.move_entity(actor, x, y, z)
        return _ok(
            action=TOOL_MOVE,
            position={"x": actor.x, "y": actor.y, "z": actor.z},
            movement_remaining=actor.resources.movement,
        )

    def _end_turn(
        self, actor: Entity, args: Dict[str, Any], policy: InformationPolicy
    ) -> Dict[str, Any]:
        self._combat.end_turn(actor.entity_id)
        return _ok(action=TOOL_END_TURN, ended_turn=True)
