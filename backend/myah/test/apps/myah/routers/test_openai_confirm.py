"""Regression tests for /openai/chat/confirm forwarding semantics."""

import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


class _FakeConfirmResponse:
    def __init__(self, *, status=200, json_data=None, text_data=''):
        self.status = status
        self._json_data = json_data or {}
        self._text_data = text_data

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def json(self):
        return self._json_data

    async def text(self):
        return self._text_data


class _FakeConfirmSession:
    def __init__(self, response):
        self.response = response
        self.posts = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def post(self, url, **kwargs):
        self.posts.append({'url': url, **kwargs})
        return self.response


def _fake_user(**overrides):
    data = {'id': 'user-1', 'name': 'Ada Lovelace', 'email': 'ada@example.test', 'role': 'user'}
    data.update(overrides)
    return SimpleNamespace(**data)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ('request_body', 'expected_forwarded'),
    [
        ({'run_id': 'stream-confirm', 'choice': 'approve', 'confirmation_id': ''}, {'choice': 'approve'}),
        ({'run_id': 'stream-confirm', 'choice': 'approve'}, {'choice': 'approve'}),
        (
            {'run_id': 'stream-confirm', 'choice': 'approve', 'confirmation_id': 'cf-abc'},
            {'choice': 'approve', 'confirmation_id': 'cf-abc'},
        ),
    ],
)
async def test_confirm_chat_action_omits_empty_confirmation_id(request_body, expected_forwarded):
    from myah.routers.openai import confirm_chat_action

    session = _FakeConfirmSession(_FakeConfirmResponse(status=200, json_data={'ok': True}))
    request = SimpleNamespace(json=AsyncMock(return_value=request_body))
    user = _fake_user()

    async def fake_container(user_id):
        assert user_id == user.id
        return SimpleNamespace(gateway_port=8765, host_port=8766)

    with (
        patch('myah.routers.openai.get_or_create_container', side_effect=fake_container),
        patch('myah.routers.openai.resolve_user_agent_base', return_value='http://agent.test'),
        patch('myah.routers.openai.aiohttp.ClientSession', return_value=session),
        patch('myah.routers.openai.AGENT_BEARER_TOKEN', 'test-agent-token'),
    ):
        result = await confirm_chat_action(request, user=user)

    assert result == {'ok': True}
    assert len(session.posts) == 1
    assert session.posts[0]['url'] == 'http://agent.test/myah/v1/confirm/stream-confirm'
    assert session.posts[0]['json'] == expected_forwarded


@pytest.mark.asyncio
async def test_confirm_chat_action_rejects_invalid_truthy_confirmation_id():
    from fastapi import HTTPException
    from myah.routers.openai import confirm_chat_action

    request = SimpleNamespace(
        json=AsyncMock(
            return_value={
                'run_id': 'stream-confirm',
                'choice': 'approve',
                'confirmation_id': '../bad',
            }
        )
    )

    with pytest.raises(HTTPException) as exc_info:
        await confirm_chat_action(request, user=_fake_user())

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == 'Invalid confirmation_id format'


@pytest.mark.asyncio
async def test_submit_chat_clarify_forwards_response_to_agent():
    from myah.routers.openai import submit_chat_clarify

    session = _FakeConfirmSession(_FakeConfirmResponse(status=200, json_data={'ok': True}))
    request = SimpleNamespace(
        json=AsyncMock(
            return_value={
                'run_id': 'stream-clarify',
                'clarify_id': 'clarify-123',
                'response': 'staging',
            }
        )
    )
    user = _fake_user()

    async def fake_container(user_id):
        assert user_id == user.id
        return SimpleNamespace(gateway_port=8765, host_port=8766)

    with (
        patch('myah.routers.openai.get_or_create_container', side_effect=fake_container),
        patch('myah.routers.openai.resolve_user_agent_base', return_value='http://agent.test'),
        patch('myah.routers.openai.aiohttp.ClientSession', return_value=session),
        patch('myah.routers.openai.AGENT_BEARER_TOKEN', 'test-agent-token'),
    ):
        result = await submit_chat_clarify(request, user=user)

    assert result == {'ok': True}
    assert len(session.posts) == 1
    assert session.posts[0]['url'] == 'http://agent.test/myah/v1/clarify/stream-clarify'
    assert session.posts[0]['json'] == {'clarify_id': 'clarify-123', 'response': 'staging'}


@pytest.mark.asyncio
async def test_submit_chat_clarify_rejects_invalid_ids_and_blank_response():
    from fastapi import HTTPException
    from myah.routers.openai import submit_chat_clarify

    bad_requests = [
        ({'run_id': '../bad', 'clarify_id': 'clarify-123', 'response': 'ok'}, 'Invalid run_id format'),
        ({'run_id': 'stream-clarify', 'clarify_id': '../bad', 'response': 'ok'}, 'Invalid clarify_id format'),
        ({'run_id': 'stream-clarify', 'clarify_id': 'clarify-123', 'response': ''}, 'response is required'),
        ({'run_id': 'stream-clarify', 'clarify_id': 'clarify-123', 'response': '   '}, 'response is required'),
    ]

    for body, expected_detail in bad_requests:
        request = SimpleNamespace(json=AsyncMock(return_value=body))
        with pytest.raises(HTTPException) as exc_info:
            await submit_chat_clarify(request, user=_fake_user())
        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == expected_detail


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ('request_body', 'expected_forwarded'),
    [
        (
            {'run_id': 'stream-secret', 'var_name': 'OPENROUTER_API_KEY', 'value': 'sk-redacted'},
            {'var_name': 'OPENROUTER_API_KEY', 'value': 'sk-redacted'},
        ),
        (
            {'run_id': 'stream-secret', 'var_name': 'OPENROUTER_API_KEY', 'cancel': True},
            {'var_name': 'OPENROUTER_API_KEY', 'value': '', 'cancel': True},
        ),
    ],
)
async def test_submit_chat_secret_forwards_value_or_cancel(request_body, expected_forwarded):
    from myah.routers.openai import submit_chat_secret

    session = _FakeConfirmSession(_FakeConfirmResponse(status=200, json_data={'ok': True}))
    request = SimpleNamespace(json=AsyncMock(return_value=request_body))
    user = _fake_user()

    async def fake_container(user_id):
        assert user_id == user.id
        return SimpleNamespace(gateway_port=8765, host_port=8766)

    with (
        patch('myah.routers.openai.get_or_create_container', side_effect=fake_container),
        patch('myah.routers.openai.resolve_user_agent_base', return_value='http://agent.test'),
        patch('myah.routers.openai.aiohttp.ClientSession', return_value=session),
        patch('myah.routers.openai.AGENT_BEARER_TOKEN', 'test-agent-token'),
    ):
        result = await submit_chat_secret(request, user=user)

    assert result == {'ok': True}
    assert session.posts[0]['url'] == 'http://agent.test/myah/v1/secret/stream-secret'
    assert session.posts[0]['json'] == expected_forwarded
