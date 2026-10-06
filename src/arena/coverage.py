"""Interface completeness, measured across a match rather than at one frame.

:func:`~src.arena.action_space.aim_coverage` and
:func:`~src.arena.action_space.move_coverage` each answer "how much of the outcome
space does the menu offer *right now*". But a menu is only as good as its worst moment:
creatures move, so coverage is a property of a board state, and a single opening figure
can hide a mid-match position where the named options stop spanning the choices.

This walks seeded scripted matches, measures at every turn, and reports the
**distribution** — with the **minimum** as the number to register, because a claim that
an interface loses nothing has to hold at the tightest moment, not on average.

Entirely offline: no model, no inference, no API calls. It is a harness property, like
replay verification, and it is knowable before a single decision is bought.
"""

from dataclasses import dataclass
from statistics import median
from typing import Callable, Dict, List, Optional, Tuple

from src.arena.action_space import aim_coverage, move_coverage
from src.arena.agent import ScriptedAgent
from src.arena.match import run_match
from src.combat.combat_system import CombatSystem
from src.models.action import SpellAction
from src.models.entity import Entity
from src.models.spell_properties import TargetingType
from src.utils import dice


@dataclass
class CoverageDistribution:
    """Coverage sampled over many board states.

    ``minimum`` is the registered claim; ``worst_at`` names the state that produced it,
    so a disappointing figure can be looked at rather than argued about.
    """

    samples: List[float]
    worst_at: Optional[str] = None

    @property
    def n(self) -> int:
        return len(self.samples)

    @property
    def minimum(self) -> float:
        return min(self.samples) if self.samples else 1.0

    @property
    def median(self) -> float:
        return median(self.samples) if self.samples else 1.0

    def to_dict(self) -> dict:
        return {
            "n": self.n,
            "min": round(self.minimum, 4),
            "median": round(self.median, 4),
            "worst_at": self.worst_at,
        }


def _area_spells(combat: CombatSystem, entity: Entity) -> List[SpellAction]:
    registry = combat.spell_registry
    if registry is None:
        return []
    out = []
    for name in entity.stat_block.known_spells:
        if name not in registry:
            continue
        spell = registry.get(name)
        if spell.targeting_type == TargetingType.AOE:
            out.append(spell)
    return out


def sample_coverage(
    build: Callable[[], CombatSystem],
    *,
    seeds: range = range(3),
    round_cap: int = 6,
) -> Dict[str, CoverageDistribution]:
    """Measure aim and move coverage at every turn of several scripted matches.

    Scripted agents on both sides: this measures the *interface*, not any policy, and
    a deterministic driver makes the sampled states reproducible. Each seed is played
    to every depth from 0 (the opening) up to *round_cap*, so the samples span real
    formations rather than one frame — which matters, because the opening position of
    a scenario is exactly the configuration its designer arranged, and therefore the
    least representative one.

    Returns ``{"aim": …, "move": …}``; the aim distribution is empty when no combatant
    knows an area spell.
    """
    aim: CoverageDistribution = CoverageDistribution([])
    move: CoverageDistribution = CoverageDistribution([])
    worst: Dict[str, Tuple[float, Optional[str]]] = {
        "aim": (2.0, None),
        "move": (2.0, None),
    }

    for seed in seeds:
        # One match per round depth, so each sample is a genuinely different formation.
        # Coverage needs the *live* combat — a transcript snapshot cannot be
        # re-measured — so the match is replayed to each depth rather than hooked.
        for depth in range(0, round_cap + 1):
            with dice.using_rng(dice.new_rng(seed)):
                combat = build()
            if depth:
                run_match(
                    combat,
                    {
                        team: ScriptedAgent(f"S{team}", team)
                        for team in {e.team for e in combat.combatants}
                    },
                    seed=seed,
                    round_cap=depth,
                )
            for entity in combat.combatants:
                if not entity.is_alive():
                    continue
                label = f"seed{seed}:round{depth}:{entity.entity_id}"
                value = move_coverage(combat, entity).coverage
                move.samples.append(value)
                if value < worst["move"][0]:
                    worst["move"] = (value, label)
                for spell in _area_spells(combat, entity):
                    value = aim_coverage(combat, entity, spell).coverage
                    aim.samples.append(value)
                    if value < worst["aim"][0]:
                        worst["aim"] = (value, f"{label}:{spell.name}")

    aim.worst_at = worst["aim"][1]
    move.worst_at = worst["move"][1]
    return {"aim": aim, "move": move}
