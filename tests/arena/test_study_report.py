"""The report computes exactly the registered measurements — checked, not assumed.

Unit tests pin the statistics and the three definitions the hypotheses rest on
(first-attempt validity, recovery, spatial). The end-to-end test runs a real mock grid
whose stumbles are placed deliberately, so the expected numbers are known in advance.
"""

import csv
import io
import math
from pathlib import Path

import pytest

from src.arena.free_text import UNREAD_TEXT
from src.arena.interfaces import REGISTRY
from src.arena.study import main, parse_grid, run_grid
from src.arena.study_report import (
    Decision,
    bootstrap_mean,
    build_report,
    classify,
    cluster_ratio,
    decisions_of,
    recoveries,
    wilson,
)

# -- statistics -------------------------------------------------------------------------


def test_wilson_matches_known_values():
    low, high = wilson(5, 10)
    assert math.isclose(low, 0.2366, abs_tol=1e-4)
    assert math.isclose(high, 0.7634, abs_tol=1e-4)
    assert wilson(0, 0) is None
    assert wilson(10, 10)[1] == pytest.approx(1.0)


def test_the_cluster_bootstrap_is_deterministic_and_brackets_the_point():
    clusters = [(8, 10), (9, 10), (4, 10), (10, 10), (7, 10)]
    first = cluster_ratio(clusters)
    assert first == cluster_ratio(clusters)
    point, low, high = first
    assert point == pytest.approx(38 / 50)
    assert low <= point <= high


def test_empty_denominators_give_no_estimate():
    assert cluster_ratio([(0, 0), (0, 0)]) is None
    assert bootstrap_mean([]) is None


# -- the registered definitions -----------------------------------------------------------


@pytest.mark.parametrize(
    "call, kind, spatial",
    [
        ({"name": "move", "arguments": {"x": 1, "z": 2}}, "move", True),
        (
            {"name": "cast_spell", "arguments": {"target_point": {"x": 1, "z": 2}}},
            "cast_point",
            True,
        ),
        (
            {"name": "cast_spell", "arguments": {"target_ids": ["a"]}},
            "cast_target",
            False,
        ),
        ({"name": "attack", "arguments": {}}, "attack", False),
        ({"name": "end_turn", "arguments": {}}, "end_turn", False),
        (
            {"name": UNREAD_TEXT, "arguments": {"text": "move toward raider-1"}},
            "unread",
            True,
        ),
        (
            {"name": UNREAD_TEXT, "arguments": {"text": "cast Fireball at (7.5, 60)"}},
            "unread",
            True,
        ),
        (
            {"name": UNREAD_TEXT, "arguments": {"text": "attack raider-1"}},
            "unread",
            False,
        ),
        (
            {"name": "choose", "arguments": {"action_id": "move:retreat:x"}},
            "choose",
            True,
        ),
        (
            {"name": "choose", "arguments": {"action_id": "cast:fireball:aim:a+b"}},
            "choose",
            True,
        ),
        (
            {"name": "choose", "arguments": {"action_id": "attack:dagger:x"}},
            "choose",
            False,
        ),
        ({"name": "(no_tool_call)", "arguments": {}}, "none", None),
    ],
)
def test_what_counts_as_spatial(call, kind, spatial):
    assert classify(call) == (kind, spatial)


def _records(*decisions):
    """A minimal transcript: team a is the model, each decision a telemetry record."""
    records = [
        {
            "kind": "match_start",
            "scenario": "kiting",
            "condition": "C2",
            "model": "m",
            "seed": 1,
            "teams": {"a": ["archer"], "b": ["bruiser"]},
        }
    ]
    turn = 0
    for ok, requests, new_turn in decisions:
        if new_turn:
            turn += 1
            records.append({"kind": "turn_start", "entity_id": "archer", "round": turn})
        records.append(
            {
                "kind": "action",
                "actor_id": "archer",
                "call": {"name": "attack", "arguments": {}},
                "result": {"ok": ok, "code": "" if ok else "out_of_range"},
                "telemetry": {"request_count": requests, "input_tokens": 10},
            }
        )
    return records


def test_a_decision_that_needed_the_correction_failed_its_first_attempt():
    """Ledger A2: accepted on the second request is not valid first time."""
    decisions = decisions_of(
        Path("m.jsonl"), _records((True, 1, True), (True, 2, False))
    )
    assert [d.ok for d in decisions] == [True, True]
    assert [d.first_attempt_valid for d in decisions] == [True, False]


def test_recovery_counts_the_next_decision_in_the_same_turn_only():
    decisions = decisions_of(
        Path("m.jsonl"),
        _records(
            (False, 1, True),  # rejected ...
            (True, 1, False),  # ... recovered in the same turn
            (False, 1, False),  # rejected, and the turn ends
            (False, 1, True),  # a new turn: not a recovery attempt for the last one
            (False, 1, False),  # rejected again, not recovered
        ),
    )
    assert recoveries(decisions) == (1, 2)


def test_only_the_model_team_is_counted():
    records = _records((True, 1, True))
    records.append(
        {
            "kind": "action",
            "actor_id": "bruiser",
            "call": {"name": "attack", "arguments": {}},
            "result": {"ok": False, "code": "out_of_range"},
        }
    )
    assert [d.actor for d in decisions_of(Path("m.jsonl"), records)] == ["archer"]


# -- end to end on a real mock bundle -----------------------------------------------------

#: Each condition's stumble lands in this code (see test_mock_model.py).
STUMBLE_CODE = {
    "C1": "malformed_output",
    "C2": "malformed_output",
    "C3": "unknown_target",
}


@pytest.fixture(scope="module")
def bundle(tmp_path_factory):
    out = tmp_path_factory.mktemp("bundle")
    grid = parse_grid(
        {
            "study": {
                "name": "report-test",
                "seeds": [1, 2],
                "scenarios": ["aoe_placement", "kiting"],
                "conditions": list(REGISTRY),
            },
            "models": [
                {
                    "id": "mock",
                    "provider": "mock",
                    "stumble_on": [0],
                    "usd_per_m_input": 1.0,
                    "usd_per_m_output": 2.0,
                }
            ],
        }
    )
    (out / "grid.toml").write_text(
        "[study]\nname='report-test'\nseeds=[1,2]\n"
        'scenarios=["aoe_placement","kiting"]\n'
        'conditions=["C1","C2","C2+M","C3"]\n'
        '[[models]]\nid="mock"\nprovider="mock"\nstumble_on=[0]\n'
        "usd_per_m_input=1.0\nusd_per_m_output=2.0\n",
        encoding="utf-8",
    )
    run_grid(grid, out, echo=lambda _: None)
    return out


def _rows(text):
    return list(csv.DictReader(io.StringIO(text)))


def test_the_report_counts_exactly_the_injected_stumbles(bundle):
    decisions_csv, matches_csv, _, summary = build_report(bundle)
    decisions = _rows(decisions_csv)
    matches = _rows(matches_csv)

    assert len(matches) == 16
    for match in matches:
        mine = [d for d in decisions if d["match"] == match["match"]]
        rejected = [d for d in mine if d["ok"] == "False"]
        assert len(rejected) == 1  # one stumble per match, on decision 0
        assert mine[0]["ok"] == "False"
        expected = STUMBLE_CODE.get(match["condition"], "malformed_output")
        assert rejected[0]["code"] == expected
        # Every other decision was valid first time, and the stumble recovered.
        assert int(match["first_attempt_valid"]) == len(mine) - 1
        assert (match["recovered"], match["recovery_eligible"]) == ("1", "1")
        assert float(match["cost_usd"]) > 0

    assert "## Validity (H1)" in summary
    assert "## C1 parse layers" in summary
    assert "unknown_target" in summary


def test_menu_length_is_recorded_only_under_a_menu(bundle):
    decisions = _rows(build_report(bundle)[0])
    for d in decisions:
        has_menu = d["condition"] in ("C2+M", "C3")
        assert (d["menu_length"] != "") == has_menu, d


def test_area_casts_are_counted_for_the_caster_scenario_only(bundle):
    matches = _rows(build_report(bundle)[1])
    # The mock plays the scripted policy, which cannot cast area spells.
    assert all(m["area_casts"] == "0" for m in matches)


def test_the_report_is_byte_identical_every_run(bundle):
    assert main(["report", str(bundle)]) == 0
    first = [p.read_bytes() for p in sorted((bundle / "report").iterdir())]
    assert main(["report", str(bundle)]) == 0
    second = [p.read_bytes() for p in sorted((bundle / "report").iterdir())]
    assert first == second and len(first) == 4


def test_decision_rows_carry_every_registered_field():
    fields = set(Decision.__dataclass_fields__)
    assert {
        "first_attempt_valid",
        "spatial",
        "code",
        "menu_length",
        "c1_layer",
    } <= fields


def test_the_harness_itself_adds_no_between_condition_effect(bundle):
    """A null control for the whole study.

    The mock makes the *same* decisions under every condition, so any difference in
    outcome between conditions on a paired scenario and seed would have been created
    by the harness — a prompt, a parser, an executor path — rather than by a model.
    There must be none: the interface may change what a decision costs, never what it
    does.
    """
    matches = _rows(build_report(bundle)[1])
    outcome = ("winner", "rounds", "model_hp_fraction", "turns", "accepted")
    by_cell = {}
    for match in matches:
        key = (match["scenario"], match["seed"])
        by_cell.setdefault(key, set()).add(tuple(match[k] for k in outcome))
    assert len(by_cell) == 4
    assert all(len(outcomes) == 1 for outcomes in by_cell.values()), by_cell


def test_c1_is_reported_under_three_ordered_parsers(bundle):
    """Prereg §7: strict <= primary <= lenient, per decision, from the recorded text."""
    _, _, bounds_csv, summary = build_report(bundle)
    rows = _rows(bounds_csv)

    assert rows and {r["match"].split("/")[1] for r in rows} == {"C1"}
    for row in rows:
        strict, primary, lenient = (
            row[k] == "True" for k in ("strict", "primary", "lenient")
        )
        assert strict <= primary <= lenient, row
    assert "## C1 under three parsers (prereg §7)" in summary
    assert "Not re-scored" not in summary  # every C1 match replayed


def test_a_cell_served_by_two_hosts_is_flagged():
    from src.arena.study_report import _hosts_section

    def decision(host, condition="C2"):
        return Decision(
            "m", condition, "kiting", 1, "x", 1, 1, "a", 0, "attack", False, True, "",
            True, 1, 0, 0, 0.0, None, None, served_provider=host,
        )  # fmt: skip

    clean = _hosts_section([decision("A"), decision("A", "C3")])
    mixed = _hosts_section([decision("A"), decision("B")])
    assert not any("Warning" in line for line in clean)
    assert any("more than one host" in line and "m / C2" in line for line in mixed)
