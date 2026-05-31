"""Tests for the HermesOutputRenderer output item Pydantic models.

The output items are the platform's normalised view of a streaming agent
response — every assistant message in the DB carries an ``output`` array of
these items, and the SvelteKit renderer dispatches on each item's ``type``
field. The tests below exercise three things:

1. **Per-item validation** — each documented item type validates against
   the discriminated :data:`OutputItem` union with a representative payload.
2. **Discriminator dispatch** — given a payload, ``TypeAdapter`` returns
   the matching concrete model, never falls back to a sibling.
3. **Failure modes** — unknown ``type`` literals and missing required
   fields raise ``ValidationError`` so the renderer can skip the item
   safely rather than rendering garbage.

The sample payloads mirror the wire shape produced by
``platform/backend/myah/utils/hermes_stream_handler.py`` — the
canonical line numbers are listed in each item class's docstring in
``shared/contract/output_items.py``.
"""
from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from shared.contract.output_items import (
    CodeInterpreterItem,
    ConfirmationItem,
    FunctionCallItem,
    FunctionCallOutputItem,
    MessageItem,
    OutputItem,
    ReasoningItem,
    SecretInputItem,
    TodoPlanItem,
)

# A single TypeAdapter is reused so pydantic v2 does not rebuild the
# discriminated-union schema on every parametrised invocation.
_OUTPUT_ITEM_ADAPTER: TypeAdapter[OutputItem] = TypeAdapter(OutputItem)


# ── Sample payloads ─────────────────────────────────────────────────────────
# One per concrete item class. Each payload is the minimal shape the
# stream handler actually writes (see line refs in the model docstrings).

ITEM_SAMPLES: dict[str, tuple[dict, type]] = {
    'message': (
        {
            'type': 'message',
            'id': 'msg_abc',
            'status': 'in_progress',
            'role': 'assistant',
            'content': [{'type': 'output_text', 'text': 'Hello world'}],
        },
        MessageItem,
    ),
    'function_call': (
        {
            'type': 'function_call',
            'id': 'fc_abc',
            'call_id': 'call_xyz',
            'name': 'shell_exec',
            'arguments': '{"command": "ls -la"}',
            'status': 'in_progress',
        },
        FunctionCallItem,
    ),
    'function_call_output': (
        {
            'type': 'function_call_output',
            'id': 'fco_abc',
            'call_id': 'call_xyz',
            'output': [{'type': 'input_text', 'text': 'total 0'}],
            'status': 'completed',
        },
        FunctionCallOutputItem,
    ),
    'reasoning': (
        {
            'type': 'reasoning',
            'id': 'rsn_abc',
            'status': 'in_progress',
            'summary': [{'type': 'summary_text', 'text': 'Considering ...'}],
        },
        ReasoningItem,
    ),
    'myah:code_interpreter': (
        {
            'type': 'myah:code_interpreter',
            'id': 'ci_abc',
            'code': "print('hello')",
            'lang': 'python',
            'status': 'completed',
            'duration': 1.2,
            'output': {'result': 'hello\n'},
        },
        CodeInterpreterItem,
    ),
    'confirmation': (
        {
            'type': 'confirmation',
            'id': 'conf_abc',
            'confirmation_id': 'conf_123',
            'run_id': 'run_abc',
            'action_type': 'exec_approval',
            'description': 'Run rm -rf /tmp/foo?',
            'options': ['approve', 'deny', 'approve_session'],
            'metadata': {'risk': 'high'},
            'status': 'pending',
        },
        ConfirmationItem,
    ),
    'secret_input': (
        {
            'type': 'secret_input',
            'id': 'secret_abc',
            'run_id': 'run_abc',
            'var_name': 'OPENAI_API_KEY',
            'prompt': 'Enter your OpenAI key',
            'help': 'https://platform.openai.com/api-keys',
            'skill_name': 'openai',
            'status': 'pending',
        },
        SecretInputItem,
    ),
    'todo_plan': (
        {
            'type': 'todo_plan',
            'id': 'todo_abc',
            'call_id': 'call_todo_1',
            'title': 'Plan',
            'todos': [
                {'id': '1', 'content': 'Inspect design', 'status': 'completed'},
                {'id': '2', 'content': 'Build strip', 'status': 'in_progress'},
                {'id': '3', 'content': 'Verify runtime', 'status': 'pending'},
            ],
            'status': 'in_progress',
        },
        TodoPlanItem,
    ),
}


# ── Per-item validation ─────────────────────────────────────────────────────


@pytest.mark.parametrize('item_type,payload_and_class', sorted(ITEM_SAMPLES.items()))
def test_each_item_validates_against_union(
    item_type: str, payload_and_class: tuple[dict, type]
) -> None:
    """Every documented item payload validates as the matching model.

    Failure here means the contract has drifted from the upstream wire
    format: either the stream handler started writing a new required
    field we don't model, or we tightened the schema in a way that
    rejects production payloads.
    """
    payload, expected_class = payload_and_class
    instance = _OUTPUT_ITEM_ADAPTER.validate_python(payload)
    assert isinstance(instance, expected_class), (
        f'discriminator dispatch failed for {item_type!r}: '
        f'got {type(instance).__name__}, expected {expected_class.__name__}'
    )


def test_completeness_every_known_item_has_a_sample() -> None:
    """Every concrete item class must appear in ITEM_SAMPLES.

    Guards against a class being added to ``output_items.py`` and the
    union without a corresponding sample being added here. Without this
    check, new item types would silently skip validation testing and
    Phase 5's completeness check could miss them.
    """
    sampled_classes = {expected_class for _, expected_class in ITEM_SAMPLES.values()}
    declared_classes = {
        MessageItem,
        FunctionCallItem,
        FunctionCallOutputItem,
        ReasoningItem,
        CodeInterpreterItem,
        ConfirmationItem,
        SecretInputItem,
        TodoPlanItem,
    }
    assert sampled_classes == declared_classes, (
        f'Test matrix drift: missing samples for '
        f'{declared_classes - sampled_classes}; '
        f'unexpected samples for {sampled_classes - declared_classes}'
    )


# ── Discriminator behaviour ─────────────────────────────────────────────────


def test_unknown_item_type_fails_validation() -> None:
    """An unrecognised ``type`` value raises ``ValidationError``.

    The renderer relies on this so it can skip the item rather than
    dispatching against a half-validated payload — which would throw at
    render time and break the entire chat surface.
    """
    payload = {'type': 'gibberish.unknown', 'id': 'g_1'}
    with pytest.raises(ValidationError):
        _OUTPUT_ITEM_ADAPTER.validate_python(payload)


def test_missing_type_field_fails_validation() -> None:
    """A payload without the discriminator field fails validation."""
    payload: dict = {'id': 'msg_abc', 'role': 'assistant'}
    with pytest.raises(ValidationError):
        _OUTPUT_ITEM_ADAPTER.validate_python(payload)


def test_missing_required_field_fails_validation() -> None:
    """Required fields are enforced — ``MessageItem`` without ``id`` fails.

    The stream handler always writes ``id`` (via ``output_id('msg')`` at
    ``hermes_stream_handler.py:210``), so a payload without it indicates a
    real bug somewhere upstream rather than a tolerated absence.
    """
    payload = {
        'type': 'message',
        # missing 'id'
        'status': 'in_progress',
        'role': 'assistant',
        'content': [],
    }
    with pytest.raises(ValidationError):
        _OUTPUT_ITEM_ADAPTER.validate_python(payload)


def test_extra_fields_are_allowed() -> None:
    """Unknown payload fields tolerated — frontend may add fields ahead of contract.

    The contract is intentionally lenient here: the stream handler is the
    single source of truth for new fields, and the contract follows by
    one PR. Strict rejection during the lag would break production.
    """
    payload = {
        'type': 'message',
        'id': 'msg_abc',
        'status': 'completed',
        'role': 'assistant',
        'content': [{'type': 'output_text', 'text': 'Hello'}],
        'brand_new_field': 'should not break validation',
    }
    instance = _OUTPUT_ITEM_ADAPTER.validate_python(payload)
    assert isinstance(instance, MessageItem)
    assert instance.id == 'msg_abc'


# ── Field-shape regressions ─────────────────────────────────────────────────


def test_function_call_arguments_is_string_not_dict() -> None:
    """``arguments`` is a JSON string on the wire, not a parsed dict.

    The stream handler serialises with ``json.dumps`` at
    ``hermes_stream_handler.py:505`` so the wire format stays stable
    across parses. Frontend code re-parses on demand; if we typed this as
    ``dict`` here, pydantic would silently coerce the string into a dict
    when validating, breaking the round-trip.
    """
    payload = {
        'type': 'function_call',
        'id': 'fc_1',
        'call_id': 'c_1',
        'name': 'tool',
        'arguments': '{"k": "v"}',  # string, not dict
        'status': 'in_progress',
    }
    instance = _OUTPUT_ITEM_ADAPTER.validate_python(payload)
    assert isinstance(instance, FunctionCallItem)
    assert isinstance(instance.arguments, str)
    assert instance.arguments == '{"k": "v"}'


def test_reasoning_duration_optional() -> None:
    """``ReasoningItem.duration`` may be ``None`` while in progress."""
    payload = {
        'type': 'reasoning',
        'id': 'rsn_1',
        'status': 'in_progress',
        'summary': [],
    }
    instance = _OUTPUT_ITEM_ADAPTER.validate_python(payload)
    assert isinstance(instance, ReasoningItem)
    assert instance.duration is None


def test_confirmation_chosen_optional() -> None:
    """``ConfirmationItem.chosen`` may be ``None`` until the user picks an option."""
    payload = {
        'type': 'confirmation',
        'id': 'conf_1',
        'confirmation_id': 'c_1',
        'run_id': 'run_1',
        'action_type': 'exec',
        'description': 'do the thing',
        'options': ['approve', 'deny'],
        'metadata': {},
        'status': 'pending',
    }
    instance = _OUTPUT_ITEM_ADAPTER.validate_python(payload)
    assert isinstance(instance, ConfirmationItem)
    assert instance.chosen is None


def test_code_interpreter_output_optional() -> None:
    """``CodeInterpreterItem.output`` may be missing while still running."""
    payload = {
        'type': 'myah:code_interpreter',
        'id': 'ci_1',
        'code': "print('hi')",
        'lang': 'python',
        'status': 'in_progress',
    }
    instance = _OUTPUT_ITEM_ADAPTER.validate_python(payload)
    assert isinstance(instance, CodeInterpreterItem)
    assert instance.output is None
    assert instance.duration is None


# ── Discriminator literal coverage ──────────────────────────────────────────


def test_every_item_class_has_a_literal_type_field() -> None:
    """Every concrete item declares a ``Literal[...]`` ``type`` field.

    Without this, the discriminated union silently degrades to structural
    matching — pydantic could pick the wrong class for an ambiguous
    payload, which would silently corrupt the rendered chat.
    """
    classes = [
        MessageItem,
        FunctionCallItem,
        FunctionCallOutputItem,
        ReasoningItem,
        CodeInterpreterItem,
        ConfirmationItem,
        SecretInputItem,
    ]
    for cls in classes:
        field = cls.model_fields['type']
        annotation_str = repr(field.annotation)
        assert 'Literal' in annotation_str, (
            f'{cls.__name__}.type is not a Literal — got {annotation_str!r}; '
            'discriminated union dispatch will not work.'
        )
