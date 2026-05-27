"""Tests for `myah dev mode {oss,hosted,show}` (Slice 3 PR 3.A Task 3.1).

The lib helper `myah.lib.cli.mode_switch` provides pure file-I/O functions
that are unit-tested in isolation; the Typer command layer at
`myah.cli.dev.mode` is exercised via CliRunner with the resolver +
process-detection helpers mocked at the consumer namespace.

Mock targets follow the consumer-namespace rule established in Slice 2:
patches go on `myah.cli.dev.mode.X` / `myah.lib.cli.mode_switch.X`, never
on the source module.
"""

from __future__ import annotations

from pathlib import Path

from myah import app
from typer.testing import CliRunner

runner = CliRunner()


# ---------------------------------------------------------------------------
# Fixtures — minimal worktree + main-repo shapes
# ---------------------------------------------------------------------------


def _make_worktree(tmp_path: Path, *, env_lines: str = '') -> Path:
    """Materialize a minimal worktree shape rooted at tmp_path."""
    (tmp_path / 'platform-oss').mkdir(exist_ok=True)
    (tmp_path / 'platform-oss' / '.env').write_text(env_lines)
    (tmp_path / '.worktree-env').write_text(
        'export BACKEND_PORT=8189\n'
        'export FRONTEND_PORT=5234\n'
        'export WORKTREE_BRANCH=test/branch\n'
    )
    return tmp_path


def _make_main_repo(tmp_path: Path, *, env_lines: str = '') -> Path:
    """Materialize a main-repo shape with platform-oss/.env contents."""
    main = tmp_path / 'main'
    (main / 'platform-oss').mkdir(parents=True, exist_ok=True)
    (main / 'platform-oss' / '.env').write_text(env_lines)
    return main


# ---------------------------------------------------------------------------
# Library tests — myah.lib.cli.mode_switch
# ---------------------------------------------------------------------------


def test_switch_to_oss_sets_deployment_mode_and_auth_false(tmp_path: Path) -> None:
    """OSS mode pins MYAH_DEPLOYMENT_MODE=oss + MYAH_AUTH=false in the worktree .env."""
    wt = _make_worktree(tmp_path, env_lines='MYAH_AUTH=true\n')

    from myah.lib.cli.mode_switch import switch_to_oss
    switch_to_oss(wt)

    text = (wt / 'platform-oss' / '.env').read_text()
    assert 'MYAH_DEPLOYMENT_MODE=oss' in text
    # MYAH_AUTH should be flipped to false (existing line replaced).
    assert 'MYAH_AUTH=false' in text
    assert 'MYAH_AUTH=true' not in text


def test_switch_to_oss_comments_out_composio_and_honcho_keys(tmp_path: Path) -> None:
    """Existing COMPOSIO_API_KEY=... + HONCHO_* lines get a leading `# ` after OSS switch."""
    wt = _make_worktree(
        tmp_path,
        env_lines=(
            'COMPOSIO_API_KEY=abc123\n'
            'HONCHO_ADMIN_KEY=def456\n'
            'HONCHO_BASE_URL=https://example.com\n'
            'HONCHO_WORKSPACE_ID=ws-789\n'
        ),
    )

    from myah.lib.cli.mode_switch import switch_to_oss
    switch_to_oss(wt)

    text = (wt / 'platform-oss' / '.env').read_text()
    assert '# COMPOSIO_API_KEY=abc123' in text
    assert '# HONCHO_ADMIN_KEY=def456' in text
    assert '# HONCHO_BASE_URL=https://example.com' in text
    assert '# HONCHO_WORKSPACE_ID=ws-789' in text
    # Original uncommented lines should NOT survive.
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith('#'):
            continue
        assert not stripped.startswith('COMPOSIO_API_KEY='), f'leaked: {line!r}'
        assert not stripped.startswith('HONCHO_'), f'leaked: {line!r}'


def test_switch_to_oss_preserves_bearer_tokens(tmp_path: Path) -> None:
    """The three fresh bearer tokens + OAuth key MUST survive a mode switch intact."""
    bearer_lines = (
        'MYAH_AGENT_BEARER_TOKEN=bearer-abc\n'
        'MYAH_HERMES_WEB_SESSION_TOKEN=session-def\n'
        'MYAH_SECRET_KEY=secret-ghi\n'
        'OAUTH_SESSION_TOKEN_ENCRYPTION_KEY=oauth-jkl\n'
        'COMPOSIO_API_KEY=will-be-commented\n'
    )
    wt = _make_worktree(tmp_path, env_lines=bearer_lines)

    from myah.lib.cli.mode_switch import switch_to_oss
    switch_to_oss(wt)

    text = (wt / 'platform-oss' / '.env').read_text()
    assert 'MYAH_AGENT_BEARER_TOKEN=bearer-abc' in text
    assert 'MYAH_HERMES_WEB_SESSION_TOKEN=session-def' in text
    assert 'MYAH_SECRET_KEY=secret-ghi' in text
    assert 'OAUTH_SESSION_TOKEN_ENCRYPTION_KEY=oauth-jkl' in text


def test_switch_to_hosted_sets_auth_true_and_comments_out_deployment_mode(
    tmp_path: Path,
) -> None:
    """Hosted mode flips MYAH_AUTH=true and comments out MYAH_DEPLOYMENT_MODE."""
    wt = _make_worktree(
        tmp_path,
        env_lines='MYAH_DEPLOYMENT_MODE=oss\nMYAH_AUTH=false\n',
    )
    main = _make_main_repo(tmp_path, env_lines='')

    from myah.lib.cli.mode_switch import switch_to_hosted
    switch_to_hosted(wt, main)

    text = (wt / 'platform-oss' / '.env').read_text()
    assert 'MYAH_AUTH=true' in text
    assert 'MYAH_AUTH=false' not in text
    # Deployment mode is commented out (so flip-back is easy) or removed entirely.
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith('#'):
            continue
        assert not stripped.startswith('MYAH_DEPLOYMENT_MODE='), f'leaked: {line!r}'


def test_switch_to_hosted_copies_composio_and_honcho_from_main_env(tmp_path: Path) -> None:
    """If main has COMPOSIO_API_KEY + HONCHO_* set, hosted mode copies them in."""
    wt = _make_worktree(tmp_path, env_lines='MYAH_DEPLOYMENT_MODE=oss\nMYAH_AUTH=false\n')
    main = _make_main_repo(
        tmp_path,
        env_lines=(
            'COMPOSIO_API_KEY=main-composio\n'
            'HONCHO_ADMIN_KEY=main-honcho-admin\n'
            'HONCHO_BASE_URL=https://main.honcho\n'
            'HONCHO_WORKSPACE_ID=main-ws\n'
        ),
    )

    from myah.lib.cli.mode_switch import switch_to_hosted
    switch_to_hosted(wt, main)

    text = (wt / 'platform-oss' / '.env').read_text()
    assert 'COMPOSIO_API_KEY=main-composio' in text
    assert 'HONCHO_ADMIN_KEY=main-honcho-admin' in text
    assert 'HONCHO_BASE_URL=https://main.honcho' in text
    assert 'HONCHO_WORKSPACE_ID=main-ws' in text


def test_switch_to_hosted_leaves_worktree_alone_when_main_lacks_secrets(tmp_path: Path) -> None:
    """When main has no COMPOSIO/HONCHO values, hosted mode does not clobber anything."""
    wt = _make_worktree(
        tmp_path,
        env_lines='MYAH_DEPLOYMENT_MODE=oss\nMYAH_AUTH=false\n# COMPOSIO_API_KEY=pre-existing\n',
    )
    main = _make_main_repo(tmp_path, env_lines='')

    from myah.lib.cli.mode_switch import switch_to_hosted
    switch_to_hosted(wt, main)

    text = (wt / 'platform-oss' / '.env').read_text()
    # No injection — main had nothing to give.
    uncommented_keys = [
        line.split('=', 1)[0].strip()
        for line in text.splitlines()
        if '=' in line and not line.strip().startswith('#')
    ]
    assert 'COMPOSIO_API_KEY' not in uncommented_keys
    assert 'HONCHO_ADMIN_KEY' not in uncommented_keys


def test_switch_to_hosted_generates_oauth_key_if_missing(tmp_path: Path) -> None:
    """Hosted mode ensures OAUTH_SESSION_TOKEN_ENCRYPTION_KEY exists (fresh if absent)."""
    wt = _make_worktree(tmp_path, env_lines='MYAH_AUTH=false\n')
    main = _make_main_repo(tmp_path)

    from myah.lib.cli.mode_switch import switch_to_hosted
    switch_to_hosted(wt, main)

    text = (wt / 'platform-oss' / '.env').read_text()
    # Find the line + extract the value.
    oauth_value = None
    for line in text.splitlines():
        if line.startswith('OAUTH_SESSION_TOKEN_ENCRYPTION_KEY='):
            oauth_value = line.split('=', 1)[1].strip()
            break
    assert oauth_value is not None, 'OAUTH_SESSION_TOKEN_ENCRYPTION_KEY missing after hosted switch'
    assert len(oauth_value) >= 16, f'fresh OAuth key too short: {oauth_value!r}'


def test_switch_to_hosted_preserves_existing_oauth_key(tmp_path: Path) -> None:
    """If OAuth key already set, hosted switch must NOT rotate it."""
    wt = _make_worktree(
        tmp_path,
        env_lines='OAUTH_SESSION_TOKEN_ENCRYPTION_KEY=existing-oauth-key\nMYAH_AUTH=false\n',
    )
    main = _make_main_repo(tmp_path)

    from myah.lib.cli.mode_switch import switch_to_hosted
    switch_to_hosted(wt, main)

    text = (wt / 'platform-oss' / '.env').read_text()
    assert 'OAUTH_SESSION_TOKEN_ENCRYPTION_KEY=existing-oauth-key' in text


def test_get_current_mode_returns_oss_when_deployment_mode_is_oss(tmp_path: Path) -> None:
    wt = _make_worktree(tmp_path, env_lines='MYAH_DEPLOYMENT_MODE=oss\n')

    from myah.lib.cli.mode_switch import get_current_mode
    assert get_current_mode(wt) == 'oss'


def test_get_current_mode_returns_hosted_when_deployment_mode_unset(tmp_path: Path) -> None:
    wt = _make_worktree(tmp_path, env_lines='MYAH_AUTH=true\n')

    from myah.lib.cli.mode_switch import get_current_mode
    assert get_current_mode(wt) == 'hosted'


def test_get_current_mode_returns_hosted_when_deployment_mode_commented_out(tmp_path: Path) -> None:
    """A commented `# MYAH_DEPLOYMENT_MODE=oss` line means hosted mode."""
    wt = _make_worktree(tmp_path, env_lines='# MYAH_DEPLOYMENT_MODE=oss\nMYAH_AUTH=true\n')

    from myah.lib.cli.mode_switch import get_current_mode
    assert get_current_mode(wt) == 'hosted'


def test_switch_round_trip_hosted_oss_hosted_preserves_secrets(tmp_path: Path) -> None:
    """A full hosted → oss → hosted round-trip preserves bearer tokens + OAuth key.

    Regression gate: mode switching must NEVER touch bearer/signing tokens or
    OAuth keys. Per-direction tests cover this individually; the round-trip
    test catches subtle bugs where comment-out + uncomment + re-comment
    leaves residue on unrelated lines.
    """
    worktree = tmp_path / 'wt'
    main = tmp_path / 'main'
    (worktree / 'platform-oss').mkdir(parents=True)
    main.mkdir()
    (main / 'platform-oss').mkdir()
    (main / 'platform-oss' / '.env').write_text(
        'COMPOSIO_API_KEY=composio-main-key\n'
        'HONCHO_ADMIN_KEY=honcho-main-key\n'
    )

    # Initial hosted state with full secret set
    initial = (
        'MYAH_AUTH=true\n'
        'MYAH_AGENT_BEARER_TOKEN=bearer-aaa\n'
        'MYAH_HERMES_WEB_SESSION_TOKEN=session-bbb\n'
        'MYAH_SECRET_KEY=secret-ccc\n'
        'OAUTH_SESSION_TOKEN_ENCRYPTION_KEY=oauth-ddd\n'
        'COMPOSIO_API_KEY=composio-original\n'
        'HONCHO_ADMIN_KEY=honcho-original\n'
    )
    (worktree / 'platform-oss' / '.env').write_text(initial)

    from myah.lib.cli.mode_switch import get_current_mode, switch_to_hosted, switch_to_oss

    # hosted → oss
    switch_to_oss(worktree)
    assert get_current_mode(worktree) == 'oss'

    # oss → hosted (re-populates composio + honcho from main's env)
    switch_to_hosted(worktree, main)
    assert get_current_mode(worktree) == 'hosted'

    # All four bearer/signing tokens + OAuth key MUST be unchanged
    final = (worktree / 'platform-oss' / '.env').read_text()
    assert 'MYAH_AGENT_BEARER_TOKEN=bearer-aaa' in final
    assert 'MYAH_HERMES_WEB_SESSION_TOKEN=session-bbb' in final
    assert 'MYAH_SECRET_KEY=secret-ccc' in final
    assert 'OAUTH_SESSION_TOKEN_ENCRYPTION_KEY=oauth-ddd' in final


# ---------------------------------------------------------------------------
# CLI tests — myah.cli.dev.mode
# ---------------------------------------------------------------------------


def test_mode_show_prints_current_mode_and_env_diffs(tmp_path: Path, mocker) -> None:
    wt = _make_worktree(
        tmp_path,
        env_lines=(
            'MYAH_DEPLOYMENT_MODE=oss\n'
            'MYAH_AUTH=false\n'
            'COMPOSIO_API_KEY=secret-value-not-shown\n'
            'OAUTH_SESSION_TOKEN_ENCRYPTION_KEY=another-secret\n'
        ),
    )
    mocker.patch('myah.cli.dev.mode.get_worktree_path', return_value=wt)

    result = runner.invoke(app, ['dev', 'mode', 'show'])

    assert result.exit_code == 0, result.output
    # The "current mode" line should mention oss.
    assert 'oss' in result.output.lower()
    assert 'MYAH_DEPLOYMENT_MODE' in result.output
    assert 'MYAH_AUTH' in result.output
    # Redacted: literal secret values must NOT leak.
    assert 'secret-value-not-shown' not in result.output
    assert 'another-secret' not in result.output


def test_mode_show_prints_hosted_mode_when_deployment_mode_unset(tmp_path: Path, mocker) -> None:
    """`mode show` reports 'hosted' when MYAH_DEPLOYMENT_MODE is unset (or commented)."""
    wt = _make_worktree(
        tmp_path,
        env_lines=(
            'MYAH_AUTH=true\n'
            'COMPOSIO_API_KEY=set-in-hosted\n'
        ),
    )
    mocker.patch('myah.cli.dev.mode.get_worktree_path', return_value=wt)
    mocker.patch('myah.cli.dev.mode._is_port_listening', return_value=False)

    result = runner.invoke(app, ['dev', 'mode', 'show'])

    assert result.exit_code == 0, result.output
    assert 'hosted' in result.output.lower()
    # COMPOSIO redaction: literal value must NOT leak; "set" marker should appear.
    assert 'set-in-hosted' not in result.output
    assert 'set' in result.output.lower()


def test_mode_oss_command_invokes_switch_and_prints_restart_hint_if_running(
    tmp_path: Path, mocker
) -> None:
    wt = _make_worktree(tmp_path, env_lines='MYAH_AUTH=true\n')
    mocker.patch('myah.cli.dev.mode.get_worktree_path', return_value=wt)
    # Pretend the backend port is listening.
    mocker.patch(
        'myah.cli.dev.mode._is_port_listening',
        side_effect=lambda port: port == 8189,
    )

    result = runner.invoke(app, ['dev', 'mode', 'oss'])

    assert result.exit_code == 0, result.output
    # The library side-effect happened: .env was rewritten.
    text = (wt / 'platform-oss' / '.env').read_text()
    assert 'MYAH_DEPLOYMENT_MODE=oss' in text
    assert 'MYAH_AUTH=false' in text
    # And the restart hint appeared because backend was up.
    assert 'restart' in result.output.lower()
    assert '8189' in result.output


def test_mode_hosted_command_invokes_switch_and_no_restart_hint_when_idle(
    tmp_path: Path, mocker
) -> None:
    wt = _make_worktree(tmp_path, env_lines='MYAH_DEPLOYMENT_MODE=oss\nMYAH_AUTH=false\n')
    main = _make_main_repo(tmp_path)
    mocker.patch('myah.cli.dev.mode.get_worktree_path', return_value=wt)
    mocker.patch('myah.cli.dev.mode.resolve_main_repo_root', return_value=main)
    mocker.patch('myah.cli.dev.mode._is_port_listening', return_value=False)

    result = runner.invoke(app, ['dev', 'mode', 'hosted'])

    assert result.exit_code == 0, result.output
    text = (wt / 'platform-oss' / '.env').read_text()
    assert 'MYAH_AUTH=true' in text
    # No restart hint when both ports idle.
    assert 'restart with' not in result.output.lower()


def test_mode_outside_worktree_exits_with_code_2(tmp_path: Path, mocker) -> None:
    mocker.patch(
        'myah.cli.dev.mode.get_worktree_path',
        side_effect=RuntimeError('not in a worktree'),
    )

    result = runner.invoke(app, ['dev', 'mode', 'show'])

    assert result.exit_code == 2, result.output
    assert 'worktree' in result.output.lower()
