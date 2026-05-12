"""Tests for AGUI action handlers."""

import httpx
import pytest
from unittest.mock import AsyncMock, patch

import open_webui.utils.agui_action_handlers as mod
from open_webui.utils.agui_action_handlers import handle_known_action


class _MockResponse:
    """Minimal mock for httpx.Response."""

    def __init__(self, status_code: int, text: str = '{}'):
        self.status_code = status_code
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f'HTTP {self.status_code}',
                request=None,
                response=self,
            )


class _MockAsyncClient:
    """Minimal mock for httpx.AsyncClient as async context manager."""

    def __init__(self, patch_fn=None, post_fn=None, put_fn=None):
        self.patch_fn = patch_fn
        self.post_fn = post_fn
        self.put_fn = put_fn

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def patch(self, url, headers=None, json=None, timeout=None):
        if self.patch_fn:
            return self.patch_fn(url, headers=headers, json=json, timeout=timeout)
        return _MockResponse(200)

    async def post(self, url, headers=None, json=None, timeout=None):
        if self.post_fn:
            return self.post_fn(url, headers=headers, json=json, timeout=timeout)
        return _MockResponse(201)

    async def put(self, url, headers=None, json=None, timeout=None):
        if self.put_fn:
            return self.put_fn(url, headers=headers, json=json, timeout=timeout)
        return _MockResponse(200)


@pytest.mark.asyncio
async def test_unknown_action_returns_none():
    action = {'type': 'ui:action', 'action': 'approve', 'composition': 'approval_card'}
    result = await handle_known_action(action, {})
    assert result is None  # Unknown actions pass through to agent


@pytest.mark.asyncio
async def test_env_vars_submit_returns_confirmation(monkeypatch):
    """env_vars_submit writes env vars via web_call_or_raise and returns confirmation."""

    async def _mock_resolve_user(metadata):
        return object()  # user is opaque to web_call_or_raise mock

    web_calls = []

    async def _mock_web_call_or_raise(user, method, path, *, json_body=None, **kwargs):
        web_calls.append((method, path, json_body))
        return None

    monkeypatch.setattr(mod, '_resolve_user_from_metadata', _mock_resolve_user)
    monkeypatch.setattr(mod, 'web_call_or_raise', _mock_web_call_or_raise)

    action = {
        'type': 'ui:submit',
        'action': 'env_vars_submit',
        'composition': 'env_vars_form',
        'formId': 'env_vars',
        'data': {'OPENAI_API_KEY': 'sk-test123'},
    }
    result = await handle_known_action(action, {'chat_id': 'test', 'user_id': 'user-1'})
    assert result is not None
    assert 'written' in result.lower()
    assert 'OPENAI_API_KEY' in result
    # All env writes go through the myah-admin plugin's loopback path (Phase 7.7 plugin migration).
    assert all(path == '/api/plugins/myah-admin/env' and method == 'PUT' for method, path, _ in web_calls)
    assert {'key': 'OPENAI_API_KEY', 'value': 'sk-test123'} in [body for _, _, body in web_calls]


@pytest.mark.asyncio
async def test_email_discard_returns_confirmation():
    action = {
        'type': 'ui:action',
        'action': 'Discard',
        'composition': 'email_reply',
    }
    result = await handle_known_action(action, {})
    assert result is not None
    assert 'discard' in result.lower()


@pytest.mark.asyncio
async def test_env_vars_submit_empty_data_returns_message():
    """Empty data returns a message without attempting container write."""
    action = {
        'type': 'ui:submit',
        'action': 'env_vars_submit',
        'composition': 'env_vars_form',
        'formId': 'env_vars',
        'data': {},
    }
    result = await handle_known_action(action, {'chat_id': 'test', 'user_id': 'user-1'})
    assert result is not None
    assert 'no environment variables' in result.lower()


@pytest.mark.asyncio
async def test_env_vars_submit_container_unavailable_returns_error(monkeypatch):
    """If hermes dashboard is unreachable, returns an error string (not an exception)."""
    from fastapi import HTTPException

    async def _mock_resolve_user(metadata):
        return object()

    async def _mock_web_call_or_raise(*args, **kwargs):
        raise HTTPException(status_code=503, detail='Hermes dashboard server unavailable — please retry')

    monkeypatch.setattr(mod, '_resolve_user_from_metadata', _mock_resolve_user)
    monkeypatch.setattr(mod, 'web_call_or_raise', _mock_web_call_or_raise)

    action = {
        'type': 'ui:submit',
        'action': 'env_vars_submit',
        'composition': 'env_vars_form',
        'formId': 'env_vars',
        'data': {'OPENAI_API_KEY': 'sk-test123'},
    }
    result = await handle_known_action(action, {'chat_id': 'test', 'user_id': 'user-1'})
    assert result is not None
    assert 'unavailable' in result.lower() or 'error' in result.lower() or 'failed' in result.lower()


@pytest.mark.asyncio
async def test_handler_exception_returns_error_string(monkeypatch):
    """If a handler raises, handle_known_action should catch it and return an error string."""

    async def _broken_handler(action, metadata):
        raise RuntimeError('simulated failure')

    monkeypatch.setitem(mod._HANDLERS, ('test_comp', 'broken_action'), _broken_handler)

    action = {'type': 'ui:action', 'action': 'broken_action', 'composition': 'test_comp'}
    result = await mod.handle_known_action(action, {})
    assert result is not None
    assert 'error' in result.lower()


@pytest.mark.asyncio
async def test_email_mark_read_calls_api(monkeypatch):
    """mark_read action calls AgentMail PATCH and returns confirmation."""
    import open_webui.utils.agui_action_handlers as mod

    async def _mock_get_key(metadata):
        return 'am_test_key_123'

    def _make_patch_fn(expected_url):
        def patch_fn(url, headers=None, json=None, timeout=None):
            assert expected_url in url
            assert headers['Authorization'] == 'Bearer am_test_key_123'
            assert json == {'add_labels': ['read'], 'remove_labels': []}
            return _MockResponse(200)

        return patch_fn

    monkeypatch.setattr(mod, '_get_agentmail_api_key', _mock_get_key)
    monkeypatch.setattr(
        httpx,
        'AsyncClient',
        lambda: _MockAsyncClient(patch_fn=_make_patch_fn(f'{mod.AGENTMAIL_API_BASE}/inboxes/inbox1/messages/msg1')),
    )

    action = {
        'type': 'ui:action',
        'action': 'mark_read',
        'composition': 'email_thread_list',
        'data': {'inbox_id': 'inbox1', 'message_id': 'msg1'},
    }
    result = await mod.handle_known_action(action, {'user_id': 'user-1', 'chat_id': 'chat-1'})
    assert result is not None
    assert 'read' in result.lower()


@pytest.mark.asyncio
async def test_email_mark_unread_calls_api(monkeypatch):
    """mark_unread action calls AgentMail PATCH with remove_labels."""
    import open_webui.utils.agui_action_handlers as mod

    async def _mock_get_key(metadata):
        return 'am_test_key_456'

    def _make_patch_fn(expected_url):
        def patch_fn(url, headers=None, json=None, timeout=None):
            assert expected_url in url
            assert json == {'add_labels': [], 'remove_labels': ['read']}
            return _MockResponse(200)

        return patch_fn

    monkeypatch.setattr(mod, '_get_agentmail_api_key', _mock_get_key)
    monkeypatch.setattr(
        httpx,
        'AsyncClient',
        lambda: _MockAsyncClient(patch_fn=_make_patch_fn(f'{mod.AGENTMAIL_API_BASE}/inboxes/inbox1/messages/msg1')),
    )

    action = {
        'type': 'ui:action',
        'action': 'mark_unread',
        'composition': 'email_thread_list',
        'data': {'inbox_id': 'inbox1', 'message_id': 'msg1'},
    }
    result = await mod.handle_known_action(action, {'user_id': 'user-1', 'chat_id': 'chat-1'})
    assert result is not None
    assert 'unread' in result.lower()


@pytest.mark.asyncio
async def test_email_archive_calls_api(monkeypatch):
    """archive action calls AgentMail PATCH with archived label."""
    import open_webui.utils.agui_action_handlers as mod

    async def _mock_get_key(metadata):
        return 'am_test_key_789'

    def _make_patch_fn(expected_url):
        def patch_fn(url, headers=None, json=None, timeout=None):
            assert expected_url in url
            assert json == {'add_labels': ['archived'], 'remove_labels': []}
            return _MockResponse(200)

        return patch_fn

    monkeypatch.setattr(mod, '_get_agentmail_api_key', _mock_get_key)
    monkeypatch.setattr(
        httpx,
        'AsyncClient',
        lambda: _MockAsyncClient(patch_fn=_make_patch_fn(f'{mod.AGENTMAIL_API_BASE}/inboxes/inbox1/messages/msg1')),
    )

    action = {
        'type': 'ui:action',
        'action': 'archive',
        'composition': 'email_thread_list',
        'data': {'inbox_id': 'inbox1', 'message_id': 'msg1'},
    }
    result = await mod.handle_known_action(action, {'user_id': 'user-1', 'chat_id': 'chat-1'})
    assert result is not None
    assert 'archived' in result.lower()


@pytest.mark.asyncio
async def test_email_reply_passes_to_agent(monkeypatch):
    """reply action returns None so it passes back to the agent."""
    import open_webui.utils.agui_action_handlers as mod

    action = {
        'type': 'ui:action',
        'action': 'reply',
        'composition': 'email_thread_list',
        'data': {'inbox_id': 'inbox1', 'thread_id': 'thread1'},
    }
    result = await mod.handle_known_action(action, {'user_id': 'user-1'})
    assert result is None  # None = pass to agent


@pytest.mark.asyncio
async def test_email_send_reply_calls_api(monkeypatch):
    """send_reply action calls AgentMail reply endpoint and returns confirmation."""
    import open_webui.utils.agui_action_handlers as mod

    async def _mock_get_key(metadata):
        return 'am_test_key_abc'

    def _make_post_fn(expected_url):
        def post_fn(url, headers=None, json=None, timeout=None):
            assert expected_url in url
            assert 'reply' in url
            assert json['text'] == 'This is my reply'
            return _MockResponse(201)

        return post_fn

    monkeypatch.setattr(mod, '_get_agentmail_api_key', _mock_get_key)
    monkeypatch.setattr(
        httpx,
        'AsyncClient',
        lambda: _MockAsyncClient(post_fn=_make_post_fn(f'{mod.AGENTMAIL_API_BASE}/inboxes/inbox1/messages/msg1/reply')),
    )

    action = {
        'type': 'ui:submit',
        'action': 'send_reply',
        'composition': 'email_reply_compose',
        'data': {
            'inbox_id': 'inbox1',
            'message_id': 'msg1',
            'body': 'This is my reply',
        },
    }
    result = await mod.handle_known_action(action, {'user_id': 'user-1', 'chat_id': 'chat-1'})
    assert result is not None
    assert 'sent' in result.lower()


@pytest.mark.asyncio
async def test_email_mark_read_missing_fields(monkeypatch):
    """mark_read with missing inbox_id returns an error string."""
    import open_webui.utils.agui_action_handlers as mod

    action = {
        'type': 'ui:action',
        'action': 'mark_read',
        'composition': 'email_thread_list',
        'data': {},
    }
    result = await mod.handle_known_action(action, {'user_id': 'user-1'})
    assert result is not None
    assert 'missing' in result.lower()


@pytest.mark.asyncio
async def test_email_send_reply_empty_body(monkeypatch):
    """send_reply with empty body returns an error string."""
    import open_webui.utils.agui_action_handlers as mod

    action = {
        'type': 'ui:submit',
        'action': 'send_reply',
        'composition': 'email_reply_compose',
        'data': {
            'inbox_id': 'inbox1',
            'message_id': 'msg1',
            'body': '   ',
        },
    }
    result = await mod.handle_known_action(action, {'user_id': 'user-1'})
    assert result is not None
    assert 'empty' in result.lower()


@pytest.mark.asyncio
async def test_email_mark_read_api_not_found(monkeypatch):
    """mark_read returns message not found on 404."""
    import open_webui.utils.agui_action_handlers as mod

    async def _mock_get_key(metadata):
        return 'am_test_key'

    def _make_patch_fn(url, headers=None, json=None, timeout=None):
        return _MockResponse(404)

    monkeypatch.setattr(mod, '_get_agentmail_api_key', _mock_get_key)
    monkeypatch.setattr(httpx, 'AsyncClient', lambda: _MockAsyncClient(patch_fn=_make_patch_fn))

    action = {
        'type': 'ui:action',
        'action': 'mark_read',
        'composition': 'email_thread_list',
        'data': {'inbox_id': 'inbox1', 'message_id': 'msg1'},
    }
    result = await mod.handle_known_action(action, {'user_id': 'user-1'})
    assert result is not None
    assert 'not found' in result.lower()


@pytest.mark.asyncio
async def test_email_send_reply_api_error(monkeypatch):
    """send_reply returns error string on API failure."""
    import open_webui.utils.agui_action_handlers as mod

    async def _mock_get_key(metadata):
        return 'am_test_key'

    def _make_post_fn(url, headers=None, json=None, timeout=None):
        return _MockResponse(500, 'Internal Server Error')

    monkeypatch.setattr(mod, '_get_agentmail_api_key', _mock_get_key)
    monkeypatch.setattr(httpx, 'AsyncClient', lambda: _MockAsyncClient(post_fn=_make_post_fn))

    action = {
        'type': 'ui:submit',
        'action': 'send_reply',
        'composition': 'email_reply_compose',
        'data': {
            'inbox_id': 'inbox1',
            'message_id': 'msg1',
            'body': 'Test reply',
        },
    }
    result = await mod.handle_known_action(action, {'user_id': 'user-1'})
    assert result is not None
    assert 'error' in result.lower() or '500' in result
