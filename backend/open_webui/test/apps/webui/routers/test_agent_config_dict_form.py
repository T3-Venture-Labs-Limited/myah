"""Tests for agent_config.py: PATCH /config translates string-form model to dict-form.

Tier 2B Task 2B.6. Replaces the deleted Myah marker block in
agent/hermes/agent/auxiliary_client.py:1058-1085 — the file is now upstream-pure.

Translation algorithm (mirrors the deleted marker block, validated against
hermes_cli.models._PROVIDER_MODELS / _PROVIDER_ALIASES):
  1. Non-string OR no '/': pass through (already dict-form, or bare slug).
  2. Prefix is a canonical provider id in _PROVIDER_MODELS:
     -> {provider: <prefix>, default: <slug>}.
  3. Prefix is a Hermes alias (_PROVIDER_ALIASES) — e.g. qwen -> alibaba:
     -> {provider: <canonical>, default: <slug>}.
  4. Otherwise pass through (let Hermes accept or reject).
"""

import asyncio
import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


def _load_agent_config_module():
    """Load open_webui/routers/agent_config.py with all heavy deps stubbed.

    Mirrors test_agent_config.py::_load_agent_config_module exactly. The
    translator (_translate_model_to_dict_form) reads from a static snapshot
    of Hermes' provider catalog baked into agent_config.py — no
    ``hermes_cli`` import is needed at runtime or in tests.
    """

    def _make(name, **attrs):
        m = ModuleType(name)
        for k, v in attrs.items():
            setattr(m, k, v)
        return m

    internal_db = _make('open_webui.internal.db', get_session=MagicMock())

    env_mod = _make(
        'open_webui.env',
        WEBUI_AUTH=True,
        ENABLE_AGENT_SETTINGS_UI=True,
    )

    constants_mod = _make(
        'open_webui.constants',
        ERROR_MESSAGES=SimpleNamespace(
            NOT_FOUND='not found',
            ACCESS_PROHIBITED='forbidden',
        ),
    )

    users_update = MagicMock()
    users_mod = _make(
        'open_webui.models.users',
        Users=SimpleNamespace(update_user_by_id=users_update),
        UserModel=MagicMock(),
    )

    auth_mod = _make(
        'open_webui.utils.auth',
        get_verified_user=MagicMock(),
        get_admin_user=MagicMock(),
    )

    agent_proxy_aux_call = AsyncMock()
    agent_proxy_mod = _make(
        'open_webui.utils.agent_proxy',
        aux_call=agent_proxy_aux_call,
        AUX_ALLOWED_TASKS={'title_generation', 'follow_up_generation'},
        normalize_catalog_models=lambda raw: [
            m['id'] if isinstance(m, dict) else m for m in (raw or [])
        ],
    )

    hermes_web_call = AsyncMock()
    hermes_web_mod = _make(
        'open_webui.utils.hermes_web',
        web_call=hermes_web_call,
    )

    config_mod = _make(
        'open_webui.config',
        AUX_DEFAULT_FALLBACKS={},
        AUX_VISION_FALLBACKS={},
        AUX_VISION_INCAPABLE=frozenset(),
        AUX_DEFAULT_TASKS=frozenset(),
        _resolve_aux_default=lambda *a, **kw: None,
    )

    for mod in (
        internal_db, env_mod, constants_mod, users_mod, auth_mod,
        agent_proxy_mod, hermes_web_mod, config_mod,
    ):
        sys.modules[mod.__name__] = mod

    router_path = (
        Path(__file__).resolve().parent.parent.parent.parent.parent
        / 'routers' / 'agent_config.py'
    )
    spec = importlib.util.spec_from_file_location(
        'open_webui.routers.agent_config', router_path
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules['open_webui.routers.agent_config'] = module
    spec.loader.exec_module(module)

    module._test_users_update = users_update
    module._test_aux_call = agent_proxy_aux_call
    module._test_web_call = hermes_web_call
    return module


@pytest.fixture
def agent_config_module():
    mod = _load_agent_config_module()
    mod._test_users_update.reset_mock()
    mod._test_aux_call.reset_mock()
    mod._test_web_call.reset_mock()
    return mod


# ── _translate_model_to_dict_form: pure unit tests ────────────────────────────


def test_translate_canonical_provider_prefix(agent_config_module):
    """anthropic/claude-haiku-4-5 -> {provider: anthropic, default: claude-haiku-4-5}."""
    result = agent_config_module._translate_model_to_dict_form(
        'anthropic/claude-haiku-4-5-20251001'
    )
    assert result == {'provider': 'anthropic', 'default': 'claude-haiku-4-5-20251001'}


def test_translate_alias_resolves_to_canonical(agent_config_module):
    """qwen/qwen3-coder -> {provider: alibaba, default: qwen3-coder} via _PROVIDER_ALIASES."""
    result = agent_config_module._translate_model_to_dict_form('qwen/qwen3-coder')
    assert result == {'provider': 'alibaba', 'default': 'qwen3-coder'}


def test_translate_openai_codex_canonical(agent_config_module):
    """openai-codex is canonical (NOT aliased to openai); preserve as-is."""
    result = agent_config_module._translate_model_to_dict_form('openai-codex/gpt-5')
    assert result == {'provider': 'openai-codex', 'default': 'gpt-5'}


def test_translate_unknown_prefix_passes_through(agent_config_module):
    """Unknown vendor prefix → pass through verbatim; Hermes will reject/accept."""
    result = agent_config_module._translate_model_to_dict_form('unknown-vendor/foo')
    assert result == 'unknown-vendor/foo'


def test_translate_dict_form_passes_through(agent_config_module):
    """If the frontend somehow sends dict-form already, leave it untouched."""
    payload = {'provider': 'openai', 'default': 'gpt-4o'}
    result = agent_config_module._translate_model_to_dict_form(payload)
    assert result == payload  # same dict, returned unchanged


def test_translate_no_slash_passes_through(agent_config_module):
    """A bare model name with no '/' → pass through (no provider hint)."""
    result = agent_config_module._translate_model_to_dict_form('gpt-4o')
    assert result == 'gpt-4o'


def test_translate_works_without_hermes_cli_importable(agent_config_module):
    """Reproduces the production environment where hermes-agent is NOT
    pip-installed in the platform venv. The translator must still work
    using only the static snapshot baked into agent_config.py.

    This guards against the regression where the translator silently
    falls back to passing the bare string through (re-introducing the
    OpenRouter-fallback bug Task 2B.6 fixes).
    """
    # Ensure hermes_cli is NOT in sys.modules so any stale lazy import
    # would surface as ImportError. The translator should never need it.
    sys.modules.pop('hermes_cli', None)
    sys.modules.pop('hermes_cli.models', None)

    result = agent_config_module._translate_model_to_dict_form(
        'anthropic/claude-haiku-4-5-20251001'
    )
    assert result == {'provider': 'anthropic', 'default': 'claude-haiku-4-5-20251001'}

    result = agent_config_module._translate_model_to_dict_form('qwen/qwen3-coder')
    assert result == {'provider': 'alibaba', 'default': 'qwen3-coder'}


def test_snapshot_includes_widely_used_providers(agent_config_module):
    """Tripwire: the snapshot must include the providers most commonly
    selected in production. If a future maintainer accidentally trims this
    set during a Tier 2C upstream merge, this test fails loudly so the
    drift is caught before it reaches users.

    The list reflects providers that ship as v1-visible in
    ``myah_overrides.py`` and are exercised by smoke-test.sh.
    """
    must_include = {
        'anthropic',
        'openai',
        'openai-codex',
        'gemini',
        'alibaba',
        'xai',
        'zai',
        'deepseek',
        'kimi-coding',
        'nous',
    }
    assert must_include.issubset(agent_config_module._HERMES_PROVIDER_IDS), (
        f'snapshot drift detected — missing canonical provider ids: '
        f'{must_include - agent_config_module._HERMES_PROVIDER_IDS}'
    )


def test_snapshot_aliases_resolve_to_canonical_or_passthrough(agent_config_module):
    """Every alias must either resolve to a canonical provider id (in
    _HERMES_PROVIDER_IDS) or map to a value the translator filters out.
    This guards against ``_HERMES_PROVIDER_ALIASES`` listing aliases that
    silently produce non-canonical ``{provider: ...}`` dicts."""
    canonical = agent_config_module._HERMES_PROVIDER_IDS
    aliases = agent_config_module._HERMES_PROVIDER_ALIASES
    # Every alias is either canonical-resolving (filterable) or a known
    # passthrough value documented in the comment block above the dict.
    documented_passthroughs = {'custom', 'ollama-cloud', 'qwen-oauth'}
    for alias, target in aliases.items():
        assert (
            target in canonical or target in documented_passthroughs
        ), (
            f'alias {alias!r} -> {target!r} is neither canonical nor a '
            f'documented passthrough; update the snapshot or the '
            f'documented_passthroughs set in this test.'
        )


# ── PATCH /config integration: translation happens before forward ─────────────


def test_patch_endpoint_translates_string_to_dict(agent_config_module):
    """End-to-end: PATCH /config with string body forwards dict to Hermes."""
    forwarded = {}

    async def _capture(user, method, path, json_body=None, **kwargs):
        if method == 'GET' and path == '/api/plugins/myah-admin/config':
            return {'status': 200, 'body': {}, 'headers': {}}
        if method == 'PUT' and path == '/api/plugins/myah-admin/config':
            forwarded.update(json_body or {})
            return {'status': 200, 'body': json_body, 'headers': {}}
        return {'status': 200, 'body': {}, 'headers': {}}

    agent_config_module._test_web_call.side_effect = _capture
    user = SimpleNamespace(id='user-1', role='user', email='u@myah.dev')

    asyncio.run(
        agent_config_module.patch_agent_config(
            body={'model': 'anthropic/claude-haiku-4-5-20251001'},
            user=user,
        )
    )

    # The PUT body wraps the merged config in {'config': ...}
    cfg = forwarded.get('config', {})
    assert isinstance(cfg.get('model'), dict)
    assert cfg['model']['provider'] == 'anthropic'
    assert cfg['model']['default'] == 'claude-haiku-4-5-20251001'
