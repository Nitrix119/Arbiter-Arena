"""What a transcript must say about itself to be a study result.

A match in the action-interface grid is one cell of *condition × scenario × seed ×
model*. Reading a transcript back — months later, from a published bundle, by a stranger
— only works if the file says which cell it is and what code produced it. Today's
``match_start`` records the roster and the round cap, which identifies the fight but not
the experiment.

Two things live here, because both are about a transcript being self-describing:

* :class:`Manifest` — the cell's identity, merged into ``match_start``.
* :func:`state_hash` — a canonical fingerprint of one ground-truth state snapshot,
  written at every ``turn_end``. ``ReplayVerifier`` re-executes a match's recorded
  actions under the same seed and compares these; an equal sequence is what "this
  transcript replays" means.

**Why the hash normalises numbers.** Movement is continuous feet, and repeated
subtraction drifts in binary floating point (30 → 22.9 → 15.799999999999999 — the real
bug found on 2026-09-19). Two runs that *are* the same battle must not hash differently
because one arrived at a value by a different arithmetic route, so every float is
rounded to the engine's own ``FEET_DP`` before hashing, and an integral float hashes as
its integer.
"""

import hashlib
import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from src.models.action_resources import FEET_DP

#: Schema versions stamped into every manifest. Bump one when its shape changes, so a
#: bundle mixing versions is detectable rather than silently misread.
OBSERVATION_SCHEMA = "observation.v1"
LEGAL_ACTION_SCHEMA = "legal_action.v1"
MATCH_RECORD_SCHEMA = "match_record.v1"

SCHEMA_VERSIONS: Dict[str, str] = {
    "observation": OBSERVATION_SCHEMA,
    "legal_action": LEGAL_ACTION_SCHEMA,
    "match_record": MATCH_RECORD_SCHEMA,
}

_REPO_ROOT = Path(__file__).resolve().parents[2]


def git_commit(root: Optional[Path] = None) -> Optional[str]:
    """The current commit sha, or ``None`` when that cannot be determined.

    A transcript should name the code that produced it, but a published bundle
    unpacked outside a checkout is a perfectly ordinary situation — so this reports
    "unknown" rather than raising and taking a match down with it.
    """
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(root or _REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None if out.returncode == 0 else None


def prompt_hash(*parts: str) -> str:
    """A stable fingerprint of the prompt text a match was run with.

    §3.1 requires every prompt variant to be hashed: the conditions differ *only* in
    their action section, so the hash is the evidence that nothing else drifted
    between cells.
    """
    digest = hashlib.sha256()
    for part in parts:
        digest.update(part.encode("utf-8"))
        digest.update(b"\x00")  # unambiguous separator, so ("ab","c") != ("a","bc")
    return digest.hexdigest()


@dataclass
class Manifest:
    """Everything needed to place one transcript in the experimental grid.

    Every field is optional: a bare functionality match (scripted vs scripted, no
    model) should still log, and absent keys are omitted rather than written as
    ``null``.
    """

    commit: Optional[str] = None
    scenario: Optional[str] = None
    seed: Optional[int] = None
    condition: Optional[str] = None
    model: Optional[str] = None
    temperature: Optional[float] = None
    prompt_hash: Optional[str] = None
    schema_versions: Dict[str, str] = field(
        default_factory=lambda: dict(SCHEMA_VERSIONS)
    )

    @classmethod
    def for_run(cls, **fields: Any) -> "Manifest":
        """Build a manifest, resolving the commit from the working tree by default."""
        fields.setdefault("commit", git_commit())
        return cls(**fields)

    def to_dict(self) -> Dict[str, Any]:
        """The manifest as a ``match_start`` payload, without its empty fields.

        ``seed`` is deliberately **not** emitted: ``match_start`` already writes the
        seed the match actually ran under, and two copies of one fact can disagree.
        The field stays on the dataclass because the batch runner names cells with
        it.
        """
        data: Dict[str, Any] = {
            "commit": self.commit,
            "scenario": self.scenario,
            "condition": self.condition,
            "model": self.model,
            "temperature": self.temperature,
            "prompt_hash": self.prompt_hash,
        }
        present = {k: v for k, v in data.items() if v is not None}
        present["schema_versions"] = dict(self.schema_versions)
        return present


def _canonical(value: Any) -> Any:
    """Normalise *value* so equal states have one encoding.

    Floats are rounded to the engine's foot precision and integral results collapse to
    ``int``, so ``30``, ``30.0`` and a drifted ``29.999999999999996`` all agree.
    """
    if isinstance(value, bool):  # before the int check — bool is an int subclass
        return value
    if isinstance(value, float):
        rounded = round(value, FEET_DP)
        return int(rounded) if rounded == int(rounded) else rounded
    if isinstance(value, dict):
        return {k: _canonical(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    return value


def canonical_json(state: Dict[str, Any]) -> str:
    """*state* as canonical JSON — sorted keys, fixed separators, normalised numbers."""
    return json.dumps(
        _canonical(state), sort_keys=True, separators=(",", ":"), default=str
    )


def state_hash(state: Dict[str, Any]) -> str:
    """A sha256 fingerprint of one ground-truth snapshot.

    Takes the output of :func:`~src.arena.observation.snapshot_state` — ground truth,
    not any agent's filtered view — so the fingerprint is of the battle, not of what
    someone was allowed to see.
    """
    return hashlib.sha256(canonical_json(state).encode("utf-8")).hexdigest()
