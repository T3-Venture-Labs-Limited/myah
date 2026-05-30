"""Replaces test_processes_oss_mode.py per spec §6.3 + plan Task 2.4 Step 5.

Parametrizes the PC + CO route lists from the Task 0.4 classification:
  - PC (8) + M-CO (1) = non-501 in OSS (gate removed in Task 2.4)
  - CO (7) = still 501 in OSS (gate kept; container_name=None on the OSS stub)
  - Webhook routes are exempt (DB-only; carve-out preserved in
    `_raise_if_oss_mode_unless_webhook` body for future re-use).

Authoritative source: docs/oss-launch/processes-py-gate-classification.md
"""

from __future__ import annotations

import datetime as dt
from unittest.mock import patch
from urllib.parse import urlparse

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from myah.models.users import UserModel
from myah.routers import processes as processes_module
from myah.utils.auth import get_verified_user

VALID_JOB_ID = 'abcdef012345'


# ── Per-chat routes (gate REMOVED — must NOT 501 in OSS) ────────────
PC_ROUTES: list[tuple[str, str, dict | None]] = [
    ('GET', '/api/v1/processes/', None),                                                  # M-CO line 278
    ('POST', '/api/v1/processes/', {'name': 'x', 'prompt': 'y', 'schedule': '* * * * *'}),  # PC 378
    ('GET', f'/api/v1/processes/{VALID_JOB_ID}', None),                                   # PC 423
    ('PATCH', f'/api/v1/processes/{VALID_JOB_ID}', {'name': 'updated'}),                  # PC 436
    ('DELETE', f'/api/v1/processes/{VALID_JOB_ID}', None),                                # PC 449
    ('POST', f'/api/v1/processes/{VALID_JOB_ID}/pause', None),                            # PC 460
    ('POST', f'/api/v1/processes/{VALID_JOB_ID}/resume', None),                           # PC 472
    ('POST', f'/api/v1/processes/{VALID_JOB_ID}/link-chat', {'chat_id': 'some-chat'}),    # PC 493
    ('POST', f'/api/v1/processes/{VALID_JOB_ID}/trigger', None),                          # PC 533
]


# ── Container-only routes (gate KEPT — still 501 in OSS) ────────────
CO_ROUTES: list[tuple[str, str, dict | None]] = [
    ('GET', f'/api/v1/processes/{VALID_JOB_ID}/runs', None),                                       # CO 634
    ('GET', f'/api/v1/processes/{VALID_JOB_ID}/artifact', None),                                   # CO 647
    ('GET', f'/api/v1/processes/{VALID_JOB_ID}/vite-port', None),                                  # CO 694
    ('POST', f'/api/v1/processes/{VALID_JOB_ID}/init-artifact', None),                             # CO 711
    ('POST', f'/api/v1/processes/{VALID_JOB_ID}/respond', {'answer': 'hello'}),                    # CO 738
    ('POST', f'/api/v1/processes/{VALID_JOB_ID}/ui-action',
     {'action_type': 'submit', 'action': 'go', 'payload': {}}),                                    # CO 792
    ('POST', f'/api/v1/processes/{VALID_JOB_ID}/sync-chat', None),                                 # CO 1394
    # Adoption reads run-output files from the per-user agent container
    # (backfill), so it is container-only and 501s in OSS like /sync-chat.
    # OSS adoption against a host Hermes is a deliberate follow-up.
    ('POST', f'/api/v1/processes/{VALID_JOB_ID}/adopt', {'backfill_limit': 0}),                    # CO adopt
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
def oss_client(oss_app) -> TestClient:
    return TestClient(oss_app)


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


# ── PC: must NOT 501 ────────────────────────────────────────────────


@pytest.mark.parametrize(('method', 'path', 'body'), PC_ROUTES)
def test_pc_route_returns_non_501_in_oss(
    oss_client: TestClient,
    method: str,
    path: str,
    body: dict | None,
) -> None:
    """Per-chat routes must reach the proxy layer in OSS, not 501 at the gate.

    With the inline gate removed (Task 2.4), the route should either
    succeed via the mocked proxy or surface a non-501 status (e.g. 404
    from chat ownership). What it must NOT do is return 501 — that's
    the contract the frontend matches on to render the upsell card,
    and these routes are no longer upsell-gated.
    """
    fake_container = type('FakeContainer', (), {
        'container_name': None,  # OSS stub shape
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
         patch('myah.models.containers.Containers.get_by_user_id', return_value=fake_container), \
         patch('myah.models.chats.Chats.get_chat_by_id_and_user_id',
               return_value=type('FakeChat', (), {'title': 'test-chat'})()):
        resp = _call(oss_client, method, path, body)

    assert resp.status_code != 501, (
        f'{method} {path} returned 501 in OSS — PC gate should be removed. '
        f'body={resp.text}'
    )


def test_list_processes_does_not_pass_include_disabled_query(
    oss_client: TestClient,
) -> None:
    """Hermes api_server has a binding bug when include_disabled is passed.

    The list route is now reachable in OSS, so keep this regression pinned:
    call GET /api/jobs with no include_disabled query string.
    """
    seen_urls: list[str] = []
    fake_container = type('FakeContainer', (), {
        'container_name': None,
        'vite_port': None,
        'host_port': 8642,
        'status': 'running',
        'id': 'oss-stub',
    })()

    async def fake_get(url: str):
        seen_urls.append(url)
        return {'jobs': []}

    with patch.object(processes_module, '_hermes_get', side_effect=fake_get), \
         patch.object(processes_module, '_ensure_container', return_value=8642), \
         patch('myah.models.containers.Containers.get_by_user_id', return_value=fake_container):
        resp = oss_client.get('/api/v1/processes/')

    assert resp.status_code == 200, resp.text
    assert len(seen_urls) == 1
    parsed = urlparse(seen_urls[0])
    assert parsed.path == '/api/jobs'
    assert parsed.query == ''


# ── CO: must STILL 501 ───────────────────────────────────────────────


@pytest.mark.parametrize(('method', 'path', 'body'), CO_ROUTES)
def test_co_route_still_returns_501_in_oss(
    oss_client: TestClient,
    method: str,
    path: str,
    body: dict | None,
) -> None:
    """Container-only routes (read container.container_name or run
    docker exec) keep the inline 501 gate so OSS users get the upsell
    card, not an opaque 404 from missing container_name."""
    resp = _call(oss_client, method, path, body)
    assert resp.status_code == 501, (
        f'{method} {path} should still 501 in OSS, got {resp.status_code} {resp.text}'
    )
    detail = (resp.json() or {}).get('detail', '')
    # Upsell-string sanity (frontend matches on a stable substring).
    assert 'app.myah.dev' in str(detail).lower() or 'hosted' in str(detail).lower(), detail


# ── Upsell-string stability across all CO routes ────────────────────


def test_co_upsell_detail_is_stable_across_endpoints(oss_client: TestClient) -> None:
    """All CO 501s share the same detail string so the frontend can
    match once instead of per-endpoint."""
    details = set()
    for method, path, body in CO_ROUTES:
        resp = _call(oss_client, method, path, body)
        assert resp.status_code == 501, f'{method} {path} -> {resp.status_code}'
        details.add((resp.json() or {}).get('detail', ''))
    assert len(details) == 1, f'CO detail strings drifted: {details!r}'


# ── Webhook carve-out: still reachable in OSS ───────────────────────


def test_webhook_endpoint_not_gated_in_oss(oss_client: TestClient, monkeypatch) -> None:
    """Webhook carve-out at processes.py:954 must remain functional in OSS.

    The webhook requires Bearer auth (MYAH_AGENT_BEARER_TOKEN); without
    it the route returns 401. The key thing is it must NOT return 501 —
    the OSS gate must not fire on webhook paths. We send a bogus
    Authorization so the auth check is exercised but unrelated to the
    OSS-gate question.
    """
    monkeypatch.setenv('MYAH_AGENT_BEARER_TOKEN', 'shared-secret')
    # Re-instantiate the module-level constant via patch so the route picks it up.
    monkeypatch.setattr(processes_module, 'CRON_WEBHOOK_SECRET', 'shared-secret')

    resp = oss_client.post(
        '/api/v1/processes/webhook/run-complete',
        headers={'Authorization': 'Bearer shared-secret'},
        json={'user_id': 'u', 'job_id': 'j', 'job_name': 'jn', 'response': '', 'status': 'ok', 'ran_at': ''},
    )
    # The handler may 400/500/etc depending on what the DB does with
    # the fake payload — what it must not do is 501 (the OSS gate
    # carve-out is the contract under test).
    assert resp.status_code != 501, f'webhook 501ed in OSS: {resp.text}'


# ── Coverage gate: every non-webhook route is classified ─────────────


def _template_path(concrete_path: str) -> str:
    return concrete_path.replace(f'/{VALID_JOB_ID}', '/{job_id}')


def test_classification_covers_every_non_webhook_route() -> None:
    """If a new route lands in processes.py, PC_ROUTES or CO_ROUTES
    must list it. Walks the router's actual routes (FastAPI runtime
    source of truth) and asserts every non-webhook route is exercised.
    """
    expected: set[tuple[str, str]] = set()
    for route in processes_module.router.routes:
        path = getattr(route, 'path', None)
        methods = getattr(route, 'methods', None)
        if not path or not methods:
            continue
        if path.startswith('/webhook/'):
            continue
        for method in methods - {'HEAD', 'OPTIONS'}:
            expected.add((method, f'/api/v1/processes{path}'))

    covered = {(m, _template_path(p)) for m, p, _ in PC_ROUTES + CO_ROUTES}
    missing = expected - covered
    extra = covered - expected
    assert not missing, (
        f'Routes in processes.py router not classified in PC_ROUTES + CO_ROUTES: '
        f'{missing}. Add them to the relevant list with a representative body.'
    )
    if extra:
        print(f'note: classification has entries no longer on the router: {extra}')
