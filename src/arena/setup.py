"""Build a match-ready ``CombatSystem`` — the arena's single combat-setup path.

Combat needs more than combatants: the **global rules** in ``rules/global/`` (the
per-turn action-economy refill, critical hit/miss, and damage
resistance/immunity/vulnerability) must be installed on the event bus or turns don't
refill and fights stalemate. The web layer does this in its ``start_combat`` handler;
:func:`build_combat` is the arena's mirror, so no arena caller has to remember the
wiring (the kind of silent seam CLAUDE.md §4 warns about).

It is also where combatants get their **readable, deterministic ids** — see
:func:`stable_entity_ids` for why that is a measurement concern, not a cosmetic one.
"""

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable, List, Optional, Sequence

from src.combat.combat_system import CombatSystem
from src.models.entity import Entity
from src.spells.rules import load_rules_from_directory

if TYPE_CHECKING:
    from src.combat.spell_registry import SpellRegistry

_GLOBAL_RULES_DIR = Path(__file__).resolve().parents[2] / "rules" / "global"


def _slug(name: str) -> str:
    """Reduce a name to a short lowercase token (``"Fighter A1"`` → ``fighter-a1``)."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "combatant"  # a punctuation-only name still needs a usable id


def stable_entity_ids(entities: Sequence[Entity]) -> List[str]:
    """Readable ids for a roster, derived from names and unique by construction.

    **Why not random ids.** An entity id is not just a key — under the free-text and
    raw-parameter interface conditions the *model must type it* to name a target, while
    the enumerated-menu condition never does. A 16-hex-character id therefore taxes
    some conditions and not others, and the resulting failures land in
    ``unknown_target`` — one of the very categories the study compares between
    conditions (V1_PLAN §3.4, H2). Readable ids remove that asymmetry, the same way
    legal move candidates removed the 2026-09-15 raw-coordinate confound.

    Because the ids depend only on the roster, the same creature also carries the same
    id in every cell of the grid, so paired-seed analysis can join on entity across
    conditions — and a replay reproduces them with no seeding dance at all.

    A duplicate name takes a numeric suffix (``goblin``, ``goblin-2``, ``goblin-3``);
    the first of a name stays bare, so the common case reads cleanly.
    """
    seen: dict[str, int] = {}
    ids: List[str] = []
    for entity in entities:
        base = _slug(entity.name)
        seen[base] = seen.get(base, 0) + 1
        ids.append(base if seen[base] == 1 else f"{base}-{seen[base]}")
    return ids


def assign_stable_ids(entities: Sequence[Entity]) -> None:
    """Give each of *entities* a readable id, in place.

    **Only safe before the entities are used.** ``Entity.__hash__``/``__eq__`` key on
    ``entity_id``, so changing one after an entity is in a set or dict corrupts that
    container — and two entities sharing an id would compare *equal*, silently
    breaking targeting. Hence the uniqueness assertion, and hence calling this at the
    top of :func:`build_combat`, before anything has touched the entities.
    """
    ids = stable_entity_ids(entities)
    if len(set(ids)) != len(ids):  # unreachable via stable_entity_ids; guard the seam
        raise ValueError(f"entity ids are not unique: {ids}")
    for entity, entity_id in zip(entities, ids):
        entity.entity_id = entity_id


def install_global_rules(combat: CombatSystem) -> None:
    """Install the global rules (per-turn refill, crits, damage modifiers) on *combat*.

    Loads each JSON rule under ``rules/global/`` onto the combat's event bus, exactly as
    the web layer does. Install once per combat — installing twice double-subscribes.
    """
    load_rules_from_directory(
        str(_GLOBAL_RULES_DIR),
        event_bus=combat.event_bus,
        damage_processor=combat._damage_processor,
    )


def build_combat(
    entities: Iterable[Entity],
    *,
    spell_registry: Optional["SpellRegistry"] = None,
    condition_rules: Any = None,
    global_rules: bool = True,
    stable_ids: bool = True,
) -> CombatSystem:
    """Assemble an unstarted, match-ready :class:`CombatSystem`.

    Args:
        entities: The combatants to add (already positioned, on their teams).
        spell_registry: Registry used to resolve ``known_spells`` at cast time.
        condition_rules: The effect registry the ``apply_condition`` block reads
            (needed for condition-applying spells).
        global_rules: Install the ``rules/global/`` set (default True). Turn it off only
            for a deliberately bare combat — without it, resources never refill.
        stable_ids: Replace each combatant's random id with a readable one derived from
            the roster (default True). See :func:`stable_entity_ids`. Turn it off only
            when a caller has already assigned ids it needs kept.
    """
    combat = CombatSystem()
    roster = list(entities)
    if stable_ids:
        # Before add_combatant: the ids feed __hash__/__eq__, so this is the last
        # moment at which changing them is safe.
        assign_stable_ids(roster)
    for entity in roster:
        combat.add_combatant(entity)
    if spell_registry is not None:
        combat.spell_registry = spell_registry
    if condition_rules is not None:
        combat.condition_rules = condition_rules
    if global_rules:
        install_global_rules(combat)
    return combat
