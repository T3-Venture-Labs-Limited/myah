"""H7 regression suite: env-composition order for worktree dev-server spawn.

The dev-server commands (`myah dev backend/frontend/both`) spawn uvicorn/vite
with an environment built by composing three sources:

    1. os.environ            (PATH from the parent shell)
    2. platform-oss/.env     (shared secrets: OPENROUTER_API_KEY, SENTRY, …)
    3. .worktree-env         (per-branch ports: BACKEND_PORT, MYAH_PLATFORM_PORT)

The order is the invariant. Reverse it and `MYAH_PLATFORM_PORT` silently falls
back to the baked default 8082 from .env, hosted-mode agent containers fetch
attachments from the wrong port, attachments silently drop on every chat send.

Per AGENTS.md "Attachment Pipeline Invariants" #2 and plan §2.2c.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def test_worktree_env_overrides_platform_env(tmp_path: Path) -> None:
    """H7: MYAH_PLATFORM_PORT in .worktree-env must override .env's baked default.

    Without this, hosted-mode per-user agent containers fetch attachments
    from MYAH_PLATFORM_PORT=8082 (the baked default in .env) instead of
    the worktree's allocated port — silently breaks attachment forwarding
    on every chat send.

    Per AGENTS.md 'Attachment Pipeline Invariants' #2 and plan §2.2c.
    """
    (tmp_path / 'platform-oss').mkdir()
    (tmp_path / 'platform-oss' / '.env').write_text(
        'MYAH_PLATFORM_PORT=8082\nMYAH_AGENT_BEARER_TOKEN=from-main\n'
    )
    (tmp_path / '.worktree-env').write_text(
        'export MYAH_PLATFORM_PORT=8189\nexport BACKEND_PORT=8189\n'
    )

    from myah.lib.cli.env_loader import load_worktree_env_chain
    env = load_worktree_env_chain(tmp_path)

    assert env['MYAH_PLATFORM_PORT'] == '8189', (
        f'H7 violation: MYAH_PLATFORM_PORT should be 8189 (from .worktree-env) '
        f'but got {env["MYAH_PLATFORM_PORT"]!r}. Reversing the load order would '
        f'silently break hosted-mode attachment forwarding.'
    )
    assert env['BACKEND_PORT'] == '8189'


def test_worktree_env_preserves_platform_env_secrets(tmp_path: Path) -> None:
    """Secrets only in .env (not in .worktree-env) must survive the merge."""
    (tmp_path / 'platform-oss').mkdir()
    (tmp_path / 'platform-oss' / '.env').write_text(
        'OPENROUTER_API_KEY=sk-real\nMYAH_AGENT_BEARER_TOKEN=from-main\n'
    )
    (tmp_path / '.worktree-env').write_text('export BACKEND_PORT=8189\n')

    from myah.lib.cli.env_loader import load_worktree_env_chain
    env = load_worktree_env_chain(tmp_path)

    assert env['OPENROUTER_API_KEY'] == 'sk-real'
    assert env['MYAH_AGENT_BEARER_TOKEN'] == 'from-main'
    assert env['BACKEND_PORT'] == '8189'


def test_load_chain_starts_from_os_environ(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """PATH from the parent shell must survive into the merged env."""
    monkeypatch.setenv('PATH', '/parent/path:/usr/bin')
    (tmp_path / 'platform-oss').mkdir()
    (tmp_path / 'platform-oss' / '.env').write_text('')
    (tmp_path / '.worktree-env').write_text('export BACKEND_PORT=8189\n')

    from myah.lib.cli.env_loader import load_worktree_env_chain
    env = load_worktree_env_chain(tmp_path)

    assert env['PATH'] == '/parent/path:/usr/bin'


def test_empty_platform_env_does_not_inherit_process_bearer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A process-global dev default must not mask a missing worktree bearer."""
    monkeypatch.setenv('MYAH_AGENT_BEARER_TOKEN', 'process-default-token')
    (tmp_path / 'platform-oss').mkdir()
    (tmp_path / 'platform-oss' / '.env').write_text('')
    (tmp_path / '.worktree-env').write_text('export BACKEND_PORT=8189\n')

    from myah.lib.cli.env_loader import load_worktree_env_chain
    env = load_worktree_env_chain(tmp_path)

    assert 'MYAH_AGENT_BEARER_TOKEN' not in env
    assert 'MYAH_ADAPTER_AUTH_KEY' not in env
    assert 'API_SERVER_KEY' not in env
    assert 'MYAH_PLATFORM_BEARER' not in env


def test_worktree_env_aligns_inherited_bearer_aliases_to_platform_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Stale parent-shell bearer aliases must not leak into worktree launches."""
    monkeypatch.setenv('MYAH_ADAPTER_AUTH_KEY', 'stale-adapter-from-other-worktree')
    monkeypatch.setenv('API_SERVER_KEY', 'stale-api-from-other-worktree')
    monkeypatch.setenv('MYAH_PLATFORM_BEARER', 'stale-platform-from-other-worktree')
    (tmp_path / 'platform-oss').mkdir()
    (tmp_path / 'platform-oss' / '.env').write_text('MYAH_AGENT_BEARER_TOKEN=worktree-token\n')
    (tmp_path / '.worktree-env').write_text('export BACKEND_PORT=8189\n')

    from myah.lib.cli.env_loader import load_worktree_env_chain
    env = load_worktree_env_chain(tmp_path)

    assert env['MYAH_AGENT_BEARER_TOKEN'] == 'worktree-token'
    assert env['MYAH_ADAPTER_AUTH_KEY'] == 'worktree-token'
    assert env['API_SERVER_KEY'] == 'worktree-token'
    assert env['MYAH_PLATFORM_BEARER'] == 'worktree-token'


def test_worktree_env_preserves_explicit_bearer_aliases_from_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Explicit aliases in the worktree files beat parent-shell cleanup/normalization."""
    monkeypatch.setenv('MYAH_ADAPTER_AUTH_KEY', 'stale-adapter-from-other-worktree')
    (tmp_path / 'platform-oss').mkdir()
    (tmp_path / 'platform-oss' / '.env').write_text(
        'MYAH_AGENT_BEARER_TOKEN=worktree-token\nMYAH_ADAPTER_AUTH_KEY=explicit-adapter\n'
    )
    (tmp_path / '.worktree-env').write_text('export BACKEND_PORT=8189\n')

    from myah.lib.cli.env_loader import load_worktree_env_chain
    env = load_worktree_env_chain(tmp_path)

    assert env['MYAH_ADAPTER_AUTH_KEY'] == 'explicit-adapter'


def test_worktree_env_aligns_dashboard_session_token_alias(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Dashboard subprocess must receive the token the platform uses for web_call auth."""
    monkeypatch.setenv('HERMES_WEB_SESSION_TOKEN', 'stale-dashboard-token')
    (tmp_path / 'platform-oss').mkdir()
    (tmp_path / 'platform-oss' / '.env').write_text(
        'MYAH_AGENT_BEARER_TOKEN=worktree-token\n'
        'MYAH_HERMES_WEB_SESSION_TOKEN=worktree-web-token\n'
    )
    (tmp_path / '.worktree-env').write_text('export BACKEND_PORT=8189\n')

    from myah.lib.cli.env_loader import load_worktree_env_chain
    env = load_worktree_env_chain(tmp_path)

    assert env['MYAH_HERMES_WEB_SESSION_TOKEN'] == 'worktree-web-token'
    assert env['HERMES_WEB_SESSION_TOKEN'] == 'worktree-web-token'


def test_worktree_env_preserves_explicit_dashboard_session_token_alias(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Explicit dashboard token aliases in worktree files are respected."""
    monkeypatch.setenv('HERMES_WEB_SESSION_TOKEN', 'stale-dashboard-token')
    (tmp_path / 'platform-oss').mkdir()
    (tmp_path / 'platform-oss' / '.env').write_text(
        'MYAH_AGENT_BEARER_TOKEN=worktree-token\n'
        'MYAH_HERMES_WEB_SESSION_TOKEN=platform-web-token\n'
        'HERMES_WEB_SESSION_TOKEN=explicit-dashboard-token\n'
    )
    (tmp_path / '.worktree-env').write_text('export BACKEND_PORT=8189\n')

    from myah.lib.cli.env_loader import load_worktree_env_chain
    env = load_worktree_env_chain(tmp_path)

    assert env['HERMES_WEB_SESSION_TOKEN'] == 'explicit-dashboard-token'


def test_worktree_env_mirrors_deployment_mode_to_public_env(tmp_path: Path) -> None:
    """OSS worktree frontend needs PUBLIC_DEPLOYMENT_MODE=oss for first-run bootstrap."""
    (tmp_path / 'platform-oss').mkdir()
    (tmp_path / 'platform-oss' / '.env').write_text(
        'MYAH_AGENT_BEARER_TOKEN=worktree-token\nMYAH_DEPLOYMENT_MODE=oss\n'
    )
    (tmp_path / '.worktree-env').write_text('export BACKEND_PORT=8189\n')

    from myah.lib.cli.env_loader import load_worktree_env_chain
    env = load_worktree_env_chain(tmp_path)

    assert env['PUBLIC_DEPLOYMENT_MODE'] == 'oss'


def test_raises_when_worktree_env_missing(tmp_path: Path) -> None:
    """If .worktree-env doesn't exist, raise — caller (dev backend/frontend)
    surfaces the error with a hint to run `myah dev worktree create` first."""
    from myah.lib.cli.env_loader import load_worktree_env_chain
    with pytest.raises(RuntimeError, match='worktree create'):
        load_worktree_env_chain(tmp_path)


def test_handles_missing_platform_env_gracefully(tmp_path: Path) -> None:
    """If platform-oss/.env doesn't exist, still load .worktree-env.

    The bearer-fail-fast in the calling command will catch the resulting
    empty MYAH_AGENT_BEARER_TOKEN."""
    (tmp_path / '.worktree-env').write_text('export BACKEND_PORT=8189\n')

    from myah.lib.cli.env_loader import load_worktree_env_chain
    env = load_worktree_env_chain(tmp_path)

    assert env['BACKEND_PORT'] == '8189'
    assert 'MYAH_AGENT_BEARER_TOKEN' not in env or not env['MYAH_AGENT_BEARER_TOKEN']


def test_parse_env_file_handles_comments_and_blanks(tmp_path: Path) -> None:
    """Comments (`# ...`), blank lines, and missing `=` are ignored."""
    env_file = tmp_path / '.env'
    env_file.write_text(
        '# header comment\n'
        '\n'
        'GOOD=value1\n'
        '   # indented comment\n'
        'no_equals_line\n'
        'export EXPORTED=value2\n'
    )

    from myah.lib.cli.env_loader import parse_env_file
    parsed = parse_env_file(env_file)

    assert parsed == {'GOOD': 'value1', 'EXPORTED': 'value2'}


def test_parse_env_file_strips_matching_quotes(tmp_path: Path) -> None:
    """Matched outer single or double quotes are stripped from value."""
    env_file = tmp_path / '.env'
    env_file.write_text(
        'DOUBLE="double quoted"\n'
        "SINGLE='single quoted'\n"
        'UNQUOTED=plain\n'
        'MISMATCHED="unbalanced\n'
    )

    from myah.lib.cli.env_loader import parse_env_file
    parsed = parse_env_file(env_file)

    assert parsed['DOUBLE'] == 'double quoted'
    assert parsed['SINGLE'] == 'single quoted'
    assert parsed['UNQUOTED'] == 'plain'
    # mismatched outer quotes preserved as-is
    assert parsed['MISMATCHED'] == '"unbalanced'


def test_parse_env_file_returns_empty_for_missing_path(tmp_path: Path) -> None:
    """Missing path returns empty dict, not raise."""
    from myah.lib.cli.env_loader import parse_env_file
    assert parse_env_file(tmp_path / 'nonexistent.env') == {}


def test_load_chain_includes_worktree_env_overrides_only_in_provided_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Values present in .worktree-env override os.environ too — that's how
    BACKEND_PORT from the per-branch file beats any stale shell export."""
    monkeypatch.setenv('BACKEND_PORT', '8082')  # stale parent-shell export
    (tmp_path / 'platform-oss').mkdir()
    (tmp_path / 'platform-oss' / '.env').write_text('')
    (tmp_path / '.worktree-env').write_text('export BACKEND_PORT=8189\n')

    from myah.lib.cli.env_loader import load_worktree_env_chain
    env = load_worktree_env_chain(tmp_path)

    assert env['BACKEND_PORT'] == '8189'
