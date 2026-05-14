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
from pathlib import Path

import pytest


# All WEBUI_* env vars enumerated in env.py at the rename PR's commit
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
    'WEBUI_BANNERS',
    'WEBUI_BUILD_HASH',
    'WEBUI_FAVICON_URL',
    'WEBUI_JWT_SECRET_KEY',
    'WEBUI_NAME',
    'WEBUI_SECRET_KEY',
    'WEBUI_SESSION_COOKIE_SAME_SITE',
    'WEBUI_SESSION_COOKIE_SECURE',
    'WEBUI_URL',
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


def test_webui_url_alias_falls_back(monkeypatch, reset_env):
    """When MYAH_URL unset but WEBUI_URL='https://my.host/', primary picks it up."""
    monkeypatch.setenv('WEBUI_URL', 'https://my.host/')
    env = _reload_env_module()
    assert env.MYAH_URL == 'https://my.host/'
    assert env.WEBUI_URL == 'https://my.host/'


def test_webui_banners_alias_falls_back(monkeypatch, reset_env):
    """When MYAH_BANNERS unset but WEBUI_BANNERS is JSON, primary picks it up."""
    monkeypatch.setenv('WEBUI_BANNERS', '[{"id":"x","type":"info","content":"hi","dismissible":true,"timestamp":0}]')
    env = _reload_env_module()
    assert env.MYAH_BANNERS == '[{"id":"x","type":"info","content":"hi","dismissible":true,"timestamp":0}]'
    assert env.WEBUI_BANNERS == env.MYAH_BANNERS


def test_webui_favicon_url_alias_falls_back(monkeypatch, reset_env):
    """When MYAH_FAVICON_URL unset but WEBUI_FAVICON_URL is set, primary picks it up."""
    monkeypatch.setenv('WEBUI_FAVICON_URL', 'https://example.com/favicon.png')
    env = _reload_env_module()
    assert env.MYAH_FAVICON_URL == 'https://example.com/favicon.png'
    assert env.WEBUI_FAVICON_URL == 'https://example.com/favicon.png'


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
def test_every_legacy_webui_name_has_myah_attribute(webui_name, monkeypatch, reset_env):
    """Every WEBUI_* env var name must have a MYAH_* primary attribute.

    Fast smoke gate: just checks the attribute exists on the env module.
    The end-to-end fall-through behaviour is verified by
    ``test_every_legacy_webui_name_falls_back_to_primary`` below. We keep
    this weak check as a simple inventory assertion with low false-positive
    risk.
    """
    myah_name = 'MYAH_' + webui_name.removeprefix('WEBUI_')
    monkeypatch.setenv(webui_name, 'legacy-value-for-test')
    env = _reload_env_module()
    assert hasattr(env, myah_name), (
        f'env.py has WEBUI_*-backed name {webui_name} but no MYAH_* primary '
        f'attribute {myah_name}. Add it to the back-compat alias block in env.py.'
    )


# Explicit (legacy_name, sentinel, expected_value_after_coercion) tuples.
#
# This is intentionally verbose: env.py's _env() chain produces values of
# different types (bool, str, Optional[str]) and some constants apply
# transformations (e.g. MYAH_NAME appends ' (Myah)'). A single uniform
# sentinel + assertion would be wrong for several names. Explicit tuples make
# each case auditable.
#
_FALL_THROUGH_CASES = [
    # (legacy_name, sentinel_value, expected_value_on_module)
    ('WEBUI_ADMIN_EMAIL', 'admin@legacy.test', 'admin@legacy.test'),
    ('WEBUI_ADMIN_NAME', 'LegacyAdmin', 'LegacyAdmin'),
    ('WEBUI_ADMIN_PASSWORD', 'legacy-password', 'legacy-password'),
    ('WEBUI_AUTH', 'false', False),
    ('WEBUI_AUTH_COOKIE_SAME_SITE', 'strict', 'strict'),
    ('WEBUI_AUTH_COOKIE_SECURE', 'true', True),
    ('WEBUI_AUTH_SIGNOUT_REDIRECT_URL', 'https://legacy.example/logout', 'https://legacy.example/logout'),
    ('WEBUI_AUTH_TRUSTED_EMAIL_HEADER', 'X-Legacy-Email', 'X-Legacy-Email'),
    ('WEBUI_AUTH_TRUSTED_GROUPS_HEADER', 'X-Legacy-Groups', 'X-Legacy-Groups'),
    ('WEBUI_AUTH_TRUSTED_NAME_HEADER', 'X-Legacy-Name', 'X-Legacy-Name'),
    ('WEBUI_AUTH_TRUSTED_ROLE_HEADER', 'X-Legacy-Role', 'X-Legacy-Role'),
    (
        'WEBUI_BANNERS',
        '[{"id":"x","type":"info","content":"hi","dismissible":true,"timestamp":0}]',
        '[{"id":"x","type":"info","content":"hi","dismissible":true,"timestamp":0}]',
    ),
    ('WEBUI_BUILD_HASH', 'legacy-build-hash', 'legacy-build-hash'),
    ('WEBUI_FAVICON_URL', 'https://legacy.example/favicon.ico', 'https://legacy.example/favicon.ico'),
    ('WEBUI_JWT_SECRET_KEY', 'legacy-jwt-secret', 'legacy-jwt-secret'),
    # MYAH_NAME appends ' (Myah)' when not the default value 'Myah'.
    ('WEBUI_NAME', 'LegacyName', 'LegacyName (Myah)'),
    ('WEBUI_SECRET_KEY', 'legacy-secret', 'legacy-secret'),
    ('WEBUI_SESSION_COOKIE_SAME_SITE', 'strict', 'strict'),
    ('WEBUI_SESSION_COOKIE_SECURE', 'true', True),
    ('WEBUI_URL', 'https://legacy.example/', 'https://legacy.example/'),
]


@pytest.mark.parametrize(('legacy_name', 'sentinel', 'expected'), _FALL_THROUGH_CASES)
def test_every_legacy_webui_name_falls_back_to_primary(
    legacy_name, sentinel, expected, monkeypatch, reset_env
):
    """Setting only the legacy WEBUI_* var must make MYAH_* resolve to that value.

    Stronger than ``test_every_legacy_webui_name_has_myah_attribute``: it
    verifies the legacy value actually flows through ``_env()`` to the
    canonical primary, with appropriate type coercion. Catches typo'd
    ``_env(MYAH_X, MYAH_X_TYPO, default)`` regressions that the weak hasattr
    check would miss.

    AUTH_COOKIE_* aliases fall back through both MYAH_SESSION_COOKIE_SECURE
    and WEBUI_SESSION_COOKIE_SECURE if their own value is unset — the
    ``reset_env`` fixture clears MYAH_*/WEBUI_* up front, so the only
    populated env var when this test runs is the one being exercised.
    """
    myah_name = 'MYAH_' + legacy_name.removeprefix('WEBUI_')
    monkeypatch.setenv(legacy_name, sentinel)
    env = _reload_env_module()

    actual = getattr(env, myah_name)
    assert actual == expected, (
        f'{myah_name} did not pick up legacy {legacy_name}={sentinel!r}: '
        f'expected {expected!r}, got {actual!r}. Likely cause: typo in the '
        f'_env() call in env.py for {myah_name}.'
    )
    # The legacy alias must agree with the primary.
    assert getattr(env, legacy_name) == expected, (
        f'Legacy alias {legacy_name} disagrees with primary {myah_name}: '
        f'env.{legacy_name}={getattr(env, legacy_name)!r}, '
        f'env.{myah_name}={actual!r}'
    )


# ---------------------------------------------------------------------------
# Phase B.2a: __init__.py KEY_FILE → env-var bridge regression tests
# ---------------------------------------------------------------------------
# `_bootstrap_secret_key()` in `myah/__init__.py` reads the on-disk
# .webui_secret_key file when no SECRET_KEY env var is set, and populates BOTH
# MYAH_SECRET_KEY and WEBUI_SECRET_KEY so env.py's _env() shim AND any
# bypass-readers (os.environ['WEBUI_SECRET_KEY']) both see the value.
#
# The on-disk filename stays `.webui_secret_key` for v0.1.0-beta.1 — its
# rename is deferred to Phase B.3 (on-disk migration concerns).


class TestBootstrapSecretKey:
    """Cover the KEY_FILE → env-var bridge in myah.__init__._bootstrap_secret_key."""

    def test_loads_from_key_file_when_no_env_var_set(self, tmp_path, monkeypatch, reset_env):
        """KEY_FILE → both MYAH_SECRET_KEY and WEBUI_SECRET_KEY env vars."""
        from myah import _bootstrap_secret_key

        key_file = tmp_path / '.webui_secret_key'
        key_file.write_text('on-disk-secret-sentinel\n')
        monkeypatch.setattr('myah.KEY_FILE', key_file)

        _bootstrap_secret_key(echo=lambda *_a, **_kw: None)

        # Both env vars populated so env.py's shim AND bypass-readers see it.
        assert os.environ['MYAH_SECRET_KEY'] == 'on-disk-secret-sentinel'
        assert os.environ['WEBUI_SECRET_KEY'] == 'on-disk-secret-sentinel'

    def test_env_py_reload_reflects_bootstrap(self, tmp_path, monkeypatch, reset_env):
        """After bootstrap loads from disk, reloading env.py picks up MYAH_SECRET_KEY."""
        from myah import _bootstrap_secret_key

        key_file = tmp_path / '.webui_secret_key'
        key_file.write_text('reload-secret-sentinel')
        monkeypatch.setattr('myah.KEY_FILE', key_file)

        _bootstrap_secret_key(echo=lambda *_a, **_kw: None)
        env = _reload_env_module()

        assert env.MYAH_SECRET_KEY == 'reload-secret-sentinel'
        # The legacy module attribute alias must also reflect the value.
        assert env.WEBUI_SECRET_KEY == 'reload-secret-sentinel'

    def test_existing_myah_secret_key_skips_key_file(self, tmp_path, monkeypatch, reset_env):
        """If MYAH_SECRET_KEY is already set in env, KEY_FILE is not consulted."""
        from myah import _bootstrap_secret_key

        key_file = tmp_path / '.webui_secret_key'
        key_file.write_text('FROM-DISK-WRONG')
        monkeypatch.setattr('myah.KEY_FILE', key_file)
        monkeypatch.setenv('MYAH_SECRET_KEY', 'from-env-correct')

        _bootstrap_secret_key(echo=lambda *_a, **_kw: None)

        # Did NOT touch WEBUI_SECRET_KEY (no env-var to legacy bridge if the
        # canonical was already provided by the caller).
        assert os.environ['MYAH_SECRET_KEY'] == 'from-env-correct'
        assert 'WEBUI_SECRET_KEY' not in os.environ

    def test_existing_legacy_webui_secret_key_skips_key_file(
        self, tmp_path, monkeypatch, reset_env
    ):
        """If only legacy WEBUI_SECRET_KEY is set, KEY_FILE is still not consulted.

        env.py's _env() shim will pick the legacy value up; the bootstrap
        does not need to bridge here because there is no on-disk file to
        load.
        """
        from myah import _bootstrap_secret_key

        key_file = tmp_path / '.webui_secret_key'
        key_file.write_text('FROM-DISK-WRONG')
        monkeypatch.setattr('myah.KEY_FILE', key_file)
        monkeypatch.setenv('WEBUI_SECRET_KEY', 'legacy-env-value')

        _bootstrap_secret_key(echo=lambda *_a, **_kw: None)

        assert os.environ['WEBUI_SECRET_KEY'] == 'legacy-env-value'
        # Canonical name was not retroactively populated — env.py's _env()
        # is responsible for the legacy → canonical resolution at read time.
        assert 'MYAH_SECRET_KEY' not in os.environ

    def test_generates_key_file_when_missing(self, tmp_path, monkeypatch, reset_env):
        """If KEY_FILE does not exist, it is generated and then loaded."""
        from myah import _bootstrap_secret_key

        key_file = tmp_path / '.webui_secret_key'
        assert not key_file.exists()
        monkeypatch.setattr('myah.KEY_FILE', key_file)

        _bootstrap_secret_key(echo=lambda *_a, **_kw: None)

        assert key_file.exists()
        on_disk = key_file.read_text().strip()
        assert on_disk  # non-empty
        # Both env vars match the generated value.
        assert os.environ['MYAH_SECRET_KEY'] == on_disk
        assert os.environ['WEBUI_SECRET_KEY'] == on_disk


def test_open_webui_dir_legacy_alias():
    """OPEN_WEBUI_DIR (legacy name) is still importable + equal to MYAH_BACKEND_DIR.

    Phase B.2b (rename order #4) renamed the OPEN_WEBUI_DIR module constant
    to MYAH_BACKEND_DIR. The legacy name is preserved as an alias at the
    bottom of env.py to avoid breaking any out-of-tree code that imports
    OPEN_WEBUI_DIR directly from ``myah.env``.
    """
    import myah.env as env
    assert env.OPEN_WEBUI_DIR == env.MYAH_BACKEND_DIR


# ---------------------------------------------------------------------------
# Phase B.3a: webui.db → myah.db on-disk migration regression tests
# ---------------------------------------------------------------------------
# `_migrate_legacy_db_filename()` in `myah/__init__.py` renames the legacy
# SQLite file (and its WAL/SHM/journal siblings) on first boot after the
# v0.1.0-beta.1 rename so existing OSS installs don't appear to "lose" their
# chat history. It is invoked from the `serve` command before `import
# myah.main`, which means it runs before any DB engine is opened.


class TestMigrateLegacyDbFilename:
    """Cover the webui.db → myah.db on-disk migration helper."""

    def _capture_echo(self):
        messages: list[str] = []

        def _echo(msg: str = '', *_a, **_kw) -> None:
            messages.append(str(msg))

        return _echo, messages

    def test_renames_legacy_when_new_is_absent(self, tmp_path):
        """The typical upgrade path: only webui.db on disk → renamed to myah.db."""
        from myah import _migrate_legacy_db_filename

        legacy = tmp_path / 'webui.db'
        legacy.write_bytes(b'sqlite-payload')
        echo, messages = self._capture_echo()

        _migrate_legacy_db_filename(tmp_path, echo=echo)

        assert not legacy.exists()
        new = tmp_path / 'myah.db'
        assert new.exists()
        assert new.read_bytes() == b'sqlite-payload'
        assert any('Migrated legacy database file' in m for m in messages)

    def test_renames_wal_shm_journal_siblings(self, tmp_path):
        """SQLite WAL/SHM/journal siblings travel with the main DB file."""
        from myah import _migrate_legacy_db_filename

        (tmp_path / 'webui.db').write_bytes(b'main')
        (tmp_path / 'webui.db-wal').write_bytes(b'wal')
        (tmp_path / 'webui.db-shm').write_bytes(b'shm')
        (tmp_path / 'webui.db-journal').write_bytes(b'journal')

        _migrate_legacy_db_filename(tmp_path, echo=lambda *_a, **_kw: None)

        assert not (tmp_path / 'webui.db').exists()
        assert not (tmp_path / 'webui.db-wal').exists()
        assert not (tmp_path / 'webui.db-shm').exists()
        assert not (tmp_path / 'webui.db-journal').exists()
        assert (tmp_path / 'myah.db').read_bytes() == b'main'
        assert (tmp_path / 'myah.db-wal').read_bytes() == b'wal'
        assert (tmp_path / 'myah.db-shm').read_bytes() == b'shm'
        assert (tmp_path / 'myah.db-journal').read_bytes() == b'journal'

    def test_no_op_when_both_files_exist(self, tmp_path):
        """Deliberate-dual-state guard: never auto-delete legacy data."""
        from myah import _migrate_legacy_db_filename

        legacy = tmp_path / 'webui.db'
        new = tmp_path / 'myah.db'
        legacy.write_bytes(b'legacy-payload')
        new.write_bytes(b'new-payload')
        echo, messages = self._capture_echo()

        _migrate_legacy_db_filename(tmp_path, echo=echo)

        # Both files remain untouched.
        assert legacy.read_bytes() == b'legacy-payload'
        assert new.read_bytes() == b'new-payload'
        # Operator gets a warning so they can resolve the ambiguity manually.
        assert any('both' in m.lower() and 'webui.db' in m for m in messages)

    def test_no_op_when_only_new_exists(self, tmp_path):
        """Typical steady state after migration: no-op, no log noise."""
        from myah import _migrate_legacy_db_filename

        new = tmp_path / 'myah.db'
        new.write_bytes(b'live-db')
        echo, messages = self._capture_echo()

        _migrate_legacy_db_filename(tmp_path, echo=echo)

        assert new.read_bytes() == b'live-db'
        assert not (tmp_path / 'webui.db').exists()
        # No migration message — function returned early before touching disk.
        assert not any('Migrated legacy database file' in m for m in messages)

    def test_no_op_when_neither_file_exists(self, tmp_path):
        """Fresh install: no-op. env.py default path will create myah.db lazily."""
        from myah import _migrate_legacy_db_filename

        echo, messages = self._capture_echo()
        _migrate_legacy_db_filename(tmp_path, echo=echo)

        assert not (tmp_path / 'webui.db').exists()
        assert not (tmp_path / 'myah.db').exists()
        assert not any('Migrated legacy database file' in m for m in messages)

    def test_permission_error_is_swallowed(self, tmp_path, monkeypatch):
        """OSError during rename must not crash boot — log and continue."""
        from myah import _migrate_legacy_db_filename

        legacy = tmp_path / 'webui.db'
        legacy.write_bytes(b'x')

        def _raise(self, *_a, **_kw):
            raise PermissionError('simulated EACCES')

        monkeypatch.setattr(Path, 'rename', _raise)

        echo, messages = self._capture_echo()
        # Must not raise.
        _migrate_legacy_db_filename(tmp_path, echo=echo)

        assert any('failed to rename legacy' in m for m in messages)

    def test_uses_resolved_data_dir_when_arg_is_none(self, tmp_path, monkeypatch):
        """Default DATA_DIR resolution path: env var → tmp_path → rename."""
        from myah import _migrate_legacy_db_filename

        monkeypatch.setenv('DATA_DIR', str(tmp_path))
        (tmp_path / 'webui.db').write_bytes(b'env-resolved')

        _migrate_legacy_db_filename(echo=lambda *_a, **_kw: None)

        assert (tmp_path / 'myah.db').read_bytes() == b'env-resolved'

    def test_idempotent_across_repeated_calls(self, tmp_path):
        """Calling twice in succession is safe; second call is a no-op."""
        from myah import _migrate_legacy_db_filename

        (tmp_path / 'webui.db').write_bytes(b'idempotent')
        _migrate_legacy_db_filename(tmp_path, echo=lambda *_a, **_kw: None)
        # Second call: only myah.db exists → must return cleanly.
        _migrate_legacy_db_filename(tmp_path, echo=lambda *_a, **_kw: None)

        assert (tmp_path / 'myah.db').read_bytes() == b'idempotent'
