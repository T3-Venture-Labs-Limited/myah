"""
Tests for the OSS auth bootstrap endpoint (POST /api/v1/auths/oss-signin).

Fresh OSS installs cannot authenticate without this endpoint: Phase 1B
removed the signin/signup surface so the seed admin user
(id=00000000-0000-0000-0000-000000000001) had no way to obtain a JWT.
See docs/gotchas/2026-05-17-oss-auth-bootstrap-missing.md.

Test fixture pattern mirrors test_oss_probe.py: mount only the auths
router into a fresh FastAPI app, override get_session to point at an
in-memory SQLite engine so each test starts with a clean DB. This avoids
importing myah.main (which pulls in the full router graph, OAuth
manager, etc.).

WEBUI_AUTH toggling: ``monkeypatch.setattr(env, 'WEBUI_AUTH', ...)``
mirrors the in-process pattern used by test_env_back_compat.py — the
auths router reads ``_myah_env.WEBUI_AUTH`` at request time so the
monkeypatch takes effect without a module reload.
"""

from __future__ import annotations

import time
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from myah import env as _myah_env
from myah.internal.db import get_session
from myah.models.users import User
from myah.routers import auths as auths_router_module


_SEED_USER_ID = '00000000-0000-0000-0000-000000000001'


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def in_memory_engine():
    """Fresh in-memory SQLite per test, with the real ``user`` table."""
    engine = create_engine(
        'sqlite://',
        connect_args={'check_same_thread': False},
        poolclass=StaticPool,
    )
    # Only the user table is needed for these tests; create just it
    # rather than the full Base.metadata (which would pull in dozens of
    # tables and slow the suite).
    User.__table__.create(bind=engine)
    yield engine
    engine.dispose()


@pytest.fixture
def session_factory(in_memory_engine):
    return sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=in_memory_engine,
        expire_on_commit=False,
    )


@pytest.fixture
def app(session_factory, monkeypatch):
    """Lightweight FastAPI app with only the auths router mounted.

    The ``get_session`` dependency is overridden to issue sessions
    against the per-test in-memory SQLite engine. Two adapters are
    needed to keep the surface small:

    1. ``DATABASE_ENABLE_SESSION_SHARING=True`` so that ``Users``
       helpers (``get_user_by_id``, ``get_super_admin_user``) honour the
       passed-in session rather than opening a new prod ``SessionLocal``.
    2. ``get_permissions`` patched to return ``{}`` — the real impl
       queries the ``group``/``group_member`` tables which aren't
       created in this minimal harness.
    """
    from myah.internal import db as _db_module

    monkeypatch.setattr(_db_module, 'DATABASE_ENABLE_SESSION_SHARING', True)
    monkeypatch.setattr(
        auths_router_module, 'get_permissions', lambda *a, **kw: {}
    )

    def _override_get_session():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app = FastAPI()
    app.include_router(auths_router_module.router, prefix='/api/v1/auths')

    # create_session_response reads request.app.state.config for JWT
    # config + user permissions; minimal stub is enough.
    app.state.config = SimpleNamespace(
        JWT_EXPIRES_IN='4w',
        USER_PERMISSIONS={},
    )
    # get_current_user checks request.app.state.redis for token denylist
    # lookups when the JWT carries a jti claim. Round-trip auth test path
    # exercises this; absence on State would AttributeError.
    app.state.redis = None

    app.dependency_overrides[get_session] = _override_get_session
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def auth_disabled(monkeypatch):
    """Set WEBUI_AUTH=False at request time (the router reads it lazily)."""
    monkeypatch.setattr(_myah_env, 'WEBUI_AUTH', False)
    monkeypatch.setattr(_myah_env, 'MYAH_AUTH', False)


@pytest.fixture
def auth_enabled(monkeypatch):
    monkeypatch.setattr(_myah_env, 'WEBUI_AUTH', True)
    monkeypatch.setattr(_myah_env, 'MYAH_AUTH', True)


def _insert_user(
    session_factory,
    *,
    user_id: str,
    email: str = 'user@localhost',
    name: str = 'Myah',
    role: str = 'admin',
) -> None:
    """Insert a user row directly via the real User model."""
    db = session_factory()
    try:
        now = int(time.time())
        db.add(
            User(
                id=user_id,
                name=name,
                email=email,
                role=role,
                profile_image_url='/user.png',
                last_active_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        db.commit()
    finally:
        db.close()


# ── Happy path: OSS-mode signin issues a valid JWT ────────────────────


def test_oss_signin_returns_token_when_auth_disabled(
    client, session_factory, auth_disabled
):
    """In OSS mode, oss-signin returns 200 with a token for the seed user."""
    _insert_user(session_factory, user_id=_SEED_USER_ID)

    r = client.post('/api/v1/auths/oss-signin')

    assert r.status_code == 200, f'Expected 200, got {r.status_code}: {r.text}'
    body = r.json()
    assert body['token'], 'oss-signin must return a non-empty token'
    assert body['token_type'] == 'Bearer', body
    assert body['id'] == _SEED_USER_ID, body
    assert body['email'] == 'user@localhost', body
    assert body['role'] == 'admin', body


# ── 404 in hosted mode ────────────────────────────────────────────────


def test_oss_signin_404s_when_auth_enabled(
    client, session_factory, auth_enabled
):
    """Hosted mode: the endpoint surface does not exist (404)."""
    # Even if the seed user is present, the endpoint must not issue a token.
    _insert_user(session_factory, user_id=_SEED_USER_ID)

    r = client.post('/api/v1/auths/oss-signin')

    assert r.status_code == 404, f'Expected 404, got {r.status_code}: {r.text}'
    assert 'hosted mode' in r.json()['detail'].lower()


# ── 500 when no admin user exists at all ──────────────────────────────


def test_oss_signin_500s_when_no_admin_user(client, auth_disabled):
    """Empty user table: clear remediation guidance in the error."""
    r = client.post('/api/v1/auths/oss-signin')

    assert r.status_code == 500, f'Expected 500, got {r.status_code}: {r.text}'
    detail = r.json()['detail'].lower()
    assert 'run alembic migrations' in detail or 're-seed' in detail, (
        f'Expected remediation guidance in error, got: {detail!r}'
    )


# ── Fallback: first admin user when seed row was deleted ──────────────


def test_oss_signin_falls_back_to_first_admin_when_seed_missing(
    client, session_factory, auth_disabled
):
    """Seed user deleted but another admin exists -> sign that admin in."""
    fallback_id = str(uuid.uuid4())
    _insert_user(
        session_factory,
        user_id=fallback_id,
        email='fallback-admin@localhost',
        role='admin',
    )

    r = client.post('/api/v1/auths/oss-signin')

    assert r.status_code == 200, f'Expected 200, got {r.status_code}: {r.text}'
    body = r.json()
    assert body['id'] == fallback_id, body
    assert body['email'] == 'fallback-admin@localhost', body
    assert body['role'] == 'admin', body


# ── Round-trip: token issued by oss-signin authenticates other endpoints ──


def test_oss_signin_token_authenticates_get_auths(
    client, session_factory, auth_disabled
):
    """The JWT issued by oss-signin must authenticate GET /api/v1/auths/.

    This is the exact contract the frontend depends on: POST oss-signin
    once on first load, then use the returned token for every subsequent
    request including the layout's getSessionUser call.
    """
    _insert_user(session_factory, user_id=_SEED_USER_ID)

    # Step 1: bootstrap signin.
    r1 = client.post('/api/v1/auths/oss-signin')
    assert r1.status_code == 200, r1.text
    token = r1.json()['token']
    assert token

    # Step 2: use the token to fetch the session-user payload.
    # ``get_current_user`` (utils/auth.py) calls
    # ``Users.get_user_by_id(data['id'])`` WITHOUT passing a db, so it
    # would otherwise hit the real prod ``SessionLocal``. Patch the
    # lookup to read from the test's in-memory session so the round-trip
    # actually exercises the JWT path, not the DB layer.
    from myah.utils import auth as auth_utils

    def _resolve_via_test_db(id_, db=None):
        s = session_factory()
        try:
            row = s.query(User).filter_by(id=id_).first()
            if row is None:
                return None
            from myah.models.users import UserModel

            return UserModel.model_validate(row)
        finally:
            s.close()

    with patch.object(
        auth_utils.Users, 'get_user_by_id', side_effect=_resolve_via_test_db
    ):
        r2 = client.get(
            '/api/v1/auths/',
            headers={'Authorization': f'Bearer {token}'},
        )

    assert r2.status_code == 200, (
        f'GET /api/v1/auths/ with the bootstrap token must succeed; '
        f'got {r2.status_code}: {r2.text}'
    )
    body = r2.json()
    assert body['id'] == _SEED_USER_ID, body
    assert body['token'] == token, (
        'GET /api/v1/auths/ echoes the bearer token in the response'
    )
