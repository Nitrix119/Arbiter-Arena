"""Turn a study bundle into the pre-registered measurements.

    python -m src.arena.study report results/<name>

Reads every completed transcript under the bundle (``_excluded/`` is counted, never
analysed) and writes three files to ``<bundle>/report/``:

* ``decisions.csv`` — one row per **model decision**: what was attempted, whether it
  was accepted, whether it was valid *first time*, and what it cost.
* ``matches.csv`` — one row per match: outcome, validity, cost, tactical metrics.
* ``summary.md`` — the tables the hypotheses are judged on, per model x condition.

**Definitions, exactly as registered** (PREREGISTRATION §6–§7):

* *Fresh decision*: one not preceded by a rejection of the same actor in the same
  turn. A retry after a rejection is **recovery**, never a second first attempt.
* *First-attempt valid* (H1): a **fresh** decision that was accepted **and** took one
  request. A decision that needed the correction re-prompt failed its first attempt
  even if the second succeeded — the same rule in every condition (ledger A2).
  *Per-call acceptance* (every call, retries included) is reported alongside.
* *Recovery*: after a rejected decision, the same actor's next decision in the same turn
  was accepted. Rejections with no later decision that turn are not counted.
* *Spatial* (H2): a move, or a cast of an area spell however it was aimed (at a
  point, or wrongly at a creature). For a refused attempt, judged from what was
  attempted — a C1 line starting with a move verb, or a cast giving coordinates or
  naming an area spell; a C3 id naming a move or an aim point. A response with no
  action at all is neither.
* Rates are pooled over decisions; intervals are a **match-level (cluster) bootstrap**
  — decisions within a match are not independent — with a fixed seed, so the report
  is byte-identical every time it is run. Win rates use **Wilson** intervals.
* *Registered verdicts* (H1–H3) use a **paired** cluster bootstrap over the
  (scenario, seed) pairs both conditions share, per model; a directional hypothesis
  is supported when the 95% interval of its contrast lies entirely above zero.

Standard library only: no numpy, no pandas, no plots (ledger A11).
"""

import csv
import functools
import io
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, FrozenSet, Iterable, List, Optional, Sequence, Tuple

from src.arena.free_text import UNREAD_TEXT
from src.arena.identifiers import identifier_key
from src.arena.interfaces import REGISTRY
from src.arena.metrics import area_hits, compute_report
from src.arena.mock_model import MOCK_MODEL
from src.arena.rescore import Bounded, RescoreError, rescore
from src.arena.scenarios import SCENARIOS, model_team
from src.models.spell_properties import AOEShape
from src.utils import dice

REPORT_DIR = "report"
BOOTSTRAP_SEED = 20260924
BOOTSTRAP_RESAMPLES = 2000
CONFIDENCE = 0.95
_Z = 1.959963984540054  # two-sided 95% normal quantile, for Wilson

_EXCLUDED_DIR = "_excluded"
_NO_CALL = "(no_tool_call)"
_MOVE_VERBS = {"move", "go", "walk", "run", "step"}
#: C1's other verbs, as its grammar reads them (``free_text.GRAMMAR``).
_ATTACK_VERBS = {"attack", "hit", "strike", "shoot", "stab"}
_END_WORDS = {"end", "pass", "done"}
_FILLERS = re.compile(r"^(?:i\s+will|i'll|i|will)\s+", re.IGNORECASE)
_COORDINATES = re.compile(r"\b[xyz]\s*[=:]|\(", re.IGNORECASE)

#: The conditions in their registered order, for stable table rows.
_CONDITION_ORDER = {name: index for index, name in enumerate(REGISTRY)}


# -- statistics -------------------------------------------------------------------


def wilson(successes: int, trials: int) -> Optional[Tuple[float, float]]:
    """The Wilson score interval for a binomial proportion, or ``None`` with no data."""
    if trials == 0:
        return None
    p = successes / trials
    denominator = 1 + _Z**2 / trials
    centre = (p + _Z**2 / (2 * trials)) / denominator
    half = _Z * math.sqrt(p * (1 - p) / trials + _Z**2 / (4 * trials**2)) / denominator
    return max(0.0, centre - half), min(1.0, centre + half)


def _percentiles(values: List[float]) -> Tuple[float, float]:
    values.sort()
    tail = (1 - CONFIDENCE) / 2
    low = values[int(tail * len(values))]
    high = values[min(len(values) - 1, int((1 - tail) * len(values)))]
    return low, high


def cluster_ratio(
    clusters: Sequence[Tuple[float, float]],
) -> Optional[Tuple[float, float, float]]:
    """A pooled ratio Σnum/Σden with a cluster-bootstrap interval.

    Each cluster is one match's ``(numerator, denominator)``: whole matches are
    resampled, because decisions within a match are not independent. Resamples whose
    denominator is zero are skipped. Seeded, so the interval is reproducible.
    """
    clusters = [c for c in clusters if c[1] > 0]
    if not clusters:
        return None
    point = sum(n for n, _ in clusters) / sum(d for _, d in clusters)
    rng = dice.new_rng(BOOTSTRAP_SEED)  # dice.py owns every RNG (CLAUDE.md §7)
    stats: List[float] = []
    for _ in range(BOOTSTRAP_RESAMPLES):
        sample = [clusters[rng.randrange(len(clusters))] for _ in clusters]
        stats.append(sum(n for n, _ in sample) / sum(d for _, d in sample))
    low, high = _percentiles(stats)
    return point, low, high


def bootstrap_mean(values: Sequence[float]) -> Optional[Tuple[float, float, float]]:
    """A mean over matches with a bootstrap interval (each match one draw)."""
    return cluster_ratio([(v, 1.0) for v in values])


# -- reading the bundle -----------------------------------------------------------


def _read(path: Path) -> List[Dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def completed_transcripts(bundle: Path) -> List[Tuple[Path, List[Dict[str, Any]]]]:
    """Every completed cell, in a stable order. Excluded attempts are not analysed."""
    out = []
    for path in sorted(bundle.rglob("seed*.jsonl")):
        relative = path.relative_to(bundle).parts
        if relative[0] in (_EXCLUDED_DIR, REPORT_DIR):
            continue
        out.append((path, _read(path)))
    return out


def excluded_attempts(bundle: Path) -> int:
    root = bundle / _EXCLUDED_DIR
    return len(list(root.rglob("*.jsonl"))) if root.exists() else 0


#: Cell key: (model, condition).
Cell = Tuple[str, str]


def excluded_by_cell(bundle: Path) -> Dict[Cell, int]:
    """Excluded attempts per model x condition, read from each attempt's own record."""
    counts: Counter = Counter()
    root = bundle / _EXCLUDED_DIR
    for path in sorted(root.rglob("*.jsonl")) if root.exists() else []:
        start = next((r for r in _read(path) if r.get("kind") == "match_start"), None)
        if start is not None:
            counts[
                (str(start.get("model", "?")), str(start.get("condition", "?")))
            ] += 1
    return dict(counts)


def _reason_kind(reason: str) -> str:
    """A runner's exclusion reason reduced to its kind: the exception type, or
    ``provider_error`` for a transcript that recorded one."""
    if "provider_error" in reason:
        return "provider_error"
    return reason.split(":", 1)[0].strip() or "unknown"


def exclusion_reasons(bundle: Path) -> Dict[Cell, Counter]:
    """Why each model x condition's attempts were excluded, from the run log."""
    reasons: Dict[Cell, Counter] = defaultdict(Counter)
    log = bundle / "run_log.jsonl"
    if not log.exists():
        return {}
    for event in _read(log):
        if event.get("event") != "cell_excluded":
            continue
        parts = [p.strip() for p in str(event.get("cell", "")).split("|")]
        if len(parts) >= 2:
            reasons[(parts[0], parts[1])][
                _reason_kind(str(event.get("reason", "")))
            ] += 1
    return dict(reasons)


def _infrastructure_section(
    decisions: List["Decision"],
    matches: List["Match"],
    excluded: Dict[Cell, int],
    reasons: Dict[Cell, Counter],
) -> List[str]:
    """Exclusions and provider retries per model x condition (prereg §8).

    Exclusion is for infrastructure only, but a host that fails on a model's own
    malformed output would make exclusions track the condition, and a condition-
    correlated exclusion rate biases every comparison. Shown per cell, never as one
    total, so that pattern is visible.
    """
    retries: Counter = Counter()
    for d in decisions:
        retries[(d.model, d.condition)] += d.provider_retries
    keys = sorted(
        {(m.model, m.condition) for m in matches} | set(excluded),
        key=lambda k: (k[0], _CONDITION_ORDER.get(k[1], 99)),
    )
    if not keys:
        return []

    def why(key: Cell) -> str:
        counted = reasons.get(key)
        if not counted:
            return "—"
        return ", ".join(f"{kind} x{n}" for kind, n in sorted(counted.items()))

    return [
        "",
        "## Infrastructure (prereg §8)",
        "",
        "Excluded attempts were re-run and are not analysed. Provider retries are "
        "failed requests repeated unchanged inside a kept match: billed, never counted "
        "as a model attempt. Either one rising with the condition is a warning sign.",
        "",
        _table(
            ["model", "condition", "excluded attempts", "provider retries", "reasons"],
            [
                [m, c, str(excluded.get((m, c), 0)), str(retries[(m, c)]), why((m, c))]
                for m, c in keys
            ],
        ),
    ]


def _prices(bundle: Path) -> Dict[str, Tuple[float, float]]:
    """model id → (usd per M input, usd per M output), from the bundle's grid copy."""
    grid_file = bundle / "grid.toml"
    if not grid_file.exists():
        return {}
    from src.arena.study import GridError, load_grid

    try:
        grid = load_grid(grid_file)
    except GridError:
        return {}
    return {m.id: (m.usd_per_m_input, m.usd_per_m_output) for m in grid.models}


# -- decisions --------------------------------------------------------------------


@dataclass
class Decision:
    """One decision by the model's team — the unit every validity rate is over."""

    model: str
    condition: str
    scenario: str
    seed: int
    match: str
    round: int
    turn: int
    actor: str
    index: int
    kind: str
    spatial: Optional[bool]
    ok: bool
    code: str
    first_attempt_valid: bool
    request_count: int
    input_tokens: int
    output_tokens: int
    latency_ms: float
    menu_length: Optional[int]
    c1_layer: Optional[int]
    served_provider: Optional[str] = None
    #: Whether a C1 response said anything besides the command that was read.
    #: Recorded apart from the layer, which describes the command alone (prereg §7).
    c1_prose: bool = False
    #: Requests the provider failed and that were retried unchanged (prereg §8).
    #: Cost, never a model attempt — ``request_count`` excludes them.
    provider_retries: int = 0
    #: Not a retry: the same actor's previous decision this turn was not rejected.
    #: H1 is measured over fresh decisions only (prereg §6).
    fresh: bool = True
    #: Requests this decision's model response was cut off at the token limit.
    length_cutoffs: int = 0
    #: Whether a length cap removed real options from the menu shown (menus only).
    menu_truncated: Optional[bool] = None
    #: The model the provider says served the decision's last request.
    served_model: Optional[str] = None
    #: Requests whose response held more than one tool call (refused if they
    #: differed, prereg §6) — visible per cell even when refused.
    multi_call_responses: int = 0
    #: What kind of action was attempted (:func:`intended_kind`), read the same way
    #: in every condition; ``None`` when the attempt named no action.
    intent: Optional[str] = None
    #: Whether the provider billed this decision, so its cost is knowable.
    #: ``None`` for a deterministic agent, which called no provider at all —
    #: ``input_tokens`` is coerced to ``0`` above and cannot tell the two apart.
    usage_reported: Optional[bool] = None


def _attempted_verb(text: str) -> str:
    words = _FILLERS.sub("", text.strip()).split()
    return words[0].casefold() if words else ""


@functools.lru_cache(maxsize=None)
def _area_spells(scenario: str) -> FrozenSet[str]:
    """Identifier keys of the area spells *scenario*'s creatures know.

    Only areas aimed at a point: a cone or line starts at the caster and is only
    pointed, as :func:`~src.arena.tools._refuse_out_of_range_aim` treats it. An
    unknown roster gives the empty set, which leaves classification by argument
    shape alone.
    """
    entry = SCENARIOS.get(scenario)
    if entry is None:
        return frozenset()
    combat = entry.build()
    registry = combat.spell_registry
    if registry is None:
        return frozenset()
    keys = set()
    for creature in combat.combatants:
        for name in creature.stat_block.known_spells:
            if name not in registry:
                continue
            area = registry.get(name).aoe
            if area is not None and area.shape not in (AOEShape.CONE, AOEShape.LINE):
                keys.add(identifier_key(name))
    return frozenset(keys)


def _names_area_spell(written: Any, area_spells: FrozenSet[str]) -> bool:
    return isinstance(written, str) and identifier_key(written) in area_spells


def classify(
    call: Dict[str, Any], area_spells: FrozenSet[str] = frozenset()
) -> Tuple[str, Optional[bool]]:
    """(kind, spatial) for a recorded call — what was attempted, accepted or not.

    A cast of an *area* spell (*area_spells*, by identifier key) is spatial however
    it was aimed: aiming one at a creature is the typical spatial mistake, and under
    C3 every area option is spatial by its ``:aim:`` id (prereg §6).
    """
    name = call.get("name", "")
    args = call.get("arguments", {}) or {}
    if name == "move":
        return "move", True
    if name == "cast_spell":
        if "target_point" in args:
            return "cast_point", True
        return "cast_target", _names_area_spell(args.get("spell_name"), area_spells)
    if name in ("attack", "end_turn"):
        return name, False
    if name == UNREAD_TEXT:
        text = str(args.get("text", ""))
        verb = _attempted_verb(text)
        spatial = verb in _MOVE_VERBS or (
            verb == "cast"
            and (
                bool(_COORDINATES.search(text))
                or any(key in identifier_key(text) for key in area_spells)
            )
        )
        return "unread", spatial
    if name == "choose":
        action_id = args.get("action_id")
        if not isinstance(action_id, str) or not action_id:
            return "choose", None  # names no action, so it is neither
        return "choose", action_id.startswith("move:") or ":aim:" in action_id
    if name == _NO_CALL:
        return "none", None
    return "unknown_tool", None


def intended_kind(
    call: Dict[str, Any], area_spells: FrozenSet[str] = frozenset()
) -> Optional[str]:
    """The kind of action a recorded attempt was — accepted or refused, any condition.

    One of ``move``, ``cast_area``, ``cast_target``, ``attack``, ``end_turn``, or
    ``None`` for an attempt that names no action. Needed because a refusal is logged
    in its condition's own shape — a C1 line as ``(unread_text)``, a C3 pick as
    ``choose`` — so comparing *which* actions each condition attempted means reading
    each attempt for what it names. Descriptive only (prereg §7): the action mix a
    condition induces, not a registered verdict.
    """
    name = call.get("name", "")
    args = call.get("arguments", {}) or {}
    if name in ("move", "attack", "end_turn"):
        return str(name)
    if name == "cast_spell":
        area = "target_point" in args or _names_area_spell(
            args.get("spell_name"), area_spells
        )
        return "cast_area" if area else "cast_target"
    if name == UNREAD_TEXT:
        text = str(args.get("text", ""))
        verb = _attempted_verb(text)
        if verb in _MOVE_VERBS:
            return "move"
        if verb in _ATTACK_VERBS:
            return "attack"
        if verb in _END_WORDS:
            return "end_turn"
        if verb == "cast":
            _, spatial = classify(call, area_spells)
            return "cast_area" if spatial else "cast_target"
        return None
    if name == "choose":
        action_id = args.get("action_id")
        if not isinstance(action_id, str):
            return None
        if action_id == "end_turn":
            return "end_turn"
        if action_id.startswith("move:"):
            return "move"
        if action_id.startswith("attack:"):
            return "attack"
        if action_id.startswith("cast:"):
            return "cast_area" if ":aim:" in action_id else "cast_target"
    return None


def decisions_of(path: Path, records: List[Dict[str, Any]]) -> List[Decision]:
    start = next(r for r in records if r["kind"] == "match_start")
    team = model_team(start, records)
    members = set(start.get("teams", {}).get(team, []))
    area_spells = _area_spells(str(start.get("scenario", "")))
    out: List[Decision] = []
    round_number = turn = 0
    for record in records:
        if record["kind"] == "turn_start":
            round_number = record.get("round", round_number)
            turn += 1
            continue
        if record["kind"] != "action" or record["actor_id"] not in members:
            continue
        telemetry = record.get("telemetry") or {}
        requests = telemetry.get("requests") or []
        layer = None
        prose = False
        host = None
        if requests:
            reading = requests[-1].get("interpretation") or {}
            layer = reading.get("layer")
            prose = bool(reading.get("prose", False))
            host = requests[-1].get("served_provider")
        kind, spatial = classify(record["call"], area_spells)
        ok = bool(record["result"].get("ok"))
        count = telemetry.get("request_count", 1)
        before = out[-1] if out else None
        retry = (
            before is not None
            and not before.ok
            and before.turn == turn
            and before.actor == record["actor_id"]
        )
        out.append(
            Decision(
                model=str(start.get("model", "?")),
                condition=str(start.get("condition", "?")),
                scenario=str(start.get("scenario", "?")),
                seed=int(start.get("seed") or 0),
                match=path.as_posix(),
                round=round_number,
                turn=turn,
                actor=record["actor_id"],
                index=len(out),
                kind=kind,
                spatial=spatial,
                ok=ok,
                code="" if ok else str(record["result"].get("code", "")),
                first_attempt_valid=ok and count == 1,
                request_count=count,
                input_tokens=telemetry.get("input_tokens") or 0,
                output_tokens=telemetry.get("output_tokens") or 0,
                latency_ms=float(telemetry.get("latency_ms") or 0.0),
                menu_length=telemetry.get("menu_length"),
                c1_layer=layer,
                c1_prose=prose,
                served_provider=host,
                provider_retries=len(telemetry.get("provider_failures") or []),
                fresh=not retry,
                length_cutoffs=sum(
                    1 for r in requests if r.get("finish_reason") == "length"
                ),
                menu_truncated=telemetry.get("menu_truncated"),
                multi_call_responses=sum(
                    1 for r in requests if (r.get("extra_tool_calls") or 0) > 0
                ),
                intent=intended_kind(record["call"], area_spells),
                usage_reported=(
                    bool(telemetry.get("usage_reported", True)) if telemetry else None
                ),
                served_model=next(
                    (
                        r["served_model"]
                        for r in reversed(requests)
                        if r.get("served_model")
                    ),
                    None,
                ),
            )
        )
    return out


def recoveries(decisions: Sequence[Decision]) -> Tuple[int, int]:
    """(recovered, rejections followed by another decision in the same turn)."""
    recovered = eligible = 0
    for before, after in zip(decisions, decisions[1:]):
        if before.ok or after.turn != before.turn or after.actor != before.actor:
            continue
        eligible += 1
        recovered += after.ok
    return recovered, eligible


# -- matches ----------------------------------------------------------------------


@dataclass
class Match:
    """One completed cell, summarised."""

    model: str
    condition: str
    scenario: str
    seed: int
    match: str
    model_won: bool
    winner: str
    rounds: int
    model_hp_fraction: float
    turns: int
    forfeit_turns: int
    decisions: int
    #: Decisions that were not retries after a rejection — H1's denominator.
    fresh_decisions: int
    #: Fresh decisions valid first time (H1's numerator).
    first_attempt_valid: int
    #: Every call accepted in one request, retries included (secondary).
    per_call_valid: int
    accepted: int
    recovered: int
    recovery_eligible: int
    spatial_decisions: int
    spatial_valid: int
    nonspatial_decisions: int
    nonspatial_valid: int
    input_tokens: int
    output_tokens: int
    cost_usd: Optional[float]
    area_casts: int
    area_enemies: int
    area_allies: int
    tactics: Dict[str, float] = field(default_factory=dict)


def match_of(
    path: Path,
    records: List[Dict[str, Any]],
    decisions: List[Decision],
    prices: Dict[str, Tuple[float, float]],
) -> Match:
    start = next(r for r in records if r["kind"] == "match_start")
    scenario = str(start.get("scenario", "?"))
    team = model_team(start, records) or ""
    report = compute_report(records, scenario if scenario in SCENARIOS else None)
    team_metrics = report.teams.get(team)
    members = set(start.get("teams", {}).get(team, []))
    hits = [h for h in area_hits(records) if h.actor_id in members]
    recovered, eligible = recoveries(decisions)
    tokens_in = sum(d.input_tokens for d in decisions)
    tokens_out = sum(d.output_tokens for d in decisions)
    price = prices.get(str(start.get("model")))
    tactics: Dict[str, float] = {}
    for scoped in report.scoped:
        if not scoped.applicable:
            continue
        for key, value in sorted(scoped.values.items()):
            if isinstance(value, (bool, int, float)):
                tactics[f"{scoped.name}.{key}"] = float(value)
    fresh = [d for d in decisions if d.fresh]
    spatial = [d for d in fresh if d.spatial is True]
    nonspatial = [d for d in fresh if d.spatial is False]
    return Match(
        model=str(start.get("model", "?")),
        condition=str(start.get("condition", "?")),
        scenario=scenario,
        seed=int(start.get("seed") or 0),
        match=path.as_posix(),
        model_won=report.winner == team,
        winner=str(report.winner),
        rounds=report.rounds,
        model_hp_fraction=report.hp_fraction.get(team, 0.0),
        turns=team_metrics.turns if team_metrics else 0,
        forfeit_turns=team_metrics.forfeit_turns if team_metrics else 0,
        decisions=len(decisions),
        fresh_decisions=len(fresh),
        first_attempt_valid=sum(d.first_attempt_valid for d in fresh),
        per_call_valid=sum(d.first_attempt_valid for d in decisions),
        accepted=sum(d.ok for d in decisions),
        recovered=recovered,
        recovery_eligible=eligible,
        spatial_decisions=len(spatial),
        spatial_valid=sum(d.first_attempt_valid for d in spatial),
        nonspatial_decisions=len(nonspatial),
        nonspatial_valid=sum(d.first_attempt_valid for d in nonspatial),
        input_tokens=tokens_in,
        output_tokens=tokens_out,
        cost_usd=(
            (tokens_in * price[0] + tokens_out * price[1]) / 1_000_000
            if price
            else None
        ),
        area_casts=len(hits),
        area_enemies=sum(h.enemies for h in hits),
        area_allies=sum(h.allies for h in hits),
        tactics=tactics,
    )


# -- the summary ------------------------------------------------------------------


def _cell_key(item: Any) -> Tuple[str, int]:
    return item.model, _CONDITION_ORDER.get(item.condition, 99)


def _fmt(value: Optional[float], digits: int = 3) -> str:
    return "—" if value is None else f"{value:.{digits}f}"


def _fmt_ci(result: Optional[Tuple[float, float, float]], digits: int = 3) -> str:
    if result is None:
        return "—"
    point, low, high = result
    return f"{point:.{digits}f} [{low:.{digits}f}, {high:.{digits}f}]"


def _fmt_wilson(successes: int, trials: int) -> str:
    interval = wilson(successes, trials)
    if interval is None:
        return "—"
    return f"{successes / trials:.3f} [{interval[0]:.3f}, {interval[1]:.3f}]"


def _table(header: Sequence[str], rows: Iterable[Sequence[str]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join(lines)


#: The intended kinds, non-spatial first, then "no action" (:func:`intended_kind`).
_INTENTS: Tuple[Optional[str], ...] = (
    "end_turn",
    "attack",
    "cast_target",
    "cast_area",
    "move",
    None,
)


def _mix_section(decisions: List[Decision]) -> List[str]:
    """What each condition attempted, and H1 with the action mix held still.

    First-attempt validity is a rate over the actions a model *chose* to attempt. A
    condition that led it to attempt easier things — more turn-endings, which are
    almost always valid — would look more valid without being so. Two sensitivity
    figures, registered in prereg §7 as descriptive and never as verdicts:

    * **without end_turn** — H1 over fresh decisions that were not an end-turn;
    * **at a common mix** — each kind's first-attempt validity in this condition,
      weighted by that kind's share of the model's fresh decisions across all its
      conditions. Undefined ("—") when the condition never attempted a kind the
      others did, since its validity there is unknown rather than zero.
    """
    fresh = [d for d in decisions if d.fresh]
    if not fresh:
        return []
    kinds = [k for k in _INTENTS if any(d.intent == k for d in fresh)]
    cells: Dict[Cell, List[Decision]] = defaultdict(list)
    by_model: Dict[str, List[Decision]] = defaultdict(list)
    for d in fresh:
        cells[(d.model, d.condition)].append(d)
        by_model[d.model].append(d)

    def valid_rate(group: List[Decision]) -> Optional[float]:
        return sum(d.first_attempt_valid for d in group) / len(group) if group else None

    rows = []
    for model, condition in sorted(cells, key=lambda k: (k[0], _cell_key_of(k[1]))):
        group = cells[(model, condition)]
        counts = []
        common: Optional[float] = 0.0
        pool = by_model[model]
        for kind in kinds:
            of_kind = [d for d in group if d.intent == kind]
            rate = valid_rate(of_kind)
            counts.append(f"{len(of_kind)} ({_fmt(rate)})" if of_kind else "0")
            weight = sum(d.intent == kind for d in pool) / len(pool)
            if weight and rate is None:
                common = None
            elif common is not None and rate is not None:
                common += weight * rate
        clusters: Dict[str, List[Decision]] = defaultdict(list)
        for d in group:
            if d.intent != "end_turn":
                clusters[d.match].append(d)
        without_end = cluster_ratio(
            [
                (sum(d.first_attempt_valid for d in ds), len(ds))
                for ds in clusters.values()
            ]
        )
        rows.append([model, condition, *counts, _fmt_ci(without_end), _fmt(common)])

    return [
        "",
        "## Validity by intended action (descriptive, prereg §7)",
        "",
        "Fresh decisions of each kind, with their first-attempt validity in brackets. "
        "The last two columns are sensitivity figures, not verdicts: H1 without "
        "end-turn decisions, and H1 with each kind weighted by its share across all of "
        "the model's conditions, so a condition cannot look more valid by attempting "
        "easier actions.",
        "",
        _table(
            [
                "model",
                "condition",
                *[k if k is not None else "no action" for k in kinds],
                "H1 without end_turn",
                "H1 at a common mix",
            ],
            rows,
        ),
    ]


def summarise(
    name: str,
    decisions: List[Decision],
    matches: List[Match],
    excluded: int,
    excluded_cells: Optional[Dict[Cell, int]] = None,
    reasons: Optional[Dict[Cell, Counter]] = None,
) -> str:
    groups: Dict[Tuple[str, str], List[Match]] = defaultdict(list)
    decision_groups: Dict[Tuple[str, str], List[Decision]] = defaultdict(list)
    for m in sorted(matches, key=_cell_key):
        groups[(m.model, m.condition)].append(m)
    for d in decisions:
        decision_groups[(d.model, d.condition)].append(d)
    keys = list(groups)

    parts = [
        f"# Study report — {name}",
        "",
        f"{len(matches)} completed matches, {len(decisions)} model decisions; "
        f"{excluded} excluded attempt(s) under `_excluded/` (infrastructure only, "
        "re-run; not analysed). Intervals: 95% match-level bootstrap "
        f"(seed {BOOTSTRAP_SEED}, {BOOTSTRAP_RESAMPLES} resamples); win rates: Wilson.",
        "",
        "## Validity (H1)",
        "",
        _table(
            [
                "model",
                "condition",
                "matches",
                "decisions",
                "fresh",
                "first-attempt valid (fresh)",
                "per-call acceptance",
                "eventually accepted",
                "recovery",
                "forfeit turns / turn",
            ],
            [
                [
                    model,
                    condition,
                    str(len(group)),
                    str(sum(m.decisions for m in group)),
                    str(sum(m.fresh_decisions for m in group)),
                    _fmt_ci(
                        cluster_ratio(
                            [(m.first_attempt_valid, m.fresh_decisions) for m in group]
                        )
                    ),
                    _fmt_ci(
                        cluster_ratio([(m.per_call_valid, m.decisions) for m in group])
                    ),
                    _fmt_ci(cluster_ratio([(m.accepted, m.decisions) for m in group])),
                    _fmt_ci(
                        cluster_ratio(
                            [(m.recovered, m.recovery_eligible) for m in group]
                        )
                    ),
                    _fmt_ci(cluster_ratio([(m.forfeit_turns, m.turns) for m in group])),
                ]
                for (model, condition), group in groups.items()
            ],
        ),
        "",
        "## Where validity fails: spatial vs non-spatial (H2)",
        "",
        "Fresh decisions only, as in H1.",
        "",
        _table(
            [
                "model",
                "condition",
                "spatial n",
                "spatial first-attempt valid",
                "non-spatial n",
                "non-spatial first-attempt valid",
            ],
            [
                [
                    model,
                    condition,
                    str(sum(m.spatial_decisions for m in group)),
                    _fmt_ci(
                        cluster_ratio(
                            [(m.spatial_valid, m.spatial_decisions) for m in group]
                        )
                    ),
                    str(sum(m.nonspatial_decisions for m in group)),
                    _fmt_ci(
                        cluster_ratio(
                            [
                                (m.nonspatial_valid, m.nonspatial_decisions)
                                for m in group
                            ]
                        )
                    ),
                ]
                for (model, condition), group in groups.items()
            ],
        ),
        *_mix_section(decisions),
        "",
        "## Rejected decisions by code",
        "",
    ]

    codes = sorted({d.code for d in decisions if d.code})
    parts.append(
        _table(
            ["model", "condition", *codes],
            [
                [
                    model,
                    condition,
                    *[
                        str(
                            Counter(
                                d.code for d in decision_groups[(model, condition)]
                            )[code]
                        )
                        for code in codes
                    ],
                ]
                for (model, condition) in keys
            ],
        )
        if codes
        else "No rejected decisions."
    )

    parts += [
        "",
        "## Cost",
        "",
        _table(
            [
                "model",
                "condition",
                "input tokens / accepted",
                "output tokens / accepted",
                "$ / accepted",
                "mean menu length",
            ],
            [_cost_row(key, groups[key], decision_groups[key]) for key in keys],
        ),
        "",
        "## Outcome",
        "",
        _table(
            ["model", "condition", "win rate", "model HP fraction"],
            [
                [
                    model,
                    condition,
                    _fmt_wilson(sum(m.model_won for m in group), len(group)),
                    _fmt_ci(bootstrap_mean([m.model_hp_fraction for m in group])),
                ]
                for (model, condition), group in groups.items()
            ],
        ),
        "",
        "## Area spells (H4b)",
        "",
        _table(
            [
                "model",
                "condition",
                "area casts",
                "enemies caught / cast",
                "allies caught / cast",
            ],
            [
                [
                    model,
                    condition,
                    str(sum(m.area_casts for m in group)),
                    _fmt_ci(
                        cluster_ratio([(m.area_enemies, m.area_casts) for m in group])
                    ),
                    _fmt_ci(
                        cluster_ratio([(m.area_allies, m.area_casts) for m in group])
                    ),
                ]
                for (model, condition), group in groups.items()
            ],
        ),
    ]

    parts += _verdicts_section(registered_verdicts(matches))
    parts += _tactics_sections(matches)
    parts += _layer_section(decisions)
    parts += _hosts_section(decisions)
    parts += _integrity_section(decisions)
    parts += _infrastructure_section(
        decisions, matches, excluded_cells or {}, reasons or {}
    )
    return "\n".join(parts) + "\n"


# -- registered verdicts (prereg §7) -------------------------------------------------

#: H1's predicted ordering, as adjacent contrasts (higher first).
H1_CONTRASTS = (("C3", "C2+M"), ("C2+M", "C2"), ("C2", "C1"))
#: The conditions H2 is stated about, each measured against the menu (C3).
H2_CONDITIONS = ("C1", "C2")

Pair = Tuple[str, int]
#: condition → (scenario, seed) → that match.
_Cells = Dict[str, Dict[Pair, "Match"]]
Estimate = Tuple[float, float, float]


@dataclass(frozen=True)
class Verdict:
    """One registered contrast for one model, and what the data say about it."""

    model: str
    hypothesis: str
    contrast: str
    pairs: int
    estimate: Optional[Estimate]
    verdict: str
    note: str = ""


def _rate(
    matches: Iterable["Match"], numerator: str, denominator: str
) -> Optional[float]:
    num = den = 0.0
    for m in matches:
        num += float(getattr(m, numerator))
        den += float(getattr(m, denominator))
    return num / den if den else None


def _mean(matches: Sequence["Match"], attribute: str) -> Optional[float]:
    if not matches:
        return None
    return sum(float(getattr(m, attribute)) for m in matches) / len(matches)


def paired_bootstrap(pairs: Sequence[Pair], statistic: Any) -> Optional[Estimate]:
    """*statistic* over the pairs, with a paired cluster-bootstrap 95% interval.

    Whole (scenario, seed) pairs are resampled, so both conditions' matches for a pair
    travel together — the pairing the design registers. Resamples on which the
    statistic is undefined (a zero denominator) are skipped. Seeded, so deterministic.
    """
    if not pairs:
        return None
    point = statistic(list(pairs))
    if point is None:
        return None
    rng = dice.new_rng(BOOTSTRAP_SEED)  # dice.py owns every RNG (CLAUDE.md §7)
    stats: List[float] = []
    for _ in range(BOOTSTRAP_RESAMPLES):
        sample = [pairs[rng.randrange(len(pairs))] for _ in pairs]
        value = statistic(sample)
        if value is not None:
            stats.append(value)
    if not stats:
        return None
    low, high = _percentiles(stats)
    return point, low, high


def _judge(estimate: Optional[Estimate]) -> str:
    if estimate is None:
        return "insufficient data"
    return "supported" if estimate[1] > 0 else "not supported"


def _difference(
    cells: _Cells, high: str, low: str, numerator: str, denominator: str
) -> Any:
    def statistic(sample: Sequence[Pair]) -> Optional[float]:
        a = _rate((cells[high][p] for p in sample), numerator, denominator)
        b = _rate((cells[low][p] for p in sample), numerator, denominator)
        return None if a is None or b is None else a - b

    return statistic


def _shared(cells: _Cells, *conditions: str) -> List[Pair]:
    if not all(c in cells for c in conditions):
        return []
    common = set.intersection(*(set(cells[c]) for c in conditions))
    return sorted(common)


#: H3 verdict when every scenario's outcome is saturated on a measure (prereg §7).
UNINFORMATIVE = "uninformative (outcomes saturated)"
#: An outcome mean at or beyond these, in *both* conditions of a contrast, is
#: saturated: a floor or ceiling that makes the tactical gap zero by construction.
SATURATED_HIGH = 0.95
SATURATED_LOW = 0.05


def _unsaturated(
    cells: _Cells, pairs: Sequence[Pair], measure: str
) -> Tuple[List[Pair], List[str]]:
    """H3's pairs minus those from scenarios saturated on *measure*, and their names.

    Judged per scenario on the point means over its shared pairs, once — not inside
    the bootstrap — so the set of scenarios is fixed before the interval is drawn.
    """
    by_scenario: Dict[str, List[Pair]] = defaultdict(list)
    for pair in pairs:
        by_scenario[pair[0]].append(pair)
    kept: List[Pair] = []
    saturated: List[str] = []
    for scenario, group in sorted(by_scenario.items()):
        a = _mean([cells["C3"][p] for p in group], measure)
        b = _mean([cells["C1"][p] for p in group], measure)
        if (
            a is not None
            and b is not None
            and (min(a, b) >= SATURATED_HIGH or max(a, b) <= SATURATED_LOW)
        ):
            saturated.append(scenario)
        else:
            kept += group
    return kept, saturated


def _verdicts_for(model: str, cells: _Cells) -> List[Verdict]:
    out: List[Verdict] = []

    # H1 — each adjacent contrast in the predicted ordering, higher minus lower.
    for high, low in H1_CONTRASTS:
        pairs = _shared(cells, high, low)
        estimate = paired_bootstrap(
            pairs,
            _difference(cells, high, low, "first_attempt_valid", "fresh_decisions"),
        )
        note = (
            "also subject to the §7 C1 rule (primary, lenient and audited bounds)"
            if low == "C1"
            else ""
        )
        out.append(
            Verdict(
                model,
                "H1",
                f"{high} − {low}",
                len(pairs),
                estimate,
                _judge(estimate),
                note,
            )
        )

    # H1's full ordering: supported only if every adjacent contrast is (prereg §7).
    legs = out[-len(H1_CONTRASTS) :]
    if any(v.verdict == "insufficient data" for v in legs):
        ordering = "insufficient data"
    elif all(v.verdict == "supported" for v in legs):
        ordering = "supported"
    else:
        ordering = "not supported"
    out.append(
        Verdict(
            model,
            "H1",
            "full ordering",
            min(v.pairs for v in legs),
            None,
            ordering,
            "supported only if all three contrasts are; the C2 − C1 leg is also "
            "subject to the §7 C1 rule",
        )
    )

    # H2 — the deficit against the menu is larger on spatial decisions than on
    # non-spatial ones: (C3 − X)_spatial − (C3 − X)_non-spatial > 0.
    for condition in H2_CONDITIONS:
        pairs = _shared(cells, "C3", condition)
        spatial = _difference(
            cells, "C3", condition, "spatial_valid", "spatial_decisions"
        )
        other = _difference(
            cells, "C3", condition, "nonspatial_valid", "nonspatial_decisions"
        )

        def h2(
            sample: Sequence[Pair], spatial: Any = spatial, other: Any = other
        ) -> Optional[float]:
            a, b = spatial(sample), other(sample)
            return None if a is None or b is None else a - b

        estimate = paired_bootstrap(pairs, h2)
        out.append(
            Verdict(
                model,
                "H2",
                condition,
                len(pairs),
                estimate,
                _judge(estimate),
                "spatial deficit vs C3 minus non-spatial deficit vs C3",
            )
        )

    # H3 — the C3 − C1 validity gap exceeds the tactical gap, on both registered
    # tactical measures (percentage points). The tactical gap is taken in absolute
    # value, so a constraint that made play *worse* cannot count in H3's favour. A
    # scenario whose outcome is saturated in both conditions is left out of that
    # measure: its tactical gap is zero by construction, not by evidence.
    pairs = _shared(cells, "C3", "C1")
    validity = _difference(cells, "C3", "C1", "first_attempt_valid", "fresh_decisions")
    judged: List[str] = []
    estimates: List[Optional[Estimate]] = []
    notes: List[str] = []
    for measure, label in (("model_won", "win rate"), ("model_hp_fraction", "HP")):

        def h3(sample: Sequence[Pair], measure: str = measure) -> Optional[float]:
            gap = validity(sample)
            a = _mean([cells["C3"][p] for p in sample], measure)
            b = _mean([cells["C1"][p] for p in sample], measure)
            if gap is None or a is None or b is None:
                return None
            return gap - abs(a - b)

        informative, saturated = _unsaturated(cells, pairs, measure)
        if saturated:
            notes.append(f"{label} saturated in: {', '.join(saturated)}")
        if pairs and not informative:
            estimates.append(None)
            judged.append(UNINFORMATIVE)
            continue
        estimate = paired_bootstrap(informative, h3)
        estimates.append(estimate)
        judged.append(_judge(estimate))
    if "insufficient data" in judged:
        overall = "insufficient data"
    elif "not supported" in judged:
        overall = "not supported"
    elif UNINFORMATIVE in judged:
        overall = UNINFORMATIVE
    else:
        overall = "supported"
    out.append(
        Verdict(
            model,
            "H3",
            "C3 − C1",
            len(pairs),
            estimates[0],
            overall,
            "validity gap minus abs(win-rate gap); HP-fraction variant: "
            + _fmt_ci(estimates[1])
            + f" ({judged[1]})"
            + "".join(f"; {n}" for n in notes),
        )
    )
    return out


def registered_verdicts(matches: Sequence["Match"]) -> List[Verdict]:
    """Every registered contrast (H1–H3), per model, in a stable order.

    Paired: a contrast uses only the (scenario, seed) pairs present in both of its
    conditions, so a seed missing from one side drops out of that contrast rather
    than skewing it. Directional: *supported* means the 95% interval lies entirely
    above zero; anything else is *not supported*; no shared pairs is *insufficient
    data*. The C1 comparison is additionally gated by the §7 C1 rule, reported
    separately.
    """
    by_model: Dict[str, _Cells] = defaultdict(lambda: defaultdict(dict))
    for m in matches:
        by_model[m.model][m.condition][(m.scenario, m.seed)] = m
    verdicts: List[Verdict] = []
    for model in sorted(by_model):
        cells = by_model[model]
        if sum(c in cells for c in ("C1", "C2", "C2+M", "C3")) < 2:
            continue  # a baseline plays one condition, so it has nothing to contrast
        verdicts += _verdicts_for(model, cells)
    return verdicts


def _verdicts_section(verdicts: List[Verdict]) -> List[str]:
    if not verdicts:
        return []
    return [
        "",
        "## Registered verdicts (prereg §7)",
        "",
        "Paired cluster bootstrap over shared (scenario, seed) pairs, per model. "
        "*Supported* means the 95% interval of the contrast lies entirely above zero.",
        "",
        _table(
            ["model", "hypothesis", "contrast", "pairs", "estimate", "verdict", "note"],
            [
                [
                    v.model,
                    v.hypothesis,
                    v.contrast,
                    str(v.pairs),
                    _fmt_ci(v.estimate),
                    v.verdict,
                    v.note or "—",
                ]
                for v in verdicts
            ],
        ),
    ]


def _cost_row(
    key: Tuple[str, str], group: List[Match], decisions: List[Decision]
) -> List[str]:
    accepted = sum(m.accepted for m in group)
    costs = [m.cost_usd for m in group]
    menus = [d.menu_length for d in decisions if d.menu_length is not None]
    per = (lambda total: total / accepted) if accepted else (lambda total: None)
    return [
        key[0],
        key[1],
        _fmt(per(sum(m.input_tokens for m in group)), 1),
        _fmt(per(sum(m.output_tokens for m in group)), 1),
        (
            _fmt(per(sum(c for c in costs if c is not None)), 6)
            if costs and all(c is not None for c in costs)
            else "—"
        ),
        _fmt(sum(menus) / len(menus), 1) if menus else "—",
    ]


def _tactics_sections(matches: List[Match]) -> List[str]:
    """One table per scenario: its scoped metrics differ, so they are not mixed."""
    parts: List[str] = []
    by_scenario: Dict[str, List[Match]] = defaultdict(list)
    for m in matches:
        by_scenario[m.scenario].append(m)
    for scenario in sorted(by_scenario):
        names = sorted({k for m in by_scenario[scenario] for k in m.tactics})
        if not names:
            continue
        groups: Dict[Tuple[str, str], List[Match]] = defaultdict(list)
        for m in sorted(by_scenario[scenario], key=_cell_key):
            groups[(m.model, m.condition)].append(m)
        parts += [
            "",
            f"## Tactics — {scenario}",
            "",
            _table(
                ["model", "condition", *names],
                [
                    [
                        model,
                        condition,
                        *[
                            _fmt_ci(
                                bootstrap_mean(
                                    [m.tactics[n] for m in group if n in m.tactics]
                                )
                            )
                            for n in names
                        ],
                    ]
                    for (model, condition), group in groups.items()
                ],
            ),
        ]
    return parts


def _hosts_section(decisions: List[Decision]) -> List[str]:
    """Which upstream hosts served each model x condition — and a flag if several did.

    OpenRouter can route one model id to different hosts, which may differ in
    quantisation; a cell served by more than one is a validity problem to report,
    not to average over (prereg §5).
    """
    hosts: Dict[Tuple[str, str], set] = defaultdict(set)
    for d in decisions:
        if d.served_provider:
            hosts[(d.model, d.condition)].add(d.served_provider)
    if not hosts:
        return []
    mixed = {key for key, names in hosts.items() if len(names) > 1}
    parts = ["", "## Serving hosts", ""]
    if mixed:
        parts += [
            "**Warning: served by more than one host** — "
            + ", ".join(f"{m} / {c}" for m, c in sorted(mixed))
            + ". Pin `hosts` in the grid, or report these cells separately.",
            "",
        ]
    parts.append(
        _table(
            ["model", "condition", "hosts"],
            [
                [model, condition, ", ".join(sorted(names))]
                for (model, condition), names in sorted(
                    hosts.items(), key=lambda kv: (kv[0][0], _cell_key_of(kv[0][1]))
                )
            ],
        )
    )
    return parts


def _integrity_section(decisions: List[Decision]) -> List[str]:
    """Silent ways a cell can be biased, counted per model x condition.

    * a response cut off at the token limit — a harness setting deciding the outcome;
    * a menu cut by a length cap — real options removed (should never happen);
    * a response holding several tool calls — a host ignoring
      ``parallel_tool_calls``; refused when they differ (prereg §6), counted always;
    * a served model other than the one requested — a router changing the subject;
    * a decision the provider never billed — its cost is unknown, and the runner's
      spend cap reads it as free, so the $ figures for that cell are a floor only.
    """
    cells: Dict[Cell, List[Decision]] = defaultdict(list)
    for d in decisions:
        cells[(d.model, d.condition)].append(d)
    if not cells:
        return []
    keys = sorted(cells, key=lambda k: (k[0], _CONDITION_ORDER.get(k[1], 99)))
    substituted = sorted(
        key
        for key in keys
        # The mock's served id is a declared sentinel, not a router's substitution.
        if any(d.served_model not in (None, key[0], MOCK_MODEL) for d in cells[key])
    )
    cut = sorted(
        key
        for key in keys
        if any(d.length_cutoffs or d.menu_truncated for d in cells[key])
    )
    unbilled = sorted(
        key for key in keys if any(d.usage_reported is False for d in cells[key])
    )
    parts = ["", "## Response integrity", ""]
    if unbilled:
        parts += [
            "**Warning: unreported token usage** — the provider billed no tokens for "
            "some decisions in " + ", ".join(f"{m} / {c}" for m, c in unbilled) + ". "
            "Their cost is unknown, not zero: the $ figures for those cells are a "
            "floor, and the runner's spend cap could not be enforced over them.",
            "",
        ]
    if substituted:
        parts += [
            "**Warning: served a model other than the one requested** — "
            + ", ".join(f"{m} / {c}" for m, c in substituted)
            + ". Check the served ids before pooling these cells.",
            "",
        ]
    if cut:
        parts += [
            "**Warning: truncation** — a response cut at the token limit or a menu cut "
            "by its cap in " + ", ".join(f"{m} / {c}" for m, c in cut) + ".",
            "",
        ]
    parts.append(
        _table(
            [
                "model",
                "condition",
                "responses cut at token limit",
                "menus truncated",
                "responses with several calls",
                "decisions with unreported usage",
                "served models",
            ],
            [
                [
                    model,
                    condition,
                    str(sum(d.length_cutoffs for d in cells[(model, condition)])),
                    str(sum(bool(d.menu_truncated) for d in cells[(model, condition)])),
                    str(sum(d.multi_call_responses for d in cells[(model, condition)])),
                    str(
                        sum(
                            d.usage_reported is False for d in cells[(model, condition)]
                        )
                    ),
                    ", ".join(
                        sorted(
                            {
                                d.served_model
                                for d in cells[(model, condition)]
                                if d.served_model
                            }
                        )
                    )
                    or "—",
                ]
                for model, condition in keys
            ],
        )
    )
    return parts


def _cell_key_of(condition: str) -> int:
    return _CONDITION_ORDER.get(condition, 99)


def _layer_section(decisions: List[Decision]) -> List[str]:
    """How C1's accepted actions were read: the parse layer each needed.

    The layer describes the **command**: 0 canonical, 1 surface-identical (case,
    markdown, quotes), 2 grammatical but not canonical, 3 read out of an untagged
    line. Whether the model wrote anything *besides* the command is the separate
    ``with prose`` column — the two were folded together until 2026-09-25, which made
    layer 0 unreachable for real output and the registered strict bound uninformative
    (prereg §7).
    """
    c1 = [d for d in decisions if d.condition == "C1"]
    if not c1:
        return []
    by_model: Dict[str, Counter] = defaultdict(Counter)
    for d in c1:
        label = f"layer {d.c1_layer}" if d.c1_layer is not None else "refused / none"
        by_model[d.model][label] += 1
        if d.c1_prose:
            by_model[d.model]["with prose"] += 1
    labels = ["layer 0", "layer 1", "layer 2", "layer 3", "refused / none"]
    return [
        "",
        "## C1 parse layers",
        "",
        "The layer describes the command that was read: 0 canonical, 1 identical "
        "after surface normalisation, 2 grammatical but not canonical, 3 read out of "
        "an untagged line. *With prose* counts accepted actions whose response also "
        "said something else; it is not a layer, and does not affect one.",
        "",
        _table(
            ["model", *labels, "with prose"],
            [
                [
                    model,
                    *[str(counts[label]) for label in labels],
                    str(counts["with prose"]),
                ]
                for model, counts in sorted(by_model.items())
            ],
        ),
    ]


# -- writing ----------------------------------------------------------------------


def _csv(rows: List[Dict[str, Any]]) -> str:
    columns: List[str] = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({k: ("" if v is None else v) for k, v in row.items()})
    return buffer.getvalue()


def _match_row(match: Match) -> Dict[str, Any]:
    row = asdict(match)
    tactics = row.pop("tactics")
    row.update({f"tactic:{k}": v for k, v in sorted(tactics.items())})
    return row


@dataclass
class _Bounds:
    """One C1 match's first attempts under the three parsers (prereg §7)."""

    model: str
    match: str
    decisions: List[Bounded]


def _bounds_of(
    relative: Path, records: List[Dict[str, Any]], problems: List[str]
) -> Optional[_Bounds]:
    start = next(r for r in records if r["kind"] == "match_start")
    scenario = SCENARIOS.get(str(start.get("scenario")))
    if start.get("condition") != "C1" or scenario is None:
        return None
    try:
        bounded = rescore(records, scenario.build)
    except RescoreError as exc:
        problems.append(f"{relative.as_posix()}: {exc}")
        return None
    return _Bounds(str(start.get("model", "?")), relative.as_posix(), bounded)


def _bounds_section(bounds: List[_Bounds], problems: List[str]) -> List[str]:
    if not bounds and not problems:
        return []
    by_model: Dict[str, List[_Bounds]] = defaultdict(list)
    for b in bounds:
        by_model[b.model].append(b)

    def rate(group: List[_Bounds], which: str) -> str:
        return _fmt_ci(
            cluster_ratio(
                [
                    (sum(getattr(d, which) for d in b.decisions), len(b.decisions))
                    for b in group
                ]
            )
        )

    parts = [
        "",
        "## C1 under three parsers (prereg §7)",
        "",
        "First-attempt validity over fresh decisions, as in H1, re-scored offline "
        "from the recorded text. *Strict* "
        "accepts only a canonical command (layer 0), whether or not the response also "
        "wrote prose; *lenient* adds every registered repair, judged "
        "by the executor in the state the game was in. Later attempts and tactics "
        "depend on the live parser and are not re-scored.",
        "",
        _table(
            ["model", "matches", "strict", "primary (live)", "lenient"],
            [
                [
                    model,
                    str(len(group)),
                    rate(group, "strict"),
                    rate(group, "primary"),
                    rate(group, "lenient"),
                ]
                for model, group in sorted(by_model.items())
            ],
        ),
    ]
    if problems:
        parts += ["", "**Not re-scored** (the match did not replay):", ""]
        parts += [f"- {p}" for p in problems]
    return parts


def build_report(bundle: Path) -> Tuple[str, str, str, str]:
    """(decisions.csv, matches.csv, c1_bounds.csv, summary.md) for *bundle*.

    Pure and deterministic: the same bundle always gives byte-identical output.
    """
    prices = _prices(bundle)
    decisions: List[Decision] = []
    matches: List[Match] = []
    bounds: List[_Bounds] = []
    problems: List[str] = []
    for path, records in completed_transcripts(bundle):
        relative = path.relative_to(bundle)
        mine = decisions_of(relative, records)
        decisions += mine
        matches.append(match_of(relative, records, mine, prices))
        bounded = _bounds_of(relative, records, problems)
        if bounded is not None:
            # The bounds re-score first attempts, so like H1 they are over fresh
            # decisions only; a retry after a refusal is recovery (prereg §6).
            fresh = {d.index for d in mine if d.fresh}
            bounded.decisions = [b for b in bounded.decisions if b.index in fresh]
            bounds.append(bounded)
    summary = summarise(
        bundle.name,
        decisions,
        matches,
        excluded_attempts(bundle),
        excluded_by_cell(bundle),
        exclusion_reasons(bundle),
    )
    summary = summary.rstrip("\n") + "\n" + "\n".join(_bounds_section(bounds, problems))
    bound_rows = [
        {"model": b.model, "match": b.match, **asdict(d)}
        for b in bounds
        for d in b.decisions
    ]
    return (
        _csv([asdict(d) for d in decisions]),
        _csv([_match_row(m) for m in matches]),
        _csv(bound_rows),
        summary.rstrip("\n") + "\n",
    )


def write_report(bundle: Path) -> List[Path]:
    """Write the report files under ``<bundle>/report/`` and return their paths."""
    decisions_csv, matches_csv, bounds_csv, summary = build_report(bundle)
    out = bundle / REPORT_DIR
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for filename, content in (
        ("decisions.csv", decisions_csv),
        ("matches.csv", matches_csv),
        ("c1_bounds.csv", bounds_csv),
        ("summary.md", summary),
    ):
        path = out / filename
        path.write_text(content, encoding="utf-8", newline="\n")
        written.append(path)
    return written


# -- reading one match, decision by decision ---------------------------------------


def _clip(text: str, limit: int = 400) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def describe(records: List[Dict[str, Any]], *, refused_only: bool = False) -> str:
    """Each model decision as the model wrote it, how it was read, and the verdict.

    For reviewing real output — C1 phrasings the parser refused (ledger A8), the
    reasons refusals gave, what a correction re-prompt rescued. Reads the transcript
    only; nothing is re-run.
    """
    start = next(r for r in records if r["kind"] == "match_start")
    team = model_team(start, records)
    members = set(start.get("teams", {}).get(team, []))
    lines = [
        f"{start.get('model', '?')} | {start.get('condition', '?')} | "
        f"{start.get('scenario', '?')} | seed {start.get('seed')} | "
        f"opponent {start.get('opponent', '?')}",
        "",
    ]
    round_number, shown = 0, 0
    for record in records:
        if record["kind"] == "turn_start":
            round_number = record.get("round", round_number)
            continue
        if record["kind"] != "action" or record["actor_id"] not in members:
            continue
        result = record["result"]
        if refused_only and result.get("ok"):
            continue
        shown += 1
        telemetry = record.get("telemetry") or {}
        requests = telemetry.get("requests") or []
        verdict = "ok" if result.get("ok") else f"REFUSED {result.get('code', '')}"
        count = telemetry.get("request_count", 1)
        extra = f"  (after {count} requests)" if count > 1 else ""
        lines.append(f"[round {round_number}] {record['actor_id']}: {verdict}{extra}")
        if requests:
            first = requests[0]
            if first.get("raw_output"):
                lines.append(f"  wrote : {_clip(first['raw_output'])!r}")
            if first.get("tool_call"):
                lines.append(f"  called: {json.dumps(first['tool_call'])}")
            reading = first.get("interpretation")
            if reading:
                if "layer" in reading:
                    prose = " (with prose)" if reading.get("prose") else ""
                    lines.append(f"  read  : layer {reading['layer']}{prose}")
                else:
                    lines.append(f"  read  : refused — {reading.get('reason', '')}")
        call = record["call"]
        lines.append(
            f"  action: {call['name']} {json.dumps(call.get('arguments', {}))}"
        )
        if not result.get("ok"):
            lines.append(f"  reason: {result.get('error', '')}")
        lines.append("")
    if not shown:
        lines.append("(no model decisions to show)")
    return "\n".join(lines).rstrip() + "\n"
