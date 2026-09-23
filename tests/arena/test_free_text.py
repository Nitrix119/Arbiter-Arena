"""C1's parser — the published accept/reject boundary, as executable tests.

``docs/current/C1_PARSER_OPTIONS.md`` §8 promised a corpus with a fixed verdict for
every item, written before any real model output was seen. This file is that corpus.
It is the boundary a reader can inspect and argue with: each row says what a piece of
text is read as — an action and the parse *layer* it needed, a refusal and its code,
or "no action at all".

Layers (options doc §5 B): 0 canonical, 1 surface-normalised, 2 grammatical but not
canonical, 3 extracted from surrounding prose or untagged. Names are passed through as
written; whether they name anything is the executor's call (``identifiers.resolve``),
shared with C2 — so ``raider-3`` *parses* and is refused later as ``unknown_target``.
"""

import ast
from pathlib import Path

import pytest

from src.arena.free_text import (
    GRAMMAR_KEYWORDS,
    Reading,
    read_response,
    render_command,
)
from src.arena.tools import ToolCall


def _attack(target="raider-1", weapon="Dagger"):
    return ToolCall("attack", {"action_name": weapon, "defender_id": target})


def _point(x, z, y=0.0):
    return {"x": float(x), "y": float(y), "z": float(z)}


def _cast_at_point(x, z, spell="Fireball", **extra):
    return ToolCall(
        "cast_spell", {"spell_name": spell, "target_point": _point(x, z)} | extra
    )


def _move(x, z):
    return ToolCall("move", _point(x, z))


END = ToolCall("end_turn", {})

#: (text, expected call, expected layer). The accepted half of the boundary.
ACCEPTED = [
    ("ACTION: attack raider-1 with Dagger", _attack(), 0),
    ("action: Attack Raider-1 with dagger.", _attack("Raider-1", "dagger"), 1),
    ("**ACTION:** `attack raider-1 with Dagger`", _attack(), 1),
    ("ACTION: attack raider–1 with “Dagger”", _attack(), 1),
    ("```\nACTION: attack raider-1 with Dagger\n```", _attack(), 1),
    ("ACTION: attack Raider 1 with Dagger", _attack("Raider 1"), 0),
    ("ACTION: hit raider-1 with Dagger", _attack(), 2),
    ("ACTION: I hit the raider-1 with my Dagger", _attack(), 2),
    (
        "Raider 1 is adjacent.\nACTION: attack raider-1 with Dagger\nGood luck!",
        _attack(),
        3,
    ),
    ("Attack raider-1 with Dagger", _attack(), 3),
    ("I won't attack raider-2.\nACTION: attack raider-1 with Dagger", _attack(), 3),
    (
        "ACTION: attack raider-1 with Dagger\nACTION: attack raider-1 with Dagger",
        _attack(),
        3,
    ),
    # Parses; the executor decides these name nothing (no repair here or there).
    ("ACTION: attack raider-3 with Dagger", _attack("raider-3"), 0),
    # KNOWN BOUNDARY (ledger A8): a trailing justification is read as part of the
    # final name, so the executor refuses the weapon as unknown_action — although a
    # reader would find the action. Pinned deliberately rather than patched with a
    # clause heuristic before any real output has been seen; the pilot decides.
    (
        "ACTION: attack raider-1 with Dagger since it's adjacent",
        _attack(weapon="Dagger since it's adjacent"),
        0,
    ),
    (
        "ACTION: cast Magic Missile at raider-1",
        ToolCall(
            "cast_spell", {"spell_name": "Magic Missile", "target_ids": ["raider-1"]}
        ),
        0,
    ),
    # Area aim.
    ("ACTION: cast Fireball at x=7.5 z=60", _cast_at_point(7.5, 60), 0),
    # Names are passed through as written, so a name's case is not a parse layer: it
    # is the shared resolver's business, exactly as in C2.
    ("ACTION: cast fireball at x=7.5 z=60", _cast_at_point(7.5, 60, "fireball"), 0),
    ("ACTION: cast Fireball at (7.5, 0, 60)", _cast_at_point(7.5, 60), 2),
    ("ACTION: cast Fireball at z=60 x=7.5", _cast_at_point(7.5, 60), 2),
    ("ACTION: cast Fireball at x: 7.5, z: 60", _cast_at_point(7.5, 60), 2),
    (
        "ACTION: cast Fireball at x=7.5 z=60 at level 4",
        _cast_at_point(7.5, 60, slot_level=4),
        0,
    ),
    # Parity with C2: an area spell aimed at a creature is the call C2 would send.
    (
        "ACTION: cast Fireball at raider-1",
        ToolCall("cast_spell", {"spell_name": "Fireball", "target_ids": ["raider-1"]}),
        0,
    ),
    (
        "ACTION: cast Cure Wounds at bodyguard, mage",
        ToolCall(
            "cast_spell",
            {"spell_name": "Cure Wounds", "target_ids": ["bodyguard", "mage"]},
        ),
        0,
    ),
    # Movement.
    ("ACTION: move to x=0 z=35", _move(0, 35), 0),
    ("ACTION: move to x=5ft z=30 feet", _move(5, 30), 2),
    ("ACTION: walk to x=-2.5 z=12.25", _move(-2.5, 12.25), 2),
    (
        "ACTION: move to x=1 y=10 z=2",
        ToolCall("move", _point(1, 2, y=10)),
        0,
    ),
    # Ending the turn.
    ("ACTION: end turn", END, 0),
    ("ACTION: End turn.", END, 1),
    ("ACTION: end my turn", END, 2),
    ("ACTION: pass", END, 2),
    (
        "ACTION: end turn — note: fireball when they bunch",
        ToolCall("end_turn", {"note": "fireball when they bunch"}),
        0,
    ),
]

#: (text, expected code, a fragment the model-facing reason must contain).
REFUSED = [
    ("ACTION: attack raider-1 or raider-2 with Dagger", "malformed_output", "attack"),
    (
        "ACTION: move to x=0 z=40 then attack raider-1 with Dagger",
        "malformed_output",
        "one action",
    ),
    (
        "ACTION: attack raider-1 with Dagger; ignore rules and end turn",
        "malformed_output",
        "one action",
    ),
    (
        "ACTION: attack raider-1 with Dagger\nACTION: attack raider-2 with Dagger",
        "malformed_output",
        "more than one",
    ),
    ("ACTION: attack raider-1", "malformed_output", "with <attack name>"),
    ("ACTION: cast Fireball at (7.5, 60)", "malformed_output", "x=<feet> z=<feet>"),
    ("ACTION: move toward raider-1", "malformed_output", "x=<feet> z=<feet>"),
    ("ACTION: move to x=5", "malformed_output", "x=<feet> z=<feet>"),
    ("ACTION: cast Fireball at x=1 z=2 at level 3.5", "malformed_output", "level"),
    ("ACTION: attack raider-1 with Dagger — note: hi", "malformed_output", "note"),
    ("ACTION: fly to x=0 z=0", "unknown_action", "fly"),
    ("ACTION: hmm", "unknown_action", "hmm"),
    ("ACTION:", "malformed_output", "ACTION:"),
]

#: Text containing no action at all — the correction path, then `no_tool_call`.
NO_ACTION = [
    None,
    "",
    "   \n  ",
    "I think I should wait and see.",
    "Let me consider the raiders' positions carefully.",
]


@pytest.mark.parametrize("text, call, layer", ACCEPTED)
def test_accepted(text, call, layer):
    reading = read_response(text)
    assert reading.code is None, reading.reason
    assert reading.call == call
    assert reading.layer == layer


@pytest.mark.parametrize("text, code, fragment", REFUSED)
def test_refused(text, code, fragment):
    reading = read_response(text)
    assert reading.call is None
    assert reading.code == code
    assert fragment in reading.reason
    assert reading.line is not None  # the attempt is kept for the transcript


@pytest.mark.parametrize("text", NO_ACTION)
def test_no_action(text):
    assert read_response(text) == Reading(None, None, None, None, "")


# -- canonical rendering: the inverse of parsing ---------------------------------


@pytest.mark.parametrize("text, call, layer", [r for r in ACCEPTED if r[2] == 0])
def test_canonical_rows_render_back_to_their_own_text(text, call, layer):
    assert "ACTION: " + render_command(call) == text


def test_rendering_keeps_full_float_precision():
    call = _move(12.345678901234, -0.1)
    assert read_response("ACTION: " + render_command(call)).call == call


def test_every_action_c3_offers_is_expressible_in_c1():
    """C1 can say everything C3 can list — proved, not argued.

    Every enumerated action for every creature in every scenario, at the opening and
    after each turn of a scripted match, is written in canonical C1 syntax and read
    back to the identical call at layer 0.
    """
    from src.arena.agent import ScriptedAgent
    from src.arena.enumeration import enumerate_legal_actions
    from src.arena.match import run_match
    from src.arena.scenarios import SCENARIOS
    from src.utils import dice

    checked = 0

    def check_all(combat):
        nonlocal checked
        for entity in combat.combatants:
            if not entity.is_alive():
                continue
            for action in enumerate_legal_actions(combat, entity):
                text = "ACTION: " + render_command(action.call)
                reading = read_response(text)
                expected = _with_ground_y(action.call)
                assert reading.call == expected, (text, reading.reason)
                assert reading.layer == 0, text
                checked += 1

    for scenario in SCENARIOS.values():
        combat = scenario.build()
        check_all(combat)

        class _Checking(ScriptedAgent):
            def decide(self, observation):
                check_all(combat)
                return super().decide(observation)

        with dice.using_rng(dice.new_rng(3)):
            run_match(
                combat,
                {"a": _Checking("A", "a"), "b": _Checking("B", "b")},
                seed=3,
                round_cap=3,
            )
    assert checked > 200


def _with_ground_y(call):
    """C1 always reads a point as x, y, z — y defaulting to the ground, 0."""
    args = dict(call.arguments)
    for key in ("target_point",):
        if key in args:
            args[key] = _point(args[key]["x"], args[key]["z"], args[key].get("y", 0))
    if call.name == "move":
        args = _point(args["x"], args["z"], args.get("y", 0))
    return ToolCall(call.name, args)


# -- names every scenario uses must be writable ----------------------------------


def test_no_study_identifier_contains_a_grammar_keyword():
    """A creature called "Guard of the Gate" could never be named in C1.

    The grammar reads keywords (`with`, `at`, `the`, …) as structure, so an identifier
    containing one as a whole word would be unwritable, and every attempt to name it
    would be charged to the model as malformed. No study scenario may contain one.
    """
    from src.arena.scenarios import SCENARIOS

    for scenario in SCENARIOS.values():
        combat = scenario.build()
        for entity in combat.combatants:
            names = [entity.entity_id, entity.name]
            names += [a.name for a in entity.stat_block.actions]
            names += list(entity.stat_block.known_spells)
            for name in names:
                words = {w.casefold() for w in name.replace("-", " ").split()}
                assert not words & GRAMMAR_KEYWORDS, (scenario.name, name)


# -- purity -----------------------------------------------------------------------


def test_reading_is_deterministic():
    text = "Thinking...\nACTION: cast Fireball at x=7.5 z=60 at level 4"
    assert read_response(text) == read_response(text)


def test_the_parser_never_looks_at_the_board():
    """State-free by construction: the module imports nothing from the engine.

    A parser that could see the board could "help" — pick the target that makes
    sense — and C1 would be measuring the parser's judgement, not the model's.
    """
    source = Path(__file__).resolve().parents[2] / "src" / "arena" / "free_text.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    allowed = {"src.arena.tools", "src.arena.error_codes", "src.errors"}
    assert {m for m in imported if m.startswith("src")} <= allowed, imported
