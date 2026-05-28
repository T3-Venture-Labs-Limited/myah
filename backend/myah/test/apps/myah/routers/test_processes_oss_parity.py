"""Per Task 2.4: per-chat (PC + M-CO) endpoints in processes.py must
NOT 501 in OSS mode after the inline gate is removed.

Source of truth: docs/oss-launch/processes-py-gate-classification.md
"Per-chat endpoints (remove gate)" section — 8 PC + 1 M-CO = 9 routes.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from myah.models.users import UserModel
from myah.routers import processes as processes_module
from myah.utils.auth import get_verified_user


VALID_JOB_ID = 'abcdef012345'


# 8 PC + 1 M-CO routes whose gate is removable per Task 0.4 classification.
PC_ROUTES: list[tuple[str, str, dict | None]] = [
    ('GET', '/api/v1/processes/', None),                                              # M-CO line 278
    ('POST', '/api/v1/processes/', {'name': 'x', 'prompt': 'y', 'schedule': '* * * * *'}),  # PC 378
    ('GET', f'/api/v1/processes/{VALID_JOB_ID}', None),                               # PC 423
    ('PATCH', f'/api/v1/processes/{VALID_JOB_ID}', {'name': 'updated'}),              # PC 436
    ('DELETE', f'/api/v1/processes/{VALID_JOB_ID}', None),                            # PC 449
    ('POST', f'/api/v1/processes/{VALID_JOB_ID}/pause', None),                        # PC 460
    ('POST', f'/api/v1/processes/{VALID_JOB_ID}/resume', None),                       # PC 472
    ('POST', f'/api/v1/processes/{VALID_JOB_ID}/link-chat', {'chat_id': 'some-chat'}),  # PC 493
    ('POST', f'/api/v1/processes/{VALID_JOB_ID}/trigger', None),                      # PC 533
]


def _fake_user() -> UserModel:
    now = int(dt.datetime.now(dt.UTC).timestamp())
    return UserModel(
        id='test-user-oss',
        email='oss@test.local',
        name='OSS Test User',
        role='admin',
        last_active_at=now,
        updated_at=now,
        created_at=now,
    )


@pytest.fixture
def oss_app(monkeypatch):
    monkeypatch.setenv('MYAH_DEPLOYMENT_MODE', 'oss')
    app = FastAPI()
    app.include_router(processes_module.router, prefix='/api/v1/processes')
    app.dependency_overrides[get_verified_user] = _fake_user
    return app


@pytest.fixture
def oss_client(
    oss_app: FastAPI,
    test_client_factory: Callable[[FastAPI], TestClient],
) -> TestClient:
    return test_client_factory(oss_app)


def _call(client: TestClient, method: str, path: str, body: dict | None):
    if method == 'GET':
        return client.get(path)
    if method == 'DELETE':
        return client.delete(path)
    if method == 'PATCH':
        return client.patch(path, json=body if body is not None else {})
    if method == 'POST':
        return client.post(path, json=body if body is not None else {})
    raise AssertionError(f'unsupported method: {method}')


@pytest.mark.parametrize(('method', 'path', 'body'), PC_ROUTES)
def test_pc_route_returns_non_501_in_oss(
    oss_client: TestClient,
    method: str,
    path: str,
    body: dict | None,
) -> None:
    """Per-chat routes must reach the proxy layer in OSS, not 501 at the gate.

    The route may still return 503 (no real host gateway), 404 (chat
    ownership check), or 200 (mocked) — the contract is simply 'not 501'.
    """
    # Stub the Hermes proxy + container lookup so the routes don't try
    # to talk to a real backend.
    fake_container = type('FakeContainer', (), {
        'container_name': None,  # OSS stub
        'vite_port': None,
        'host_port': 8642,
        'status': 'running',
        'id': 'oss-stub',
    })()

    with patch.object(processes_module, '_hermes_post', return_value={'ok': True, 'job': {}}), \
         patch.object(processes_module, '_hermes_get', return_value={'jobs': [], 'id': 'job-id-1'}), \
         patch.object(processes_module, '_hermes_patch', return_value={'ok': True, 'job': {}}), \
         patch.object(processes_module, '_hermes_delete', return_value={'ok': True}), \
         patch.object(processes_module, '_ensure_container', return_value=8642), \
         patch('myah.models.containers.Containers.get_by_user_id', return_value=fake_container):
        # link-chat path validates chat ownership in the DB; stub that too.
        with patch('myah.models.chats.Chats.get_chat_by_id_and_user_id',
                   return_value=type('FakeChat', (), {'title': 'test-chat'})()):
            resp = _call(oss_client, method, path, body)

    assert resp.status_code != 501, (
        f'{method} {path} returned 501 in OSS — per-chat gate should be removed. '
        f'body={resp.text}'
    )
