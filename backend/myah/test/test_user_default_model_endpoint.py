"""Tests for POST/GET /api/v1/users/user/default-model.

Verifies the endpoint accepts the (model_id, provider_id) pair, rejects
half-pair input, and returns the new default_provider field on read.

Strategy: mount only the users router into a fresh FastAPI app + stub
`Users.update_user_by_id` / `Users.get_user_by_id` directly. The endpoint
doesn't take a `db: Session = Depends(...)` (it goes straight to the
classmethod), so overriding the session dependency wouldn't reach the
data layer. Stubbing the classmethods at the boundary is the focused
test for the endpoint's form-validation + response-shape behavior.
"""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from myah.routers import users as users_router_module


_TEST_USER_ID = 'u-test-1'


class _UserStore:
    """In-memory user store that mimics the Users classmethod surface
    just enough for the endpoint's two callsites."""

    def __init__(self, user_id: str):
        self.user_id = user_id
        self.default_model = None
        self.default_provider = None

    def get_user_by_id(self, uid: str):
        if uid != self.user_id:
            return None
        return SimpleNamespace(
            id=uid,
            default_model=self.default_model,
            default_provider=self.default_provider,
        )

    def update_user_by_id(self, uid: str, patch_dict: dict):
        if uid != self.user_id:
            return None
        if 'default_model' in patch_dict:
            self.default_model = patch_dict['default_model']
        if 'default_provider' in patch_dict:
            self.default_provider = patch_dict['default_provider']
        return self.get_user_by_id(uid)


@pytest.fixture
def store():
    return _UserStore(_TEST_USER_ID)


@pytest.fixture
def app(store):
    """FastAPI app with the users router + Users methods stubbed."""
    application = FastAPI()
    application.include_router(users_router_module.router, prefix='/api/v1/users')

    # Patch the Users classmethods the endpoint hits.
    patches = [
        patch.object(users_router_module.Users, 'get_user_by_id', store.get_user_by_id),
        patch.object(users_router_module.Users, 'update_user_by_id', store.update_user_by_id),
    ]
    for p in patches:
        p.start()
    yield application
    for p in patches:
        p.stop()


@contextmanager
def _mock_verified_user(app, user_id):
    from myah.utils.auth import get_verified_user

    class _U:
        id = user_id
        role = 'admin'

    app.dependency_overrides[get_verified_user] = lambda: _U()
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_verified_user, None)


@pytest.fixture
def client(app):
    return TestClient(app)


def test_set_user_default_model_accepts_pair(app, client):
    """POST /user/default-model with both model_id and provider_id.

    Mirrors Hermes upstream's canonical {provider, model} shape — see
    `docs/superpowers/specs/2026-05-24-default-model-canonical-format-design.md`.
    """
    with _mock_verified_user(app, _TEST_USER_ID):
        r = client.post(
            '/api/v1/users/user/default-model',
            json={'model_id': 'gpt-4o-mini', 'provider_id': 'openai'},
        )
    assert r.status_code == 200, r.text
    assert r.json() == {'default_model': 'gpt-4o-mini', 'default_provider': 'openai'}


def test_set_user_default_model_clears_with_both_null(app, client):
    with _mock_verified_user(app, _TEST_USER_ID):
        r = client.post(
            '/api/v1/users/user/default-model',
            json={'model_id': None, 'provider_id': None},
        )
    assert r.status_code == 200, r.text
    assert r.json() == {'default_model': None, 'default_provider': None}


def test_set_user_default_model_rejects_one_without_other(app, client):
    """422 on half-pair input — endpoint enforces both-or-neither in addition
    to the Pydantic UserModel validator (added in Task 6)."""
    with _mock_verified_user(app, _TEST_USER_ID):
        r = client.post(
            '/api/v1/users/user/default-model',
            json={'model_id': 'gpt-4o-mini', 'provider_id': None},
        )
    assert r.status_code == 422, r.text


def test_get_user_default_model_returns_pair(app, client):
    """GET /user/default-model returns both fields."""
    with _mock_verified_user(app, _TEST_USER_ID):
        client.post(
            '/api/v1/users/user/default-model',
            json={'model_id': 'claude-opus-4.7', 'provider_id': 'anthropic'},
        )
        r = client.get('/api/v1/users/user/default-model')
    assert r.status_code == 200, r.text
    assert r.json() == {'default_model': 'claude-opus-4.7', 'default_provider': 'anthropic'}
