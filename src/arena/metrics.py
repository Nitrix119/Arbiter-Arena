"""Compute benchmark metrics from a recorded match transcript — the first, no-engine-work slice.

Everything here reads a match's JSONL transcript (see :mod:`src.arena.transcript`) and never
re-runs a model: the log already carries per-action results, per-turn ground-truth snapshots,
and the roster's stat blocks. The metrics are intentionally **un-normalised** — raw counts and
fractions — so we can first check they tell the story we know the logs contain, and calibrate
ranges later.

Two kinds of metric, kept firmly apart:

* **Global (per team).** Always computable and always applicable — conformance (illegal / no-tool
  / forfeit), damage dealt and taken, overkill, the match outcome.
* **Scenario-scoped.** Only meaningful for a *specific subject* in a *specific scenario* — kiting
  adherence for the ranged unit, protected-unit survival for the fragile one. These **never
  auto-apply**: a scoped metric is computed only when a known scenario declares it *and* its
  subject resolves **uniquely** by role. Otherwise it is reported as *not applicable* (with a
  reason) rather than measured on a unit that should not be tracked — the failure mode that would
  silently muddy the signal.
"""

import json
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Loading & indexing
# ---------------------------------------------------------------------------


def load_transcript(path: str) -> List[dict]:
    """Read a match JSONL transcript into a list of records (one per line)."""
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


@dataclass(frozen=True)
class Combatant:
    """The fixed facts about one combatant, from the ``match_start`` roster."""

    entity_id: str
    name: str
    team: str
    max_hp: int
    size_ft: float
    max_attack_range_ft: float

    @property
    def is_ranged(self) -> bool:
        """True when the combatant can attack beyond melee (reach > 5 ft)."""
        return self.max_attack_range_ft > 5.0


def build_roster(records: List[dict]) -> Dict[str, Combatant]:
    """Index the combatants declared in the ``match_start`` record by entity_id."""
    start = _first(records, "match_start")
    roster: Dict[str, Combatant] = {}
    for c in start.get("combatants", []):
        ranges = [a.get("range_ft") or 0.0 for a in c.get("actions", [])]
        roster[c["entity_id"]] = Combatant(
            entity_id=c["entity_id"],
            name=c["name"],
            team=c["team"],
            max_hp=c["max_hp"],
            size_ft=c.get("size_ft", 5.0),
            max_attack_range_ft=max(ranges) if ranges else 0.0,
        )
    return roster


def _first(records: List[dict], kind: str) -> dict:
    for r in records:
        if r.get("kind") == kind:
            return r
    raise ValueError(f"transcript has no {kind!r} record")


def _of_kind(records: List[dict], kind: str) -> List[dict]:
    return [r for r in records if r.get("kind") == kind]


# ---------------------------------------------------------------------------
# Turn grouping & end-cause reconstruction
# ---------------------------------------------------------------------------


@dataclass
class Turn:
    """One combatant's turn: the actor, its action records, and how the turn ended."""

    entity_id: str
    actions: List[dict]
    end_cause: str  # "agent" | "budget" | "cap" | "skip"

    @property
    def forced(self) -> bool:
        return self.end_cause != "agent"


# Mirror of the turn driver's guards (src/arena/turn_driver.py) so we can reconstruct *why* a
# turn ended from the logged action stream — the transcript does not record it directly.
_MAX_CONSECUTIVE_FAILURES = 3
_MAX_TOTAL_FAILURES = 5
_MAX_ACTIONS_PER_TURN = 20


def _end_cause(actions: List[dict]) -> str:
    """Replay the failure-budget logic over a turn's actions to classify how it ended.

    ``agent`` — the agent ended its own turn (a successful ``end_turn``). ``budget`` — the driver
    force-ended after 3 consecutive or 5 total failed calls. ``cap`` — the per-turn action cap.
    ``skip`` — a downed actor took no action.
    """
    if not actions:
        return "skip"
    consecutive = 0
    failures = 0
    acted = 0
    for a in actions:
        ok = bool(a["result"].get("ok"))
        if a["call"]["name"] == "end_turn" and ok:
            return "agent"
        if not ok:
            consecutive += 1
            failures += 1
            if consecutive >= _MAX_CONSECUTIVE_FAILURES or failures >= _MAX_TOTAL_FAILURES:
                return "budget"
        else:
            consecutive = 0
            acted += 1
            if acted >= _MAX_ACTIONS_PER_TURN:
                return "cap"
    return "agent"  # completed without tripping a guard (e.g. a truncated tail)


def group_turns(records: List[dict]) -> List[Turn]:
    """Split the record stream into per-turn groups.

    A turn runs from a ``turn_start`` to the next ``turn_end``. A downed actor is skipped by the
    driver and logs a bare ``turn_end`` (no ``turn_start``, no actions) — captured here as a
    zero-action ``skip`` turn so the counts stay honest.
    """
    turns: List[Turn] = []
    cur_id: Optional[str] = None
    cur_actions: List[dict] = []
    for r in records:
        kind = r.get("kind")
        if kind == "turn_start":
            cur_id = r["entity_id"]
            cur_actions = []
        elif kind == "action":
            cur_actions.append(r)
        elif kind == "turn_end":
            entity_id = cur_id if cur_id is not None else r["entity_id"]
            turns.append(Turn(entity_id, cur_actions, _end_cause(cur_actions)))
            cur_id = None
            cur_actions = []
    return turns


# ---------------------------------------------------------------------------
# HP timelines
# ---------------------------------------------------------------------------


def hp_timeline(records: List[dict], roster: Dict[str, Combatant]) -> Dict[str, List[int]]:
    """Per-entity HP over the match: max HP, then its HP at each ``turn_end`` snapshot.

    Ground truth straight from the ungated snapshots, so it captures every source of HP loss (not
    only logged attack damage). Used for damage-taken and for scoped survival/HP-taken metrics.
    """
    timelines: Dict[str, List[int]] = {eid: [c.max_hp] for eid, c in roster.items()}
    for te in _of_kind(records, "turn_end"):
        for e in te["state"]["entities"]:
            eid = e["entity_id"]
            if eid in timelines and e.get("hp") is not None:
                timelines[eid].append(e["hp"])
    return timelines


def _final_hp(timeline: List[int]) -> int:
    return timeline[-1] if timeline else 0


def _hp_lost(timeline: List[int]) -> int:
    """Total HP lost = sum of downward steps (ignores healing add-back) = damage taken."""
    return sum(max(0, timeline[i - 1] - timeline[i]) for i in range(1, len(timeline)))


# ---------------------------------------------------------------------------
# Damage & overkill from the action stream
# ---------------------------------------------------------------------------


def _action_damage(result: dict) -> List[Tuple[str, int]]:
    """(target_id, damage) pairs an action dealt — one for an attack, many for a spell."""
    if not result.get("ok"):
        return []
    if result.get("action") == "attack" and result.get("target_id") is not None:
        return [(result["target_id"], int(result.get("damage") or 0))]
    pairs = []
    for r in result.get("results", []):  # cast_spell: per-target results
        if r.get("target_id") is not None:
            pairs.append((r["target_id"], int(r.get("damage") or 0)))
    return pairs


# ---------------------------------------------------------------------------
# Metric containers
# ---------------------------------------------------------------------------


@dataclass
class TeamMetrics:
    """Global, always-applicable metrics for one team."""

    team: str
    turns: int = 0
    decisions: int = 0  # every tool call the agent made (ok or not)
    rejected: int = 0  # referee rejected the call (illegal)
    no_tool_calls: int = 0  # model produced no parseable call
    forfeit_turns: int = 0  # turn force-ended by the failure budget
    damage_dealt: int = 0
    damage_taken: int = 0
    overkill: int = 0

    @property
    def illegal_rate(self) -> float:
        return self.rejected / self.decisions if self.decisions else 0.0

    @property
    def damage_per_turn(self) -> float:
        return self.damage_dealt / self.turns if self.turns else 0.0


@dataclass
class ScopedMetric:
    """A scenario-scoped metric, or a record that it did not apply."""

    name: str
    applicable: bool
    subject_id: Optional[str] = None
    subject_name: Optional[str] = None
    values: Dict[str, object] = field(default_factory=dict)
    reason: str = ""  # why it was not applicable, when applicable is False


@dataclass
class MatchReport:
    seed: Optional[int]
    winner: Optional[str]
    reason: str
    rounds: int
    hp_fraction: Dict[str, float]
    survivors: Dict[str, List[str]]
    teams: Dict[str, TeamMetrics]
    scoped: List[ScopedMetric] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Scenario scopes — the applicability declarations
# ---------------------------------------------------------------------------

# A scenario is the *only* thing that authorises a scoped metric, and it names the metric plus the
# role rule that resolves its subject. Resolution must be UNIQUE or the metric declines to apply.
# (Kept as an explicit table, not inferred, precisely so a metric never fires on the wrong unit.)
_SCENARIO_SCOPES: Dict[str, List[Tuple[str, str]]] = {
    "kiting": [("kiting_adherence", "unique_ranged")],
    "protect_squishy": [("protected_survival", "unique_fragile")],
    "alpha_strike": [],  # coordination is a global (focus-fire) metric, added in a later slice
}


def _resolve_subject(role: str, roster: Dict[str, Combatant]) -> Tuple[Optional[Combatant], str]:
    """Resolve a scoped metric's subject by role, requiring uniqueness.

    Returns ``(combatant, "")`` on a unique match, or ``(None, reason)`` when the role matches
    zero or more than one combatant — in which case the metric declines rather than guess.
    """
    if role == "unique_ranged":
        cands = [c for c in roster.values() if c.is_ranged]
        label = "ranged unit"
    elif role == "unique_fragile":
        fewest = min((c.max_hp for c in roster.values()), default=0)
        cands = [c for c in roster.values() if c.max_hp == fewest]
        label = "fragile (lowest max-HP) unit"
    else:
        return None, f"unknown role rule {role!r}"
    if len(cands) == 1:
        return cands[0], ""
    return None, f"{label} is not unique ({len(cands)} candidates); not tracking to avoid a false signal"


# ---------------------------------------------------------------------------
# Scoped metric computations
# ---------------------------------------------------------------------------


def _melee_reach_between(a: Combatant, b: Combatant) -> float:
    """Centre-to-centre distance at which *b* can melee-attack *a* (edge reach + both half-sizes)."""
    return b.max_attack_range_ft + a.size_ft / 2 + b.size_ft / 2


def _positions_by_turn(records: List[dict]) -> List[Dict[str, dict]]:
    """Each ``turn_end`` snapshot as ``{entity_id: {"hp":…, "x":…, "z":…, "alive":…}}``."""
    frames = []
    for te in _of_kind(records, "turn_end"):
        frame = {}
        for e in te["state"]["entities"]:
            pos = e.get("position", {})
            frame[e["entity_id"]] = {
                "hp": e.get("hp"),
                "x": pos.get("x"),
                "z": pos.get("z"),
                "alive": e.get("alive", True),
            }
        frames.append(frame)
    return frames


def _kiting_adherence(
    subject: Combatant, records: List[dict], roster: Dict[str, Combatant]
) -> Dict[str, object]:
    """How well a ranged subject stayed out of melee — the kiting signal.

    ``frac_out_of_melee``: of the snapshots where the subject was alive, the fraction where the
    nearest melee enemy could not reach it. ``rounds_in_melee``: how many it spent reachable.
    ``hp_taken`` / ``final_hp``: the outcome ("wins nearly untouched" vs "stands and trades").
    """
    melee_enemies = [
        c for c in roster.values() if c.team != subject.team and not c.is_ranged
    ]
    frames = _positions_by_turn(records)
    considered = 0
    out_of_melee = 0
    for frame in frames:
        me = frame.get(subject.entity_id)
        if me is None or not me["alive"] or me["x"] is None:
            continue
        reachable = []
        for enemy in melee_enemies:
            ef = frame.get(enemy.entity_id)
            if ef is None or not ef["alive"] or ef["x"] is None:
                continue
            dist = math.dist((me["x"], me["z"]), (ef["x"], ef["z"]))
            reachable.append(dist <= _melee_reach_between(subject, enemy))
        if not reachable:  # no live melee enemy this frame — not a kiting decision point
            continue
        considered += 1
        if not any(reachable):
            out_of_melee += 1
    timeline = hp_timeline(records, roster)[subject.entity_id]
    return {
        "frac_out_of_melee": (out_of_melee / considered) if considered else None,
        "in_melee_snapshots": considered - out_of_melee,
        "snapshots_considered": considered,
        "hp_taken": subject.max_hp - _final_hp(timeline),
        "final_hp": _final_hp(timeline),
        "survived": _final_hp(timeline) > 0,
    }


def _protected_survival(
    subject: Combatant, records: List[dict], roster: Dict[str, Combatant]
) -> Dict[str, object]:
    """Whether the protected unit lived and how much it was hurt — the true objective signal.

    (This is the metric that would have caught the 2026-09-15 false positive: a *won* match in
    which the unit that was supposed to be protected died.)
    """
    timeline = hp_timeline(records, roster)[subject.entity_id]
    final = _final_hp(timeline)
    return {
        "survived": final > 0,
        "final_hp": final,
        "hp_taken": subject.max_hp - final,
        "hp_lost_total": _hp_lost(timeline),
    }


_SCOPED_COMPUTERS = {
    "kiting_adherence": _kiting_adherence,
    "protected_survival": _protected_survival,
}


# ---------------------------------------------------------------------------
# Top-level computation
# ---------------------------------------------------------------------------


def compute_report(records: List[dict], scenario: Optional[str] = None) -> MatchReport:
    """Compute the full metric report for one match transcript.

    *scenario* (when given and known) authorises this match's scenario-scoped metrics; omit it (or
    pass an unknown name) and only the global, always-applicable metrics are produced.
    """
    roster = build_roster(records)
    start = _first(records, "match_start")
    end = _first(records, "match_end")
    turns = group_turns(records)

    teams: Dict[str, TeamMetrics] = {t: TeamMetrics(team=t) for t in {c.team for c in roster.values()}}

    # Per-turn: conformance counts + damage dealt/overkill from the action stream.
    running_hp = {eid: c.max_hp for eid, c in roster.items()}
    for turn in turns:
        actor = roster.get(turn.entity_id)
        if actor is None:
            continue
        tm = teams[actor.team]
        tm.turns += 1
        if turn.end_cause == "budget":
            tm.forfeit_turns += 1
        for a in turn.actions:
            tm.decisions += 1
            if a["call"]["name"] == "(no_tool_call)":
                tm.no_tool_calls += 1
            if not a["result"].get("ok"):
                tm.rejected += 1
                continue
            for target_id, dmg in _action_damage(a["result"]):
                tm.damage_dealt += dmg
                before = running_hp.get(target_id, 0)
                tm.overkill += max(0, dmg - before)
                running_hp[target_id] = max(0, before - dmg)

    # Damage taken: ground-truth HP loss from the snapshots, summed per team.
    timelines = hp_timeline(records, roster)
    for eid, c in roster.items():
        teams[c.team].damage_taken += _hp_lost(timelines[eid])

    scoped = _compute_scoped(records, roster, scenario)
    hp_fraction, survivors = _final_standings(records, roster)

    return MatchReport(
        seed=start.get("seed"),
        winner=end.get("winner"),
        reason=end.get("reason", ""),
        rounds=end.get("rounds", 0),
        hp_fraction=hp_fraction,
        survivors=survivors,
        teams=teams,
        scoped=scoped,
    )


def _final_standings(
    records: List[dict], roster: Dict[str, Combatant]
) -> Tuple[Dict[str, float], Dict[str, List[str]]]:
    """Per-team surviving-HP fraction and survivor names, from the last snapshot.

    Derived here rather than read from ``match_end`` because the transcript's ``match_end`` record
    carries only winner/reason/rounds; the final ``turn_end`` snapshot is the ground truth.
    """
    ends = _of_kind(records, "turn_end")
    cur: Dict[str, int] = {}
    mx: Dict[str, int] = {}
    survivors: Dict[str, List[str]] = {}
    if ends:
        for e in ends[-1]["state"]["entities"]:
            c = roster.get(e["entity_id"])
            if c is None:
                continue
            hp = max(0, e.get("hp") or 0)
            cur[c.team] = cur.get(c.team, 0) + hp
            mx[c.team] = mx.get(c.team, 0) + c.max_hp
            if hp > 0:
                survivors.setdefault(c.team, []).append(c.name)
    hp_fraction = {t: (cur[t] / mx[t] if mx.get(t) else 0.0) for t in mx}
    return hp_fraction, survivors


def _compute_scoped(
    records: List[dict], roster: Dict[str, Combatant], scenario: Optional[str]
) -> List[ScopedMetric]:
    if scenario is None:
        return []
    declarations = _SCENARIO_SCOPES.get(scenario)
    if declarations is None:
        return [ScopedMetric(f"<{scenario}>", applicable=False, reason="unknown scenario; no scope declared")]
    out: List[ScopedMetric] = []
    for metric_name, role in declarations:
        subject, reason = _resolve_subject(role, roster)
        if subject is None:
            out.append(ScopedMetric(metric_name, applicable=False, reason=reason))
            continue
        values = _SCOPED_COMPUTERS[metric_name](subject, records, roster)
        out.append(
            ScopedMetric(
                metric_name,
                applicable=True,
                subject_id=subject.entity_id,
                subject_name=subject.name,
                values=values,
            )
        )
    return out
