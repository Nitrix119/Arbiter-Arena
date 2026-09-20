"""Reusable benchmark scenarios — an LLM side vs the deterministic heuristic.

Each :class:`Scenario` builds a **fresh, unstarted** ``CombatSystem`` (via
:func:`~src.arena.setup.build_combat`, so the global rules are installed) and names
which team the LLM controls and which the heuristic controls. Fresh entities are built
on every call so a batch of seeded matches never shares mutated state. Positions are
backend feet.

Design (session notes, 2026-09): the heuristic
(:class:`~src.arena.agent.ScriptedAgent`) only advances-and-attacks, so it always
controls a plain **melee** side; the LLM controls the side whose good play needs the
skill under test. For an asymmetric scenario the LLM side and the reason are recorded in
``Scenario.llm_rationale``. Most use weapon attacks only; ``aoe_placement`` is the
exception and wires a scoped spell registry.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from src.arena.setup import build_combat
from src.combat.combat_system import CombatSystem
from src.combat.spell_registry import SpellRegistry
from src.loaders import StatBlockLoader
from src.models import (
    AbilityScores,
    AttackAction,
    Damage,
    DamageType,
    Entity,
    StatBlock,
)

_SPELLS_DIR = Path(__file__).resolve().parents[2] / "examples" / "spells"

_ABILITIES = (16, 14, 14, 10, 12, 10)  # str, dex, con, int, wis, cha
# A caster trades muscle for a spellcasting stat; INT 16 gives Fireball DC 13.
_CASTER_ABILITIES = (8, 14, 12, 16, 12, 10)


def _attack(
    name: str,
    formula: str,
    damage_type: DamageType,
    *,
    bonus_to_hit: int = 5,
    range_ft: float = 5.0,
) -> AttackAction:
    return AttackAction(
        name=name,
        description="",
        bonus_to_hit=bonus_to_hit,
        damage=[Damage(damage_type, formula=formula)],
        range_ft=range_ft,
    )


def _entity(
    name: str,
    team: str,
    pos: Tuple[float, float, float],
    *,
    hp: int,
    ac: int,
    speed: int = 30,
    attacks,
    known_spells: Optional[List[str]] = None,
    spellcasting_ability: str = "",
    spell_slot_defaults: Optional[Dict[str, int]] = None,
    abilities: Tuple[int, ...] = _ABILITIES,
) -> Entity:
    block = StatBlock(
        name=name,
        ability_scores=AbilityScores(*abilities),
        hit_points_max=hp,
        armor_class=ac,
        proficiency_bonus=2,
        known_spells=list(known_spells or []),
        spellcasting_ability=spellcasting_ability,
        spell_slot_defaults=dict(spell_slot_defaults or {}),
        resource_defaults={
            "actions": 1,
            "bonus_actions": 1,
            "reactions": 1,
            "speed": speed,
        },
    )
    for action in attacks:
        block.add_action(action)
    entity = Entity(block, team=team)
    entity.x, entity.y, entity.z = pos
    return entity


def _spell_registry(*names: str) -> SpellRegistry:
    """A registry holding just the named spells from ``examples/spells``.

    Scoped to what a scenario actually casts rather than the whole catalogue, so a
    scenario's spell list is visible in its own definition and an unrelated content
    change cannot alter what a benchmark creature can do.
    """
    registry = SpellRegistry()
    for name in names:
        registry.register(StatBlockLoader.load_spell_from_json(str(_SPELLS_DIR / name)))
    return registry


def _greatsword() -> AttackAction:
    return _attack("Greatsword", "2d6", DamageType.SLASHING, range_ft=5.0)


def _longbow() -> AttackAction:
    return _attack("Longbow", "1d10", DamageType.PIERCING, range_ft=80.0)


@dataclass(frozen=True)
class Scenario:
    """A named benchmark setup: which team is the LLM, and how to build the fight."""

    name: str
    description: str
    llm_team: str
    heuristic_team: str
    llm_rationale: str
    build: Callable[[], CombatSystem]


# ── 1. Kiting duel — movement & range control ────────────────────────────────
def _build_kiting() -> CombatSystem:
    archer = _entity(
        "Archer", "a", (0, 0, 0), hp=18, ac=14, speed=40, attacks=[_longbow()]
    )
    bruiser = _entity(
        "Bruiser", "b", (40, 0, 0), hp=45, ac=15, speed=30, attacks=[_greatsword()]
    )
    return build_combat([archer, bruiser])


# ── 2. Alpha-strike — target priority & coordination (symmetric 2v2) ─────────
def _build_alpha_strike() -> CombatSystem:
    # Low HP / modest AC so a focused pair of hits kills — makes concentrating fire
    # decisive and keeps matches short (a few rounds), not a grind.
    entities = [
        _entity("Fighter A1", "a", (0, 0, 0), hp=15, ac=14, attacks=[_greatsword()]),
        _entity("Fighter A2", "a", (0, 0, 10), hp=15, ac=14, attacks=[_greatsword()]),
        _entity("Fighter B1", "b", (15, 0, 0), hp=15, ac=14, attacks=[_greatsword()]),
        _entity("Fighter B2", "b", (15, 0, 10), hp=15, ac=14, attacks=[_greatsword()]),
    ]
    return build_combat(entities)


# ── 5. Protect the squishy — role-based positioning ──────────────────────────
def _build_protect_squishy() -> CombatSystem:
    entities = [
        _entity("Tank", "a", (0, 0, 0), hp=50, ac=17, attacks=[_greatsword()]),
        _entity("Sharpshooter", "a", (-8, 0, 0), hp=14, ac=13, attacks=[_longbow()]),
        _entity("Raider 1", "b", (30, 0, 0), hp=30, ac=14, attacks=[_greatsword()]),
        _entity("Raider 2", "b", (30, 0, 10), hp=30, ac=14, attacks=[_greatsword()]),
    ]
    return build_combat(entities)


# ── 4. AoE placement — area targeting with friendly fire on the board ───────
def _build_aoe_placement() -> CombatSystem:
    """A mage who can catch both raiders — or both raiders and its own bodyguard.

    Built around Fireball's footprint rather than the reverse. ``size_ft: 20`` is the
    **radius**, so the blast is 40 ft across:

    * the raiders stand 15 ft apart at z=60, so one centre between them catches both;
    * the bodyguard holds at z=25, 35 ft short of them — outside a blast centred on
      the raiders, but inside one centred carelessly between the mage and them;
    * the mage sits at the origin, well back, and is fragile enough that it cannot
      simply walk into its own blast radius and survive.

    Fireball carries no ``cannot_cause_self_damage``, so friendly fire is real. That is
    what makes placement a judgement rather than a formality, and it is the point of
    the scenario: the good option and the careless option both exist and differ only in
    where the centre goes. ``tests/arena/test_scenarios.py`` asserts both are reachable,
    because a scenario whose central decision is not actually available would let H4
    fail silently.
    """
    entities = [
        _entity(
            "Mage",
            "a",
            (0, 0, 0),
            hp=22,
            ac=12,
            attacks=[_attack("Dagger", "1d4", DamageType.PIERCING, bonus_to_hit=3)],
            known_spells=["Fireball"],
            spellcasting_ability="intelligence",
            spell_slot_defaults={"3": 2},
            abilities=_CASTER_ABILITIES,
        ),
        _entity("Bodyguard", "a", (0, 0, 25), hp=34, ac=16, attacks=[_greatsword()]),
        _entity("Raider 1", "b", (0, 0, 60), hp=26, ac=13, attacks=[_greatsword()]),
        _entity("Raider 2", "b", (15, 0, 60), hp=26, ac=13, attacks=[_greatsword()]),
    ]
    return build_combat(entities, spell_registry=_spell_registry("fireball.json"))


SCENARIOS: Dict[str, Scenario] = {
    "kiting": Scenario(
        name="kiting",
        description=(
            "Kiting duel: a fast, fragile archer vs a heavy melee bruiser, 40 ft apart."
        ),
        llm_team="a",
        heuristic_team="b",
        llm_rationale=(
            "LLM = the archer (team a): kiting is the skill — shoot, then retreat past "
            "the bruiser's reach so it never lands a blow. The bruiser's optimal line "
            "is simply 'close and swing', which the heuristic plays faithfully. "
            "Signal: HP taken by the archer (a skilled model wins nearly untouched; a "
            "naive one stands and trades)."
        ),
        build=_build_kiting,
    ),
    "alpha_strike": Scenario(
        name="alpha_strike",
        description=(
            "Alpha-strike: identical 2v2 melee fighters — only the controller differs."
        ),
        llm_team="a",
        heuristic_team="b",
        llm_rationale=(
            "Symmetric roster, so LLM = team a by convention. Tests coordination with "
            "equal pieces: concentrate both attacks to drop one enemy a turn early "
            "(halving its return damage) vs the heuristic's cruder lowest-HP "
            "targeting. Signal: win-rate above 50% against the mirror heuristic."
        ),
        build=_build_alpha_strike,
    ),
    "protect_squishy": Scenario(
        name="protect_squishy",
        description=(
            "Protect the squishy: a tank + fragile archer vs two melee raiders."
        ),
        llm_team="a",
        heuristic_team="b",
        llm_rationale=(
            "LLM = the mixed duo (team a): the skill is role play — interpose the "
            "tank, keep the archer back and shooting, don't let the raiders reach it. "
            "The raiders just advance and swing, which the heuristic plays faithfully. "
            "Signal: did the archer survive / stay untouched, and did team a win "
            "comfortably."
        ),
        build=_build_protect_squishy,
    ),
    "aoe_placement": Scenario(
        name="aoe_placement",
        description=(
            "AoE placement: a Fireball mage and a bodyguard vs two raiders 15 ft "
            "apart — the blast can catch both, or both plus your own bodyguard."
        ),
        llm_team="a",
        heuristic_team="b",
        llm_rationale=(
            "LLM = the caster's side (team a): the skill is where to put a 20 ft "
            "radius that does not care whose side you are on. The raiders just "
            "advance and swing, which the scripted opponent plays faithfully (it "
            "cannot cast, so it could not hold this side). Signal: did the blast "
            "catch both raiders without catching the bodyguard, and did the mage "
            "keep its distance while doing it. This is the only scenario that "
            "exercises a spell at all, so it is the only one where H4's expressivity "
            "question can be asked."
        ),
        build=_build_aoe_placement,
    ),
}
