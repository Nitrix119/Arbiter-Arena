"""The conditions differ in exactly what the study says they differ in — and nothing else.

§3.1's central claim is that the four conditions vary only in the action section of the
prompt and the response channel. That claim is the study's internal validity: any other
difference is an alternative explanation for every result. It is asserted here rather
than promised in a docstring, because prompt text is edited casually and a stray
condition-specific sentence in the shared body would be invisible and fatal.
"""

import pytest

from src.arena.agent import RejectedResponse
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
from src.errors import UNKNOWN_ACTION, UNKNOWN_TARGET

#: Conditions using raw parameters. C3 uses choose(); C1 is registered but not built.
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


def test_c1_declines_loudly_rather_than_degrading():
    """Declining beats pretending (CLAUDE.md §1): a silently degraded condition would
    produce data that looks fine and means nothing."""
    interface = get_interface(C1)
    with pytest.raises(NotImplementedError):
        interface.interpret(None, RequestRecord(), _obs())
    with pytest.raises(NotImplementedError):
        interface.action_prompt()


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


# -- one path per condition (the Phase 0 dual-path defect) --------------------


def test_no_llm_facing_tool_offers_a_menu_id():
    """A tool taking *either* a menu id or raw coordinates is two conditions in one.

    `move` used to accept both, so a model could pick C2's format or C3's affordance
    per decision — collapsing the very distinction C2+M exists to isolate. Phase 0
    flagged it; this is the guard that keeps it fixed.
    """
    for tool in TOOLS:
        properties = tool["input_schema"].get("properties", {})
        assert "option_id" not in properties, tool["name"]
        assert "action_id" not in properties, tool["name"]


def test_move_requires_the_ground_plane():
    move = next(t for t in TOOLS if t["name"] == "move")
    assert set(move["input_schema"]["required"]) == {"x", "z"}


def test_the_raw_param_action_section_never_mentions_an_option_id():
    for name in BUILT:
        section = get_interface(name).action_prompt().lower()
        assert "option_id" not in section
        assert "action_id" not in section


# -- C3: one tool, and ids that resolve --------------------------------------


def _enumerated():
    from src.arena.enumeration import EnumeratedAction

    return [
        EnumeratedAction(
            "attack:dagger:raider-1",
            "Attack Raider 1 with Dagger",
            ToolCall("attack", {"action_name": "Dagger", "defender_id": "raider-1"}),
        ),
        EnumeratedAction("end_turn", "End your turn", ToolCall("end_turn", {})),
    ]


def _menu_obs():
    return {**_obs(), "enumerated_actions": _enumerated()}


def test_c3_offers_exactly_one_tool():
    """The condition's whole point: one tool, one argument."""
    tools = get_interface(C3).api_tools(_menu_obs())
    assert [t["name"] for t in tools] == ["choose"]
    assert list(tools[0]["input_schema"]["properties"]) == ["action_id"]


def test_c3_shows_ids_and_labels_but_never_raw_parameters():
    """Showing the underlying call would hand C3 C2's format as well."""
    shown = get_interface(C3).shape_observation(_menu_obs())

    assert "legal_actions" not in shown
    assert "enumerated_actions" not in shown
    assert shown["actions"] == [
        {"action_id": "attack:dagger:raider-1", "label": "Attack Raider 1 with Dagger"},
        {"action_id": "end_turn", "label": "End your turn"},
    ]


def test_c3_resolves_a_chosen_id_to_the_real_action():
    call = ToolCall("choose", {"action_id": "attack:dagger:raider-1"})
    resolved = get_interface(C3).interpret(call, RequestRecord(), _menu_obs())

    assert resolved.name == "attack"
    assert resolved.arguments == {"action_name": "Dagger", "defender_id": "raider-1"}


def test_c3_resolution_does_not_alias_the_menu():
    """A returned call is executed and mutated (notes are popped); it must be a copy."""
    observation = _menu_obs()
    first = get_interface(C3).interpret(
        ToolCall("choose", {"action_id": "end_turn"}), RequestRecord(), observation
    )
    first.arguments["note"] = "scribbled"

    second = get_interface(C3).interpret(
        ToolCall("choose", {"action_id": "end_turn"}), RequestRecord(), observation
    )
    assert second.arguments == {}


def _refusal(call, observation):
    """Interpret *call* under C3 and return the coded refusal it must raise."""
    with pytest.raises(RejectedResponse) as refused:
        get_interface(C3).interpret(call, RequestRecord(), observation)
    return refused.value


def test_c3_refuses_an_invented_id_rather_than_guessing():
    """Resolving a near-miss would silently repair a hallucination the study counts.

    The refusal is *coded*: an invented id names a target that does not exist, the
    same `unknown_target` a C2 model gets for an invented entity id. It used to be a
    bare `None`, which the shared loop answered with a free correction and then logged
    as `no_tool_call` — miscoding it and sparing C3 a failure C2 would be charged.
    """
    call = ToolCall("choose", {"action_id": "attack:dagger:raider-9"})
    refused = _refusal(call, _menu_obs())

    assert refused.code == UNKNOWN_TARGET
    assert refused.call is call  # the attempt is kept, for the transcript
    assert "attack:dagger:raider-9" in str(refused)


def test_c3_refuses_a_call_to_any_other_tool():
    """A model reaching past `choose` is calling a tool this condition does not have."""
    direct = ToolCall("attack", {"action_name": "Dagger", "defender_id": "raider-1"})
    assert _refusal(direct, _menu_obs()).code == UNKNOWN_ACTION


def test_c3_with_nothing_enumerated_refuses_the_id():
    call = ToolCall("choose", {"action_id": "end_turn"})
    assert _refusal(call, _obs()).code == UNKNOWN_TARGET


def test_c3_saying_nothing_is_still_not_a_refusal():
    """No call at all keeps the correction path: that is `no_tool_call`, not a code."""
    assert get_interface(C3).interpret(None, RequestRecord(), _menu_obs()) is None


@pytest.mark.parametrize("name", BUILT)
def test_no_other_condition_sees_the_enumerated_list(name):
    """The flat list is C3's affordance; handing it over would leak the condition."""
    shown = get_interface(name).shape_observation(_menu_obs())
    assert "enumerated_actions" not in shown
    assert "actions" not in shown


# -- own capabilities survive every condition's shaping ------------------------


def _aoe_mage_observation():
    from src.arena.observation import build_observation
    from src.arena.scenarios import SCENARIOS

    from .conftest import force_turn

    combat = SCENARIOS["aoe_placement"].build()
    mage = next(e for e in combat.combatants if e.name == "Mage")
    force_turn(combat, mage)
    return combat, mage, build_observation(combat, mage)


@pytest.mark.parametrize("name", [C2, C2_MENU, C3])
def test_every_condition_shows_the_creature_its_own_capabilities(name):
    """What a creature *is* is state, not affordance, so no condition strips it."""
    _, _, observation = _aoe_mage_observation()
    mine = get_interface(name).shape_observation(observation)["self"]["capabilities"]

    assert [a["name"] for a in mine["attacks"]] == ["Dagger"]
    assert [s["name"] for s in mine["spells"]] == ["Fireball"]


def test_c2_can_act_by_the_names_it_is_shown():
    """End to end: a C2 model copying the names C2 shows it gets a legal call.

    Before own capabilities were in the shared body, the Mage under C2 saw neither
    `Dagger` nor `Fireball` anywhere, and any spelling it guessed differently was an
    `unknown_action` charged to the interface rather than the model.
    """
    from src.arena.tools import ToolExecutor

    combat, mage, observation = _aoe_mage_observation()
    mine = get_interface(C2).shape_observation(observation)["self"]["capabilities"]
    spell = mine["spells"][0]["name"]

    result = ToolExecutor(combat).apply(
        mage,
        ToolCall(
            "cast_spell",
            {"spell_name": spell, "target_point": {"x": 7.5, "z": 60}},
        ),
    )
    assert result["ok"], result


def test_no_raw_param_tool_points_at_a_menu_c2_does_not_have():
    """C2 is shown these descriptions with the menu stripped; naming it misleads."""
    for tool in TOOLS:
        assert "menu" not in tool["description"].lower(), tool["name"]
        for field in tool["input_schema"].get("properties", {}).values():
            assert "menu" not in field.get("description", "").lower(), tool["name"]
