"""The C1 parser audit: blind sampling, resumable labelling, weighted error rates.

The labelling loop is driven by scripted keystrokes, so every path a person can take —
an unreadable answer, "no single action", skip, quit and resume — is exercised.
"""

import json

import pytest

from src.arena.audit import (
    ACCEPTED,
    AUDIT_REPORT,
    ITEMS,
    KEY,
    LABELS,
    POPULATION,
    REFUSED,
    canonical_label,
    draw_sample,
    first_attempts,
    label_loop,
    main,
    same_action,
    score,
    write_sample,
)
from src.arena.free_text import render_command
from src.arena.study import parse_grid, run_grid
from src.arena.study_report import write_report
from src.arena.tools import ToolCall


@pytest.fixture(scope="module")
def bundle(tmp_path_factory):
    """A mock C1 + C2 bundle whose stumbles give the audit refused items to sample."""
    out = tmp_path_factory.mktemp("bundle")
    grid = parse_grid(
        {
            "study": {
                "name": "audit-test",
                "seeds": [1, 2],
                "scenarios": ["kiting", "aoe_placement"],
                "conditions": ["C1", "C2"],
            },
            "models": [{"id": "mock", "provider": "mock", "stumble_on": [0, 3]}],
        }
    )
    run_grid(grid, out, echo=lambda _: None)
    write_report(out)
    return out


def _read(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _answers(*keys):
    queue = list(keys)
    return lambda prompt: queue.pop(0)


# -- sampling --------------------------------------------------------------------------


def test_only_c1_first_attempts_are_sampled(bundle):
    attempts = first_attempts(bundle)
    assert attempts
    assert {a.match.split("/")[1] for a in attempts} == {"C1"}
    assert {a.stratum for a in attempts} == {ACCEPTED, REFUSED}


def test_the_labeller_never_sees_the_parsers_verdict(bundle, tmp_path):
    write_sample(bundle, tmp_path, n=10, seed=3)
    for item in _read(tmp_path / ITEMS):
        assert set(item) == {"id", "text"}  # blind: no stratum, no parse
    key = _read(tmp_path / KEY)
    assert {row["stratum"] for row in key} == {ACCEPTED, REFUSED}


def test_the_sample_is_half_each_stratum_and_interleaved(bundle):
    attempts = first_attempts(bundle)
    chosen, population = draw_sample(attempts, 10, seed=3)

    strata = [a.stratum for a in chosen]
    refused_available = population[REFUSED]
    assert strata.count(ACCEPTED) == 5
    assert strata.count(REFUSED) == min(5, refused_available)
    assert strata != sorted(strata)  # shuffled: position says nothing about verdict
    assert population[ACCEPTED] + population[REFUSED] == len(attempts)
    assert draw_sample(attempts, 10, seed=3)[0] == chosen  # reproducible


def test_a_new_sample_never_orphans_existing_labels(bundle, tmp_path):
    write_sample(bundle, tmp_path, n=6, seed=1)
    (tmp_path / LABELS).write_text('{"id": "x", "label": null}\n', encoding="utf-8")
    with pytest.raises(FileExistsError):
        write_sample(bundle, tmp_path, n=6, seed=2)


# -- labelling -------------------------------------------------------------------------


def test_labels_are_stored_canonical():
    assert canonical_label("Attack raider-1 with dagger.") == (
        "attack raider-1 with dagger",
        "",
    )
    label, why = canonical_label("hit them hard")
    assert label is None and why


def test_the_label_loop_saves_as_it_goes_and_resumes(bundle, tmp_path):
    write_sample(bundle, tmp_path, n=4, seed=5)
    said = []

    # Item 1: a typo'd answer is refused and re-asked, then a valid one.
    # Item 2: no single action.  Item 3: skipped.  Item 4: quit.
    remaining = label_loop(
        tmp_path,
        ask=_answers("atack bruiser", "end turn", "n", "s", "q"),
        say=said.append,
    )
    labels = _read(tmp_path / LABELS)
    assert [row["label"] for row in labels] == ["end turn", None]
    assert remaining == 2  # the skipped item and the one quit on
    assert any("not a C1 command" in line for line in said)

    # A second session picks up exactly the unlabelled items.
    label_loop(tmp_path, ask=_answers("end turn", "end turn"), say=lambda _: None)
    assert len(_read(tmp_path / LABELS)) == 4


# -- scoring ---------------------------------------------------------------------------


def test_actions_match_by_meaning_not_spelling():
    parsed = {
        "name": "attack",
        "arguments": {"action_name": "Dagger", "defender_id": "Raider 1"},
    }
    assert same_action("attack raider-1 with dagger", parsed)
    assert not same_action("attack raider-2 with dagger", parsed)
    assert same_action(None, None)
    assert not same_action(None, parsed)
    point = {
        "name": "cast_spell",
        "arguments": {"spell_name": "Fireball", "target_point": {"x": 7.5, "z": 60}},
    }
    assert same_action("cast Fireball at x=7.5 y=0 z=60", point)


def _label_everything(tmp_path, refused_as_action):
    """Label accepted items as the parser read them; refused ones as told."""
    for entry in _read(tmp_path / KEY):
        if entry["stratum"] == ACCEPTED:
            call = entry["parser_call"]
            label = render_command(ToolCall(call["name"], call["arguments"]))
        else:
            label = "end turn" if refused_as_action else None
        with open(tmp_path / LABELS, "a", encoding="utf-8") as handle:
            handle.write(json.dumps({"id": entry["id"], "label": label}) + "\n")


def test_a_parser_that_agrees_with_the_reader_scores_zero(bundle, tmp_path):
    write_sample(bundle, tmp_path, n=10, seed=2)
    _label_everything(tmp_path, refused_as_action=False)
    result = score(tmp_path)

    assert result.unlabelled == 0
    assert result.false_rejects == 0 and result.false_accepts == 0
    assert result.false_reject_rate()[0] == 0.0


def test_false_rejects_are_weighted_by_the_refused_share(bundle, tmp_path):
    write_sample(bundle, tmp_path, n=10, seed=2)
    _label_everything(tmp_path, refused_as_action=True)
    result = score(tmp_path)
    population = json.loads((tmp_path / POPULATION).read_text(encoding="utf-8"))

    share = population[REFUSED] / (population[REFUSED] + population[ACCEPTED])
    point, low, high = result.false_reject_rate()
    assert result.false_rejects == result.refused_labelled
    assert point == pytest.approx(share)  # every refused item was a false reject
    assert low <= point <= high <= share + 1e-9


# -- the decision rule and the CLI --------------------------------------------------------


def test_score_reports_the_registered_decision_rule(bundle, tmp_path):
    assert main(["sample", str(bundle), "--out", str(tmp_path), "--n", "8"]) == 0
    _label_everything(tmp_path, refused_as_action=False)
    report = bundle / "report"
    assert main(["score", str(tmp_path), "--report", str(report)]) == 0

    text = (tmp_path / AUDIT_REPORT).read_text(encoding="utf-8")
    assert "## Decision rule for C1 < C2 in H1" in text
    # The mock stumbles identically in C1 and C2, so C1 is not below C2: (a) fails.
    assert "| mock |" in text and "not supported" in text


def test_running_out_of_input_saves_and_quits(bundle, tmp_path):
    """Ctrl-D, Ctrl-Z or exhausted piped input must not lose work or crash."""
    write_sample(bundle, tmp_path, n=4, seed=5)

    def one_then_eof(prompt, answers=["end turn"]):
        if answers:
            return answers.pop()
        raise EOFError

    remaining = label_loop(tmp_path, ask=one_then_eof, say=lambda _: None)
    assert remaining == 3
    assert len(_read(tmp_path / LABELS)) == 1


# -- fresh decisions only, as in H1 (review 2026-09-24) -------------------------------


def test_only_fresh_first_attempts_are_sampled(bundle):
    """A retry after a refusal is recovery, not a first attempt (prereg §6), so it is
    not in the population the false-reject rate is weighted to."""
    from src.arena.study_report import completed_transcripts, decisions_of

    fresh = set()
    for path, records in completed_transcripts(bundle):
        relative = path.relative_to(bundle)
        for d in decisions_of(relative, records):
            if d.condition == "C1" and d.fresh:
                fresh.add((relative.as_posix(), d.index))
    attempts = first_attempts(bundle)

    assert {(a.match, a.index) for a in attempts} == fresh


def _write_csv(path, rows):
    import csv

    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_the_decision_rule_compares_fresh_decisions_only(tmp_path):
    """Retries flip this verdict if they are pooled in; H1 is over fresh decisions."""
    from src.arena.audit import AuditScore, decision_rule

    def rows(condition, fresh, valid, n):
        return [
            {
                "model": "m",
                "condition": condition,
                "fresh": str(fresh),
                "first_attempt_valid": str(valid),
            }
        ] * n

    decisions = (
        rows("C2", True, True, 4)
        + rows("C2", False, False, 8)  # retries: would drag C2 down to 4/12
        + rows("C1", True, True, 2)
        + rows("C1", True, False, 2)
        + rows("C1", False, True, 8)  # retries: would lift C1 to 10/12
    )
    _write_csv(tmp_path / "decisions.csv", decisions)
    _write_csv(
        tmp_path / "c1_bounds.csv",
        [{"model": "m", "lenient": "True"}, {"model": "m", "lenient": "False"}],
    )
    nothing_labelled = AuditScore(0, 0, 0, 0, 0, 0, 0.0)

    lines = decision_rule(tmp_path, nothing_labelled)

    row = next(line for line in lines if line.startswith("| m |"))
    assert "| 1.000 | 0.500 | 0.500 |" in row  # C2, C1 primary, C1 lenient
    assert row.endswith("| supported |")
