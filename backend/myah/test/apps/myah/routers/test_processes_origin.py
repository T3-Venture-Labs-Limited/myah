"""Tests for Bug C-platform: processes.create_process forwards origin to agent.

When a cron job is created from a chat:

* The frontend submits the form with ``chat_id`` (the active chat's UUID).
* The platform's ``create_process`` validates ownership of that chat and
  builds an ``origin`` object: ``{platform: "myah", chat_id, chat_name, thread_id}``.
* The platform POSTs ``/api/jobs`` to the agent with both the form fields
  AND the ``origin`` object.

Before the fix, ``ProcessCreateForm`` had no ``chat_id`` field and the
form data was forwarded raw via ``form_data.model_dump(exclude_none=True)``.
There was no way for the platform to send origin, even when the frontend
had the chat context.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_chat_lookup(chat_obj=None):
    """Helper: install a stubbed Chats.get_chat_by_id_and_user_id."""
    return patch(
        'myah.models.chats.Chats.get_chat_by_id_and_user_id',
        return_value=chat_obj,
    )


# ── Myah: Bug C-platform — origin forwarding test coverage ───────


@pytest.mark.asyncio
async def test_create_process_with_chat_id_forwards_origin():
    """When chat_id is present, build origin and forward to agent."""
    from myah.routers.processes import create_process, ProcessCreateForm

    user = MagicMock(id='user-1')
    chat_obj = MagicMock(title='My Cron Chat')

    form = ProcessCreateForm(
        name='hourly-summary',
        schedule='*/60 * * * *',
        prompt='summarize my recent emails',
        deliver='origin',
        chat_id='chat-uuid-1',
    )

    captured_body = {}

    async def fake_hermes_post(_url, body=None):
        captured_body.update(body or {})
        return {'job': {'id': 'job1', **(body or {})}}

    async def fake_ensure_container(_user):
        return 9999

    with patch('myah.routers.processes._hermes_post', side_effect=fake_hermes_post), \
         patch('myah.routers.processes._ensure_container', side_effect=fake_ensure_container), \
         _make_chat_lookup(chat_obj=chat_obj):
        await create_process(form, user)

    assert captured_body.get('origin') is not None, (
        f"expected origin in forwarded body, got: {captured_body!r}"
    )
    origin = captured_body['origin']
    assert origin['platform'] == 'myah'
    assert origin['chat_id'] == 'chat-uuid-1'
    # Don't pin chat_name strictly — the spec says it's optional, but
    # passing it through is a nice-to-have so the agent can render
    # friendlier error messages.
    assert 'chat_name' in origin

    # When origin is set with a real chat_id, deliver should remain
    # 'origin' so the agent's _resolve_delivery_target uses the origin.
    assert captured_body.get('deliver') == 'origin'

    # chat_id MUST NOT leak as a top-level field — the agent doesn't know
    # about it, only origin.chat_id.
    assert 'chat_id' not in captured_body


@pytest.mark.asyncio
async def test_create_process_without_chat_id_omits_origin():
    """No chat_id → no origin in forwarded body (backward-compat)."""
    from myah.routers.processes import create_process, ProcessCreateForm

    user = MagicMock(id='user-1')
    form = ProcessCreateForm(
        name='task',
        schedule='*/5 * * * *',
        prompt='do thing',
    )

    captured_body = {}

    async def fake_hermes_post(_url, body=None):
        captured_body.update(body or {})
        return {'job': {'id': 'job1', **(body or {})}}

    async def fake_ensure_container(_user):
        return 9999

    with patch('myah.routers.processes._hermes_post', side_effect=fake_hermes_post), \
         patch('myah.routers.processes._ensure_container', side_effect=fake_ensure_container):
        await create_process(form, user)

    assert 'origin' not in captured_body
    assert 'chat_id' not in captured_body


@pytest.mark.asyncio
async def test_create_process_rejects_unknown_chat_id():
    """chat_id that doesn't belong to the user → HTTPException 404."""
    from fastapi import HTTPException
    from myah.routers.processes import create_process, ProcessCreateForm

    user = MagicMock(id='user-1')
    form = ProcessCreateForm(
        name='task',
        schedule='*/5 * * * *',
        prompt='do thing',
        chat_id='not-mine-chat',
    )

    async def fake_hermes_post(_url, body=None):  # should never be called
        return {'job': {}}

    async def fake_ensure_container(_user):
        return 9999

    with patch('myah.routers.processes._hermes_post', side_effect=fake_hermes_post) as mock_post, \
         patch('myah.routers.processes._ensure_container', side_effect=fake_ensure_container), \
         _make_chat_lookup(chat_obj=None):
        with pytest.raises(HTTPException) as exc:
            await create_process(form, user)

    assert exc.value.status_code in (400, 404)
    mock_post.assert_not_called()


@pytest.mark.asyncio
async def test_create_process_rejects_local_chat_id_prefix():
    """chat_id starting with 'local:' (temporary chat) is rejected."""
    from fastapi import HTTPException
    from myah.routers.processes import create_process, ProcessCreateForm

    user = MagicMock(id='user-1')
    form = ProcessCreateForm(
        name='task',
        schedule='*/5 * * * *',
        prompt='do thing',
        chat_id='local:temp-12345',
    )

    async def fake_hermes_post(_url, body=None):
        return {'job': {}}

    async def fake_ensure_container(_user):
        return 9999

    with patch('myah.routers.processes._hermes_post', side_effect=fake_hermes_post) as mock_post, \
         patch('myah.routers.processes._ensure_container', side_effect=fake_ensure_container):
        with pytest.raises(HTTPException) as exc:
            await create_process(form, user)

    assert exc.value.status_code == 400
    mock_post.assert_not_called()
# ─────────────────────────────────────────────────────────────────
