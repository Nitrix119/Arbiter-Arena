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

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from src.arena.telemetry import RequestRecord
from src.arena.tools import TOOLS, ToolCall

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

_MENU_ACTION = """\
How to act:
- The battlefield lists every action available to the active creature, each with an \
`action_id`.
- Respond with EXACTLY ONE tool call: choose(action_id=…), and nothing else. Copy the \
`action_id` exactly as listed.
- Everything you can do this turn is in that list, including ending your turn."""


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

        The default strips the legal-action menu unless the condition grants it. The
        rest of the observation is untouched — §3.1 requires the state body to be
        identical across conditions.
        """
        if self.shows_menu:
            return observation
        trimmed = dict(observation)
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
        """Turn one model response into an executable :class:`ToolCall`, or ``None``.

        ``None`` means "the model did not produce an action I can use", which the
        shared loop answers with one correction and then a loud failure. Taking both
        the decoded *call* and the raw *record* lets a text condition read
        ``record.raw_output`` without the loop knowing which kind of condition it is
        driving.
        """

    def correction(self) -> str:
        """The single re-prompt sent when :meth:`interpret` returns ``None``."""
        return "Respond with exactly one tool call."


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

    Not implemented yet: the grammar and its parser are their own piece of work and
    must be frozen and adversarially tested before the pilot (V1_PLAN §3.1). The class
    exists so the seam is visible and the registry is honest about what is missing —
    :meth:`interpret` receives ``record.raw_output``, which is where the model's text
    already arrives, so C1 needs a parser rather than a second agent loop.
    """

    name = C1
    shows_menu = False

    def action_prompt(self) -> str:
        raise NotImplementedError("C1's grammar is not written yet")

    def api_tools(self, observation: Dict[str, Any]) -> List[Dict[str, Any]]:
        return []  # a text condition offers no tools at all

    def interpret(
        self,
        call: Optional[ToolCall],
        record: RequestRecord,
        observation: Dict[str, Any],
    ) -> Optional[ToolCall]:
        raise NotImplementedError("C1's parser is not written yet")


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


class MenuInterface(ActionInterface):
    """C3 — one tool, ``choose(action_id)``, over an enumerated legal-action list."""

    name = C3
    shows_menu = True

    def action_prompt(self) -> str:
        return _MENU_ACTION

    def interpret(
        self,
        call: Optional[ToolCall],
        record: RequestRecord,
        observation: Dict[str, Any],
    ) -> Optional[ToolCall]:
        raise NotImplementedError("C3's enumeration lands with the choose tool")

    def correction(self) -> str:
        return "Respond with exactly one choose(action_id=…) tool call."


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
