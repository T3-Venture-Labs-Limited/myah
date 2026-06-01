"""Tests for the /api/v1/myah/* router used by the myah-hermes-plugin.

Today the only endpoint is ``GET /whoami``, used by the plugin's
register(ctx) in OSS mode to discover its own MYAH_USER_ID without
forcing the user to paste it by hand into ``~/.hermes/.env``.

Single-tenant assumption: the FIRST registered user in the database
is treated as the OSS user. Tests cover:

1. Auth: missing header → 401
2. Auth: wrong token → 401
3. Misconfig: MYAH_AGENT_BEARER_TOKEN unset → 503 (refuse, don't 200)
4. Empty user table → 404 (with actionable message)
5. Happy path: returns user_id + user_name + deployment_mode
6. deployment_mode reflects MYAH_DEPLOYMENT_MODE env var
"""

import os
from pathlib import Path

os.environ.setdefault('DATABASE_URL', 'sqlite://')
os.environ.setdefault('ENABLE_DB_MIGRATIONS', 'False')
os.environ.setdefault('WEBUI_SECRET_KEY', 'test-secret')

import subprocess
import sys
import textwrap
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from myah.routers.myah import router

# ── Import hygiene regression ──────────────────────────────────────

def test_router_import_does_not_initialize_socket_or_config(tmp_path):
    """Regression: importing ``myah.routers.myah`` must NOT pull in
    ``myah.utils.chat_tasks`` / ``myah.socket.main`` / ``myah.config`` at
    module-load time.

    Those modules query the ``config`` table at import time; importing them
    during pytest collection broke this file's collection with
    ``sqlite3.OperationalError: no such table: config`` (PR #269). The router
    now resolves ``background_tasks_handler`` lazily at call time, so it can be
    imported against a DB that has no tables.
    """
    db_path = tmp_path / 'import-regression.db'
    code = textwrap.dedent(
        """
        import sys
        import myah.routers.myah  # noqa: F401

        leaked = [
            m for m in ('myah.utils.chat_tasks', 'myah.socket.main', 'myah.config')
            if m in sys.modules
        ]
        assert not leaked, f'router import pulled in: {leaked}'
        """
    )
    # Pin myah resolution to THIS source tree. The backend dir (parent of the
    # ``myah`` package) is ``test_myah.py``'s parents[3]; prepending it to
    # PYTHONPATH makes the subprocess import the same source the parent test
    # process does, regardless of any editable install pointing elsewhere.
    backend_dir = Path(__file__).resolve().parents[3]
    env = {
        **os.environ,
        'PYTHONPATH': os.pathsep.join(
            [str(backend_dir), os.environ.get('PYTHONPATH', '')]
        ).rstrip(os.pathsep),
        'DATABASE_URL': f'sqlite:///{db_path}',
        'ENABLE_DB_MIGRATIONS': 'False',
        'MYAH_SECRET_KEY': 'test-secret',
    }
    result = subprocess.run(
        [sys.executable, '-c', code], capture_output=True, text=True, env=env
    )
    assert result.returncode == 0, result.stderr


class _AsyncReturn:
    """Minimal async-callable mock that records call_count.

    The existing tests use ``unittest.mock.patch`` for sync helpers;
    this fills the same role for async functions without pulling in
    AsyncMock just for two more tests.
    """

    def __init__(self, value):
        self._value = value
        self.call_count = 0

    async def __call__(self, *args, **kwargs):
        self.call_count += 1
        return self._value


def _make_app() -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix='/api/v1/myah')
    return TestClient(app)


# ── Auth ───────────────────────────────────────────────────────────


def test_whoami_missing_authorization_header_returns_401(monkeypatch):
    monkeypatch.setenv('MYAH_AGENT_BEARER_TOKEN', 'expected-token')
    client = _make_app()
    resp = client.get('/api/v1/myah/whoami')
    assert resp.status_code == 401
    assert 'Authorization' in resp.json()['detail']


def test_whoami_wrong_token_returns_401(monkeypatch):
    monkeypatch.setenv('MYAH_AGENT_BEARER_TOKEN', 'expected-token')
    client = _make_app()
    resp = client.get(
        '/api/v1/myah/whoami', headers={'Authorization': 'Bearer wrong-token'}
    )
    assert resp.status_code == 401
    assert 'Invalid bearer token' in resp.json()['detail']


def test_whoami_unconfigured_token_returns_503(monkeypatch):
    """If the platform itself doesn't have MYAH_AGENT_BEARER_TOKEN set, /whoami
    must NOT silently 200 — it should refuse so the plugin sees a clear error."""
    monkeypatch.delenv('MYAH_AGENT_BEARER_TOKEN', raising=False)
    client = _make_app()
    resp = client.get(
        '/api/v1/myah/whoami', headers={'Authorization': 'Bearer anything'}
    )
    assert resp.status_code == 503
    assert 'MYAH_AGENT_BEARER_TOKEN not configured' in resp.json()['detail']


# ── Single-tenant resolution ─────────────────────────────────────────


def test_whoami_no_users_returns_404(monkeypatch):
    monkeypatch.setenv('MYAH_AGENT_BEARER_TOKEN', 'tok')

    client = _make_app()
    # Users.get_users returns a dict with 'users' list (current Open WebUI shape).
    with patch(
        'myah.routers.myah.Users.get_users',
        return_value={'users': [], 'total': 0},
    ):
        resp = client.get('/api/v1/myah/whoami', headers={'Authorization': 'Bearer tok'})

    assert resp.status_code == 404
    detail = resp.json()['detail']
    assert 'No users registered' in detail
    assert 'Sign up' in detail  # actionable message


def test_whoami_returns_first_user(monkeypatch):
    monkeypatch.setenv('MYAH_AGENT_BEARER_TOKEN', 'tok')
    monkeypatch.setenv('MYAH_DEPLOYMENT_MODE', 'oss')

    fake_user = SimpleNamespace(id='user-abc-123', name='Alice')

    client = _make_app()
    with patch(
        'myah.routers.myah.Users.get_users',
        return_value={'users': [fake_user], 'total': 1},
    ):
        resp = client.get('/api/v1/myah/whoami', headers={'Authorization': 'Bearer tok'})

    assert resp.status_code == 200
    body = resp.json()
    assert body['user_id'] == 'user-abc-123'
    assert body['user_name'] == 'Alice'
    assert body['deployment_mode'] == 'oss'


def test_whoami_deployment_mode_hosted_when_unset(monkeypatch):
    monkeypatch.setenv('MYAH_AGENT_BEARER_TOKEN', 'tok')
    monkeypatch.delenv('MYAH_DEPLOYMENT_MODE', raising=False)

    fake_user = SimpleNamespace(id='u1', name='Bob')

    client = _make_app()
    with patch(
        'myah.routers.myah.Users.get_users',
        return_value={'users': [fake_user], 'total': 1},
    ):
        resp = client.get('/api/v1/myah/whoami', headers={'Authorization': 'Bearer tok'})

    assert resp.status_code == 200
    assert resp.json()['deployment_mode'] == 'hosted'


def test_whoami_user_with_no_name_returns_empty_string(monkeypatch):
    """User.name can be None per ORM. Coerce to empty string for the wire payload."""
    monkeypatch.setenv('MYAH_AGENT_BEARER_TOKEN', 'tok')

    fake_user = SimpleNamespace(id='u1', name=None)

    client = _make_app()
    with patch(
        'myah.routers.myah.Users.get_users',
        return_value={'users': [fake_user], 'total': 1},
    ):
        resp = client.get('/api/v1/myah/whoami', headers={'Authorization': 'Bearer tok'})

    assert resp.status_code == 200
    assert resp.json()['user_name'] == ''


def test_whoami_handles_legacy_list_shape(monkeypatch):
    """Old / mocked Users.get_users may return a plain list. Handle gracefully."""
    monkeypatch.setenv('MYAH_AGENT_BEARER_TOKEN', 'tok')

    fake_user = SimpleNamespace(id='u-legacy', name='Legacy')

    client = _make_app()
    with patch('myah.routers.myah.Users.get_users', return_value=[fake_user]):
        resp = client.get('/api/v1/myah/whoami', headers={'Authorization': 'Bearer tok'})

    assert resp.status_code == 200
    assert resp.json()['user_id'] == 'u-legacy'


# ── OSS Issue #5 — /whoami exposes hermes default-model ───────────────


def test_whoami_returns_hermes_default_model_in_oss(monkeypatch):
    """OSS regression: /whoami includes the user's hermes config default
    (provider, model) pair so the plugin can sync the user row to it.

    Post-2026-05-24: the pair is split across default_model + default_provider
    fields mirroring Hermes upstream's canonical {provider, model} shape.
    """
    monkeypatch.setenv('MYAH_AGENT_BEARER_TOKEN', 'tok')
    monkeypatch.setenv('MYAH_DEPLOYMENT_MODE', 'oss')

    fake_user = SimpleNamespace(id='u1', name='Alice')

    client = _make_app()
    with patch(
        'myah.routers.myah.Users.get_users',
        return_value={'users': [fake_user], 'total': 1},
    ), patch(
        'myah.utils.hermes_web.fetch_hermes_default_model',
        new=_AsyncReturn(('opencode-go', 'mimo-v2.5')),
    ):
        resp = client.get('/api/v1/myah/whoami', headers={'Authorization': 'Bearer tok'})

    assert resp.status_code == 200
    body = resp.json()
    assert body['default_model'] == 'mimo-v2.5'
    assert body['default_provider'] == 'opencode-go'


def test_whoami_default_model_is_none_in_hosted(monkeypatch):
    """Hosted mode (no MYAH_DEPLOYMENT_MODE): default_model is None
    AND the hermes-default-model fetcher must NOT be called.
    """
    monkeypatch.setenv('MYAH_AGENT_BEARER_TOKEN', 'tok')
    monkeypatch.delenv('MYAH_DEPLOYMENT_MODE', raising=False)

    fake_user = SimpleNamespace(id='u1', name='Alice')
    fake_fetch = _AsyncReturn('should-not-be-called')

    client = _make_app()
    with patch(
        'myah.routers.myah.Users.get_users',
        return_value={'users': [fake_user], 'total': 1},
    ), patch(
        'myah.utils.hermes_web.fetch_hermes_default_model',
        new=fake_fetch,
    ):
        resp = client.get('/api/v1/myah/whoami', headers={'Authorization': 'Bearer tok'})

    assert resp.status_code == 200
    assert resp.json().get('default_model') is None
    assert fake_fetch.call_count == 0


def test_whoami_default_model_handles_hermes_unreachable(monkeypatch):
    """If hermes is unreachable, /whoami still 200s with default_model=None."""
    monkeypatch.setenv('MYAH_AGENT_BEARER_TOKEN', 'tok')
    monkeypatch.setenv('MYAH_DEPLOYMENT_MODE', 'oss')

    fake_user = SimpleNamespace(id='u1', name='Alice')

    client = _make_app()
    with patch(
        'myah.routers.myah.Users.get_users',
        return_value={'users': [fake_user], 'total': 1},
    ), patch(
        'myah.utils.hermes_web.fetch_hermes_default_model',
        new=_AsyncReturn(None),
    ):
        resp = client.get('/api/v1/myah/whoami', headers={'Authorization': 'Bearer tok'})

    assert resp.status_code == 200
    assert resp.json().get('default_model') is None


# ── ISSUE-004 follow-up — /whoami syncs user.default_model ─────────────


def test_whoami_oss_syncs_default_model_when_user_default_empty(monkeypatch):
    """OSS: if user has no default pair set and hermes returns one,
    the platform should update the user row directly (no JWT needed —
    the plugin only has the bearer).

    Post-2026-05-24: writes the structured (provider, model) pair to both
    default_model and default_provider columns atomically.
    """
    monkeypatch.setenv('MYAH_AGENT_BEARER_TOKEN', 'tok')
    monkeypatch.setenv('MYAH_DEPLOYMENT_MODE', 'oss')

    fake_user = SimpleNamespace(id='u1', name='Alice', default_model=None, default_provider=None)
    update_calls = []

    def _capture_update(user_id, updates):
        update_calls.append((user_id, updates))
        return SimpleNamespace(
            id=user_id,
            default_model=updates.get('default_model'),
            default_provider=updates.get('default_provider'),
        )

    client = _make_app()
    with patch(
        'myah.routers.myah.Users.get_users',
        return_value={'users': [fake_user], 'total': 1},
    ), patch(
        'myah.routers.myah.Users.update_user_by_id',
        side_effect=_capture_update,
    ), patch(
        'myah.utils.hermes_web.fetch_hermes_default_model',
        new=_AsyncReturn(('opencode-go', 'mimo-v2.5')),
    ):
        resp = client.get('/api/v1/myah/whoami', headers={'Authorization': 'Bearer tok'})

    assert resp.status_code == 200
    body = resp.json()
    assert body['default_model'] == 'mimo-v2.5'
    assert body['default_provider'] == 'opencode-go'
    # Verify the update was called with the hermes default pair
    assert update_calls == [
        ('u1', {'default_provider': 'opencode-go', 'default_model': 'mimo-v2.5'})
    ]


def test_whoami_oss_syncs_default_model_when_user_has_openwebui_default(monkeypatch):
    """OSS: if user has the legacy Open WebUI default pair ('openai', 'gpt-4o-mini'),
    overwrite it (the user didn't deliberately choose it — open-webui set it
    at signup as the bundled fallback)."""
    monkeypatch.setenv('MYAH_AGENT_BEARER_TOKEN', 'tok')
    monkeypatch.setenv('MYAH_DEPLOYMENT_MODE', 'oss')

    fake_user = SimpleNamespace(
        id='u1', name='Alice', default_model='gpt-4o-mini', default_provider='openai'
    )
    update_calls = []

    def _capture_update(user_id, updates):
        update_calls.append((user_id, updates))
        return SimpleNamespace(
            id=user_id,
            default_model=updates.get('default_model'),
            default_provider=updates.get('default_provider'),
        )

    client = _make_app()
    with patch(
        'myah.routers.myah.Users.get_users',
        return_value={'users': [fake_user], 'total': 1},
    ), patch(
        'myah.routers.myah.Users.update_user_by_id',
        side_effect=_capture_update,
    ), patch(
        'myah.utils.hermes_web.fetch_hermes_default_model',
        new=_AsyncReturn(('opencode-go', 'mimo-v2.5')),
    ):
        resp = client.get('/api/v1/myah/whoami', headers={'Authorization': 'Bearer tok'})

    assert resp.status_code == 200
    assert update_calls == [
        ('u1', {'default_provider': 'opencode-go', 'default_model': 'mimo-v2.5'})
    ]


def test_whoami_oss_does_not_clobber_deliberate_user_choice(monkeypatch):
    """OSS: if user.default pair is anything OTHER than (None, None)/('openai', 'gpt-4o-mini'),
    treat it as a deliberate choice and do NOT overwrite.

    The user may have explicitly switched models in the UI; we shouldn't
    blow that choice away just because hermes config differs.
    """
    monkeypatch.setenv('MYAH_AGENT_BEARER_TOKEN', 'tok')
    monkeypatch.setenv('MYAH_DEPLOYMENT_MODE', 'oss')

    fake_user = SimpleNamespace(
        id='u1', name='Alice',
        default_model='claude-opus-4.7', default_provider='anthropic',
    )
    update_calls = []

    client = _make_app()
    with patch(
        'myah.routers.myah.Users.get_users',
        return_value={'users': [fake_user], 'total': 1},
    ), patch(
        'myah.routers.myah.Users.update_user_by_id',
        side_effect=lambda *a, **kw: update_calls.append((a, kw)) or fake_user,
    ), patch(
        'myah.utils.hermes_web.fetch_hermes_default_model',
        new=_AsyncReturn(('opencode-go', 'mimo-v2.5')),
    ):
        resp = client.get('/api/v1/myah/whoami', headers={'Authorization': 'Bearer tok'})

    assert resp.status_code == 200
    # Response surfaces hermes default for transparency, but DB is untouched
    body = resp.json()
    assert body['default_model'] == 'mimo-v2.5'
    assert body['default_provider'] == 'opencode-go'
    assert update_calls == [], 'must not clobber deliberate user choice'


def test_whoami_hosted_never_syncs_default_model(monkeypatch):
    """Hosted: default_model sync logic is gated on OSS mode."""
    monkeypatch.setenv('MYAH_AGENT_BEARER_TOKEN', 'tok')
    monkeypatch.delenv('MYAH_DEPLOYMENT_MODE', raising=False)

    fake_user = SimpleNamespace(id='u1', name='Alice', default_model=None)
    update_calls = []

    client = _make_app()
    with patch(
        'myah.routers.myah.Users.get_users',
        return_value={'users': [fake_user], 'total': 1},
    ), patch(
        'myah.routers.myah.Users.update_user_by_id',
        side_effect=lambda *a, **kw: update_calls.append((a, kw)) or fake_user,
    ):
        resp = client.get('/api/v1/myah/whoami', headers={'Authorization': 'Bearer tok'})

    assert resp.status_code == 200
    assert update_calls == []


# ── ISSUE-003 — /whoami auto-imports hermes provider catalog in OSS ───


def test_whoami_oss_auto_imports_providers_from_hermes_catalog(monkeypatch):
    """OSS: /whoami upserts UserProviderStatuses for every provider in the
    user's hermes catalog that has a credential. Eliminates the 'connected
    only via UI' problem from Issue #4 + Issue #3."""
    monkeypatch.setenv('MYAH_AGENT_BEARER_TOKEN', 'tok')
    monkeypatch.setenv('MYAH_DEPLOYMENT_MODE', 'oss')

    fake_user = SimpleNamespace(id='u1', name='Alice', default_model=None)
    upsert_calls = []

    fake_catalog = [
        {'id': 'openrouter', 'has_credential': True, 'label': 'OpenRouter'},
        {'id': 'opencode-go', 'has_credential': True, 'label': 'OpenCode Go'},
        {'id': 'zai', 'has_credential': True, 'label': 'Z.AI'},
        # has_credential=False → should NOT be imported
        {'id': 'anthropic', 'has_credential': False, 'label': 'Anthropic'},
    ]

    client = _make_app()
    with patch(
        'myah.routers.myah.Users.get_users',
        return_value={'users': [fake_user], 'total': 1},
    ), patch(
        'myah.utils.hermes_web.fetch_hermes_provider_catalog',
        new=_AsyncReturn(fake_catalog),
    ), patch(
        'myah.models.user_provider_status.UserProviderStatuses.upsert',
        side_effect=lambda **kw: upsert_calls.append(kw) or SimpleNamespace(**kw),
    ), patch(
        'myah.utils.hermes_web.fetch_hermes_default_model',
        new=_AsyncReturn(None),
    ):
        resp = client.get('/api/v1/myah/whoami', headers={'Authorization': 'Bearer tok'})

    assert resp.status_code == 200

    upserted_ids = {c['provider_id'] for c in upsert_calls}
    assert upserted_ids == {'openrouter', 'opencode-go', 'zai'}, (
        f'expected 3 credentialed providers, got {upserted_ids}'
    )
    # All upserts must mark the row as the auto-import variant
    for call in upsert_calls:
        assert call['user_id'] == 'u1'
        assert call['is_valid'] is True
        assert call['key_last_four'] == 'hermes'  # marker for "auto-imported"


def test_whoami_hosted_never_auto_imports_providers(monkeypatch):
    """Hosted: the auto-import path is OSS-only."""
    monkeypatch.setenv('MYAH_AGENT_BEARER_TOKEN', 'tok')
    monkeypatch.delenv('MYAH_DEPLOYMENT_MODE', raising=False)

    fake_user = SimpleNamespace(id='u1', name='Alice', default_model=None)
    upsert_calls = []
    fetcher = _AsyncReturn([{'id': 'openrouter', 'has_credential': True}])

    client = _make_app()
    with patch(
        'myah.routers.myah.Users.get_users',
        return_value={'users': [fake_user], 'total': 1},
    ), patch(
        'myah.utils.hermes_web.fetch_hermes_provider_catalog',
        new=fetcher,
    ), patch(
        'myah.models.user_provider_status.UserProviderStatuses.upsert',
        side_effect=lambda **kw: upsert_calls.append(kw),
    ):
        resp = client.get('/api/v1/myah/whoami', headers={'Authorization': 'Bearer tok'})

    assert resp.status_code == 200
    assert upsert_calls == []
    # The catalog fetcher must not even be called in hosted mode
    assert fetcher.call_count == 0


def test_whoami_oss_provider_import_failure_does_not_block_whoami(monkeypatch):
    """If the catalog fetch raises, /whoami still returns 200 with the
    user_id — the plugin needs user_id even when the import fails."""
    monkeypatch.setenv('MYAH_AGENT_BEARER_TOKEN', 'tok')
    monkeypatch.setenv('MYAH_DEPLOYMENT_MODE', 'oss')

    fake_user = SimpleNamespace(id='u1', name='Alice', default_model=None)

    async def _explode(*a, **kw):
        raise RuntimeError('hermes unreachable')

    client = _make_app()
    with patch(
        'myah.routers.myah.Users.get_users',
        return_value={'users': [fake_user], 'total': 1},
    ), patch(
        'myah.utils.hermes_web.fetch_hermes_provider_catalog',
        new=_explode,
    ), patch(
        'myah.utils.hermes_web.fetch_hermes_default_model',
        new=_AsyncReturn(None),
    ):
        resp = client.get('/api/v1/myah/whoami', headers={'Authorization': 'Bearer tok'})

    assert resp.status_code == 200
    assert resp.json()['user_id'] == 'u1'


def test_whoami_oss_skips_providers_without_credential(monkeypatch):
    """Providers in the catalog without credentials are NOT imported.
    These are visible-but-not-credentialed entries (provider available
    in UI but user hasn't connected). They should stay disconnected
    until the user provides a key."""
    monkeypatch.setenv('MYAH_AGENT_BEARER_TOKEN', 'tok')
    monkeypatch.setenv('MYAH_DEPLOYMENT_MODE', 'oss')

    fake_user = SimpleNamespace(id='u1', name='Alice', default_model=None)
    upsert_calls = []

    fake_catalog = [
        {'id': 'openrouter', 'has_credential': False, 'label': 'OpenRouter'},
        {'id': 'anthropic', 'has_credential': False, 'label': 'Anthropic'},
    ]

    client = _make_app()
    with patch(
        'myah.routers.myah.Users.get_users',
        return_value={'users': [fake_user], 'total': 1},
    ), patch(
        'myah.utils.hermes_web.fetch_hermes_provider_catalog',
        new=_AsyncReturn(fake_catalog),
    ), patch(
        'myah.models.user_provider_status.UserProviderStatuses.upsert',
        side_effect=lambda **kw: upsert_calls.append(kw),
    ), patch(
        'myah.utils.hermes_web.fetch_hermes_default_model',
        new=_AsyncReturn(None),
    ):
        resp = client.get('/api/v1/myah/whoami', headers={'Authorization': 'Bearer tok'})

    assert resp.status_code == 200
    assert upsert_calls == []


# ── Durable final-message fallback ─────────────────────────────────

def test_final_message_requires_bearer(monkeypatch):
    monkeypatch.setenv('MYAH_AGENT_BEARER_TOKEN', 'tok')
    client = _make_app()

    resp = client.post(
        '/api/v1/myah/messages/final',
        json={
            'user_id': 'u1',
            'chat_id': 'chat1',
            'message_id': 'msg1',
            'response': 'hello',
        },
    )

    assert resp.status_code == 401


def test_final_message_persists_assistant_reply(monkeypatch):
    monkeypatch.setenv('MYAH_AGENT_BEARER_TOKEN', 'tok')
    client = _make_app()

    fake_chat = SimpleNamespace(id='chat1', user_id='u1', chat={'history': {'messages': {}}})
    with (
        patch('myah.routers.myah.Chats.get_chat_by_id_and_user_id', return_value=fake_chat),
        patch('myah.routers.myah.Chats.upsert_message_to_chat_by_id_and_message_id') as upsert,
    ):
        upsert.return_value = fake_chat
        resp = client.post(
            '/api/v1/myah/messages/final',
            headers={'Authorization': 'Bearer tok'},
            json={
                'user_id': 'u1',
                'chat_id': 'chat1',
                'message_id': 'msg1',
                'response': 'final answer',
                'model': 'gpt-5.4',
                'provider': 'openai-codex',
            },
        )

    assert resp.status_code == 200
    assert resp.json() == {'ok': True, 'message_id': 'msg1'}
    upsert.assert_called_once()
    args = upsert.call_args.args
    assert args[0] == 'chat1'
    assert args[1] == 'msg1'
    update = args[2]
    assert update['role'] == 'assistant'
    assert update['content'] == 'final answer'
    assert update['done'] is True
    assert update['modelUsed'] == {'id': 'gpt-5.4', 'provider': 'openai-codex'}


def test_final_message_rejects_wrong_user_chat(monkeypatch):
    monkeypatch.setenv('MYAH_AGENT_BEARER_TOKEN', 'tok')
    client = _make_app()

    with patch('myah.routers.myah.Chats.get_chat_by_id_and_user_id', return_value=None):
        resp = client.post(
            '/api/v1/myah/messages/final',
            headers={'Authorization': 'Bearer tok'},
            json={
                'user_id': 'u1',
                'chat_id': 'missing-chat',
                'message_id': 'msg1',
                'response': 'final answer',
            },
        )

    assert resp.status_code == 404


def test_final_message_requires_message_id(monkeypatch):
    monkeypatch.setenv('MYAH_AGENT_BEARER_TOKEN', 'tok')
    client = _make_app()

    fake_chat = SimpleNamespace(id='chat1', user_id='u1', chat={'history': {'messages': {}}})
    with patch('myah.routers.myah.Chats.get_chat_by_id_and_user_id', return_value=fake_chat):
        resp = client.post(
            '/api/v1/myah/messages/final',
            headers={'Authorization': 'Bearer tok'},
            json={
                'user_id': 'u1',
                'chat_id': 'chat1',
                'response': 'final answer',
            },
        )

    assert resp.status_code == 400
    assert 'message_id' in resp.json()['detail']


def test_final_message_rejects_invalid_status(monkeypatch):
    monkeypatch.setenv('MYAH_AGENT_BEARER_TOKEN', 'tok')
    client = _make_app()

    fake_chat = SimpleNamespace(id='chat1', user_id='u1', chat={'history': {'messages': {}}})
    with patch('myah.routers.myah.Chats.get_chat_by_id_and_user_id', return_value=fake_chat):
        resp = client.post(
            '/api/v1/myah/messages/final',
            headers={'Authorization': 'Bearer tok'},
            json={
                'user_id': 'u1',
                'chat_id': 'chat1',
                'message_id': 'msg1',
                'response': 'final answer',
                'status': 'weird',
            },
        )

    assert resp.status_code == 400
    assert 'status' in resp.json()['detail']


def test_final_message_emits_active_chat_shaped_completion(monkeypatch):
    monkeypatch.setenv('MYAH_AGENT_BEARER_TOKEN', 'tok')
    client = _make_app()

    emitted = []

    async def _capture_emit(room, envelope):
        emitted.append((room, envelope))

    fake_chat = SimpleNamespace(id='chat1', user_id='u1', chat={'history': {'messages': {}}})
    with (
        patch('myah.routers.myah.Chats.get_chat_by_id_and_user_id', return_value=fake_chat),
        patch('myah.routers.myah.Chats.upsert_message_to_chat_by_id_and_message_id', return_value=fake_chat),
        patch('myah.routers.myah._emit_socket_event', new=_capture_emit),
    ):
        resp = client.post(
            '/api/v1/myah/messages/final',
            headers={'Authorization': 'Bearer tok'},
            json={
                'user_id': 'u1',
                'chat_id': 'chat1',
                'message_id': 'msg1',
                'response': 'final answer',
            },
        )

    assert resp.status_code == 200
    completion = next(envelope for room, envelope in emitted if envelope['data']['type'] == 'chat:completion')
    assert completion == {
        'chat_id': 'chat1',
        'message_id': 'msg1',
        'data': {
            'type': 'chat:completion',
            'data': {
                'content': 'final answer',
                'done': True,
                'message_id': 'msg1',
                'chat_id': 'chat1',
            },
        },
    }


def test_final_message_duplicate_retry_is_idempotent(monkeypatch):
    monkeypatch.setenv('MYAH_AGENT_BEARER_TOKEN', 'tok')
    client = _make_app()

    emitted = []

    async def _capture_emit(room, envelope):
        emitted.append((room, envelope))

    fake_chat = SimpleNamespace(
        id='chat1',
        user_id='u1',
        chat={
            'history': {
                'messages': {
                    'msg1': {
                        'id': 'msg1',
                        'role': 'assistant',
                        'content': 'final answer',
                        'done': True,
                    }
                }
            }
        },
    )
    with (
        patch('myah.routers.myah.Chats.get_chat_by_id_and_user_id', return_value=fake_chat),
        patch('myah.routers.myah.Chats.upsert_message_to_chat_by_id_and_message_id') as upsert,
        patch('myah.routers.myah.background_tasks_handler') as background_handler,
        patch('myah.routers.myah.asyncio.create_task') as create_task,
        patch('myah.routers.myah._emit_socket_event', new=_capture_emit),
    ):
        resp = client.post(
            '/api/v1/myah/messages/final',
            headers={'Authorization': 'Bearer tok'},
            json={
                'user_id': 'u1',
                'chat_id': 'chat1',
                'message_id': 'msg1',
                'response': 'final answer',
            },
        )

    assert resp.status_code == 200
    assert resp.json() == {'ok': True, 'message_id': 'msg1', 'duplicate': True}
    upsert.assert_not_called()
    background_handler.assert_not_called()
    create_task.assert_not_called()
    assert emitted == []


def test_final_message_triggers_background_tasks_when_persisted(monkeypatch):
    monkeypatch.setenv('MYAH_AGENT_BEARER_TOKEN', 'tok')
    client = _make_app()

    bg_calls = []

    async def _fake_bg(ctx):
        bg_calls.append(ctx)

    fake_chat = SimpleNamespace(id='chat1', user_id='u1', chat={'history': {'messages': {}}})
    scheduled = []

    def _fake_create_task(coro):
        scheduled.append(coro)
        task = Mock()
        task.exception.return_value = None
        task.add_done_callback.return_value = None
        return task

    with (
        patch('myah.routers.myah.Chats.get_chat_by_id_and_user_id', return_value=fake_chat),
        patch('myah.routers.myah.Users.get_user_by_id', return_value=SimpleNamespace(settings={})),
        patch('myah.routers.myah.Chats.upsert_message_to_chat_by_id_and_message_id', return_value=fake_chat),
        patch('myah.routers.myah.background_tasks_handler', new=_fake_bg),
        patch('myah.routers.myah.asyncio.create_task', side_effect=_fake_create_task) as create_task,
    ):
        resp = client.post(
            '/api/v1/myah/messages/final',
            headers={'Authorization': 'Bearer tok'},
            json={
                'user_id': 'u1',
                'chat_id': 'chat1',
                'message_id': 'msg1',
                'response': 'final answer',
                'model': 'gpt-5.4',
                'provider': 'openai-codex',
            },
        )

    assert resp.status_code == 200
    assert len(bg_calls) == 0
    create_task.assert_called_once()
    assert len(scheduled) == 1

    import asyncio

    asyncio.run(scheduled[0])
    assert len(bg_calls) == 1
    ctx = bg_calls[0]
    assert ctx['metadata']['chat_id'] == 'chat1'
    assert ctx['metadata']['message_id'] == 'msg1'
    assert ctx['form_data']['model'] == 'gpt-5.4'
    assert ctx['form_data']['messages'] == [
        {'role': 'assistant', 'content': 'final answer', 'model': 'gpt-5.4'}
    ]
    assert ctx['tasks']['title_generation'] is True
    assert ctx['tasks']['follow_up_generation'] is True


def test_final_message_respects_disabled_generation_settings(monkeypatch):
    monkeypatch.setenv('MYAH_AGENT_BEARER_TOKEN', 'tok')
    client = _make_app()

    bg_calls = []

    async def _fake_bg(ctx):
        bg_calls.append(ctx)

    fake_chat = SimpleNamespace(id='chat1', user_id='u1', chat={'history': {'messages': {}}})
    scheduled = []

    def _fake_create_task(coro):
        scheduled.append(coro)
        task = Mock()
        task.exception.return_value = None
        task.add_done_callback.return_value = None
        return task

    user_with_disabled_generation = SimpleNamespace(
        settings={
            'title': {'auto': False},
            'autoFollowUps': False,
        }
    )

    with (
        patch('myah.routers.myah.Chats.get_chat_by_id_and_user_id', return_value=fake_chat),
        patch('myah.routers.myah.Users.get_user_by_id', return_value=user_with_disabled_generation),
        patch('myah.routers.myah.Chats.upsert_message_to_chat_by_id_and_message_id', return_value=fake_chat),
        patch('myah.routers.myah.background_tasks_handler', new=_fake_bg),
        patch('myah.routers.myah.asyncio.create_task', side_effect=_fake_create_task),
    ):
        resp = client.post(
            '/api/v1/myah/messages/final',
            headers={'Authorization': 'Bearer tok'},
            json={
                'user_id': 'u1',
                'chat_id': 'chat1',
                'message_id': 'msg1',
                'response': 'final answer',
                'model': 'gpt-5.4',
            },
        )

    assert resp.status_code == 200
    assert len(scheduled) == 1

    import asyncio

    asyncio.run(scheduled[0])
    assert len(bg_calls) == 1
    ctx = bg_calls[0]
    assert ctx['tasks']['title_generation'] is False
    assert ctx['tasks']['follow_up_generation'] is False
