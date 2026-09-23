"""The study runner: validation, ordering, resume, exclusion, spend — all offline.

No test here touches the network. Live providers are replaced by the mock model or by
fakes whose failures are shaped like the real SDKs' (an exception class whose module is
``openai``), which is exactly how the runner tells infrastructure from a bug.
"""

import json
from pathlib import Path

import pytest

from src.arena.agent import Agent, ProviderError
from src.arena.interfaces import C1, C2, C3
from src.arena.mock_model import MockModelAgent
from src.arena.study import (
    EXCLUDED_DIR,
    GRID_COPY,
    MODEL_FACTORIES,
    PROVIDER_MOCK,
    RUN_LOG,
    Cell,
    GridError,
    ModelSpec,
    cells,
    is_infrastructure_error,
    main,
    parse_grid,
    preflight,
    run_grid,
    spent_usd,
)
from src.arena.telemetry import RequestRecord
from src.arena.tools import ToolCall


def _grid(**study):
    base = {
        "name": "test",
        "seeds": [1],
        "scenarios": ["kiting"],
        "conditions": [C2],
        "backoff_seconds": 5,
    }
    base.update(study)
    models = base.pop("models", [{"id": "mock", "provider": "mock"}])
    return parse_grid({"study": base, "models": models})


class RateLimitError(Exception):
    """Shaped like the SDK's: its module says it came from the provider."""


RateLimitError.__module__ = "openai"


# -- validation ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "study, fragment",
    [
        ({"scenarios": ["arena_of_doom"]}, "kiting"),
        ({"conditions": ["C4"]}, r"C2\+M"),
        ({"seeds": [1, 1]}, "repeats"),
        ({"seeds": []}, "non-empty"),
        ({"opponent": "grandmaster"}, "heuristic"),
        ({"round_cap": 0}, "positive"),
        ({"typo_key": 1}, "typo_key"),
    ],
)
def test_a_bad_grid_names_the_problem(study, fragment):
    with pytest.raises(GridError, match=fragment):
        _grid(**study)


def test_a_live_model_needs_prices_and_a_spend_cap():
    live = {"id": "org/model", "provider": "openrouter"}
    with pytest.raises(GridError, match="usd_per_m_input"):
        _grid(models=[live])
    priced = {**live, "usd_per_m_input": 0.1, "usd_per_m_output": 0.4}
    with pytest.raises(GridError, match="spend_cap_usd"):
        _grid(models=[priced])
    assert _grid(models=[priced], spend_cap_usd=5.0).models[0].id == "org/model"


def test_stumbles_are_for_the_mock_only():
    live = {
        "id": "org/model",
        "provider": "openrouter",
        "usd_per_m_input": 0.1,
        "usd_per_m_output": 0.1,
        "stumble_on": [0],
    }
    with pytest.raises(GridError, match="mock only"):
        _grid(models=[live], spend_cap_usd=1.0)
    mock = _grid(models=[{"id": "mock", "provider": "mock", "stumble_on": [0, 3]}])
    assert mock.models[0].stumble_on == (0, 3)


def test_direct_anthropic_routing_is_refused():
    """Prereg §5: every live model goes through OpenRouter — no mixed routing."""
    with pytest.raises(GridError, match="OpenRouter"):
        _grid(models=[{"id": "claude", "provider": "anthropic"}])


# -- cells ---------------------------------------------------------------------------


def test_cells_run_seed_major():
    """An interrupted run must leave whole paired seeds, not half the conditions."""
    grid = _grid(
        seeds=[1, 2], conditions=[C1, C2], scenarios=["kiting", "alpha_strike"]
    )
    order = [(c.seed, c.scenario, c.condition) for c in cells(grid)]
    assert order[:4] == [
        (1, "kiting", C1),
        (1, "kiting", C2),
        (1, "alpha_strike", C1),
        (1, "alpha_strike", C2),
    ]
    assert {seed for seed, _, _ in order[:4]} == {1}


def test_a_cell_path_is_filesystem_safe():
    spec = ModelSpec("org/model:free", PROVIDER_MOCK)
    path = Cell(spec, "C2+M", "kiting", 3).path(Path("out"))
    assert path == Path("out/org-model-free/C2M/kiting/seed3.jsonl")


# -- running and resuming ------------------------------------------------------------


def test_a_run_writes_each_cell_and_a_resume_skips_them(tmp_path):
    grid = _grid(conditions=[C1, C3])

    first = run_grid(grid, tmp_path, echo=lambda _: None)
    second = run_grid(grid, tmp_path, echo=lambda _: None)

    assert (first.done, first.skipped) == (2, 0)
    assert (second.done, second.skipped) == (0, 2)
    written = sorted(tmp_path.rglob("seed1.jsonl"))
    assert len(written) == 2
    assert not list(tmp_path.rglob("*.partial"))  # written atomically
    start = json.loads(written[0].read_text(encoding="utf-8").splitlines()[0])
    assert start["kind"] == "match_start" and start["model"] == "mock"
    events = [
        json.loads(line)["event"]
        for line in (tmp_path / RUN_LOG).read_text().splitlines()
    ]
    assert events.count("cell_done") == 2 and events.count("cell_skip") == 2


def test_the_grid_is_copied_beside_the_results(tmp_path):
    grid_file = tmp_path / "grid.src.toml"
    grid_file.write_text("# the grid\n", encoding="utf-8")
    run_grid(_grid(), tmp_path / "out", grid_path=grid_file, echo=lambda _: None)
    assert (tmp_path / "out" / GRID_COPY).read_text() == "# the grid\n"


# -- exclusion: infrastructure only ---------------------------------------------------


class _Raises(Agent):
    def __init__(self, exc):
        super().__init__("broken", "a")
        self._exc = exc

    def decide(self, observation):
        raise self._exc


def _flaky(first_agent):
    """A factory whose first agent misbehaves and whose later ones are the mock."""
    built = []

    def factory(seat):
        built.append(seat.name)
        if len(built) == 1:
            return first_agent
        return MockModelAgent(seat.name, seat.team, seat.interface)

    return {**MODEL_FACTORIES, PROVIDER_MOCK: factory}


def test_an_escaping_provider_error_excludes_and_retries(tmp_path):
    waits = []
    summary = run_grid(
        _grid(),
        tmp_path,
        factories=_flaky(_Raises(RateLimitError("429 slow down"))),
        sleep=waits.append,
        echo=lambda _: None,
    )

    assert summary.done == 1 and summary.excluded_attempts == 1
    assert waits == [5.0]
    assert list((tmp_path / EXCLUDED_DIR).rglob("*.attempt1.jsonl"))


def test_a_transcript_with_a_provider_error_is_excluded(tmp_path):
    """A ProviderError inside a match is contained by the driver — but still infra."""
    summary = run_grid(
        _grid(),
        tmp_path,
        factories=_flaky(_Raises(ProviderError("empty choices"))),
        sleep=lambda _: None,
        echo=lambda _: None,
    )
    assert summary.done == 1 and summary.excluded_attempts == 1


def test_a_bug_is_raised_never_retried(tmp_path):
    """A retry loop that swallowed our own defects would hide them for hours."""
    with pytest.raises(KeyError):
        run_grid(
            _grid(),
            tmp_path,
            factories=_flaky(_Raises(KeyError("oops"))),
            sleep=lambda _: None,
            echo=lambda _: None,
        )


def test_a_cell_that_never_succeeds_is_reported_failed(tmp_path):
    always = {
        **MODEL_FACTORIES,
        PROVIDER_MOCK: lambda *a: _Raises(RateLimitError("still 429")),
    }
    summary = run_grid(
        _grid(max_attempts=2),
        tmp_path,
        factories=always,
        sleep=lambda _: None,
        echo=lambda _: None,
    )
    assert summary.failed and summary.excluded_attempts == 2
    assert not list(tmp_path.rglob("seed1.jsonl"))


def test_infrastructure_is_recognised_by_where_the_error_came_from():
    assert is_infrastructure_error(RateLimitError())
    assert is_infrastructure_error(ConnectionError())
    assert not is_infrastructure_error(KeyError())


# -- spend -----------------------------------------------------------------------------


def test_the_spend_cap_stops_the_run_and_survives_a_resume(tmp_path):
    priced = {
        "id": "mock",
        "provider": "mock",
        "usd_per_m_input": 1_000.0,
        "usd_per_m_output": 1_000.0,
    }
    grid = _grid(models=[priced], conditions=[C1, C2, C3], spend_cap_usd=0.01)

    first = run_grid(grid, tmp_path, echo=lambda _: None)
    assert first.done == 1 and first.stopped
    assert spent_usd(tmp_path, grid) >= 0.01

    resumed = run_grid(grid, tmp_path, echo=lambda _: None)
    assert resumed.done == 0 and resumed.stopped  # recomputed from disk, not reset


# -- preflight -------------------------------------------------------------------------


class _Silent(Agent):
    def decide(self, observation):  # pragma: no cover - preflight never decides
        raise AssertionError

    def _request_action(self, messages, tools):
        return None, RequestRecord(raw_output="")


class _Healthy(_Silent):
    def _request_action(self, messages, tools):
        if tools:
            return ToolCall("end_turn", {}), RequestRecord()
        return None, RequestRecord(raw_output="ACTION: end turn")


def _live(agent_cls):
    grid = _grid(
        models=[
            {
                "id": "org/model",
                "provider": "openrouter",
                "usd_per_m_input": 0.1,
                "usd_per_m_output": 0.1,
            }
        ],
        spend_cap_usd=1.0,
    )
    factories = {**MODEL_FACTORIES, "openrouter": lambda *a: agent_cls("m", "a")}
    return grid, factories


def test_preflight_catches_a_model_without_tool_calling():
    problems = preflight(*_live(_Silent))
    assert any("no tool call" in p for p in problems)
    assert any("no text" in p for p in problems)


def test_preflight_passes_a_healthy_model_and_skips_the_mock():
    assert preflight(*_live(_Healthy)) == []
    assert preflight(_grid()) == []


# -- the CLI ---------------------------------------------------------------------------


def test_a_dry_run_writes_nothing(tmp_path, capsys):
    grid_file = tmp_path / "grid.toml"
    grid_file.write_text(
        '[study]\nseeds = [1, 2]\nscenarios = ["kiting"]\nconditions = ["C1", "C3"]\n'
        '[[models]]\nid = "mock"\nprovider = "mock"\n',
        encoding="utf-8",
    )
    out = tmp_path / "out"

    assert main(["run", str(grid_file), "--out", str(out), "--dry-run"]) == 0
    assert "4 cells" in capsys.readouterr().out
    assert not out.exists()


def test_a_bad_grid_file_exits_with_its_reason(tmp_path, capsys):
    grid_file = tmp_path / "grid.toml"
    grid_file.write_text(
        '[study]\nseeds = [1]\nscenarios = ["nowhere"]\nconditions = ["C1"]\n'
        '[[models]]\nid = "mock"\nprovider = "mock"\n',
        encoding="utf-8",
    )
    assert main(["run", str(grid_file), "--out", str(tmp_path / "o")]) == 2
    assert "nowhere" in capsys.readouterr().err


# -- the upstream host (Phase 1 review, F3) --------------------------------------------


def test_hosts_are_for_openrouter_models_only():
    with pytest.raises(GridError, match="OpenRouter models only"):
        _grid(models=[{"id": "mock", "provider": "mock", "hosts": ["X"]}])
    live = {
        "id": "org/m",
        "provider": "openrouter",
        "usd_per_m_input": 0.1,
        "usd_per_m_output": 0.1,
        "hosts": ["DeepInfra"],
    }
    assert _grid(models=[live], spend_cap_usd=1.0).models[0].hosts == ("DeepInfra",)


# -- robustness and a self-describing manifest (Phase 1 review F7-F9) -----------------


def test_a_run_stops_at_the_first_cell_that_exhausts_its_retries(tmp_path):
    """A quota or outage must not fail, and bill, every remaining cell in turn."""
    attempts = []

    def always_429(seat):
        attempts.append(seat.name)
        return _Raises(RateLimitError("429"))

    summary = run_grid(
        _grid(max_attempts=2, conditions=[C1, C2, C3]),
        tmp_path,
        factories={**MODEL_FACTORIES, PROVIDER_MOCK: always_429},
        sleep=lambda _: None,
        echo=lambda _: None,
    )
    assert len(attempts) == 2  # only the first cell was tried
    assert summary.stopped and "failed all 2 attempts" in summary.stopped


def _live_grid():
    return _grid(
        models=[
            {
                "id": "org/m",
                "provider": "openrouter",
                "usd_per_m_input": 0.1,
                "usd_per_m_output": 0.1,
            }
        ],
        spend_cap_usd=1.0,
    )


def test_a_live_run_refuses_a_dirty_tree(tmp_path, monkeypatch):
    monkeypatch.setattr("src.arena.study.git_dirty", lambda: True)
    summary = run_grid(_live_grid(), tmp_path / "out", echo=lambda _: None)
    assert summary.stopped and "uncommitted" in summary.stopped
    assert not (tmp_path / "out").exists()  # refused before anything ran


def test_a_mock_run_does_not_care_about_the_tree(tmp_path, monkeypatch):
    monkeypatch.setattr("src.arena.study.git_dirty", lambda: True)
    assert run_grid(_grid(), tmp_path, echo=lambda _: None).done == 1


def test_the_manifest_names_the_opponent_and_the_tree_state(tmp_path):
    run_grid(_grid(), tmp_path, echo=lambda _: None)
    (path,) = tmp_path.rglob("seed1.jsonl")
    start = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert start["opponent"] == "scripted"
    assert "git_dirty" in start


def test_the_heuristic_opponent_plays_and_replays(tmp_path):
    from src.arena.replay import verify
    from src.arena.scenarios import SCENARIOS

    run_grid(
        _grid(opponent="heuristic", scenarios=["alpha_strike"], conditions=[C3]),
        tmp_path,
        echo=lambda _: None,
    )
    (path,) = tmp_path.rglob("seed1.jsonl")
    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert records[0]["opponent"] == "heuristic"
    assert verify(records, SCENARIOS["alpha_strike"].build).ok


# -- baselines (prereg §7; Phase 1 review F6) --------------------------------------------


def _baselines(*policies, **study):
    models = [
        {"id": f"baseline-{p}", "provider": "baseline", "policy": p} for p in policies
    ]
    return _grid(models=models, **study)


def test_a_baseline_needs_a_known_policy_and_nothing_else_takes_one():
    with pytest.raises(GridError, match="policy is required"):
        _grid(models=[{"id": "b", "provider": "baseline"}])
    with pytest.raises(GridError, match="only for a baseline"):
        _grid(models=[{"id": "m", "provider": "mock", "policy": "scripted"}])
    with pytest.raises(GridError, match="grandmaster"):
        _grid(models=[{"id": "b", "provider": "baseline", "policy": "grandmaster"}])


def test_baselines_play_once_per_scenario_and_seed_in_their_own_condition():
    grid = _baselines(
        "scripted", "random", "heuristic", conditions=[C1, C2], seeds=[1, 2]
    )
    seen = [(c.model.policy, c.condition) for c in cells(grid)]
    assert len(seen) == 3 * 2  # three baselines x two seeds x one scenario
    assert set(seen) == {("scripted", "C3"), ("random", "C3"), ("heuristic", "native")}


@pytest.mark.parametrize("policy", ["scripted", "random", "heuristic"])
def test_each_baseline_plays_replays_and_costs_nothing(policy, tmp_path):
    from src.arena.replay import verify
    from src.arena.scenarios import SCENARIOS

    summary = run_grid(_baselines(policy), tmp_path, echo=lambda _: None)
    assert summary.done == 1
    (path,) = tmp_path.rglob("seed1.jsonl")
    records = [json.loads(line) for line in path.read_text().splitlines()]

    assert verify(records, SCENARIOS["kiting"].build).ok
    actions = [r for r in records if r["kind"] == "action"]
    assert actions and not any("telemetry" in r for r in actions)
    if policy == "random":  # choosing only from the menu, every choice executes
        mine = [r for r in actions if r["actor_id"] == "archer"]
        assert mine and all(r["result"]["ok"] for r in mine)


def test_a_baseline_only_grid_needs_no_prices_cap_or_clean_tree(tmp_path, monkeypatch):
    monkeypatch.setattr("src.arena.study.git_dirty", lambda: True)
    grid = _baselines("scripted")
    assert grid.spend_cap_usd == 0.0
    assert run_grid(grid, tmp_path, echo=lambda _: None).done == 1
    assert preflight(grid) == []
