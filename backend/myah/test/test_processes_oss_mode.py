"""
Tests that ``processes.py`` route handlers reject every request with
HTTP 501 in OSS mode (``MYAH_DEPLOYMENT_MODE=oss``).

Background — Q-oss-cron-processes-ui (spec §3, locked decision):
the cron-history / processes-artifact UI is a hosted-only feature. The
OSS variant short-circuits every endpoint to 501 with an upsell message
so the frontend renders an upsell card instead of a half-broken UI.

Before this fix, each endpoint would crash at runtime in OSS mode —
either with ``FileNotFoundError: 'docker'`` (when the Docker CLI isn't
installed), ``HTTPException(404, 'No container found')`` (synthetic
container row has no ``container_name``), or ``HTTPException(503,
'Agent container unreachable')`` from the hermes-HTTP call path failing
because the routes assume a per-user container port the OSS variant
doesn't have. The user-facing symptom was inconsistent
500/503/404 responses depending on which call path crashed first;
501 makes the gating consistent and machine-detectable for the
frontend's upsell-rendering logic.

Coverage policy: **every** ``@router`` route in ``processes.py``
except the inbound webhooks (``/webhook/run-complete``,
``/webhook/run-started``, which are DB-only and don't depend on the
per-user-container architecture). Adding a new route to processes.py
without an ``is_oss_mode()`` guard must be caught by the stability
test below.

Reference: spec §3 Q-oss-cron-processes-ui, plan Task D.4.
"""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from myah.models.users import UserModel
from myah.routers import processes as processes_module
from myah.utils.auth import get_verified_user


def _fake_user() -> UserModel:
    """Build a stand-in UserModel for tests (auth is overridden)."""
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
    """A minimal FastAPI app that mounts only the processes router and
    overrides the auth dependency. ``MYAH_DEPLOYMENT_MODE=oss`` ensures
    the ``is_oss_mode()`` helper inside processes.py short-circuits."""
    monkeypatch.setenv('MYAH_DEPLOYMENT_MODE', 'oss')

    app = FastAPI()
    app.include_router(processes_module.router, prefix='/api/v1/processes')
    app.dependency_overrides[get_verified_user] = _fake_user
    return app


@pytest.fixture
def oss_client(oss_app) -> TestClient:
    return TestClient(oss_app)


# Twelve-hex job id format used by some routes (re.match r'^[a-f0-9]{12}$').
# Tests use a valid-shaped id so the 501 gate fires before any
# path-validation 400.
VALID_JOB_ID = 'abcdef012345'


# All ``@router`` routes in processes.py that must 501 in OSS mode.
# Webhook routes are intentionally excluded — see module docstring +
# the OSS-mode gate comment block in processes.py.
GATED_ROUTES: list[tuple[str, str, dict | None]] = [
    # Core CRUD
    ('GET', '/api/v1/processes/', None),
    ('POST', '/api/v1/processes/', {'name': 'x', 'prompt': 'y', 'schedule': '* * * * *'}),
    ('GET', f'/api/v1/processes/{VALID_JOB_ID}', None),
    ('PATCH', f'/api/v1/processes/{VALID_JOB_ID}', {'name': 'updated'}),
    ('DELETE', f'/api/v1/processes/{VALID_JOB_ID}', None),
    # Lifecycle
    ('POST', f'/api/v1/processes/{VALID_JOB_ID}/pause', None),
    ('POST', f'/api/v1/processes/{VALID_JOB_ID}/resume', None),
    ('POST', f'/api/v1/processes/{VALID_JOB_ID}/trigger', None),
    ('POST', f'/api/v1/processes/{VALID_JOB_ID}/link-chat', {'chat_id': 'some-chat'}),
    # Per-process runs + artifact UI
    ('GET', f'/api/v1/processes/{VALID_JOB_ID}/runs', None),
    ('GET', f'/api/v1/processes/{VALID_JOB_ID}/artifact', None),
    ('GET', f'/api/v1/processes/{VALID_JOB_ID}/vite-port', None),
    ('POST', f'/api/v1/processes/{VALID_JOB_ID}/init-artifact', None),
    # Human-in-the-loop
    ('POST', f'/api/v1/processes/{VALID_JOB_ID}/respond', {'answer': 'hello'}),
    ('POST', f'/api/v1/processes/{VALID_JOB_ID}/ui-action', {'action_type': 'submit', 'action': 'go', 'payload': {}}),
    # Chat backfill
    ('POST', f'/api/v1/processes/{VALID_JOB_ID}/sync-chat', None),
]


def _call(client: TestClient, method: str, path: str, body: dict | None):
    """Invoke a route with the right verb. POST/PATCH use json=body."""
    if method == 'GET':
        return client.get(path)
    if method == 'DELETE':
        return client.delete(path)
    if method == 'PATCH':
        return client.patch(path, json=body if body is not None else {})
    if method == 'POST':
        return client.post(path, json=body if body is not None else {})
    raise AssertionError(f'unsupported method: {method}')


# ── Every gated route returns 501 ────────────────────────────────────


@pytest.mark.parametrize(('method', 'path', 'body'), GATED_ROUTES)
def test_route_returns_501_in_oss(
    oss_client: TestClient,
    method: str,
    path: str,
    body: dict | None,
) -> None:
    """Every non-webhook route in processes.py must return 501 in OSS mode.

    This is the contract: the frontend matches on 501 + the stable
    detail string to render the upsell card. If a new route is added to
    processes.py without an ``is_oss_mode()`` guard, this parametrized
    case fails for that route.
    """
    r = _call(oss_client, method, path, body)
    assert r.status_code == 501, f'{method} {path} -> {r.status_code} {r.text}'


# ── Upsell-message contract ──────────────────────────────────────────


def test_upsell_detail_mentions_hosted_url(oss_client: TestClient) -> None:
    """Every OSS 501 response carries the same upsell message so the
    frontend's upsell-renderer has a single contract to match."""
    r = oss_client.get('/api/v1/processes/')
    detail = (r.json() or {}).get('detail', '')
    assert 'app.myah.dev' in detail.lower(), detail
    assert 'hermes cron' in detail.lower() or 'host' in detail.lower(), detail


def test_upsell_detail_is_stable_across_endpoints(oss_client: TestClient) -> None:
    """All 501s share the same detail string so the frontend can match
    once instead of per-endpoint. Covers ALL gated routes — adding a
    new route to the router without the standard 501 gate makes the
    detail set non-singleton and fails this test."""
    details = set()
    for method, path, body in GATED_ROUTES:
        r = _call(oss_client, method, path, body)
        assert r.status_code == 501, f'{method} {path} -> {r.status_code} {r.text}'
        details.add(r.json().get('detail', ''))
    assert len(details) == 1, f'detail strings drifted: {details!r}'


# ── Router coverage: every UI route is in GATED_ROUTES ───────────────


def _template_path(concrete_path: str) -> str:
    """Convert a concrete path back to its router template form.

    GATED_ROUTES uses the expanded ``VALID_JOB_ID`` for the {job_id}
    parameter; the FastAPI router stores routes with ``{job_id}`` as
    a literal. Map between them so the coverage assertion compares
    apples to apples.
    """
    return concrete_path.replace(f'/{VALID_JOB_ID}', '/{job_id}')


def test_gated_routes_covers_every_non_webhook_route() -> None:
    """If a new route lands in processes.py, GATED_ROUTES must list it.

    Walks the router's actual routes (the FastAPI runtime source of
    truth, not a hard-coded list) and asserts every non-webhook route
    is exercised above. Adding a new route to the router without
    adding it to GATED_ROUTES makes this test fail loudly, which in
    turn keeps the OSS 501 contract from regressing silently.
    """
    expected: set[tuple[str, str]] = set()
    for route in processes_module.router.routes:
        # ``route.path`` is the relative path the router was registered
        # with (no /api/v1/processes prefix). ``route.methods`` is the
        # set of HTTP verbs (excluding HEAD).
        path = getattr(route, 'path', None)
        methods = getattr(route, 'methods', None)
        if not path or not methods:
            continue
        if path.startswith('/webhook/'):
            continue  # intentionally ungated — see module docstring
        for method in methods - {'HEAD', 'OPTIONS'}:
            expected.add((method, f'/api/v1/processes{path}'))

    # Normalise the concrete paths in GATED_ROUTES back to their
    # router-template form for the comparison.
    covered = {(m, _template_path(p)) for m, p, _ in GATED_ROUTES}
    missing = expected - covered
    extra = covered - expected
    assert not missing, (
        f'Routes in processes.py router not covered by GATED_ROUTES: {missing}. '
        'Add them to GATED_ROUTES with a representative request body.'
    )
    # ``extra`` is allowed (GATED_ROUTES may pre-empt a route a future
    # PR removes), but worth surfacing in test logs:
    if extra:
        print(f'note: GATED_ROUTES has entries no longer on the router: {extra}')


# ── Auth-before-OSS-gate regression (Phase D finding D3) ────────────
#
# The fixtures above override ``get_verified_user`` via
# ``app.dependency_overrides``, so they never exercise the real
# auth chain. In the real runtime, ``Depends(get_verified_user)`` is
# the per-route auth dep and runs BEFORE the function body's
# ``_raise_if_oss_mode()`` — so without a router-level OSS gate, an
# OSS user with no token gets 401 instead of 501. That breaks the
# contract the smoke test in scripts/smoke-test-oss.sh expects.
#
# This block exercises the FULL HTTP request → auth → handler path
# with NO auth override, asserting 501 is returned by the
# router-level dep before any per-route auth dep can raise 401.


def _build_oss_app_without_auth_override() -> FastAPI:
    """Mount the processes router with NO dependency overrides.

    Mirrors what ``myah.main`` does in production: include the
    router, let its real per-route ``Depends(get_verified_user)`` run.
    The router-level OSS gate must short-circuit with 501 before
    auth gets a chance to raise 401.
    """
    app = FastAPI()
    app.include_router(processes_module.router, prefix='/api/v1/processes')
    return app


def test_processes_returns_501_without_auth_in_oss_mode(monkeypatch) -> None:
    """OSS users see the upsell card, not a 401 login wall.

    Reproduces the Phase D smoke-test failure verbatim:
        curl -o /dev/null -w "%{http_code}\\n" http://127.0.0.1:8080/api/v1/processes/
    Pre-fix: 401 (auth dep ran before OSS check).
    Post-fix: 501 with the upsell-card detail.
    """
    monkeypatch.setenv('MYAH_DEPLOYMENT_MODE', 'oss')
    client = TestClient(_build_oss_app_without_auth_override())

    res = client.get('/api/v1/processes/')

    assert res.status_code == 501, f'expected 501 OSS-upsell, got {res.status_code}: {res.text}'
    detail = res.json().get('detail', '')
    assert 'app.myah.dev' in detail, detail


@pytest.mark.parametrize(('method', 'path', 'body'), GATED_ROUTES)
def test_every_gated_route_returns_501_without_auth_in_oss_mode(
    monkeypatch,
    method: str,
    path: str,
    body: dict | None,
) -> None:
    """The router-level gate must beat the per-route auth dep on EVERY
    gated route — not just ``GET /``.

    Without the router-level dependency, any route with a
    ``Depends(get_verified_user)`` parameter raises 401 before the
    function body's ``_raise_if_oss_mode()`` runs. This test exercises
    the same routes as ``test_route_returns_501_in_oss`` but with NO
    auth dependency override, so it catches the auth-before-OSS-gate
    ordering bug for every route, not just the index.
    """
    monkeypatch.setenv('MYAH_DEPLOYMENT_MODE', 'oss')
    client = TestClient(_build_oss_app_without_auth_override())

    res = _call(client, method, path, body)
    assert res.status_code == 501, (
        f'{method} {path} -> {res.status_code} {res.text} '
        '(expected 501; if 401, the OSS gate is running AFTER the auth dep)'
    )


# ── Hosted-mode is unaffected ────────────────────────────────────────


def test_hosted_mode_does_not_return_501(monkeypatch) -> None:
    """When ``MYAH_DEPLOYMENT_MODE`` is unset (hosted default), the
    OSS gate does NOT fire — the original code path runs and returns
    whatever status it would normally (200/404/503 depending on the
    underlying state; the key thing is it's NOT 501).

    This regression-guards the gate so adding a stray ``is_oss_mode``
    check at file-scope wouldn't accidentally flip hosted to 501 too.
    """
    monkeypatch.delenv('MYAH_DEPLOYMENT_MODE', raising=False)

    app = FastAPI()
    app.include_router(processes_module.router, prefix='/api/v1/processes')
    app.dependency_overrides[get_verified_user] = _fake_user
    client = TestClient(app)

    # GET / will hit the real hosted path. Container lookup will likely
    # fail (no DB row + no hermes container) so the response is some
    # error — just NOT 501.
    r = client.get('/api/v1/processes/')
    assert r.status_code != 501, (
        f'hosted mode should not return 501; got {r.status_code} {r.text}'
    )
