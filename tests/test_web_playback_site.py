"""The playback page as a self-contained static site.

The same page is served two ways: by FastAPI at ``/playback``, and as static files on
GitHub Pages under a sub-path (``/Arbiter-Arena/``), where readers can watch the
featured matches without cloning anything. Both only work if every asset path is
relative, so these tests pin that, check that every asset the page names is really
served, and check that the featured-match list only names transcripts that exist
and load. Which match opens first is checked under node
(``tests/js/playback_check.mjs``).
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from web.app import app

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "web" / "templates" / "playback.html"
STATIC = ROOT / "web" / "static"
MATCHES = STATIC / "matches"
FEATURED = MATCHES / "featured.json"
PLAYBACK_JS = STATIC / "js" / "playback.js"

ASSET_ATTR = re.compile(r'\b(?:src|href)="([^"#?]+)"')


@pytest.fixture
def client():
    return TestClient(app)


def _assets() -> list[str]:
    return ASSET_ATTR.findall(TEMPLATE.read_text(encoding="utf-8"))


def test_page_names_assets():
    # Guard against the regex silently matching nothing, which would make the
    # tests below pass vacuously.
    assert {"static/css/playback.css", "static/js/playback.js"} <= set(_assets())


def test_asset_paths_are_relative():
    # A root-absolute path ("/static/...") breaks under the GitHub Pages sub-path.
    absolute = [a for a in _assets() if a.startswith("/")]
    assert absolute == [], f"root-absolute asset paths: {absolute}"


def test_script_fetches_relative_paths():
    js = PLAYBACK_JS.read_text(encoding="utf-8")
    assert "'/static/" not in js and "`/static/" not in js


@pytest.mark.parametrize("asset", _assets())
def test_every_asset_is_served(client, asset):
    # Resolved against /playback, a relative "static/x" is requested as /static/x.
    assert client.get("/" + asset).status_code == 200


def _featured() -> list[dict]:
    return json.loads(FEATURED.read_text(encoding="utf-8"))


def test_featured_list_is_well_formed():
    featured = _featured()
    assert featured, "the featured list must not be empty"
    files = [m["file"] for m in featured]
    assert len(files) == len(set(files)), "duplicate featured file"
    for m in featured:
        assert set(m) == {"file", "label"}, m
        assert re.fullmatch(r"[\w.+-]+\.jsonl", m["file"]), m["file"]
        assert m["label"].strip()


@pytest.mark.parametrize("entry", _featured(), ids=lambda m: m["file"])
def test_featured_match_exists_and_parses(client, entry):
    path = MATCHES / entry["file"]
    assert path.is_file(), f"featured match missing: {entry['file']}"
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert lines and all(isinstance(json.loads(ln), dict) for ln in lines)
    assert client.get(f"/static/matches/{entry['file']}").status_code == 200


def test_featured_list_is_served(client):
    assert client.get("/static/matches/featured.json").status_code == 200


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_initial_match_choice(tmp_path):
    shutil.copy(STATIC / "js" / "playback-data.js", tmp_path / "playback-data.mjs")
    check = ROOT / "tests" / "js" / "playback_check.mjs"
    shutil.copy(check, tmp_path / "playback_check.mjs")
    result = subprocess.run(
        ["node", str(tmp_path / "playback_check.mjs")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
