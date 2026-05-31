"""Typed Pydantic models for every Hermes output item the renderer consumes.

The platform's stream handler (``platform/backend/myah/utils/hermes_stream_handler.py``)
normalises the SSE event flow into a flat ``output: list[OutputItem]`` array
attached to every assistant message. The frontend renderer
(``platform/src/lib/components/chat/Messages/HermesOutputRenderer.svelte`` and its
subcomponents) consumes that array and dispatches on each item's ``type`` field
to render the right card.

This module is the single source of truth for those shapes. TypeScript
interfaces are generated from these models via
``platform/scripts/generate-ts-contract.sh``; the result lands at
``platform/src/lib/types/contract.ts``. The HermesOutputRenderer's local
``types.ts`` re-exports those interfaces under their existing TS names so no
prop signature has to change.

Adding a new output item type
-----------------------------

1. Add a new ``BaseModel`` subclass with a ``Literal["..."]`` discriminator
   value matching the wire string.
2. Add it to the union list in :data:`OutputItem`.
3. Append it to ``ContractRoot`` in
   ``platform/shared/contract/_codegen_module.py`` so it flows through
   pydantic2ts into ``platform/src/lib/types/contract.ts``.
4. Re-run ``bash platform/scripts/generate-ts-contract.sh``.
5. Add a frontend re-export entry in
   ``platform/src/lib/components/chat/Messages/HermesOutputRenderer/types.ts``
   if the TS-side renderer needs the type by a different historical name.

Wire-format origins
-------------------

The handler at ``hermes_stream_handler.py`` constructs every item shape; the
canonical references are:

* ``message`` — line 208
* ``reasoning`` — lines 431, 635
* ``function_call`` — line 527
* ``function_call_output`` — line 552
* ``confirmation`` — line 663
* ``secret_input`` — line 690
* ``myah:code_interpreter`` — built by ``utils/middleware.py:1994`` for
  the legacy code-interpreter pass-through; no Hermes equivalent today.

Field shapes mirror the existing TypeScript interfaces in
``platform/src/lib/components/chat/Messages/HermesOutputRenderer/types.ts``
(pre-Phase-4) so the frontend migration is a no-op rename.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field


class _BaseOutputItem(BaseModel):
    """Base config shared by every output item model.

    ``extra='allow'`` keeps validation tolerant of new fields the stream
    handler may attach. The renderer subcomponents already use defensive
    access (``item.field ?? default``) so unknown-but-non-null fields are
    safe; the contract reflects that intent rather than fail-validating
    real production payloads.
    """

    model_config = ConfigDict(extra='allow')


# ── Sub-part shapes ─────────────────────────────────────────────────────────
# Output items embed structured "content parts" (analogous to OpenAI's
# response API) inside ``content`` / ``output`` / ``summary`` arrays. These
# helper models give the generated TS file proper interfaces for each part
# rather than emitting an inline ``{ type: 'output_text', text: string }``
# every time.


class OutputTextPart(_BaseOutputItem):
    """A plain visible-text part inside an assistant message.

    Wire source: ``hermes_stream_handler.py::_get_or_create_message_item``
    (line 213) and the streaming append loop (line 442).
    """

    type: Literal['output_text']
    text: str


class InputTextPart(_BaseOutputItem):
    """A plain text part inside a tool-result payload.

    Wire source: ``hermes_stream_handler.py::tool.completed`` branch at
    line 555 (``output: [{'type': 'input_text', 'text': result_text}]``).
    """

    type: Literal['input_text']
    text: str


class SummaryTextPart(_BaseOutputItem):
    """A text part inside a reasoning item's summary array.

    Wire source: ``hermes_stream_handler.py::reasoning.delta`` branch at
    line 638 (the initial empty summary entry) and append at line 644.
    """

    type: Literal['summary_text']
    text: str


# ── Output items ────────────────────────────────────────────────────────────


class MessageItem(_BaseOutputItem):
    """An assistant (or user) message item with one or more text parts.

    The ``role`` field is ``"assistant"`` for normal stream output but the
    handler also writes user messages into the same shape when re-rendering
    a chat from the DB. The status transitions ``in_progress`` -> ``completed``
    when the run ends or a tool call closes the current message.

    Wire source: ``hermes_stream_handler.py:208`` (``_get_or_create_message_item``).
    """

    type: Literal['message']
    id: str
    status: Literal['in_progress', 'completed']
    role: str
    # Required to match the existing TS interface — the handler always
    # initialises this to ``[{'type': 'output_text', 'text': ''}]`` at
    # item creation, so the field is never absent on the wire.
    content: list[OutputTextPart]


class FunctionCallItem(_BaseOutputItem):
    """A tool invocation in the output stream.

    ``arguments`` is stored as a JSON string (not a parsed dict) because the
    upstream handler serialises with ``json.dumps`` at
    ``hermes_stream_handler.py:505`` to keep the wire format stable across
    parses. Frontend code re-parses on demand.

    Wire source: ``hermes_stream_handler.py:527`` (``tool.started`` branch).
    The status transitions ``in_progress`` -> ``completed`` (or ``failed``)
    when the matching ``tool.completed`` event arrives.
    """

    type: Literal['function_call']
    id: str
    call_id: str
    name: str
    arguments: str
    status: Literal['in_progress', 'completed', 'failed']


class FunctionCallOutputItem(_BaseOutputItem):
    """The result of a tool invocation.

    ``status`` is typed as ``str`` (not a Literal union) because the upstream
    handler hardcodes ``"completed"`` today but the frontend only treats it
    as a display hint; future Hermes versions could emit other values.

    Wire source: ``hermes_stream_handler.py:552`` (``tool.completed`` branch).
    """

    type: Literal['function_call_output']
    id: str
    call_id: str
    # Required to match the existing TS interface — the handler always
    # initialises this to ``[{'type': 'input_text', 'text': result_text}]``
    # at line 555 of ``hermes_stream_handler.py``.
    output: list[InputTextPart]
    status: str


class ReasoningItem(_BaseOutputItem):
    """A chain-of-thought / reasoning summary item.

    The ``duration`` field is set when the reasoning block completes (either
    by a subsequent tool call closing the in-flight reasoning at
    ``hermes_stream_handler.py:520`` or by run completion). It is rendered as
    the seconds shown in the ``Thought for N seconds`` chip.

    Wire source: ``hermes_stream_handler.py:635`` (``reasoning.delta``
    branch's create-on-first-delta path).
    """

    type: Literal['reasoning']
    id: str
    status: Literal['in_progress', 'completed']
    # Required to match the existing TS interface — the handler always
    # creates with at least the empty initial summary part at line 638.
    summary: list[SummaryTextPart]
    duration: float | None = None


class CodeInterpreterOutputPayload(_BaseOutputItem):
    """The structured payload attached to a code_interpreter item's output.

    The legacy upstream Open WebUI code-interpreter writes any of ``result``,
    ``error``, or ``output`` into a free-form dict; the contract carries them
    explicitly so the generated TS interface narrows correctly.
    """

    result: str | None = None
    error: str | None = None
    output: str | None = None


class CodeInterpreterItem(_BaseOutputItem):
    """A Myah-only legacy code-interpreter pass-through item.

    Hermes does not emit this today (the canonical tool-call flow uses
    ``function_call`` + ``function_call_output``). The platform retains the
    item shape because pre-Hermes message history may carry it and the
    frontend renders it via ``CodeExecutionBlock.svelte``. Once all legacy
    chat history is migrated this entire item type can be retired; until
    then, the contract documents its shape.

    Wire source: ``utils/middleware.py:1994`` (legacy code-interpreter
    branch in the OpenAI-routing path, not the Hermes path).
    """

    type: Literal['myah:code_interpreter']
    id: str
    code: str
    lang: str
    status: Literal['in_progress', 'completed']
    duration: float | None = None
    output: CodeInterpreterOutputPayload | None = None


class ConfirmationItem(_BaseOutputItem):
    """An approval card waiting on user response.

    ``status`` transitions ``pending`` -> ``resolved`` (user picked an
    option) or ``cancelled`` (run aborted before resolution). The ``chosen``
    field carries the option ID the user selected — its allowed values come
    from Phase 3's ``ApprovalOption`` enum (``approve``, ``deny``,
    ``approve_session``); typed here as ``str`` because Phase 3 had not
    landed at the time Phase 4 was authored.

    Wire source: ``hermes_stream_handler.py:663``
    (``tool.confirmation_required`` branch).
    """

    type: Literal['confirmation']
    id: str
    confirmation_id: str
    run_id: str
    action_type: str
    description: str
    # Required to match the existing TS interface — the handler always
    # provides values (see ``hermes_stream_handler.py:659-660``).
    options: list[str]
    metadata: dict[str, Any]
    status: Literal['pending', 'resolved', 'cancelled']
    chosen: str | None = None


class SecretInputItem(_BaseOutputItem):
    """A secret-prompt card waiting on user input.

    ``status`` transitions ``pending`` -> ``stored`` (user supplied the
    secret) or ``timeout`` (poll expired). The ``help`` field carries either
    a URL or a freeform hint string — frontends should treat it as
    untrusted display text.

    Wire source: ``hermes_stream_handler.py:690`` (``secret.required``
    branch). Status updates land in the same item via the
    ``secret.resolved`` branch at line 711.
    """

    type: Literal['secret_input']
    id: str
    run_id: str
    var_name: str
    prompt: str
    help: str
    skill_name: str
    status: Literal['pending', 'stored', 'timeout']


class TodoPlanEntry(BaseModel):
    """One item from Hermes' ``todo`` tool result.

    Nested entries deliberately are not output items and therefore do not
    carry a ``type`` discriminator. They mirror the stable Hermes todo shape:
    ``{id, content, status}``.
    """

    id: str
    content: str
    status: Literal['pending', 'in_progress', 'completed', 'cancelled']


class TodoPlanItem(_BaseOutputItem):
    """Pinned plan/checklist state derived from Hermes ``todo`` tool output.

    Wire source: ``hermes_stream_handler.py`` successful ``tool.completed``
    branch for ``tool == 'todo'``. The handler parses the tool result JSON and
    upserts a single latest plan item so the frontend can render a first-class
    pinned strip instead of a generic function-call row.
    """

    type: Literal['todo_plan']
    id: str
    call_id: str
    title: str = 'Plan'
    todos: list[TodoPlanEntry]
    status: Literal['in_progress', 'completed']
    updated_at: float | None = None


class ArtifactCardItem(_BaseOutputItem):
    """Inline artifact preview card attached to an assistant message.

    Replaces the legacy ``hermes:artifact`` socket event broadcast — the
    artifact reference is now part of the message itself, so it survives
    DB persistence + reload without re-running an SSE consumer.

    Wire source: ``hermes_stream_handler.py`` (post-run persisted-files
    branch + the in-flight ``tool.completed`` branch). Either ``file_id``
    (when the file was persisted into Myah storage) or ``path`` (when the
    artifact lives only inside the agent container) MUST be present so
    the renderer can fetch content.
    """

    type: Literal['artifact_card']
    id: str
    file_id: str | None = None
    path: str | None = None
    filename: str
    mime: str | None = None
    mtime: float = 0.0
    kind: Literal[
        'xlsx',
        'csv',
        'docx',
        'markdown',
        'code',
        'image',
        'video',
        'pdf',
        'pptx',
        'html',
        'json',
        'audio',
        'text',
        'sqlite',
    ]
    summary: str | None = None
    preview: dict | list | str | None = None


# ── Discriminated union ─────────────────────────────────────────────────────
#
# Pydantic v2 narrows on the ``type`` field literal value. Validation fails
# when the field is missing or carries an unknown literal — the renderer's
# defensive code path skips unknown items rather than crashing the chat,
# but the contract still flags new types via the completeness tests.

OutputItem = Annotated[
    Union[  # noqa: UP007  same Union[..] reasoning as events.py
        MessageItem,
        FunctionCallItem,
        FunctionCallOutputItem,
        ReasoningItem,
        CodeInterpreterItem,
        ConfirmationItem,
        SecretInputItem,
        TodoPlanItem,
        ArtifactCardItem,
    ],
    Field(discriminator='type'),
]


__all__ = [
    'ArtifactCardItem',
    'CodeInterpreterItem',
    'CodeInterpreterOutputPayload',
    'ConfirmationItem',
    'FunctionCallItem',
    'FunctionCallOutputItem',
    'InputTextPart',
    'MessageItem',
    'OutputItem',
    'OutputTextPart',
    'ReasoningItem',
    'SecretInputItem',
    'SummaryTextPart',
    'TodoPlanEntry',
    'TodoPlanItem',
]
