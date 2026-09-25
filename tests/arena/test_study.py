"""The study runner: validation, ordering, resume, exclusion, spend — all offline.

No test here touches the network. Live providers are replaced by the mock model or by
fakes whose failures are shaped like the real SDKs' (an exception class whose module is
``openai``), which is exactly how the runner tells infrastructure from a bug.
"""

import json
from pathlib import Path

import pytest

from src.arena.agent import Agent, ProviderError
from src.arena.interfaces import C1, C2, C3, get_interface
from src.arena.llm_common import decide_one_action
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


def test_stumble_style_is_for_the_mock_and_names_its_options():
    with pytest.raises(GridError, match="mock only"):
        _grid(
            models=[
                {
                    "id": "b",
                    "provider": "baseline",
                    "policy": "scripted",
                    "stumble_style": "hostile",
                }
            ]
        )
    with pytest.raises(GridError, match="hostile"):
        _grid(models=[{"id": "mock", "provider": "mock", "stumble_style": "rude"}])
    hostile = _grid(
        models=[{"id": "mock", "provider": "mock", "stumble_style": "hostile"}]
    )
    assert hostile.models[0].stumble_style == "hostile"


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
    """Ends its turn every time, through the real decide loop so telemetry is real."""

    billed = {"input_tokens": 40, "output_tokens": 8}

    def __init__(self, name, team=None):
        super().__init__(name, team)
        self.interface = get_interface(C2)

    def decide(self, observation):
        return decide_one_action(
            self._request_action, self, observation, self.interface
        )

    def _request_action(self, messages, tools):
        if tools:
            return ToolCall("end_turn", {}), RequestRecord(**self.billed)
        return None, RequestRecord(raw_output="ACTION: end turn", **self.billed)


class _Unbilled(_Healthy):
    """Answers correctly, but its host reports no token usage."""

    billed: dict = {}


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


def test_preflight_refuses_a_model_whose_host_reports_no_usage():
    """An unbillable model reads as $0.00, so the spend cap would never fire.

    Caught before the first cell, where it costs two requests instead of a whole
    grid's worth of unmetered spend.
    """
    problems = preflight(*_live(_Unbilled))
    assert any("no token usage" in p for p in problems)


def test_a_run_stops_when_a_kept_cell_reports_no_usage(tmp_path, monkeypatch):
    """The backstop for a route that stops billing mid-grid (prereg §5).

    The match itself is sound, so it is kept and analysed; what is gone is the
    ability to enforce the cap, so the run does not go on spending.
    """
    monkeypatch.setattr("src.arena.study.git_dirty", lambda: False)
    grid, factories = _live(_Unbilled)
    summary = run_grid(grid, tmp_path, factories=factories, echo=lambda _: None)

    assert summary.done == 1
    assert "no token usage" in (summary.stopped or "")
    kept = list(tmp_path.rglob("seed*.jsonl"))
    assert len(kept) == 1  # kept, not excluded: the data is fine, the billing is not
    assert any(
        event.get("event") == "stop" and "usage" in str(event.get("reason", ""))
        for event in (
            json.loads(line)
            for line in (tmp_path / RUN_LOG).read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    )


def test_a_billed_run_does_not_stop(tmp_path, monkeypatch):
    monkeypatch.setattr("src.arena.study.git_dirty", lambda: False)
    grid, factories = _live(_Healthy)
    summary = run_grid(grid, tmp_path, factories=factories, echo=lambda _: None)

    assert summary.stopped is None
    assert summary.done == 1


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


class _DiesAfter(Agent):
    """Plays a few real (costed) mock decisions, then the provider fails for good."""

    def __init__(self, seat, decisions=2):
        super().__init__(seat.name, seat.team)
        self._inner = MockModelAgent(seat.name, seat.team, seat.interface)
        self._left = decisions

    def decide(self, observation):
        if self._left == 0:
            raise RateLimitError("429 for good")
        self._left -= 1
        return self._inner.decide(observation)

    def last_telemetry(self):
        return self._inner.last_telemetry()


def test_a_resume_never_overwrites_an_excluded_attempt(tmp_path):
    """Prereg §8 reports every exclusion, and the spend cap counts every attempt.

    The attempt number used to restart at 1 on each run, so a resumed cell that failed
    again overwrote the last run's excluded transcripts: the exclusion count fell and
    their cost vanished from the cap.
    """
    from src.arena.study_report import excluded_attempts

    grid = _grid(
        max_attempts=2,
        models=[
            {
                "id": "mock",
                "provider": "mock",
                "usd_per_m_input": 1.0,
                "usd_per_m_output": 1.0,
            }
        ],
    )
    dying = {**MODEL_FACTORIES, PROVIDER_MOCK: _DiesAfter}
    quiet = {"sleep": lambda _: None, "echo": lambda _: None}

    first = run_grid(grid, tmp_path, factories=dying, **quiet)
    spent_once = spent_usd(tmp_path, grid)
    second = run_grid(grid, tmp_path, factories=dying, **quiet)

    assert first.excluded_attempts == second.excluded_attempts == 2
    names = sorted(p.name for p in (tmp_path / EXCLUDED_DIR).rglob("*.jsonl"))
    assert names == [f"seed1.attempt{n}.jsonl" for n in (1, 2, 3, 4)]
    assert excluded_attempts(tmp_path) == 4
    assert spent_once > 0
    assert spent_usd(tmp_path, grid) == pytest.approx(2 * spent_once)


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
    with pytest.raises(GridError, match="grandmaster"):
        _grid(models=[{"id": "b", "provider": "baseline", "policy": "grandmaster"}])
    live = {"id": "o", "provider": "openrouter", "usd_per_m_input": 1.0}
    live["usd_per_m_output"] = 1.0
    with pytest.raises(GridError, match="policy"):
        _grid(models=[{**live, "policy": "random"}], spend_cap_usd=1.0)


def test_a_mock_may_choose_its_policy_but_not_the_heuristic():
    """The mock writes a policy's decisions in each condition's format. The random
    policy casts, so the offline grid exercises area aiming in every condition; the
    heuristic plays natively and cannot be written as a condition's answer."""
    grid = _grid(models=[{"id": "m", "provider": "mock", "policy": "random"}])
    assert grid.models[0].policy == "random"
    with pytest.raises(GridError, match="heuristic"):
        _grid(models=[{"id": "m", "provider": "mock", "policy": "heuristic"}])


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


# -- committed grids and the decision viewer (Phase 1 review F10) ----------------------


def test_the_committed_demo_grid_runs_offline(tmp_path, capsys):
    from src.arena.study import load_grid

    grid = load_grid(Path("examples/study/demo.toml"))
    assert {m.provider for m in grid.models} == {"mock", "baseline"}
    assert (
        main(["run", "examples/study/demo.toml", "--out", str(tmp_path), "--dry-run"])
        == 0
    )
    assert "cells" in capsys.readouterr().out


def test_the_pilot_template_cannot_run_until_filled_in():
    from src.arena.study import load_grid

    with pytest.raises(GridError, match="unfilled template"):
        load_grid(Path("examples/study/pilot.toml"))


def test_a_live_model_priced_at_zero_is_refused():
    free = {
        "id": "org/m",
        "provider": "openrouter",
        "usd_per_m_input": 0.0,
        "usd_per_m_output": 0.0,
    }
    with pytest.raises(GridError, match="above zero"):
        _grid(models=[free], spend_cap_usd=1.0)


def test_show_reads_a_match_decision_by_decision(tmp_path, capsys):
    run_grid(
        _grid(
            conditions=[C1],
            models=[{"id": "mock", "provider": "mock", "stumble_on": [0]}],
        ),
        tmp_path,
        echo=lambda _: None,
    )
    (path,) = tmp_path.rglob("seed1.jsonl")

    assert main(["show", str(path)]) == 0
    everything = capsys.readouterr().out
    assert "REFUSED malformed_output" in everything
    # The mock writes a preamble line before a canonical command, so the command is
    # layer 0 and the prose is recorded beside it, not folded into the layer.
    assert "read  : refused" in everything
    assert "read  : layer 0 (with prose)" in everything

    assert main(["show", str(path), "--refused"]) == 0
    refused = capsys.readouterr().out
    assert refused.count("REFUSED") == 1 and ": ok" not in refused


# -- verify: the bundle replays (V1_PLAN §5) ----------------------------------------


def test_verify_replays_every_completed_cell(tmp_path, capsys):
    run_grid(_grid(conditions=[C1, C2]), tmp_path, echo=lambda _: None)

    assert main(["verify", str(tmp_path)]) == 0
    assert "2/2 transcripts replay (100.0%)" in capsys.readouterr().out


def test_verify_fails_loudly_on_a_transcript_that_does_not_replay(tmp_path, capsys):
    import json

    run_grid(_grid(), tmp_path, echo=lambda _: None)
    (path,) = tmp_path.rglob("seed1.jsonl")
    records = [json.loads(line) for line in path.read_text().splitlines()]
    turn_end = next(r for r in records if r["kind"] == "turn_end")
    turn_end["state_hash"] = "0" * 64  # a tampered record
    path.write_text("".join(json.dumps(r) + "\n" for r in records))

    assert main(["verify", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "0/1 transcripts replay" in out
    assert "seed1.jsonl" in out


def test_verify_ignores_excluded_attempts_and_refuses_an_empty_bundle(tmp_path):
    (tmp_path / "_excluded").mkdir()
    (tmp_path / "_excluded" / "seed1.attempt1.jsonl").write_text("{}\n")
    assert main(["verify", str(tmp_path)]) == 1  # nothing verified is not a pass


# -- sampling settings are grid fields, recorded (review 2026-09-24, M-1 / M-3) --------


def _live_model(**extra):
    return {
        "id": "vendor/model",
        "provider": "openrouter",
        "usd_per_m_input": 0.1,
        "usd_per_m_output": 0.1,
        **extra,
    }


def test_max_tokens_and_reasoning_are_validated_grid_fields():
    grid = _grid(
        models=[_live_model(max_tokens=2048, reasoning={"effort": "low"})],
        spend_cap_usd=1.0,
    )
    assert grid.models[0].max_tokens == 2048
    assert grid.models[0].reasoning_config() == {"effort": "low"}

    with pytest.raises(GridError, match="max_tokens"):
        _grid(models=[_live_model(max_tokens=0)], spend_cap_usd=1.0)
    with pytest.raises(GridError, match="reasoning"):
        _grid(models=[_live_model(reasoning="low")], spend_cap_usd=1.0)
    with pytest.raises(GridError, match="OpenRouter"):
        _grid(
            models=[{"id": "mock", "provider": "mock", "reasoning": {"effort": "low"}}]
        )


def test_the_manifest_records_the_settings_that_ran(tmp_path):
    run_grid(_grid(), tmp_path, echo=lambda _: None)
    (path,) = tmp_path.rglob("seed1.jsonl")
    start = json.loads(path.read_text().splitlines()[0])

    assert start["max_tokens"] == 4096
    assert set(start["versions"]) >= {"python", "lark"}
    assert "hosts" not in start and "reasoning" not in start  # none were set


def test_the_committed_opponent_grid_is_free_and_uses_the_heuristic():
    """pilot_opponent.toml informs the opponent choice at no API cost (review M-5)."""
    from src.arena.study import load_grid

    grid = load_grid(Path("examples/study/pilot_opponent.toml"))
    assert grid.opponent == "heuristic"
    assert {m.provider for m in grid.models} == {"baseline"}


# -- the dry run's cost estimate ------------------------------------------------------


def test_a_dry_run_reports_the_spend_cap_and_says_when_it_cannot_estimate():
    """A fresh grid has no measurement, so the cap is the only honest number.

    The alternative — multiplying a guessed tokens-per-call — would print a figure
    with no basis, and the dry run is the last checkpoint before real money.
    """
    from src.arena.study import _dry_run

    grid = _grid(
        models=[
            {
                "id": "org/model",
                "provider": "openrouter",
                "usd_per_m_input": 1.0,
                "usd_per_m_output": 3.0,
            }
        ],
        spend_cap_usd=2.5,
    )
    text = _dry_run(grid, Path("no-such-bundle"))

    assert "spend cap $2.50" in text
    assert "org/model" in text and "not yet measured" in text


def test_a_dry_run_estimates_from_what_the_bundle_already_cost(tmp_path, monkeypatch):
    """On a resume the estimate is measured, not guessed: $/request from disk."""
    from src.arena.study import CALLS_PER_MATCH_ESTIMATE, _dry_run

    monkeypatch.setattr("src.arena.study.git_dirty", lambda: False)
    model = {
        "id": "org/model",
        "provider": "openrouter",
        # $1 per token either way, so the arithmetic is readable.
        "usd_per_m_input": 1_000_000.0,
        "usd_per_m_output": 1_000_000.0,
    }
    ran = _grid(seeds=[1], models=[model], spend_cap_usd=1e9)
    factories = {**MODEL_FACTORIES, "openrouter": lambda *a: _Healthy("m", "a")}
    run_grid(ran, tmp_path, factories=factories, echo=lambda _: None)

    # The same grid, one seed wider: one cell is on disk and one is still to run.
    wider = _grid(seeds=[1, 2], models=[model], spend_cap_usd=1e9)
    text = _dry_run(wider, tmp_path)

    # _Healthy bills 40 + 8 tokens per request, so a request cost $48 and the one
    # remaining cell is estimated at that rate over ~35 requests.
    assert "1 already done, 1 to run" in text
    assert "$48.0000/request measured" in text
    assert f"${48.0 * CALLS_PER_MATCH_ESTIMATE:,.2f}" in text
