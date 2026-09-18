"""Dice rolling utilities.

All randomness in the combat engine flows through a single, context-scoped
RNG (a :class:`random.Random`).  ``dice.py`` is the only module that touches
``random``, so binding a seed here seeds the whole engine.

The active RNG lives in a :class:`~contextvars.ContextVar`, so each battle can
run under its own seeded RNG without the roll call sites (``roll_d20`` &c.)
changing.  Two isolation styles compose:

- :func:`seed_rng` reseeds the *currently bound* RNG in place — the simplest,
  process-wide "make this reproducible" switch (and what tests use).
- :func:`using_rng` binds a *fresh* RNG for the duration of a ``with`` block, so
  a :class:`~src.combat.combat_system.CombatSystem` given its own seed is fully
  isolated from every other battle in the process.  Because each asyncio task
  copies the context, concurrent WebSocket sessions are isolated automatically.
"""

import re
import random
import contextvars
from contextlib import contextmanager
from typing import Iterator, List, Optional, Tuple

# The engine's active RNG. A per-context default keeps today's non-deterministic
# behaviour when nothing binds a seed. Bind a private RNG via using_rng().
_current: contextvars.ContextVar[random.Random] = contextvars.ContextVar(
    "dice_rng", default=random.Random()
)


def _rng() -> random.Random:
    """Return the RNG bound in the current context."""
    return _current.get()


def current_rng() -> random.Random:
    """Return the RNG currently bound in this context.

    Useful for a battle that wants to *inherit* the ambient RNG (rather than
    allocate a private seeded one) so existing seed-the-global callers keep
    working unchanged.
    """
    return _current.get()


def new_rng(seed: Optional[int] = None) -> random.Random:
    """Construct a fresh, independent RNG.

    Args:
        seed: Integer seed for a reproducible stream, or ``None`` for system
            entropy. The returned RNG is not bound anywhere — pass it to
            :func:`using_rng` (or hold it on a battle) to make it active.
    """
    return random.Random(seed)


@contextmanager
def using_rng(rng: random.Random) -> Iterator[random.Random]:
    """Bind *rng* as the active RNG for the duration of the ``with`` block.

    Restores the previously bound RNG on exit, so nested/sequential binds do not
    leak.  Re-binding the same RNG is harmless (idempotent).
    """
    token = _current.set(rng)
    try:
        yield rng
    finally:
        _current.reset(token)


def seed_rng(seed: Optional[int] = None) -> None:
    """Seed the currently bound RNG in place.

    Args:
        seed: Integer seed for a reproducible roll sequence, or ``None`` to
            reseed from system entropy (the default non-deterministic mode).
    """
    _current.get().seed(seed)


def new_id() -> str:
    """Return a fresh entity id drawn from the active RNG.

    Seeded so that a battle run under a bound seed produces the same ids every
    time (ids feed :class:`~src.models.entity.Entity` hashing and tie-breaks).
    64 random bits keep collisions astronomically unlikely.
    """
    return f"{_rng().getrandbits(64):016x}"


def roll_d20() -> int:
    """Roll a d20.

    Returns:
        Random value from 1-20
    """
    return _rng().randint(1, 20)


def roll_dice(num_dice: int, num_sides: int) -> int:
    """Roll multiple dice.

    Args:
        num_dice: Number of dice to roll
        num_sides: Sides on each die

    Returns:
        Sum of all dice rolled
    """
    return sum(_rng().randint(1, num_sides) for _ in range(num_dice))


# Matches tokens like: +2d6, -1d8, +5, -3, 2d6 (leading token, no sign)
_TOKEN_RE = re.compile(r"([+-]?)(\d+)(?:d(\d+))?", re.IGNORECASE)


def parse_dice_formula(formula: str) -> List[Tuple[int, int, bool]]:
    """Parse an arbitrary dice formula like "2d6+1d8+5".

    Each token is returned as ``(signed_count, num_sides, is_dice)``:
      - Dice term (e.g. ``-2d6``): ``is_dice`` is True, ``signed_count`` is the
        signed number of dice, ``num_sides`` is the die size.
      - Flat modifier (e.g. ``+5``): ``is_dice`` is False, ``signed_count`` is
        the signed modifier value, and ``num_sides`` is 0.

    Args:
        formula: Dice formula string, e.g. "2d6+1d8-3" or "1d20+5"

    Returns:
        List of ``(signed_count, num_sides, is_dice)`` tuples.

    Raises:
        ValueError: If the formula contains no valid tokens.
    """
    formula = formula.strip().lower().replace(" ", "")
    tokens = _TOKEN_RE.findall(formula)
    if not tokens:
        raise ValueError(f"Invalid dice formula: {formula!r}")

    result = []
    for sign, number, sides in tokens:
        multiplier = -1 if sign == "-" else 1
        if sides:
            result.append((multiplier * int(number), int(sides), True))
        else:
            result.append((multiplier * int(number), 0, False))
    return result


def roll_formula(formula: str) -> int:
    """Roll an arbitrary dice formula.

    Supports formulas like "2d6+1d8+5" or "1d20-2".

    Args:
        formula: Dice formula string

    Returns:
        Total result
    """
    total = 0
    for count_or_val, sides, is_dice in parse_dice_formula(formula):
        if is_dice:
            sign = -1 if count_or_val < 0 else 1
            total += sign * roll_dice(abs(count_or_val), sides)
        else:
            total += count_or_val
    return total


def multiply_formula(formula: str, multiplier: int) -> str:
    """Multiply the dice counts in a formula by a multiplier.

    Args:
        formula: Dice formula string, e.g. "6d8" or "2d6+3"
        multiplier: Factor to multiply dice counts by

    Returns:
        New formula string with dice counts multiplied, e.g. "12d8" or "4d6+3"
    """

    def replace_token(m: re.Match) -> str:
        sign, number, sides = m.group(1), m.group(2), m.group(3)
        if sides:
            return f"{sign}{int(number) * multiplier}d{sides}"
        return f"{sign}{number}"

    return _TOKEN_RE.sub(replace_token, formula.strip().replace(" ", ""))


def roll_with_advantage() -> int:
    """Roll with advantage (roll twice, take highest).

    Returns:
        The higher of two d20 rolls
    """
    return max(roll_d20(), roll_d20())


def roll_with_disadvantage() -> int:
    """Roll with disadvantage (roll twice, take lowest).

    Returns:
        The lower of two d20 rolls
    """
    return min(roll_d20(), roll_d20())
