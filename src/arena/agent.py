"""The agent contract and two deterministic baseline agents.

An :class:`Agent` controls a **team** (B1): the turn driver invokes it for whichever of
its creatures is currently active, so the ``observation``'s ``self`` rotates. Each call
returns exactly **one** action (B2) — the driver loops until the agent ends its turn.

The contract is **provider-neutral** (E4): an agent receives a plain-dict observation
and a list of plain-JSON tool schemas, and returns a plain
:class:`~src.arena.tools.ToolCall`. An LLM adapter is one implementation; the
deterministic agents here are baselines and test fixtures. An agent may keep a small,
capped ``notes`` string across its turns — a scratchpad memory (B3) the deterministic
agents don't use but an LLM agent will.
"""

import math
import random
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from src.arena.telemetry import DecisionTelemetry
from src.arena.tools import (
    TOOL_ATTACK,
    TOOL_CAST_SPELL,
    TOOL_END_TURN,
    TOOL_MOVE,
    ToolCall,
)


class NoToolCallError(RuntimeError):
    """An agent could not produce a tool call for its turn (e.g. the model returned
    prose).

    The turn driver treats this like an illegal action — counted against the failure
    budget and fed back — rather than a crash, so one flaky model response can't abort
    a whole match.
    """


class ProviderError(NoToolCallError):
    """The *provider* failed, rather than the model choosing badly.

    An empty or malformed response envelope — no ``choices``, an error body — is
    infrastructure, and the study excludes matches only for infrastructure
    (``docs/current/V1_PLAN.md`` §3.5), never for bad model behaviour. Separating it
    here is what makes that exclusion rule applyable after the fact; lumping it in
    with "the model returned prose" would quietly count a rate-limited request as a
    reasoning failure.

    Subclasses :class:`NoToolCallError` so the turn driver's existing handling — count
    it, feed it back, never crash the match — applies unchanged.

    Carries the failed request's :class:`~src.arena.telemetry.RequestRecord` when the
    adapter has one: a request that failed still took time and may still have been
    billed, and a timeout's latency is exactly the number worth seeing.
    """

    def __init__(self, message: str, record: Optional[Any] = None) -> None:
        super().__init__(message)
        self.record = record


class Agent(ABC):
    """Base class: decides one action from an observation.

    Subclasses implement :meth:`decide`. ``notes`` is an optional scratchpad the agent
    may carry between its own turns (capped at :data:`MAX_NOTES_CHARS`).
    """

    MAX_NOTES_CHARS = 500

    def __init__(self, name: str, team: Optional[str] = None) -> None:
        self.name = name
        self.team = team
        self.notes = ""
        #: Populated by :func:`~src.arena.llm_common.decide_one_action` for agents that
        #: call a provider; stays ``None`` for the deterministic ones.
        self.telemetry: Optional[DecisionTelemetry] = None

    def remember(self, text: str) -> None:
        """Store a capped scratchpad note to carry to the agent's next turn."""
        self.notes = (text or "")[: self.MAX_NOTES_CHARS]

    def reseed(self, seed: int) -> None:
        """Reseed any private randomness this agent uses (default: no-op).

        Called by the match runner so one match seed governs a stochastic agent's
        choices too — kept on a stream *separate* from the dice RNG so changing dice
        draws does not reshuffle agent decisions. Deterministic agents ignore it.
        """

    def last_telemetry(self) -> Optional[DecisionTelemetry]:
        """Cost and latency for the most recent :meth:`decide`, if measured.

        ``None`` for the deterministic agents: they cost nothing and call nobody, so
        there is nothing to report and their transcripts carry no telemetry key. The
        turn driver reads this after every decision — including one that raised, since
        a failed request still spent tokens.
        """
        return self.telemetry

    @abstractmethod
    def decide(
        self, observation: Dict[str, Any], tools: List[Dict[str, Any]]
    ) -> ToolCall:
        """Return one action to attempt, given the current observation."""


# ---------------------------------------------------------------------------
# Geometry / selection helpers (operate purely on the observation dict)
# ---------------------------------------------------------------------------


def _dist(a: Dict[str, float], b: Dict[str, float]) -> float:
    return math.sqrt(
        (a["x"] - b["x"]) ** 2 + (a["y"] - b["y"]) ** 2 + (a["z"] - b["z"]) ** 2
    )


def _pick_target(
    self_view: Dict[str, Any], candidates: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """Choose the enemy to hit: lowest HP if HP is visible for all, else the nearest."""
    if candidates and all("hp" in c for c in candidates):
        return min(candidates, key=lambda c: c["hp"])
    sp = self_view["position"]
    return min(candidates, key=lambda c: _dist(sp, c["position"]))


def _move_option_toward(
    observation: Dict[str, Any], enemy_id: str
) -> Optional[ToolCall]:
    """A ``move`` ToolCall taking the legal ``toward_melee`` option for *enemy_id*, if
    any.

    The option comes from :func:`~src.arena.action_space.move_candidates`, so it is
    already overlap-checked against every creature — closing to melee never lands on a
    third body (unlike computing a raw standoff). Returns ``None`` when no such legal
    option exists (e.g. already in reach, or fully boxed in).
    """
    want = f"toward_melee:{enemy_id}"
    for move in observation["legal_actions"].get("moves", []):
        if move["option_id"] == want:
            return ToolCall(TOOL_MOVE, {"option_id": want})
    return None


def _attacks_on_enemies(observation: Dict[str, Any], enemy_ids: set) -> List[tuple]:
    """All ``(attack, enemy_target_view)`` pairs the actor could make this call."""
    enemy_by_id = {e["entity_id"]: e for e in observation["enemies"]}
    pairs = []
    for atk in observation["legal_actions"]["attacks"]:
        for t in atk["targets"]:
            if t["entity_id"] in enemy_ids:
                pairs.append((atk, enemy_by_id[t["entity_id"]]))
    return pairs


def _spells_on_enemies(observation: Dict[str, Any], enemy_ids: set) -> List[tuple]:
    """All ``(spell, enemy_target_view)`` pairs for single-target spells with a
    reachable enemy.
    """
    enemy_by_id = {e["entity_id"]: e for e in observation["enemies"]}
    pairs = []
    for sp in observation["legal_actions"]["spells"]:
        for t in sp["targets"]:
            if t["entity_id"] in enemy_ids:
                pairs.append((sp, enemy_by_id[t["entity_id"]]))
    return pairs


# ---------------------------------------------------------------------------
# Baseline agents
# ---------------------------------------------------------------------------


class RandomAgent(Agent):
    """Picks uniformly among legal actions — a sanity floor.

    Candidates are every affordable attack/single-target spell against a reachable
    enemy, a step toward a random enemy when movement remains, and ``end_turn``.
    Deterministic when given a seeded ``rng``.
    """

    def __init__(
        self, name: str, team: Optional[str] = None, rng: Optional[random.Random] = None
    ):
        super().__init__(name, team)
        self._rng = rng or random.Random()

    def reseed(self, seed: int) -> None:
        """Reseed this agent's private choice RNG for a reproducible match."""
        self._rng.seed(seed)

    def decide(
        self, observation: Dict[str, Any], tools: List[Dict[str, Any]]
    ) -> ToolCall:
        la = observation["legal_actions"]
        enemy_ids = {e["entity_id"] for e in observation["enemies"]}
        candidates: List[ToolCall] = [ToolCall(TOOL_END_TURN, {})]

        for atk, target in _attacks_on_enemies(observation, enemy_ids):
            candidates.append(
                ToolCall(
                    TOOL_ATTACK,
                    {"action_name": atk["name"], "defender_id": target["entity_id"]},
                )
            )
        for sp, target in _spells_on_enemies(observation, enemy_ids):
            candidates.append(
                ToolCall(
                    TOOL_CAST_SPELL,
                    {"spell_name": sp["name"], "target_ids": [target["entity_id"]]},
                )
            )
        for move in la.get("moves", []):
            candidates.append(ToolCall(TOOL_MOVE, {"option_id": move["option_id"]}))

        return self._rng.choice(candidates)


class ScriptedAgent(Agent):
    """A deterministic heuristic: hit the weakest reachable enemy, else close, else end.

    Priority each call: (1) attack the lowest-HP reachable enemy; (2) failing that, cast
    a single-target spell at one; (3) failing that, move toward the nearest enemy; (4)
    end the turn. A fixed skill benchmark for LLM agents to be measured against.
    """

    def decide(
        self, observation: Dict[str, Any], tools: List[Dict[str, Any]]
    ) -> ToolCall:
        self_view = observation["self"]
        enemies = observation["enemies"]
        enemy_ids = {e["entity_id"] for e in enemies}

        attack_pairs = _attacks_on_enemies(observation, enemy_ids)
        if attack_pairs:
            target = _pick_target(self_view, [t for _, t in attack_pairs])
            atk = next(
                a for a, t in attack_pairs if t["entity_id"] == target["entity_id"]
            )
            return ToolCall(
                TOOL_ATTACK,
                {"action_name": atk["name"], "defender_id": target["entity_id"]},
            )

        spell_pairs = _spells_on_enemies(observation, enemy_ids)
        if spell_pairs:
            target = _pick_target(self_view, [t for _, t in spell_pairs])
            sp = next(
                s for s, t in spell_pairs if t["entity_id"] == target["entity_id"]
            )
            return ToolCall(
                TOOL_CAST_SPELL,
                {"spell_name": sp["name"], "target_ids": [target["entity_id"]]},
            )

        budget = observation["legal_actions"]["movement_remaining_ft"]
        if budget >= 1 and enemies:
            nearest = min(
                enemies, key=lambda e: _dist(self_view["position"], e["position"])
            )
            move = _move_option_toward(observation, nearest["entity_id"])
            if move is not None:
                return move

        return ToolCall(TOOL_END_TURN, {})
