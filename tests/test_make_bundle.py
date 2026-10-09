"""The release bundle carries what the study needs to be checked, and nothing else.

``tools/make_bundle.py`` packs a result bundle, the parser audit, the prompts and the
pre-registration into one zip. These tests hold it to the three refusals that make the
zip trustworthy: a missing audit, a prompt that no longer hashes to what the
transcripts recorded, and anything key-shaped.
"""

import hashlib
import importlib.util
import json
import sys
import zipfile
from pathlib import Path

import pytest

from src.arena.interfaces import get_interface
from src.arena.manifest import interface_fingerprint

_SCRIPT = Path(__file__).resolve().parent.parent / "tools" / "make_bundle.py"


@pytest.fixture(scope="module")
def make_bundle():
    spec = importlib.util.spec_from_file_location("make_bundle", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _transcript(path: Path, condition: str, prompt_hash, extra: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    start = {
        "i": 0,
        "kind": "match_start",
        "model": "m",
        "condition": condition,
        "prompt_hash": prompt_hash,
    }
    lines = [json.dumps(start), json.dumps({"i": 1, "kind": "action", "note": extra})]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.fixture
def layout(tmp_path):
    bundle = tmp_path / "results" / "final"
    _transcript(
        bundle / "m" / "C2" / "kiting" / "seed101.jsonl",
        "C2",
        interface_fingerprint(get_interface("C2")),
    )
    _transcript(
        bundle / "baseline-heuristic" / "native" / "kiting" / "seed101.jsonl",
        "native",
        None,
    )
    (bundle / "report").mkdir()
    (bundle / "report" / "summary.md").write_text("# Study report\n", encoding="utf-8")
    audit = tmp_path / "audit"
    audit.mkdir()
    for name in ("items.jsonl", "key.jsonl", "labels.jsonl"):
        (audit / name).write_text("{}\n", encoding="utf-8")
    (audit / "population.json").write_text("{}\n", encoding="utf-8")
    (audit / "audit_report.md").write_text("# Audit\n", encoding="utf-8")
    prereg = tmp_path / "PREREGISTRATION.md"
    prereg.write_text("# Pre-registration, with deviations\n", encoding="utf-8")
    return bundle, audit, prereg, tmp_path / "out.zip"


def _build(make_bundle, layout):
    bundle, audit, prereg, out = layout
    return make_bundle.build_bundle(
        bundle,
        audit,
        out,
        prereg=prereg,
        frozen_prereg="# Pre-registration, as frozen\n",
        version="1.0.0",
    )


def test_bundle_unzips_into_the_repo_layout(make_bundle, layout):
    _build(make_bundle, layout)
    with zipfile.ZipFile(layout[3]) as z:
        names = set(z.namelist())
    assert "results/final/m/C2/kiting/seed101.jsonl" in names
    assert "results/final/report/summary.md" in names
    assert "audit/audit_report.md" in names
    assert "audit/labels.jsonl" in names
    assert "study-bundle/README.md" in names
    assert "study-bundle/PREREGISTRATION.md" in names
    assert "study-bundle/PREREGISTRATION_at_freeze.md" in names


def test_prompts_are_exported_for_the_conditions_in_the_bundle(make_bundle, layout):
    _build(make_bundle, layout)
    with zipfile.ZipFile(layout[3]) as z:
        names = set(z.namelist())
        prompt = z.read("study-bundle/prompts/C2.md").decode("utf-8")
    assert {n for n in names if n.startswith("study-bundle/prompts/")} == {
        "study-bundle/prompts/C2.md"
    }
    assert get_interface("C2").system_prompt() in prompt
    assert interface_fingerprint(get_interface("C2")) in prompt


def test_checksums_cover_every_other_member(make_bundle, layout):
    _build(make_bundle, layout)
    with zipfile.ZipFile(layout[3]) as z:
        sums = z.read("study-bundle/SHA256SUMS").decode("utf-8").splitlines()
        listed = {}
        for line in sums:
            digest, name = line.split("  ", 1)
            listed[name] = digest
        others = set(z.namelist()) - {"study-bundle/SHA256SUMS"}
        assert set(listed) == others
        for name in others:
            assert hashlib.sha256(z.read(name)).hexdigest() == listed[name]


def test_a_missing_audit_is_refused(make_bundle, layout):
    bundle, audit, prereg, out = layout
    (audit / "audit_report.md").unlink()
    with pytest.raises(make_bundle.BundleError, match="audit_report.md"):
        _build(make_bundle, layout)
    assert not out.exists()


def test_a_prompt_that_no_longer_hashes_is_refused(make_bundle, layout):
    bundle = layout[0]
    _transcript(bundle / "m" / "C3" / "kiting" / "seed101.jsonl", "C3", "0" * 64)
    with pytest.raises(make_bundle.BundleError, match="C3"):
        _build(make_bundle, layout)
    assert not layout[3].exists()


def test_anything_key_shaped_is_refused(make_bundle, layout):
    bundle = layout[0]
    _transcript(
        bundle / "m" / "C2" / "kiting" / "seed102.jsonl",
        "C2",
        interface_fingerprint(get_interface("C2")),
        extra="my key is sk-or-v1-abcdef0123456789",
    )
    with pytest.raises(make_bundle.BundleError, match="seed102.jsonl"):
        _build(make_bundle, layout)
    assert not layout[3].exists()
