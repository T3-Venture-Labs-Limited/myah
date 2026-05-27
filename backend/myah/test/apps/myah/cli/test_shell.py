"""Tests for the subprocess indirection layer."""

import pytest

from myah.lib.cli.shell import ShellError, ShellResult, run


def test_run_returns_shell_result_dataclass() -> None:
    """run() must return a ShellResult with returncode/stdout/stderr fields."""
    result = run(['true'])
    assert isinstance(result, ShellResult)
    assert result.returncode == 0
    assert result.stdout == ''
    assert result.stderr == ''


def test_run_captures_stdout() -> None:
    """stdout is captured to a string (not bytes)."""
    result = run(['echo', 'hello world'])
    assert result.returncode == 0
    assert result.stdout.strip() == 'hello world'


def test_run_captures_stderr() -> None:
    """stderr is captured separately."""
    result = run(['sh', '-c', 'echo to-stderr 1>&2'])
    assert result.returncode == 0
    assert result.stderr.strip() == 'to-stderr'


def test_run_returncode_on_failure() -> None:
    """A failing command returns non-zero but doesn't raise by default."""
    result = run(['false'])
    assert result.returncode != 0


def test_run_check_true_raises_on_failure() -> None:
    """check=True raises ShellError on non-zero exit."""
    with pytest.raises(ShellError) as excinfo:
        run(['false'], check=True)
    assert excinfo.value.returncode != 0


def test_run_accepts_env_override() -> None:
    """The env kwarg sets the subprocess environment."""
    result = run(['sh', '-c', 'echo $MY_TEST_VAR'], env={'MY_TEST_VAR': 'spam'})
    assert result.returncode == 0
    assert result.stdout.strip() == 'spam'


def test_run_accepts_cwd_override(tmp_path) -> None:
    """The cwd kwarg sets the subprocess working directory."""
    result = run(['pwd'], cwd=str(tmp_path))
    assert result.returncode == 0
    assert result.stdout.strip() == str(tmp_path)


def test_run_passes_input_to_stdin() -> None:
    """The input kwarg feeds the given string to the subprocess's stdin."""
    result = run(['cat'], input='hello-from-stdin\n')
    assert result.returncode == 0
    assert result.stdout.strip() == 'hello-from-stdin'


def test_run_timeout_raises_subprocess_timeout_expired() -> None:
    """A timeout raises subprocess.TimeoutExpired (not wrapped) — documented leak.

    We deliberately let TimeoutExpired propagate unwrapped so callers can
    access its .timeout attribute. ShellError is only for non-zero exits.
    """
    import subprocess
    with pytest.raises(subprocess.TimeoutExpired):
        run(['sleep', '5'], timeout=0.1)


def test_shell_error_exposes_full_context() -> None:
    """ShellError carries cmd, returncode, stdout, stderr on the instance."""
    with pytest.raises(ShellError) as excinfo:
        run(['sh', '-c', 'echo to-out; echo to-err 1>&2; exit 7'], check=True)
    err = excinfo.value
    assert err.cmd == ['sh', '-c', 'echo to-out; echo to-err 1>&2; exit 7']
    assert err.returncode == 7
    assert 'to-out' in err.stdout
    assert 'to-err' in err.stderr
