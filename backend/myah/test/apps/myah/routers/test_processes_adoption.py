"""Adopt Legacy Hermes Crons into Myah — backend Phase 0 + Phase 1 tests.

Phase 0 (this section): the safe job-metadata patch primitive
``_patch_job_myah_metadata``. It persists ``job.myah.*`` through the
myah-admin dashboard endpoint (``web_call``), and must:

  - accept a ``myah.chat_id`` / ``myah.adopted_at`` payload and forward it
    verbatim to the dashboard endpoint for the right job_id;
  - never carry top-level ``origin`` / ``deliver`` (native external
    delivery is preserved by *omission* — the platform never sends those
    keys so a plugin-side merge can't clobber them);
  - reject malformed / path-traversal job ids before any network call;
  - reject payloads that try to mutate non-Myah-owned top-level keys;
  - surface a clear error when the plugin endpoint is unavailable (404).

Phase 1 (second section): the ``POST /processes/{job_id}/adopt`` endpoint
and its helpers (``_build_myah_adoption_metadata``,
``_find_or_create_process_chat``, ``_backfill_runs_to_chat``).

These tests drive the implementation TDD-style. The Hermes/dashboard wire
calls are mocked; the chat layer uses the real per-test SQLite DB via the
``db_session`` fixtures in conftest.py.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

VALID_JOB_ID = 'abcdef012345'


def _web_call_result(status: int = 200, body=None) -> dict:
    return {'status': status, 'body': body if body is not None else {'ok': True}, 'headers': {}}


# ─────────────────────────────────────────────────────────────────────────────
# Phase 0 — _patch_job_myah_metadata
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_metadata_patch_accepts_myah_chat_id():
    """A valid job + myah block is forwarded verbatim to the dashboard
    endpoint for that job_id."""
    from myah.routers.processes import _patch_job_myah_metadata

    user = MagicMock(id='user-1')
    captured: dict = {}

    async def fake_web_call(u, method, path, *, json_body=None, **kw):
        captured['user'] = u
        captured['method'] = method
        captured['path'] = path
        captured['body'] = json_body
        return _web_call_result(200, {'job': {'id': VALID_JOB_ID}})

    with patch('myah.utils.hermes_web.web_call', side_effect=fake_web_call):
        await _patch_job_myah_metadata(
            user,
            VALID_JOB_ID,
            {'myah': {'chat_id': 'chat-1', 'adopted_at': '2026-05-29T00:00:00+00:00'}},
        )

    assert captured['user'] is user
    assert VALID_JOB_ID in captured['path']
    assert captured['path'].rstrip('/').endswith('myah-metadata')
    assert captured['body']['myah']['chat_id'] == 'chat-1'
    assert 'adopted_at' in captured['body']['myah']
    # Preserve native delivery by omission: never carry these keys.
    assert 'origin' not in captured['body']
    assert 'deliver' not in captured['body']


@pytest.mark.asyncio
async def test_metadata_patch_preserves_existing_origin_and_deliver():
    """The helper refuses to carry top-level origin/deliver, so a plugin
    merge can never clobber native external delivery."""
    from myah.routers.processes import _patch_job_myah_metadata

    user = MagicMock(id='user-1')
    wc = AsyncMock(return_value=_web_call_result())
    with patch('myah.utils.hermes_web.web_call', new=wc):
        with pytest.raises(HTTPException) as exc:
            await _patch_job_myah_metadata(
                user,
                VALID_JOB_ID,
                {'myah': {'chat_id': 'c1'}, 'origin': {'platform': 'telegram'}, 'deliver': 'origin'},
            )
    assert exc.value.status_code == 400
    wc.assert_not_called()


@pytest.mark.asyncio
async def test_metadata_patch_rejects_invalid_job_id():
    """Malformed / path-traversal job ids are rejected before any network call."""
    from myah.routers.processes import _patch_job_myah_metadata

    user = MagicMock(id='user-1')
    wc = AsyncMock(return_value=_web_call_result())
    bad_ids = ['../etc', 'ABCDEF012345', 'abcdef', 'abcdef0123456', 'abc/def01234', '', 'g' * 12]
    with patch('myah.utils.hermes_web.web_call', new=wc):
        for bad in bad_ids:
            with pytest.raises(HTTPException) as exc:
                await _patch_job_myah_metadata(user, bad, {'myah': {'chat_id': 'c1'}})
            assert exc.value.status_code == 400, bad
    wc.assert_not_called()


@pytest.mark.asyncio
async def test_metadata_patch_rejects_invalid_payload_shape():
    """Only the Myah-owned top-level key is allowed; everything else is rejected."""
    from myah.routers.processes import _patch_job_myah_metadata

    user = MagicMock(id='user-1')
    wc = AsyncMock(return_value=_web_call_result())
    bad_payloads = [
        {'deliver': 'local'},                           # non-myah top-level key
        {'myah': {'chat_id': 'c'}, 'enabled': False},   # sneaks an extra key
        {},                                             # empty
        {'myah': 'not-a-dict'},                         # myah not an object
        'not-a-dict',                                   # not a dict at all
        {'origin': {'platform': 'myah'}},               # origin is not patchable here
    ]
    with patch('myah.utils.hermes_web.web_call', new=wc):
        for payload in bad_payloads:
            with pytest.raises(HTTPException) as exc:
                await _patch_job_myah_metadata(user, VALID_JOB_ID, payload)
            assert exc.value.status_code == 400, payload
    wc.assert_not_called()


@pytest.mark.asyncio
async def test_metadata_patch_surfaces_unavailable_plugin_endpoint():
    """A 404 from the dashboard (plugin too old / endpoint missing) is
    surfaced as a clear error, never swallowed silently."""
    from myah.routers.processes import _patch_job_myah_metadata

    user = MagicMock(id='user-1')
    with patch(
        'myah.utils.hermes_web.web_call',
        new=AsyncMock(return_value=_web_call_result(404, {'detail': 'not found'})),
    ):
        with pytest.raises(HTTPException) as exc:
            await _patch_job_myah_metadata(user, VALID_JOB_ID, {'myah': {'chat_id': 'c1'}})
    # Not a generic 500 / not a silent success — a deliberate, recognisable code.
    assert exc.value.status_code in (501, 502, 503)
    assert 'plugin' in str(exc.value.detail).lower() or 'metadata' in str(exc.value.detail).lower()


@pytest.mark.asyncio
async def test_metadata_patch_surfaces_other_dashboard_errors():
    """A non-404 4xx/5xx from the dashboard propagates (not swallowed)."""
    from myah.routers.processes import _patch_job_myah_metadata

    user = MagicMock(id='user-1')
    with patch(
        'myah.utils.hermes_web.web_call',
        new=AsyncMock(return_value=_web_call_result(500, {'detail': 'boom'})),
    ):
        with pytest.raises(HTTPException) as exc:
            await _patch_job_myah_metadata(user, VALID_JOB_ID, {'myah': {'chat_id': 'c1'}})
    assert exc.value.status_code >= 400


# ─────────────────────────────────────────────────────────────────────────────
# Phase 1 — helpers: _build_myah_adoption_metadata + _backfill_runs_to_chat
# ─────────────────────────────────────────────────────────────────────────────


def _make_user(db_session, uid: str = 'user-adopt-1'):
    from myah.models.users import Users

    Users.insert_new_user(id=uid, name='adopt-test', email=f'{uid}@local', role='user')
    return Users.get_user_by_id(uid)


def _make_chat(db_session, user_id: str, title: str):
    from myah.models.chats import ChatForm, Chats

    form = ChatForm(chat={'title': title, 'history': {'messages': {}, 'currentId': None}})
    return Chats.insert_new_chat(user_id, form)


def _run(stem: str, ran_at: str, response: str = 'hello', status: str = 'ok') -> dict:
    return {'id': stem, 'ran_at': ran_at, 'status': status, 'response': response, 'prompt': ''}


def test_build_adoption_metadata_snapshots_legacy_origin():
    from myah.routers.processes import _build_myah_adoption_metadata

    job = {'id': VALID_JOB_ID, 'name': 'Nightly Digest',
           'origin': {'platform': 'telegram', 'chat_id': 'tg-99'}}
    md = _build_myah_adoption_metadata(job, 'myah-chat-1', '2026-05-29T00:00:00+00:00')

    assert set(md.keys()) == {'myah'}, 'only the Myah namespace is patched'
    myah = md['myah']
    assert myah['chat_id'] == 'myah-chat-1'
    assert myah['adopted_at'] == '2026-05-29T00:00:00+00:00'
    assert myah['chat_name'] == 'Process: Nightly Digest'
    # legacy origin is snapshotted so we never lose where it came from …
    assert myah['legacy_origin']['platform'] == 'telegram'
    assert myah['legacy_origin']['chat_id'] == 'tg-99'
    # … but the native top-level origin/deliver are NOT in the patch payload.
    assert 'origin' not in md
    assert 'deliver' not in md


def test_backfill_uses_deterministic_ids_oldest_to_newest_and_is_idempotent(db_session):
    from myah.models.chats import Chats
    from myah.routers.processes import _backfill_runs_to_chat

    user = _make_user(db_session)
    chat = _make_chat(db_session, user.id, 'Process: Digest')

    # _fetch_run_outputs returns NEWEST first.
    runs = [
        _run('2026-05-29_09-00-00', '2026-05-29T09:00:00+00:00', 'newest'),
        _run('2026-05-29_08-00-00', '2026-05-29T08:00:00+00:00', 'middle'),
        _run('2026-05-29_07-00-00', '2026-05-29T07:00:00+00:00', 'oldest'),
    ]
    backfilled, skipped = _backfill_runs_to_chat(chat.id, VALID_JOB_ID, 'Digest', runs)
    assert backfilled == 3
    assert skipped == 0

    refreshed = Chats.get_chat_by_id(chat.id)
    messages = refreshed.chat['history']['messages']
    # Deterministic ids: cron_{job_id}_{stem}
    oldest_id = f'cron_{VALID_JOB_ID}_2026-05-29_07-00-00'
    middle_id = f'cron_{VALID_JOB_ID}_2026-05-29_08-00-00'
    newest_id = f'cron_{VALID_JOB_ID}_2026-05-29_09-00-00'
    assert {oldest_id, middle_id, newest_id} <= set(messages)
    # Chain is oldest -> middle -> newest (parentId links forward in time).
    assert messages[oldest_id]['parentId'] is None
    assert messages[middle_id]['parentId'] == oldest_id
    assert messages[newest_id]['parentId'] == middle_id
    assert messages[oldest_id]['childrenIds'] == [middle_id]
    assert messages[middle_id]['childrenIds'] == [newest_id]
    assert refreshed.chat['history']['currentId'] == newest_id

    # Rerun is idempotent: nothing new, no duplicate children.
    backfilled2, skipped2 = _backfill_runs_to_chat(chat.id, VALID_JOB_ID, 'Digest', runs)
    assert backfilled2 == 0
    assert skipped2 == 3
    refreshed2 = Chats.get_chat_by_id(chat.id)
    messages2 = refreshed2.chat['history']['messages']
    assert len(messages2) == len(messages)
    assert messages2[oldest_id]['childrenIds'] == [middle_id], 'no duplicate child pointers on rerun'


def test_backfill_skips_existing_message_without_reparenting(db_session):
    from myah.models.chats import Chats
    from myah.routers.processes import _backfill_runs_to_chat

    user = _make_user(db_session)
    chat = _make_chat(db_session, user.id, 'Process: Digest')

    first = [_run('2026-05-29_07-00-00', '2026-05-29T07:00:00+00:00', 'oldest')]
    _backfill_runs_to_chat(chat.id, VALID_JOB_ID, 'Digest', first)
    oldest_id = f'cron_{VALID_JOB_ID}_2026-05-29_07-00-00'

    # New run arrives; oldest already present → only the new one is appended,
    # parented onto the existing tail, existing message untouched.
    both = [
        _run('2026-05-29_08-00-00', '2026-05-29T08:00:00+00:00', 'newer'),
        _run('2026-05-29_07-00-00', '2026-05-29T07:00:00+00:00', 'oldest'),
    ]
    backfilled, skipped = _backfill_runs_to_chat(chat.id, VALID_JOB_ID, 'Digest', both)
    assert backfilled == 1
    assert skipped == 1
    newer_id = f'cron_{VALID_JOB_ID}_2026-05-29_08-00-00'
    messages = Chats.get_chat_by_id(chat.id).chat['history']['messages']
    assert messages[newer_id]['parentId'] == oldest_id
    assert messages[oldest_id]['childrenIds'] == [newer_id]


def test_webhook_run_id_uses_deterministic_message_id_and_dedupes_backfill(db_session):
    from myah.models.chats import Chats
    from myah.routers.processes import _backfill_runs_to_chat, _inject_cron_output_to_chat

    user = _make_user(db_session)
    chat = _make_chat(db_session, user.id, 'Process: Digest')
    run_id = '2026-05-29_07-00-00'
    _backfill_runs_to_chat(
        chat.id,
        VALID_JOB_ID,
        'Digest',
        [_run(run_id, '2026-05-29T07:00:00+00:00', 'backfilled response')],
    )

    import asyncio

    delivered = asyncio.run(
        _inject_cron_output_to_chat(
            user.id,
            'Digest',
            'live duplicate response',
            'ok',
            '2026-05-29T07:00:00+00:00',
            chat_id=chat.id,
            msg_id=f'cron_{VALID_JOB_ID}_{run_id}',
        )
    )

    assert delivered is True
    refreshed = Chats.get_chat_by_id(chat.id)
    messages = refreshed.chat['history']['messages']
    assert len(messages) == 1
    assert messages[f'cron_{VALID_JOB_ID}_{run_id}']['content'].endswith('backfilled response')


def test_explicit_cron_chat_lookup_is_scoped_to_webhook_user(db_session):
    from myah.routers.processes import _inject_cron_output_to_chat

    owner = _make_user(db_session, uid='chat-owner')
    attacker = _make_user(db_session, uid='webhook-user')
    owner_chat = _make_chat(db_session, owner.id, 'Process: Digest')

    import asyncio

    delivered = asyncio.run(
        _inject_cron_output_to_chat(
            attacker.id,
            'Digest',
            'should not land in owner chat',
            'ok',
            '2026-05-29T07:00:00+00:00',
            chat_id=owner_chat.id,
            suppress_chat_lookup_sentry=True,
        )
    )

    assert delivered is False


# ─────────────────────────────────────────────────────────────────────────────
# Phase 1 — POST /processes/{job_id}/adopt endpoint
# ─────────────────────────────────────────────────────────────────────────────


def _patch_endpoint_deps(*, job: dict, runs: list[dict], metadata_calls: list, container_name='cron-container'):
    """Context-manager bundle stubbing the agent-container + Hermes layers the
    adopt endpoint depends on. Returns a contextlib.ExitStack-style list."""
    import contextlib

    fake_container = type('FakeContainer', (), {'container_name': container_name, 'vite_port': None,
                                                'host_port': 9999, 'status': 'running', 'id': 'c'})()

    async def fake_patch(user, job_id, metadata):
        metadata_calls.append({'job_id': job_id, 'metadata': metadata})
        return {'job': {'id': job_id, **metadata}}

    stack = contextlib.ExitStack()
    stack.enter_context(patch('myah.routers.processes._ensure_container', new=AsyncMock(return_value=9999)))
    stack.enter_context(patch('myah.routers.processes._hermes_get', new=AsyncMock(return_value={'job': job})))
    stack.enter_context(patch('myah.routers.processes._fetch_run_outputs', new=AsyncMock(return_value=runs)))
    stack.enter_context(patch('myah.routers.processes._patch_job_myah_metadata', side_effect=fake_patch))
    stack.enter_context(patch('myah.models.containers.Containers.get_by_user_id', return_value=fake_container))
    return stack


@pytest.mark.asyncio
async def test_adopt_legacy_process_creates_chat_patches_metadata_and_backfills(db_session, monkeypatch):
    monkeypatch.setenv('MYAH_DEPLOYMENT_MODE', 'hosted')
    from myah.models.chats import Chats
    from myah.routers.processes import ProcessAdoptForm, adopt_process

    user = _make_user(db_session)
    job = {'id': VALID_JOB_ID, 'name': 'Nightly Digest'}  # legacy: no myah, no origin
    runs = [
        _run('2026-05-29_09-00-00', '2026-05-29T09:00:00+00:00', 'newest'),
        _run('2026-05-29_08-00-00', '2026-05-29T08:00:00+00:00', 'oldest'),
    ]
    metadata_calls: list = []

    with _patch_endpoint_deps(job=job, runs=runs, metadata_calls=metadata_calls):
        resp = await adopt_process(VALID_JOB_ID, ProcessAdoptForm(), user)

    assert resp['ok'] is True
    assert resp['created_chat'] is True
    assert resp['backfilled'] == 2
    assert resp['skipped_existing'] == 0
    chat_id = resp['chat_id']

    # A "Process: {name}" chat was created and owned by the user.
    created = Chats.get_chat_by_id_and_user_id(chat_id, user.id)
    assert created is not None
    assert created.title == 'Process: Nightly Digest'

    # Metadata patch carried myah.chat_id only — never origin/deliver.
    assert len(metadata_calls) == 1
    md = metadata_calls[0]['metadata']
    assert md['myah']['chat_id'] == chat_id
    assert 'origin' not in md and 'deliver' not in md

    # Backfill is oldest-to-newest with deterministic ids.
    messages = created.chat['history']['messages']
    oldest_id = f'cron_{VALID_JOB_ID}_2026-05-29_08-00-00'
    newest_id = f'cron_{VALID_JOB_ID}_2026-05-29_09-00-00'
    assert messages[oldest_id]['parentId'] is None
    assert messages[newest_id]['parentId'] == oldest_id
    assert 'Cron run' in messages[oldest_id]['content']


@pytest.mark.asyncio
async def test_adopt_existing_myah_metadata_is_idempotent(db_session, monkeypatch):
    monkeypatch.setenv('MYAH_DEPLOYMENT_MODE', 'hosted')
    from myah.models.chats import Chats
    from myah.routers.processes import ProcessAdoptForm, adopt_process

    user = _make_user(db_session)
    existing = _make_chat(db_session, user.id, 'Process: Digest')
    job = {'id': VALID_JOB_ID, 'name': 'Digest', 'myah': {'chat_id': existing.id}}
    runs = [
        _run('2026-05-29_09-00-00', '2026-05-29T09:00:00+00:00'),
        _run('2026-05-29_08-00-00', '2026-05-29T08:00:00+00:00'),
    ]

    with _patch_endpoint_deps(job=job, runs=runs, metadata_calls=[]):
        first = await adopt_process(VALID_JOB_ID, ProcessAdoptForm(), user)
    assert first['created_chat'] is False
    assert first['chat_id'] == existing.id
    assert first['backfilled'] == 2

    with _patch_endpoint_deps(job=job, runs=runs, metadata_calls=[]):
        second = await adopt_process(VALID_JOB_ID, ProcessAdoptForm(), user)
    assert second['backfilled'] == 0
    assert second['skipped_existing'] == 2

    # No duplicate messages across reruns.
    messages = Chats.get_chat_by_id(existing.id).chat['history']['messages']
    cron_msgs = [m for m in messages if m.startswith(f'cron_{VALID_JOB_ID}_')]
    assert len(cron_msgs) == 2


@pytest.mark.asyncio
async def test_adopt_existing_myah_origin_is_idempotent(db_session, monkeypatch):
    monkeypatch.setenv('MYAH_DEPLOYMENT_MODE', 'hosted')
    from myah.routers.processes import ProcessAdoptForm, adopt_process

    user = _make_user(db_session)
    existing = _make_chat(db_session, user.id, 'Process: Native')
    # Native Myah job: origin.platform == 'myah' with a valid owned chat.
    job = {'id': VALID_JOB_ID, 'name': 'Native',
           'origin': {'platform': 'myah', 'chat_id': existing.id}}
    runs = [_run('2026-05-29_08-00-00', '2026-05-29T08:00:00+00:00')]

    with _patch_endpoint_deps(job=job, runs=runs, metadata_calls=[]):
        resp = await adopt_process(VALID_JOB_ID, ProcessAdoptForm(), user)
    assert resp['created_chat'] is False
    assert resp['chat_id'] == existing.id


@pytest.mark.asyncio
async def test_adopt_preserves_deliver_and_external_origin_by_default(db_session, monkeypatch):
    monkeypatch.setenv('MYAH_DEPLOYMENT_MODE', 'hosted')
    from myah.routers.processes import ProcessAdoptForm, adopt_process

    user = _make_user(db_session)
    job = {'id': VALID_JOB_ID, 'name': 'TG Bot', 'deliver': 'origin',
           'origin': {'platform': 'telegram', 'chat_id': 'tg-1'}}
    metadata_calls: list = []

    with _patch_endpoint_deps(job=job, runs=[], metadata_calls=metadata_calls):
        resp = await adopt_process(VALID_JOB_ID, ProcessAdoptForm(), user)

    assert resp['ok'] is True
    # external origin → a fresh Myah chat is created (we do not reuse tg origin).
    assert resp['created_chat'] is True
    md = metadata_calls[0]['metadata']
    assert md['myah']['chat_id'] == resp['chat_id']
    # The legacy telegram origin is snapshotted but native origin/deliver are
    # never sent in the patch (preserved by omission).
    assert md['myah']['legacy_origin']['platform'] == 'telegram'
    assert 'origin' not in md and 'deliver' not in md


@pytest.mark.asyncio
async def test_adopt_rejects_chat_not_owned_by_user(db_session, monkeypatch):
    monkeypatch.setenv('MYAH_DEPLOYMENT_MODE', 'hosted')
    from myah.routers.processes import ProcessAdoptForm, adopt_process

    user = _make_user(db_session)
    # chat_id that does not exist / not owned
    with patch('myah.routers.processes._ensure_container', new=AsyncMock(return_value=9999)) as mc:
        with pytest.raises(HTTPException) as exc:
            await adopt_process(VALID_JOB_ID, ProcessAdoptForm(chat_id='not-mine'), user)
    assert exc.value.status_code == 404
    mc.assert_not_called()  # ownership rejected before any container work


@pytest.mark.asyncio
async def test_adopt_rejects_local_temp_chat_id(db_session, monkeypatch):
    monkeypatch.setenv('MYAH_DEPLOYMENT_MODE', 'hosted')
    from myah.routers.processes import ProcessAdoptForm, adopt_process

    user = _make_user(db_session)
    with patch('myah.routers.processes._ensure_container', new=AsyncMock(return_value=9999)) as mc:
        with pytest.raises(HTTPException) as exc:
            await adopt_process(VALID_JOB_ID, ProcessAdoptForm(chat_id='local:temp-1'), user)
    assert exc.value.status_code == 400
    mc.assert_not_called()


@pytest.mark.asyncio
async def test_adopt_missing_job_returns_404(db_session, monkeypatch):
    monkeypatch.setenv('MYAH_DEPLOYMENT_MODE', 'hosted')
    from myah.routers.processes import ProcessAdoptForm, adopt_process

    user = _make_user(db_session)
    fake_container = type('FC', (), {'container_name': 'c', 'host_port': 9999, 'status': 'running', 'id': 'c'})()
    with patch('myah.routers.processes._ensure_container', new=AsyncMock(return_value=9999)), \
         patch('myah.routers.processes._hermes_get', new=AsyncMock(return_value={'job': None})), \
         patch('myah.models.containers.Containers.get_by_user_id', return_value=fake_container):
        with pytest.raises(HTTPException) as exc:
            await adopt_process(VALID_JOB_ID, ProcessAdoptForm(), user)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_adopt_reports_truncated_history_when_limit_hit(db_session, monkeypatch):
    monkeypatch.setenv('MYAH_DEPLOYMENT_MODE', 'hosted')
    from myah.routers.processes import ProcessAdoptForm, adopt_process

    user = _make_user(db_session)
    job = {'id': VALID_JOB_ID, 'name': 'Digest'}
    # backfill_limit=1, but _fetch_run_outputs returns exactly the limit → truncated.
    runs = [_run('2026-05-29_09-00-00', '2026-05-29T09:00:00+00:00')]

    with _patch_endpoint_deps(job=job, runs=runs, metadata_calls=[]):
        resp = await adopt_process(VALID_JOB_ID, ProcessAdoptForm(backfill_limit=1), user)
    assert resp['truncated'] is True

    # Fewer runs than the limit → not truncated.
    with _patch_endpoint_deps(job=job, runs=runs, metadata_calls=[]):
        resp2 = await adopt_process(VALID_JOB_ID, ProcessAdoptForm(backfill_limit=50), user)
    assert resp2['truncated'] is False
