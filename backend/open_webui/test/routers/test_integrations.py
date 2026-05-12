"""Pytest coverage for the Composio integration layer.

Covers:
  - SDK wrapper functions (mocked Composio client)
  - All 7 integrations router endpoints (FastAPI TestClient)
  - Callback state JWT rejection regression
  - 409 name-reservation guard on POST /api/v1/agent/mcp
  - User-delete cleanup hook for integration sessions
"""

import datetime as dt
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jose import jwt


# ── Shared fixtures ──────────────────────────────────────────────────────────

_MOCK_USER = MagicMock(id='test-user-id', role='user')

_SECRET = 'test-secret-key-for-integrations'


def _make_state(user_id: str, toolkit: str) -> str:
    """Sign a state JWT matching the router's _sign_state logic."""
    now = dt.datetime.now(dt.timezone.utc)
    from uuid import uuid4

    payload = {
        'user_id': user_id,
        'toolkit': toolkit,
        'nonce': uuid4().hex,
        'exp': now + dt.timedelta(seconds=300),
        'iat': now,
    }
    return jwt.encode(payload, _SECRET, algorithm='HS256')


# ── TestComposioWrapper ──────────────────────────────────────────────────────


class TestComposioWrapper:
    """Unit tests for SDK wrapper functions in open_webui.utils.composio."""

    def test_get_client_raises_without_api_key(self):
        """_get_client must raise RuntimeError when COMPOSIO_API_KEY is empty."""
        from open_webui.utils import composio as mod

        # Reset the module-level singleton so the next call re-initialises.
        mod._composio_client = None

        with patch.object(mod, 'COMPOSIO_API_KEY', ''):
            with pytest.raises(RuntimeError, match='COMPOSIO_API_KEY is not configured'):
                mod._get_client()

    def test_get_client_returns_singleton_when_key_set(self):
        """_get_client returns the same Composio instance on repeated calls."""
        from open_webui.utils import composio as mod

        mod._composio_client = None

        fake_client = MagicMock()
        with patch.object(mod, 'COMPOSIO_API_KEY', 'sk-test'), patch.object(
            mod, 'Composio', return_value=fake_client
        ) as mock_cls:
            client1 = mod._get_client()
            client2 = mod._get_client()
            mock_cls.assert_called_once_with(api_key='sk-test')
            assert client1 is client2

        # Clean up singleton for subsequent tests.
        mod._composio_client = None

    def test_list_toolkits_returns_dict(self):
        """list_toolkits must return a dict with 'items' and 'next_cursor'."""
        from open_webui.utils import composio as mod

        user = MagicMock(id='u1')

        # Build a mock toolkit item with .connection attribute.
        conn_account = MagicMock(id='ca_abc', alias='work')
        connection = MagicMock(is_active=True, connected_account=conn_account)
        item = MagicMock(
            slug='gmail',
            name='Gmail',
            logo='https://example.com/gmail.png',
            is_no_auth=False,
            connection=connection,
        )
        result = MagicMock(items=[item], next_cursor='cursor123')

        with patch.object(mod, '_get_client') as mock_client, patch.object(
            mod, '_session_cache', {}
        ):
            session = MagicMock()
            session.toolkits.return_value = result
            mock_client.return_value.create.return_value = session

            out = mod.list_toolkits(user)

        assert 'items' in out
        assert 'next_cursor' in out
        assert out['next_cursor'] == 'cursor123'
        assert len(out['items']) == 1
        assert out['items'][0]['slug'] == 'gmail'
        assert out['items'][0]['connection']['is_active'] is True
        assert out['items'][0]['connection']['id'] == 'ca_abc'
        assert out['items'][0]['connection']['alias'] is None

    def test_list_toolkits_no_connection(self):
        """list_toolkits omits 'connection' key when item has no connection."""
        from open_webui.utils import composio as mod

        user = MagicMock(id='u2')
        item = MagicMock(
            slug='slack',
            name='Slack',
            logo='https://example.com/slack.png',
            is_no_auth=False,
            connection=None,
        )
        result = MagicMock(items=[item], next_cursor=None)

        with patch.object(mod, '_get_client') as mock_client, patch.object(
            mod, '_session_cache', {}
        ):
            session = MagicMock()
            session.toolkits.return_value = result
            mock_client.return_value.create.return_value = session

            out = mod.list_toolkits(user)

        assert out['items'][0].get('connection') is None

    def test_list_toolkits_omits_inactive_connection(self):
        """Regression: SDK always returns a connection object even for unconnected
        toolkits (with is_active=False). list_toolkits MUST omit it so the frontend's
        'second account' modal doesn't fire on first connect."""
        from open_webui.utils import composio as mod

        user = MagicMock(id='u3')
        inactive = MagicMock(is_active=False, connected_account=None)
        item = MagicMock(
            slug='gmail',
            name='Gmail',
            logo='https://example.com/gmail.png',
            is_no_auth=False,
            connection=inactive,
        )
        result = MagicMock(items=[item], next_cursor=None)

        with patch.object(mod, '_get_client') as mock_client, patch.object(
            mod, '_session_cache', {}
        ):
            session = MagicMock()
            session.toolkits.return_value = result
            mock_client.return_value.create.return_value = session

            out = mod.list_toolkits(user)

        assert 'connection' not in out['items'][0]

    def test_list_catalog_returns_list(self):
        """list_catalog must return a list of toolkit dicts with auth metadata."""
        from open_webui.utils import composio as mod

        tk1 = MagicMock(slug='gmail', name='Gmail', is_local_toolkit=False,
                        no_auth=False, auth_schemes=['OAUTH2'],
                        composio_managed_auth_schemes=['OAUTH2'])
        tk2 = MagicMock(slug='stripe', name='Stripe', is_local_toolkit=False,
                        no_auth=False, auth_schemes=['API_KEY'],
                        composio_managed_auth_schemes=None)

        with patch.object(mod, '_get_client') as mock_client, patch.object(
            mod, '_toolkits_cache', {'items': [], 'fetched_at': 0.0}
        ):
            mock_client.return_value.toolkits.get.return_value = [tk1, tk2]
            mock_client.return_value.auth_configs.list.return_value = MagicMock(items=[])

            out = mod.list_catalog()

        assert isinstance(out, list)
        assert len(out) == 2
        assert out[0]['slug'] == 'gmail'
        assert out[0]['composio_managed_auth_schemes'] == ['OAUTH2']
        assert out[1]['slug'] == 'stripe'

    def test_list_catalog_filters_unmanaged_oauth_without_admin_config(self):
        """Twitter-style toolkits (unmanaged OAuth-only) MUST be hidden until admin sets up auth_config."""
        from open_webui.utils import composio as mod

        gmail = MagicMock(slug='gmail', name='Gmail', is_local_toolkit=False,
                          no_auth=False, auth_schemes=['OAUTH2'],
                          composio_managed_auth_schemes=['OAUTH2'])
        twitter = MagicMock(slug='twitter', name='Twitter', is_local_toolkit=False,
                            no_auth=False, auth_schemes=['OAUTH2'],
                            composio_managed_auth_schemes=[])
        stripe = MagicMock(slug='stripe', name='Stripe', is_local_toolkit=False,
                           no_auth=False, auth_schemes=['API_KEY'],
                           composio_managed_auth_schemes=None)

        with patch.object(mod, '_get_client') as mock_client, patch.object(
            mod, '_toolkits_cache', {'items': [], 'fetched_at': 0.0}
        ):
            mock_client.return_value.toolkits.get.return_value = [gmail, twitter, stripe]
            mock_client.return_value.auth_configs.list.return_value = MagicMock(items=[])

            out = mod.list_catalog()

        slugs = [item['slug'] for item in out]
        assert 'gmail' in slugs, 'managed OAuth must be visible'
        assert 'stripe' in slugs, 'API_KEY (form-based) must be visible'
        assert 'twitter' not in slugs, 'unmanaged OAuth without admin auth_config must be hidden'

    def test_list_catalog_filters_no_auth_toolkits(self):
        """no_auth=True toolkits (HackerNews, Tavily) MUST be hidden — they have no Connect flow.

        Composio rejects authorize() on them with ToolkitsIsNoAuth/4326 because there is
        nothing to authorize. The agent can already invoke them via the Composio MCP server
        without any per-user connection. Showing a Connect button would 503 every click.
        """
        from open_webui.utils import composio as mod

        hackernews = MagicMock(slug='hackernews', name='HackerNews', is_local_toolkit=False,
                                no_auth=True, auth_schemes=None,
                                composio_managed_auth_schemes=None)
        gmail = MagicMock(slug='gmail', name='Gmail', is_local_toolkit=False,
                          no_auth=False, auth_schemes=['OAUTH2'],
                          composio_managed_auth_schemes=['OAUTH2'])

        with patch.object(mod, '_get_client') as mock_client, patch.object(
            mod, '_toolkits_cache', {'items': [], 'fetched_at': 0.0}
        ):
            mock_client.return_value.toolkits.get.return_value = [hackernews, gmail]
            mock_client.return_value.auth_configs.list.return_value = MagicMock(items=[])

            out = mod.list_catalog()

        slugs = [item['slug'] for item in out]
        assert 'gmail' in slugs, 'managed OAuth must be visible'
        assert 'hackernews' not in slugs, 'no_auth toolkits must be hidden — Connect would 503'

    def test_list_catalog_includes_admin_configured_unmanaged_oauth(self):
        """Once admin creates an auth_config for Twitter, it MUST appear in the catalog."""
        from open_webui.utils import composio as mod

        twitter = MagicMock(slug='twitter', name='Twitter', is_local_toolkit=False,
                            no_auth=False, auth_schemes=['OAUTH2'],
                            composio_managed_auth_schemes=[])
        snowflake = MagicMock(slug='snowflake', name='Snowflake', is_local_toolkit=False,
                              no_auth=False, auth_schemes=['OAUTH2'],
                              composio_managed_auth_schemes=[])

        twitter_config = MagicMock()
        twitter_config.toolkit = MagicMock(slug='twitter')

        with patch.object(mod, '_get_client') as mock_client, patch.object(
            mod, '_toolkits_cache', {'items': [], 'fetched_at': 0.0}
        ):
            mock_client.return_value.toolkits.get.return_value = [twitter, snowflake]
            mock_client.return_value.auth_configs.list.return_value = MagicMock(items=[twitter_config])

            out = mod.list_catalog()

        slugs = [item['slug'] for item in out]
        assert 'twitter' in slugs, 'unmanaged OAuth WITH admin auth_config must be visible'
        assert 'snowflake' not in slugs, 'unmanaged OAuth WITHOUT admin auth_config must remain hidden'

    def test_list_catalog_degrades_gracefully_when_auth_configs_fails(self):
        """If auth_configs.list() raises, catalog must still return the always-actionable subset."""
        from open_webui.utils import composio as mod

        gmail = MagicMock(slug='gmail', name='Gmail', is_local_toolkit=False,
                          no_auth=False, auth_schemes=['OAUTH2'],
                          composio_managed_auth_schemes=['OAUTH2'])
        twitter = MagicMock(slug='twitter', name='Twitter', is_local_toolkit=False,
                            no_auth=False, auth_schemes=['OAUTH2'],
                            composio_managed_auth_schemes=[])

        with patch.object(mod, '_get_client') as mock_client, patch.object(
            mod, '_toolkits_cache', {'items': [], 'fetched_at': 0.0}
        ):
            mock_client.return_value.toolkits.get.return_value = [gmail, twitter]
            mock_client.return_value.auth_configs.list.side_effect = RuntimeError('network down')

            out = mod.list_catalog()

        slugs = [item['slug'] for item in out]
        assert 'gmail' in slugs, 'managed toolkits must still appear when auth_configs fails'
        assert 'twitter' not in slugs, 'unmanaged toolkits stay hidden when configured-set is unknown'

    def test_disconnect_returns_true_on_success(self):
        """disconnect returns True when the SDK call succeeds and ca is owned by user."""
        from open_webui.utils import composio as mod

        user = MagicMock(id='u1')

        with patch.object(mod, '_get_client') as mock_client:
            mock_client.return_value.connected_accounts.get.return_value = MagicMock(user_id='u1')
            mock_client.return_value.connected_accounts.delete.return_value = None
            result = mod.disconnect(user, 'ca_123')

        assert result is True

    def test_disconnect_returns_false_on_failure(self):
        """disconnect returns False when the SDK delete call raises (post-ownership check)."""
        from open_webui.utils import composio as mod

        user = MagicMock(id='u1')

        with patch.object(mod, '_get_client') as mock_client:
            mock_client.return_value.connected_accounts.get.return_value = MagicMock(user_id='u1')
            mock_client.return_value.connected_accounts.delete.side_effect = Exception('not found')
            result = mod.disconnect(user, 'ca_123')

        assert result is False

    def test_disconnect_blocks_cross_tenant_ca_id(self):
        """disconnect raises CrossTenantAccessError when ca_id belongs to a different user."""
        from open_webui.utils import composio as mod

        user = MagicMock(id='u1')

        with patch.object(mod, '_get_client') as mock_client:
            mock_client.return_value.connected_accounts.get.return_value = MagicMock(user_id='u2')
            with pytest.raises(mod.CrossTenantAccessError):
                mod.disconnect(user, 'ca_belongs_to_u2')

            mock_client.return_value.connected_accounts.delete.assert_not_called()

    def test_disconnect_blocks_when_ca_lookup_fails(self):
        """disconnect raises CrossTenantAccessError when SDK get() fails (fail-safe)."""
        from open_webui.utils import composio as mod

        user = MagicMock(id='u1')

        with patch.object(mod, '_get_client') as mock_client:
            mock_client.return_value.connected_accounts.get.side_effect = Exception('forged ca_id')
            with pytest.raises(mod.CrossTenantAccessError):
                mod.disconnect(user, 'ca_does_not_exist')

            mock_client.return_value.connected_accounts.delete.assert_not_called()

    def test_update_alias_returns_true_on_success(self):
        """update_alias returns True when the SDK call succeeds and ca is owned by user."""
        from open_webui.utils import composio as mod

        user = MagicMock(id='u1')

        with patch.object(mod, '_get_client') as mock_client:
            mock_client.return_value.connected_accounts.get.return_value = MagicMock(user_id='u1')
            mock_client.return_value.connected_accounts.update.return_value = None
            result = mod.update_alias(user, 'ca_123', 'my-work-gmail')

        assert result is True

    def test_update_alias_returns_false_on_failure(self):
        """update_alias returns False when the SDK update call raises (post-ownership check)."""
        from open_webui.utils import composio as mod

        user = MagicMock(id='u1')

        with patch.object(mod, '_get_client') as mock_client:
            mock_client.return_value.connected_accounts.get.return_value = MagicMock(user_id='u1')
            mock_client.return_value.connected_accounts.update.side_effect = Exception('fail')
            result = mod.update_alias(user, 'ca_123', 'my-work-gmail')

        assert result is False

    def test_update_alias_blocks_cross_tenant_ca_id(self):
        """update_alias raises CrossTenantAccessError when ca_id belongs to a different user."""
        from open_webui.utils import composio as mod

        user = MagicMock(id='u1')

        with patch.object(mod, '_get_client') as mock_client:
            mock_client.return_value.connected_accounts.get.return_value = MagicMock(user_id='u2')
            with pytest.raises(mod.CrossTenantAccessError):
                mod.update_alias(user, 'ca_belongs_to_u2', 'sneaky-rename')

            mock_client.return_value.connected_accounts.update.assert_not_called()

    def test_authorize_toolkit_returns_redirect_url(self):
        """authorize_toolkit returns the redirect_url from the SDK."""
        from open_webui.utils import composio as mod

        user = MagicMock(id='u1')

        connection_request = MagicMock(redirect_url='https://auth.example.com/oauth?state=abc')
        session = MagicMock()
        session.authorize.return_value = connection_request

        with patch.object(mod, '_get_client') as mock_client, patch.object(
            mod, '_sign_state_jwt', return_value='jwt-state-token'
        ):
            mock_client.return_value.create.return_value = session

            url = mod.authorize_toolkit(user, 'gmail', callback_url='https://app.myah.dev/api/v1/integrations/composio/callback?state=jwt-state-token')

        assert url == 'https://auth.example.com/oauth?state=abc'

    def test_authorize_toolkit_raises_when_no_redirect_url(self):
        """authorize_toolkit raises RuntimeError when redirect_url is None."""
        from open_webui.utils import composio as mod

        user = MagicMock(id='u1')

        connection_request = MagicMock(redirect_url=None)
        session = MagicMock()
        session.authorize.return_value = connection_request

        with patch.object(mod, '_get_client') as mock_client, patch.object(
            mod, '_sign_state_jwt', return_value='jwt-state-token'
        ), pytest.raises(RuntimeError, match='no redirect URL'):
            mock_client.return_value.create.return_value = session
            mod.authorize_toolkit(user, 'gmail', callback_url='https://app.myah.dev/cb?state=jwt-state-token')


# ── TestIntegrationsRoutes ────────────────────────────────────────────────────


class TestIntegrationsRoutes:
    """FastAPI TestClient tests for the integrations router endpoints."""

    @pytest.fixture(autouse=True)
    def _setup_app(self):
        """Build a minimal FastAPI app with the integrations router and overrides."""
        from open_webui.routers.integrations import router as integrations_router
        from open_webui.utils.auth import get_verified_user

        self.app = FastAPI()
        self.app.include_router(integrations_router, prefix='/api/v1/integrations')

        self.app.dependency_overrides[get_verified_user] = lambda: _MOCK_USER
        self.client = TestClient(self.app)
        yield
        self.app.dependency_overrides.clear()

    # ── GET /api/v1/integrations ──────────────────────────────────────────

    def test_list_integrations_returns_200(self):
        """GET /api/v1/integrations returns 200 with items/next_cursor."""
        with patch('open_webui.routers.integrations.composio_utils') as mock_cu:
            mock_cu.list_toolkits.return_value = {
                'items': [{'slug': 'gmail', 'name': 'Gmail'}],
                'next_cursor': None,
            }
            resp = self.client.get('/api/v1/integrations')

        assert resp.status_code == 200
        body = resp.json()
        assert 'items' in body
        assert 'next_cursor' in body

    # ── GET /api/v1/integrations/catalog ───────────────────────────────────

    def test_get_catalog_returns_200(self):
        """GET /api/v1/integrations/catalog returns 200 with a list."""
        with patch('open_webui.routers.integrations.composio_utils') as mock_cu:
            mock_cu.list_catalog.return_value = [
                {'slug': 'gmail', 'name': 'Gmail'},
                {'slug': 'github', 'name': 'GitHub'},
            ]
            resp = self.client.get('/api/v1/integrations/catalog')

        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)
        assert len(body) == 2

    # ── POST /api/v1/integrations/{toolkit}/connect ───────────────────────

    def test_connect_toolkit_returns_redirect_url(self):
        """POST /api/v1/integrations/gmail/connect returns 200 with redirect_url.

        register_with_agent is scheduled as a FastAPI background task so the
        response returns immediately. After TestClient drains the response,
        the background task runs and register_with_agent is called.
        """
        with patch('open_webui.routers.integrations.composio_utils') as mock_cu, patch(
            'open_webui.routers.integrations._sign_state', return_value='jwt-state'
        ):
            mock_cu.register_with_agent = AsyncMock(return_value=True)
            mock_cu.authorize_toolkit.return_value = 'https://auth.example.com/oauth'
            resp = self.client.post(
                '/api/v1/integrations/gmail/connect',
                json={'alias': None, 'callback_url': None},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body['redirect_url'] == 'https://auth.example.com/oauth'
        mock_cu.register_with_agent.assert_awaited_once()

    def test_connect_toolkit_calls_authorize_before_registration_completes(self):
        """authorize_toolkit MUST be called before register_with_agent finishes.

        The Connect endpoint computes the OAuth redirect URL via authorize_toolkit
        immediately, while register_with_agent is scheduled as a background task.
        In production this means the user sees the Composio modal in ~1s while
        the ~10s docker exec runs after the response is flushed. The TestClient
        always waits for background tasks to drain (Starlette ASGITransport
        artifact), so we can't time the response — but we CAN assert ordering.

        This test injects a sleep into register_with_agent and records the time
        each mock was entered. authorize_toolkit must enter BEFORE register_with_agent
        finishes — proving register_with_agent did not block the response path.
        """
        import asyncio
        import time

        timings = {}

        async def slow_register(_user):
            timings['register_started'] = time.perf_counter()
            await asyncio.sleep(0.3)
            timings['register_finished'] = time.perf_counter()
            return True

        def fast_authorize(*args, **kwargs):
            timings['authorize_called'] = time.perf_counter()
            return 'https://auth.example.com/oauth'

        with patch('open_webui.routers.integrations.composio_utils') as mock_cu, patch(
            'open_webui.routers.integrations._sign_state', return_value='jwt-state'
        ):
            mock_cu.register_with_agent = AsyncMock(side_effect=slow_register)
            mock_cu.authorize_toolkit.side_effect = fast_authorize

            resp = self.client.post(
                '/api/v1/integrations/gmail/connect',
                json={'alias': None, 'callback_url': None},
            )

        assert resp.status_code == 200
        assert resp.json()['redirect_url'] == 'https://auth.example.com/oauth'
        assert 'authorize_called' in timings, 'authorize_toolkit was never called'
        assert 'register_finished' in timings, 'background task never ran'
        assert timings['authorize_called'] < timings['register_finished'], (
            'authorize_toolkit was called AFTER register_with_agent finished — '
            'register_with_agent is not scheduled as a background task. '
            f"timings: {timings}"
        )

    def test_connect_toolkit_authorize_failure_returns_503(self):
        """POST connect surfaces a generic 503 when authorize_toolkit raises."""
        with patch('open_webui.routers.integrations.composio_utils') as mock_cu, patch(
            'open_webui.routers.integrations._sign_state', return_value='jwt-state'
        ):
            mock_cu.register_with_agent = AsyncMock(return_value=True)
            mock_cu.authorize_toolkit.side_effect = RuntimeError('any composio failure')
            resp = self.client.post(
                '/api/v1/integrations/twitter/connect',
                json={'alias': None, 'callback_url': None},
            )

        assert resp.status_code == 503
        detail = resp.json()['detail']
        assert 'twitter' in detail.lower()
        assert 'composio' not in detail.lower()
        assert 'dashboard' not in detail.lower()

    def test_connect_toolkit_ignores_malicious_callback_url(self):
        """body.callback_url=evil.com is IGNORED — server uses Origin allowlist instead.

        A malicious frontend (or XSS) could otherwise harvest the signed state
        JWT by pointing the OAuth callback at an attacker domain.
        """
        captured = {}

        def capture_callback(*args, **kwargs):
            captured['callback_url'] = kwargs.get('callback_url') or (args[3] if len(args) > 3 else None)
            return 'https://auth.example.com/oauth'

        with patch('open_webui.routers.integrations.composio_utils') as mock_cu, patch(
            'open_webui.routers.integrations._sign_state', return_value='jwt-state'
        ):
            mock_cu.register_with_agent = AsyncMock(return_value=True)
            mock_cu.authorize_toolkit.side_effect = capture_callback
            resp = self.client.post(
                '/api/v1/integrations/gmail/connect',
                json={'alias': None, 'callback_url': 'https://evil.attacker.com/?'},
                headers={'Origin': 'http://localhost:5173'},
            )

        assert resp.status_code == 200
        assert captured['callback_url'] is not None
        assert 'evil.attacker.com' not in captured['callback_url']
        assert captured['callback_url'].startswith('http://localhost:5173/api/v1/integrations/composio/callback?state=')

    def test_connect_toolkit_falls_back_to_prod_when_origin_unknown(self):
        """Unknown/missing Origin header falls back to https://app.myah.dev."""
        captured = {}

        def capture_callback(*args, **kwargs):
            captured['callback_url'] = kwargs.get('callback_url') or (args[3] if len(args) > 3 else None)
            return 'https://auth.example.com/oauth'

        with patch('open_webui.routers.integrations.composio_utils') as mock_cu, patch(
            'open_webui.routers.integrations._sign_state', return_value='jwt-state'
        ):
            mock_cu.register_with_agent = AsyncMock(return_value=True)
            mock_cu.authorize_toolkit.side_effect = capture_callback
            resp = self.client.post(
                '/api/v1/integrations/gmail/connect',
                json={'alias': None},
                headers={'Origin': 'https://unknown.host.example'},
            )

        assert resp.status_code == 200
        assert captured['callback_url'].startswith(
            'https://app.myah.dev/api/v1/integrations/composio/callback?state='
        )

    # ── GET /api/v1/integrations/composio/callback ─────────────────────────

    def test_callback_rejects_missing_state(self):
        """GET callback without state parameter returns 401."""
        resp = self.client.get('/api/v1/integrations/composio/callback', follow_redirects=False)
        assert resp.status_code == 401

    def test_callback_rejects_bad_state(self):
        """GET callback with invalid state JWT returns 401."""
        resp = self.client.get(
            '/api/v1/integrations/composio/callback?state=not-a-jwt',
            follow_redirects=False,
        )
        assert resp.status_code == 401

    def test_callback_valid_state_redirects(self):
        """GET callback with a valid state JWT redirects to /agent/integrations."""
        state = _make_state('test-user-id', 'gmail')
        with patch('open_webui.routers.integrations.WEBUI_SECRET_KEY', _SECRET):
            # Re-import _verify_state to pick up the patched secret.
            # Instead, we patch at the module level.
            from open_webui.routers import integrations as integ_mod

            original_key = integ_mod.WEBUI_SECRET_KEY
            integ_mod.WEBUI_SECRET_KEY = _SECRET
            try:
                resp = self.client.get(
                    f'/api/v1/integrations/composio/callback?status=success&state={state}',
                    follow_redirects=False,
                )
            finally:
                integ_mod.WEBUI_SECRET_KEY = original_key

        assert resp.status_code == 302
        assert '/agent/integrations?toast=connected:gmail' in resp.headers['location']

    def test_callback_logs_ca_id_owner_mismatch(self):
        """Mismatched ca_id owner is logged with ERROR but does NOT block the redirect.

        This is a defensive bind-check — no current code persists anything
        keyed on the callback's ca_id, so we don't 403. But probing must be
        visible in logs/Sentry for the moment a future change introduces a
        write that needs the binding.
        """
        from open_webui.routers import integrations as integ_mod

        state = _make_state(_MOCK_USER.id, 'gmail')
        original_key = integ_mod.WEBUI_SECRET_KEY
        integ_mod.WEBUI_SECRET_KEY = _SECRET
        try:
            with patch('open_webui.routers.integrations.composio_utils') as mock_cu, patch.object(
                integ_mod, 'logger'
            ) as mock_logger:
                mock_cu._get_client.return_value.connected_accounts.get.return_value = MagicMock(
                    user_id='other-user'
                )
                resp = self.client.get(
                    f'/api/v1/integrations/composio/callback'
                    f'?state={state}&status=success&connected_account_id=ca_belongs_to_other',
                    follow_redirects=False,
                )

            assert resp.status_code == 302
            error_calls = [c.args[0] for c in mock_logger.error.call_args_list]
            assert any('user_id mismatch' in msg for msg in error_calls), \
                f'expected mismatch log, got error calls: {error_calls}'
        finally:
            integ_mod.WEBUI_SECRET_KEY = original_key

    def test_callback_passes_when_ca_id_owner_matches(self):
        """Matched ca_id owner does not log an error — happy path."""
        from open_webui.routers import integrations as integ_mod

        state = _make_state(_MOCK_USER.id, 'gmail')
        original_key = integ_mod.WEBUI_SECRET_KEY
        integ_mod.WEBUI_SECRET_KEY = _SECRET
        try:
            with patch('open_webui.routers.integrations.composio_utils') as mock_cu, patch.object(
                integ_mod, 'logger'
            ) as mock_logger:
                mock_cu._get_client.return_value.connected_accounts.get.return_value = MagicMock(
                    user_id=_MOCK_USER.id
                )
                resp = self.client.get(
                    f'/api/v1/integrations/composio/callback'
                    f'?state={state}&status=success&connected_account_id=ca_owned_by_mock_user',
                    follow_redirects=False,
                )

            assert resp.status_code == 302
            assert 'connected:gmail' in resp.headers['location']
            error_calls = [c.args[0] for c in mock_logger.error.call_args_list]
            assert not any('user_id mismatch' in msg for msg in error_calls), \
                'should NOT log mismatch when owner matches'
        finally:
            integ_mod.WEBUI_SECRET_KEY = original_key

    def test_callback_error_status_toasts(self):
        """GET callback with status!=success shows error toast."""
        state = _make_state('test-user-id', 'slack')
        from open_webui.routers import integrations as integ_mod

        original_key = integ_mod.WEBUI_SECRET_KEY
        integ_mod.WEBUI_SECRET_KEY = _SECRET
        try:
            resp = self.client.get(
                f'/api/v1/integrations/composio/callback?status=failed&state={state}',
                follow_redirects=False,
            )
        finally:
            integ_mod.WEBUI_SECRET_KEY = original_key

        assert resp.status_code == 302
        assert '/agent/integrations?toast=error:slack' in resp.headers['location']

    # ── DELETE /api/v1/integrations/{toolkit}/{ca_id} ───────────────────────

    def test_disconnect_returns_deleted(self):
        """DELETE /api/v1/integrations/gmail/ca_123 returns 200 with deleted:true."""
        with patch('open_webui.routers.integrations.composio_utils') as mock_cu:
            mock_cu.disconnect.return_value = True
            resp = self.client.delete('/api/v1/integrations/gmail/ca_123')

        assert resp.status_code == 200
        assert resp.json() == {'deleted': True}

    def test_disconnect_returns_not_deleted(self):
        """DELETE returns deleted:false when SDK call fails."""
        with patch('open_webui.routers.integrations.composio_utils') as mock_cu:
            mock_cu.disconnect.return_value = False
            resp = self.client.delete('/api/v1/integrations/gmail/ca_456')

        assert resp.status_code == 200
        assert resp.json() == {'deleted': False}

    def test_disconnect_returns_403_for_cross_tenant_ca_id(self):
        """DELETE with another user's ca_id returns 403, never reaches Composio delete."""
        from open_webui.utils.composio import CrossTenantAccessError

        with patch('open_webui.routers.integrations.composio_utils') as mock_cu:
            mock_cu.CrossTenantAccessError = CrossTenantAccessError
            mock_cu.disconnect.side_effect = CrossTenantAccessError('not your connected account')
            resp = self.client.delete('/api/v1/integrations/gmail/ca_belongs_to_someone_else')

        assert resp.status_code == 403
        assert 'not your' in resp.json()['detail'].lower()

    # ── PATCH /api/v1/integrations/{toolkit}/{ca_id} ───────────────────────

    def test_update_alias_returns_updated(self):
        """PATCH /api/v1/integrations/gmail/ca_123 returns 200 with updated:true."""
        with patch('open_webui.routers.integrations.composio_utils') as mock_cu:
            mock_cu.update_alias.return_value = True
            resp = self.client.patch(
                '/api/v1/integrations/gmail/ca_123',
                json={'alias': 'my-work-gmail'},
            )

        assert resp.status_code == 200
        assert resp.json() == {'updated': True}

    def test_update_alias_returns_403_for_cross_tenant_ca_id(self):
        """PATCH with another user's ca_id returns 403, never reaches Composio update."""
        from open_webui.utils.composio import CrossTenantAccessError

        with patch('open_webui.routers.integrations.composio_utils') as mock_cu:
            mock_cu.CrossTenantAccessError = CrossTenantAccessError
            mock_cu.update_alias.side_effect = CrossTenantAccessError('not your connected account')
            resp = self.client.patch(
                '/api/v1/integrations/gmail/ca_belongs_to_someone_else',
                json={'alias': 'sneaky-rename'},
            )

        assert resp.status_code == 403
        assert 'not your' in resp.json()['detail'].lower()

    # ── POST /api/v1/integrations/refresh-mcp ──────────────────────────────

    def test_refresh_mcp_returns_registered(self):
        """POST /api/v1/integrations/refresh-mcp returns 200 with registered:true."""
        with patch('open_webui.routers.integrations.composio_utils') as mock_cu:
            mock_cu.register_with_agent = AsyncMock(return_value=True)
            resp = self.client.post('/api/v1/integrations/refresh-mcp')

        assert resp.status_code == 200
        assert resp.json() == {'registered': True}

    def test_refresh_mcp_returns_not_registered_on_failure(self):
        """POST /api/v1/integrations/refresh-mcp returns registered:false when registration fails."""
        with patch('open_webui.routers.integrations.composio_utils') as mock_cu:
            mock_cu.register_with_agent = AsyncMock(return_value=False)
            resp = self.client.post('/api/v1/integrations/refresh-mcp')

        assert resp.status_code == 200
        assert resp.json() == {'registered': False}


# ── TestNameProtection ────────────────────────────────────────────────────────


class TestNameProtection:
    """Regression tests for the 409 guard that reserves the 'composio' MCP name."""

    @pytest.fixture(autouse=True)
    def _setup_app(self):
        """Build a minimal FastAPI app with the agent_config router."""
        from open_webui.routers.agent_config import router as agent_config_router
        from open_webui.utils.auth import get_verified_user

        self.app = FastAPI()
        self.app.include_router(agent_config_router, prefix='/api/v1/agent')
        self.app.dependency_overrides[get_verified_user] = lambda: _MOCK_USER
        self.client = TestClient(self.app)
        yield
        self.app.dependency_overrides.clear()

    def test_composio_name_returns_409(self):
        """POST /api/v1/agent/mcp with name=composio returns 409."""
        with patch('open_webui.routers.agent_config.web_call', new_callable=AsyncMock) as mock_wc:
            # The 409 should fire before web_call is ever reached.
            resp = self.client.post('/api/v1/agent/mcp', json={'name': 'composio', 'url': 'http://localhost:3000'})

        assert resp.status_code == 409
        assert 'reserved' in resp.json()['detail'].lower()
        mock_wc.assert_not_called()

    def test_other_names_pass_through(self):
        """POST /api/v1/agent/mcp with name!=composio does NOT return 409."""
        with patch('open_webui.routers.agent_config.web_call', new_callable=AsyncMock) as mock_wc, patch(
            'open_webui.routers.agent_config._ensure_feature_enabled'
        ):
            mock_wc.return_value = {'status': 200, 'body': {'ok': True}, 'headers': {}}
            resp = self.client.post(
                '/api/v1/agent/mcp', json={'name': 'mygithub', 'url': 'http://localhost:3000'}
            )

        # Should not be 409 — could be 200 or another error depending on web_call mock.
        assert resp.status_code != 409


# ── TestUserDeleteCleanup ────────────────────────────────────────────────────


class TestUserDeleteCleanup:
    """Verify that deleting a user also removes their integration session."""

    def test_delete_user_removes_integration_session(self):
        """Users.delete_user_by_id must call IntegrationSessions.delete_by_user_id
        and revoke_all_for_user_sync for Composio cleanup."""
        from open_webui.models.users import Users

        mock_is = MagicMock()
        mock_is.delete_by_user_id.return_value = 1

        with patch(
            'open_webui.models.integration_session.IntegrationSessions', mock_is
        ), patch(
            'open_webui.utils.composio.revoke_all_for_user_sync', return_value=0
        ) as mock_revoke, patch('open_webui.models.users.Chats') as mock_chats, patch(
            'open_webui.models.users.Groups'
        ) as mock_groups, patch(
            'open_webui.models.users.get_db_context'
        ) as mock_db_ctx:
            mock_chats.delete_chats_by_user_id.return_value = True
            mock_groups.remove_user_from_all_groups.return_value = None

            mock_session = MagicMock()
            mock_db_ctx.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_db_ctx.return_value.__exit__ = MagicMock(return_value=False)

            mock_session.query.return_value.filter_by.return_value.delete.return_value = 1

            result = Users.delete_user_by_id('user-to-delete')

        assert result is True
        mock_is.delete_by_user_id.assert_called_once_with('user-to-delete')
        mock_revoke.assert_called_once_with('user-to-delete')