"""How a written name is matched to the thing it names — forgiving of spelling only.

Under the raw-parameter conditions a model must *write* identifiers: an entity id to
name a target, an attack or spell name to name an action. ``Raider 1``, ``raider-1``
and ``RAIDER_1`` all name the same creature to any reader, and refusing two of them
would charge the interface a transcription cost that has nothing to do with the
decision being measured — the same reasoning that made entity ids readable in the
first place (prereg §4.2).

**One resolver, shared.** The executor resolves every raw-parameter call through
:func:`resolve`, and the free-text parser (C1) hands its names to the same executor,
so no condition gets a tolerance another lacks.

**Spelling, never identity.** Matching compares a normalised *key* — case, spacing,
punctuation and Unicode lookalikes removed — and nothing looser. There is deliberately
no edit distance: ``raider-3`` stays unknown rather than becoming ``raider-2``, because
that would silently repair a hallucination the study counts (C3's ``interpret`` refuses
near-misses for the same reason). Two things sharing a key are reported as ambiguous
rather than guessed between.
"""

import re
import unicodedata
from typing import List, Sequence, Tuple, TypeVar

T = TypeVar("T")

_NON_ALNUM = re.compile(r"[^0-9a-z]+")


def identifier_key(written: str) -> str:
    """Reduce *written* to its matching key: ``"Raider 1"`` → ``"raider1"``.

    NFKC first, so typographic lookalikes (en dashes, non-breaking spaces, full-width
    letters) fold to their plain forms before anything is stripped.
    """
    folded = unicodedata.normalize("NFKC", str(written)).casefold()
    return _NON_ALNUM.sub("", folded)


def resolve(written: str, tiers: Sequence[Sequence[Tuple[str, T]]]) -> List[T]:
    """Return everything *written* could name, in order of how directly it names it.

    *tiers* lists ``(label, item)`` pairs, most authoritative first — for creatures,
    ids before display names. An **exact** spelling anywhere wins outright, so an
    identifier that already worked keeps working unchanged. Failing that, the first
    tier with any key match decides: one match is the answer, several are an
    ambiguity for the caller to refuse. Empty means nothing is named.
    """
    for tier in tiers:
        for label, item in tier:
            if label == written:
                return [item]

    key = identifier_key(written)
    if not key:
        return []  # punctuation alone names nothing
    for tier in tiers:
        matches: List[T] = []
        for label, item in tier:
            if identifier_key(label) == key and not any(m is item for m in matches):
                matches.append(item)
        if matches:
            return matches
    return []
