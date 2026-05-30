"""Adopt Legacy Hermes Crons — backend Phase 2: process response normalization.

``_normalize_process_for_myah(job, user)`` is the single source of truth for
the adoption fields the frontend consumes:

  - ``chat_id``        — navigation target (only a *real, owned* Myah chat);
  - ``adoptable``      — whether to show the "Adopt into Myah" affordance;
  - ``adoption_state`` — myah_linked | legacy_unowned | external_origin |
                         myah_origin_missing_chat.

Both the list route and the detail route must run jobs through it so the two
surfaces never disagree.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

VALID_JOB_ID = 'abcdef012345'


def _make_user(db_session, uid: str = 'user-norm-1'):
    from myah.models.users import Users

    Users.insert_new_user(id=uid, name='norm-test', email=f'{uid}@local', role='user')
    return Users.get_user_by_id(uid)


def _make_chat(db_session, user_id: str, title: str):
    from myah.models.chats import ChatForm, Chats

    form = ChatForm(chat={'title': title, 'history': {'messages': {}, 'currentId': None}})
    return Chats.insert_new_chat(user_id, form)


# ── unit: state classification ──────────────────────────────────────────────


def test_external_origin_marked_external_origin_not_plain_legacy():
    from myah.routers.processes import _normalize_process_for_myah

    job = {'id': VALID_JOB_ID, 'name': 'TG', 'deliver': 'origin',
           'origin': {'platform': 'telegram', 'chat_id': 'tg-1'}}
    out = _normalize_process_for_myah(job, user=None)
    assert out['adoption_state'] == 'external_origin'
    assert out['adoptable'] is True
    # never expose a non-Myah origin chat id as a Myah navigation target
    assert out['chat_id'] is None


def test_no_origin_marked_legacy_unowned():
    from myah.routers.processes import _normalize_process_for_myah

    job = {'id': VALID_JOB_ID, 'name': 'Bare cron'}
    out = _normalize_process_for_myah(job, user=None)
    assert out['adoption_state'] == 'legacy_unowned'
    assert out['adoptable'] is True
    assert out['chat_id'] is None


def test_myah_metadata_chat_is_linked_and_not_adoptable(db_session):
    from myah.routers.processes import _normalize_process_for_myah

    user = _make_user(db_session)
    chat = _make_chat(db_session, user.id, 'Process: X')
    job = {'id': VALID_JOB_ID, 'name': 'X', 'myah': {'chat_id': chat.id}}
    out = _normalize_process_for_myah(job, user=user)
    assert out['chat_id'] == chat.id
    assert out['adoption_state'] == 'myah_linked'
    assert out['adoptable'] is False


def test_native_myah_origin_is_linked(db_session):
    from myah.routers.processes import _normalize_process_for_myah

    user = _make_user(db_session)
    chat = _make_chat(db_session, user.id, 'Process: Native')
    job = {'id': VALID_JOB_ID, 'name': 'Native', 'origin': {'platform': 'myah', 'chat_id': chat.id}}
    out = _normalize_process_for_myah(job, user=user)
    assert out['chat_id'] == chat.id
    assert out['adoption_state'] == 'myah_linked'


def test_myah_metadata_preferred_over_native_origin(db_session):
    """When both myah.chat_id and a native origin exist, myah metadata wins."""
    from myah.routers.processes import _normalize_process_for_myah

    user = _make_user(db_session)
    adopted = _make_chat(db_session, user.id, 'Process: Adopted')
    job = {
        'id': VALID_JOB_ID,
        'name': 'Both',
        'myah': {'chat_id': adopted.id},
        'origin': {'platform': 'myah', 'chat_id': 'some-other-chat'},
    }
    out = _normalize_process_for_myah(job, user=user)
    assert out['chat_id'] == adopted.id


def test_myah_origin_missing_chat_state(db_session):
    """Claims a Myah chat that doesn't exist / isn't owned → repair state, no nav."""
    from myah.routers.processes import _normalize_process_for_myah

    user = _make_user(db_session)
    job = {'id': VALID_JOB_ID, 'name': 'Gone', 'myah': {'chat_id': 'deleted-or-foreign'}}
    out = _normalize_process_for_myah(job, user=user)
    assert out['adoption_state'] == 'myah_origin_missing_chat'
    assert out['chat_id'] is None
    assert out['adoptable'] is True


def test_external_origin_with_myah_metadata_is_linked(db_session):
    """An adopted external-origin job (telegram origin + myah.chat_id) is linked."""
    from myah.routers.processes import _normalize_process_for_myah

    user = _make_user(db_session)
    chat = _make_chat(db_session, user.id, 'Process: Adopted TG')
    job = {
        'id': VALID_JOB_ID,
        'name': 'Adopted TG',
        'deliver': 'origin',
        'origin': {'platform': 'telegram', 'chat_id': 'tg-1'},
        'myah': {'chat_id': chat.id},
    }
    out = _normalize_process_for_myah(job, user=user)
    assert out['chat_id'] == chat.id
    assert out['adoption_state'] == 'myah_linked'


# ── integration: list + get expose the same fields ─────────────────────────


@pytest.mark.asyncio
async def test_list_processes_derives_chat_id_from_myah_metadata(db_session):
    from myah.routers.processes import list_processes

    user = _make_user(db_session)
    chat = _make_chat(db_session, user.id, 'Process: Linked')
    job = {'id': VALID_JOB_ID, 'name': 'Linked', 'myah': {'chat_id': chat.id}}
    fake_container = type('FC', (), {'container_name': None, 'vite_port': 5173,
                                     'host_port': 9999, 'status': 'running', 'id': 'c'})()
    with patch('myah.routers.processes._ensure_container', new=AsyncMock(return_value=9999)), \
         patch('myah.routers.processes._hermes_get', new=AsyncMock(return_value={'jobs': [dict(job)]})), \
         patch('myah.models.containers.Containers.get_by_user_id', return_value=fake_container):
        listed = await list_processes(user)
    assert listed[0]['chat_id'] == chat.id
    assert listed[0]['adoption_state'] == 'myah_linked'


@pytest.mark.asyncio
async def test_list_processes_derives_chat_id_from_native_myah_origin(db_session):
    from myah.routers.processes import list_processes

    user = _make_user(db_session)
    chat = _make_chat(db_session, user.id, 'Process: Native')
    job = {'id': VALID_JOB_ID, 'name': 'Native', 'origin': {'platform': 'myah', 'chat_id': chat.id}}
    fake_container = type('FC', (), {'container_name': None, 'vite_port': None,
                                     'host_port': 9999, 'status': 'running', 'id': 'c'})()
    with patch('myah.routers.processes._ensure_container', new=AsyncMock(return_value=9999)), \
         patch('myah.routers.processes._hermes_get', new=AsyncMock(return_value={'jobs': [dict(job)]})), \
         patch('myah.models.containers.Containers.get_by_user_id', return_value=fake_container):
        listed = await list_processes(user)
    assert listed[0]['chat_id'] == chat.id
    assert listed[0]['adoption_state'] == 'myah_linked'


@pytest.mark.asyncio
async def test_get_process_includes_same_adoption_state_as_list(db_session):
    from myah.routers.processes import get_process, list_processes

    user = _make_user(db_session)
    # external origin → adoptable external_origin in BOTH surfaces
    job = {'id': VALID_JOB_ID, 'name': 'TG', 'deliver': 'origin',
           'origin': {'platform': 'telegram', 'chat_id': 'tg-1'}}
    fake_container = type('FC', (), {'container_name': None, 'vite_port': None,
                                     'host_port': 9999, 'status': 'running', 'id': 'c'})()
    with patch('myah.routers.processes._ensure_container', new=AsyncMock(return_value=9999)), \
         patch('myah.models.containers.Containers.get_by_user_id', return_value=fake_container):
        with patch('myah.routers.processes._hermes_get', new=AsyncMock(return_value={'jobs': [dict(job)]})):
            listed = await list_processes(user)
        with patch('myah.routers.processes._hermes_get', new=AsyncMock(return_value={'job': dict(job)})):
            got = await get_process(VALID_JOB_ID, user)

    assert listed[0]['adoption_state'] == 'external_origin'
    assert got['adoption_state'] == listed[0]['adoption_state']
    assert got['adoptable'] == listed[0]['adoptable']
    assert got['chat_id'] == listed[0]['chat_id'] is None
