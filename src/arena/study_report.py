"""Turn a study bundle into the pre-registered measurements.

    python -m src.arena.study report results/<name>

Reads every completed transcript under the bundle (``_excluded/`` is counted, never
analysed) and writes three files to ``<bundle>/report/``:

* ``decisions.csv`` — one row per **model decision**: what was attempted, whether it
  was accepted, whether it was valid *first time*, and what it cost.
* ``matches.csv`` — one row per match: outcome, validity, cost, tactical metrics.
* ``summary.md`` — the tables the hypotheses are judged on, per model x condition.

**Definitions, exactly as registered** (PREREGISTRATION §6–§7):

* *First-attempt valid*: the decision was accepted **and** took one request. A decision
  that needed the correction re-prompt failed its first attempt even if the second
  succeeded — the same rule in every condition (ledger A2).
* *Recovery*: after a rejected decision, the same actor's next decision in the same turn
  was accepted. Rejections with no later decision that turn are not counted.
* *Spatial* (H2): a move, or a spell aimed at a point. For a refused attempt, judged
  from what was attempted — a C1 line starting with a move verb or a cast giving
  coordinates; a C3 id naming a move or an aim point. A response with no action at all
  is neither.
* Rates are pooled over decisions; intervals are a **match-level (cluster) bootstrap**
  — decisions within a match are not independent — with a fixed seed, so the report
  is byte-identical every time it is run. Win rates use **Wilson** intervals.

Standard library only: no numpy, no pandas, no plots (ledger A11).
"""

import csv
import io
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from src.arena.free_text import UNREAD_TEXT
from src.arena.interfaces import REGISTRY
from src.arena.metrics import area_hits, compute_report
from src.arena.rescore import Bounded, RescoreError, rescore
from src.arena.scenarios import SCENARIOS, model_team
from src.utils import dice

REPORT_DIR = "report"
BOOTSTRAP_SEED = 20260924
BOOTSTRAP_RESAMPLES = 2000
CONFIDENCE = 0.95
_Z = 1.959963984540054  # two-sided 95% normal quantile, for Wilson

_EXCLUDED_DIR = "_excluded"
_NO_CALL = "(no_tool_call)"
_MOVE_VERBS = {"move", "go", "walk", "run", "step"}
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


def _attempted_verb(text: str) -> str:
    words = _FILLERS.sub("", text.strip()).split()
    return words[0].casefold() if words else ""


def classify(call: Dict[str, Any]) -> Tuple[str, Optional[bool]]:
    """(kind, spatial) for a recorded call — what was attempted, accepted or not."""
    name = call.get("name", "")
    args = call.get("arguments", {}) or {}
    if name == "move":
        return "move", True
    if name == "cast_spell":
        return (
            ("cast_point", True) if "target_point" in args else ("cast_target", False)
        )
    if name in ("attack", "end_turn"):
        return name, False
    if name == UNREAD_TEXT:
        text = str(args.get("text", ""))
        verb = _attempted_verb(text)
        spatial = verb in _MOVE_VERBS or (
            verb == "cast" and bool(_COORDINATES.search(text))
        )
        return "unread", spatial
    if name == "choose":
        action_id = str(args.get("action_id", ""))
        return "choose", action_id.startswith("move:") or ":aim:" in action_id
    if name == _NO_CALL:
        return "none", None
    return "unknown_tool", None


def decisions_of(path: Path, records: List[Dict[str, Any]]) -> List[Decision]:
    start = next(r for r in records if r["kind"] == "match_start")
    team = model_team(start, records)
    members = set(start.get("teams", {}).get(team, []))
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
        host = None
        if requests:
            reading = requests[-1].get("interpretation") or {}
            layer = reading.get("layer")
            host = requests[-1].get("served_provider")
        kind, spatial = classify(record["call"])
        ok = bool(record["result"].get("ok"))
        count = telemetry.get("request_count", 1)
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
                served_provider=host,
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
    first_attempt_valid: int
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
    spatial = [d for d in decisions if d.spatial is True]
    nonspatial = [d for d in decisions if d.spatial is False]
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
        first_attempt_valid=sum(d.first_attempt_valid for d in decisions),
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


def summarise(
    name: str,
    decisions: List[Decision],
    matches: List[Match],
    excluded: int,
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
                "first-attempt valid",
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
                    _fmt_ci(
                        cluster_ratio(
                            [(m.first_attempt_valid, m.decisions) for m in group]
                        )
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

    parts += _tactics_sections(matches)
    parts += _layer_section(decisions)
    parts += _hosts_section(decisions)
    return "\n".join(parts) + "\n"


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


def _cell_key_of(condition: str) -> int:
    return _CONDITION_ORDER.get(condition, 99)


def _layer_section(decisions: List[Decision]) -> List[str]:
    """How C1's accepted actions were read: the parse layer each needed."""
    c1 = [d for d in decisions if d.condition == "C1"]
    if not c1:
        return []
    by_model: Dict[str, Counter] = defaultdict(Counter)
    for d in c1:
        label = f"layer {d.c1_layer}" if d.c1_layer is not None else "refused / none"
        by_model[d.model][label] += 1
    labels = ["layer 0", "layer 1", "layer 2", "layer 3", "refused / none"]
    return [
        "",
        "## C1 parse layers",
        "",
        _table(
            ["model", *labels],
            [
                [model, *[str(counts[label]) for label in labels]]
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
        "First-attempt validity, re-scored offline from the recorded text. *Strict* "
        "accepts only canonical text; *lenient* adds every registered repair, judged "
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
            bounds.append(bounded)
    summary = summarise(bundle.name, decisions, matches, excluded_attempts(bundle))
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
                    lines.append(f"  read  : layer {reading['layer']}")
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
