"""What one decision cost, and what the model actually said.

The study reports tokens and dollars **per accepted action** (V1_PLAN §3.4), which is
not the same as per request: a decision may take two requests when the model replies
without a tool call and is re-prompted, and the enumerated-menu condition trades a
longer input menu against fewer retries. Recording per *request* and summing is
therefore the honest unit — a single record per decision would under-report cost on
exactly the decisions the study is comparing.

The raw output is kept for the same reason the §3.4 taxonomy exists: "the model
proposed something illegal" is a category, but the failure story that makes the write-up
(§4) is the *text* — fluent reasoning ending in an impossible spatial action. That
cannot be reconstructed from a parsed ``ToolCall``.

**Secrets.** Only the provider's *response* is recorded here, never the request, so a
key cannot reach a transcript by construction. :func:`scrub` is defence in depth for
the case where a model echoes something key-shaped back at us.
"""

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

#: Key shapes worth redacting if a model ever echoes one. Deliberately broad.
_SECRET_PATTERNS = (
    re.compile(r"sk-or-v1-[A-Za-z0-9_-]{8,}"),
    re.compile(r"sk-ant-[A-Za-z0-9_-]{8,}"),
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
)
REDACTED = "[REDACTED]"


def scrub_value(value: Any) -> Any:
    """:func:`scrub` every string inside *value* — lists and dicts, recursively."""
    if isinstance(value, str):
        return scrub(value)
    if isinstance(value, list):
        return [scrub_value(v) for v in value]
    if isinstance(value, dict):
        return {k: scrub_value(v) for k, v in value.items()}
    return value


def scrub(text: Optional[str]) -> Optional[str]:
    """Redact anything key-shaped from *text*."""
    if not text:
        return text
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(REDACTED, text)
    return text


@dataclass
class RequestRecord:
    """One provider request — its cost, its latency, and what came back.

    Every field is optional because providers differ and a flaky one omits things. A
    missing ``usage`` block must never take a match down (the lesson of
    CODEBASE_REVIEW A1), so absent values are ``None``, not an exception.
    """

    latency_ms: float = 0.0
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    #: The model the provider says it served — not the string we asked for. §3.1
    #: requires recording it, because a router may substitute a model silently.
    served_model: Optional[str] = None
    #: The upstream host that served it (OpenRouter routes one model id across hosts,
    #: which may differ in quantisation). A study cell must not mix hosts silently.
    served_provider: Optional[str] = None
    finish_reason: Optional[str] = None
    #: The model's own prose, verbatim (scrubbed). Empty when it only made a call.
    raw_output: Optional[str] = None
    #: The tool call as returned, before parsing — so a malformed one is still visible.
    tool_call: Optional[Dict[str, Any]] = None
    #: Set when the envelope itself was broken (a provider failure, not a decision).
    error: Optional[str] = None
    #: How a text condition read this response: ``{"layer", "line"}`` for an accepted
    #: action, ``{"code", "reason", "line"}`` for a refused one, absent when the
    #: response held no action. The parse layer is what lets C1's validity be
    #: re-scored offline under a stricter or more lenient parser.
    interpretation: Optional[Dict[str, Any]] = None
    #: Tool calls the provider returned beyond the first, which the adapter does not
    #: act on (ledger A5). Recorded so a provider that emits several is visible.
    extra_tool_calls: int = 0
    #: How many *different* calls the response made (identical repeats count once).
    #: More than one is refused in every tool condition, as C1 refuses two different
    #: ACTION lines (prereg §6).
    distinct_tool_calls: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """A JSON-safe record, scrubbed.

        Scrubbing happens **here**, at the serialisation boundary, not in
        ``__post_init__``: adapters fill ``raw_output`` and ``error`` in as they parse
        the response, so a constructor-time scrub would run before the fields it
        guards were set and silently protect nothing. This is the one choke point
        every record passes through on its way out of the process.
        """
        data = asdict(self)
        data["raw_output"] = scrub(self.raw_output)
        data["error"] = scrub(self.error)
        # The raw call and C1's reading both copy the model's own text.
        data["tool_call"] = scrub_value(self.tool_call)
        data["interpretation"] = scrub_value(self.interpretation)
        return data


@dataclass
class DecisionTelemetry:
    """Every request made while deciding one action.

    Usually one; two when the model needed re-prompting. The sums are what the
    cost-per-accepted-action metric divides.
    """

    requests: List[RequestRecord] = field(default_factory=list)
    #: Requests the *provider* failed (an empty envelope, a dropped connection) and
    #: that were retried unchanged. Billed, so counted in the token sums; never seen
    #: by the model, so never in ``requests`` or ``request_count``, which is what
    #: first-attempt validity reads (review 2026-09-24, H-2).
    provider_failures: List[RequestRecord] = field(default_factory=list)
    #: How many legal options the model was shown (menu conditions only) — a cost
    #: covariate the study records per decision (prereg §2).
    menu_length: Optional[int] = None
    #: Whether a length cap removed real options from that menu (it should never).
    menu_truncated: Optional[bool] = None

    @property
    def request_count(self) -> int:
        return len(self.requests)

    @property
    def input_tokens(self) -> Optional[int]:
        """Every input token billed for this decision, failed attempts included."""
        return _sum_or_none(r.input_tokens for r in self._billed())

    @property
    def output_tokens(self) -> Optional[int]:
        return _sum_or_none(r.output_tokens for r in self._billed())

    def _billed(self) -> List[RequestRecord]:
        return [*self.requests, *self.provider_failures]

    @property
    def usage_reported(self) -> bool:
        """Whether this decision's cost is *knowable* — every billed request billed.

        :func:`_sum_or_none` keeps "not reported" apart from zero, but a consumer that
        coerces ``None`` to ``0`` reads an unbilled decision as a free one. That is not
        a rounding error: it silently disables the study's spend cap, which is computed
        from these sums. So the fact is recorded once, here, and the runner refuses to
        keep spending against a cap it can no longer enforce (prereg §5).

        A *partial* report is not knowable either — the sum would be an undercount.

        A provider *failure* is judged differently from a request. A failure that
        reports no usage at all is the ordinary shape of a 429, a dropped connection or
        a 5xx: no response came back to bill, so it counts as nothing spent. Treating
        it as unknown made one transient retry stop a live grid. A failure with
        *partial* counts did come with a response, so it is still unknowable.
        """
        if not self._billed():
            return False
        return all(_fully_reported(r) for r in self.requests) and not any(
            _partly_reported(r) for r in self.provider_failures
        )

    @property
    def latency_ms(self) -> float:
        return sum(r.latency_ms for r in self.requests)

    @property
    def served_model(self) -> Optional[str]:
        """The model that served the last request, if the provider said."""
        for record in reversed(self.requests):
            if record.served_model:
                return record.served_model
        return None

    def to_dict(self) -> Dict[str, Any]:
        """A JSON-safe record for the transcript: the sums, plus each request."""
        return {
            "requests": [r.to_dict() for r in self.requests],
            "provider_failures": [r.to_dict() for r in self.provider_failures],
            "request_count": self.request_count,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "usage_reported": self.usage_reported,
            "latency_ms": round(self.latency_ms, 3),
            "served_model": self.served_model,
            "menu_length": self.menu_length,
            "menu_truncated": self.menu_truncated,
        }


def _fully_reported(record: RequestRecord) -> bool:
    return record.input_tokens is not None and record.output_tokens is not None


def _partly_reported(record: RequestRecord) -> bool:
    return (record.input_tokens is None) != (record.output_tokens is None)


def _sum_or_none(values: Any) -> Optional[int]:
    """Sum *values*, or ``None`` when the provider reported none of them.

    Zero and "not reported" are different facts — a cost metric must not read a
    provider that omits ``usage`` as a free call.
    """
    present = [v for v in values if v is not None]
    return sum(present) if present else None
