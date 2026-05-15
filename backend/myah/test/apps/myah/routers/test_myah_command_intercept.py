# Tests for the Myah slash-command interception logic in openai.py.
#
# The interception catches /new and /reset — session-reset commands that have
# no meaning on the Myah web platform — and redirects users to the sidebar
# New Chat flow instead of passing the raw command to Hermes.
#
# Uses the importlib stub pattern (same as test_containers_env.py) to load
# openai.py without triggering its database/migration side-effects.

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock


# ── module loader ─────────────────────────────────────────────────────────────


def _load_openai_module():
    """Load myah/routers/openai.py with all heavy imports stubbed out.

    Returns the loaded module object so tests can access its constants.
    """
    # Build minimal stubs for every myah package that openai.py touches
    # at import time. The goal is to reach module-level constant definitions
    # without triggering DB migrations, Redis, or external network calls.

    def _make(name, **attrs):
        m = ModuleType(name)
        for k, v in attrs.items():
            setattr(m, k, v)
        return m

    # myah.internal.db — triggers peewee migration on import
    internal_db = _make('myah.internal.db', get_session=MagicMock())

    # myah.models.*
    models_models = _make('myah.models.models', Models=MagicMock())
    models_access = _make('myah.models.access_grants', AccessGrants=MagicMock())
    models_files = _make('myah.models.files', Files=MagicMock())
    models_groups = _make('myah.models.groups', Groups=MagicMock())
    models_users = _make('myah.models.users', UserModel=MagicMock())

    # myah.env — provides module-level constants used at import time
    env_mod = _make(
        'myah.env',
        MODELS_CACHE_TTL=60,
        AIOHTTP_CLIENT_SESSION_SSL=False,
        AIOHTTP_CLIENT_TIMEOUT=300,
        AIOHTTP_CLIENT_TIMEOUT_MODEL_LIST=10,
        ENABLE_FORWARD_USER_INFO_HEADERS=False,
        FORWARD_SESSION_INFO_HEADER_CHAT_ID='',
        BYPASS_MODEL_ACCESS_CONTROL=False,
    )

    # myah.constants
    constants_mod = _make('myah.constants', ERROR_MESSAGES=SimpleNamespace())

    # myah.routers.containers
    containers_mod = _make(
        'myah.routers.containers',
        AGENT_BEARER_TOKEN='',
        _gateway_url=MagicMock(),
        get_or_create_container=MagicMock(),
    )

    # myah.utils.*
    payload_mod = _make(
        'myah.utils.payload',
        apply_model_params_to_body_openai=MagicMock(),
        apply_system_prompt_to_body=MagicMock(),
    )
    misc_mod = _make(
        'myah.utils.misc',
        cleanup_response=MagicMock(),
        convert_logit_bias_input_to_json=MagicMock(),
        stream_chunks_handler=MagicMock(),
        stream_wrapper=MagicMock(),
    )
    auth_mod = _make(
        'myah.utils.auth',
        get_admin_user=MagicMock(),
        get_verified_user=MagicMock(),
    )
    headers_mod = _make('myah.utils.headers', include_user_info_headers=MagicMock())
    anthropic_mod = _make(
        'myah.utils.anthropic',
        is_anthropic_url=MagicMock(return_value=False),
        get_anthropic_models=MagicMock(return_value=[]),
    )
    hermes_routing_mod = _make(
        'myah.utils.hermes_routing',
        resolve_user_agent_base=MagicMock(side_effect=lambda url: url),
    )

    stubs = {
        'myah.internal.db': internal_db,
        'myah.models.models': models_models,
        'myah.models.access_grants': models_access,
        'myah.models.files': models_files,
        'myah.models.groups': models_groups,
        'myah.models.users': models_users,
        'myah.env': env_mod,
        'myah.constants': constants_mod,
        'myah.routers.containers': containers_mod,
        'myah.utils.payload': payload_mod,
        'myah.utils.misc': misc_mod,
        'myah.utils.auth': auth_mod,
        'myah.utils.headers': headers_mod,
        'myah.utils.anthropic': anthropic_mod,
        'myah.utils.hermes_routing': hermes_routing_mod,
    }

    # Snapshot existing sys.modules entries so we can restore them after load
    saved = {name: sys.modules.get(name) for name in stubs}
    sys.modules.update(stubs)

    try:
        path = Path(__file__).resolve().parents[4] / 'routers' / 'openai.py'
        spec = importlib.util.spec_from_file_location('myah.routers.openai', path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        # Restore original sys.modules state
        for name, original in saved.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original


# Load once for all tests in this module
_openai = _load_openai_module()
_MYAH_NEW_CHAT_REDIRECT = _openai._MYAH_NEW_CHAT_REDIRECT

# Call the real function from openai.py so tests exercise the actual handler code path.
_apply_interception = _openai._apply_myah_command_interception


# ── tests ─────────────────────────────────────────────────────────────────────


def test_new_exact_is_rewritten():
    result = _apply_interception('/new')
    assert result == _MYAH_NEW_CHAT_REDIRECT


def test_reset_exact_is_rewritten():
    result = _apply_interception('/reset')
    assert result == _MYAH_NEW_CHAT_REDIRECT


def test_new_with_whitespace_is_rewritten():
    result = _apply_interception('  /new  ')
    assert result == _MYAH_NEW_CHAT_REDIRECT


def test_new_uppercase_is_rewritten():
    result = _apply_interception('/NEW')
    assert result == _MYAH_NEW_CHAT_REDIRECT


def test_new_with_trailing_words_is_not_intercepted():
    text = '/new start a project'
    result = _apply_interception(text)
    assert result == text


def test_model_command_passes_through():
    text = '/model gpt-4'
    result = _apply_interception(text)
    assert result == text


def test_ordinary_message_passes_through():
    text = 'Hello, how are you?'
    result = _apply_interception(text)
    assert result == text


def test_empty_string_passes_through():
    result = _apply_interception('')
    assert result == ''


def test_bare_slash_passes_through():
    result = _apply_interception('/')
    assert result == '/'
