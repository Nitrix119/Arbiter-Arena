"""Every rejection carries the right taxonomy code — proven by real refusals.

The study (``docs/current/V1_PLAN.md`` §3.4) groups invalid actions by code, so a
mislabelled or missing code corrupts the headline measurement rather than crashing
anything. Two kinds of test guard that:

* **Per-code execution tests** drive a live ``CombatSystem`` into each refusal and
  assert the code the executor returns. Asserting the declared table would prove
  nothing (CLAUDE.md §4 — test behaviour, not structure).
* **A drift test** AST-parses the engine for ``RuleViolation(CODE, ...)`` raise sites
  and compares both directions against the declared taxonomy, so a code nothing raises
  and a raise nothing declares each fail loudly (CLAUDE.md §9, 2026-09-03: a
  declaration nobody verifies is a comment).
"""

import ast
from pathlib import Path

from src import errors as engine_errors
from src.arena import error_codes as codes
from src.arena.tools import ToolCall, ToolExecutor
from src.errors import ENGINE_ERROR_CODES
from src.models.action_resources import ActionCost

from .conftest import force_turn, melee_attack, ranged_attack, single_target_spell

_SRC = Path(__file__).resolve().parents[2] / "src"
#: Packages whose refusals the arena reads back as taxonomy codes.
_ENGINE_PACKAGES = ("combat", "spatial", "models")


def _started(make_combat, entities, focus, registry=None):
    combat = make_combat(entities, registry=registry)
    combat.start_combat()
    force_turn(combat, focus)
    return combat


def _code(combat, actor, call) -> str:
    result = ToolExecutor(combat).apply(actor, call)
    assert result["ok"] is False, f"expected a refusal, got {result}"
    return result["code"]


# -- engine-raised codes -----------------------------------------------------


def test_out_of_range(make_entity, make_combat):
    fighter = make_entity("Fighter", team="a", pos=(0, 0, 0), attacks=[melee_attack()])
    goblin = make_entity("Goblin", team="b", pos=(100, 0, 0))
    combat = _started(make_combat, [fighter, goblin], fighter)

    assert (
        _code(
            combat,
            fighter,
            ToolCall(
                "attack",
                {"action_name": "Longsword", "defender_id": goblin.entity_id},
            ),
        )
        == "out_of_range"
    )


def test_destination_blocked(make_entity, make_combat):
    fighter = make_entity("Fighter", team="a", pos=(0, 0, 0))
    goblin = make_entity("Goblin", team="b", pos=(10, 0, 0))
    combat = _started(make_combat, [fighter, goblin], fighter)

    # Move onto the goblin's own square — the bounding boxes overlap.
    assert (
        _code(combat, fighter, ToolCall("move", {"x": 10.0, "z": 0.0}))
        == "destination_blocked"
    )


def test_insufficient_resource_when_movement_is_spent(make_entity, make_combat):
    fighter = make_entity("Fighter", team="a", pos=(0, 0, 0))
    goblin = make_entity("Goblin", team="b", pos=(200, 0, 0))
    combat = _started(make_combat, [fighter, goblin], fighter)
    fighter.resources.movement = 5.0

    assert (
        _code(combat, fighter, ToolCall("move", {"x": 100.0, "z": 0.0}))
        == "insufficient_resource"
    )


def test_action_economy_spent_is_distinct_from_a_spent_consumable(
    make_entity, make_combat
):
    """A used-up action and a used-up consumable are different failures.

    Both are "cannot afford"; the study counts them apart, because an agent that has
    already attacked this turn made a very different mistake from one that ran out of
    feet.
    """
    fighter = make_entity("Fighter", team="a", pos=(0, 0, 0), attacks=[melee_attack()])
    goblin = make_entity("Goblin", team="b", pos=(5, 0, 0))
    combat = _started(make_combat, [fighter, goblin], fighter)
    fighter.spend_resources(ActionCost(actions=1))  # already acted

    assert (
        _code(
            combat,
            fighter,
            ToolCall(
                "attack",
                {"action_name": "Longsword", "defender_id": goblin.entity_id},
            ),
        )
        == "action_economy_spent"
    )


def test_not_your_turn(make_entity, make_combat):
    fighter = make_entity("Fighter", team="a", pos=(0, 0, 0), attacks=[melee_attack()])
    goblin = make_entity("Goblin", team="b", pos=(5, 0, 0))
    combat = _started(make_combat, [fighter, goblin], goblin)  # goblin's turn

    assert (
        _code(
            combat,
            fighter,
            ToolCall(
                "attack",
                {"action_name": "Longsword", "defender_id": goblin.entity_id},
            ),
        )
        == "not_your_turn"
    )


def test_unknown_action_for_an_attack_the_actor_lacks(make_entity, make_combat):
    fighter = make_entity("Fighter", team="a", pos=(0, 0, 0), attacks=[melee_attack()])
    goblin = make_entity("Goblin", team="b", pos=(5, 0, 0))
    combat = _started(make_combat, [fighter, goblin], fighter)

    assert (
        _code(
            combat,
            fighter,
            ToolCall(
                "attack", {"action_name": "Fireball", "defender_id": goblin.entity_id}
            ),
        )
        == "unknown_action"
    )


def test_unknown_action_for_a_spell_the_actor_does_not_know(
    make_entity, make_combat, registry_with
):
    spell = single_target_spell("Firebolt")
    wizard = make_entity("Wizard", team="a", pos=(0, 0, 0), spellcasting_ability="int")
    goblin = make_entity("Goblin", team="b", pos=(20, 0, 0))
    combat = _started(
        make_combat, [wizard, goblin], wizard, registry=registry_with(spell)
    )

    assert (
        _code(
            combat,
            wizard,
            ToolCall(
                "cast_spell",
                {"spell_name": "Firebolt", "target_ids": [goblin.entity_id]},
            ),
        )
        == "unknown_action"
    )


def test_unknown_target_for_a_hallucinated_entity_id(make_entity, make_combat):
    fighter = make_entity("Fighter", team="a", pos=(0, 0, 0), attacks=[melee_attack()])
    goblin = make_entity("Goblin", team="b", pos=(5, 0, 0))
    combat = _started(make_combat, [fighter, goblin], fighter)

    assert (
        _code(
            combat,
            fighter,
            ToolCall("attack", {"action_name": "Longsword", "defender_id": "no-such"}),
        )
        == "unknown_target"
    )


def test_unknown_target_for_a_hallucinated_move_option(make_entity, make_combat):
    fighter = make_entity("Fighter", team="a", pos=(0, 0, 0))
    goblin = make_entity("Goblin", team="b", pos=(50, 0, 0))
    combat = _started(make_combat, [fighter, goblin], fighter)

    assert (
        _code(combat, fighter, ToolCall("move", {"option_id": "invented:xyz"}))
        == "unknown_target"
    )


def test_insufficient_resource_when_a_spell_slot_is_gone(
    make_entity, make_combat, registry_with
):
    spell = single_target_spell("Magic Missile", spell_level=1)
    wizard = make_entity(
        "Wizard",
        team="a",
        pos=(0, 0, 0),
        known_spells=["Magic Missile"],
        spellcasting_ability="int",
        spell_slot_defaults={1: 1},
    )
    goblin = make_entity("Goblin", team="b", pos=(20, 0, 0))
    combat = _started(
        make_combat, [wizard, goblin], wizard, registry=registry_with(spell)
    )
    wizard.spell_slots.remaining[1] = 0

    assert (
        _code(
            combat,
            wizard,
            ToolCall(
                "cast_spell",
                {"spell_name": "Magic Missile", "target_ids": [goblin.entity_id]},
            ),
        )
        == "insufficient_resource"
    )


def test_invalid_target_relation_for_a_slot_below_the_spells_level(
    make_entity, make_combat, registry_with
):
    spell = single_target_spell("Magic Missile", spell_level=2)
    wizard = make_entity(
        "Wizard",
        team="a",
        pos=(0, 0, 0),
        known_spells=["Magic Missile"],
        spellcasting_ability="int",
        spell_slot_defaults={1: 2, 2: 2},
    )
    goblin = make_entity("Goblin", team="b", pos=(20, 0, 0))
    combat = _started(
        make_combat, [wizard, goblin], wizard, registry=registry_with(spell)
    )

    assert (
        _code(
            combat,
            wizard,
            ToolCall(
                "cast_spell",
                {
                    "spell_name": "Magic Missile",
                    "target_ids": [goblin.entity_id],
                    "slot_level": 1,
                },
            ),
        )
        == "invalid_target_relation"
    )


# -- arena-raised codes ------------------------------------------------------


def test_unknown_action_for_a_tool_that_does_not_exist(make_entity, make_combat):
    fighter = make_entity("Fighter", team="a", pos=(0, 0, 0))
    goblin = make_entity("Goblin", team="b", pos=(5, 0, 0))
    combat = _started(make_combat, [fighter, goblin], fighter)

    assert _code(combat, fighter, ToolCall("teleport", {})) == "unknown_action"


def test_malformed_output_for_a_missing_required_argument(make_entity, make_combat):
    """A missing argument is the model's formatting failure, not a refused rule.

    It also must not escape as a bare ``KeyError`` — the turn driver feeds the error
    text back to the model, and a stray traceback is not feedback.
    """
    fighter = make_entity("Fighter", team="a", pos=(0, 0, 0), attacks=[melee_attack()])
    goblin = make_entity("Goblin", team="b", pos=(5, 0, 0))
    combat = _started(make_combat, [fighter, goblin], fighter)

    assert (
        _code(combat, fighter, ToolCall("attack", {"action_name": "Longsword"}))
        == "malformed_output"
    )


def test_malformed_output_for_a_move_with_no_destination(make_entity, make_combat):
    fighter = make_entity("Fighter", team="a", pos=(0, 0, 0))
    goblin = make_entity("Goblin", team="b", pos=(50, 0, 0))
    combat = _started(make_combat, [fighter, goblin], fighter)

    assert _code(combat, fighter, ToolCall("move", {})) == "malformed_output"


def test_untyped_engine_refusal_falls_back_without_escaping(make_entity, make_combat):
    """An engine ``ValueError`` with no code is bucketed, not crashed on.

    ``engine_error`` should stay at zero in a real run; it exists so that an untyped
    refusal path shows up in the metrics instead of silently joining a real category.
    """
    fighter = make_entity("Fighter", team="a", pos=(0, 0, 0), attacks=[melee_attack()])
    goblin = make_entity("Goblin", team="b", pos=(5, 0, 0))
    combat = _started(make_combat, [fighter, goblin], fighter)

    def _boom(*args, **kwargs):
        raise ValueError("something the engine cannot model")

    combat.resolve_attack = _boom  # type: ignore[method-assign]

    result = ToolExecutor(combat).apply(
        fighter,
        ToolCall(
            "attack", {"action_name": "Longsword", "defender_id": goblin.entity_id}
        ),
    )
    assert result["ok"] is False
    assert result["code"] == codes.ENGINE_ERROR
    assert "cannot model" in result["error"]


# -- the declaration is checked against the code ------------------------------


def _resolve(node: ast.AST, tree: ast.Module, where: str) -> set:
    """Resolve one code expression to the set of codes it can produce.

    Three forms are readable, and nothing else is allowed: a string literal; a
    constant name imported from :mod:`src.errors`; or a call to a helper *defined in
    the same module* that returns nothing but those. Following the helper keeps the
    guard complete — ``_shortfall_code`` picks between two codes, and a guard that
    shrugged at it would quietly stop covering the two most common refusals.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {node.value}

    if isinstance(node, ast.Name):
        value = getattr(engine_errors, node.id, None)
        assert isinstance(value, str), (
            f"{where}: RuleViolation code {node.id!r} is not a string constant "
            "declared in src/errors.py."
        )
        return {value}

    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        helper = next(
            (
                f
                for f in ast.walk(tree)
                if isinstance(f, ast.FunctionDef) and f.name == node.func.id
            ),
            None,
        )
        assert helper is not None, (
            f"{where}: RuleViolation code comes from {node.func.id!r}, which is not "
            "defined in this module; the drift guard cannot follow it."
        )
        returns = [
            r.value
            for r in ast.walk(helper)
            if isinstance(r, ast.Return) and r.value is not None
        ]
        assert returns, f"{where}: {node.func.id!r} returns no code."
        found: set = set()
        for value in returns:
            found |= _resolve(value, tree, where)
        return found

    raise AssertionError(
        f"{where}: RuleViolation raised with a code the drift guard cannot read. "
        "Use a literal, a constant from src/errors.py, or a helper in this module "
        "that returns only those."
    )


def _raised_codes() -> set:
    """Every code the engine can pass as ``RuleViolation``'s first argument.

    Reads the source rather than importing it, so a raise site on a path no test
    happens to execute still counts.
    """
    found: set = set()
    for package in _ENGINE_PACKAGES:
        for path in (_SRC / package).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Raise) or node.exc is None:
                    continue
                exc = node.exc
                if not isinstance(exc, ast.Call):
                    continue
                if not isinstance(exc.func, ast.Name) or exc.func.id != "RuleViolation":
                    continue
                assert exc.args, f"{path}:{node.lineno}: RuleViolation needs a code."
                found |= _resolve(exc.args[0], tree, f"{path}:{node.lineno}")
    return found


def test_every_raised_engine_code_is_declared():
    undeclared = _raised_codes() - ENGINE_ERROR_CODES
    assert not undeclared, (
        f"engine raises undeclared code(s) {sorted(undeclared)} — add them to "
        "src/errors.py and to the §3.4 taxonomy before the pre-registration freezes."
    )


def test_every_declared_engine_code_is_actually_raised():
    unraised = ENGINE_ERROR_CODES - _raised_codes()
    assert not unraised, (
        f"declared code(s) {sorted(unraised)} are raised nowhere — the taxonomy "
        "would document a category that can never occur."
    )


def test_codes_chosen_by_a_helper_are_resolved_not_guessed():
    """The AST walk must follow ``_shortfall_code``-style indirection.

    ``combat_system`` picks between two codes inside a helper and passes the *call*
    as the code. Both outcomes must still be visible to the drift guard, or the two
    most common refusals quietly stop being covered.
    """
    raised = _raised_codes()
    assert "action_economy_spent" in raised
    assert "insufficient_resource" in raised


def test_taxonomy_partitions_cleanly():
    assert codes.ALL_CODES == ENGINE_ERROR_CODES | codes.AGENT_ERROR_CODES
    assert not (ENGINE_ERROR_CODES & codes.AGENT_ERROR_CODES)


def test_every_tool_failure_carries_a_declared_code(make_entity, make_combat):
    """No refusal may invent a code outside the taxonomy."""
    fighter = make_entity("Fighter", team="a", pos=(0, 0, 0), attacks=[ranged_attack()])
    goblin = make_entity("Goblin", team="b", pos=(500, 0, 0))
    combat = _started(make_combat, [fighter, goblin], fighter)
    executor = ToolExecutor(combat)

    bad_calls = [
        ToolCall("teleport", {}),
        ToolCall("attack", {}),
        ToolCall("attack", {"action_name": "Longbow", "defender_id": "nope"}),
        ToolCall("attack", {"action_name": "Longbow", "defender_id": goblin.entity_id}),
        ToolCall("move", {}),
        ToolCall("move", {"option_id": "nope"}),
    ]
    for call in bad_calls:
        result = executor.apply(fighter, call)
        assert result["ok"] is False, call
        assert result["code"] in codes.ALL_CODES, (call, result)


def test_every_interface_refusal_raises_a_declared_code():
    """A study condition's coded refusal lands in the taxonomy like any other.

    ``RejectedResponse(CODE, ...)`` is raised in ``src/arena`` rather than the engine,
    so the drift test above never sees it. Each site must name its code by a constant
    that resolves to a declared code — a typo'd string would silently open a category
    the analysis does not know.
    """
    sites = []
    for path in sorted((_SRC / "arena").rglob("*.py")):
        if path.name == "replay.py":
            continue  # re-raises the code a transcript recorded, not a new one
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "RejectedResponse"
            ):
                code = node.args[0]
                assert isinstance(code, ast.Name), f"{path.name}: use a named code"
                value = getattr(engine_errors, code.id, None) or getattr(
                    codes, code.id, None
                )
                assert value in codes.ALL_CODES, f"{path.name}: {code.id}"
                sites.append(code.id)
    assert sites, "no interface refusals found — has the scan gone stale?"
