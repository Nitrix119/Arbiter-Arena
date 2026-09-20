"""Re-run a recorded match and prove it lands in exactly the same states.

A published result bundle is only worth anything if a stranger can check it. Replay
verification is the check: take a transcript, re-execute the decisions it recorded
against a freshly built combat under the same seed, and confirm every per-turn
:func:`~src.arena.manifest.state_hash` matches. It is a **harness check, not a result**
(V1_PLAN §3.4) — it should be 100%, and anything less means the recording or the engine
is not deterministic in the way the study claims.

**How, and why not the obvious way.** V1_PLAN describes re-executing the recorded
*accepted* actions. That desyncs: when an agent burns its failure budget the turn driver
ends the turn by calling ``combat.end_turn`` directly, never through the
:class:`~src.arena.tools.ToolExecutor`, so that forced end is **not** in the transcript
as an action. Replaying only accepted actions would silently skip it and every
subsequent turn would be off by one.

So instead a :class:`ReplayAgent` feeds the recorded calls — *including the rejected
ones, and the failures that produced no call at all* — back through the ordinary
:func:`~src.arena.match.run_match`. The driver's own budget logic then reproduces forced
ends for free, there is still exactly one execution path (CLAUDE.md §3), and the
question "does a rejection consume RNG?" is answered by construction rather than
assumed.

Entity ids are derived from the roster (:func:`~src.arena.setup.stable_entity_ids`), so
rebuilding needs nothing but the scenario — no seeding dance to make ids line up.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

from src.arena.agent import Agent, NoToolCallError, ProviderError
from src.arena.error_codes import PROVIDER_ERROR
from src.arena.match import run_match
from src.arena.tools import ToolCall
from src.arena.transcript import Transcript
from src.combat.combat_system import CombatSystem

#: The placeholder the turn driver logs when an agent produced no call at all.
NO_TOOL_CALL_NAME = "(no_tool_call)"


@dataclass
class ReplayReport:
    """The verdict, and — when it fails — enough to find out why.

    A verifier that only says "no" sends you back to the transcript by hand, so the
    report names the first diverging turn and both hashes.
    """

    ok: bool
    turns_checked: int
    first_divergence: Optional[int] = None
    expected_hash: Optional[str] = None
    actual_hash: Optional[str] = None
    detail: str = ""

    def __bool__(self) -> bool:
        return self.ok


class ReplayAgent(Agent):
    """Replays one team's recorded decisions, in order, without a model.

    Rejected calls are replayed too, not filtered out: they are part of what happened,
    they are what drives the failure budget to force a turn end, and skipping them
    would quietly change the match being verified.

    Running out of recorded calls is a **failure of the replay**, not a reason to
    improvise — it means the rebuilt match asked for more decisions than the original
    made, which is a divergence and must surface as one.
    """

    def __init__(
        self, name: str, team: Optional[str], calls: Sequence[Dict[str, Any]]
    ) -> None:
        super().__init__(name, team)
        self._calls = list(calls)
        self._index = 0

    @property
    def exhausted(self) -> bool:
        return self._index >= len(self._calls)

    def decide(
        self, observation: Dict[str, Any], tools: List[Dict[str, Any]]
    ) -> ToolCall:
        if self.exhausted:
            raise ReplayDivergence(
                f"{self.name}: the replay asked for more decisions than the "
                f"transcript recorded ({len(self._calls)})."
            )
        record = self._calls[self._index]
        self._index += 1

        name = record["call"]["name"]
        if name == NO_TOOL_CALL_NAME:
            # Reproduce the original non-decision, with its original flavour, so the
            # failure budget advances exactly as it did the first time.
            message = record.get("result", {}).get("error", "no tool call (replayed)")
            if record.get("result", {}).get("code") == PROVIDER_ERROR:
                raise ProviderError(message)
            raise NoToolCallError(message)
        return ToolCall(name, dict(record["call"].get("arguments", {})))


class ReplayDivergence(RuntimeError):
    """The replay could not follow the transcript (not a hash mismatch)."""


def _actions_by_team(
    records: Sequence[Dict[str, Any]], teams: Dict[str, List[str]]
) -> Dict[Optional[str], List[Dict[str, Any]]]:
    """Group recorded actions by the team of the entity that took them.

    An :class:`~src.arena.agent.Agent` controls a *team* (B1), so each replay agent
    needs its own side's decisions in order — interleaved as the initiative order
    produced them.
    """
    team_of = {entity_id: team for team, ids in teams.items() for entity_id in ids}
    grouped: Dict[Optional[str], List[Dict[str, Any]]] = {t: [] for t in teams}
    for record in records:
        if record["kind"] != "action":
            continue
        grouped.setdefault(team_of.get(record["actor_id"]), []).append(record)
    return grouped


def verify(
    records: Sequence[Dict[str, Any]],
    build: Callable[[], CombatSystem],
    *,
    round_cap: Optional[int] = None,
) -> ReplayReport:
    """Re-run the match *records* describe and compare every per-turn state hash.

    Args:
        records: The transcript's records (see
            :meth:`~src.arena.transcript.Transcript.records`).
        build: Rebuilds the *same roster*, unstarted — typically
            ``SCENARIOS[name].build``. Stable entity ids mean this needs no seeding.
        round_cap: Override the recorded cap; defaults to what the match ran with.

    Returns a :class:`ReplayReport`; it never raises for a mismatch, since "this
    transcript does not reproduce" is a result the caller reports, not an error.
    """
    start = next((r for r in records if r["kind"] == "match_start"), None)
    if start is None:
        return ReplayReport(False, 0, detail="transcript has no match_start record")

    expected = [
        r["state_hash"]
        for r in records
        if r["kind"] == "turn_end" and "state_hash" in r
    ]
    if not expected:
        return ReplayReport(
            False,
            0,
            detail=(
                "transcript records no state hashes — it predates hashing and cannot "
                "be verified"
            ),
        )

    grouped = _actions_by_team(records, start["teams"])
    agents: Dict[Optional[str], Agent] = {
        team: ReplayAgent(f"replay:{team}", team, calls)
        for team, calls in grouped.items()
    }

    combat = build()
    replayed = Transcript()
    ran_out: Optional[str] = None
    try:
        run_match(
            combat,
            agents,
            seed=start.get("seed"),
            round_cap=round_cap or start.get("round_cap", 20),
            transcript=replayed,
        )
    except ReplayDivergence as exc:
        # Running out of recorded decisions means the replay outlived the original —
        # so it had already diverged. Compare the turns we *did* get before reporting
        # the exhaustion, since the first differing hash is the useful answer and
        # "ran out of decisions" is only the symptom.
        ran_out = str(exc)

    actual = [r["state_hash"] for r in replayed.records_of("turn_end")]
    report = _compare(expected, actual)
    if report.ok and ran_out:  # matched as far as it went, then simply stopped early
        return ReplayReport(False, len(actual), detail=ran_out)
    if ran_out:
        report.detail = f"{report.detail}; then {ran_out}"
    return report


def _compare(expected: List[str], actual: List[str]) -> ReplayReport:
    for index, (want, got) in enumerate(zip(expected, actual)):
        if want != got:
            return ReplayReport(
                ok=False,
                turns_checked=index,
                first_divergence=index,
                expected_hash=want,
                actual_hash=got,
                detail=f"state diverged at turn index {index}",
            )
    if len(expected) != len(actual):
        return ReplayReport(
            ok=False,
            turns_checked=min(len(expected), len(actual)),
            first_divergence=min(len(expected), len(actual)),
            detail=(
                f"turn count differs: transcript has {len(expected)}, "
                f"replay produced {len(actual)}"
            ),
        )
    return ReplayReport(ok=True, turns_checked=len(expected))


@dataclass
class BundleReport:
    """Verification across a result bundle — §5's "replays verify 100%" check."""

    total: int = 0
    verified: int = 0
    failures: List[str] = field(default_factory=list)

    @property
    def rate(self) -> float:
        return self.verified / self.total if self.total else 0.0

    def __bool__(self) -> bool:
        """True only at 100%. An empty bundle is not a pass: nothing was checked."""
        return self.total > 0 and self.verified == self.total


def verify_bundle(
    transcripts: Dict[str, Sequence[Dict[str, Any]]],
    resolve_build: Callable[[Sequence[Dict[str, Any]]], Callable[[], CombatSystem]],
) -> BundleReport:
    """Verify every transcript in a bundle, keyed by a label (usually a filename).

    *resolve_build* turns a transcript into the builder for its roster — for the study
    grid that is a lookup of ``match_start["scenario"]`` in ``SCENARIOS``. Passing it
    in keeps this module from importing the scenario catalogue, so a caller with its
    own rosters can verify too.
    """
    report = BundleReport()
    for label, records in transcripts.items():
        report.total += 1
        result = verify(records, resolve_build(records))
        if result.ok:
            report.verified += 1
        else:
            report.failures.append(f"{label}: {result.detail}")
    return report
