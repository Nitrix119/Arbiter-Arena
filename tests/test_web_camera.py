"""The board camera's maths, shared by the battle and playback pages.

The functions live in ``web/static/js/camera.js``, so they are checked under node
(``tests/js/camera_check.mjs``): zoom keeps the point under the cursor fixed, and the
playback fit lands the whole match in the area the panels leave uncovered, which is
the bug that hid tokens beneath them in 1.0.0. Skipped where node is not installed;
GitHub's runners have it.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CAMERA = ROOT / "web" / "static" / "js" / "camera.js"
CHECKS = ROOT / "tests" / "js" / "camera_check.mjs"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_camera_maths(tmp_path):
    shutil.copy(CAMERA, tmp_path / "camera.mjs")
    shutil.copy(CHECKS, tmp_path / "camera_check.mjs")
    result = subprocess.run(
        ["node", str(tmp_path / "camera_check.mjs")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "all checks pass" in result.stdout


def test_both_pages_use_the_shared_camera():
    # One zoom implementation, not two: the playback page once had none at all.
    for page in ("input.js", "playback.js"):
        source = (ROOT / "web" / "static" / "js" / page).read_text(encoding="utf-8")
        assert "from './camera.js'" in source, page
        assert "zoomAt(camera" in source, page
