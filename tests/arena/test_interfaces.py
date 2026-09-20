"""The conditions differ in exactly what the study says they differ in — and nothing else.

§3.1's central claim is that the four conditions vary only in the action section of the
prompt and the response channel. That claim is the study's internal validity: any other
difference is an alternative explanation for every result. It is asserted here rather
than promised in a docstring, because prompt text is edited casually and a stray
condition-specific sentence in the shared body would be invisible and fatal.
"""

import pytest

from src.arena.interfaces import (
    C1,
    C2,
    C2_MENU,
    C3,
    REGISTRY,
    SHARED_PROMPT,
    ActionInterface,
    get_interface,
)
from src.arena.telemetry import RequestRecord
from src.arena.tools import TOOLS, ToolCall

#: Conditions whose prompt and decoding are implemented. C1 is registered but not built.
BUILT = [C2, C2_MENU]


def _obs():
    return {
        "round": 1,
        "self": {"name": "Hero"},
        "enemies": [],
        "legal_actions": {"attacks": [], "spells": [], "moves": []},
    }


# -- the registry ------------------------------------------------------------


def test_every_condition_is_registered():
    assert set(REGISTRY) == {C1, C2, C2_MENU, C3}


def test_an_unknown_condition_names_the_valid_ones():
    with pytest.raises(ValueError, match="C2"):
        get_interface("C4")


def test_each_interface_reports_its_own_name():
    for name in REGISTRY:
        assert get_interface(name).name == name


# -- the §3.1 guarantee ------------------------------------------------------


@pytest.mark.parametrize("name", BUILT)
def test_the_shared_body_is_byte_identical_in_every_condition(name):
    """The world model must not drift between conditions by so much as a character."""
    assert get_interface(name).system_prompt().startswith(SHARED_PROMPT)


def test_prompts_differ_only_in_the_action_section():
    """The whole experiment rests on this.

    Strip each condition's action section and what remains must be the same text. If
    this ever fails, some condition-specific sentence has leaked into the shared body
    and every between-condition result has a second possible cause.
    """
    remainders = set()
    for name in BUILT:
        interface = get_interface(name)
        full = interface.system_prompt()
        remainders.add(full.replace(interface.action_prompt(), "").strip())

    assert len(remainders) == 1
    assert remainders.pop() == SHARED_PROMPT.strip()


def test_the_action_sections_actually_differ():
    """A guarantee that everything is identical would be trivially satisfiable."""
    sections = {get_interface(name).action_prompt() for name in BUILT}
    assert len(sections) == len(BUILT)


def test_the_shared_body_never_mentions_a_menu():
    """ "Your legal options" in the shared text would silently make C2's prompt a lie.

    It used to: the instruction line in `render_observation` said "study the
    battlefield and your legal options", which is false under a condition that shows
    no options.
    """
    lowered = SHARED_PROMPT.lower()
    for leak in ("legal option", "action_id", "listed option", "choose("):
        assert leak not in lowered, f"{leak!r} is condition-specific"


def test_the_shared_body_keeps_the_axis_convention():
    """A pre-freeze prompt property worth pinning — it was added to fix a real bug."""
    lowered = SHARED_PROMPT.lower()
    assert "east" in lowered and "south" in lowered and "ground plane" in lowered


# -- what each condition shows ------------------------------------------------


def test_c2_strips_the_menu_and_c2_menu_keeps_it():
    """The single dial C2 -> C2+M turns: affordance, with format held constant."""
    assert "legal_actions" not in get_interface(C2).shape_observation(_obs())
    assert "legal_actions" in get_interface(C2_MENU).shape_observation(_obs())


def test_stripping_the_menu_changes_nothing_else():
    """Only the menu key may differ, or the observation is no longer held fixed."""
    full = _obs()
    stripped = get_interface(C2).shape_observation(full)

    assert set(full) - set(stripped) == {"legal_actions"}
    for key, value in stripped.items():
        assert full[key] == value


def test_shaping_does_not_mutate_the_callers_observation():
    """The turn driver reuses the observation; a destructive strip would leak across
    agents."""
    observation = _obs()
    get_interface(C2).shape_observation(observation)
    assert "legal_actions" in observation


@pytest.mark.parametrize("name", BUILT)
def test_raw_param_conditions_offer_the_full_tool_set(name):
    offered = {t["name"] for t in get_interface(name).api_tools(_obs())}
    assert offered == {t["name"] for t in TOOLS}


@pytest.mark.parametrize("name", BUILT)
def test_a_raw_param_condition_passes_the_call_through(name):
    call = ToolCall("attack", {"action_name": "Dagger", "defender_id": "raider-1"})
    interpreted = get_interface(name).interpret(call, RequestRecord(), _obs())
    assert interpreted is call


@pytest.mark.parametrize("name", BUILT)
def test_no_call_means_no_action(name):
    assert get_interface(name).interpret(None, RequestRecord(), _obs()) is None


# -- what is not built yet ----------------------------------------------------


@pytest.mark.parametrize("name", [C1, C3])
def test_unbuilt_conditions_decline_loudly(name):
    """Declining beats pretending (CLAUDE.md §1): a silently degraded condition would
    produce data that looks fine and means nothing."""
    interface = get_interface(name)
    with pytest.raises(NotImplementedError):
        interface.interpret(None, RequestRecord(), _obs())


def test_c1_offers_no_tools_at_all():
    """A text condition must not be handed a tool schema — that would be C2."""
    assert get_interface(C1).api_tools(_obs()) == []


def test_c3_is_a_menu_condition():
    assert get_interface(C3).shows_menu is True
    assert "action_id" in get_interface(C3).action_prompt()


# -- the contract -------------------------------------------------------------


def test_every_interface_implements_the_contract():
    for name in REGISTRY:
        interface = get_interface(name)
        assert isinstance(interface, ActionInterface)
        assert isinstance(interface.shows_menu, bool)
        assert interface.correction()
