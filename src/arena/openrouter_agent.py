"""OpenRouter adapter — a provider-neutral Agent backed by any OpenRouter model.

Talks to OpenRouter's OpenAI-compatible Chat Completions API (its documented
client) via the ``openai`` SDK pointed at https://openrouter.ai/api/v1. All
prompt/notes/one-action-loop logic is shared with the Claude adapter through
:mod:`src.arena.llm_common`; only the request and the tool-schema envelope differ.
This lets us pit **free** models (e.g. NVIDIA Nemotron) against Claude or the
scripted baseline — cheap experimentation, and a way to surface where weaker models
fail. Wiring and the git-ignored key file are in
``docs/current/AGENT_ARENA_LLM_SETUP.md``.

Note: not every free model supports function/tool calling. Pick a tool-capable one
(OpenRouter's "Tools" filter). A model that can't will make no tool call —
:func:`llm_common.decide_one_action` retries once, then fails loudly, which is
exactly how a flaw surfaces.
"""

import time
from types import ModuleType
from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.arena.agent import Agent, ProviderError
from src.arena.credentials import resolve_credential
from src.arena.interfaces import C2_MENU, ActionInterface, get_interface
from src.arena.llm_common import (
    decide_one_action,
    decode_arguments,
    distinct_call_count,
)
from src.arena.telemetry import RequestRecord
from src.arena.tools import ToolCall

# Declared Optional up front so the ImportError fallback below type-checks.
openai: Optional[ModuleType]
try:  # optional dependency — only this module needs it (pip install -e ".[agents]")
    import openai
except ImportError:  # pragma: no cover - exercised via the missing-dep message
    openai = None

DEFAULT_MODEL = (
    "nvidia/nemotron-nano-9b-v2:free"  # free + tool-capable; override with --model
)
DEFAULT_MAX_TOKENS = 4096
# V1_PLAN §3.2 holds sampling at the provider minimum and records it. Still not
# deterministic — the study says so rather than claiming otherwise.
DEFAULT_TEMPERATURE = 0.0
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
# Optional OpenRouter attribution headers (harmless; used only for their leaderboards).
_RANKING_HEADERS = {
    "HTTP-Referer": "https://github.com/Nitrix119/arbiter-arena",
    "X-Title": "Arbiter Arena",
}


def _served_provider(response: Any) -> Optional[str]:
    """The upstream host OpenRouter routed this request to, if the response says.

    OpenRouter adds a ``provider`` field the OpenAI SDK keeps as an extra attribute.
    """
    provider = getattr(response, "provider", None)
    if provider is None:
        provider = (getattr(response, "model_extra", None) or {}).get("provider")
    return str(provider) if provider else None


def _to_openai_tools(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Neutral ``{name, description, input_schema}`` → OpenAI function-tool envelope."""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t["input_schema"],
            },
        }
        for t in tools
    ]


def _usage(response: Any) -> Tuple[Optional[int], Optional[int]]:
    """``(input_tokens, output_tokens)`` from an OpenAI-style ``usage`` block.

    Either may be ``None``: "not reported" is not "zero", and a provider that omits
    ``usage`` must not read as a free call in the cost metric.
    """
    usage = getattr(response, "usage", None)
    return (
        getattr(usage, "prompt_tokens", None),
        getattr(usage, "completion_tokens", None),
    )


def _first_message(response: Any, model: str, record: RequestRecord) -> Any:
    """Return the first choice's message, or refuse as a *provider* failure.

    A free host under load answers with an error body or an empty payload rather than
    a completion, and ``response.choices[0]`` on that raises ``TypeError`` mid-match
    (observed live, 2026-09-15). A four-day background grid cannot die on one flaky
    response, so this is a counted, recorded failure instead — and one tagged as
    infrastructure, since the model never got to make a choice. *record* travels with
    the error so the failed request's latency is not lost.
    """
    choices = getattr(response, "choices", None)
    if not choices:
        detail = getattr(response, "error", None)
        message = (
            f"{model}: the provider returned no choices"
            + (f" ({detail})" if detail else "")
            + " — an empty or error payload, not a model decision."
        )
        record.error = message
        raise ProviderError(message, record=record)
    message_obj = getattr(choices[0], "message", None)
    if message_obj is None:
        message = f"{model}: the provider returned a choice with no message."
        record.error = message
        raise ProviderError(message, record=record)
    return message_obj


class OpenRouterAgent(Agent):
    """Drives a team by asking an OpenRouter model for one action at a time via
    tool use."""

    def __init__(
        self,
        name: str,
        team: Optional[str] = None,
        *,
        model: str = DEFAULT_MODEL,
        temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        interface: Optional[ActionInterface] = None,
        client: Any = None,
        hosts: Sequence[str] = (),
        seed: Optional[int] = None,
        reasoning: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(name, team)
        if client is None:
            if openai is None:
                raise ImportError(
                    "OpenRouterAgent needs the 'openai' package. Install it with "
                    '`pip install -e ".[agents]"` (see '
                    "docs/current/AGENT_ARENA_LLM_SETUP.md)."
                )
            api_key = resolve_credential("OPENROUTER_API_KEY", "openrouter.key")
            client = openai.OpenAI(base_url=OPENROUTER_BASE_URL, api_key=api_key)
        self._client = client
        #: Upstream hosts allowed to serve the model, in order, fallbacks off. Empty
        #: leaves routing to OpenRouter — recorded per request either way.
        self.hosts = tuple(hosts)
        #: Sampling seed, forwarded to hosts that honour it (the match's seed).
        self.seed = seed
        #: OpenRouter's ``reasoning`` setting for a thinking model (e.g.
        #: ``{"effort": "low"}``). Pinned by the grid rather than left to host
        #: defaults, which can differ; ``None`` sends nothing.
        self.reasoning = dict(reasoning) if reasoning is not None else None
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        #: The study condition. Held on the agent, not passed by the turn driver:
        #: which interface a model is given is the thing under test, and the driver
        #: must stay ignorant of it.
        self.interface = interface or get_interface(C2_MENU)

    def decide(self, observation: Dict[str, Any]) -> ToolCall:
        return decide_one_action(
            self._request_action, self, observation, self.interface
        )

    def _request_action(
        self, messages: List[Dict[str, Any]], api_tools: List[Dict[str, Any]]
    ) -> Tuple[Optional[ToolCall], RequestRecord]:
        """One OpenRouter (chat-completions) request; return its tool call and cost."""
        system = self.interface.system_prompt()
        oai_messages = [{"role": "system", "content": system}, *messages]
        # A text condition (C1) offers no tools, and the API refuses `tool_choice`
        # without `tools` — so both are omitted rather than sent empty.
        tool_fields: Dict[str, Any] = {}
        if api_tools:
            # One action per response, as every condition's prompt asks. Hosts that
            # honour this return one call; any that still send several different
            # ones are refused by the interface, exactly as C1 refuses two lines.
            tool_fields = {
                "tools": _to_openai_tools(api_tools),
                "tool_choice": "auto",
                "parallel_tool_calls": False,
            }
        extra_body: Dict[str, Any] = {}
        if self.hosts:
            extra_body["provider"] = {
                "order": list(self.hosts),
                "allow_fallbacks": False,
            }
        if self.reasoning is not None:
            extra_body["reasoning"] = dict(self.reasoning)
        if extra_body:
            tool_fields["extra_body"] = extra_body
        if self.seed is not None:
            tool_fields["seed"] = self.seed
        started = time.perf_counter()
        response = self._client.chat.completions.create(
            model=self.model,
            messages=oai_messages,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            extra_headers=_RANKING_HEADERS,
            **tool_fields,
        )
        input_tokens, output_tokens = _usage(response)
        record = RequestRecord(
            latency_ms=(time.perf_counter() - started) * 1000.0,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            # The router may serve a different model than the one asked for, so record
            # what actually answered (§3.1), not what we requested.
            served_model=getattr(response, "model", None),
            served_provider=_served_provider(response),
        )

        message = _first_message(response, self.model, record)
        record.raw_output = getattr(message, "content", None) or None
        choice = response.choices[0]
        record.finish_reason = getattr(choice, "finish_reason", None)

        tool_calls = getattr(message, "tool_calls", None) or []
        record.extra_tool_calls = max(0, len(tool_calls) - 1)
        record.distinct_tool_calls = distinct_call_count(
            (tc.function.name, tc.function.arguments) for tc in tool_calls
        )
        for tc in tool_calls:
            fn = tc.function
            arguments = fn.arguments
            record.tool_call = {"name": fn.name, "arguments": arguments}
            args = decode_arguments(fn.name, arguments, record)
            return ToolCall(fn.name, args, call_id=getattr(tc, "id", None)), record
        return None, record
