"""Tests for the AuxTask, ApprovalOption, and HermesPlatform enums.

These three enums close out Phase 3 of Workstream I. Each one mirrors a
piece of wire vocabulary the platform exchanges with Hermes:

* ``AuxTask`` — the task names dispatched via ``POST /myah/v1/aux/{task}``.
  Must match Hermes' own allow-list at
  ``agent/hermes/gateway/platforms/myah.py::_AUX_ALLOWED_TASKS``.
* ``ApprovalOption`` — the choices the frontend sends to
  ``POST /openai/chat/confirm`` (and downstream to
  ``/myah/v1/confirm/{stream_id}``).
* ``HermesPlatform`` — a mirror of ``agent/hermes/gateway/config.py::Platform``.
  Includes a runtime cross-reference test that imports the upstream enum
  directly and asserts set equality.

The runtime upstream import for ``HermesPlatform`` doubles as a fast drift
detector: if Hermes adds a platform value upstream, this test fails on the
next submodule bump and forces a coordinated update.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from shared.contract import (
    AUX_ALLOWED_TASKS,
    ApprovalOption,
    AuxTask,
    HermesPlatform,
)
from shared.contract.enums import (
    AUX_ALLOWED_TASKS as AUX_ALLOWED_TASKS_DIRECT,
)
from shared.contract.enums import (
    ApprovalOption as ApprovalOptionDirect,
)
from shared.contract.enums import (
    AuxTask as AuxTaskDirect,
)
from shared.contract.enums import (
    HermesPlatform as HermesPlatformDirect,
)

# ── AuxTask ──────────────────────────────────────────────────────────


EXPECTED_AUX_TASK_VALUES: frozenset[str] = frozenset({
    'title_generation',
    'follow_up_generation',
})


def test_aux_task_values() -> None:
    """The enum carries exactly the two tasks the platform forwards today."""
    actual = {member.value for member in AuxTask}
    assert actual == EXPECTED_AUX_TASK_VALUES, (
        f'AuxTask drift: missing={EXPECTED_AUX_TASK_VALUES - actual} '
        f'extra={actual - EXPECTED_AUX_TASK_VALUES}'
    )


def test_aux_allowed_tasks_matches_enum() -> None:
    """``AUX_ALLOWED_TASKS`` is a frozenset of the enum's string values."""
    assert isinstance(AUX_ALLOWED_TASKS, frozenset)
    assert AUX_ALLOWED_TASKS == {member.value for member in AuxTask}
    # The package re-export and the direct module attribute are the same object.
    assert AUX_ALLOWED_TASKS is AUX_ALLOWED_TASKS_DIRECT


def test_aux_task_round_trip() -> None:
    """``str -> enum -> str`` round-trips for every member."""
    for member in AuxTask:
        assert AuxTask(member.value) is member
        assert str(member.value) == member.value


def test_aux_task_re_export_identity() -> None:
    """Re-export from ``shared.contract`` matches the direct module class."""
    assert AuxTask is AuxTaskDirect


def test_aux_task_matches_hermes_upstream() -> None:
    """Cross-tier sanity: contract values match the upstream allow-list.

    The upstream allow-list lives as a plain ``frozenset`` literal at
    ``agent/hermes/gateway/platforms/myah.py:_AUX_ALLOWED_TASKS``. We can't
    cleanly import the surrounding aiohttp class without the full Hermes
    runtime, so we read the source file and grep for the literal — same
    spirit as the cross-reference test for ``HermesPlatform`` below, just
    cheaper.
    """
    upstream_path = (
        Path(__file__).resolve().parents[4]
        / 'agent'
        / 'hermes'
        / 'gateway'
        / 'platforms'
        / 'myah.py'
    )
    if not upstream_path.exists():
        pytest.skip(f'Hermes submodule not available at {upstream_path}')

    text = upstream_path.read_text(encoding='utf-8')
    for member in AuxTask:
        assert f"'{member.value}'" in text, (
            f'AuxTask.{member.name} ({member.value!r}) is not present in '
            f'{upstream_path}. The platform allow-list and the Hermes '
            'allow-list MUST stay in sync.'
        )


# ── ApprovalOption ───────────────────────────────────────────────────


EXPECTED_APPROVAL_OPTIONS: frozenset[str] = frozenset({
    'approve',
    'deny',
    'approve_session',
})


def test_approval_option_values() -> None:
    """Three fixed choices: approve / deny / approve_session."""
    actual = {member.value for member in ApprovalOption}
    assert actual == EXPECTED_APPROVAL_OPTIONS, (
        f'ApprovalOption drift: '
        f'missing={EXPECTED_APPROVAL_OPTIONS - actual} '
        f'extra={actual - EXPECTED_APPROVAL_OPTIONS}'
    )


@pytest.mark.parametrize('value', sorted(EXPECTED_APPROVAL_OPTIONS))
def test_approval_option_round_trip(value: str) -> None:
    """Each wire string round-trips via ``ApprovalOption(value).value``."""
    member = ApprovalOption(value)
    assert member.value == value
    assert member == value  # str-subclass equality


def test_approval_option_unknown_raises() -> None:
    """An unknown choice raises ``ValueError`` (used by the /chat/confirm 400)."""
    with pytest.raises(ValueError):
        ApprovalOption('maybe')


def test_approval_option_re_export_identity() -> None:
    assert ApprovalOption is ApprovalOptionDirect


# ── HermesPlatform ───────────────────────────────────────────────────


def _load_upstream_platform_enum():
    """Import ``Platform`` from ``agent/hermes/gateway/config.py`` at runtime.

    The submodule isn't on ``sys.path`` by default — this helper splices it
    on for the duration of the test. We restore the path on the way out so
    nothing else in the suite leaks Hermes-internal modules.
    """
    repo_root = Path(__file__).resolve().parents[4]
    hermes_root = repo_root / 'agent' / 'hermes'
    if not hermes_root.exists():
        pytest.skip(f'Hermes submodule not available at {hermes_root}')

    inserted = [str(hermes_root)]
    sys.path.insert(0, str(hermes_root))
    try:
        # ``hermes_cli.config`` is imported as a side effect of ``gateway.config``;
        # ensure both are available.
        from gateway.config import Platform  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover — surfaces useful skip reason
        pytest.skip(f'Could not import upstream Platform enum: {exc!r}')
        return None
    finally:
        for entry in inserted:
            try:
                sys.path.remove(entry)
            except ValueError:
                pass
    return Platform


def test_hermes_platform_includes_myah() -> None:
    """``HermesPlatform.MYAH`` is the wire identifier for this platform."""
    assert HermesPlatform.MYAH.value == 'myah'


def test_hermes_platform_re_export_identity() -> None:
    assert HermesPlatform is HermesPlatformDirect


def test_hermes_platform_matches_upstream() -> None:
    """Every value in upstream ``Platform`` must appear in ``HermesPlatform``.

    This is the canonical drift test promised by Phase 5 of the workstream
    plan, run preemptively here so Phase 3 lands aligned. When Hermes adds
    a new platform value, this test fails on the next submodule bump and
    forces a coordinated update.
    """
    upstream = _load_upstream_platform_enum()
    if upstream is None:  # pragma: no cover — pytest.skip handled by helper
        return

    upstream_values = {member.value for member in upstream}
    contract_values = {member.value for member in HermesPlatform}

    missing = upstream_values - contract_values
    extra = contract_values - upstream_values

    assert not missing, (
        f'HermesPlatform is MISSING upstream values: {sorted(missing)}. '
        'Hermes added these to ``gateway/config.py::Platform``; mirror them '
        'here in ``platform/shared/contract/enums.py``.'
    )
    assert not extra, (
        f'HermesPlatform has EXTRA values not in upstream: {sorted(extra)}. '
        'Either the upstream renamed/removed a platform (drop it here too) '
        'or this contract drifted ahead of Hermes (re-sync).'
    )
