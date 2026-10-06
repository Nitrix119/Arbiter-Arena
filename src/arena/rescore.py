"""Re-score C1's first attempts under the strict and lenient parsers — offline, free.

PREREGISTRATION §7 reports C1 under three parsers. The *primary* parser is the one used
live, and its verdicts are already in the transcript. The other two are recomputed here
from the recorded raw text, at no API cost:

* **strict** — accepted only if the live reading needed no tolerance at all (layer 0),
  in one request. This needs nothing but the transcript.
* **lenient** — valid if the primary first attempt was valid, *or* the lenient reading
  (:func:`~src.arena.free_text.read_lenient`) of the first response's text would have
  been accepted by the executor **in the state the game was in at that moment**.

The second needs the game state at each decision, which the transcript does not store.
The re-scorer rebuilds it by replaying the match through the ordinary ``run_match``
(:class:`~src.arena.replay.ReplayAgent` feeds the recorded calls back in, rejections
included). At each model decision it asks a **deep copy** of the live combat what the
executor would have said. The copy has its own state and its own RNG, so the probe can
never disturb the replay. Checked when designing this: the original's state hash and
RNG are unchanged after resolving an action on its copy.

**What this does not re-score.** Only the *first attempt* of each decision. After the
live parser refused something, what happened next was shaped by that refusal, so later
attempts and the match's tactics depend on the live parser and are labelled so (§7).
"""

import copy
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence

from src.arena.agent import Agent
from src.arena.free_text import read_lenient
from src.arena.interfaces import C1
from src.arena.match import run_match
from src.arena.replay import ReplayAgent, ReplayDivergence, actions_by_team
from src.arena.scenarios import model_team
from src.arena.tools import ToolExecutor
from src.arena.transcript import Transcript
from src.combat.combat_system import CombatSystem
from src.models.action import AttackAction
from src.models.entity import Entity


class RescoreError(RuntimeError):
    """A transcript could not be replayed, so its bounds cannot be computed."""


@dataclass(frozen=True)
class Bounded:
    """One C1 first attempt under all three parsers."""

    index: int  # the model team's decision index (matches decisions.csv)
    actor: str
    primary: bool
    strict: bool
    lenient: bool
    lenient_layer: Optional[int]


def sole_attack(entity: Entity) -> Optional[str]:
    """The creature's attack name if it has exactly one — the lenient implied weapon."""
    names = [
        a.name
        for a in entity.stat_block.actions + entity.granted_actions
        if isinstance(a, AttackAction)
    ]
    return names[0] if len(names) == 1 else None


def _strict(record: Dict[str, Any]) -> bool:
    telemetry = record.get("telemetry") or {}
    requests = telemetry.get("requests") or []
    if not (record["result"].get("ok") and telemetry.get("request_count") == 1):
        return False
    reading = requests[0].get("interpretation") or {}
    return reading.get("layer") == 0


class _Probe(ReplayAgent):
    """Replays the model team's decisions, probing the lenient reading at each one."""

    def __init__(self, name: str, team: Optional[str], calls: Sequence[Any]) -> None:
        super().__init__(name, team, calls)
        self.combat: Optional[CombatSystem] = None
        self.bounds: List[Bounded] = []

    def decide(self, observation: Dict[str, Any]) -> Any:
        if not self.exhausted and self.combat is not None:
            self.bounds.append(self._bound(self._index, self._calls[self._index]))
        return super().decide(observation)

    def _bound(self, index: int, record: Dict[str, Any]) -> Bounded:
        assert self.combat is not None
        telemetry = record.get("telemetry") or {}
        requests = telemetry.get("requests") or []
        primary = (
            bool(record["result"].get("ok")) and telemetry.get("request_count", 1) == 1
        )
        lenient, layer = primary, None
        if not primary and requests:
            actor = self._actor(self.combat, record["actor_id"])
            reading = read_lenient(
                requests[0].get("raw_output"), sole_attack=sole_attack(actor)
            )
            if reading.call is not None:
                layer = reading.layer
                twin = copy.deepcopy(self.combat)
                result = ToolExecutor(twin).apply(
                    self._actor(twin, record["actor_id"]), reading.call
                )
                lenient = bool(result.get("ok"))
        return Bounded(
            index=index,
            actor=record["actor_id"],
            primary=primary,
            strict=_strict(record),
            lenient=lenient,
            lenient_layer=layer,
        )

    @staticmethod
    def _actor(combat: CombatSystem, entity_id: str) -> Entity:
        for entity in combat.combatants:
            if entity.entity_id == entity_id:
                return entity
        raise RescoreError(f"no combatant {entity_id!r} in the rebuilt match")


def rescore(
    records: Sequence[Dict[str, Any]], build: Callable[[], CombatSystem]
) -> List[Bounded]:
    """The strict / primary / lenient verdict for every model decision in a C1 match.

    Returns an empty list for a transcript that is not C1: the bounds are defined only
    for the free-text parser. Raises :class:`RescoreError` if the match cannot be
    replayed, since a bound computed on the wrong state would be worse than none.
    """
    start = next((r for r in records if r["kind"] == "match_start"), None)
    if start is None or start.get("condition") != C1:
        return []
    team = model_team(start, list(records))
    grouped = actions_by_team(records, start["teams"])
    probe = _Probe("rescore", team, grouped.get(team, []))
    agents: Dict[Optional[str], Agent] = {
        t: (probe if t == team else ReplayAgent(f"replay:{t}", t, calls))
        for t, calls in grouped.items()
    }
    combat = build()
    probe.combat = combat
    replayed = Transcript()
    try:
        run_match(
            combat,
            agents,
            seed=start.get("seed"),
            round_cap=start.get("round_cap", 20),
            transcript=replayed,
        )
    except ReplayDivergence as exc:
        raise RescoreError(f"the match did not replay: {exc}") from None
    # Every probe was taken on the rebuilt state, so that state must *be* the
    # original's, turn for turn — the same hash check the ReplayVerifier makes.
    expected = [r.get("state_hash") for r in records if r["kind"] == "turn_end"]
    actual = [r.get("state_hash") for r in replayed.records_of("turn_end")]
    if expected != actual:
        raise RescoreError("the replay diverged from the transcript's state hashes")
    return probe.bounds
