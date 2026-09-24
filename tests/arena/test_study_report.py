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
    Match,
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
        # A choice naming no id names no action: neither spatial nor not (prereg §6).
        ({"name": "choose", "arguments": {"action_id": None}}, "choose", None),
        ({"name": "choose", "arguments": {}}, "choose", None),
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


def test_a_retry_after_a_rejection_is_not_a_fresh_decision():
    """H1 is over fresh decisions: a retry is recovery, not a second first attempt.

    Counting a retry as a new decision let a recovered retry score as a first-attempt
    success, mixing recovery into the headline number (review 2026-09-24, H-1).
    """
    decisions = decisions_of(
        Path("m.jsonl"),
        _records(
            (True, 1, True),  # fresh, valid
            (False, 1, False),  # fresh, rejected ...
            (True, 1, False),  # ... a retry, not fresh
            (True, 1, False),  # after a success: fresh again
            (False, 1, False),  # fresh, rejected, and the turn ends
            (True, 1, True),  # a new turn: fresh
        ),
    )
    assert [d.fresh for d in decisions] == [True, True, False, True, True, True]


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
        # The stumble is a fresh decision that failed; the decision after it is a
        # retry, not a fresh decision, so it counts toward recovery and never toward
        # first-attempt validity (prereg §6). Every other decision was valid.
        assert [d["fresh"] for d in mine[:2]] == ["True", "False"]
        assert int(match["fresh_decisions"]) == len(mine) - 1
        assert int(match["first_attempt_valid"]) == len(mine) - 2
        assert int(match["per_call_valid"]) == len(mine) - 1
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
        "fresh",
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


def test_baselines_are_reported_beside_the_models(tmp_path):
    """Baselines anchor the tactical metrics, so they appear in the same tables."""
    grid = parse_grid(
        {
            "study": {"seeds": [1], "scenarios": ["kiting"], "conditions": ["C2"]},
            "models": [
                {"id": "mock", "provider": "mock"},
                {
                    "id": "baseline-scripted",
                    "provider": "baseline",
                    "policy": "scripted",
                },
                {
                    "id": "baseline-heuristic",
                    "provider": "baseline",
                    "policy": "heuristic",
                },
            ],
        }
    )
    run_grid(grid, tmp_path, echo=lambda _: None)
    summary = build_report(tmp_path)[3]

    assert "| baseline-scripted | C3 |" in summary
    assert "| baseline-heuristic | native |" in summary
    assert "| mock | C2 |" in summary
    # A baseline plays one condition, so it has nothing to contrast.
    # (Here the mock plays one condition too, so no model has verdicts at all.)
    assert "## Registered verdicts" not in summary


# -- infrastructure, per condition (review 2026-09-24, H-2) -------------------------------


def test_exclusions_and_provider_retries_are_reported_per_condition(tmp_path):
    """A condition-correlated exclusion pattern is a validity problem — so show it.

    Excluding is for infrastructure only, but a host that fails on a model's own
    malformed output would make exclusions track the condition. Only a per-condition
    breakdown can reveal that, so the report gives one, with the reasons.
    """
    import json

    grid = parse_grid(
        {
            "study": {
                "seeds": [1],
                "scenarios": ["kiting"],
                "conditions": ["C2", "C3"],
            },
            "models": [{"id": "mock", "provider": "mock"}],
        }
    )
    run_grid(grid, tmp_path, echo=lambda _: None)
    (c2,) = (tmp_path / "mock" / "C2").rglob("seed1.jsonl")
    records = [json.loads(line) for line in c2.read_text(encoding="utf-8").splitlines()]

    # One excluded attempt for the C2 cell, as the runner files it and logs it.
    excluded = (
        tmp_path / "_excluded" / "mock" / "C2" / "kiting" / "seed1.attempt1.jsonl"
    )
    excluded.parent.mkdir(parents=True)
    excluded.write_text(json.dumps(records[0]) + "\n", encoding="utf-8")
    with open(tmp_path / "run_log.jsonl", "a", encoding="utf-8") as log:
        log.write(
            json.dumps(
                {
                    "event": "cell_excluded",
                    "cell": "mock | C2 | kiting | seed 1",
                    "attempt": 1,
                    "reason": "RateLimitError: 429 slow down",
                }
            )
            + "\n"
        )
    # And one retried provider failure inside the completed C2 match.
    first = next(r for r in records if r["kind"] == "action" and "telemetry" in r)
    first["telemetry"]["provider_failures"] = [{"error": "no choices"}]
    c2.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")

    decisions_csv, _, _, summary = build_report(tmp_path)

    assert "## Infrastructure" in summary
    assert "| mock | C2 | 1 | 1 | RateLimitError x1 |" in summary
    assert "| mock | C3 | 0 | 0 | — |" in summary
    retries = [int(row["provider_retries"]) for row in _rows(decisions_csv)]
    assert sum(retries) == 1


# -- registered verdicts: paired, per model (review 2026-09-24, H-3) ------------------


def _match(condition, scenario, seed, *, valid, fresh=10, won=False, hp=0.5, sp=None):
    """A synthetic match: *valid* of *fresh* first attempts, split evenly by space
    unless *sp* gives ``(spatial valid, spatial n, non-spatial valid, non-spatial n)``.
    """
    sv, sn, nv, nn = sp or (
        valid // 2,
        fresh // 2,
        valid - valid // 2,
        fresh - fresh // 2,
    )
    return Match(
        model="m", condition=condition, scenario=scenario, seed=seed,
        match=f"{condition}/{scenario}/{seed}", model_won=won, winner="a" if won else "b",
        rounds=3, model_hp_fraction=hp, turns=3, forfeit_turns=0, decisions=fresh,
        fresh_decisions=fresh, first_attempt_valid=valid, per_call_valid=valid,
        accepted=valid, recovered=0, recovery_eligible=0, spatial_decisions=sn,
        spatial_valid=sv, nonspatial_decisions=nn, nonspatial_valid=nv,
        input_tokens=0, output_tokens=0, cost_usd=None, area_casts=0,
        area_enemies=0, area_allies=0,
    )  # fmt: skip


PAIRS = [
    (scenario, seed) for scenario in ("kiting", "alpha_strike") for seed in range(5)
]


def _verdict(verdicts, hypothesis, contrast):
    return next(
        v for v in verdicts if (v.hypothesis, v.contrast) == (hypothesis, contrast)
    )


def test_h1_contrasts_are_paired_and_directional():
    from src.arena.study_report import registered_verdicts

    matches = [
        _match(cond, sc, seed, valid=v + (seed % 2))
        for cond, v in (("C3", 9), ("C2+M", 8), ("C2", 6), ("C1", 6))
        for sc, seed in PAIRS
    ]
    verdicts = registered_verdicts(matches)

    assert _verdict(verdicts, "H1", "C3 − C2+M").verdict == "supported"
    assert _verdict(verdicts, "H1", "C2+M − C2").verdict == "supported"
    # Identical rates cannot support a directional claim.
    tie = _verdict(verdicts, "H1", "C2 − C1")
    assert tie.verdict == "not supported"
    assert tie.estimate[0] == pytest.approx(0.0)
    assert "§7 C1 rule" in tie.note


def test_h2_is_the_spatial_deficit_against_the_menu_beyond_the_non_spatial_one():
    from src.arena.study_report import registered_verdicts

    matches = [_match("C3", sc, seed, valid=10, sp=(5, 5, 5, 5)) for sc, seed in PAIRS]
    # C1 loses spatial decisions only; C2 loses both kinds equally.
    matches += [_match("C1", sc, seed, valid=7, sp=(2, 5, 5, 5)) for sc, seed in PAIRS]
    matches += [_match("C2", sc, seed, valid=8, sp=(4, 5, 4, 5)) for sc, seed in PAIRS]
    verdicts = registered_verdicts(matches)

    assert _verdict(verdicts, "H2", "C1").verdict == "supported"
    assert _verdict(verdicts, "H2", "C2").verdict == "not supported"


def test_h3_needs_the_validity_gap_to_exceed_both_tactical_gaps():
    from src.arena.study_report import registered_verdicts

    # Validity: C3 1.0 vs C1 0.5 (a 50-point gap). Win rate: identical. HP fraction:
    # a 10-point gap. Both tactical gaps are smaller, so H3 is supported.
    matches = [
        _match("C3", sc, seed, valid=10, won=seed < 3, hp=0.6) for sc, seed in PAIRS
    ] + [_match("C1", sc, seed, valid=5, won=seed < 3, hp=0.5) for sc, seed in PAIRS]
    assert (
        _verdict(registered_verdicts(matches), "H3", "C3 − C1").verdict == "supported"
    )

    # Now tactics move as much as validity: not supported.
    matches = [
        _match("C3", sc, seed, valid=10, won=True, hp=1.0) for sc, seed in PAIRS
    ] + [_match("C1", sc, seed, valid=5, won=False, hp=0.0) for sc, seed in PAIRS]
    assert (
        _verdict(registered_verdicts(matches), "H3", "C3 − C1").verdict
        == "not supported"
    )


def test_a_contrast_without_paired_data_says_so():
    from src.arena.study_report import registered_verdicts

    matches = [_match(c, sc, seed, valid=9) for c in ("C3", "C1") for sc, seed in PAIRS]
    verdicts = registered_verdicts(matches)
    assert _verdict(verdicts, "H1", "C3 − C2+M").verdict == "insufficient data"
    assert _verdict(verdicts, "H3", "C3 − C1").verdict != "insufficient data"


def test_only_seeds_present_in_both_conditions_are_paired():
    """An excluded-and-unrerun seed must drop out of the pair, not skew one side."""
    from src.arena.study_report import registered_verdicts

    matches = [_match("C3", sc, seed, valid=10) for sc, seed in PAIRS]
    matches += [_match("C2+M", sc, seed, valid=5) for sc, seed in PAIRS[:-1]]
    matches.append(_match("C3", "extra", 99, valid=0))  # unpaired, must be ignored
    verdict = _verdict(registered_verdicts(matches), "H1", "C3 − C2+M")
    assert verdict.pairs == len(PAIRS) - 1
    assert verdict.estimate[0] == pytest.approx(0.5)


def test_verdicts_are_deterministic_and_in_the_summary(bundle):
    from src.arena.study_report import registered_verdicts

    summary = build_report(bundle)[3]
    assert "## Registered verdicts (prereg §7)" in summary
    assert registered_verdicts([]) == []


# -- response integrity (review 2026-09-24, M-1 / M-4) --------------------------------


def test_truncation_and_model_substitution_are_surfaced_per_cell():
    """Three silent failure modes, each of which would bias a cell without a trace.

    A response cut off at the token limit is a harness setting deciding the outcome;
    a menu cut by a length cap removes real options; a router serving a different
    model than the one requested changes the subject. All are counted per cell.
    """
    from src.arena.study_report import _integrity_section

    records = _records((True, 1, True), (False, 1, False), (True, 1, False))
    actions = [r for r in records if r["kind"] == "action"]
    actions[0]["telemetry"].update(
        requests=[{"finish_reason": "length", "served_model": "m"}],
        menu_truncated=True,
    )
    actions[1]["telemetry"].update(
        requests=[{"finish_reason": "stop", "served_model": "m-quantised"}]
    )
    decisions = decisions_of(Path("m.jsonl"), records)

    assert [d.length_cutoffs for d in decisions] == [1, 0, 0]
    assert [d.menu_truncated for d in decisions] == [True, None, None]
    section = "\n".join(_integrity_section(decisions))
    assert "| m | C2 | 1 | 1 | m, m-quantised |" in section
    assert "served a model other than the one requested" in section
    assert "m / C2" in section


def test_a_clean_bundle_has_no_integrity_warnings():
    from src.arena.study_report import _integrity_section

    records = _records((True, 1, True))
    records[-1]["telemetry"]["requests"] = [
        {"finish_reason": "stop", "served_model": "m"}
    ]
    section = "\n".join(_integrity_section(decisions_of(Path("m.jsonl"), records)))
    assert "Warning" not in section
