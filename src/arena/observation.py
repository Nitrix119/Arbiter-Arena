"""Build an agent's view of the battle — its sensory input for one turn.

``build_observation`` produces a plain ``dict`` (JSON-serializable) from *one
entity's* point of view: itself and its allies in full, each enemy filtered through
the :class:`~src.arena.information_policy.InformationPolicy`, the battle's round/turn
state, and the entity's legal-action menu
(:func:`~src.arena.action_space.legal_actions`).

Positions are reported in **backend feet** ``(x, y, z)`` — the engine's own
coordinates — so the observation is honest to the model the engine runs. The web
layer's cell-coordinate swap is a presentation concern that a future web spectator
bridge applies; it does not belong in the agent's view.
"""

from typing import TYPE_CHECKING, Any, Dict, Optional

from src.arena.action_space import legal_actions
from src.arena.enumeration import DEFAULT_MAX_ACTIONS, enumerate_legal_actions
from src.arena.information_policy import (
    FULL_INFORMATION,
    HP_EXACT,
    InformationPolicy,
    bucket_hp,
)
from src.models.action import AttackAction
from src.models.entity import Entity
from src.spatial.range_check import effective_range_ft

if TYPE_CHECKING:
    from src.combat.combat_system import CombatSystem


#: The flat menu's length cap (a §3.1 cost covariate), read at call time so a test can
#: lower it. A cap that bites removes real options, so it is flagged, never silent.
MENU_CAP = DEFAULT_MAX_ACTIONS


def _position(entity: Entity) -> dict:
    return {"x": entity.x, "y": entity.y, "z": entity.z}


def _resources(entity: Entity) -> dict:
    r = entity.resources
    return {
        "actions": r.actions,
        "bonus_actions": r.bonus_actions,
        "reactions": r.reactions,
        "movement": r.movement,
    }


def _spell_slots(entity: Entity) -> Optional[dict]:
    if entity.spell_slots is None:
        return None
    return {
        str(level): remaining
        for level, remaining in entity.spell_slots.remaining.items()
    }


def _conditions(entity: Entity) -> list:
    return [c.condition_type.value for c in entity.conditions]


def _serialize_ally(entity: Entity) -> Dict[str, Any]:
    """Full view of a friendly entity (self or ally) — nothing is hidden."""
    return {
        "entity_id": entity.entity_id,
        "name": entity.name,
        "team": entity.team,
        "position": _position(entity),
        "size_ft": entity.stat_block.size.size_ft,
        "alive": entity.is_alive(),
        "hp": entity.current_hp,
        "max_hp": entity.max_hp,
        "temp_hp": entity.temporary_hp,
        "ac": entity.ac,
        "conditions": _conditions(entity),
        "resources": _resources(entity),
        "spell_slots": _spell_slots(entity),
    }


def _serialize_enemy(entity: Entity, policy: InformationPolicy) -> Dict[str, Any]:
    """View of an enemy, with fields hidden or coarsened per *policy*.

    Identity, team, position, and liveness are always shown — the battlefield is
    shared and the engine needs positions. Everything else is gated by the policy.
    """
    view: Dict[str, Any] = {
        "entity_id": entity.entity_id,
        "name": entity.name,
        "team": entity.team,
        "position": _position(entity),
        "size_ft": entity.stat_block.size.size_ft,
        "alive": entity.is_alive(),
    }

    if policy.shows_hp:
        if policy.hp_display == HP_EXACT:
            view["hp"] = entity.current_hp
            view["max_hp"] = entity.max_hp
            view["temp_hp"] = entity.temporary_hp
        else:  # bucketed
            view["hp_bucket"] = bucket_hp(entity.current_hp, entity.max_hp)

    if policy.reveal_enemy_ac:
        view["ac"] = entity.ac
    if policy.reveal_enemy_conditions:
        view["conditions"] = _conditions(entity)
    if policy.reveal_enemy_resources:
        view["resources"] = _resources(entity)
    if policy.reveal_enemy_spell_slots:
        view["spell_slots"] = _spell_slots(entity)
    if policy.reveal_enemy_actions:
        view["actions"] = [
            a.name for a in entity.stat_block.actions + entity.granted_actions
        ]
        view["known_spells"] = list(entity.stat_block.known_spells)

    return view


def _spell_capability(combat: "CombatSystem", name: str) -> Dict[str, Any]:
    """What a known spell *is*: level, targeting, reach and area — never whether it
    can be cast right now.

    A spell the combat cannot resolve (no registry, or absent from it) is still named:
    the creature knows it, and hiding it would be the observation deciding legality.
    """
    registry = combat.spell_registry
    if registry is None or name not in registry:
        return {"name": name}
    spell = registry.get(name)
    return {
        "name": spell.name,
        "spell_level": spell.spell_level,
        "targeting": spell.targeting_type.value,
        "range_ft": effective_range_ft(spell),
        "area": (
            {"shape": spell.aoe.shape.value, "size_ft": spell.aoe.size_ft}
            if spell.aoe is not None
            else None
        ),
    }


def _capabilities(combat: "CombatSystem", entity: Entity) -> Dict[str, Any]:
    """A friendly creature's own attacks and spells, as static facts.

    **Shown in every condition**, because it is what the creature *is*, not what is
    legal. Before this existed, a creature's own attack and spell names appeared only
    in the legal-action menu, so the no-menu conditions (C1, C2) had to guess the
    exact names the executor matches — and C2 → C2+M measured "being told what you
    are" on top of the affordance it exists to isolate. Affordability, slots and
    targets stay in the menu, where they belong.

    Kept out of :func:`_serialize_ally` on purpose: :func:`snapshot_state` reuses that
    helper and feeds the per-turn state hash, which static fields would change.
    """
    return {
        "attacks": [
            _without_empty_description(_serialize_action(a))
            for a in entity.stat_block.actions + entity.granted_actions
            if isinstance(a, AttackAction)
        ],
        "spells": [
            _spell_capability(combat, name) for name in entity.stat_block.known_spells
        ],
    }


def _without_empty_description(view: Dict[str, Any]) -> Dict[str, Any]:
    """Drop a blank description: shown in every observation, it is only noise (A6)."""
    if not view.get("description"):
        view.pop("description", None)
    return view


def _friendly(combat: "CombatSystem", entity: Entity) -> Dict[str, Any]:
    """The full view of a friendly creature, plus what it can do."""
    return {**_serialize_ally(entity), "capabilities": _capabilities(combat, entity)}


def build_observation(
    combat: "CombatSystem",
    entity: Entity,
    policy: InformationPolicy = FULL_INFORMATION,
) -> dict:
    """Return *entity*'s observation of *combat* as a JSON-serializable dict.

    Args:
        combat: The battle to observe.
        entity: The entity whose viewpoint this observation is from.
        policy: What this agent may learn about its enemies. Defaults to
            :data:`~src.arena.information_policy.FULL_INFORMATION`.

    The returned dict has: ``round``/``turn``/``state``/``is_my_turn``, ``self`` and
    ``allies`` (full, each with its ``capabilities``), ``enemies`` (policy-filtered),
    ``legal_actions`` (the menu of what *entity* may do now) and ``enumerated_actions``
    (the same options flattened).
    An :class:`~src.arena.interfaces.ActionInterface` decides which of the last two a
    given study condition actually sees — this function shows everything.
    """
    current = combat.get_current_entity()
    menu = legal_actions(combat, entity)
    enumerated = enumerate_legal_actions(combat, entity, max_actions=None)
    return {
        "state": combat.state.name,
        "round": combat.round,
        "turn": combat.turn,
        "is_my_turn": current is not None and current.entity_id == entity.entity_id,
        "self": _friendly(combat, entity),
        "allies": [_friendly(combat, a) for a in combat.get_allies(entity)],
        "enemies": [_serialize_enemy(e, policy) for e in combat.get_enemies(entity)],
        "legal_actions": menu.to_dict(),
        # The same options flattened into one choosable list, for the enumerated
        # condition. Built here, unconditionally, so this module stays ignorant of
        # which condition is running; each ActionInterface decides what to show.
        # Carries live EnumeratedAction objects, not dicts — the interface needs the
        # ToolCall each id resolves to, and shows only `action_id`/`label`.
        "enumerated_actions": enumerated[:MENU_CAP],
        # Harness metadata: whether a cap (actions or aim points) removed real
        # options. Recorded per decision; every condition strips it before showing.
        "menu_truncated": len(enumerated) > MENU_CAP or menu.truncated,
    }


def _serialize_action(action: Any) -> Dict[str, Any]:
    """A static, JSON-safe view of one action — name, reach, and damage formulas.

    Reads the *authoring* fields (not a resolved roll), so it shows the option the
    agent had rather than any one outcome. ``range_ft`` is present only on weapon
    attacks; spells carry their reach elsewhere and report ``None`` here.
    """
    return {
        "name": action.name,
        "description": action.description,
        "range_ft": getattr(action, "range_ft", None),
        "damage": [
            {"damage_type": d.damage_type.value, "formula": d.formula or str(d.amount)}
            for d in action.damage
        ],
    }


def serialize_stat_block(entity: Entity) -> Dict[str, Any]:
    """A static, ground-truth view of an entity's *template* for the transcript.

    Unlike :func:`_serialize_ally` (mutable per-turn state), this captures the fixed
    stat block — abilities, AC, max HP, the full action menu and known spells — so a
    replay can show *every option a combatant (and the agent behind it) had*, not just
    what it used. Pure: it reads the immutable ``StatBlock`` and never mutates anything.
    """
    block = entity.stat_block
    scores = block.ability_scores
    mods = scores.get_all_modifiers()
    return {
        "entity_id": entity.entity_id,
        "name": entity.name,
        "team": entity.team,
        "size_ft": block.size.size_ft,
        "max_hp": entity.max_hp,
        "ac": entity.ac,
        "proficiency_bonus": block.proficiency_bonus,
        "abilities": {
            ability: {"score": getattr(scores, ability), "modifier": mods[ability]}
            for ability in mods
        },
        "speed": dict(block.resource_defaults),
        "actions": [
            _serialize_action(a) for a in block.actions + entity.granted_actions
        ],
        "known_spells": list(block.known_spells),
        "spellcasting_ability": block.spellcasting_ability,
    }


def snapshot_state(combat: "CombatSystem") -> Dict[str, Any]:
    """Return a neutral, **ungated** full-state snapshot of *combat* for the transcript.

    Unlike :func:`build_observation` (one agent's policy-filtered view), this is
    ground truth — every combatant in full — so replay and scoring have complete data
    regardless of what any agent was allowed to see. Positions are in backend feet.
    """
    current = combat.get_current_entity()
    return {
        "state": combat.state.name,
        "round": combat.round,
        "turn": combat.turn,
        "current_entity_id": current.entity_id if current else None,
        "entities": [_serialize_ally(e) for e in combat.combatants],
    }
