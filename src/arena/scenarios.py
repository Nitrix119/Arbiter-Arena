"""Reusable benchmark scenarios — an LLM side vs the deterministic heuristic.

Each :class:`Scenario` builds a **fresh, unstarted** ``CombatSystem`` (via
:func:`~src.arena.setup.build_combat`, so the global rules are installed) and names which team
the LLM controls and which the heuristic controls. Fresh entities are built on every call so a
batch of seeded matches never shares mutated state. Positions are backend feet.

Design (session notes, 2026-09): the heuristic (:class:`~src.arena.agent.ScriptedAgent`) only
advances-and-attacks, so it always controls a plain **melee** side; the LLM controls the side
whose good play needs the skill under test. For an asymmetric scenario the LLM side and the
reason are recorded in ``Scenario.llm_rationale``. Only weapon attacks are used (no spells), so
these need no spell registry.
"""

from dataclasses import dataclass
from typing import Callable, Dict, Tuple

from src.arena.setup import build_combat
from src.combat.combat_system import CombatSystem
from src.models import (
    AbilityScores,
    AttackAction,
    Damage,
    DamageType,
    Entity,
    StatBlock,
)

_ABILITIES = (16, 14, 14, 10, 12, 10)  # str, dex, con, int, wis, cha


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
) -> Entity:
    block = StatBlock(
        name=name,
        ability_scores=AbilityScores(*_ABILITIES),
        hit_points_max=hp,
        armor_class=ac,
        proficiency_bonus=2,
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


SCENARIOS: Dict[str, Scenario] = {
    "kiting": Scenario(
        name="kiting",
        description="Kiting duel: a fast, fragile archer vs a heavy melee bruiser, 40 ft apart.",
        llm_team="a",
        heuristic_team="b",
        llm_rationale=(
            "LLM = the archer (team a): kiting is the skill — shoot, then retreat past the "
            "bruiser's reach so it never lands a blow. The bruiser's optimal line is simply "
            "'close and swing', which the heuristic plays faithfully. Signal: HP taken by the "
            "archer (a skilled model wins nearly untouched; a naive one stands and trades)."
        ),
        build=_build_kiting,
    ),
    "alpha_strike": Scenario(
        name="alpha_strike",
        description="Alpha-strike: identical 2v2 melee fighters — only the controller differs.",
        llm_team="a",
        heuristic_team="b",
        llm_rationale=(
            "Symmetric roster, so LLM = team a by convention. Tests coordination with equal "
            "pieces: concentrate both attacks to drop one enemy a turn early (halving its "
            "return damage) vs the heuristic's cruder lowest-HP targeting. Signal: win-rate "
            "above 50% against the mirror heuristic."
        ),
        build=_build_alpha_strike,
    ),
    "protect_squishy": Scenario(
        name="protect_squishy",
        description="Protect the squishy: a tank + fragile archer vs two melee raiders.",
        llm_team="a",
        heuristic_team="b",
        llm_rationale=(
            "LLM = the mixed duo (team a): the skill is role play — interpose the tank, keep "
            "the archer back and shooting, don't let the raiders reach it. The raiders just "
            "advance and swing, which the heuristic plays faithfully. Signal: did the archer "
            "survive / stay untouched, and did team a win comfortably."
        ),
        build=_build_protect_squishy,
    ),
}
