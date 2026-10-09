"""Pack the study's release bundle: everything a reader needs to check the results.

    python tools/make_bundle.py results/final --version 1.0.0 \\
        --out dist/arbiter-arena-study-1.0.0.zip

The zip unzips into the repository root: ``results/final/`` and ``audit/`` land where
the documented ``study verify``, ``study report`` and ``audit score`` commands expect
them, and ``study-bundle/`` holds the prompts, both versions of the pre-registration,
a README and ``SHA256SUMS``.

It refuses to write anything, naming the cause, when:

- the audit is incomplete (it cannot be re-scored without all of its files);
- a condition's prompt, rebuilt from today's code, no longer hashes to what the
  transcripts recorded (the exported text would not be the text the models saw);
- any file contains a key-shaped string (the same patterns the recorder scrubs).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.arena.audit import (  # noqa: E402
    AUDIT_REPORT,
    ITEMS,
    KEY,
    LABELS,
    POPULATION,
)
from src.arena.interfaces import get_interface  # noqa: E402
from src.arena.llm_common import augment_tools_with_notes  # noqa: E402
from src.arena.manifest import interface_fingerprint  # noqa: E402
from src.arena.telemetry import scrub  # noqa: E402

AUDIT_FILES = (ITEMS, KEY, LABELS, POPULATION, AUDIT_REPORT)
BUNDLE_DIR = "study-bundle"
SUMS = f"{BUNDLE_DIR}/SHA256SUMS"
PREREG_PATH = "docs/current/PREREGISTRATION.md"
FREEZE_TAG = "study-freeze"


class BundleError(Exception):
    """The bundle cannot be built as asked; the message names the cause."""


def _recorded_prompt_hashes(bundle: Path) -> Dict[str, Set[str]]:
    """Each condition's prompt hashes, as the transcripts' ``match_start`` recorded."""
    recorded: Dict[str, Set[str]] = {}
    for path in sorted(bundle.rglob("seed*.jsonl")):
        with open(path, encoding="utf-8") as handle:
            start = json.loads(handle.readline())
        if start.get("prompt_hash") is None:  # a native baseline sees no prompt
            continue
        recorded.setdefault(start["condition"], set()).add(start["prompt_hash"])
    return recorded


def _prompt_document(condition: str, digest: str) -> str:
    interface = get_interface(condition)
    tools = augment_tools_with_notes(interface.api_tools({}))
    return (
        f"# Condition {condition}: what the model was shown\n\n"
        f"Fingerprint (`interface_fingerprint`, recorded as `prompt_hash` in every "
        f"transcript): `{digest}`\n\n"
        "## System prompt\n\n"
        f"```text\n{interface.system_prompt()}\n```\n\n"
        "## Tools\n\n"
        f"```json\n{json.dumps(tools, indent=2, sort_keys=True, default=str)}\n```\n"
    )


def _prompts(bundle: Path) -> Dict[str, str]:
    """One document per condition, refused if today's code would hash differently."""
    documents: Dict[str, str] = {}
    for condition, hashes in sorted(_recorded_prompt_hashes(bundle).items()):
        current = interface_fingerprint(get_interface(condition))
        if hashes != {current}:
            raise BundleError(
                f"condition {condition}: transcripts recorded prompt hash(es) "
                f"{sorted(hashes)}, but today's code gives {current}. Export the "
                f"prompts from the commit the bundle was run at."
            )
        documents[condition] = _prompt_document(condition, current)
    return documents


def _readme(bundle: Path, version: str, prompts: Dict[str, str]) -> str:
    transcripts = len(list(bundle.rglob("seed*.jsonl")))
    conditions = ", ".join(sorted(prompts))
    return f"""\
# Arbiter Arena {version}: the action-interface study bundle

The complete data behind the study: {transcripts} match transcripts, the report
generated from them, the blind C1 parser audit, the prompts every condition was shown
({conditions}), and the pre-registration.

## Contents

- `results/{bundle.name}/`: one JSONL transcript per match
  (`<model>/<condition>/<scenario>/seed<n>.jsonl`), the grid it was run from
  (`grid.toml`), the run log, and `report/` (`summary.md` and its CSVs).
- `audit/`: the 200-item blind audit. `items.jsonl` is what the labeller saw,
  `labels.jsonl` their labels, `key.jsonl` the parser's sealed verdicts, and
  `audit_report.md` the score.
- `{BUNDLE_DIR}/prompts/`: each condition's system prompt and tool schemas, with the
  fingerprint every transcript recorded. The bundle tool refuses to export a prompt
  that no longer hashes to that value.
- `{BUNDLE_DIR}/PREREGISTRATION_at_freeze.md`: the pre-registration at the
  `{FREEZE_TAG}` tag, before any confirmatory data.
- `{BUNDLE_DIR}/PREREGISTRATION.md`: the same document at release, with every later
  deviation dated in its §10.
- `{BUNDLE_DIR}/SHA256SUMS`: a checksum for every other file in the zip.

## Reproduce the results

Unzip into the root of a clone of the repository, then:

```
pip install -e ".[web,dev]"
python -m src.arena.study verify results/{bundle.name}    # must print 100.0%
python -m src.arena.study report results/{bundle.name}    # rewrites report/ identically
python -m src.arena.audit score audit/ --report results/{bundle.name}/report
```

To read one match decision by decision, pass a transcript to
`python -m src.arena.study show`.

Every transcript records the commit it was run at; the bundle was run at the
`{FREEZE_TAG}` tag. Verification and the report need no API key and make no network
calls.

## Licence

Released with the repository under Apache-2.0; see its `LICENSE` and `NOTICE`.
"""


def _members(
    bundle: Path,
    audit: Path,
    prereg: Path,
    frozen_prereg: str,
    version: str,
) -> Dict[str, bytes]:
    """Every file in the zip, by its name in the zip, before any is written."""
    missing = [name for name in AUDIT_FILES if not (audit / name).is_file()]
    if missing:
        raise BundleError(
            f"the audit in {audit} is incomplete: missing {', '.join(missing)}"
        )
    prompts = _prompts(bundle)

    members: Dict[str, bytes] = {}
    for path in sorted(p for p in bundle.rglob("*") if p.is_file()):
        rel = path.relative_to(bundle).as_posix()
        members[f"results/{bundle.name}/{rel}"] = path.read_bytes()
    for name in AUDIT_FILES:
        members[f"audit/{name}"] = (audit / name).read_bytes()
    for condition, document in prompts.items():
        members[f"{BUNDLE_DIR}/prompts/{condition}.md"] = document.encode("utf-8")
    members[f"{BUNDLE_DIR}/PREREGISTRATION.md"] = prereg.read_bytes()
    members[f"{BUNDLE_DIR}/PREREGISTRATION_at_freeze.md"] = frozen_prereg.encode(
        "utf-8"
    )
    members[f"{BUNDLE_DIR}/README.md"] = _readme(bundle, version, prompts).encode(
        "utf-8"
    )

    for name, data in members.items():
        text = data.decode("utf-8", errors="replace")
        if scrub(text) != text:
            raise BundleError(f"{name} contains a key-shaped string; nothing written")
    return members


def build_bundle(
    bundle: Path,
    audit: Path,
    out: Path,
    *,
    prereg: Path,
    frozen_prereg: str,
    version: str,
) -> List[str]:
    """Write the zip to *out* and return its member names, or raise BundleError."""
    members = _members(bundle, audit, prereg, frozen_prereg, version)
    sums = "".join(
        f"{hashlib.sha256(data).hexdigest()}  {name}\n"
        for name, data in sorted(members.items())
    )
    members[SUMS] = sums.encode("utf-8")
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for name, data in sorted(members.items()):
            z.writestr(name, data)
    return sorted(members)


def _at_tag(tag: str, path: str) -> str:
    result = subprocess.run(
        ["git", "show", f"{tag}:{path}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise BundleError(f"cannot read {path} at {tag}: {result.stderr.strip()}")
    return result.stdout


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("bundle", type=Path, help="a study bundle, e.g. results/final")
    parser.add_argument("--audit", type=Path, default=Path("audit"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--version", required=True, help="the release, e.g. 1.0.0")
    args = parser.parse_args(argv)
    try:
        names = build_bundle(
            args.bundle,
            args.audit,
            args.out,
            prereg=ROOT / PREREG_PATH,
            frozen_prereg=_at_tag(FREEZE_TAG, PREREG_PATH),
            version=args.version,
        )
    except BundleError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(f"wrote {args.out} ({len(names)} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
