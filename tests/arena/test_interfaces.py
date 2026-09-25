"""The conditions differ in exactly what the study says they differ in — and nothing else.

§3.1's central claim is that the four conditions vary only in the action section of the
prompt and the response channel. That claim is the study's internal validity: any other
difference is an alternative explanation for every result. It is asserted here rather
than promised in a docstring, because prompt text is edited casually and a stray
condition-specific sentence in the shared body would be invisible and fatal.
"""

import pytest

from src.arena.agent import RejectedResponse
from src.arena.free_text import UNREAD_TEXT
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

#: Every condition, for the guarantees that must hold across all of them.
ALL = [C1, C2, C2_MENU, C3]
#: Conditions answering with raw-parameter tool calls. C3 uses choose(); C1 writes text.
RAW = [C2, C2_MENU]


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


@pytest.mark.parametrize("name", ALL)
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
    for name in ALL:
        interface = get_interface(name)
        full = interface.system_prompt()
        remainders.add(full.replace(interface.action_prompt(), "").strip())

    assert len(remainders) == 1
    assert remainders.pop() == SHARED_PROMPT.strip()


def test_the_action_sections_actually_differ():
    """A guarantee that everything is identical would be trivially satisfiable."""
    sections = {get_interface(name).action_prompt() for name in ALL}
    assert len(sections) == len(ALL)


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


@pytest.mark.parametrize("name", RAW)
def test_raw_param_conditions_offer_the_full_tool_set(name):
    offered = {t["name"] for t in get_interface(name).api_tools(_obs())}
    assert offered == {t["name"] for t in TOOLS}


@pytest.mark.parametrize("name", RAW)
def test_a_raw_param_condition_passes_the_call_through(name):
    call = ToolCall("attack", {"action_name": "Dagger", "defender_id": "raider-1"})
    interpreted = get_interface(name).interpret(call, RequestRecord(), _obs())
    assert interpreted is call


@pytest.mark.parametrize("name", RAW)
def test_no_call_means_no_action(name):
    assert get_interface(name).interpret(None, RequestRecord(), _obs()) is None


# -- C1: plain text in a declared grammar ----------------------------------------


def _read(text):
    """Interpret *text* as a C1 response; return (action, the request record)."""
    record = RequestRecord(raw_output=text)
    return get_interface(C1).interpret(None, record, _obs()), record


def test_c1_offers_no_tools_at_all():
    """A text condition must not be handed a tool schema — that would be C2."""
    assert get_interface(C1).api_tools(_obs()) == []


def test_c1_reads_an_action_from_the_models_text():
    action, record = _read("ACTION: attack raider-1 with Dagger")

    assert action == ToolCall(
        "attack", {"action_name": "Dagger", "defender_id": "raider-1"}
    )
    assert record.interpretation == {
        "layer": 0,
        "line": "attack raider-1 with Dagger",
        "prose": False,
    }


def test_c1_refuses_an_unreadable_line_with_a_code():
    """An attempt the grammar cannot read is malformed_output, counted, not retried."""
    with pytest.raises(RejectedResponse) as refused:
        _read("ACTION: attack raider-1")

    assert refused.value.code == "malformed_output"
    assert refused.value.call == ToolCall(UNREAD_TEXT, {"text": "attack raider-1"})
    assert "with <attack name>" in str(refused.value)


def test_c1_records_how_a_refused_line_was_read():
    record = RequestRecord(raw_output="ACTION: fly to x=0 z=0")
    with pytest.raises(RejectedResponse):
        get_interface(C1).interpret(None, record, _obs())
    assert record.interpretation["code"] == "unknown_action"
    assert record.interpretation["line"] == "fly to x=0 z=0"


def test_c1_prose_without_an_action_takes_the_correction_path():
    action, record = _read("Let me think about where the raiders will go.")
    assert action is None
    assert record.interpretation is None


def test_c1_ignores_any_tool_call_a_provider_returns():
    """No tools are offered; a stray call is not C1's answer — the text is."""
    stray = ToolCall("end_turn", {})
    record = RequestRecord(raw_output="ACTION: move to x=0 z=35")
    action = get_interface(C1).interpret(stray, record, _obs())
    assert action.name == "move"


def test_c1_describes_rejections_in_its_own_syntax():
    """C1 must never be shown C2's tool-call JSON when it errs."""
    interface = get_interface(C1)
    parsed = {
        "name": "attack",
        "arguments": {"action_name": "Dagger", "defender_id": "raider-3"},
    }
    unread = {"name": UNREAD_TEXT, "arguments": {"text": "attack raider-1"}}

    assert interface.format_rejected(parsed) == "attack raider-3 with Dagger"
    assert interface.format_rejected(unread) == '"attack raider-1"'
    assert "{" not in interface.format_rejected(parsed)


def test_c1_correction_asks_for_the_action_line():
    assert "ACTION:" in get_interface(C1).correction()


def test_c1_prompt_examples_are_canonical_and_name_no_study_creature():
    """The worked examples must parse exactly, and must not hint at any real board.

    An example naming a study creature or weapon would be advice for that scenario
    rather than a description of the syntax.
    """
    from src.arena.free_text import read_response
    from src.arena.scenarios import SCENARIOS

    section = get_interface(C1).action_prompt()
    examples = [
        line.strip()
        for line in section.splitlines()
        if line.strip().startswith("ACTION: ") and "<" not in line
    ]
    assert len(examples) >= 2
    for example in examples:
        assert read_response(example).layer == 0, example

    study_names = set()
    for scenario in SCENARIOS.values():
        for entity in scenario.build().combatants:
            study_names |= {entity.entity_id, entity.name}
            study_names |= {a.name for a in entity.stat_block.actions}
            study_names |= set(entity.stat_block.known_spells)
    for name in study_names:
        assert name.casefold() not in section.casefold(), name


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


@pytest.mark.parametrize("name", RAW)
@pytest.mark.parametrize(
    "arguments",
    [
        {"option_id": "retreat:raider-1"},
        {"option_id": "retreat:raider-1", "x": 0, "z": 0},
    ],
    ids=["id-only", "id-and-coordinates"],
)
def test_a_raw_param_move_by_menu_id_is_refused_at_run_time(name, arguments):
    """The schema no longer offers option_id, but a host need not enforce a schema.

    The executor still honours option_id for the baselines, and C2+M's menu used to
    *show* every move's option_id. So a model that sends one anyway would get C3's format
    inside a raw-parameter condition. The guard has to be behavioural, not only a
    schema and a prompt that never mention it (review 2026-09-24, C-3).
    """
    with pytest.raises(RejectedResponse) as refused:
        get_interface(name).interpret(
            ToolCall("move", arguments), RequestRecord(), _obs()
        )

    assert refused.value.code == "malformed_output"
    assert "option_id" not in str(refused.value)  # never advertise the other path


def test_the_raw_param_action_section_never_mentions_an_option_id():
    for name in RAW:
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
    """The condition's whole point: one tool, one required argument (plus the note)."""
    tools = get_interface(C3).api_tools(_menu_obs())
    assert [t["name"] for t in tools] == ["choose"]
    assert tools[0]["input_schema"]["required"] == ["action_id"]
    assert set(tools[0]["input_schema"]["properties"]) == {"action_id", "note"}


def test_a_c3_note_rides_on_ending_the_turn():
    """Note parity: C3 can leave itself a reminder exactly where C2 can, at end_turn."""
    call = ToolCall("choose", {"action_id": "end_turn", "note": "focus raider-2"})
    resolved = get_interface(C3).interpret(call, RequestRecord(), _menu_obs())
    assert resolved == ToolCall("end_turn", {"note": "focus raider-2"})


def test_a_c3_note_on_any_other_choice_is_dropped():
    """As in C2, where the note field exists only on end_turn."""
    call = ToolCall("choose", {"action_id": "attack:dagger:raider-1", "note": "stray"})
    resolved = get_interface(C3).interpret(call, RequestRecord(), _menu_obs())
    assert "note" not in resolved.arguments


def test_every_condition_can_leave_itself_a_note():
    """A between-turn scratchpad in some conditions but not others is a confound.

    C3 had none until 2026-09-24: the note field was added only to a tool *named*
    end_turn, which C3 does not offer. Memory would then have differed by condition,
    the same class of artefact as opaque ids or unlabelled coordinates.
    """
    from src.arena.llm_common import augment_tools_with_notes

    for name in ALL:
        interface = get_interface(name)
        tools = augment_tools_with_notes(interface.api_tools(_menu_obs()))
        in_schema = any(
            "note" in t["input_schema"].get("properties", {}) for t in tools
        )
        in_prompt = "note:" in interface.action_prompt()
        assert in_schema or in_prompt, name


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


@pytest.mark.parametrize("name", [C1, *RAW])
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


# -- menu length: a cost covariate recorded per decision ----------------------------


@pytest.mark.parametrize(
    "name, shown", [(C1, False), (C2, False), (C2_MENU, True), (C3, True)]
)
def test_menu_length_is_counted_only_where_a_menu_is_shown(name, shown):
    """Prereg §2 records menu length per decision; it exists only under a menu."""
    _, _, observation = _aoe_mage_observation()
    length = get_interface(name).menu_length(observation)

    if shown:
        assert length == len(observation["enumerated_actions"]) > 1
    else:
        assert length is None


@pytest.mark.parametrize(
    "arguments",
    [{}, {"action_id": None}, {"action_id": 3}, {"action_id": ["end_turn"]}],
)
def test_a_c3_choice_naming_no_id_is_malformed_not_unknown(arguments):
    """No id at all is a missing argument — C2's analogue is ``malformed_output`` too.

    ``unknown_target`` is for an id that *was* written but is not on the list; counting
    an absent one there would inflate the very category H2 is stated in terms of.
    """
    with pytest.raises(RejectedResponse) as refused:
        get_interface(C3).interpret(
            ToolCall("choose", arguments), RequestRecord(), _menu_obs()
        )
    assert refused.value.code == "malformed_output"


# -- several different calls in one response (review 2026-09-24, prereg §6) --------


def _several(distinct):
    record = RequestRecord()
    record.distinct_tool_calls = distinct
    record.extra_tool_calls = 1
    return record


@pytest.mark.parametrize("name", RAW)
def test_a_raw_param_response_with_two_different_calls_is_refused(name):
    """C1 refuses two different ACTION lines; a tool condition must not run the first.

    Otherwise the same behaviour is a failure in C1 and a success in C2, a bias in
    H1's C2 − C1 contrast toward the very ordering it predicts.
    """
    call = ToolCall("attack", {"action_name": "Dagger", "defender_id": "raider-1"})
    with pytest.raises(RejectedResponse) as refused:
        get_interface(name).interpret(call, _several(2), _obs())

    assert refused.value.code == "malformed_output"
    assert refused.value.call is call  # logged as what it first attempted


def test_a_c3_response_choosing_two_different_ids_is_refused():
    call = ToolCall("choose", {"action_id": "end_turn"})
    with pytest.raises(RejectedResponse) as refused:
        get_interface(C3).interpret(call, _several(2), _menu_obs())

    assert refused.value.code == "malformed_output"


@pytest.mark.parametrize("name", RAW)
def test_an_identical_repeat_is_one_action(name):
    """As in C1, where a repeated identical ACTION line is read once."""
    call = ToolCall("attack", {"action_name": "Dagger", "defender_id": "raider-1"})
    assert get_interface(name).interpret(call, _several(1), _obs()) is call


def test_a_c3_identical_repeat_is_one_action():
    call = ToolCall("choose", {"action_id": "end_turn"})
    resolved = get_interface(C3).interpret(call, _several(1), _menu_obs())
    assert resolved.name == "end_turn"


# -- C2+M is not shown ids it may not use (review 2026-09-24) ------------------------


def test_c2_menu_shows_no_id_it_cannot_act_by():
    """A move or aim by menu id is refused in C2+M, so the menu must not display one.

    Showing it set a trap only C2+M could fall into, biasing C2+M down: inflating
    C3 − C2+M (the format effect) and shrinking C2+M − C2 (the affordance effect).
    Everything a raw-parameter call needs is still shown.
    """
    import json

    _, _, observation = _aoe_mage_observation()
    shown = get_interface(C2_MENU).shape_observation(observation)

    assert "option_id" not in json.dumps(shown, default=str)
    menu = shown["legal_actions"]
    assert menu["moves"] and all(
        {"label", "x", "y", "z", "cost_ft"} <= set(m) for m in menu["moves"]
    )
    aims = [a for spell in menu["spells"] for a in spell["aim_points"]]
    assert aims and all({"x", "y", "z", "hits"} <= set(a) for a in aims)
    # The caller's copy keeps its ids: the deterministic baselines move by them.
    assert all("option_id" in m for m in observation["legal_actions"]["moves"])
