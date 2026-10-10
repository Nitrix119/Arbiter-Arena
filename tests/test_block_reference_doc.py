"""The block reference doc is generated from the registry and must not drift.

docs/current/BLOCK_REFERENCE.md is rendered from the live block REGISTRY (each handler's
docstring + its BlockContract), so the authoring docs cannot fall behind the code
the loader validates against. If this fails, regenerate with:

    python -m src.spells.reference
"""

import os

from src.spells.reference import generate_block_reference, BLOCK_REFERENCE_PATH
from src.spells.registry import REGISTRY

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")


def _checked_in() -> str:
    path = os.path.join(REPO_ROOT, BLOCK_REFERENCE_PATH)
    assert os.path.exists(path), (
        f"{BLOCK_REFERENCE_PATH} is missing; generate it with "
        f"'python -m src.spells.reference'"
    )
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def test_block_reference_is_up_to_date():
    assert _checked_in() == generate_block_reference(), (
        "BLOCK_REFERENCE.md is out of date with the registry; regenerate with "
        "'python -m src.spells.reference'"
    )


def test_every_registered_block_is_documented():
    doc = _checked_in()
    for block_type in REGISTRY.types():
        assert f"## `{block_type}`" in doc, f"{block_type} missing from the reference"


def test_every_block_has_a_summary():
    """A block with no docstring would render '(undocumented)' — catch it here
    rather than shipping a reference with a hole in it."""
    assert "_(undocumented)_" not in _checked_in()


def test_every_event_and_its_fields_are_documented():
    # A trigger's event.<field> is checked at load against event_fields(), so the
    # reference must say which fields each event carries.
    from src.combat.event_data import event_fields
    from src.combat.events import EventType

    doc = _checked_in()
    events = doc.split("## Events", 1)[1].split("\n## ", 1)[0]
    for event_type in EventType:
        line = next(
            (ln for ln in events.splitlines() if f"`{event_type.name}`" in ln), None
        )
        assert line is not None, f"{event_type.name} missing from the reference"
        for field in event_fields(event_type):
            assert f"`{field}`" in line, f"{event_type.name}.{field} undocumented"


def test_every_context_key_is_documented():
    from src.spells.context import CONTEXT_KEYS

    doc = _checked_in()
    keys = doc.split("## Context keys", 1)[1].split("\n## ", 1)[0]
    for key in CONTEXT_KEYS:
        assert f"| `{key}` |" in keys, f"context.{key} missing from the reference"


def test_every_context_key_but_the_slot_has_a_declared_writer():
    # A block that writes a key without declaring it leaves the reference saying
    # nothing writes it (attack_roll's attack_cancelled/had_advantage did).
    from src.spells.context import CONTEXT_KEYS

    declared = {k for t in REGISTRY.types() for k in REGISTRY.get(t).contract.writes}
    assert CONTEXT_KEYS - declared == {"slot_level"}
