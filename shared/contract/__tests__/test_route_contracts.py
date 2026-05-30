"""Route-level contracts for high-risk Myah↔Hermes HTTP boundaries."""
from __future__ import annotations

from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from shared.contract.events import HermesEvent
from shared.contract.routes import (
    HermesJob,
    HermesJobGetResponse,
    HermesJobRunResponse,
    HermesJobsListResponse,
    MyahConfirmRequest,
    MyahConfirmResponse,
    MyahMessageRequest,
    MyahMessageResponse,
    MyahSecretRequest,
    MyahSecretResponse,
)
from shared.contract.samples import EVENT_SAMPLES

FAKE_SECRET_VALUE = 'FAKE_SECRET_VALUE'

_HERMES_EVENT_ADAPTER: TypeAdapter[HermesEvent] = TypeAdapter(HermesEvent)


def _message_request_sample() -> dict[str, Any]:
    return {
        'message': 'Summarize this attachment.',
        'session_id': 'session_123',
        'user_id': 'user_123',
        'message_id': 'message_123',
        'user_name': 'Test User',
        'chat_name': 'Contract test chat',
        'ui_state': {'active_view': 'chat', 'selected_file_id': 'file_123'},
        'attachments': [
            {
                'id': 'file_123',
                'name': 'notes.txt',
                'mime_type': 'text/plain',
                'content_url': 'https://platform.example.test/api/v1/files/file_123/content',
            }
        ],
        'model': 'anthropic/claude-sonnet-4-6',
        'provider': 'openrouter',
    }


def _hermes_job_sample() -> dict[str, Any]:
    return {
        'id': 'job_123',
        'name': 'Daily Myah digest',
        'schedule': '0 9 * * *',
        'enabled': True,
        'status': 'scheduled',
        'last_run': {'id': 'run_prev', 'status': 'completed'},
        'next_run': '2026-05-31T09:00:00Z',
        'origin': {
            'platform': 'myah',
            'chat_id': 'chat_origin_123',
            'chat_name': 'Daily standup',
            'thread_id': None,
        },
        'myah': {
            'chat_id': 'chat_myah_456',
            'adoption_state': 'linked',
            'linked_by_user_id': 'user_123',
        },
        'chat_id': 'chat_top_level_789',
        'deliver': 'origin',
        'repeat': True,
        'skills': ['calendar', 'email'],
    }


def test_message_request_and_response_samples_validate() -> None:
    request = MyahMessageRequest.model_validate(_message_request_sample())
    assert request.message == 'Summarize this attachment.'
    assert request.session_id == 'session_123'
    assert request.user_id == 'user_123'
    assert request.message_id == 'message_123'
    assert request.user_name == 'Test User'
    assert request.chat_name == 'Contract test chat'
    assert request.ui_state == {'active_view': 'chat', 'selected_file_id': 'file_123'}
    assert request.attachments[0]['id'] == 'file_123'
    assert request.model == 'anthropic/claude-sonnet-4-6'
    assert request.provider == 'openrouter'

    response = MyahMessageResponse.model_validate(
        {'stream_id': 'stream_123', 'session_id': 'session_123'},
    )
    assert response.stream_id == 'stream_123'
    assert response.session_id == 'session_123'

    missing_message = _message_request_sample()
    missing_message.pop('message')
    with pytest.raises(ValidationError):
        MyahMessageRequest.model_validate(missing_message)

    missing_session = _message_request_sample()
    missing_session.pop('session_id')
    with pytest.raises(ValidationError):
        MyahMessageRequest.model_validate(missing_session)


def test_confirm_request_and_response_samples_validate() -> None:
    for choice in ['approve', 'deny', 'approve_session']:
        request = MyahConfirmRequest.model_validate(
            {
                'confirmation_id': 'conf_123',
                'choice': choice,
                'metadata': {'source': 'contract-test'},
            },
        )
        assert request.choice == choice
        assert request.metadata == {'source': 'contract-test'}

    response = MyahConfirmResponse.model_validate({'ok': True, 'status': 'accepted'})
    assert response.ok is True
    assert response.status == 'accepted'


def test_secret_request_and_response_samples_validate() -> None:
    request = MyahSecretRequest.model_validate(
        {
            'var_name': 'OPENAI_API_KEY',
            'value': FAKE_SECRET_VALUE,
            'secret': None,
            'metadata': {'source': 'contract-test'},
        },
    )
    assert request.var_name == 'OPENAI_API_KEY'
    assert request.value == FAKE_SECRET_VALUE
    assert request.secret is None
    assert request.metadata == {'source': 'contract-test'}

    response = MyahSecretResponse.model_validate({'ok': True, 'status': 'stored'})
    assert response.ok is True
    assert response.status == 'stored'


def test_sse_event_samples_validate_against_hermes_event_union() -> None:
    for event_type, payload in sorted(EVENT_SAMPLES.items()):
        event = _HERMES_EVENT_ADAPTER.validate_python(payload)
        assert event.event == event_type


def test_hermes_jobs_list_requires_jobs_wrapper() -> None:
    sample = _hermes_job_sample()
    response = HermesJobsListResponse.model_validate({'jobs': [sample]})
    job = response.jobs[0]
    assert job.id == 'job_123'
    assert job.origin == sample['origin']
    assert job.myah == sample['myah']
    assert job.chat_id == sample['chat_id']
    assert job.deliver == sample['deliver']
    assert job.repeat is True
    assert job.skills == ['calendar', 'email']

    with pytest.raises(ValidationError):
        HermesJobsListResponse.model_validate([sample])


def test_hermes_job_get_requires_job_wrapper() -> None:
    sample = _hermes_job_sample()
    response = HermesJobGetResponse.model_validate({'job': sample})
    assert response.job.id == 'job_123'

    with pytest.raises(ValidationError):
        HermesJobGetResponse.model_validate(sample)


def test_hermes_job_contract_preserves_myah_adoption_metadata() -> None:
    job = HermesJob.model_validate(_hermes_job_sample())
    assert job.origin is not None
    assert job.origin['platform'] == 'myah'
    assert job.origin['chat_id'] == 'chat_origin_123'
    assert job.myah is not None
    assert job.myah['chat_id'] == 'chat_myah_456'
    assert job.chat_id == 'chat_top_level_789'

    run_response = HermesJobRunResponse.model_validate(
        {'ok': True, 'run_id': 'run_123', 'job': _hermes_job_sample()},
    )
    assert run_response.ok is True
    assert run_response.run_id == 'run_123'
    assert run_response.job is not None
    assert run_response.job.origin == job.origin


def test_route_contract_models_allow_extra_fields() -> None:
    message = MyahMessageRequest.model_validate(
        {
            **_message_request_sample(),
            'future_request_field': {'kept': True},
        },
    )
    assert message.future_request_field == {'kept': True}

    job = HermesJob.model_validate(
        {
            **_hermes_job_sample(),
            'future_job_field': {'kept': True},
        },
    )
    assert job.future_job_field == {'kept': True}
