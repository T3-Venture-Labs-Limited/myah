"""Cross-tier drift check — contract enums match the Hermes submodule.

Phase 3 of Workstream I introduces ``HermesPlatform``, an enum that mirrors
the upstream Hermes ``Platform`` enum at ``agent/hermes/gateway/config.py``.
The ``HermesPlatform`` enum exists so the platform backend and frontend can
narrow on platform identifiers without coordinating with Hermes on every
new value — but it has to stay in sync.

This test imports the upstream enum at runtime and asserts:

1. **No drop** — every value upstream defines is present in the contract.
2. **No invention** — the contract does not declare a value upstream lacks.

Failure means Hermes added (or removed) a platform identifier; the action
is to update ``shared.contract.enums.HermesPlatform`` in the same PR that
bumps the submodule SHA. CI red catches the drift before merge.

Phase 5 (this file) was authored before Phase 3, so the import is wrapped
in ``pytest.importorskip`` for graceful skipping until Phase 3 lands. Once
Phase 3 is merged this test becomes mandatory.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# ── Upstream Platform enum loader ──────────────────────────────────────────
# Plan B PR B (2026-05-12): the agent/hermes/ submodule has been deleted.
# Hermes is now installed via pip (as a dep of myah-hermes-plugin), so
# `gateway.config` is importable directly without manipulating sys.path.

_REPO_ROOT = Path(__file__).resolve().parents[4]


def _import_upstream_platform_enum() -> type:
    """Return the upstream ``Platform`` enum class, skipping the test if absent."""
    try:
        from gateway.config import Platform  # type: ignore[import-not-found]
    except ImportError as exc:
        pytest.skip(
            f'Could not import upstream Platform enum: {exc}. '
            'Ensure hermes-agent is installed (`pip install -e myah-hermes-plugin`).',
        )
    return Platform


# ── HermesPlatform mirror tests (Phase 3 dependency) ────────────────────────


def test_every_upstream_platform_value_is_in_the_contract() -> None:
    """Every value of upstream ``Platform`` must appear in ``HermesPlatform``.

    A drop would mean the platform's allow-lists silently reject a new
    Hermes-supported platform — for example, a new bridge added to
    Hermes that the platform's catalog endpoint refuses to surface.
    """
    enums_module = pytest.importorskip(
        'shared.contract.enums',
        reason='Phase 3 contract enums not yet present',
    )
    hermes_platform = getattr(enums_module, 'HermesPlatform', None)
    if hermes_platform is None:
        pytest.skip(
            'Phase 3 HermesPlatform enum not yet present in shared.contract.enums'
        )

    upstream = _import_upstream_platform_enum()
    upstream_values = {member.value for member in upstream}
    contract_values = {member.value for member in hermes_platform}

    missing = upstream_values - contract_values
    assert not missing, (
        f'Upstream Platform values absent from HermesPlatform: {sorted(missing)}. '
        f'Add them to ``shared.contract.enums.HermesPlatform`` in the same PR that '
        f'bumps the agent/hermes submodule SHA.'
    )


def test_contract_does_not_invent_platform_values() -> None:
    """``HermesPlatform`` must not declare values upstream Hermes lacks.

    A contract-only platform would propagate a phantom identifier through
    the typed surface, and any backend code routing on it would silently
    fail because Hermes itself doesn't know the value.
    """
    enums_module = pytest.importorskip(
        'shared.contract.enums',
        reason='Phase 3 contract enums not yet present',
    )
    hermes_platform = getattr(enums_module, 'HermesPlatform', None)
    if hermes_platform is None:
        pytest.skip(
            'Phase 3 HermesPlatform enum not yet present in shared.contract.enums'
        )

    upstream = _import_upstream_platform_enum()
    upstream_values = {member.value for member in upstream}
    contract_values = {member.value for member in hermes_platform}

    invented = contract_values - upstream_values
    assert not invented, (
        f'HermesPlatform contains values not in upstream Platform: {sorted(invented)}. '
        f'Either upstream removed them (delete from contract) or the contract '
        f'invented them (which breaks routing — remove).'
    )


def test_myah_value_is_present() -> None:
    """The MYAH-specific platform identifier must exist on both sides.

    This is the value Myah identifies as on the wire. Without it, Hermes's
    cron delivery, send_message_tool routing, and channel directory all
    break. Catching its absence at contract time is the cheapest possible
    safety net.
    """
    enums_module = pytest.importorskip(
        'shared.contract.enums',
        reason='Phase 3 contract enums not yet present',
    )
    hermes_platform = getattr(enums_module, 'HermesPlatform', None)
    if hermes_platform is None:
        pytest.skip(
            'Phase 3 HermesPlatform enum not yet present in shared.contract.enums'
        )

    upstream = _import_upstream_platform_enum()
    upstream_values = {member.value for member in upstream}
    contract_values = {member.value for member in hermes_platform}

    assert 'myah' in upstream_values, (
        'Upstream Hermes Platform enum is missing the ``MYAH`` value. The '
        'fork divergence between Myah and upstream Hermes is significant — '
        'check ``agent/hermes/gateway/config.py``.'
    )
    assert 'myah' in contract_values, (
        'Contract HermesPlatform enum is missing the ``MYAH`` value.'
    )
