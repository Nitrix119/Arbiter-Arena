"""The write-up's chart script reads the same numbers the report prints (ledger A11).

Only the data half is tested: CI does not install the ``[plots]`` extra, and the
point of the script is that its estimates cannot drift from ``summary.md``.
"""

import csv
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

from src.arena.study_report import cluster_ratio, wilson

_SCRIPT = Path(__file__).resolve().parent.parent / "tools" / "plot_study.py"

FIELDS = [
    "model",
    "condition",
    "scenario",
    "model_won",
    "model_hp_fraction",
    "first_attempt_valid",
    "fresh_decisions",
    "area_allies",
    "area_casts",
    "tactic:kiting_adherence.survived",
]
SONNET = "anthropic/claude-sonnet-5.5"


@pytest.fixture(scope="module")
def plot_study():
    spec = importlib.util.spec_from_file_location("plot_study", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve annotations through it
    spec.loader.exec_module(module)
    return module


def _row(condition, scenario, won, hp, valid, fresh, allies, casts, survived=""):
    return dict(
        zip(
            FIELDS,
            [
                SONNET,
                condition,
                scenario,
                str(won),
                str(hp),
                str(valid),
                str(fresh),
                str(allies),
                str(casts),
                str(survived),
            ],
        )
    )


ROWS = [
    _row("C1", "kiting", True, 0.5, 9, 10, 1, 2, 1.0),
    _row("C1", "alpha_strike", False, 0.0, 4, 8, 0, 0),
    _row("C2", "kiting", False, 0.25, 3, 6, 0, 1, 0.0),
]


def test_importing_the_script_does_not_load_matplotlib():
    # CI has no [plots] extra, so only drawing may import it. A fresh process,
    # because this suite's other imports could have loaded it already.
    code = "; ".join(
        [
            "import importlib.util, sys",
            f"spec = importlib.util.spec_from_file_location('p', {str(_SCRIPT)!r})",
            "m = importlib.util.module_from_spec(spec)",
            "sys.modules['p'] = m",
            "spec.loader.exec_module(m)",
            "assert 'matplotlib' not in sys.modules",
        ]
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_validity_matches_the_reports_pooled_ratio(plot_study):
    points = {p.condition: p for p in plot_study.validity(ROWS, SONNET)}
    assert points["C1"].estimate == cluster_ratio([(9, 10), (4, 8)])
    assert points["C1"].n == 18


def test_a_condition_with_no_data_is_kept_and_marked_empty(plot_study):
    # C3 has no rows: it stays on the axis with no estimate, so the chart can say
    # "no casts" rather than silently dropping the condition.
    fire = {p.condition: p for p in plot_study.friendly_fire(ROWS, SONNET)}
    assert list(fire) == ["C1", "C2", "C2+M", "C3"]
    assert fire["C3"].estimate is None and fire["C3"].n == 0
    # One cast that caught nobody is a real zero, not missing data.
    assert fire["C2"].estimate == (0.0, 0.0, 0.0)


def test_win_rate_uses_wilson(plot_study):
    points = {p.condition: p for p in plot_study.win_rate(ROWS, SONNET)}
    low, high = wilson(1, 2)
    assert points["C1"].estimate == (0.5, low, high)


def test_scenario_means_skip_other_scenarios(plot_study):
    field = "tactic:kiting_adherence.survived"
    points = {
        p.condition: p for p in plot_study.match_mean(ROWS, SONNET, field, "kiting")
    }
    assert points["C1"].n == 1
    assert points["C1"].estimate is not None and points["C1"].estimate[0] == 1.0


def test_reads_the_reports_csv(plot_study, tmp_path):
    report = tmp_path / "report"
    report.mkdir()
    with open(report / "matches.csv", "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(ROWS)
    assert plot_study.read_matches(tmp_path) == ROWS
