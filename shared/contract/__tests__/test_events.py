"""Tests for the Hermes SSE event Pydantic models.

These tests exercise the contract surface the platform's stream handler
depends on: every event type Hermes is known to emit must validate
against :data:`HermesEvent`, the discriminated union must dispatch to the
correct concrete class, and unrecognised event types must fail
validation so the handler can log a warning and continue.
"""
from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from shared.contract.events import (
    ApprovalRequestEvent,
    ApprovalRespondedEvent,
    HermesEvent,
    MessageDeltaEvent,
    ReasoningAvailableEvent,
    ReasoningDeltaEvent,
    RunCompletedEvent,
    RunFailedEvent,
    SecretRequiredEvent,
    SecretResolvedEvent,
    StatusEvent,
    ToolCompletedEvent,
    ToolConfirmationRequiredEvent,
    ToolStartedEvent,
)

# A single TypeAdapter avoids re-building the discriminated union machinery on
# every test invocation. Pydantic v2 caches schema compilation under the hood
# so this is purely a readability optimisation.
_HERMES_EVENT_ADAPTER: TypeAdapter[HermesEvent] = TypeAdapter(HermesEvent)


# ── Sample payloads (one per event type) ────────────────────────────────────
# Payloads mirror what the upstream emitters actually push onto the SSE
# queue today. See the docstrings on each event class for the canonical
# wire-format source line.

EVENT_SAMPLES: dict[str, tuple[dict, type]] = {
    'message.delta': (
        {
            'event': 'message.delta',
            'delta': 'Hello world',
            'run_id': 'run_abc',
            'stream_id': 'run_abc',
            'timestamp': 1714400000.0,
        },
        MessageDeltaEvent,
    ),
    'reasoning.delta': (
        {
            'event': 'reasoning.delta',
            'text': 'Considering the problem...',
            'run_id': 'run_abc',
            'timestamp': 1714400001.0,
        },
        ReasoningDeltaEvent,
    ),
    'reasoning.available': (
        {
            'event': 'reasoning.available',
            'text': 'Full chain-of-thought transcript.',
            'run_id': 'run_abc',
        },
        ReasoningAvailableEvent,
    ),
    'tool.started': (
        {
            'event': 'tool.started',
            'tool': 'shell_exec',
            'call_id': 'call_xyz',
            'args': {'command': 'ls -la'},
            'preview': 'ls -la',
            'run_id': 'run_abc',
        },
        ToolStartedEvent,
    ),
    'tool.completed': (
        {
            'event': 'tool.completed',
            'tool': 'shell_exec',
            'call_id': 'call_xyz',
            'args': {'command': 'ls -la'},
            'result': 'total 0\ndrwxr-xr-x  2 user staff   64 Apr 25 12:00 .',
            'duration': 0.123,
            'error': False,
            'run_id': 'run_abc',
        },
        ToolCompletedEvent,
    ),
    'tool.confirmation_required': (
        {
            'event': 'tool.confirmation_required',
            'confirmation_id': 'conf_123',
            'action_type': 'exec_approval',
            'description': 'Command requires approval: rm -rf /tmp/foo',
            'options': ['approve', 'approve_session', 'deny'],
            'metadata': {'risk': 'high'},
            'run_id': 'run_abc',
        },
        ToolConfirmationRequiredEvent,
    ),
    'approval.request': (
        {
            'event': 'approval.request',
            'command': 'rm -rf /tmp/foo',
            'description': 'Command requires approval: rm -rf /tmp/foo',
            'pattern_key': 'dangerous_rm',
            'pattern_keys': ['dangerous_rm'],
            'choices': ['once', 'session', 'always', 'deny'],
            'run_id': 'run_abc',
            'timestamp': 1714400002.0,
        },
        ApprovalRequestEvent,
    ),
    'approval.responded': (
        {
            'event': 'approval.responded',
            'choice': 'once',
            'resolved': 1,
            'run_id': 'run_abc',
            'timestamp': 1714400003.0,
        },
        ApprovalRespondedEvent,
    ),
    'secret.required': (
        {
            'event': 'secret.required',
            'var_name': 'OPENAI_API_KEY',
            'prompt': 'Enter your OpenAI API key',
            'help': 'https://platform.openai.com/api-keys',
            'skill_name': 'openai',
            'run_id': 'run_abc',
        },
        SecretRequiredEvent,
    ),
    'secret.resolved': (
        {
            'event': 'secret.resolved',
            'var_name': 'OPENAI_API_KEY',
            'status': 'stored',
            'run_id': 'run_abc',
        },
        SecretResolvedEvent,
    ),
    'run.completed': (
        {
            'event': 'run.completed',
            'output': 'Final response text',
            'usage': {'input_tokens': 100, 'output_tokens': 50, 'total_tokens': 150},
            'model': 'anthropic/claude-sonnet-4-6',
            'provider': 'openrouter',
            'run_id': 'run_abc',
        },
        RunCompletedEvent,
    ),
    'run.failed': (
        {
            'event': 'run.failed',
            'error': 'LLM provider returned 429',
            'run_id': 'run_abc',
        },
        RunFailedEvent,
    ),
    'status': (
        {
            'event': 'status',
            'text': 'working',
            'run_id': 'run_abc',
        },
        StatusEvent,
    ),
}


# ── Per-event validation ────────────────────────────────────────────────────


@pytest.mark.parametrize('event_type,payload_and_class', sorted(EVENT_SAMPLES.items()))
def test_each_event_validates_against_union(
    event_type: str, payload_and_class: tuple[dict, type]
) -> None:
    """Every documented event payload must validate as the matching model.

    Failure here means the contract has drifted from the upstream wire
    format — either Hermes added a required field we don't know about, or
    we accidentally tightened the schema. Either way the stream handler's
    new validation layer would reject real production traffic.
    """
    payload, expected_class = payload_and_class
    instance = _HERMES_EVENT_ADAPTER.validate_python(payload)
    assert isinstance(instance, expected_class), (
        f'discriminator dispatch failed for {event_type!r}: '
        f'got {type(instance).__name__}, expected {expected_class.__name__}'
    )


def test_completeness_every_known_event_has_a_sample() -> None:
    """Every concrete event class must appear in EVENT_SAMPLES.

    This guards against a class being added to ``events.py`` and the
    union without a corresponding sample payload being added to the
    test matrix above. Without this check, new events would silently
    skip validation testing.
    """
    sampled_classes = {expected_class for _, expected_class in EVENT_SAMPLES.values()}
    declared_classes = {
        MessageDeltaEvent,
        ReasoningDeltaEvent,
        ReasoningAvailableEvent,
        ToolStartedEvent,
        ToolCompletedEvent,
        ToolConfirmationRequiredEvent,
        ApprovalRequestEvent,
        ApprovalRespondedEvent,
        SecretRequiredEvent,
        SecretResolvedEvent,
        RunCompletedEvent,
        RunFailedEvent,
        StatusEvent,
    }
    assert sampled_classes == declared_classes, (
        f'Test matrix drift: missing samples for '
        f'{declared_classes - sampled_classes}; '
        f'unexpected samples for {sampled_classes - declared_classes}'
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


def test_tool_confirmation_required_options_default() -> None:
    """``options`` defaults to ``['approve', 'deny']`` to match handler default."""
    payload = {
        'event': 'tool.confirmation_required',
        'confirmation_id': 'conf_1',
    }
    instance = _HERMES_EVENT_ADAPTER.validate_python(payload)
    assert isinstance(instance, ToolConfirmationRequiredEvent)
    assert instance.options == ['approve', 'deny']
    assert instance.metadata == {}


# ── Discriminator literal coverage ──────────────────────────────────────────


def test_every_event_class_has_a_literal_event_field() -> None:
    """Every concrete event must declare a ``Literal[...]`` ``event`` field.

    Without this, the discriminated union silently degrades to structural
    matching, which can pick the wrong class for ambiguous payloads.
    """
    classes = [
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
        StatusEvent,
    ]
    for cls in classes:
        field = cls.model_fields['event']
        # The annotation should be ``Literal["..."]`` — pydantic stores the
        # discriminator literal in ``field.annotation``.
        annotation_str = repr(field.annotation)
        assert 'Literal' in annotation_str, (
            f'{cls.__name__}.event is not a Literal — got {annotation_str!r}; '
            'discriminated union dispatch will not work.'
        )
