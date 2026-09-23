"""C1's parser: plain text in a declared command grammar, read deterministically.

The free-text condition asks the model for one line — ``ACTION: attack raider-1 with
Dagger`` — and this module turns that text into the same :class:`ToolCall` a C2 model
would have sent. Everything about *meaning* is left to the shared executor: names are
passed through as written and resolved there (:mod:`src.arena.identifiers`), so C1 gets
no tolerance C2 lacks, and legality is refereed exactly as for every other condition.

Design, from ``docs/current/C1_PARSER_OPTIONS.md`` (accepted 2026-09-24):

* **Deterministic and state-free.** A pure function of the text. The module imports
  nothing that can see the board, so it cannot "help" by choosing the sensible target;
  a test enforces that.
* **One grammar, published and executed.** :data:`GRAMMAR` is the Lark grammar the
  parser runs; the prompt teaches its canonical forms, and
  ``tests/arena/test_free_text.py`` is the accept/reject boundary as a table.
* **Layered tolerance, recorded.** Every accepted action carries the layer it needed:
  0 byte-identical to the canonical rendering, 1 identical after surface normalisation
  (case, markdown, quotes, dashes, trailing punctuation), 2 grammatical but not
  canonical (synonyms, fillers, number formats), 3 read out of surrounding prose or an
  untagged line. The layer is *derived* by comparing the text with
  :func:`render_command` of the result, so the grammar carries no bookkeeping.
* **No repair.** A name that names nothing still parses and is refused by the executor;
  a construction the grammar cannot read is refused here with a code and a reason the
  model can act on. The lenient bound (implied weapon, bare coordinate pairs, "take the
  last of several actions") is deliberately *not* here — it belongs to the offline
  re-scorer, never to the live measurement.

Parser choice: LALR, so a grammar ambiguity is a construction-time error rather than a
silent pick between readings.
"""

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from lark import Lark, Token, Transformer
from lark.exceptions import LarkError, VisitError

from src.arena.error_codes import MALFORMED_OUTPUT
from src.arena.tools import TOOL_ATTACK, TOOL_CAST_SPELL, TOOL_END_TURN, TOOL_MOVE
from src.arena.tools import ToolCall
from src.errors import UNKNOWN_ACTION

#: The call recorded when a response is refused before it became an action.
UNREAD_TEXT = "(unread_text)"

#: The executed grammar. Every keyword is its **own** case-insensitive string literal
#: (an alternation would become a regex and lose this): Lark then retypes a ``WORD``
#: that spells a keyword exactly, so ``within`` stays a word while ``with`` is
#: structure. Anonymous literals are dropped from the tree, which is why the verb
#: families need no terminal of their own. A name is a run of words and numbers
#: (``Raider 1``).
GRAMMAR = r"""
?start: command

command: attack | cast | move | end

attack: _attack_verb _the? name _with _my? name
cast: "cast"i name aim? slot?
aim: _at (point | targets)
targets: _the? name ("," _the? name)*
slot: _at "level"i NUMBER
move: _move_verb "to"i? point
end: "end"i _my? "turn"i | "pass"i | "done"i

_attack_verb: "attack"i | "hit"i | "strike"i | "shoot"i | "stab"i
_move_verb: "move"i | "go"i | "walk"i | "run"i | "step"i
_with: "with"i | "using"i
_at: "at"i | "on"i | "targeting"i
_the: "the"i
_my: "my"i

?point: labelled | triple
labelled: coord (","? coord)+
coord: axis (":" | "=")? NUMBER _unit?
!axis: "x"i | "y"i | "z"i
_unit: "ft"i | "feet"i
triple: "(" NUMBER "," NUMBER "," NUMBER ")"

name: WORD (WORD | NUMBER)*

NUMBER.2: /-?\d+(\.\d+)?/
WORD: /[^\s,()=:]+/i

%ignore /\s+/
"""

#: Every word the grammar treats as structure. An identifier containing one as a whole
#: word could never be written, so study rosters are checked against this set.
GRAMMAR_KEYWORDS = frozenset(
    {
        "attack", "hit", "strike", "shoot", "stab",
        "move", "go", "walk", "run", "step",
        "cast", "end", "turn", "pass", "done",
        "with", "using", "at", "on", "targeting", "to", "level",
        "the", "my", "x", "y", "z", "ft", "feet",
        "or", "and", "then", "note", "i", "will",
    }
)  # fmt: skip

#: First words that start a command. Anything else is an unknown action.
_VERBS = frozenset(
    {"attack", "hit", "strike", "shoot", "stab", "cast"}
    | {"move", "go", "walk", "run", "step", "end", "pass", "done"}
)
#: Words that join alternatives. Never part of a name, so a phrase containing one is
#: refused rather than read as a single creature called "raider-1 or raider-2".
_JOINERS = frozenset({"or", "and", "then"})
_ATTACK_WORDS = {"attack", "hit", "strike", "shoot", "stab"}
_MOVE_WORDS = {"move", "go", "walk", "run", "step"}

#: How to write each command, quoted back to a model whose line could not be read.
_TEMPLATES = {
    "attack": "attack <target> with <attack name>",
    "cast": (
        "cast <spell name> at <target>, or cast <spell name> at x=<feet> z=<feet>"
        " (optionally ending: at level <n>)"
    ),
    "move": "move to x=<feet> z=<feet>",
    "end": "end turn (optionally: end turn — note: <reminder>)",
}

_PARSER = Lark(GRAMMAR, parser="lalr", maybe_placeholders=False)

_TAG = re.compile(r"^\s*action\s*:\s*(.*)$", re.IGNORECASE)
_FENCE = re.compile(r"^\s*```[\w-]*\s*$")
_DASHES = re.compile("[‐‑‒–—―−]")
_LEADING_FILLER = re.compile(r"^(?:i\s+will|i'll|i|will)\s+", re.IGNORECASE)
_NOTE = re.compile(r"^(?P<head>.*?)\s*[-:;,]?\s*\bnote\s*:\s*(?P<note>.*)$", re.I)
_SECOND_ACTION = re.compile(
    r"(?:\b(?:and|then)\b|;)\s*(?:then\s+)?(?:" + "|".join(sorted(_VERBS)) + r")\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Reading:
    """What one response was read as.

    Exactly one of three outcomes: an accepted ``call`` (with its ``layer``), a
    refusal (``code`` and ``reason``), or — all fields empty — no action at all.
    ``line`` is the command text that was read, kept for the transcript and for
    describing a refusal back to the model.
    """

    call: Optional[ToolCall]
    layer: Optional[int]
    line: Optional[str]
    code: Optional[str]
    reason: str


_NOTHING = Reading(None, None, None, None, "")


# -- surface normalisation ---------------------------------------------------------


def surface(text: str) -> str:
    """Layer 1: fold away what changes how text *looks* but not what it says.

    Unicode compatibility forms and dash variants, markdown emphasis and code marks,
    double quotes, runs of whitespace, and trailing sentence punctuation.
    """
    text = unicodedata.normalize("NFKC", text)
    text = _DASHES.sub("-", text)
    text = text.replace("‘", "'").replace("’", "'")
    text = re.sub(r"[*`\"“”„]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"^(?:[->#]\s*)+(?=action\s*:)", "", text, flags=re.IGNORECASE)
    return text.rstrip(".!;").strip()


# -- canonical rendering -----------------------------------------------------------


def _number(value: Any) -> str:
    """Shortest text that reads back to the same float; integral values bare."""
    number = float(value)
    return str(int(number)) if number.is_integer() else repr(number)


def _render_point(point: Dict[str, Any]) -> str:
    parts = [f"x={_number(point['x'])}"]
    if float(point.get("y", 0.0)) != 0.0:
        parts.append(f"y={_number(point['y'])}")
    parts.append(f"z={_number(point['z'])}")
    return " ".join(parts)


def render_command(call: ToolCall) -> str:
    """The canonical C1 text for *call* — the exact inverse of parsing it.

    Used to show a model its own rejected actions in its own format, and to decide
    the parse layer: text byte-identical to this rendering needed no tolerance at all.
    """
    args = call.arguments
    if call.name == TOOL_ATTACK:
        return f"attack {args['defender_id']} with {args['action_name']}"
    if call.name == TOOL_CAST_SPELL:
        text = f"cast {args['spell_name']}"
        if args.get("target_ids"):
            text += " at " + ", ".join(args["target_ids"])
        elif args.get("target_point"):
            text += " at " + _render_point(args["target_point"])
        if args.get("slot_level") is not None:
            text += f" at level {args['slot_level']}"
        return text
    if call.name == TOOL_MOVE:
        return f"move to {_render_point(args)}"
    if call.name == TOOL_END_TURN:
        note = args.get("note")
        return f"end turn — note: {note}" if note else "end turn"
    raise ValueError(f"No C1 rendering for tool {call.name!r}")


# -- the grammar's tree to a call --------------------------------------------------


class _Unreadable(ValueError):
    """The line parsed, but says something the command cannot mean."""


class _ToCall(Transformer):
    """Build the :class:`ToolCall` a C2 model would have sent for the same action."""

    def name(self, tokens: List[Token]) -> str:
        words = [str(t) for t in tokens]
        joined = {w.casefold() for w in words} & _JOINERS
        if joined:
            # "raider-1 or raider-2" is two names, not one called that.
            raise _Unreadable(f"name one target, not several joined by {min(joined)!r}")
        return " ".join(words)

    def targets(self, names: List[str]) -> List[str]:
        return list(names)

    def axis(self, tokens: List[Token]) -> str:
        return str(tokens[0]).lower()

    def coord(self, items: List[Any]) -> Tuple[str, float]:
        axis, number = items
        return axis, float(number)

    def labelled(self, coords: List[Tuple[str, float]]) -> Dict[str, float]:
        point: Dict[str, float] = {}
        for axis, value in coords:
            if axis in point:
                raise _Unreadable(f"{axis} is given twice")
            point[axis] = value
        if "x" not in point or "z" not in point:
            raise _Unreadable("a point needs both x and z")
        return {"x": point["x"], "y": point.get("y", 0.0), "z": point["z"]}

    def triple(self, numbers: List[Token]) -> Dict[str, float]:
        x, y, z = (float(n) for n in numbers)
        return {"x": x, "y": y, "z": z}

    def aim(self, items: List[Any]) -> Dict[str, Any]:
        (target,) = items
        if isinstance(target, dict):
            return {"target_point": target}
        return {"target_ids": target}

    def slot(self, items: List[Token]) -> Dict[str, int]:
        (number,) = items
        level = float(number)
        if not level.is_integer():
            raise _Unreadable("a slot level is a whole number")
        return {"slot_level": int(level)}

    def attack(self, items: List[Any]) -> ToolCall:
        target, weapon = items
        return ToolCall(TOOL_ATTACK, {"action_name": weapon, "defender_id": target})

    def cast(self, items: List[Any]) -> ToolCall:
        spell, *parts = items
        args: Dict[str, Any] = {"spell_name": spell}
        for part in parts:
            args.update(part)
        return ToolCall(TOOL_CAST_SPELL, args)

    def move(self, items: List[Any]) -> ToolCall:
        (point,) = items
        return ToolCall(TOOL_MOVE, dict(point))

    def end(self, items: List[Any]) -> ToolCall:
        return ToolCall(TOOL_END_TURN, {})

    def command(self, items: List[ToolCall]) -> ToolCall:
        return items[0]


def _verb_family(word: str) -> str:
    if word in _ATTACK_WORDS:
        return "attack"
    if word in _MOVE_WORDS:
        return "move"
    if word == "cast":
        return "cast"
    return "end"


def _refuse(line: str, code: str, reason: str) -> Reading:
    return Reading(None, None, line, code, reason)


def _read_command(command: str) -> Reading:
    """Read one command (the text after ``ACTION:``), already surface-normalised."""
    line = command
    command = _LEADING_FILLER.sub("", command).strip()
    if not command:
        return _refuse(line, MALFORMED_OUTPUT, _empty_reason())

    note: Optional[str] = None
    split = _NOTE.match(command)
    if split:
        command, note = split.group("head").strip(), split.group("note").strip()

    first = command.split()[0].casefold() if command.split() else ""
    if first not in _VERBS:
        return _refuse(
            line,
            UNKNOWN_ACTION,
            f"Unknown action {first!r}: a command starts with attack, cast, move or "
            "end turn.",
        )
    if _SECOND_ACTION.search(command):
        return _refuse(
            line,
            MALFORMED_OUTPUT,
            "Write one action per response; the others can follow after this one "
            "resolves.",
        )

    family = _verb_family(first)
    try:
        call = _ToCall().transform(_PARSER.parse(command))
    except VisitError as exc:
        detail = str(exc.orig_exc) if isinstance(exc.orig_exc, _Unreadable) else ""
        return _refuse(line, MALFORMED_OUTPUT, _template_reason(family, detail))
    except LarkError:
        return _refuse(line, MALFORMED_OUTPUT, _template_reason(family))

    if note is not None:
        if call.name != TOOL_END_TURN:
            return _refuse(line, MALFORMED_OUTPUT, "A note can only follow end turn.")
        if note:
            call.arguments["note"] = note
    return Reading(call, None, line, None, "")


def _template_reason(family: str, detail: str = "") -> str:
    why = f" ({detail})" if detail else ""
    return (
        f"Could not read that {family} command{why}. Write it as: {_TEMPLATES[family]}"
    )


def _empty_reason() -> str:
    return "Nothing follows ACTION:. Write one command after it, e.g. end turn."


# -- a whole response --------------------------------------------------------------


def _layer(response: str, call: ToolCall, extracted: bool) -> int:
    if extracted:
        return 3
    canonical = "ACTION: " + render_command(call)
    if response.strip() == canonical:
        return 0
    body = "\n".join(ln for ln in response.splitlines() if not _FENCE.match(ln))
    if surface(body).casefold() == surface(canonical).casefold():
        return 1
    return 2


def read_response(text: Optional[str]) -> Reading:
    """Read a model's whole response into one action, a refusal, or nothing.

    * Lines tagged ``ACTION:`` are read. Several are accepted only when they say the
      same thing; otherwise the response is refused as more than one action.
    * With no tag, a line is read only if exactly one line of the response is a
      command (layer 3). If none is, the response contains **no action** — the
      correction path, and ``no_tool_call`` if that fails too — because nothing marks
      the prose as an attempt.
    """
    if text is None or not text.strip():
        return _NOTHING

    lines = [ln for ln in text.splitlines() if not _FENCE.match(ln)]
    content = [surface(ln) for ln in lines if surface(ln)]

    tagged = [m.group(1) for m in (_TAG.match(ln) for ln in content) if m]
    if tagged:
        readings = [_read_command(command) for command in tagged]
        refused = next((r for r in readings if r.code is not None), None)
        if refused is not None:
            return refused
        calls = [r.call for r in readings]
        if any(call != calls[0] for call in calls):
            return _refuse(
                " | ".join(tagged),
                MALFORMED_OUTPUT,
                "The response gives more than one different ACTION; give exactly one.",
            )
        extracted = len(content) > 1
        call = calls[0]
        assert call is not None
        return Reading(call, _layer(text, call, extracted), tagged[0], None, "")

    readable = [r for r in (_read_command(ln) for ln in content) if r.call is not None]
    if not readable:
        return _NOTHING
    if any(r.call != readable[0].call for r in readable):
        return _refuse(
            " | ".join(r.line or "" for r in readable),
            MALFORMED_OUTPUT,
            "The response gives more than one different action; give exactly one "
            "line: ACTION: <command>.",
        )
    first = readable[0]
    assert first.call is not None
    return Reading(first.call, 3, first.line, None, "")


# -- the lenient bound (offline re-scoring only) -------------------------------------

#: The layer a reading gets when only the lenient bound could make it.
LENIENT_LAYER = 4

_JUSTIFICATION = re.compile(
    r"\s+(?:since|because|as|so that|so|to\s+(?:avoid|stay|keep|finish|get))\b.*$",
    re.IGNORECASE,
)
_NUMBER = r"-?\d+(?:\.\d+)?"
_BARE_PAIR = re.compile(rf"\(\s*({_NUMBER})\s*,\s*({_NUMBER})\s*\)")
_TRAILING_PAIR = re.compile(rf"\b(at|to)\s+({_NUMBER})\s*,\s*({_NUMBER})\s*$", re.I)
_HAS_WEAPON = re.compile(r"\b(?:with|using)\b", re.IGNORECASE)


def _repair(line: str, sole_attack: Optional[str]) -> str:
    """Apply every registered lenient repair to one command line, in a fixed order."""
    line = _JUSTIFICATION.sub("", line)
    second = _SECOND_ACTION.search(line)
    if second:
        line = line[: second.start()]
    line = line.strip().rstrip(",;").strip()
    line = _BARE_PAIR.sub(r"x=\1 z=\2", line)
    line = _TRAILING_PAIR.sub(r"\1 x=\2 z=\3", line)
    words = _LEADING_FILLER.sub("", line).split()
    is_attack = bool(words) and words[0].casefold() in _ATTACK_WORDS
    if is_attack and sole_attack and not _HAS_WEAPON.search(line):
        line = f"{line} with {sole_attack}"
    return line


def read_lenient(text: Optional[str], *, sole_attack: Optional[str] = None) -> Reading:
    """The most any defensible parser could accept — for offline re-scoring only.

    Registered in PREREGISTRATION §7 as C1's upper bound. It is **never** used live.
    Whatever the primary parser accepts is returned unchanged, unless a repair reads
    that same line as a *different* action, which is then offered as the alternative
    (layer 4). Otherwise the candidate lines (the tagged ones, or every line if none is
    tagged) are tried **last first**, with these repairs applied:

    * drop a trailing justification ("… since it's adjacent"; ledger A8);
    * keep the first clause of a two-action line;
    * read a bare ``(x, z)`` pair, or a trailing ``at x, z``, as ground coordinates;
    * add the weapon to an attack that names none, if the creature has exactly one
      (*sole_attack*, passed in as data so this module still never sees the board).

    Trying the last line first is the "last of several differing actions" reading. A
    line that no repair makes readable leaves the primary verdict standing, so the
    bound can only ever add acceptances.
    """
    primary = read_response(text)
    if text is None:
        return primary
    if primary.call is not None:
        # The primary reading stands unless a repair reads the same line differently:
        # "with Dagger since it's adjacent" *parses*, with a weapon the executor will
        # refuse. The alternative is offered, never forced — the re-scorer counts the
        # decision valid if either reading executes, so the bound only adds.
        repaired = _read_command(_repair(primary.line or "", sole_attack))
        if repaired.call is not None and repaired.call != primary.call:
            return Reading(repaired.call, LENIENT_LAYER, primary.line, None, "")
        return primary

    lines = [ln for ln in text.splitlines() if not _FENCE.match(ln)]
    content = [surface(ln) for ln in lines if surface(ln)]
    tagged = [m.group(1) for m in (_TAG.match(ln) for ln in content) if m]
    for line in reversed(tagged or content):
        reading = _read_command(_repair(line, sole_attack))
        if reading.call is not None:
            return Reading(reading.call, LENIENT_LAYER, line, None, "")
    return primary
