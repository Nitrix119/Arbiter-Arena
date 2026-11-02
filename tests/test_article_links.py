"""The article's images must survive being read elsewhere.

The article is published off-site, so its images are absolute URLs into this
repository. Pointing them at a branch means they can break whenever files move, and
mixing refs means a reader sees figures from different releases, so they all share
one release tag. The tag has to be created when the release is cut, or they 404.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ARTICLE = ROOT / "docs" / "ARTICLE.md"

IMAGE_URL = re.compile(
    r"https://raw\.githubusercontent\.com/Nitrix119/Arbiter-Arena/([^/]+)/([^)\s]+)"
)


def _images() -> list[tuple[str, str]]:
    return IMAGE_URL.findall(ARTICLE.read_text(encoding="utf-8"))


def test_article_has_images():
    # Guard against the regex silently matching nothing, which would make the
    # tests below pass vacuously.
    assert _images()


def test_images_share_one_release_tag():
    refs = {ref for ref, _ in _images()}
    assert len(refs) == 1, f"images use several refs: {sorted(refs)}"
    assert re.fullmatch(r"v\d+\.\d+\.\d+", refs.pop())


def test_every_image_exists():
    missing = [path for _, path in _images() if not (ROOT / path).is_file()]
    assert missing == []
