"""Tests for the Hermes SSE event Pydantic models.

These tests exercise the contract surface the platform's stream handler
depends on: every event type Hermes is known to emit must validate
against :data:`HermesEvent`, the discriminated union must dispatch to the
correct concrete class, and unrecognised event types must fail
validation so the handler can log a warning and continue.
"""
from __future__ import annotations

from typing import get_args

import pytest
from pydantic import TypeAdapter, ValidationError

from shared.contract.events import (
    ApprovalRequestEvent,
    ApprovalRespondedEvent,
    ClarifyRequiredEvent,
    ClarifyResolvedEvent,
    HermesEvent,
    MessageDeltaEvent,
    ReasoningAvailableEvent,
    ReasoningDeltaEvent,
    RunCancelledEvent,
    RunCompletedEvent,
    RunFailedEvent,
    SecretRequiredEvent,
    SecretResolvedEvent,
    StatusEvent,
    ToolCompletedEvent,
    ToolConfirmationRequiredEvent,
    ToolStartedEvent,
)
from shared.contract.samples import EVENT_SAMPLES

# A single TypeAdapter avoids re-building the discriminated union machinery on
# every test invocation. Pydantic v2 caches schema compilation under the hood
# so this is purely a readability optimisation.
_HERMES_EVENT_ADAPTER: TypeAdapter[HermesEvent] = TypeAdapter(HermesEvent)


EVENT_SAMPLE_CLASSES: dict[str, type] = {
    'approval.request': ApprovalRequestEvent,
    'approval.responded': ApprovalRespondedEvent,
    'clarify.required': ClarifyRequiredEvent,
    'clarify.resolved': ClarifyResolvedEvent,
    'message.delta': MessageDeltaEvent,
    'reasoning.available': ReasoningAvailableEvent,
    'reasoning.delta': ReasoningDeltaEvent,
    'run.cancelled': RunCancelledEvent,
    'run.completed': RunCompletedEvent,
    'run.failed': RunFailedEvent,
    'secret.required': SecretRequiredEvent,
    'secret.resolved': SecretResolvedEvent,
    'status': StatusEvent,
    'tool.completed': ToolCompletedEvent,
    'tool.confirmation_required': ToolConfirmationRequiredEvent,
    'tool.started': ToolStartedEvent,
}


def _contract_event_literals() -> set[str]:
    """Return the set of ``event`` literal values declared by ``HermesEvent``."""
    annotated_args = get_args(HermesEvent)
    union_type = annotated_args[0]
    event_classes = get_args(union_type)
    literals: set[str] = set()
    for cls in event_classes:
        for value in get_args(cls.model_fields['event'].annotation):
            if isinstance(value, str):
                literals.add(value)
    return literals


# ── Per-event validation ────────────────────────────────────────────────────


@pytest.mark.parametrize('event_type,payload', sorted(EVENT_SAMPLES.items()))
def test_each_event_validates_against_union(event_type: str, payload: dict) -> None:
    """Every reusable event sample must validate as the matching model.

    Failure here means the contract has drifted from the upstream wire
    format — either Hermes added a required field we don't know about, or
    we accidentally tightened the schema. Either way the stream handler's
    new validation layer would reject real production traffic.
    """
    expected_class = EVENT_SAMPLE_CLASSES[event_type]
    instance = _HERMES_EVENT_ADAPTER.validate_python(payload)
    assert isinstance(instance, expected_class), (
        f'discriminator dispatch failed for {event_type!r}: '
        f'got {type(instance).__name__}, expected {expected_class.__name__}'
    )


def test_completeness_every_known_event_has_a_sample() -> None:
    """Every concrete event class must appear in reusable ``EVENT_SAMPLES``.

    This guards against a class being added to ``events.py`` and the
    union without a corresponding sample payload being added to the shared
    sample matrix. Without this check, new events would silently skip
    validation testing.
    """
    sampled_events = set(EVENT_SAMPLES)
    declared_events = set(EVENT_SAMPLE_CLASSES)
    assert sampled_events == declared_events, (
        f'Event sample drift: missing samples for {sorted(declared_events - sampled_events)}; '
        f'unexpected samples for {sorted(sampled_events - declared_events)}'
    )
    assert 'run.cancelled' in EVENT_SAMPLES


def test_every_hermes_event_union_literal_has_a_sample() -> None:
    """Every ``HermesEvent`` discriminator literal must have reusable sample data."""
    sampled_events = set(EVENT_SAMPLES)
    union_events = _contract_event_literals()
    assert sampled_events == union_events, (
        f'HermesEvent sample drift: missing samples for {sorted(union_events - sampled_events)}; '
        f'unexpected samples for {sorted(sampled_events - union_events)}'
    )


# ── Discriminator behaviour ─────────────────────────────────────────────────

def test_unknown_event_type_fails_validation() -> None:
    """An unrecognised ``event`` value must raise ``ValidationError``.

    The stream handler relies on this so it can log a warning and skip
    the event rather than dispatching against a half-validated payload.
    """
    payload = {'event': 'gibberish.unknown', 'foo': 'bar'}
    with pytest.raises(ValidationError):
        _HERMES_EVENT_ADAPTER.validate_python(payload)


def test_missing_event_field_fails_validation() -> None:
    """A payload without the discriminator field must fail validation."""
    payload: dict = {'delta': 'Hello'}
    with pytest.raises(ValidationError):
        _HERMES_EVENT_ADAPTER.validate_python(payload)


def test_extra_fields_are_allowed() -> None:
    """Unknown payload fields must be tolerated, not rejected.

    Hermes may ship new fields upstream before the platform knows about
    them. The contract is conservative: validation succeeds, the handler
    keeps running, and the new field is simply not surfaced to the UI
    until the platform side is updated.
    """
    payload = {
        'event': 'message.delta',
        'delta': 'Hello',
        'run_id': 'run_1',
        'brand_new_field': 'should not break validation',
    }
    instance = _HERMES_EVENT_ADAPTER.validate_python(payload)
    assert isinstance(instance, MessageDeltaEvent)
    assert instance.delta == 'Hello'


# ── Field-shape regressions ─────────────────────────────────────────────────

def test_tool_started_accepts_str_args_from_api_server() -> None:
    """``api_server.py`` packs ``args`` as a stringified preview, not a dict.

    See ``agent/hermes/gateway/platforms/api_server.py`` line ~2332:
    ``"args": str(args)[:500] if args else ""``. The contract's ``args``
    field is typed as ``Any`` precisely so both the dict shape (Myah
    adapter) and the string shape (API server) validate.
    """
    payload = {
        'event': 'tool.started',
        'tool': 'shell_exec',
        'call_id': 'call_xyz',
        'args': "{'command': 'ls'}",  # stringified
        'preview': 'ls',
        'run_id': 'run_abc',
    }
    instance = _HERMES_EVENT_ADAPTER.validate_python(payload)
    assert isinstance(instance, ToolStartedEvent)
    assert instance.args == "{'command': 'ls'}"


def test_run_completed_optional_fields_default_to_none() -> None:
    """``run.completed`` minimal payload (only the discriminator) must validate."""
    payload = {'event': 'run.completed'}
    instance = _HERMES_EVENT_ADAPTER.validate_python(payload)
    assert isinstance(instance, RunCompletedEvent)
    assert instance.output is None
    assert instance.usage is None
    assert instance.model is None
    assert instance.provider is None


def test_run_failed_defaults_error_text() -> None:
    """``run.failed`` without an explicit error message gets a placeholder.

    Mirrors the platform's existing handler default at
    ``hermes_stream_handler.py``: ``error_text = event_data.get('error',
    'Agent run failed')``.
    """
    payload = {'event': 'run.failed'}
    instance = _HERMES_EVENT_ADAPTER.validate_python(payload)
    assert isinstance(instance, RunFailedEvent)
    assert instance.error == 'Agent run failed'


def test_run_cancelled_minimal_payload_validates() -> None:
    """``run.cancelled`` requires only its discriminator."""
    payload = {'event': 'run.cancelled'}
    instance = _HERMES_EVENT_ADAPTER.validate_python(payload)
    assert isinstance(instance, RunCancelledEvent)
    assert instance.run_id is None


def test_tool_confirmation_required_options_default() -> None:
    """``options`` defaults to ``['approve', 'deny']`` to match handler default."""
    payload = {
        'event': 'tool.confirmation_required',
        'confirmation_id': 'conf_1',
    }
    instance = _HERMES_EVENT_ADAPTER.validate_python(payload)
    assert isinstance(instance, ToolConfirmationRequiredEvent)
    assert instance.confirmation_id == 'conf_1'
    assert instance.options == ['approve', 'deny']
    assert instance.metadata == {}


def test_tool_confirmation_required_accepts_exec_approval_without_confirmation_id() -> None:
    """Exec approvals resolve by stream/session key and may omit ``confirmation_id``."""
    payload = {
        'event': 'tool.confirmation_required',
        'action_type': 'exec_approval',
        'description': 'Allow command?',
        'options': ['approve', 'deny', 'approve_session'],
        'metadata': {'command': 'pytest -q'},
        'stream_id': 'stream-exec-approval',
    }
    instance = _HERMES_EVENT_ADAPTER.validate_python(payload)
    assert isinstance(instance, ToolConfirmationRequiredEvent)
    assert instance.confirmation_id is None
    assert instance.action_type == 'exec_approval'


def test_tool_confirmation_required_accepts_null_confirmation_id() -> None:
    """Exec approvals may send explicit JSON null confirmation_id."""
    payload = {
        'event': 'tool.confirmation_required',
        'confirmation_id': None,
        'action_type': 'exec_approval',
        'description': 'Command requires approval',
    }
    instance = _HERMES_EVENT_ADAPTER.validate_python(payload)
    assert isinstance(instance, ToolConfirmationRequiredEvent)
    assert instance.confirmation_id is None
    assert instance.action_type == 'exec_approval'


def test_tool_confirmation_required_preserves_action_confirmation_id() -> None:
    """Action confirmations with explicit IDs must still preserve them."""
    payload = {
        'event': 'tool.confirmation_required',
        'confirmation_id': 'conf-action-123',
        'action_type': 'confirmation',
    }
    instance = _HERMES_EVENT_ADAPTER.validate_python(payload)
    assert isinstance(instance, ToolConfirmationRequiredEvent)
    assert instance.confirmation_id == 'conf-action-123'


# ── Clarify event shape regressions ─────────────────────────────────────────

def test_clarify_required_with_choices_validates() -> None:
    """``clarify.required`` carries the question + optional multiple-choice list."""
    payload = {
        'event': 'clarify.required',
        'clarify_id': 'clarify_1',
        'question': 'Which environment?',
        'choices': ['staging', 'production'],
        'timeout_seconds': 120,
        'run_id': 'run_abc',
    }
    instance = _HERMES_EVENT_ADAPTER.validate_python(payload)
    assert isinstance(instance, ClarifyRequiredEvent)
    assert instance.choices == ['staging', 'production']
    assert instance.timeout_seconds == 120


def test_clarify_required_free_text_has_no_choices() -> None:
    """A free-text clarify prompt omits ``choices`` entirely."""
    payload = {
        'event': 'clarify.required',
        'clarify_id': 'clarify_2',
        'question': 'What should I name the file?',
        'run_id': 'run_abc',
    }
    instance = _HERMES_EVENT_ADAPTER.validate_python(payload)
    assert isinstance(instance, ClarifyRequiredEvent)
    assert instance.choices is None


def test_clarify_resolved_statuses_validate() -> None:
    """``clarify.resolved`` carries the terminal status and optional response."""
    payload = {
        'event': 'clarify.resolved',
        'clarify_id': 'clarify_1',
        'status': 'answered',
        'response': 'staging',
        'run_id': 'run_abc',
    }
    instance = _HERMES_EVENT_ADAPTER.validate_python(payload)
    assert isinstance(instance, ClarifyResolvedEvent)
    assert instance.status == 'answered'
    assert instance.response == 'staging'


# ── Discriminator literal coverage ──────────────────────────────────────────

def test_every_event_class_has_a_literal_event_field() -> None:
    """Every concrete event must declare a ``Literal[...]`` ``event`` field.

    Without this, the discriminated union silently degrades to structural
    matching, which can pick the wrong class for ambiguous payloads.
    """
    for cls in EVENT_SAMPLE_CLASSES.values():
        field = cls.model_fields['event']
        # The annotation should be ``Literal["..."]`` — pydantic stores the
        # discriminator literal in ``field.annotation``.
        annotation_str = repr(field.annotation)
        assert 'Literal' in annotation_str, (
            f'{cls.__name__}.event is not a Literal — got {annotation_str!r}; '
            'discriminated union dispatch will not work.'
        )
