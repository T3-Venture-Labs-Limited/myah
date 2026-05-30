"""Adopt Legacy Hermes Crons — backend Phase 3: link_process_to_chat as adoption-lite.

``link_process_to_chat`` must persist Myah routing metadata through the SAME
safe primitive adoption uses (``job.myah.chat_id``) — not a top-level
``chat_id`` that native Hermes ``PATCH /api/jobs/{id}`` silently drops.

It must also preserve native external ``origin`` / ``deliver`` (by never
sending them) and reject unowned / local-temp chats.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

VALID_JOB_ID = 'abcdef012345'


def _make_user(db_session, uid: str = 'user-link-1'):
    from myah.models.users import Users

    Users.insert_new_user(id=uid, name='link-test', email=f'{uid}@local', role='user')
    return Users.get_user_by_id(uid)


def _make_chat(db_session, user_id: str, title: str):
    from myah.models.chats import ChatForm, Chats

    form = ChatForm(chat={'title': title, 'history': {'messages': {}, 'currentId': None}})
    return Chats.insert_new_chat(user_id, form)


@pytest.mark.asyncio
async def test_link_process_to_chat_patches_myah_metadata_not_top_level_chat_id_only(db_session):
    from myah.routers.processes import LinkChatForm, link_process_to_chat

    user = _make_user(db_session)
    chat = _make_chat(db_session, user.id, 'My Chat')
    job = {'id': VALID_JOB_ID, 'name': 'Cron'}
    calls: list = []

    async def fake_patch(u, job_id, metadata):
        calls.append({'job_id': job_id, 'metadata': metadata})
        return {'job': {'id': job_id, **metadata}}

    with patch('myah.routers.processes._ensure_container', new=AsyncMock(return_value=9999)), \
         patch('myah.routers.processes._hermes_get', new=AsyncMock(return_value={'job': job})), \
         patch('myah.routers.processes._patch_job_myah_metadata', side_effect=fake_patch), \
         patch('myah.routers.processes._hermes_patch', new=AsyncMock()) as mock_hermes_patch:
        await link_process_to_chat(VALID_JOB_ID, LinkChatForm(chat_id=chat.id), user)

    # Patched via the safe metadata primitive, with myah.chat_id …
    assert len(calls) == 1
    assert calls[0]['job_id'] == VALID_JOB_ID
    assert calls[0]['metadata']['myah']['chat_id'] == chat.id
    # … and NOT via a silently-dropped top-level chat_id PATCH.
    mock_hermes_patch.assert_not_called()
    assert 'chat_id' not in calls[0]['metadata']  # never a top-level chat_id key


@pytest.mark.asyncio
async def test_link_process_to_chat_preserves_external_origin_when_deliver_origin(db_session):
    from myah.routers.processes import LinkChatForm, link_process_to_chat

    user = _make_user(db_session)
    chat = _make_chat(db_session, user.id, 'My Chat')
    job = {'id': VALID_JOB_ID, 'name': 'TG', 'deliver': 'origin',
           'origin': {'platform': 'telegram', 'chat_id': 'tg-1'}}
    calls: list = []

    async def fake_patch(u, job_id, metadata):
        calls.append(metadata)
        return {'job': {'id': job_id}}

    with patch('myah.routers.processes._ensure_container', new=AsyncMock(return_value=9999)), \
         patch('myah.routers.processes._hermes_get', new=AsyncMock(return_value={'job': job})), \
         patch('myah.routers.processes._patch_job_myah_metadata', side_effect=fake_patch):
        await link_process_to_chat(VALID_JOB_ID, LinkChatForm(chat_id=chat.id), user)

    md = calls[0]
    # legacy origin snapshotted, native origin/deliver never sent
    assert md['myah']['legacy_origin']['platform'] == 'telegram'
    assert 'origin' not in md
    assert 'deliver' not in md


@pytest.mark.asyncio
async def test_link_process_to_chat_rejects_unowned_chat(db_session):
    from myah.routers.processes import LinkChatForm, link_process_to_chat

    user = _make_user(db_session)
    with patch('myah.routers.processes._ensure_container', new=AsyncMock(return_value=9999)) as mc, \
         patch('myah.routers.processes._patch_job_myah_metadata', new=AsyncMock()) as mp:
        with pytest.raises(HTTPException) as exc:
            await link_process_to_chat(VALID_JOB_ID, LinkChatForm(chat_id='not-owned'), user)
    assert exc.value.status_code == 404
    mc.assert_not_called()
    mp.assert_not_called()


@pytest.mark.asyncio
async def test_link_process_to_chat_rejects_local_temp_chat(db_session):
    from myah.routers.processes import LinkChatForm, link_process_to_chat

    user = _make_user(db_session)
    with patch('myah.routers.processes._ensure_container', new=AsyncMock(return_value=9999)) as mc, \
         patch('myah.routers.processes._patch_job_myah_metadata', new=AsyncMock()) as mp:
        with pytest.raises(HTTPException) as exc:
            await link_process_to_chat(VALID_JOB_ID, LinkChatForm(chat_id='local:temp-1'), user)
    assert exc.value.status_code == 400
    mc.assert_not_called()
    mp.assert_not_called()
