"""The action interface — the one thing the study actually varies.

Four conditions (V1_PLAN §3.1) differ in **exactly two respects**: how an action is
expressed, and whether the legal-action menu is shown. Everything else — the state
observation, the information policy, the engine, the failure budget — is held identical,
because a difference anywhere else would be an alternative explanation for any result.

| | output | menu shown? |
|---|---|---|
| **C1** ``free`` | plain text in a declared grammar | no |
| **C2** ``schema`` | tool call, raw params | no |
| **C2+M** ``schema_menu`` | tool call, raw params | **yes** |
| **C3** ``menu`` | ``choose(action_id)`` | **yes** |

C2+M exists because C3 moves two dials at once — format *and* affordance. C2 → C2+M
isolates affordance; C2+M → C3 isolates format. Without it a C2/C3 difference has two
candidate causes and the headline claim cannot be attributed to either.

**Why a strategy rather than a flag.** Four conditions × (prompt, observation, tools,
decoder) is sixteen places to branch. A registry keeps one implementation per condition
and one ``decide_one_action`` loop, so there is no second agent path to drift
(CLAUDE.md §3). It also means C1 — whose response is *text*, not a tool call — drops in
as another entry rather than as a special case in the loop.
"""

import json
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from src.arena.agent import RejectedResponse
from src.arena.free_text import UNREAD_TEXT, read_response, render_command
from src.arena.telemetry import RequestRecord
from src.arena.tools import TOOLS, ToolCall
from src.errors import UNKNOWN_ACTION, UNKNOWN_TARGET

#: Condition names, used in the manifest, transcripts and the batch grid.
C1 = "C1"
C2 = "C2"
C2_MENU = "C2+M"
C3 = "C3"

# ---------------------------------------------------------------------------
# The prompt, split at the seam the study varies
# ---------------------------------------------------------------------------

#: Everything true of the world regardless of how an action is expressed. **This text
#: must be byte-identical in every condition** — ``tests/arena/test_interfaces.py``
#: asserts the assembled prompts differ *only* in the action section, which is the §3.1
#: guarantee made machine-checkable rather than promised.
SHARED_PROMPT = """\
You are commanding a team in a Dungeons & Dragons 5th Edition combat encounter. \
Your goal is to defeat the enemy team.

How you play:
- You act one creature at a time, one action at a time. Each message shows the current \
battlefield for the active creature.
- After your action resolves you'll see the updated battlefield and act again, until \
you end the turn.
- A referee enforces the rules: an illegal action is rejected with an error you can \
learn from and correct.
- End your turn when you have nothing more worth doing.

The world model:
- Positions and distances are in FEET, on an open battlefield — there is no grid. You \
may move to any point within your movement budget; melee reach is measured edge to \
edge.
- Coordinates are (x, y, z): x runs EAST, z runs SOUTH, and y is VERTICAL (up). The \
ground plane is x and z — give both when naming a destination or an aim point. y is \
0 unless something is off the ground.
- You cannot move onto another creature.
- You only know what you can observe. An enemy's HP, AC, or capabilities may be \
hidden; you learn about them by seeing what they do and the damage they take.

Not modelled (do not plan around these): opportunity attacks and other reactions on \
another creature's turn, and legendary actions.

No tactics are scripted for you — use your own judgment and knowledge of 5e to play \
well."""

_RAW_PARAMS_ACTION = """\
How to act:
- Respond with EXACTLY ONE tool call (attack, cast_spell, move, or end_turn) and \
nothing else.
- Name targets by their entity_id. Name destinations and area-spell aim points by raw \
coordinates: move(x=…, z=…), or target_point={"x": …, "z": …}."""

_MENU_NOTE = """\
- The battlefield also lists the legal actions available to the active creature — the \
targets in reach, the named move destinations, and where an area spell could be aimed \
and who it would catch. Reading it is up to you; you still act by the tool calls \
above."""

#: C1's action section. Mirrors C2's "exactly one … and nothing else" so the two
#: differ in channel, not in how much the model is invited to say. The examples use a
#: creature and abilities that appear in no study scenario (a test enforces it), so
#: they teach the syntax without advising on any real board.
_FREE_TEXT_ACTION = """\
How to act:
- Respond with EXACTLY ONE line, in this form, and nothing else:
    ACTION: <command>
- Commands:
    attack <target> with <attack name>
    cast <spell name> at <target>
    cast <spell name> at x=<feet> z=<feet>
    move to x=<feet> z=<feet>
    end turn
  Add "at level <n>" after a cast to use a higher spell slot. To leave yourself a \
reminder for next turn: end turn \u2014 note: <reminder>
- Name targets by their entity_id and your attacks and spells by name, as shown on \
the battlefield. Destinations and area-spell aim points are ground coordinates in feet.
- Examples:
    ACTION: attack hobgoblin-2 with Warhammer
    ACTION: cast Stinking Cloud at x=12.5 z=40
    ACTION: move to x=-5 z=20"""

_MENU_ACTION = """\
How to act:
- The battlefield lists every action available to the active creature, each with an \
`action_id`.
- Respond with EXACTLY ONE tool call: choose(action_id=…), and nothing else. Copy the \
`action_id` exactly as listed.
- Everything you can do this turn is in that list, including ending your turn."""


def describe_tool_call(action: Dict[str, Any]) -> str:
    """A rejected action as the tool-call conditions see it: ``name {json args}``."""
    return f"{action.get('name')} {json.dumps(action.get('arguments', {}))}"


class ActionInterface(ABC):
    """How one condition expresses an action, and what it is shown.

    Subclasses vary only what the study varies. Anything they share lives in
    :data:`SHARED_PROMPT` or in the turn driver, not here.
    """

    #: Condition name recorded in the manifest and every transcript.
    name: str
    #: Whether the observation carries the legal-action menu.
    shows_menu: bool

    def system_prompt(self) -> str:
        """The full system prompt: shared world model plus this condition's action
        section."""
        return f"{SHARED_PROMPT}\n\n{self.action_prompt()}"

    @abstractmethod
    def action_prompt(self) -> str:
        """The **only** prompt text allowed to vary between conditions."""

    def shape_observation(self, observation: Dict[str, Any]) -> Dict[str, Any]:
        """Return the observation this condition shows.

        The default strips the legal-action menu unless the condition grants it, and
        always strips ``enumerated_actions`` — the flat choosable list is C3's
        vocabulary, and handing it to another condition would give that condition C3's
        affordance for free. The rest of the observation is untouched; §3.1 requires
        the state body to be identical across conditions.
        """
        trimmed = dict(observation)
        trimmed.pop("enumerated_actions", None)
        if not self.shows_menu:
            trimmed.pop("legal_actions", None)
        return trimmed

    def api_tools(self, observation: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Tool schemas offered for this decision. Empty for a text condition."""
        return list(TOOLS)

    @abstractmethod
    def interpret(
        self,
        call: Optional[ToolCall],
        record: RequestRecord,
        observation: Dict[str, Any],
    ) -> Optional[ToolCall]:
        """Turn one model response into an executable :class:`ToolCall`.

        Two ways to decline, and they mean different things:

        * return ``None`` — the model produced **no action at all** (prose, silence).
          The shared loop answers with one correction and then a loud failure, logged
          as ``no_tool_call``.
        * raise :class:`~src.arena.agent.RejectedResponse` — the model **did** answer,
          and this condition refuses the answer with a taxonomy code. It is logged as
          a rejected action under that code, with no free retry, exactly as an
          executor refusal would be.

        Taking both
        the decoded *call* and the raw *record* lets a text condition read
        ``record.raw_output`` without the loop knowing which kind of condition it is
        driving.
        """

    def correction(self) -> str:
        """The single re-prompt sent when :meth:`interpret` returns ``None``."""
        return "Respond with exactly one tool call."

    def format_rejected(self, action: Dict[str, Any]) -> str:
        """How a rejected action is described back to the model.

        Part of the action section in spirit: the feedback must speak the condition's
        own format, or a text condition would be shown C2's tool-call syntax every
        time it erred. The surrounding header is shared and stays in the loop.
        """
        return describe_tool_call(action)


class RawParamsInterface(ActionInterface):
    """Tool calls with raw parameters — entity ids, names, coordinates in feet."""

    def action_prompt(self) -> str:
        return _RAW_PARAMS_ACTION

    def interpret(
        self,
        call: Optional[ToolCall],
        record: RequestRecord,
        observation: Dict[str, Any],
    ) -> Optional[ToolCall]:
        return call


class FreeTextInterface(ActionInterface):
    """C1 — plain text in a declared grammar, parsed deterministically.

    The model is offered no tools; its answer is the text in ``record.raw_output``,
    read by :func:`~src.arena.free_text.read_response` into the same
    :class:`ToolCall` a C2 model would send. The parser checks *form* only — names are
    resolved and legality refereed by the shared executor — so C1 differs from C2 in
    the channel and nothing else. See ``docs/current/C1_PARSER_OPTIONS.md``.
    """

    name = C1
    shows_menu = False

    def action_prompt(self) -> str:
        return _FREE_TEXT_ACTION

    def api_tools(self, observation: Dict[str, Any]) -> List[Dict[str, Any]]:
        return []  # a text condition offers no tools at all

    def interpret(
        self,
        call: Optional[ToolCall],
        record: RequestRecord,
        observation: Dict[str, Any],
    ) -> Optional[ToolCall]:
        """Read the model's text; ignore any stray tool call (none was offered).

        How the text was read is written onto *record*, so the transcript carries the
        parse layer of every accepted action and the reason for every refusal.
        """
        reading = read_response(record.raw_output)
        if reading.call is not None:
            record.interpretation = {"layer": reading.layer, "line": reading.line}
            return reading.call
        if reading.code is None:
            return None  # no action at all: the correction path
        record.interpretation = {
            "code": reading.code,
            "reason": reading.reason,
            "line": reading.line,
        }
        raise RejectedResponse(
            reading.code,
            reading.reason,
            ToolCall(UNREAD_TEXT, {"text": reading.line or ""}),
        )

    def correction(self) -> str:
        return "Respond with exactly one line: ACTION: <command>"

    def format_rejected(self, action: Dict[str, Any]) -> str:
        """Show the model its own rejected line, in its own syntax — never JSON."""
        name = action.get("name", "")
        arguments = dict(action.get("arguments", {}))
        if name == UNREAD_TEXT:
            return f'"{arguments.get("text", "")}"'
        try:
            return render_command(ToolCall(name, arguments))
        except (KeyError, ValueError):
            return describe_tool_call(action)  # not a C1 action; never expected


class SchemaInterface(RawParamsInterface):
    """C2 — tool calls with raw params, and no legal-action menu."""

    name = C2
    shows_menu = False


class SchemaMenuInterface(RawParamsInterface):
    """C2+M — C2's format with C3's affordance: raw params, menu shown.

    The menu is *informational* here. The model still names targets and coordinates
    itself, which is what makes C2 → C2+M a clean test of affordance alone.
    """

    name = C2_MENU
    shows_menu = True

    def action_prompt(self) -> str:
        return f"{_RAW_PARAMS_ACTION}\n{_MENU_NOTE}"


#: C3's entire tool vocabulary. One tool, one argument — the condition's whole point.
CHOOSE_TOOL: Dict[str, Any] = {
    "name": "choose",
    "description": (
        "Take one of the actions listed for the active creature. Pass the "
        "`action_id` exactly as it appears in the list."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "action_id": {
                "type": "string",
                "description": "id of a listed action, copied exactly.",
            }
        },
        "required": ["action_id"],
    },
}


class MenuInterface(ActionInterface):
    """C3 — one tool, ``choose(action_id)``, over an enumerated legal-action list.

    The observation carries the flattened list (``enumerated_actions``) instead of the
    structured menu: under this condition there is nothing to assemble, so showing the
    raw parameters alongside would hand the model C2's format too and collapse the
    distinction the condition exists to isolate.
    """

    name = C3
    shows_menu = True

    def action_prompt(self) -> str:
        return _MENU_ACTION

    def api_tools(self, observation: Dict[str, Any]) -> List[Dict[str, Any]]:
        return [dict(CHOOSE_TOOL)]

    def shape_observation(self, observation: Dict[str, Any]) -> Dict[str, Any]:
        """Swap the structured menu for the flat, id-bearing list.

        The structured menu goes: under this condition there is nothing for the model
        to assemble, and showing raw targets and coordinates alongside would hand it
        C2's format too. Each entry is reduced to ``action_id`` and ``label`` — the
        ``ToolCall`` behind it is resolution machinery, not something to display.
        """
        shown = dict(observation)
        shown.pop("legal_actions", None)
        shown["actions"] = [
            action.to_dict() for action in observation.get("enumerated_actions", [])
        ]
        shown.pop("enumerated_actions", None)
        return shown

    def interpret(
        self,
        call: Optional[ToolCall],
        record: RequestRecord,
        observation: Dict[str, Any],
    ) -> Optional[ToolCall]:
        """Resolve a chosen id back to the real action.

        An id that is not on the list is refused as ``unknown_target`` — never
        resolved to its nearest neighbour, which would silently repair a hallucination
        the study is trying to count. It is the C2 analogue of naming an entity that
        does not exist, so it is coded and charged the same way. Calling any tool but
        ``choose`` is ``unknown_action``: this condition offers no other.
        """
        if call is None:
            return None
        if call.name != CHOOSE_TOOL["name"]:
            raise RejectedResponse(
                UNKNOWN_ACTION,
                f"Unknown tool {call.name!r}: the only tool is "
                "choose(action_id=...).",
                call,
            )
        chosen = call.arguments.get("action_id")
        for action in observation.get("enumerated_actions", []):
            if action.action_id == chosen:
                # A fresh ToolCall: the enumeration is rebuilt each decision and its
                # arguments must not be mutable state shared with the menu.
                return ToolCall(action.call.name, dict(action.call.arguments))
        raise RejectedResponse(
            UNKNOWN_TARGET,
            f"No listed action {chosen!r}; choose an action_id from the list.",
            call,
        )

    def correction(self) -> str:
        return (
            "Respond with exactly one choose(action_id=…) tool call, using an "
            "action_id from the list."
        )


#: The condition catalogue. Registry, never an if/elif on the condition name.
REGISTRY: Dict[str, type] = {
    C1: FreeTextInterface,
    C2: SchemaInterface,
    C2_MENU: SchemaMenuInterface,
    C3: MenuInterface,
}


def get_interface(name: str) -> ActionInterface:
    """Build the interface for condition *name*, naming the valid options on a typo."""
    try:
        return REGISTRY[name]()
    except KeyError:
        raise ValueError(
            f"Unknown condition {name!r}; expected one of {sorted(REGISTRY)}"
        ) from None
