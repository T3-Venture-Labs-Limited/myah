"""Regression gate for the Slice 2 bash deprecation prologues.

These tests are STRUCTURAL — they assert the deprecation warnings exist
in the source text of both bash scripts. They do NOT execute the scripts.

Rationale: a future refactor that accidentally removes the deprecation
warning would silently re-bless the bash workflow as the canonical path,
defeating the deprecation message. This test fails fast.
"""

from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[7]  # walk up from test file to repo root
_PLATFORM_OSS = Path(__file__).resolve().parents[6]  # platform-oss/ root
_SETUP_WORKTREE_SH = _REPO_ROOT / 'scripts' / 'setup-worktree.sh'
_DEV_WORKTREE_SH = _REPO_ROOT / 'scripts' / 'dev-worktree.sh'
_DEV_OSS_SH = _REPO_ROOT / 'scripts' / 'dev-oss.sh'
_SETUP_MYAH_OSS_SH = _PLATFORM_OSS / 'scripts' / 'setup-myah-oss.sh'
_VERIFY_PLUGINS_SH = _PLATFORM_OSS / 'scripts' / 'verify-hermes-plugins-install.sh'


def test_setup_worktree_sh_contains_deprecation_warning() -> None:
    """setup-worktree.sh must announce its deprecation prominently."""
    text = _SETUP_WORKTREE_SH.read_text()
    assert 'DEPRECATED' in text, 'setup-worktree.sh missing DEPRECATED token'
    assert 'myah dev worktree create' in text, (
        'setup-worktree.sh must point users at the canonical replacement command'
    )
    assert 'will be removed in Slice 6' in text or 'removed in Slice 6' in text


def test_dev_worktree_sh_contains_deprecation_warning() -> None:
    """dev-worktree.sh must announce its deprecation prominently."""
    text = _DEV_WORKTREE_SH.read_text()
    assert 'DEPRECATED' in text
    assert 'myah dev backend' in text  # the verb-mapping table
    assert 'myah dev logs' in text


def test_dev_worktree_sh_lists_all_verb_mappings() -> None:
    """The verb-mapping table must cover every documented verb."""
    text = _DEV_WORKTREE_SH.read_text()
    for verb in ('backend', 'frontend', 'both', 'restart', 'stop', 'status', 'logs'):
        assert f'myah dev {verb}' in text, (
            f'dev-worktree.sh missing replacement mapping for verb `{verb}`'
        )


def test_dev_oss_sh_contains_deprecation_warning() -> None:
    """dev-oss.sh must announce its deprecation prominently."""
    text = _DEV_OSS_SH.read_text()
    assert 'DEPRECATED' in text
    assert 'myah dev oss' in text  # canonical replacement command


def test_dev_oss_sh_lists_all_verb_mappings() -> None:
    """The verb-mapping table must cover every documented verb."""
    text = _DEV_OSS_SH.read_text()
    # Primary verbs map directly to 'myah dev oss <verb>'.
    for verb in ('up', 'down', 'restart', 'status'):
        assert f'myah dev oss {verb}' in text, (
            f'dev-oss.sh missing replacement mapping for verb `{verb}`'
        )
    # logs maps to unified myah dev logs.
    assert 'myah dev logs' in text
    # doctor maps to top-level myah doctor.
    assert 'myah doctor' in text


def test_setup_myah_oss_sh_contains_deprecation_warning() -> None:
    """setup-myah-oss.sh must announce its deprecation prominently."""
    text = _SETUP_MYAH_OSS_SH.read_text()
    assert 'DEPRECATED' in text, 'setup-myah-oss.sh missing DEPRECATED token'
    assert 'myah install' in text, (
        'setup-myah-oss.sh must point users at the canonical replacement command'
    )
    assert 'will be removed in Slice 6' in text or 'removed in Slice 6' in text


def test_setup_myah_oss_sh_lists_flag_mapping() -> None:
    """The flag-mapping section must cover both --rotate and the no-flag default."""
    text = _SETUP_MYAH_OSS_SH.read_text()
    # --rotate flag must map to `myah install --rotate`
    assert 'myah install --rotate' in text, (
        'setup-myah-oss.sh missing replacement mapping for `--rotate`'
    )
    # No-flag invocation must map to bare `myah install`
    assert 'myah install' in text
    # Generic fallback must point at help
    assert 'myah install --help' in text, (
        'setup-myah-oss.sh missing fallback mapping to `myah install --help`'
    )


def test_verify_hermes_plugins_install_sh_contains_deprecation_warning() -> None:
    """verify-hermes-plugins-install.sh must announce its deprecation prominently."""
    text = _VERIFY_PLUGINS_SH.read_text()
    assert 'DEPRECATED' in text, 'verify-hermes-plugins-install.sh missing DEPRECATED token'
    # Both replacement commands must be cited — they cover complementary verification needs.
    assert 'myah plugins list' in text, (
        'verify-hermes-plugins-install.sh must point users at `myah plugins list`'
    )
    assert 'myah doctor' in text, (
        'verify-hermes-plugins-install.sh must point users at `myah doctor`'
    )
    assert 'will be removed in Slice 6' in text or 'removed in Slice 6' in text


def test_deprecation_warnings_go_to_stderr_not_stdout() -> None:
    """The warning heredoc must redirect to >&2.

    Stdout-piped output of dev-worktree.sh/setup-worktree.sh/dev-oss.sh/
    setup-myah-oss.sh/verify-hermes-plugins-install.sh (e.g. for parsing
    in a script) must NOT be polluted by the deprecation banner.
    """
    for script in (
        _SETUP_WORKTREE_SH,
        _DEV_WORKTREE_SH,
        _DEV_OSS_SH,
        _SETUP_MYAH_OSS_SH,
        _VERIFY_PLUGINS_SH,
    ):
        text = script.read_text()
        # The pattern `cat >&2 <<` is the canonical "heredoc to stderr".
        assert 'cat >&2 <<DEPRECATION' in text, (
            f'{script.name} deprecation block must redirect to stderr (cat >&2 <<DEPRECATION)'
        )


def test_legacy_behavior_preserved() -> None:
    """The deprecation block must come BEFORE the existing legacy logic.

    A naive 'replace the file body with a stub' refactor would lose the
    backward-compat behavior during the deprecation period. Assert that
    the legacy markers (the symlink lines in setup-worktree.sh; the verb
    case statement in dev-worktree.sh; the prerequisite check + secret
    generation in setup-myah-oss.sh) still exist after the deprecation.
    """
    setup_text = _SETUP_WORKTREE_SH.read_text()
    assert 'ln -s "$MAIN/platform-oss/.venv"' in setup_text, (
        'setup-worktree.sh legacy symlink behavior was removed instead of '
        'preserved alongside the deprecation warning'
    )

    dev_text = _DEV_WORKTREE_SH.read_text()
    # The script ends in a big case statement that handles each verb.
    assert '_start_backend' in dev_text
    assert '_start_frontend' in dev_text
    assert 'case "$MODE"' in dev_text

    # setup-myah-oss.sh: the prerequisite checks + the 8-phase install body
    # must still be intact after the deprecation prologue.
    setup_oss_text = _SETUP_MYAH_OSS_SH.read_text()
    assert '0. Prerequisite checks' in setup_oss_text, (
        'setup-myah-oss.sh phase-0 prereq check was removed instead of '
        'preserved alongside the deprecation warning'
    )
    assert 'MYAH_AGENT_BEARER_TOKEN' in setup_oss_text, (
        'setup-myah-oss.sh secret-generation logic was removed'
    )
    assert 'MYAH_OSS_SETUP_ENV_ONLY' in setup_oss_text, (
        'setup-myah-oss.sh env-only escape hatch was removed'
    )

    # verify-hermes-plugins-install.sh: the install-attempt + plugin-dir
    # inspection logic must still be intact after the deprecation prologue.
    verify_text = _VERIFY_PLUGINS_SH.read_text()
    assert 'hermes plugins install' in verify_text, (
        'verify-hermes-plugins-install.sh install-attempt logic was removed'
    )
    assert 'plugin.yaml' in verify_text, (
        'verify-hermes-plugins-install.sh manifest inspection was removed'
    )


def test_bash_syntax_remains_valid() -> None:
    """`bash -n` on all five scripts must still succeed after editing."""
    import subprocess

    for script in (
        _SETUP_WORKTREE_SH,
        _DEV_WORKTREE_SH,
        _DEV_OSS_SH,
        _SETUP_MYAH_OSS_SH,
        _VERIFY_PLUGINS_SH,
    ):
        result = subprocess.run(
            ['bash', '-n', str(script)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f'`bash -n {script.name}` failed:\n{result.stderr}'
        )
