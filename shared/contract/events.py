"""Typed Pydantic models for every Hermes SSE event the platform consumes.

Every event Hermes emits onto the SSE stream this platform parses lives here
as a Pydantic v2 ``BaseModel`` with a ``Literal`` discriminator field. The
discriminated union :data:`HermesEvent` lets the stream handler validate raw
JSON event dicts and dispatch on a typed enum-like value rather than free-form
strings.

The models intentionally mirror the wire format Hermes emits at
``agent/hermes/gateway/platforms/myah.py`` and
``agent/hermes/gateway/platforms/api_server.py``. When new fields are added
upstream, prefer making them ``Optional[...] = None`` so unknown-but-non-null
payloads don't fail validation in production: a stricter contract can be
enforced later once the upstream shape is stable.

Discriminator field
-------------------

The wire field is ``event`` (e.g. ``{"event": "message.delta", "delta": "hi"}``).
``HermesEvent`` is therefore an Annotated discriminated union over the
``event`` field. The handler at
``platform/backend/myah/utils/hermes_stream_handler.py`` reads this same
field as the local variable ``event_type``.

Adding a new event
------------------

1. Add a new ``BaseModel`` subclass with a ``Literal["..."]`` discriminator
   value matching the wire string.
2. Add it to the union list in :data:`HermesEvent`.
3. Append it to ``ContractRoot`` in
   ``platform/shared/contract/_codegen_module.py`` so it flows through
   pydantic2ts into ``platform/src/lib/types/contract.ts``.
4. Re-run ``bash platform/scripts/generate-ts-contract.sh``.
5. Add a dispatch branch in ``hermes_stream_handler.py`` if the platform
   should react to it; otherwise the event is just recognised (no warning)
   and ignored.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field


class _BaseHermesEvent(BaseModel):
    """Base config shared by every Hermes event model.

    ``extra='allow'`` lets the model survive when Hermes adds new payload
    fields upstream — the stream handler's existing ``event_data.get(...)``
    paths keep working, and the validation layer doesn't fail-close on
    legitimate new payloads. This is the conservative choice the plan
    explicitly asks for: ``Better to underspecify than to fail-validate a
    real event from production.``
    """

    model_config = ConfigDict(extra='allow')


# ── Stream identity fields shared by every event from gateway/platforms/myah.py
# Every event the Myah adapter pushes carries ``stream_id``, ``run_id`` and
# ``timestamp`` (see _push_event* call sites). The /v1/runs API server emits
# only ``run_id`` (no ``stream_id``); both code paths feed into the same
# stream handler. The fields are therefore optional on the contract — the
# handler doesn't require them.


class MessageDeltaEvent(_BaseHermesEvent):
    """A streamed delta of visible assistant text.

    Wire source: ``myah.py::_stream_delta`` and
    ``api_server.py::_text_cb``.
    """

    event: Literal['message.delta']
    delta: str
    run_id: str | None = None
    stream_id: str | None = None
    timestamp: float | None = None


class ReasoningDeltaEvent(_BaseHermesEvent):
    """Real-time reasoning token from the model's chain-of-thought channel.

    Wire source: ``myah.py::_reasoning`` and
    ``api_server.py::_reasoning_cb``. Also emitted by ``_format_tool_event``
    for the legacy ``"_thinking"`` callback shape.
    """

    event: Literal['reasoning.delta']
    text: str
    run_id: str | None = None
    stream_id: str | None = None
    timestamp: float | None = None


class ReasoningAvailableEvent(_BaseHermesEvent):
    """Post-hoc reasoning snapshot for XML-scratchpad models.

    Wire source: ``api_server.py::_make_run_event_callback`` and
    ``myah.py::_format_tool_event`` (``reasoning.available`` branch).
    """

    event: Literal['reasoning.available']
    text: str
    run_id: str | None = None
    stream_id: str | None = None
    timestamp: float | None = None


class ToolStartedEvent(_BaseHermesEvent):
    """A tool invocation has begun.

    Wire sources differ slightly between the API server and the Myah adapter:

    * ``api_server.py`` packs ``args`` as a stringified JSON snippet
      (``str(args)[:500]``) — pydantic accepts both ``dict`` and ``str``
      because ``args`` is typed as ``Any``.
    * ``myah.py`` packs ``args`` as a ``dict`` (or ``{}``).

    The ``tool`` field is the human-facing tool name used by the agent (e.g.
    ``shell_exec``); ``call_id`` is the upstream's correlation identifier so
    ``tool.completed`` can be matched back to the matching ``tool.started``.
    """

    event: Literal['tool.started']
    tool: str
    call_id: str | None = None
    args: Any = None
    preview: str | None = None
    run_id: str | None = None
    stream_id: str | None = None
    timestamp: float | None = None


class ToolCompletedEvent(_BaseHermesEvent):
    """A tool invocation has finished (successfully or with an error).

    The ``error`` field carries a boolean flag (not the error message
    itself); ``result`` carries the tool's stringified output, truncated by
    the upstream emitter.

    Wire sources: ``api_server.py::_make_run_event_callback`` and
    ``myah.py::_format_tool_event``.
    """

    event: Literal['tool.completed']
    tool: str
    call_id: str | None = None
    args: Any = None
    result: Any = None
    duration: float | None = None
    error: bool = False
    run_id: str | None = None
    stream_id: str | None = None
    timestamp: float | None = None


class ToolConfirmationRequiredEvent(_BaseHermesEvent):
    """The agent is blocked waiting for user approval of a dangerous action.

    Wire sources: ``myah.py::send_exec_approval`` and
    ``api_server.py::_confirmation_notify`` (which forwards the approval
    payload from ``tools.approval`` largely as-is). The ``options`` list is
    typed as ``list[str]`` because the wire vocabulary is fixed today
    (``approve``, ``deny``, ``approve_session``) but the formal enum lives
    in Phase 3 of Workstream I, not here.
    """

    event: Literal['tool.confirmation_required']
    confirmation_id: str
    action_type: str = 'confirmation'
    description: str = ''
    options: list[str] = Field(default_factory=lambda: ['approve', 'deny'])
    metadata: dict[str, Any] = Field(default_factory=dict)
    run_id: str | None = None
    stream_id: str | None = None
    timestamp: float | None = None


class SecretRequiredEvent(_BaseHermesEvent):
    """The agent has paused waiting for the user to supply a secret value.

    Wire source: ``myah.py::_secret_capture_callback``.
    """

    event: Literal['secret.required']
    var_name: str
    prompt: str = ''
    help: str = ''
    skill_name: str = ''
    run_id: str | None = None
    stream_id: str | None = None
    timestamp: float | None = None


class SecretResolvedEvent(_BaseHermesEvent):
    """The pending secret prompt has been answered (or timed out).

    Wire source: ``myah.py::_secret_capture_callback`` (success +
    timeout branches). The ``status`` field carries either ``stored`` or
    ``timeout`` today; reserved values are accepted via ``extra='allow'``.
    """

    event: Literal['secret.resolved']
    var_name: str
    status: str = 'stored'
    run_id: str | None = None
    stream_id: str | None = None
    timestamp: float | None = None


class RunCompletedEvent(_BaseHermesEvent):
    """The agent run finished successfully.

    Carries optional final ``output`` text (the API server emits it; the
    Myah adapter does not because tokens already streamed via
    ``message.delta``), the ``usage`` accounting dict, and the Myah-only
    ``model``/``provider`` attribution fields used for per-message badges.

    Wire sources: ``myah.py::_dispatch_message`` finally branch and
    ``api_server.py::_run_and_close``.
    """

    event: Literal['run.completed']
    output: str | None = None
    usage: dict[str, Any] | None = None
    model: str | None = None
    provider: str | None = None
    run_id: str | None = None
    stream_id: str | None = None
    timestamp: float | None = None


class RunFailedEvent(_BaseHermesEvent):
    """The agent run terminated with an error.

    Wire sources: ``myah.py::_dispatch_message`` (multiple branches) and
    ``api_server.py::_run_and_close``.
    """

    event: Literal['run.failed']
    error: str = 'Agent run failed'
    run_id: str | None = None
    stream_id: str | None = None
    timestamp: float | None = None


class RunCancelledEvent(_BaseHermesEvent):
    """The agent run was cancelled (e.g., user-initiated stop or upstream
    asyncio.CancelledError during streaming).

    Hermes emits this from gateway/platforms/api_server.py:3122 when an
    asyncio.CancelledError fires inside the run loop. The platform marks
    the run as cancelled in the chat record so the UI shows a cancelled
    state instead of leaving the message stuck mid-stream.
    """

    event: Literal['run.cancelled']
    run_id: str | None = None
    stream_id: str | None = None
    timestamp: float | None = None


class StatusEvent(_BaseHermesEvent):
    """Free-form status hint emitted by the Myah adapter.

    The platform stream handler does not currently react to ``status``
    events — they're typed here so the new validation layer recognises
    them as well-formed Hermes events rather than logging a warning. If
    the platform later wants to surface them in the UI, the model is
    already in place.

    Wire sources: ``myah.py::_status``, ``myah.py::_format_tool_event``
    fallback branch, and ``myah.py::_handle_message`` (typing indicator).
    """

    event: Literal['status']
    text: str | None = None
    status: str | None = None
    run_id: str | None = None
    stream_id: str | None = None
    timestamp: float | None = None


# ── Discriminated union ──────────────────────────────────────────────────────
#
# Pydantic v2 narrows on the literal value of the ``event`` field. Validation
# fails (with a ``ValidationError``) when the field is missing entirely or
# carries an unknown literal — both situations the stream handler treats as
# "log a warning and continue" rather than aborting the run.

# A type alias built from individual Union members, written across multiple
# lines for readability. Ruff's UP007 prefers ``X | Y`` syntax but on a union
# this wide it produces a 230+ character line that fails E501; ``Union[...]``
# stays under the 120-char limit and renders one event per line.
HermesEvent = Annotated[
    Union[  # noqa: UP007
        MessageDeltaEvent,
        ReasoningDeltaEvent,
        ReasoningAvailableEvent,
        ToolStartedEvent,
        ToolCompletedEvent,
        ToolConfirmationRequiredEvent,
        SecretRequiredEvent,
        SecretResolvedEvent,
        RunCompletedEvent,
        RunFailedEvent,
        RunCancelledEvent,
        StatusEvent,
    ],
    Field(discriminator='event'),
]


__all__ = [
    'HermesEvent',
    'MessageDeltaEvent',
    'ReasoningAvailableEvent',
    'ReasoningDeltaEvent',
    'RunCancelledEvent',
    'RunCompletedEvent',
    'RunFailedEvent',
    'SecretRequiredEvent',
    'SecretResolvedEvent',
    'StatusEvent',
    'ToolCompletedEvent',
    'ToolConfirmationRequiredEvent',
    'ToolStartedEvent',
]
