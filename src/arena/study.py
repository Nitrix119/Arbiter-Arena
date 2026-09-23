"""The study grid runner: every cell, once, resumably, within a spend cap.

    python -m src.arena.study run GRID.toml --out results/<name> [--dry-run]
    python -m src.arena.study report results/<name>

A **cell** is one match: model × condition × scenario × seed. The runner plays each
through the ordinary :func:`~src.arena.match.run_match` — there is no second match path
— and writes its transcript to a fixed place, so a run is **resumable** (a cell whose
transcript exists is done) and the result bundle is self-describing (the grid is copied
beside it).

What it guards, in the order the pre-registration cares about:

* **Exclusion is for infrastructure only** (prereg §8). A cell is excluded — kept under
  ``_excluded/`` and re-run with backoff — when a provider or network error escapes the
  match, or its transcript records any ``provider_error``. Bad model behaviour is data,
  never a reason to exclude. Anything else that escapes is a bug and is raised, not
  retried: a retry loop must not hide a defect.
* **Spend** is recomputed from every transcript on disk at start, so a cap survives a
  resume, and the runner stops before a cell once the cap is reached.
* **Preflight** makes one tool-call and one text-only request per live model before any
  cell, so a dead model id or a model without tool calling fails the run in seconds
  rather than hours in (CODEBASE_REVIEW A1's note).
* **Cells run seed-major**, so an interrupted run leaves a balanced set of paired cells.

Every live model is routed through OpenRouter (prereg §5: mixed routing would be a
provider-path confound), so the providers are ``openrouter`` and ``mock`` — the latter a
:class:`~src.arena.mock_model.MockModelAgent`, which lets the whole grid run offline.
"""

import argparse
import json
import os
import re
import shutil
import sys
import time
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence, Tuple

from src.arena.agent import Agent, ScriptedAgent
from src.arena.error_codes import PROVIDER_ERROR
from src.arena.interfaces import C1, C2, REGISTRY, ActionInterface, get_interface
from src.arena.manifest import Manifest, git_dirty, interface_fingerprint
from src.arena.match import DEFAULT_ROUND_CAP, run_match
from src.arena.scenarios import SCENARIOS
from src.arena.transcript import Transcript
from src.combat.combat_system import CombatSystem

PROVIDER_OPENROUTER = "openrouter"
PROVIDER_MOCK = "mock"
PROVIDERS = (PROVIDER_OPENROUTER, PROVIDER_MOCK)

OPPONENT_SCRIPTED = "scripted"
OPPONENT_HEURISTIC = "heuristic"
OPPONENTS = (OPPONENT_SCRIPTED, OPPONENT_HEURISTIC)

#: Where excluded attempts are kept, beside the completed cells.
EXCLUDED_DIR = "_excluded"
RUN_LOG = "run_log.jsonl"
GRID_COPY = "grid.toml"

#: Rough calls per match, for ``--dry-run`` estimates only (2026-09-15 diagnostic).
CALLS_PER_MATCH_ESTIMATE = 35

#: SDK packages whose exceptions are infrastructure, not model behaviour or our bugs.
_INFRA_MODULES = ("openai", "anthropic", "httpx", "httpcore")


class GridError(ValueError):
    """A grid file that cannot be run, naming the bad value and the valid options."""


# -- the grid ----------------------------------------------------------------------


@dataclass(frozen=True)
class ModelSpec:
    """One model in the grid, and what its tokens cost."""

    id: str
    provider: str
    temperature: float = 0.0
    usd_per_m_input: float = 0.0
    usd_per_m_output: float = 0.0
    #: Mock only: decision indices at which the mock answers malformed, so an offline
    #: grid exercises the refusal paths and the report's taxonomy.
    stumble_on: Tuple[int, ...] = ()
    #: OpenRouter only: the upstream hosts allowed to serve this model, in order, with
    #: fallbacks off. One model id can otherwise be served by different hosts (and
    #: quantisations) from cell to cell — an uncontrolled variable.
    hosts: Tuple[str, ...] = ()

    def cost_usd(self, input_tokens: int, output_tokens: int) -> float:
        return (
            input_tokens * self.usd_per_m_input + output_tokens * self.usd_per_m_output
        ) / 1_000_000


@dataclass(frozen=True)
class Grid:
    """A parsed, validated study grid."""

    name: str
    seeds: Tuple[int, ...]
    scenarios: Tuple[str, ...]
    conditions: Tuple[str, ...]
    models: Tuple[ModelSpec, ...]
    opponent: str = OPPONENT_SCRIPTED
    round_cap: int = DEFAULT_ROUND_CAP
    spend_cap_usd: float = 0.0
    max_attempts: int = 3
    backoff_seconds: float = 30.0

    def model(self, model_id: str) -> Optional[ModelSpec]:
        return next((m for m in self.models if m.id == model_id), None)


def _choices(value: Any, valid: Sequence[str], what: str) -> Tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise GridError(f"{what} must be a non-empty list; got {value!r}")
    for item in value:
        if item not in valid:
            raise GridError(
                f"Unknown {what[:-1]} {item!r}; expected one of {sorted(valid)}"
            )
    return tuple(value)


def _number(table: Dict[str, Any], key: str, default: float, what: str) -> float:
    value = table.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise GridError(f"{what}.{key} must be a non-negative number; got {value!r}")
    return float(value)


def parse_grid(data: Dict[str, Any]) -> Grid:
    """Validate a grid's TOML tables into a :class:`Grid`, refusing anything unclear."""
    study = data.get("study")
    if not isinstance(study, dict):
        raise GridError("The grid needs a [study] table")
    unknown = set(study) - {
        "name",
        "seeds",
        "scenarios",
        "conditions",
        "opponent",
        "round_cap",
        "spend_cap_usd",
        "max_attempts",
        "backoff_seconds",
    }
    if unknown:
        raise GridError(f"Unknown [study] key(s) {sorted(unknown)}")

    seeds = study.get("seeds")
    if (
        not isinstance(seeds, list)
        or not seeds
        or not all(isinstance(s, int) and not isinstance(s, bool) for s in seeds)
    ):
        raise GridError(
            f"study.seeds must be a non-empty list of integers; got {seeds!r}"
        )
    if len(set(seeds)) != len(seeds):
        raise GridError(f"study.seeds repeats a seed: {seeds}")

    opponent = study.get("opponent", OPPONENT_SCRIPTED)
    if opponent not in OPPONENTS:
        raise GridError(f"Unknown opponent {opponent!r}; expected one of {OPPONENTS}")

    models_data = data.get("models")
    if not isinstance(models_data, list) or not models_data:
        raise GridError("The grid needs at least one [[models]] entry")
    models: List[ModelSpec] = []
    for index, entry in enumerate(models_data):
        what = f"models[{index}]"
        provider = entry.get("provider")
        if provider not in PROVIDERS:
            raise GridError(
                f"{what}: unknown provider {provider!r}; expected one of {PROVIDERS} "
                "(every live model is routed through OpenRouter — prereg §5)"
            )
        model_id = entry.get("id")
        if not isinstance(model_id, str) or not model_id:
            raise GridError(f"{what}: id must be a non-empty string")
        if provider != PROVIDER_MOCK and not (
            "usd_per_m_input" in entry and "usd_per_m_output" in entry
        ):
            raise GridError(
                f"{what} ({model_id}): usd_per_m_input and usd_per_m_output are "
                "required for a live model — the spend cap is computed from them"
            )
        stumble_on = entry.get("stumble_on", [])
        if stumble_on and provider != PROVIDER_MOCK:
            raise GridError(f"{what} ({model_id}): stumble_on is for the mock only")
        if not isinstance(stumble_on, list) or not all(
            isinstance(i, int) and not isinstance(i, bool) and i >= 0
            for i in stumble_on
        ):
            raise GridError(f"{what}: stumble_on must be a list of decision indices")
        hosts = entry.get("hosts", [])
        if hosts and provider != PROVIDER_OPENROUTER:
            raise GridError(f"{what} ({model_id}): hosts is for OpenRouter models only")
        if not isinstance(hosts, list) or not all(
            isinstance(h, str) and h for h in hosts
        ):
            raise GridError(f"{what}: hosts must be a list of provider names")
        models.append(
            ModelSpec(
                id=model_id,
                provider=provider,
                temperature=_number(entry, "temperature", 0.0, what),
                usd_per_m_input=_number(entry, "usd_per_m_input", 0.0, what),
                usd_per_m_output=_number(entry, "usd_per_m_output", 0.0, what),
                stumble_on=tuple(stumble_on),
                hosts=tuple(hosts),
            )
        )
    if len({m.id for m in models}) != len(models):
        raise GridError("Two [[models]] entries share an id")

    round_cap = study.get("round_cap", DEFAULT_ROUND_CAP)
    max_attempts = study.get("max_attempts", 3)
    for key, value in (("round_cap", round_cap), ("max_attempts", max_attempts)):
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise GridError(f"study.{key} must be a positive integer; got {value!r}")

    spend_cap = _number(study, "spend_cap_usd", 0.0, "study")
    if spend_cap == 0.0 and any(m.provider != PROVIDER_MOCK for m in models):
        raise GridError("study.spend_cap_usd is required (> 0) when any model is live")

    return Grid(
        name=str(study.get("name", "study")),
        seeds=tuple(seeds),
        scenarios=_choices(study.get("scenarios"), list(SCENARIOS), "scenarios"),
        conditions=_choices(study.get("conditions"), list(REGISTRY), "conditions"),
        models=tuple(models),
        opponent=opponent,
        round_cap=round_cap,
        spend_cap_usd=spend_cap,
        max_attempts=max_attempts,
        backoff_seconds=_number(study, "backoff_seconds", 30.0, "study"),
    )


def load_grid(path: Path) -> Grid:
    with open(path, "rb") as handle:
        try:
            data = tomllib.load(handle)
        except tomllib.TOMLDecodeError as exc:
            raise GridError(f"{path}: not valid TOML ({exc})") from None
    return parse_grid(data)


# -- cells ------------------------------------------------------------------------


def _slug(text: str) -> str:
    """A filesystem-safe token: ``C2+M`` → ``C2M``, ``org/m:free`` → ``org-m-free``."""
    return re.sub(r"[^A-Za-z0-9._-]+", "-", text.replace("+", "")).strip("-")


@dataclass(frozen=True)
class Cell:
    """One match in the grid."""

    model: ModelSpec
    condition: str
    scenario: str
    seed: int

    def path(self, out: Path) -> Path:
        return (
            out
            / _slug(self.model.id)
            / _slug(self.condition)
            / self.scenario
            / f"seed{self.seed}.jsonl"
        )

    def label(self) -> str:
        return (
            f"{self.model.id} | {self.condition} | {self.scenario} | seed {self.seed}"
        )


def cells(grid: Grid) -> Iterator[Cell]:
    """Every cell, **seed-major**: a run stopped part-way leaves whole paired seeds."""
    for seed in grid.seeds:
        for scenario in grid.scenarios:
            for condition in grid.conditions:
                for model in grid.models:
                    yield Cell(model, condition, scenario, seed)


# -- agents -----------------------------------------------------------------------


@dataclass(frozen=True)
class Seat:
    """Everything a factory needs to seat a model at a match."""

    spec: ModelSpec
    name: str
    team: Optional[str]
    interface: ActionInterface
    combat: Optional[CombatSystem] = None
    seed: Optional[int] = None


#: provider → builds the model's agent. Registry, not a branch on the name.
ModelFactory = Callable[[Seat], Agent]


def _openrouter_agent(seat: Seat) -> Agent:
    from src.arena.openrouter_agent import OpenRouterAgent

    return OpenRouterAgent(
        seat.name,
        seat.team,
        model=seat.spec.id,
        temperature=seat.spec.temperature,
        interface=seat.interface,
        hosts=seat.spec.hosts,
        seed=seat.seed,
    )


def _mock_agent(seat: Seat) -> Agent:
    from src.arena.mock_model import MockModelAgent

    return MockModelAgent(
        seat.name, seat.team, seat.interface, stumble_on=seat.spec.stumble_on
    )


MODEL_FACTORIES: Dict[str, ModelFactory] = {
    PROVIDER_OPENROUTER: _openrouter_agent,
    PROVIDER_MOCK: _mock_agent,
}


def _opponent(kind: str, combat: CombatSystem, team: Optional[str]) -> Agent:
    if kind == OPPONENT_HEURISTIC:
        from src.arena.heuristic.agent import HeuristicAgent

        return HeuristicAgent("opponent", team, combat)
    return ScriptedAgent("opponent", team)


# -- running one cell -------------------------------------------------------------


def is_infrastructure_error(exc: BaseException) -> bool:
    """True for a provider, network or timeout failure — never for our own bug."""
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return True
    return type(exc).__module__.split(".")[0] in _INFRA_MODULES


def provider_errors(records: Sequence[Dict[str, Any]]) -> int:
    """How many actions in a transcript were infrastructure failures."""
    return sum(
        1
        for r in records
        if r.get("kind") == "action" and r["result"].get("code") == PROVIDER_ERROR
    )


def transcript_tokens(records: Sequence[Dict[str, Any]]) -> Tuple[int, int]:
    """(input, output) tokens a transcript's decisions reported spending."""
    tokens_in = tokens_out = 0
    for r in records:
        telemetry = r.get("telemetry") if r.get("kind") == "action" else None
        if telemetry:
            tokens_in += telemetry.get("input_tokens") or 0
            tokens_out += telemetry.get("output_tokens") or 0
    return tokens_in, tokens_out


@dataclass
class CellResult:
    """What became of one attempt at a cell."""

    records: List[Dict[str, Any]]
    excluded_reason: Optional[str] = None


def play_cell(
    cell: Cell,
    grid: Grid,
    *,
    factories: Dict[str, ModelFactory] = MODEL_FACTORIES,
) -> CellResult:
    """Play one cell once. Infrastructure failure → excluded; anything else raises."""
    scenario = SCENARIOS[cell.scenario]
    interface = get_interface(cell.condition)
    combat = scenario.build()
    model_team = scenario.llm_team
    agents: Dict[Optional[str], Agent] = {
        model_team: factories[cell.model.provider](
            Seat(
                cell.model,
                f"{cell.model.id} [{cell.condition}]",
                model_team,
                interface,
                combat=combat,
                seed=cell.seed,
            )
        ),
        scenario.heuristic_team: _opponent(
            grid.opponent, combat, scenario.heuristic_team
        ),
    }
    manifest = Manifest.for_run(
        scenario=cell.scenario,
        seed=cell.seed,
        condition=cell.condition,
        model=cell.model.id,
        temperature=cell.model.temperature,
        prompt_hash=interface_fingerprint(interface),
        opponent=grid.opponent,
    )
    transcript = Transcript()
    try:
        run_match(
            combat,
            agents,
            seed=cell.seed,
            round_cap=grid.round_cap,
            transcript=transcript,
            manifest=manifest,
        )
    except Exception as exc:
        if not is_infrastructure_error(exc):
            raise  # a bug, not the weather: never retried, never hidden
        return CellResult(transcript.records, f"{type(exc).__name__}: {exc}")

    failures = provider_errors(transcript.records)
    if failures:
        return CellResult(transcript.records, f"{failures} provider_error action(s)")
    return CellResult(transcript.records)


def _write_atomically(path: Path, records: Sequence[Dict[str, Any]]) -> None:
    """Write a transcript so a crash can never leave a half-file that looks complete."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(
        "".join(json.dumps(r, default=str) + "\n" for r in records), encoding="utf-8"
    )
    os.replace(temporary, path)


def _read(path: Path) -> List[Dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


# -- spend ------------------------------------------------------------------------


def spent_usd(out: Path, grid: Grid) -> float:
    """Everything the bundle on disk has cost — completed and excluded alike.

    Recomputed from the transcripts rather than kept in a counter, so a resumed run
    starts from the true figure and a cap cannot be reset by restarting.
    """
    total = 0.0
    for path in out.rglob("*.jsonl"):
        if path.name == RUN_LOG:
            continue
        records = _read(path)
        start = next((r for r in records if r.get("kind") == "match_start"), {})
        spec = grid.model(start.get("model", ""))
        if spec is not None:
            total += spec.cost_usd(*transcript_tokens(records))
    return total


# -- preflight --------------------------------------------------------------------

_PREFLIGHT_PROMPT = [{"role": "user", "content": "Preflight check. End your turn."}]


def preflight(
    grid: Grid,
    factories: Dict[str, ModelFactory] = MODEL_FACTORIES,
    echo: Callable[[str], None] = print,
) -> List[str]:
    """One tool-call and one text-only request per live model. Returns the problems.

    The tool-call check uses C2's tools; the text check uses C1's (none). A model that
    cannot answer either cannot fill its row of the grid, and finding that out before
    the first cell costs a few hundred tokens instead of a day.
    """
    problems: List[str] = []
    for spec in grid.models:
        if spec.provider == PROVIDER_MOCK:
            continue
        for condition, needs_call in ((C2, True), (C1, False)):
            interface = get_interface(condition)
            agent = factories[spec.provider](Seat(spec, "preflight", "a", interface))
            tools = interface.api_tools({})
            try:
                call, record = agent._request_action(  # type: ignore[attr-defined]
                    list(_PREFLIGHT_PROMPT), tools
                )
            except Exception as exc:
                problems.append(f"{spec.id}: {condition} preflight failed: {exc}")
                continue
            if needs_call and call is None:
                problems.append(
                    f"{spec.id}: returned no tool call — C2, C2+M and C3 need tool "
                    "calling"
                )
            if not needs_call and not (record.raw_output or "").strip():
                problems.append(f"{spec.id}: returned no text for the C1 check")
            echo(
                f"preflight {spec.id} [{condition}]: served by "
                f"{record.served_provider or 'an unreported host'}"
            )
    return problems


# -- the run ----------------------------------------------------------------------


class _Log:
    def __init__(self, path: Path) -> None:
        self._path = path

    def __call__(self, event: str, **fields: Any) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps({"event": event, "time": time.time(), **fields}))
            handle.write("\n")


@dataclass
class RunSummary:
    """What a run did."""

    done: int = 0
    skipped: int = 0
    excluded_attempts: int = 0
    failed: List[str] = field(default_factory=list)
    stopped: Optional[str] = None


def run_grid(
    grid: Grid,
    out: Path,
    *,
    grid_path: Optional[Path] = None,
    factories: Dict[str, ModelFactory] = MODEL_FACTORIES,
    sleep: Callable[[float], None] = time.sleep,
    echo: Callable[[str], None] = print,
    allow_dirty: bool = False,
) -> RunSummary:
    """Run every cell not already on disk. Resumable; stops at the spend cap.

    Refuses to start a **live** run from a tree with uncommitted changes (unless
    *allow_dirty*): the manifest's commit would then name code that did not run.
    Stops at the first cell that exhausts its retries — a quota or an outage would
    otherwise fail, and bill, every remaining cell in turn.
    """
    live = any(m.provider != PROVIDER_MOCK for m in grid.models)
    if live and not allow_dirty and git_dirty():
        reason = (
            "the working tree has uncommitted changes, so the recorded commit would "
            "not name the code that ran — commit first, or pass --allow-dirty"
        )
        echo(reason)
        return RunSummary(stopped=reason)
    out.mkdir(parents=True, exist_ok=True)
    if grid_path is not None:
        shutil.copyfile(grid_path, out / GRID_COPY)
    log = _Log(out / RUN_LOG)
    summary = RunSummary()
    spend = spent_usd(out, grid)
    log("run_start", grid=grid.name, spent_usd=spend)

    for cell in cells(grid):
        path = cell.path(out)
        if path.exists():
            summary.skipped += 1
            log("cell_skip", cell=cell.label())
            continue
        if grid.spend_cap_usd and spend >= grid.spend_cap_usd:
            summary.stopped = (
                f"spend cap reached: ${spend:.4f} of ${grid.spend_cap_usd:.2f}"
            )
            log("stop", reason=summary.stopped)
            echo(summary.stopped)
            break

        for attempt in range(1, grid.max_attempts + 1):
            result = play_cell(cell, grid, factories=factories)
            spend += cell.model.cost_usd(*transcript_tokens(result.records))
            if result.excluded_reason is None:
                _write_atomically(path, result.records)
                summary.done += 1
                log("cell_done", cell=cell.label(), spent_usd=spend)
                echo(f"done      {cell.label()}")
                break
            summary.excluded_attempts += 1
            relative = path.relative_to(out)
            excluded = (
                out / EXCLUDED_DIR / relative.with_suffix(f".attempt{attempt}.jsonl")
            )
            _write_atomically(excluded, result.records)
            log(
                "cell_excluded",
                cell=cell.label(),
                attempt=attempt,
                reason=result.excluded_reason,
            )
            echo(f"excluded  {cell.label()} ({result.excluded_reason})")
            if attempt < grid.max_attempts:
                sleep(grid.backoff_seconds * 2 ** (attempt - 1))
        else:
            summary.failed.append(cell.label())
            log("cell_failed", cell=cell.label())
            summary.stopped = (
                f"{cell.label()} failed all {grid.max_attempts} attempts — stopping "
                "(a quota or an outage?); resume to retry it first"
            )
            log("stop", reason=summary.stopped)
            echo(summary.stopped)
            break

    log("run_end", done=summary.done, skipped=summary.skipped, spent_usd=spend)
    return summary


# -- CLI --------------------------------------------------------------------------


def _dry_run(grid: Grid, out: Path) -> str:
    all_cells = list(cells(grid))
    existing = sum(1 for c in all_cells if c.path(out).exists())
    remaining = len(all_cells) - existing
    return (
        f"{grid.name}: {len(all_cells)} cells "
        f"({len(grid.models)} models x {len(grid.conditions)} conditions x "
        f"{len(grid.scenarios)} scenarios x {len(grid.seeds)} seeds); "
        f"{existing} already done, {remaining} to run "
        f"(~{remaining * CALLS_PER_MATCH_ESTIMATE} model calls)."
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.arena.study")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="run a study grid (resumable)")
    run.add_argument("grid", type=Path)
    run.add_argument("--out", type=Path, required=True)
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--skip-preflight", action="store_true")
    run.add_argument(
        "--allow-dirty",
        action="store_true",
        help="run live models from a tree with uncommitted changes (recorded)",
    )
    report = commands.add_parser("report", help="summarise a result bundle")
    report.add_argument("bundle", type=Path)
    args = parser.parse_args(argv)

    if args.command == "report":
        from src.arena.study_report import write_report

        for written in write_report(args.bundle):
            print(f"wrote {written}")
        return 0

    try:
        grid = load_grid(args.grid)
    except GridError as exc:
        print(f"grid error: {exc}", file=sys.stderr)
        return 2
    print(_dry_run(grid, args.out))
    if args.dry_run:
        return 0
    if not args.skip_preflight:
        problems = preflight(grid)
        if problems:
            for problem in problems:
                print(f"preflight: {problem}", file=sys.stderr)
            return 3
    summary = run_grid(
        grid, args.out, grid_path=args.grid, allow_dirty=args.allow_dirty
    )
    print(
        f"done {summary.done}, skipped {summary.skipped}, excluded attempts "
        f"{summary.excluded_attempts}, failed {len(summary.failed)}"
        + (f"; stopped: {summary.stopped}" if summary.stopped else "")
    )
    return 1 if summary.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
