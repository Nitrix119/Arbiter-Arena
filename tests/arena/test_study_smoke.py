"""The offline smoke: every condition x every scenario, run by the real runner.

V1_PLAN Phase 1: "all conditions x all scenarios with a mocked model, green in CI".
Everything below the model is real — the runner, run_match, each condition's
interpret, the executor, transcripts on disk — and the bundle must replay at 100%.
"""

import json

from src.arena.interfaces import REGISTRY
from src.arena.replay import verify_bundle
from src.arena.scenarios import SCENARIOS
from src.arena.study import parse_grid, run_grid

GRID = {
    "study": {
        "name": "smoke",
        "seeds": [1],
        "scenarios": sorted(SCENARIOS),
        "conditions": sorted(REGISTRY),
    },
    "models": [{"id": "mock", "provider": "mock", "stumble_on": [0, 4]}],
}


def _bundle(out):
    return {
        str(path): [
            json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
        ]
        for path in sorted(out.rglob("seed*.jsonl"))
    }


def test_every_cell_runs_offline_and_replays(tmp_path):
    grid = parse_grid(GRID)

    first = run_grid(grid, tmp_path, echo=lambda _: None)
    assert first.done == len(SCENARIOS) * len(REGISTRY) == 16
    assert not first.failed and first.excluded_attempts == 0

    bundle = _bundle(tmp_path)
    report = verify_bundle(
        bundle,
        lambda records: SCENARIOS[records[0]["scenario"]].build,
    )
    assert report, report.failures

    starts = [records[0] for records in bundle.values()]
    assert {s["condition"] for s in starts} == set(REGISTRY)
    hashes = {}
    for start in starts:
        hashes.setdefault(start["condition"], set()).add(start["prompt_hash"])
    assert all(len(h) == 1 for h in hashes.values())  # one prompt per condition
    assert len({next(iter(h)) for h in hashes.values()}) == len(REGISTRY)

    second = run_grid(grid, tmp_path, echo=lambda _: None)
    assert (second.done, second.skipped) == (0, 16)
