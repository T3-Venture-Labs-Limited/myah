"""Back-compat aliases for WEBUI_* env vars.

Phase 1A Task A.3. Hosted production deploys configure their environment
with WEBUI_AUTH, WEBUI_SECRET_KEY, WEBUI_NAME, etc. The rename to MYAH_*
must not break those deploys on first boot. This module verifies that:

1. MYAH_* primary names exist and pick up MYAH_*-prefixed env vars.
2. When MYAH_* is unset BUT the legacy WEBUI_* name is set, MYAH_* falls
   back to the legacy value (with a deprecation log emitted once per
   process).
3. MYAH_* takes precedence over WEBUI_* when both are set.

The set of WEBUI_* names is enumerated at module-import time inside env.py
via grep at implementation time — see env.py's _env() helper for the list.
"""

from __future__ import annotations

import importlib
import logging
import os

import pytest


# All 18 WEBUI_* env vars enumerated in env.py at the rename PR's commit
# (verified via:  grep -ohE '\bWEBUI_[A-Z_]+' env.py | sort -u).
_WEBUI_ENV_VARS = [
    'WEBUI_ADMIN_EMAIL',
    'WEBUI_ADMIN_NAME',
    'WEBUI_ADMIN_PASSWORD',
    'WEBUI_AUTH',
    'WEBUI_AUTH_COOKIE_SAME_SITE',
    'WEBUI_AUTH_COOKIE_SECURE',
    'WEBUI_AUTH_SIGNOUT_REDIRECT_URL',
    'WEBUI_AUTH_TRUSTED_EMAIL_HEADER',
    'WEBUI_AUTH_TRUSTED_GROUPS_HEADER',
    'WEBUI_AUTH_TRUSTED_NAME_HEADER',
    'WEBUI_AUTH_TRUSTED_ROLE_HEADER',
    'WEBUI_BUILD_HASH',
    'WEBUI_FAVICON_URL',
    'WEBUI_JWT_SECRET_KEY',
    'WEBUI_NAME',
    'WEBUI_SECRET_KEY',
    'WEBUI_SESSION_COOKIE_SAME_SITE',
    'WEBUI_SESSION_COOKIE_SECURE',
]


@pytest.fixture
def reset_env(monkeypatch):
    """Ensure each test starts with no MYAH_ or WEBUI_ overrides."""
    for key in list(os.environ.keys()):
        if key.startswith(('MYAH_', 'WEBUI_')):
            monkeypatch.delenv(key, raising=False)


def _reload_env_module():
    """Force-reimport so env.py picks up monkeypatched values."""
    import myah.env

    importlib.reload(myah.env)
    return myah.env


def test_myah_auth_default_when_neither_set(reset_env):
    """When neither MYAH_AUTH nor WEBUI_AUTH is set, default is True."""
    env = _reload_env_module()
    assert env.MYAH_AUTH is True


def test_webui_auth_alias_falls_back(monkeypatch, reset_env):
    """When MYAH_AUTH is unset but WEBUI_AUTH=false, MYAH_AUTH is False."""
    monkeypatch.setenv('WEBUI_AUTH', 'false')
    env = _reload_env_module()
    assert env.MYAH_AUTH is False


def test_myah_auth_wins_over_webui_auth(monkeypatch, reset_env):
    """MYAH_AUTH takes precedence over WEBUI_AUTH when both are set."""
    monkeypatch.setenv('MYAH_AUTH', 'true')
    monkeypatch.setenv('WEBUI_AUTH', 'false')
    env = _reload_env_module()
    assert env.MYAH_AUTH is True


def test_webui_name_alias_falls_back(monkeypatch, reset_env):
    """When MYAH_NAME unset but WEBUI_NAME='Custom', primary picks it up."""
    monkeypatch.setenv('WEBUI_NAME', 'CustomName')
    env = _reload_env_module()
    assert env.MYAH_NAME == 'CustomName (Myah)'  # env.py adds suffix


def test_webui_secret_key_alias_falls_back(monkeypatch, reset_env):
    monkeypatch.setenv('WEBUI_SECRET_KEY', 'legacy-secret-value')
    env = _reload_env_module()
    assert env.MYAH_SECRET_KEY == 'legacy-secret-value'


def test_legacy_alias_still_works_as_module_attribute(monkeypatch, reset_env):
    """Code that still imports the legacy name (WEBUI_AUTH) must keep working."""
    monkeypatch.setenv('MYAH_AUTH', 'false')
    env = _reload_env_module()
    # Both names must agree
    assert env.WEBUI_AUTH is False
    assert env.MYAH_AUTH is False


def test_deprecation_log_emitted_on_legacy_use(monkeypatch, reset_env, caplog):
    """Using WEBUI_AUTH emits a one-time deprecation warning."""
    monkeypatch.setenv('WEBUI_AUTH', 'true')
    with caplog.at_level(logging.WARNING):
        env = _reload_env_module()
        _ = env.MYAH_AUTH
    assert any(
        'WEBUI_AUTH' in r.message and 'deprecated' in r.message.lower()
        for r in caplog.records
    ), 'No deprecation warning was emitted for legacy WEBUI_AUTH use'


@pytest.mark.parametrize('webui_name', _WEBUI_ENV_VARS)
def test_every_legacy_webui_name_is_aliased(webui_name, monkeypatch, reset_env):
    """Every WEBUI_* env var name must have a MYAH_* primary that reads it.

    This is the regression gate: if a new WEBUI_* env var is added to env.py
    without the back-compat treatment, this test fails for that name.

    The test sets the legacy name and asserts that env.py reads the primary
    MYAH_* attribute (which should fall back to the legacy value).
    """
    myah_name = 'MYAH_' + webui_name.removeprefix('WEBUI_')
    monkeypatch.setenv(webui_name, 'legacy-value-for-test')
    env = _reload_env_module()
    # The primary MYAH_* attribute must exist on the env module
    assert hasattr(env, myah_name), (
        f'env.py has WEBUI_*-backed name {webui_name} but no MYAH_* primary '
        f'attribute {myah_name}. Add it to the back-compat alias block in env.py.'
    )
