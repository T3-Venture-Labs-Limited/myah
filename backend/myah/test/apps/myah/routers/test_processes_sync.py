"""Adopt Legacy Hermes Crons — backend Phase 4: sync_process_chat is
metadata-aware and idempotent.

Opening a process chat backfills missing historical outputs. It must resolve
the target chat the same way adoption does (``job.myah.chat_id`` → native Myah
``origin.chat_id`` → title fallback) and reuse the deterministic-id backfill
helper so reruns never duplicate messages or corrupt child pointers.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

VALID_JOB_ID = 'abcdef012345'


def _make_user(db_session, uid: str = 'user-sync-1'):
    from myah.models.users import Users

    Users.insert_new_user(id=uid, name='sync-test', email=f'{uid}@local', role='user')
    return Users.get_user_by_id(uid)


def _make_chat(db_session, user_id: str, title: str):
    from myah.models.chats import ChatForm, Chats

    form = ChatForm(chat={'title': title, 'history': {'messages': {}, 'currentId': None}})
    return Chats.insert_new_chat(user_id, form)


def _run(stem: str, ran_at: str, response: str = 'hello', status: str = 'ok') -> dict:
    return {'id': stem, 'ran_at': ran_at, 'status': status, 'response': response, 'prompt': ''}


def _patch_sync_deps(*, job: dict, runs: list[dict], container_name='cron-container'):
    import contextlib

    fake_container = type('FC', (), {'container_name': container_name, 'vite_port': None,
                                     'host_port': 9999, 'status': 'running', 'id': 'c'})()
    stack = contextlib.ExitStack()
    stack.enter_context(patch('myah.routers.processes._ensure_container', new=AsyncMock(return_value=9999)))
    stack.enter_context(patch('myah.routers.processes._hermes_get', new=AsyncMock(return_value={'job': job})))
    stack.enter_context(patch('myah.routers.processes._fetch_run_outputs', new=AsyncMock(return_value=runs)))
    stack.enter_context(patch('myah.models.containers.Containers.get_by_user_id', return_value=fake_container))
    return stack


@pytest.mark.asyncio
async def test_sync_process_chat_uses_myah_chat_id_before_title_match(db_session, monkeypatch):
    monkeypatch.setenv('MYAH_DEPLOYMENT_MODE', 'hosted')
    from myah.models.chats import Chats
    from myah.routers.processes import sync_process_chat

    user = _make_user(db_session)
    adopted = _make_chat(db_session, user.id, 'Some Older Chat')          # myah.chat_id target
    title_chat = _make_chat(db_session, user.id, 'Process: Digest')        # title-convention decoy
    job = {'id': VALID_JOB_ID, 'name': 'Digest', 'myah': {'chat_id': adopted.id}}
    runs = [_run('2026-05-29_09-00-00', '2026-05-29T09:00:00+00:00')]

    with _patch_sync_deps(job=job, runs=runs):
        await sync_process_chat(VALID_JOB_ID, user)

    adopted_msgs = Chats.get_chat_by_id(adopted.id).chat['history']['messages']
    title_msgs = Chats.get_chat_by_id(title_chat.id).chat['history']['messages']
    assert f'cron_{VALID_JOB_ID}_2026-05-29_09-00-00' in adopted_msgs
    assert title_msgs == {}, 'title-match chat must NOT be used when myah.chat_id resolves'


@pytest.mark.asyncio
async def test_sync_process_chat_uses_origin_chat_id_for_native_myah_jobs(db_session, monkeypatch):
    monkeypatch.setenv('MYAH_DEPLOYMENT_MODE', 'hosted')
    from myah.models.chats import Chats
    from myah.routers.processes import sync_process_chat

    user = _make_user(db_session)
    native = _make_chat(db_session, user.id, 'Native Chat')
    job = {'id': VALID_JOB_ID, 'name': 'Native', 'origin': {'platform': 'myah', 'chat_id': native.id}}
    runs = [_run('2026-05-29_09-00-00', '2026-05-29T09:00:00+00:00')]

    with _patch_sync_deps(job=job, runs=runs):
        await sync_process_chat(VALID_JOB_ID, user)

    msgs = Chats.get_chat_by_id(native.id).chat['history']['messages']
    assert f'cron_{VALID_JOB_ID}_2026-05-29_09-00-00' in msgs


@pytest.mark.asyncio
async def test_sync_process_chat_falls_back_to_title_match(db_session, monkeypatch):
    monkeypatch.setenv('MYAH_DEPLOYMENT_MODE', 'hosted')
    from myah.models.chats import Chats
    from myah.routers.processes import sync_process_chat

    user = _make_user(db_session)
    title_chat = _make_chat(db_session, user.id, 'Process: Legacy')
    job = {'id': VALID_JOB_ID, 'name': 'Legacy'}  # no myah, no origin
    runs = [_run('2026-05-29_09-00-00', '2026-05-29T09:00:00+00:00')]

    with _patch_sync_deps(job=job, runs=runs):
        await sync_process_chat(VALID_JOB_ID, user)

    msgs = Chats.get_chat_by_id(title_chat.id).chat['history']['messages']
    assert f'cron_{VALID_JOB_ID}_2026-05-29_09-00-00' in msgs


@pytest.mark.asyncio
async def test_sync_process_chat_uses_deterministic_message_ids(db_session, monkeypatch):
    monkeypatch.setenv('MYAH_DEPLOYMENT_MODE', 'hosted')
    from myah.models.chats import Chats
    from myah.routers.processes import sync_process_chat

    user = _make_user(db_session)
    chat = _make_chat(db_session, user.id, 'Process: Digest')
    job = {'id': VALID_JOB_ID, 'name': 'Digest'}
    runs = [
        _run('2026-05-29_09-00-00', '2026-05-29T09:00:00+00:00'),
        _run('2026-05-29_08-00-00', '2026-05-29T08:00:00+00:00'),
    ]
    with _patch_sync_deps(job=job, runs=runs):
        await sync_process_chat(VALID_JOB_ID, user)

    msgs = Chats.get_chat_by_id(chat.id).chat['history']['messages']
    assert set(msgs) == {
        f'cron_{VALID_JOB_ID}_2026-05-29_08-00-00',
        f'cron_{VALID_JOB_ID}_2026-05-29_09-00-00',
    }


@pytest.mark.asyncio
async def test_sync_process_chat_no_duplicate_children_on_rerun(db_session, monkeypatch):
    monkeypatch.setenv('MYAH_DEPLOYMENT_MODE', 'hosted')
    from myah.models.chats import Chats
    from myah.routers.processes import sync_process_chat

    user = _make_user(db_session)
    chat = _make_chat(db_session, user.id, 'Process: Digest')
    job = {'id': VALID_JOB_ID, 'name': 'Digest'}
    runs = [
        _run('2026-05-29_09-00-00', '2026-05-29T09:00:00+00:00'),
        _run('2026-05-29_08-00-00', '2026-05-29T08:00:00+00:00'),
    ]
    with _patch_sync_deps(job=job, runs=runs):
        await sync_process_chat(VALID_JOB_ID, user)
    with _patch_sync_deps(job=job, runs=runs):
        await sync_process_chat(VALID_JOB_ID, user)  # rerun

    msgs = Chats.get_chat_by_id(chat.id).chat['history']['messages']
    cron_ids = sorted(m for m in msgs if m.startswith(f'cron_{VALID_JOB_ID}_'))
    assert len(cron_ids) == 2, 'rerun must not duplicate messages'
    oldest = f'cron_{VALID_JOB_ID}_2026-05-29_08-00-00'
    newest = f'cron_{VALID_JOB_ID}_2026-05-29_09-00-00'
    assert msgs[oldest]['childrenIds'] == [newest], 'no duplicate child pointers on rerun'


@pytest.mark.asyncio
async def test_sync_process_chat_skips_existing_message_without_reparenting(db_session, monkeypatch):
    monkeypatch.setenv('MYAH_DEPLOYMENT_MODE', 'hosted')
    from myah.models.chats import Chats
    from myah.routers.processes import _backfill_runs_to_chat, sync_process_chat

    user = _make_user(db_session)
    chat = _make_chat(db_session, user.id, 'Process: Digest')
    job = {'id': VALID_JOB_ID, 'name': 'Digest'}

    # Seed the oldest run directly, then sync with [newer, oldest].
    _backfill_runs_to_chat(chat.id, VALID_JOB_ID, 'Digest',
                           [_run('2026-05-29_08-00-00', '2026-05-29T08:00:00+00:00')])
    oldest = f'cron_{VALID_JOB_ID}_2026-05-29_08-00-00'

    runs = [
        _run('2026-05-29_09-00-00', '2026-05-29T09:00:00+00:00'),
        _run('2026-05-29_08-00-00', '2026-05-29T08:00:00+00:00'),
    ]
    with _patch_sync_deps(job=job, runs=runs):
        await sync_process_chat(VALID_JOB_ID, user)

    msgs = Chats.get_chat_by_id(chat.id).chat['history']['messages']
    newer = f'cron_{VALID_JOB_ID}_2026-05-29_09-00-00'
    assert msgs[oldest]['parentId'] is None, 'existing message is not reparented'
    assert msgs[newer]['parentId'] == oldest
    assert msgs[oldest]['childrenIds'] == [newer]
