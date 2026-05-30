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
