"""The C1 parser audit: blind hand-labels, and the parser's measured error.

    python -m src.arena.audit sample results/<name> --out audit/ [--n 200] [--seed 1]
    python -m src.arena.audit label audit/
    python -m src.arena.audit score audit/ [--report results/<name>/report]

PREREGISTRATION §7 registers a parser audit. A sample of C1 first-attempt responses
from the **final** run is hand-labelled **without sight of the parser's verdict**, and
the parser's false-reject and false-accept rates are reported. They feed the decision
rule for C1's place in H1.

**Blinding.** ``sample`` writes two files. ``items.jsonl`` holds only an opaque id and
the model's text, and it is the only file the labelling loop reads. ``key.jsonl`` holds
the parser's verdicts and stays closed until ``score``. The sample is drawn half from
responses the parser accepted and half from those it refused, so both error rates are
estimable. The two halves are shuffled together, so an item's position says nothing
about its verdict.

**What a label means.** The single action a careful reader, following only the prompt's
rules, would take the text to mean, or "no single action". A label is typed as a C1
command, so it is canonical and comparable. Names are written as the model wrote them,
because resolving names is the executor's job and is shared with C2.

**Weighting.** The halves are not the population's proportions, so each rate is
estimated within its stratum and scaled by that stratum's share of all first attempts.
For example, the population false-reject rate = P(refused) × P(a reader finds an action
| refused).
"""

import argparse
import csv
import hashlib
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from src.arena.free_text import read_response, render_command
from src.arena.identifiers import identifier_key
from src.arena.interfaces import C1, C2
from src.arena.scenarios import model_team
from src.arena.study_report import completed_transcripts, decisions_of, wilson
from src.utils import dice

ITEMS = "items.jsonl"
KEY = "key.jsonl"
LABELS = "labels.jsonl"
POPULATION = "population.json"
AUDIT_REPORT = "audit_report.md"

ACCEPTED = "accepted"
REFUSED = "refused"

DEFAULT_SAMPLE = 200

_HELP = """\
Label each response with the ONE action a careful reader, following only the prompt's
rules, would take it to mean. Write it as a C1 command, with names as the model wrote
them:
    attack <target> with <attack name>
    cast <spell> at <target>         cast <spell> at x=<feet> z=<feet>   [at level <n>]
    move to x=<feet> z=<feet>        end turn
Keys:  n = no single action   s = skip for now   q = save and quit   ? = this help"""


# -- sampling ----------------------------------------------------------------------


@dataclass(frozen=True)
class Attempt:
    """One C1 first attempt: what the model wrote, and what the parser read."""

    id: str
    text: str
    stratum: str
    parser_call: Optional[Dict[str, Any]]
    model: str
    match: str
    index: int


def _attempt_id(match: str, index: int) -> str:
    return hashlib.sha256(f"{match}#{index}".encode("utf-8")).hexdigest()[:12]


def first_attempts(bundle: Path) -> List[Attempt]:
    """Every C1 first attempt in the bundle, in a stable order.

    Fresh decisions only, as in H1 (prereg §6): a retry after a refusal is measured
    by recovery, so it is not in the population the audited rates are weighted to.
    Freshness is read from the report's own :func:`decisions_of`, so the two cannot
    disagree about which decisions those are.
    """
    out: List[Attempt] = []
    for path, records in completed_transcripts(bundle):
        start = next(r for r in records if r["kind"] == "match_start")
        if start.get("condition") != C1:
            continue
        members = set(start["teams"].get(model_team(start, records), []))
        relative = path.relative_to(bundle)
        match = relative.as_posix()
        fresh = {d.index for d in decisions_of(relative, records) if d.fresh}
        decisions = [
            r for r in records if r["kind"] == "action" and r["actor_id"] in members
        ]
        for index, record in enumerate(decisions):
            requests = (record.get("telemetry") or {}).get("requests") or []
            if index not in fresh or not requests:
                continue
            text = requests[0].get("raw_output") or ""
            call = read_response(text).call
            out.append(
                Attempt(
                    id=_attempt_id(match, index),
                    text=text,
                    stratum=ACCEPTED if call is not None else REFUSED,
                    parser_call=(
                        {"name": call.name, "arguments": call.arguments}
                        if call is not None
                        else None
                    ),
                    model=str(start.get("model", "?")),
                    match=match,
                    index=index,
                )
            )
    return out


def draw_sample(
    attempts: Sequence[Attempt], n: int, seed: int
) -> Tuple[List[Attempt], Dict[str, int]]:
    """Half from each stratum (all of one if it is short), shuffled together."""
    strata: Dict[str, List[Attempt]] = {ACCEPTED: [], REFUSED: []}
    for attempt in attempts:
        strata[attempt.stratum].append(attempt)
    rng = dice.new_rng(seed)
    chosen: List[Attempt] = []
    half = n // 2
    for name in (ACCEPTED, REFUSED):
        pool = strata[name]
        chosen += rng.sample(pool, min(half, len(pool)))
    rng.shuffle(chosen)
    population = {name: len(pool) for name, pool in strata.items()}
    return chosen, population


def _write_jsonl(path: Path, rows: Sequence[Dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8", newline="\n"
    )


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def write_sample(bundle: Path, out: Path, n: int, seed: int) -> Dict[str, int]:
    """Draw the sample and write the blind items, the sealed key and the counts."""
    if (out / LABELS).exists():
        raise FileExistsError(
            f"{out / LABELS} already exists: a new sample would orphan its labels"
        )
    chosen, population = draw_sample(first_attempts(bundle), n, seed)
    out.mkdir(parents=True, exist_ok=True)
    _write_jsonl(out / ITEMS, [{"id": a.id, "text": a.text} for a in chosen])
    _write_jsonl(
        out / KEY,
        [
            {
                "id": a.id,
                "stratum": a.stratum,
                "parser_call": a.parser_call,
                "model": a.model,
                "match": a.match,
                "index": a.index,
            }
            for a in chosen
        ],
    )
    (out / POPULATION).write_text(
        json.dumps({**population, "seed": seed, "n": n, "sampled": len(chosen)}),
        encoding="utf-8",
    )
    return population


# -- labelling ---------------------------------------------------------------------


def canonical_label(answer: str) -> Tuple[Optional[str], str]:
    """(canonical C1 command, "") if *answer* reads as one, else (None, why)."""
    reading = read_response("ACTION: " + answer.strip())
    if reading.call is None:
        return None, reading.reason or "not a C1 command"
    return render_command(reading.call), ""


def label_loop(
    out: Path,
    ask: Callable[[str], str] = input,
    say: Callable[[str], None] = print,
) -> int:
    """Label every unlabelled item, saving after each one. Returns how many remain."""
    items = _read_jsonl(out / ITEMS)
    done = {row["id"] for row in _read_jsonl(out / LABELS)}
    todo = [item for item in items if item["id"] not in done]
    say(_HELP)
    skipped = 0
    for position, item in enumerate(todo, start=1):
        say(f"\n[{len(done) + position} of {len(items)}] " + "-" * 40)
        say(item["text"] if item["text"].strip() else "(empty response)")
        say("-" * 50)
        while True:
            try:
                answer = ask("label> ").strip()
            except EOFError:  # Ctrl-D / Ctrl-Z, or piped input ran out: save and quit
                answer = "q"
            if answer == "?":
                say(_HELP)
                continue
            if answer.lower() == "q":
                return len(todo) - position + 1 + skipped
            if answer.lower() == "s":
                skipped += 1
                break
            if answer.lower() == "n":
                label: Optional[str] = None
                say("  recorded: no single action")
            else:
                label, why = canonical_label(answer)
                if label is None:
                    say(f"  not a C1 command: {why}")
                    continue
                say(f"  recorded: {label}")
            with open(out / LABELS, "a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps({"id": item["id"], "label": label}) + "\n")
            break
    return skipped


# -- scoring -----------------------------------------------------------------------


def _normalised(call: Dict[str, Any]) -> str:
    """A call as comparable text: names by key, points as floats with ground y."""

    def norm(value: Any) -> Any:
        if isinstance(value, str):
            return identifier_key(value)
        if isinstance(value, list):
            return [norm(v) for v in value]
        if isinstance(value, dict):
            point = {k: float(value.get(k, 0.0)) for k in ("x", "y", "z")}
            return point if set(value) <= {"x", "y", "z"} else value
        return value

    args = {k: norm(v) for k, v in (call.get("arguments") or {}).items()}
    if call.get("name") == "move":
        args = norm(call.get("arguments") or {})
    return json.dumps({"name": call.get("name"), "arguments": args}, sort_keys=True)


def same_action(label: Optional[str], parser_call: Optional[Dict[str, Any]]) -> bool:
    """Does a human label name the action the parser read?"""
    if label is None or parser_call is None:
        return label is None and parser_call is None
    call = read_response("ACTION: " + label).call
    if call is None:
        return False
    return _normalised({"name": call.name, "arguments": call.arguments}) == _normalised(
        parser_call
    )


@dataclass(frozen=True)
class AuditScore:
    """The parser's measured error, weighted back to the population."""

    labelled: int
    unlabelled: int
    refused_labelled: int
    false_rejects: int
    accepted_labelled: int
    false_accepts: int
    share_refused: float

    def false_reject_rate(self) -> Optional[Tuple[float, float, float]]:
        """P(a reader finds an action AND the parser refused), with a 95% interval."""
        return self._weighted(
            self.false_rejects, self.refused_labelled, self.share_refused
        )

    def false_accept_rate(self) -> Optional[Tuple[float, float, float]]:
        """P(the parser read an action the reader would not), with a 95% interval."""
        return self._weighted(
            self.false_accepts, self.accepted_labelled, 1.0 - self.share_refused
        )

    @staticmethod
    def _weighted(k: int, n: int, share: float) -> Optional[Tuple[float, float, float]]:
        interval = wilson(k, n)
        if interval is None:
            return None
        return share * k / n, share * interval[0], share * interval[1]


def score(out: Path) -> AuditScore:
    key = {row["id"]: row for row in _read_jsonl(out / KEY)}
    labels = {row["id"]: row["label"] for row in _read_jsonl(out / LABELS)}
    population = json.loads((out / POPULATION).read_text(encoding="utf-8"))
    total = population[ACCEPTED] + population[REFUSED]
    refused_n = false_rejects = accepted_n = false_accepts = 0
    for item_id, label in labels.items():
        entry = key[item_id]
        if entry["stratum"] == REFUSED:
            refused_n += 1
            false_rejects += label is not None
        else:
            accepted_n += 1
            false_accepts += not same_action(label, entry["parser_call"])
    return AuditScore(
        labelled=len(labels),
        unlabelled=len(key) - len(labels),
        refused_labelled=refused_n,
        false_rejects=false_rejects,
        accepted_labelled=accepted_n,
        false_accepts=false_accepts,
        share_refused=population[REFUSED] / total if total else 0.0,
    )


# -- the registered decision rule --------------------------------------------------


def _pooled(rows: Sequence[Dict[str, str]], column: str) -> Optional[float]:
    return sum(r[column] == "True" for r in rows) / len(rows) if rows else None


def decision_rule(report_dir: Path, result: AuditScore) -> List[str]:
    """PREREGISTRATION §7's rule for C1 < C2 in H1, on the report's point estimates.

    Supported only if C1 < C2 holds (a) under the primary parser, (b) under the lenient
    bound, and (c) after adding the upper 95% bound of the audited false-reject rate
    to C1's primary validity. Otherwise the C1 comparison is exploratory.
    """
    with open(report_dir / "decisions.csv", encoding="utf-8") as handle:
        # Fresh decisions only, as H1 is measured (prereg §6); c1_bounds.csv is
        # already restricted to them, so all three checks share one denominator.
        decisions = [r for r in csv.DictReader(handle) if r.get("fresh") == "True"]
    with open(report_dir / "c1_bounds.csv", encoding="utf-8") as handle:
        bounds = list(csv.DictReader(handle))
    fr = result.false_reject_rate()
    fr_upper = fr[2] if fr else 0.0

    by_model: Dict[str, Dict[str, List[Dict[str, str]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for row in decisions:
        by_model[row["model"]][row["condition"]].append(row)
    lenient_by_model: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    for row in bounds:
        lenient_by_model[row["model"]].append(row)

    lines = [
        "| model | C2 | C1 primary | C1 lenient | C1 + FR upper "
        "| (a) | (b) | (c) | verdict |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for model in sorted(by_model):
        c2 = _pooled(by_model[model][C2], "first_attempt_valid")
        c1 = _pooled(by_model[model][C1], "first_attempt_valid")
        lenient = _pooled(lenient_by_model[model], "lenient")
        if c1 is None or c2 is None or lenient is None:
            lines.append(f"| {model} | — | — | — | — | — | — | — | not computable |")
            continue
        adjusted = min(1.0, c1 + fr_upper)
        checks = (c1 < c2, lenient < c2, adjusted < c2)
        if all(checks):
            verdict = "supported"
        elif checks[0]:
            verdict = "exploratory"
        else:
            verdict = "not supported"
        marks = ["yes" if c else "no" for c in checks]
        lines.append(
            f"| {model} | {c2:.3f} | {c1:.3f} | {lenient:.3f} | {adjusted:.3f} | "
            + " | ".join(marks)
            + f" | {verdict} |"
        )
    return lines


def _fmt(rate: Optional[Tuple[float, float, float]]) -> str:
    if rate is None:
        return "—"
    return f"{rate[0]:.4f} [{rate[1]:.4f}, {rate[2]:.4f}]"


def audit_report(out: Path, result: AuditScore, report_dir: Optional[Path]) -> str:
    parts = [
        "# C1 parser audit",
        "",
        f"{result.labelled} labelled, {result.unlabelled} not yet labelled. Rates are "
        "weighted to the population of C1 first attempts (95% Wilson, scaled by the "
        f"stratum share; refused share {result.share_refused:.3f}).",
        "",
        "| measure | labelled in stratum | errors | population rate |",
        "|---|---|---|---|",
        f"| false reject (refused, but a reader finds one action) | "
        f"{result.refused_labelled} | {result.false_rejects} | "
        f"{_fmt(result.false_reject_rate())} |",
        f"| false accept (accepted, but as a different action or none) | "
        f"{result.accepted_labelled} | {result.false_accepts} | "
        f"{_fmt(result.false_accept_rate())} |",
    ]
    if report_dir is not None:
        parts += [
            "",
            "## Decision rule for C1 < C2 in H1 (PREREGISTRATION §7)",
            "",
            "Judged on pooled point estimates; intervals are in the study report.",
            "",
            *decision_rule(report_dir, result),
        ]
    return "\n".join(parts) + "\n"


# -- CLI ---------------------------------------------------------------------------


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.arena.audit")
    commands = parser.add_subparsers(dest="command", required=True)
    sample = commands.add_parser("sample", help="draw a blind, stratified sample")
    sample.add_argument("bundle", type=Path)
    sample.add_argument("--out", type=Path, required=True)
    sample.add_argument("--n", type=int, default=DEFAULT_SAMPLE)
    sample.add_argument("--seed", type=int, default=1)
    label = commands.add_parser("label", help="label the sample (resumable)")
    label.add_argument("audit", type=Path)
    scored = commands.add_parser("score", help="measure the parser's error")
    scored.add_argument("audit", type=Path)
    scored.add_argument("--report", type=Path, default=None)
    args = parser.parse_args(argv)

    if args.command == "sample":
        try:
            population = write_sample(args.bundle, args.out, args.n, args.seed)
        except FileExistsError as exc:
            print(exc, file=sys.stderr)
            return 2
        print(
            f"sampled from {population[ACCEPTED]} accepted and "
            f"{population[REFUSED]} refused C1 first attempts -> {args.out / ITEMS}"
        )
        return 0
    if args.command == "label":
        remaining = label_loop(args.audit)
        print(f"\n{remaining} item(s) still to label." if remaining else "\nAll done.")
        return 0

    result = score(args.audit)
    text = audit_report(args.audit, result, args.report)
    (args.audit / AUDIT_REPORT).write_text(text, encoding="utf-8", newline="\n")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
