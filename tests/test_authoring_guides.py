"""The authoring guides' examples must load, and must match the spells that ship.

The spell guide rotted for months because nothing read it: its examples used a
deleted form and invalid target values, and it linked to files that no longer
existed. This test reads both guides the way an author would use them. It loads
every JSON example through the real loader, and holds named spell examples to the
shipped files, which have execution tests of their own.

An example containing ``...`` is an outline, not a spec, and is only parsed. A
pattern example may be written as ``{"name": ..., "program": [...]}``: it is
validated, and held to the shipped spell of that name.
"""

import json
import re
from pathlib import Path

import pytest

from src.loaders.stat_block_loader import StatBlockLoader
from src.spells.validate import validate_program

ROOT = Path(__file__).resolve().parent.parent
SPELLS = ROOT / "examples" / "spells"
GUIDES = [
    SPELLS / "SPELL_DEFINITION_GUIDE.md",
    ROOT / "examples" / "creatures" / "CREATURE_DEFINITION_GUIDE.md",
]
RETIRED = ['"effects"', "add_entity_effect", "on_apply", "RuleEngine"]
_FENCE = re.compile(r"```json\n(.*?)```", re.S)
_LINK = re.compile(r"\]\(([^)\s]+)\)")


def _shipped_programs():
    programs = {}
    for path in SPELLS.glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        programs[data["name"]] = data["program"]
    return programs


def _examples(guide):
    for index, text in enumerate(_FENCE.findall(guide.read_text(encoding="utf-8"))):
        yield pytest.param(guide, text, id=f"{guide.stem}-{index}")


EXAMPLES = [example for guide in GUIDES for example in _examples(guide)]


def _parse(text):
    # A bare `"program": [...]` fragment is valid once wrapped in an object.
    for candidate in (text, "{" + text + "}"):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    raise AssertionError(f"example is not valid JSON:\n{text}")


def _blocks_of(value):
    """The block program an example holds, if it is one or contains one."""
    if isinstance(value, list) and value and all("block" in b for b in value):
        return value
    if isinstance(value, dict) and "block" in value:
        return [value]
    if isinstance(value, dict) and set(value) in ({"program"}, {"name", "program"}):
        return value["program"]
    return None


@pytest.mark.parametrize("guide,text", EXAMPLES)
def test_example_loads(guide, text):
    if "..." in text:
        return  # an outline: shape only, never loaded
    value = _parse(text)
    if isinstance(value, dict) and value.get("type") in ("spell", "attack"):
        StatBlockLoader._parse_action(value)
    elif isinstance(value, dict) and "actions" in value and "abilities" in value:
        StatBlockLoader.from_dict(value)
    elif (program := _blocks_of(value)) is not None:
        validate_program(program, spell_name=f"{guide.name} example")


@pytest.mark.parametrize("guide,text", EXAMPLES)
def test_named_spell_example_matches_the_shipped_file(guide, text):
    if "..." in text:
        return
    value = _parse(text)
    shipped = _shipped_programs()
    # A full spell, or a pattern example written as {"name": ..., "program": [...]}.
    named = isinstance(value, dict) and (
        value.get("type") == "spell" or set(value) == {"name", "program"}
    )
    if named:
        if value.get("name") in shipped:
            assert value["program"] == shipped[value["name"]], (
                f"{guide.name}: the {value['name']} example differs from "
                "examples/spells; copy the shipped program"
            )


@pytest.mark.parametrize("guide", GUIDES, ids=lambda g: g.stem)
def test_guide_does_not_teach_the_retired_form(guide):
    text = guide.read_text(encoding="utf-8")
    found = [term for term in RETIRED if term in text]
    assert not found, f"{guide.name} still documents the retired form: {found}"


@pytest.mark.parametrize("guide", GUIDES, ids=lambda g: g.stem)
def test_guide_links_resolve(guide):
    text = guide.read_text(encoding="utf-8")
    broken = []
    for target in _LINK.findall(text):
        if target.startswith(("http://", "https://", "#", "mailto:")):
            continue
        path = (guide.parent / target.split("#", 1)[0]).resolve()
        if not path.exists():
            broken.append(target)
    assert not broken, f"{guide.name} links to missing files: {broken}"
