# Tests for the seed-on-first-spawn path in open_webui/routers/containers.py.
# Uses the importlib stub pattern to load _start_container without triggering
# Docker, DB, or Redis infrastructure.

import asyncio
import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel, ConfigDict


# ── Minimal ContainerModel that satisfies FastAPI route response annotations ─


class _ContainerModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str = 'test-id'
    user_id: str = 'user-abc'
    container_id: Optional[str] = None
    container_name: Optional[str] = None
    host_port: Optional[int] = None
    vite_port: Optional[int] = None
    vnc_port: Optional[int] = None
    status: str = 'running'
    created_at: int = 0
    last_active: int = 0


def _load_containers_module():
    """Load open_webui/routers/containers.py with all heavy deps stubbed."""

    def _make(name, **attrs):
        m = ModuleType(name)
        for k, v in attrs.items():
            setattr(m, k, v)
        return m

    # ── stub docker ───────────────────────────────────────────────────────────
    docker_errors = _make(
        'docker.errors',
        APIError=Exception,
        DockerException=Exception,
        NotFound=Exception,
    )
    docker_mod = _make(
        'docker',
        errors=docker_errors,
        from_env=MagicMock(),
        DockerClient=MagicMock(),
    )
    docker_mod.errors = docker_errors

    # ── stub httpx ────────────────────────────────────────────────────────────
    httpx_mod = _make(
        'httpx',
        AsyncClient=MagicMock(),
        ConnectError=Exception,
        TimeoutException=Exception,
    )

    # ── stub open_webui internals ─────────────────────────────────────────────
    internal_db = _make('open_webui.internal.db', get_session=MagicMock())
    constants_mod = _make(
        'open_webui.constants',
        ERROR_MESSAGES=SimpleNamespace(NOT_FOUND='not found', ACCESS_PROHIBITED='forbidden'),
    )

    _sample_record = _ContainerModel(status='running', created_at=0, last_active=0)
    containers_db = MagicMock()
    containers_db.get_by_user_id = MagicMock(return_value=None)
    containers_db.update_status = MagicMock(return_value=_sample_record)
    containers_db.create = MagicMock(return_value=_sample_record)
    containers_db.touch = MagicMock()
    containers_mod = _make(
        'open_webui.models.containers',
        ContainerModel=_ContainerModel,
        Containers=containers_db,
    )

    user_model_cls = MagicMock()
    users_get = MagicMock()
    users_mod = _make(
        'open_webui.models.users',
        UserModel=user_model_cls,
        Users=SimpleNamespace(
            get_user_by_id=users_get,
            update_user_by_id=MagicMock(),
        ),
    )

    honcho_service_mock = MagicMock()
    honcho_service_mock.get_or_provision = MagicMock(
        return_value=SimpleNamespace(api_key='', workspace_id='', provisioned=False)
    )
    honcho_mod = _make('open_webui.services.honcho', honcho_service=honcho_service_mock)

    auth_mod = _make(
        'open_webui.utils.auth',
        get_verified_user=MagicMock(),
        get_admin_user=MagicMock(),
    )

    # ── stub web_call (the seeding call — Wave 3c migrated path) ────────────
    aux_call_mock = AsyncMock()
    hermes_web_mod = _make(
        'open_webui.utils.hermes_web',
        web_call=aux_call_mock,
    )
    # agent_proxy is still imported by containers.py for normalize_catalog_models
    # via the lazy import inside _build_catalog_map.
    agent_proxy_mod = _make(
        'open_webui.utils.agent_proxy',
        AUX_ALLOWED_TASKS={'title_generation', 'follow_up_generation'},
        normalize_catalog_models=lambda raw: [m['id'] if isinstance(m, dict) else m for m in (raw or [])],
    )

    # ── stub config (resolve helpers) ────────────────────────────────────────
    def _resolve_aux_default_stub(provider, task, *, catalog=None):
        _AUX_DEFAULT = {
            'openrouter': 'google/gemini-3-flash-preview',
            'anthropic': 'claude-haiku-4-5-20251001',
        }
        _AUX_VISION = {'openrouter': 'google/gemini-3-flash-preview'}
        _INCAPABLE = frozenset({'deepseek'})
        if task == 'vision':
            if provider in _INCAPABLE:
                return None
            return _AUX_VISION.get(provider) or _AUX_DEFAULT.get(provider)
        return _AUX_DEFAULT.get(provider)

    config_mod = _make(
        'open_webui.config',
        AUX_DEFAULT_FALLBACKS={'openrouter': 'google/gemini-3-flash-preview'},
        AUX_VISION_FALLBACKS={'openrouter': 'google/gemini-3-flash-preview'},
        AUX_VISION_INCAPABLE=frozenset({'deepseek'}),
        AUX_DEFAULT_TASKS=frozenset({'title_generation', 'follow_up_generation'}),
        _resolve_aux_default=_resolve_aux_default_stub,
    )

    # ── telemetry stub (optional import in containers.py) ────────────────────
    telemetry_mod = _make(
        'open_webui.utils.telemetry.myah_metrics',
        record_container_startup=None,
    )
    telemetry_parent = _make('open_webui.utils.telemetry')

    for mod in (
        docker_mod,
        docker_errors,
        httpx_mod,
        internal_db,
        constants_mod,
        containers_mod,
        users_mod,
        honcho_mod,
        auth_mod,
        agent_proxy_mod,
        hermes_web_mod,
        config_mod,
        telemetry_parent,
        telemetry_mod,
    ):
        sys.modules[mod.__name__] = mod

    router_path = Path(__file__).resolve().parent.parent.parent.parent.parent / 'routers' / 'containers.py'
    spec = importlib.util.spec_from_file_location('open_webui.routers.containers', router_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules['open_webui.routers.containers'] = module
    spec.loader.exec_module(module)

    # Expose test handles
    module._test_aux_call = aux_call_mock
    module._test_users_get = users_get
    module._test_containers_db = containers_db
    return module


@pytest.fixture
def containers_mod():
    mod = _load_containers_module()
    mod._test_aux_call.reset_mock()
    mod._test_users_get.reset_mock()
    return mod


def _fake_user(user_id='user-abc'):
    return SimpleNamespace(id=user_id, role='user', email='u@myah.dev')


# ── helpers ───────────────────────────────────────────────────────────────────


def _make_start_info(adopt: bool, host_port: int = 8642) -> dict:
    """Build a fake info dict as returned by _start_container_sync."""
    return {
        'container_id': 'cid-123',
        'name': f'myah-agent-user-abc',
        'host_port': host_port,
        'vite_port': 5174,
        'vnc_port': 5900,
        'needs_health_check': True,
        'adopt': adopt,
    }


# ── tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_container_first_spawn_seeds_aux_defaults(containers_mod):
    """adopt=False + healthy → seed_aux_defaults logic fires for the user's provider."""
    fake_user = _fake_user()
    containers_mod._test_users_get.return_value = fake_user

    # The seed logic calls web_call: GET /api/config, GET /api/plugins/myah-admin/providers,
    # PUT /api/config (Wave 3c migration — paths now go through hermes dashboard).
    async def _aux_side_effect(user, method, path, **kwargs):
        if method == 'GET' and path == '/api/plugins/myah-admin/config':
            # Return active model so the seed logic extracts 'openrouter' as provider
            return {
                'status': 200,
                'body': {'model': 'openrouter/google/gemini-3-flash-preview'},
                'headers': {},
            }
        if method == 'GET' and '/providers' in path:
            return {
                'status': 200,
                'body': {'openrouter': {'curated_models': ['google/gemini-3-flash-preview']}},
                'headers': {},
            }
        if method == 'PUT':
            return {'status': 200, 'body': {'ok': True}, 'headers': {}}
        return {'status': 200, 'body': {}, 'headers': {}}

    containers_mod._test_aux_call.side_effect = _aux_side_effect

    new_record = MagicMock()
    new_record.host_port = 8642

    with (
        patch.object(containers_mod.asyncio, 'to_thread', new=_fake_to_thread(containers_mod)),
        patch(
            'open_webui.routers.containers._start_container_sync',
            return_value=_make_start_info(adopt=False),
        ),
        patch(
            'open_webui.routers.containers._wait_for_ready',
            new=AsyncMock(return_value=(True, {'checks': {'llm_credentials': True}})),
        ),
    ):
        containers_mod.Containers.update_status.return_value = new_record
        record = await containers_mod._start_container('user-abc', MagicMock())

    # Seeding must have made at least one web_call (the GET /providers call)
    call_paths = [c.args[2] for c in containers_mod._test_aux_call.await_args_list]
    assert any('/providers' in p for p in call_paths), f'Expected a GET /providers call for seeding; got: {call_paths}'
    # And at least one PUT for writing the defaults
    patch_calls = [c for c in containers_mod._test_aux_call.await_args_list if c.args[1] == 'PUT']
    assert len(patch_calls) >= 1, 'Expected at least one PUT call to seed aux defaults'


@pytest.mark.asyncio
async def test_container_adopt_does_not_seed(containers_mod):
    """adopt=True → seed logic must NOT fire (existing containers keep their config)."""
    containers_mod._test_aux_call.side_effect = None
    containers_mod._test_aux_call.return_value = {'status': 200, 'body': {}, 'headers': {}}

    adopted_record = MagicMock()
    adopted_record.host_port = 8642

    with (
        patch.object(containers_mod.asyncio, 'to_thread', new=_fake_to_thread(containers_mod)),
        patch(
            'open_webui.routers.containers._start_container_sync',
            return_value=_make_start_info(adopt=True),
        ),
        patch(
            'open_webui.routers.containers._wait_for_ready',
            new=AsyncMock(return_value=(True, None)),
        ),
    ):
        containers_mod.Containers.update_status.return_value = adopted_record
        record = await containers_mod._start_container('user-abc', MagicMock())

    # No web_call should have been made at all
    containers_mod._test_aux_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_seed_dict_form_model_extracts_provider(containers_mod):
    """Bug #2: when config 'model' is a dict {provider, name, ...}, provider is extracted correctly."""
    fake_user = _fake_user()
    containers_mod._test_users_get.return_value = fake_user

    async def _aux_side_effect(user, method, path, **kwargs):
        if method == 'GET' and path == '/api/plugins/myah-admin/config':
            # Dict-form model as written by PR 1c Appendix A
            return {
                'status': 200,
                'body': {
                    'model': {'name': 'google/gemini-3-flash-preview', 'provider': 'openrouter'},
                    'auxiliary': {},
                },
                'headers': {},
            }
        if method == 'GET' and '/providers' in path:
            return {
                'status': 200,
                'body': {'openrouter': {'curated_models': ['google/gemini-3-flash-preview']}},
                'headers': {},
            }
        if method == 'PUT':
            return {'status': 200, 'body': {'ok': True}, 'headers': {}}
        return {'status': 200, 'body': {}, 'headers': {}}

    containers_mod._test_aux_call.side_effect = _aux_side_effect

    # Call _seed_aux_defaults_for_user directly to test provider extraction
    await containers_mod._seed_aux_defaults_for_user('user-abc')

    # Should have proceeded to seed (GET /providers + PUT)
    call_paths = [c.args[2] for c in containers_mod._test_aux_call.await_args_list]
    assert any('/providers' in p for p in call_paths), (
        f'Dict-form provider extraction failed — no /providers call; calls: {call_paths}'
    )
    patch_calls = [c for c in containers_mod._test_aux_call.await_args_list if c.args[1] == 'PUT']
    assert len(patch_calls) >= 1, 'Expected PUT after dict-form provider extraction'


@pytest.mark.asyncio
async def test_seed_skipped_when_aux_already_configured(containers_mod):
    """Bug #5: if any AUX_DEFAULT_TASKS task already has a provider, re-seed is skipped."""
    fake_user = _fake_user()
    containers_mod._test_users_get.return_value = fake_user

    async def _aux_side_effect(user, method, path, **kwargs):
        if method == 'GET' and path == '/api/plugins/myah-admin/config':
            # Config already has per-task aux entries set
            return {
                'status': 200,
                'body': {
                    'model': 'openrouter/google/gemini-3-flash-preview',
                    'auxiliary': {
                        'title_generation': {
                            'provider': 'openrouter',
                            'model': 'google/gemini-3-flash-preview',
                        }
                    },
                },
                'headers': {},
            }
        return {'status': 200, 'body': {}, 'headers': {}}

    containers_mod._test_aux_call.side_effect = _aux_side_effect

    await containers_mod._seed_aux_defaults_for_user('user-abc')

    # No /providers fetch or PUT — guard should have short-circuited
    call_paths = [c.args[2] for c in containers_mod._test_aux_call.await_args_list]
    assert not any('/providers' in p for p in call_paths), (
        f'Re-seed guard failed — /providers was still called: {call_paths}'
    )
    patch_calls = [c for c in containers_mod._test_aux_call.await_args_list if c.args[1] == 'PUT']
    assert len(patch_calls) == 0, f'Re-seed guard failed — PUT was issued: {patch_calls}'


@pytest.mark.asyncio
async def test_seed_aux_defaults_uses_plugin_config_path(containers_mod):
    """Regression: aux-seeding must call /api/plugins/myah-admin/config, not /api/config.

    PR 3 (Phase 7.7 plugin migration) swapped these paths. If the aux-seeding
    hot path ever drifts back to the native /api/config path, this test
    catches it before deploy.
    """
    fake_user = _fake_user()
    containers_mod._test_users_get.return_value = fake_user

    async def _aux_side_effect(user, method, path, **kwargs):
        if method == 'GET' and path == '/api/plugins/myah-admin/config':
            return {
                'status': 200,
                'body': {'model': 'openrouter/google/gemini-3-flash-preview', 'auxiliary': {}},
                'headers': {},
            }
        if method == 'GET' and '/providers' in path:
            return {
                'status': 200,
                'body': {'openrouter': {'curated_models': ['google/gemini-3-flash-preview']}},
                'headers': {},
            }
        if method == 'PUT' and path == '/api/plugins/myah-admin/config':
            return {'status': 200, 'body': {'ok': True}, 'headers': {}}
        return {'status': 200, 'body': {}, 'headers': {}}

    containers_mod._test_aux_call.side_effect = _aux_side_effect

    await containers_mod._seed_aux_defaults_for_user('user-abc')

    paths = {c.args[2] for c in containers_mod._test_aux_call.await_args_list}
    # Plugin-namespace path must have been called for both GET and PUT
    assert '/api/plugins/myah-admin/config' in paths, (
        f'Expected aux-seeding to call /api/plugins/myah-admin/config; got: {paths}'
    )
    # Native path must not be called (regression gate)
    assert '/api/config' not in paths, (
        f'Regression: aux-seeding hit the native /api/config path; got: {paths}'
    )


# ── helper: to_thread that runs sync lambdas inline ─────────────────────────


def _fake_to_thread(containers_mod):
    """Return a coroutine-based to_thread replacement that runs sync callables inline."""

    async def _to_thread(fn, *args, **kwargs):
        result = fn(*args, **kwargs)
        return result

    return _to_thread


# ── PR 3: Container env-var injection tests ───────────────────────────────
"""Tests for container env-var injection (PR 3 Task 3 regression gate).

Verifies that MYAH_PLATFORM_BASE_URL and MYAH_PLATFORM_BEARER are present in
the environment dict passed to the Docker containers.run() call so that the
Hermes media adapter can fetch attachment bytes back from the platform.
"""

from unittest.mock import MagicMock, patch

from docker.errors import NotFound


class TestContainerEnvInjection:
    """Ensure per-user agent containers receive the media-fetch env vars."""

    def test_container_env_includes_myah_platform_base_and_bearer(self):
        """MYAH_PLATFORM_BASE_URL and MYAH_PLATFORM_BEARER must be injected."""
        from open_webui.routers.containers import _start_container_sync

        captured_env = {}

        def fake_containers_run(*args, **kwargs):
            captured_env.update(kwargs.get('environment', {}))
            mock_container = MagicMock()
            mock_container.id = 'fake-container-id'
            return mock_container

        mock_docker_client = MagicMock()
        mock_docker_client.containers.run.side_effect = fake_containers_run
        mock_docker_client.volumes.list.return_value = []
        mock_docker_client.volumes.create.return_value = MagicMock()
        # No pre-existing container — triggers the NotFound path
        mock_docker_client.containers.get.side_effect = NotFound('not found')

        with (
            patch('open_webui.routers.containers._docker_client', return_value=mock_docker_client),
            patch(
                'open_webui.routers.containers._free_port',
                side_effect=[9001, 9002, 9003, 9004, 9005],
            ),
            patch('open_webui.routers.containers.Containers') as mock_containers_model,
            patch('open_webui.routers.containers.AGENT_BEARER_TOKEN', 'test-bearer'),
            patch('open_webui.routers.containers.PLATFORM_WEBHOOK_HOST', 'host.docker.internal'),
            patch('open_webui.routers.containers.PLATFORM_PORT', '8082'),
        ):
            mock_containers_model.update_status.return_value = None

            _start_container_sync(
                user_id='user-test-1',
                honcho_api_key='hk-1',
                honcho_workspace_id='ws-1',
            )

        assert 'MYAH_PLATFORM_BASE_URL' in captured_env, 'MYAH_PLATFORM_BASE_URL missing from container environment'
        assert 'MYAH_PLATFORM_BEARER' in captured_env, 'MYAH_PLATFORM_BEARER missing from container environment'
        assert captured_env['MYAH_PLATFORM_BASE_URL'] == 'http://host.docker.internal:8082'
        assert captured_env['MYAH_PLATFORM_BEARER'] == 'test-bearer'

    def test_container_env_includes_myah_home_chat_disabled(self):
        """B1 regression — suppress the gateway "no home channel" first-message warning.

        Upstream's gateway/run.py:6802 calls _home_target_env_var('myah') which
        resolves to the plugin's PlatformEntry.cron_deliver_env_var. The plugin
        registers cron_deliver_env_var='MYAH_HOME_CHAT' (see
        plugins/myah-hermes-plugin/.../myah_platform/__init__.py:344), so the
        registry-resolved env var that suppresses the warning is MYAH_HOME_CHAT.

        Setting only MYAH_HOME_CHANNEL='disabled' (as PR #109 did) leaves the
        warning firing on every fresh chat because the gateway never reads
        MYAH_HOME_CHANNEL — it reads whatever the registry returns.

        MYAH_HOME_CHANNEL='disabled' is kept as a defensive fallback for the
        path where plugin discovery fails and _resolve_home_env_var falls back
        to the legacy hardcoded name.
        """
        from open_webui.routers.containers import _start_container_sync

        captured_env = {}

        def fake_containers_run(*args, **kwargs):
            captured_env.update(kwargs.get('environment', {}))
            mock_container = MagicMock()
            mock_container.id = 'fake-container-id'
            return mock_container

        mock_docker_client = MagicMock()
        mock_docker_client.containers.run.side_effect = fake_containers_run
        mock_docker_client.volumes.list.return_value = []
        mock_docker_client.volumes.create.return_value = MagicMock()
        mock_docker_client.containers.get.side_effect = NotFound('not found')

        with (
            patch('open_webui.routers.containers._docker_client', return_value=mock_docker_client),
            patch(
                'open_webui.routers.containers._free_port',
                side_effect=[9001, 9002, 9003, 9004, 9005],
            ),
            patch('open_webui.routers.containers.Containers') as mock_containers_model,
            patch('open_webui.routers.containers.AGENT_BEARER_TOKEN', 'test-bearer'),
            patch('open_webui.routers.containers.PLATFORM_WEBHOOK_HOST', 'host.docker.internal'),
            patch('open_webui.routers.containers.PLATFORM_PORT', '8082'),
        ):
            mock_containers_model.update_status.return_value = None

            _start_container_sync(
                user_id='user-b1-regression',
                honcho_api_key='hk-1',
                honcho_workspace_id='ws-1',
            )

        # Primary: registry-resolved env var name (plugin's cron_deliver_env_var).
        # Without this set, the gateway's first-message warning fires.
        assert captured_env.get('MYAH_HOME_CHAT') == 'disabled', (
            'MYAH_HOME_CHAT must be set to "disabled" to suppress the gateway '
            '"No home channel is set" warning. This is the registry-resolved env '
            "var (plugin's PlatformEntry.cron_deliver_env_var); PR #109 set only "
            'MYAH_HOME_CHANNEL by mistake — that var is never read at runtime.'
        )
        # Defensive fallback: legacy hardcoded name. Kept so the suppression
        # survives if plugin discovery ever fails and _resolve_home_env_var
        # falls back to a hardcoded lookup table.
        assert captured_env.get('MYAH_HOME_CHANNEL') == 'disabled', (
            'MYAH_HOME_CHANNEL must remain set as a defensive fallback for the '
            'path where plugin discovery fails and the registry resolution chain '
            'cannot find cron_deliver_env_var.'
        )


# ── Webhook host resolution + MYAH_PLATFORM_NETWORK regression gate ─────────


def test_platform_webhook_host_falls_back_to_docker_host_when_no_explicit(monkeypatch):
    """When MYAH_PLATFORM_WEBHOOK_HOST is unset, fall back to _detect_docker_host()."""
    monkeypatch.delenv('MYAH_PLATFORM_WEBHOOK_HOST', raising=False)
    import importlib
    from open_webui.routers import containers

    importlib.reload(containers)
    assert containers.PLATFORM_WEBHOOK_HOST in ('host.docker.internal', '172.17.0.1')


def test_platform_webhook_host_explicit_override_wins(monkeypatch):
    """MYAH_PLATFORM_WEBHOOK_HOST takes precedence over docker-host detection."""
    monkeypatch.setenv('MYAH_PLATFORM_WEBHOOK_HOST', 'custom.example.com')
    import importlib
    from open_webui.routers import containers

    importlib.reload(containers)
    assert containers.PLATFORM_WEBHOOK_HOST == 'custom.example.com'


def test_platform_network_env_var_is_unused(monkeypatch):
    """Regression gate: MYAH_PLATFORM_NETWORK was a half-feature that caused the
    2026-04-30 incident (PR #71 / #72). It has been removed from containers.py.
    Setting the env var must have no effect on PLATFORM_WEBHOOK_HOST and no
    effect on the spawn-side container.run kwargs.

    See docs/gotchas/agent-platform-network-isolation.md (class 13).
    """
    from unittest.mock import MagicMock, patch

    from docker.errors import NotFound

    monkeypatch.setenv('MYAH_PLATFORM_NETWORK', 'should-be-ignored')
    monkeypatch.delenv('MYAH_PLATFORM_WEBHOOK_HOST', raising=False)

    # 1) Module-level resolution: PLATFORM_WEBHOOK_HOST must NOT become 'platform'.
    import importlib
    from open_webui.routers import containers

    importlib.reload(containers)
    assert containers.PLATFORM_WEBHOOK_HOST != 'platform', (
        f'MYAH_PLATFORM_NETWORK leaked into PLATFORM_WEBHOOK_HOST resolution '
        f'(got {containers.PLATFORM_WEBHOOK_HOST!r}). The env var should be unused.'
    )
    assert containers.PLATFORM_WEBHOOK_HOST in ('host.docker.internal', '172.17.0.1')

    # 2) Spawn-side: client.containers.run must NOT be called with network=...
    captured_kwargs = {}

    def fake_containers_run(*args, **kwargs):
        captured_kwargs.update(kwargs)
        mock_container = MagicMock()
        mock_container.id = 'fake-container-id'
        return mock_container

    mock_docker_client = MagicMock()
    mock_docker_client.containers.run.side_effect = fake_containers_run
    mock_docker_client.volumes.list.return_value = []
    mock_docker_client.volumes.create.return_value = MagicMock()
    mock_docker_client.containers.get.side_effect = NotFound('not found')

    with (
        patch('open_webui.routers.containers._docker_client', return_value=mock_docker_client),
        patch(
            'open_webui.routers.containers._free_port',
            side_effect=[9001, 9002, 9003, 9004, 9005],
        ),
        patch('open_webui.routers.containers.Containers') as mock_containers_model,
        patch('open_webui.routers.containers.AGENT_BEARER_TOKEN', 'test-bearer'),
        patch('open_webui.routers.containers.PLATFORM_WEBHOOK_HOST', 'host.docker.internal'),
        patch('open_webui.routers.containers.PLATFORM_PORT', '8080'),
    ):
        mock_containers_model.update_status.return_value = None
        containers._start_container_sync(
            user_id='regression-test-user',
            honcho_api_key='hk-1',
            honcho_workspace_id='ws-1',
        )

    assert 'network' not in captured_kwargs, (
        f'client.containers.run was called with network={captured_kwargs.get("network")!r} '
        f'despite MYAH_PLATFORM_NETWORK being a removed half-feature. The env var should '
        f'have no effect on the spawn path.'
    )


# ── Phase 7.2: MYAH_AGENT_IMAGE_OVERRIDES (canary mechanism) ─────────────


class TestImageOverrideParser:
    """``_parse_image_overrides`` must be defensive against malformed input
    — a bad env var must NEVER take down the spawner."""

    def test_empty_string_returns_empty_dict(self):
        from open_webui.routers.containers import _parse_image_overrides

        assert _parse_image_overrides('') == {}

    def test_single_pair_parsed(self):
        from open_webui.routers.containers import _parse_image_overrides

        assert _parse_image_overrides('user-abc=myah/agent-stock:abc123') == {
            'user-abc': 'myah/agent-stock:abc123',
        }

    def test_multiple_pairs_parsed(self):
        from open_webui.routers.containers import _parse_image_overrides

        out = _parse_image_overrides('user-a=img1,user-b=img2:tag,user-c=ghcr.io/org/img:sha-123')
        assert out == {
            'user-a': 'img1',
            'user-b': 'img2:tag',
            'user-c': 'ghcr.io/org/img:sha-123',
        }

    def test_whitespace_around_tokens_is_stripped(self):
        """Operators may add whitespace when editing the env var. We
        normalize so a stray space doesn't silently break the override."""
        from open_webui.routers.containers import _parse_image_overrides

        assert _parse_image_overrides('  user-a = img1 , user-b=img2 ') == {'user-a': 'img1', 'user-b': 'img2'}

    def test_empty_entries_ignored(self):
        """Trailing commas, double-commas, and leading-comma artifacts
        from copy/paste editing must not crash the parser."""
        from open_webui.routers.containers import _parse_image_overrides

        assert _parse_image_overrides(',user-a=img1,,user-b=img2,') == {
            'user-a': 'img1',
            'user-b': 'img2',
        }

    def test_malformed_entry_skipped_others_kept(self):
        """A single bad entry must not invalidate the rest of the
        override list. The spawner needs to keep working even if the
        operator typo'd one line."""
        from open_webui.routers.containers import _parse_image_overrides

        assert _parse_image_overrides('user-a=img1,not-a-valid-entry,user-b=img2') == {
            'user-a': 'img1',
            'user-b': 'img2',
        }

    def test_entry_with_empty_user_id_skipped(self):
        from open_webui.routers.containers import _parse_image_overrides

        assert _parse_image_overrides('=img1,user-b=img2') == {'user-b': 'img2'}

    def test_entry_with_empty_image_skipped(self):
        from open_webui.routers.containers import _parse_image_overrides

        assert _parse_image_overrides('user-a=,user-b=img2') == {'user-b': 'img2'}

    def test_image_with_equals_sign_in_value(self):
        """Image references with ``=`` in them (rare, but valid for some
        registries with query-string-style refs) must use partition not
        split, so the first ``=`` is the separator and the rest is the
        image. ``partition`` already does this correctly."""
        from open_webui.routers.containers import _parse_image_overrides

        assert _parse_image_overrides('user-a=img:tag?digest=sha:abc') == {
            'user-a': 'img:tag?digest=sha:abc',
        }


class TestImageForUser:
    """``_image_for_user`` falls back to ``AGENT_IMAGE`` for users with
    no override and returns the pinned image for users that do."""

    def test_returns_default_when_no_override(self):
        from open_webui.routers import containers

        with patch.object(containers, 'AGENT_IMAGE_OVERRIDES', {}):
            with patch.object(containers, 'AGENT_IMAGE', 'myah/agent:latest'):
                assert containers._image_for_user('user-a') == 'myah/agent:latest'

    def test_returns_override_when_present(self):
        from open_webui.routers import containers

        overrides = {'user-a': 'myah/agent-stock:abc123'}
        with patch.object(containers, 'AGENT_IMAGE_OVERRIDES', overrides):
            with patch.object(containers, 'AGENT_IMAGE', 'myah/agent:latest'):
                assert containers._image_for_user('user-a') == 'myah/agent-stock:abc123'

    def test_returns_default_for_unmapped_users_even_when_overrides_active(self):
        """An override for user-a must NOT leak to user-b. This is the
        core canary safety invariant: a per-user override is per-user."""
        from open_webui.routers import containers

        overrides = {'user-a': 'myah/agent-stock:abc123'}
        with patch.object(containers, 'AGENT_IMAGE_OVERRIDES', overrides):
            with patch.object(containers, 'AGENT_IMAGE', 'myah/agent:latest'):
                # user-a is pinned to stock
                assert containers._image_for_user('user-a') == 'myah/agent-stock:abc123'
                # user-b is NOT — falls back to default
                assert containers._image_for_user('user-b') == 'myah/agent:latest'


class TestImageOverrideAppliedAtSpawn:
    """Integration test: the per-user override actually reaches the
    Docker ``containers.run`` call. Without this gate, the override
    parser could be correct but never wired into the spawn path —
    silent canary failure where everyone keeps running the default
    image despite the env var being set."""

    def test_override_passes_pinned_image_to_docker(self):
        from open_webui.routers.containers import _start_container_sync

        captured_kwargs = {}

        def fake_containers_run(*args, **kwargs):
            captured_kwargs.update(kwargs)
            mock_container = MagicMock()
            mock_container.id = 'fake-container-id'
            return mock_container

        mock_docker_client = MagicMock()
        mock_docker_client.containers.run.side_effect = fake_containers_run
        mock_docker_client.volumes.list.return_value = []
        mock_docker_client.volumes.create.return_value = MagicMock()
        mock_docker_client.containers.get.side_effect = NotFound('not found')

        with (
            patch(
                'open_webui.routers.containers._docker_client',
                return_value=mock_docker_client,
            ),
            patch(
                'open_webui.routers.containers._free_port',
                side_effect=[9001, 9002, 9003, 9004, 9005],
            ),
            patch('open_webui.routers.containers.Containers') as mock_containers_model,
            patch('open_webui.routers.containers.AGENT_BEARER_TOKEN', 'test-bearer'),
            patch('open_webui.routers.containers.AGENT_IMAGE', 'myah/agent:latest'),
            patch(
                'open_webui.routers.containers.AGENT_IMAGE_OVERRIDES',
                {'user-canary': 'myah/agent-stock:abc123'},
            ),
            patch('open_webui.routers.containers.PLATFORM_WEBHOOK_HOST', 'host.docker.internal'),
            patch('open_webui.routers.containers.PLATFORM_PORT', '8082'),
        ):
            mock_containers_model.update_status.return_value = None

            _start_container_sync(
                user_id='user-canary',
                honcho_api_key='hk-1',
                honcho_workspace_id='ws-1',
            )

        assert captured_kwargs.get('image') == 'myah/agent-stock:abc123', (
            f'Per-user override did NOT reach Docker run kwargs. '
            f'Got image={captured_kwargs.get("image")!r}; expected the '
            f'override value. The canary mechanism would silently keep '
            f'running the default image despite the env var being set.'
        )

    def test_unmapped_user_keeps_default_image(self):
        """Mirror of the above: a user NOT in the override map must use
        the default image even when the override map is non-empty."""
        from open_webui.routers.containers import _start_container_sync

        captured_kwargs = {}

        def fake_containers_run(*args, **kwargs):
            captured_kwargs.update(kwargs)
            mock_container = MagicMock()
            mock_container.id = 'fake-container-id'
            return mock_container

        mock_docker_client = MagicMock()
        mock_docker_client.containers.run.side_effect = fake_containers_run
        mock_docker_client.volumes.list.return_value = []
        mock_docker_client.volumes.create.return_value = MagicMock()
        mock_docker_client.containers.get.side_effect = NotFound('not found')

        with (
            patch(
                'open_webui.routers.containers._docker_client',
                return_value=mock_docker_client,
            ),
            patch(
                'open_webui.routers.containers._free_port',
                side_effect=[9001, 9002, 9003, 9004, 9005],
            ),
            patch('open_webui.routers.containers.Containers') as mock_containers_model,
            patch('open_webui.routers.containers.AGENT_BEARER_TOKEN', 'test-bearer'),
            patch('open_webui.routers.containers.AGENT_IMAGE', 'myah/agent:latest'),
            patch(
                'open_webui.routers.containers.AGENT_IMAGE_OVERRIDES',
                {'user-canary': 'myah/agent-stock:abc123'},
            ),
            patch('open_webui.routers.containers.PLATFORM_WEBHOOK_HOST', 'host.docker.internal'),
            patch('open_webui.routers.containers.PLATFORM_PORT', '8082'),
        ):
            mock_containers_model.update_status.return_value = None

            _start_container_sync(
                user_id='user-not-in-canary',
                honcho_api_key='hk-1',
                honcho_workspace_id='ws-1',
            )

        assert captured_kwargs.get('image') == 'myah/agent:latest', (
            f'Default user wrongly got pinned image. The canary override '
            f'for user-canary leaked to user-not-in-canary. Per-user '
            f'isolation is the core safety invariant of the override '
            f'mechanism.'
        )
