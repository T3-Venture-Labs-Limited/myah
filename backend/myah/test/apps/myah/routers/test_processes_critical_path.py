"""T3-1092 Task 5 — cron/process route critical-path regression tests.

Protected surfaces (see ``docs/testing/critical-path-coverage.md``):

* S5 — process CRUD/state transitions (``list``/``get``/``update``/``delete``/
  ``pause``/``resume``/``trigger`` proxy behaviour + the ``ui-action`` action
  route's container-write-failure branch).
* S6 — the ``/webhook/run-started`` inbound webhook (auth, required fields,
  Socket.IO emit). The ``/webhook/run-complete`` outbox/idempotency behaviour is
  already protected by ``backend/myah/test/test_cron_outbox.py`` and is mapped
  there rather than duplicated here.
* S7 — the ``/{job_id}/respond`` human-in-the-loop path (validation + the
  container pending-file write).
* S10 — artifact/result retrieval boundary protection (``/{job_id}/artifact``
  and ``/{job_id}/runs`` validation branches).

Scope / safety:

* No real network calls — every outbound Hermes/agent HTTP call and every
  ``docker exec`` is replaced with a local fake/mock.
* No real secrets — only placeholder bearer/token values are used.
* These tests assert proxy-boundary behaviour (the URL Hermes is called on, the
  envelope unwrap the frontend depends on, the payload written into the agent
  container), not brittle implementation internals.

This file deliberately does NOT re-assert the OSS-vs-hosted 501 gating, which is
owned by ``test_processes_oss_parity.py`` /
``test_processes_oss_route_classification.py`` (S11), nor the create_process
``origin`` forwarding owned by ``test_processes_origin.py``.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from myah.models.users import UserModel
from myah.routers import processes as processes_module
from myah.utils.auth import get_verified_user

VALID_JOB_ID = 'abcdef012345'  # 12 hex chars — matches the ^[a-f0-9]{12}$ guard


def _fake_user() -> UserModel:
    now = int(dt.datetime.now(dt.UTC).timestamp())
    return UserModel(
        id='user-9',
        email='cron-cp@test.local',
        name='Critical Path User',
        role='admin',
        last_active_at=now,
        updated_at=now,
        created_at=now,
    )


@pytest.fixture
def hosted_client(
    monkeypatch: pytest.MonkeyPatch,
    test_client_factory: Callable[[FastAPI], TestClient],
) -> TestClient:
    """TestClient for the processes router in *hosted* mode.

    Hosted mode means ``_raise_if_oss_mode()`` is a no-op, so the
    container-only routes (respond / ui-action / runs / artifact) reach their
    real handler bodies instead of short-circuiting to 501.
    """
    monkeypatch.setenv('MYAH_DEPLOYMENT_MODE', 'hosted')
    app = FastAPI()
    app.include_router(processes_module.router, prefix='/api/v1/processes')
    app.dependency_overrides[get_verified_user] = _fake_user
    return test_client_factory(app)


# ─────────────────────────────────────────────────────────────────────────────
# S5 — process CRUD / state-transition proxy behaviour
#
# These call the route coroutines directly (mirroring test_processes_origin.py)
# so the assertions can pin the exact Hermes URL + envelope-unwrap contract the
# frontend relies on. The OSS-parity suite only asserts "not 501"; it does not
# pin the proxy URL or the {"job": ...} / {"jobs": ...} unwrap.
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_processes_unwraps_jobs_envelope_and_surfaces_origin_chat_id():
    """``list`` returns the inner job list, stamps ``vite_port``, fills the
    enrichment defaults when there is no container_name, and surfaces
    ``origin.chat_id`` to a top-level ``chat_id`` (Bug A) without clobbering an
    already-present top-level ``chat_id``."""
    user = MagicMock(id='user-1')
    # container_name=None → the docker-exec enrichment block is skipped, so the
    # test needs no subprocess mock and the default-headline branch runs.
    fake_container = MagicMock(container_name=None, vite_port=5173)
    jobs_envelope = {
        'jobs': [
            {'id': VALID_JOB_ID, 'name': 'job-a', 'origin': {'platform': 'myah', 'chat_id': 'chat-from-origin'}},
            {'id': '0123456789ab', 'name': 'job-b', 'chat_id': 'explicit-chat'},
        ]
    }

    async def fake_get(_url):
        return jobs_envelope

    async def fake_ensure(_user):
        return 9999

    with (
        patch('myah.routers.processes._hermes_get', side_effect=fake_get),
        patch('myah.routers.processes._ensure_container', side_effect=fake_ensure),
        patch('myah.models.containers.Containers.get_by_user_id', return_value=fake_container),
    ):
        result = await processes_module.list_processes(user)

    assert isinstance(result, list), 'list route must unwrap {"jobs": [...]} to a plain list'
    by_name = {j['name']: j for j in result}
    assert set(by_name) == {'job-a', 'job-b'}
    # New adoption contract: origin.chat_id is only a navigation target when it
    # resolves to a real owned Myah chat; otherwise the cron is repair-adoptable.
    assert by_name['job-a']['chat_id'] is None
    assert by_name['job-a']['adoption_state'] == 'myah_origin_missing_chat'
    assert by_name['job-a']['adoptable'] is True
    # A stale top-level chat_id is no longer exposed as a navigation target;
    # without Myah metadata/origin it remains adoptable as a legacy unowned cron.
    assert by_name['job-b']['chat_id'] is None
    assert by_name['job-b']['adoption_state'] == 'legacy_unowned'
    assert by_name['job-b']['adoptable'] is True
    for job in result:
        assert job['vite_port'] == 5173
        assert job['last_run_headline'] is None
        assert job['has_pending_input'] is False


@pytest.mark.asyncio
async def test_get_process_unwraps_job_envelope():
    """``get`` calls ``/api/jobs/{id}`` and unwraps the ``{"job": ...}`` envelope."""
    user = MagicMock(id='user-1')
    seen = {}

    async def fake_get(url):
        seen['url'] = url
        return {'job': {'id': VALID_JOB_ID, 'name': 'job-a'}}

    async def fake_ensure(_user):
        return 9999

    with (
        patch('myah.routers.processes._hermes_get', side_effect=fake_get),
        patch('myah.routers.processes._ensure_container', side_effect=fake_ensure),
    ):
        result = await processes_module.get_process(VALID_JOB_ID, user)

    assert seen['url'].endswith(f'/api/jobs/{VALID_JOB_ID}')
    assert result['id'] == VALID_JOB_ID
    assert result['name'] == 'job-a'
    assert result['chat_id'] is None
    assert result['adoption_state'] == 'legacy_unowned'
    assert result['adoptable'] is True


@pytest.mark.asyncio
async def test_update_process_forwards_only_set_fields_and_unwraps():
    """``update`` forwards only the fields the caller set (exclude_none) and
    unwraps the returned job envelope."""
    user = MagicMock(id='user-1')
    captured = {}

    async def fake_patch(url, body):
        captured['url'] = url
        captured['body'] = body
        return {'job': {'id': VALID_JOB_ID, 'name': 'renamed'}}

    async def fake_ensure(_user):
        return 9999

    form = processes_module.ProcessUpdateForm(name='renamed')

    with (
        patch('myah.routers.processes._hermes_patch', side_effect=fake_patch),
        patch('myah.routers.processes._ensure_container', side_effect=fake_ensure),
    ):
        result = await processes_module.update_process(VALID_JOB_ID, form, user)

    assert captured['url'].endswith(f'/api/jobs/{VALID_JOB_ID}')
    # Unset fields (schedule/prompt/...) must NOT be forwarded as null overwrites.
    assert captured['body'] == {'name': 'renamed'}
    assert result == {'id': VALID_JOB_ID, 'name': 'renamed'}


@pytest.mark.asyncio
async def test_delete_process_returns_proxy_result():
    """``delete`` calls ``DELETE /api/jobs/{id}`` and returns the proxy result."""
    user = MagicMock(id='user-1')
    seen = {}

    async def fake_delete(url):
        seen['url'] = url
        return {'ok': True}

    async def fake_ensure(_user):
        return 9999

    with (
        patch('myah.routers.processes._hermes_delete', side_effect=fake_delete),
        patch('myah.routers.processes._ensure_container', side_effect=fake_ensure),
    ):
        result = await processes_module.delete_process(VALID_JOB_ID, user)

    assert seen['url'].endswith(f'/api/jobs/{VALID_JOB_ID}')
    assert result == {'ok': True}


@pytest.mark.asyncio
async def test_pause_and_resume_post_to_expected_paths_and_unwrap():
    """``pause``/``resume`` POST to ``/api/jobs/{id}/pause`` and ``.../resume``."""
    user = MagicMock(id='user-1')
    seen: list[str] = []

    async def fake_post(url, body=None):
        seen.append(url)
        return {'job': {'id': VALID_JOB_ID, 'status': 'toggled'}}

    async def fake_ensure(_user):
        return 9999

    with (
        patch('myah.routers.processes._hermes_post', side_effect=fake_post),
        patch('myah.routers.processes._ensure_container', side_effect=fake_ensure),
    ):
        paused = await processes_module.pause_process(VALID_JOB_ID, user)
        resumed = await processes_module.resume_process(VALID_JOB_ID, user)

    assert seen[0].endswith(f'/api/jobs/{VALID_JOB_ID}/pause')
    assert seen[1].endswith(f'/api/jobs/{VALID_JOB_ID}/resume')
    assert paused == {'id': VALID_JOB_ID, 'status': 'toggled'}
    assert resumed == {'id': VALID_JOB_ID, 'status': 'toggled'}


@pytest.mark.asyncio
async def test_trigger_process_posts_to_run_not_trigger():
    """Regression: Hermes' manual-run endpoint suffix is ``/run``, NOT
    ``/trigger`` (documented quirk at processes.py). If this flips, manual
    'Run now' silently 404s against the agent."""
    user = MagicMock(id='user-1')
    seen: list[str] = []

    async def fake_post(url, body=None):
        seen.append(url)
        return {'job': {'id': VALID_JOB_ID}}

    async def fake_ensure(_user):
        return 9999

    with (
        patch('myah.routers.processes._hermes_post', side_effect=fake_post),
        patch('myah.routers.processes._ensure_container', side_effect=fake_ensure),
    ):
        await processes_module.trigger_process(VALID_JOB_ID, user)

    assert len(seen) == 1
    assert seen[0].endswith(f'/api/jobs/{VALID_JOB_ID}/run'), seen
    assert '/trigger' not in seen[0]


# ─────────────────────────────────────────────────────────────────────────────
# S5 — ui-action container-write-failure branch (RED → GREEN)
#
# When the docker-exec write of the action record fails (returncode != 0) the
# handler must log a warning and CONTINUE on to drive the agent. Before the fix
# it referenced an undefined ``log`` (NameError) and 500'd instead.
# ─────────────────────────────────────────────────────────────────────────────


def test_ui_action_continues_when_container_write_fails(hosted_client: TestClient):
    """A failed action-record write must not abort the request: the handler
    logs and proceeds to the agent call. (RED before the log→logger fix:
    NameError on the undefined ``log`` symbol.)"""
    fake_container = MagicMock(container_name='myah-agent-user-9')

    class _FailingProc:
        returncode = 1  # the action-record write FAILED

        async def communicate(self, input=None):
            return (b'', b'no space left on device')

    async def fake_exec(*_args, **_kwargs):
        return _FailingProc()

    class _FakeResp:
        def raise_for_status(self):
            return None

        def json(self):
            return {'choices': [{'message': {'content': 'agent handled it'}}]}

    class _FakeAsyncClient:
        def __init__(self, *_a, **_k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

        async def post(self, *_a, **_k):
            return _FakeResp()

    async def fake_ensure(_user):
        return 9999

    async def fake_get(_url):
        return {'job': {'id': VALID_JOB_ID, 'name': 'My Process'}}

    with (
        patch('myah.routers.processes._ensure_container', side_effect=fake_ensure),
        patch('myah.models.containers.Containers.get_by_user_id', return_value=fake_container),
        patch('myah.routers.processes.asyncio.create_subprocess_exec', side_effect=fake_exec),
        patch('myah.routers.processes._hermes_get', side_effect=fake_get),
        patch('myah.models.chats.Chats.get_chat_list_by_user_id', return_value=[]),
        patch('myah.routers.processes.httpx.AsyncClient', _FakeAsyncClient),
        patch('myah.routers.processes._inject_cron_output_to_chat', new_callable=AsyncMock) as mock_inject,
        patch('myah.socket.main.sio.emit', new_callable=AsyncMock) as mock_emit,
    ):
        resp = hosted_client.post(
            f'/api/v1/processes/{VALID_JOB_ID}/ui-action',
            json={'action_type': 'click', 'action': 'refresh', 'payload': {}, 'message_id': 'm1'},
        )

    assert resp.status_code == 200, resp.text
    assert resp.json().get('ok') is True
    # We made it past the write-failure branch into agent handling + delivery.
    mock_inject.assert_awaited()
    mock_emit.assert_awaited()


# ─────────────────────────────────────────────────────────────────────────────
# S6 — /webhook/run-started inbound webhook
# ─────────────────────────────────────────────────────────────────────────────


def test_run_started_webhook_rejects_missing_bearer(hosted_client: TestClient, monkeypatch):
    """No/invalid Authorization → 401, even though webhooks are OSS-exempt."""
    monkeypatch.setattr(processes_module, 'CRON_WEBHOOK_SECRET', 'fake-cron-secret')
    resp = hosted_client.post(
        '/api/v1/processes/webhook/run-started',
        json={'user_id': 'u', 'job_id': 'j', 'job_name': 'n'},
    )
    assert resp.status_code == 401


def test_run_started_webhook_requires_user_and_job_id(hosted_client: TestClient, monkeypatch):
    """Authenticated but missing user_id/job_id → 400."""
    monkeypatch.setattr(processes_module, 'CRON_WEBHOOK_SECRET', 'fake-cron-secret')
    resp = hosted_client.post(
        '/api/v1/processes/webhook/run-started',
        headers={'Authorization': 'Bearer fake-cron-secret'},
        json={'job_name': 'n'},  # no user_id, no job_id
    )
    assert resp.status_code == 400


def test_run_started_webhook_emits_socket_event(hosted_client: TestClient, monkeypatch):
    """A valid run-started webhook emits ``process:run-started`` to the user's
    room so the UI can show a live 'Running…' indicator."""
    monkeypatch.setattr(processes_module, 'CRON_WEBHOOK_SECRET', 'fake-cron-secret')
    with patch('myah.socket.main.sio.emit', new_callable=AsyncMock) as mock_emit:
        resp = hosted_client.post(
            '/api/v1/processes/webhook/run-started',
            headers={'Authorization': 'Bearer fake-cron-secret'},
            json={'user_id': 'user-9', 'job_id': VALID_JOB_ID, 'job_name': 'Daily Digest'},
        )

    assert resp.status_code == 200
    assert resp.json() == {'ok': True}
    mock_emit.assert_awaited_once()
    args, kwargs = mock_emit.call_args
    assert args[0] == 'process:run-started'
    assert args[1] == {'job_id': VALID_JOB_ID, 'job_name': 'Daily Digest'}
    assert kwargs.get('room') == 'user:user-9'


# ─────────────────────────────────────────────────────────────────────────────
# S7 — /{job_id}/respond human-in-the-loop path
#
# NOTE on plan mapping: the plan candidate "forwards valid user response to
# expected agent endpoint" does not match the real handler — ``/respond`` does
# NOT call an agent HTTP endpoint. It writes the answer JSON into the agent
# container's ``/data/.hermes/cron/pending/{job_id}.json`` via ``docker exec``.
# Hermes then prepends it to the next run. We protect the *actual* behaviour.
# ─────────────────────────────────────────────────────────────────────────────


def test_respond_rejects_missing_answer_field(hosted_client: TestClient):
    """``RespondForm.answer`` is required → FastAPI 422 on an empty body."""
    resp = hosted_client.post(f'/api/v1/processes/{VALID_JOB_ID}/respond', json={})
    assert resp.status_code == 422


def test_respond_rejects_invalid_job_id_format(hosted_client: TestClient):
    """A job_id that is not 12 hex chars → 400 (guards the docker-exec path)."""
    resp = hosted_client.post('/api/v1/processes/zzzzzzzzzzzz/respond', json={'answer': 'hi'})
    assert resp.status_code == 400


def test_respond_returns_404_when_no_container(hosted_client: TestClient):
    """Valid request but the user has no agent container → 404."""
    with patch('myah.models.containers.Containers.get_by_user_id', return_value=None):
        resp = hosted_client.post(
            f'/api/v1/processes/{VALID_JOB_ID}/respond',
            json={'answer': 'hi'},
        )
    assert resp.status_code == 404


def test_respond_writes_answer_into_container_pending_file(hosted_client: TestClient):
    """A valid answer is written into the per-user container via ``docker exec``;
    the embedded script targets the container and carries the answer + job_id."""
    captured = {}
    fake_container = MagicMock(container_name='myah-agent-user-9')

    class _OkProc:
        returncode = 0

        async def communicate(self, input=None):
            return (b'ok', b'')

    async def fake_exec(*args, **_kwargs):
        captured['args'] = args
        return _OkProc()

    with (
        patch('myah.models.containers.Containers.get_by_user_id', return_value=fake_container),
        patch('myah.routers.processes.asyncio.create_subprocess_exec', side_effect=fake_exec),
    ):
        resp = hosted_client.post(
            f'/api/v1/processes/{VALID_JOB_ID}/respond',
            json={'answer': 'ship it on friday'},
        )

    assert resp.status_code == 200
    assert resp.json() == {'ok': True}
    args = captured['args']
    # docker exec <container> python3 -c <script>
    assert args[:3] == ('docker', 'exec', 'myah-agent-user-9')
    script = args[-1]
    assert 'ship it on friday' in script
    assert VALID_JOB_ID in script


# ─────────────────────────────────────────────────────────────────────────────
# S10 — artifact / result retrieval boundary protection
#
# Full docker-exec success paths for /artifact + /runs are mapped to a named
# follow-up slice (see docs/testing/critical-path-coverage.md S10). Here we pin
# the cheap, network-free validation branches that guard those handlers.
# ─────────────────────────────────────────────────────────────────────────────


def test_get_process_artifact_rejects_invalid_job_id_format(hosted_client: TestClient):
    """``/artifact`` validates job_id shape before any container access → 400."""
    resp = hosted_client.get('/api/v1/processes/zzzzzzzzzzzz/artifact')
    assert resp.status_code == 400


def test_list_process_runs_returns_404_when_no_container(hosted_client: TestClient):
    """``/runs`` returns 404 when the user has no agent container."""
    with patch('myah.models.containers.Containers.get_by_user_id', return_value=None):
        resp = hosted_client.get(f'/api/v1/processes/{VALID_JOB_ID}/runs')
    assert resp.status_code == 404


def test_list_process_runs_rejects_invalid_job_id_format(hosted_client: TestClient):
    """With a container present, ``/runs`` still rejects a malformed job_id → 400
    (guards ``_fetch_run_outputs`` before it builds a docker-exec script)."""
    fake_container = MagicMock(container_name='myah-agent-user-9')
    with patch('myah.models.containers.Containers.get_by_user_id', return_value=fake_container):
        resp = hosted_client.get('/api/v1/processes/zzzzzzzzzzzz/runs')
    assert resp.status_code == 400
