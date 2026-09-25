"""Offline re-scoring of C1 under the strict and lenient bounds.

Each fixture decision is written to land in a known place across the three parsers,
so the bounds are checked against verdicts worked out by hand. The lenient verdict
needs the game state at the moment of decision; these tests prove it is probed on a
copy that leaves the replay undisturbed.
"""

from typing import Any, Dict, List

import pytest

from src.arena.agent import Agent, ScriptedAgent
from src.arena.interfaces import C1, get_interface
from src.arena.llm_common import decide_one_action
from src.arena.manifest import Manifest
from src.arena.match import run_match
from src.arena.mock_model import MockModelAgent
from src.arena.replay import verify
from src.arena.rescore import RescoreError, rescore
from src.arena.scenarios import SCENARIOS
from src.arena.telemetry import RequestRecord
from src.arena.transcript import Transcript

#: What the archer (whose one attack is a Longbow) writes, decision by decision, and
#: the (primary, strict, lenient) verdicts each must get.
SCRIPT = [
    # No weapon named: primary refuses; lenient implies the Longbow, in range.
    ("ACTION: attack bruiser", (False, False, True)),
    # Prose around a *canonical* line: the layer describes the command, so this is
    # layer 0 and strict accepts it. Before 2026-09-25 the prose forced layer 3 and
    # strict refused, which made the strict bound unmeetable for real model output
    # (prereg §7) — a model almost always writes a sentence.
    ("Loosing an arrow.\nACTION: attack bruiser with Longbow", (True, True, True)),
    # Canonical: valid under all three. Ends turn 1.
    ("ACTION: end turn", (True, True, True)),
    # Turn 2. A synonym form: grammatical but not canonical (layer 2), so strict
    # refuses. This is what strict is for, and it still discriminates.
    ("ACTION: end my turn", (True, False, True)),
    # A target that does not exist: no reading can make that executable.
    ("ACTION: attack nobody with Longbow", (False, False, False)),
]


class _Writes(Agent):
    """A C1 "model" that writes the scripted lines, then ends every turn."""

    def __init__(self, lines: List[str]) -> None:
        super().__init__("archer-model", "a")
        self._lines = list(lines)

    def decide(self, observation: Dict[str, Any]):
        line = self._lines.pop(0) if self._lines else "ACTION: end turn"

        def request(messages, tools):
            return None, RequestRecord(raw_output=line)

        return decide_one_action(request, self, observation, get_interface(C1))


def _kiting_match(agent):
    transcript = Transcript()
    run_match(
        SCENARIOS["kiting"].build(),
        {"a": agent, "b": ScriptedAgent("Bruiser", "b")},
        seed=2,
        round_cap=3,
        transcript=transcript,
        manifest=Manifest(scenario="kiting", condition=C1, model="script"),
    )
    return transcript.records


def test_the_three_parsers_disagree_exactly_where_they_should():
    records = _kiting_match(_Writes([line for line, _ in SCRIPT]))
    bounds = rescore(records, SCENARIOS["kiting"].build)

    got = [(b.primary, b.strict, b.lenient) for b in bounds[: len(SCRIPT)]]
    assert got == [expected for _, expected in SCRIPT]
    assert bounds[0].lenient_layer == 4
    # The remaining turns are canonical end turns: valid under every parser.
    assert all(b.primary and b.strict and b.lenient for b in bounds[len(SCRIPT) :])


def test_the_bounds_are_ordered_strict_primary_lenient():
    """A bound that could invert would not be a bound."""
    records = _kiting_match(_Writes([line for line, _ in SCRIPT]))
    for b in rescore(records, SCENARIOS["kiting"].build):
        assert b.strict <= b.primary <= b.lenient


def test_probing_leaves_the_match_replayable():
    records = _kiting_match(_Writes([line for line, _ in SCRIPT]))
    rescore(records, SCENARIOS["kiting"].build)
    assert verify(records, SCENARIOS["kiting"].build).ok


def test_a_non_c1_match_has_no_bounds():
    transcript = Transcript()
    run_match(
        SCENARIOS["kiting"].build(),
        {
            "a": MockModelAgent("m", "a", get_interface("C2")),
            "b": ScriptedAgent("B", "b"),
        },
        seed=1,
        round_cap=2,
        transcript=transcript,
        manifest=Manifest(scenario="kiting", condition="C2"),
    )
    assert rescore(transcript.records, SCENARIOS["kiting"].build) == []


def test_a_transcript_that_does_not_replay_is_refused_loudly():
    """A bound computed on the wrong state would be worse than none."""
    records = _kiting_match(_Writes([line for line, _ in SCRIPT]))
    tampered = [dict(r) for r in records]
    for record in tampered:
        if record["kind"] == "turn_end":
            record["state_hash"] = "0" * 64
            break
    with pytest.raises(RescoreError):
        rescore(tampered, SCENARIOS["kiting"].build)
