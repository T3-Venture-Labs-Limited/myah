"""Tests for OSS-mode helpers in hermes_web.py.

OSS mode (MYAH_DEPLOYMENT_MODE=oss) skips per-user container spawning
entirely and forwards chat / admin / proxy requests to a single
host-side Hermes gateway the OSS user runs themselves. These tests
verify:

1. ``is_oss_mode()`` toggles correctly on the env var.
2. ``_resolve_*_port`` short-circuits to the OSS port helpers when
   OSS mode is active, bypassing ``_ensure_container``.
3. The OSS port helpers return sensible defaults that match
   upstream's ``hermes gateway start`` defaults (8642 / 8643 / 9119).
4. ``get_or_create_container`` refuses to spawn in OSS mode.
"""

from unittest.mock import patch

import pytest
from fastapi import HTTPException

from open_webui.utils.hermes_web import (
    _oss_chat_port,
    _oss_gateway_port,
    _oss_web_port,
    _oss_web_session_token,
    _resolve_chat_port,
    _resolve_gateway_port,
    _resolve_web_endpoint,
    is_oss_mode,
)


class _UserStub:
    """Minimal UserModel stub for unit tests."""

    def __init__(self, user_id='u1'):
        self.id = user_id


# ── is_oss_mode ─────────────────────────────────────────────────────


def test_is_oss_mode_default_false(monkeypatch):
    """Default deployment is hosted (per-user containers)."""
    monkeypatch.delenv('MYAH_DEPLOYMENT_MODE', raising=False)
    assert is_oss_mode() is False


def test_is_oss_mode_oss_true(monkeypatch):
    monkeypatch.setenv('MYAH_DEPLOYMENT_MODE', 'oss')
    assert is_oss_mode() is True


def test_is_oss_mode_uppercase_normalized(monkeypatch):
    """Case is normalized so OSS / Oss / oss all toggle on."""
    monkeypatch.setenv('MYAH_DEPLOYMENT_MODE', 'OSS')
    assert is_oss_mode() is True
    monkeypatch.setenv('MYAH_DEPLOYMENT_MODE', 'Oss')
    assert is_oss_mode() is True


def test_is_oss_mode_whitespace_stripped(monkeypatch):
    monkeypatch.setenv('MYAH_DEPLOYMENT_MODE', '  oss  ')
    assert is_oss_mode() is True


def test_is_oss_mode_other_values_false(monkeypatch):
    """Anything other than 'oss' (case/whitespace-normalized) is hosted."""
    for val in ('hosted', 'production', '1', 'true', '', 'os'):
        monkeypatch.setenv('MYAH_DEPLOYMENT_MODE', val)
        assert is_oss_mode() is False, f'Expected hosted for {val!r}'


# ── port defaults match upstream ────────────────────────────────────


def test_oss_chat_port_default_matches_upstream(monkeypatch):
    """OSS chat port defaults to upstream's hermes gateway start (8642)."""
    monkeypatch.delenv('MYAH_HERMES_CHAT_PORT', raising=False)
    assert _oss_chat_port() == 8642


def test_oss_gateway_port_default_matches_upstream(monkeypatch):
    """OSS gateway port defaults to the standalone myah aiohttp runner (8643)."""
    monkeypatch.delenv('MYAH_HERMES_GATEWAY_PORT', raising=False)
    assert _oss_gateway_port() == 8643


def test_oss_web_port_default_matches_upstream(monkeypatch):
    """OSS web port defaults to hermes dashboard (9119)."""
    monkeypatch.delenv('MYAH_HERMES_WEB_PORT', raising=False)
    assert _oss_web_port() == 9119


def test_oss_chat_port_explicit_override(monkeypatch):
    monkeypatch.setenv('MYAH_HERMES_CHAT_PORT', '9100')
    assert _oss_chat_port() == 9100


def test_oss_chat_port_invalid_falls_back_to_default(monkeypatch):
    """Bad values log a warning and fall back to 8642 instead of crashing."""
    monkeypatch.setenv('MYAH_HERMES_CHAT_PORT', 'not-a-number')
    assert _oss_chat_port() == 8642


def test_oss_web_session_token_empty_when_unset(monkeypatch):
    """Empty token is acceptable for trivial single-tenant deployments."""
    monkeypatch.delenv('MYAH_HERMES_WEB_SESSION_TOKEN', raising=False)
    assert _oss_web_session_token() == ''


def test_oss_web_session_token_explicit(monkeypatch):
    monkeypatch.setenv('MYAH_HERMES_WEB_SESSION_TOKEN', 'secret-token-123')
    assert _oss_web_session_token() == 'secret-token-123'


# ── _resolve_*_port short-circuit ────────────────────────────────────


@pytest.mark.asyncio
async def test_resolve_chat_port_oss_skips_container(monkeypatch):
    """In OSS mode, _resolve_chat_port returns _oss_chat_port WITHOUT touching containers."""
    monkeypatch.setenv('MYAH_DEPLOYMENT_MODE', 'oss')
    monkeypatch.setenv('MYAH_HERMES_CHAT_PORT', '8642')

    with patch('open_webui.utils.hermes_web._ensure_container') as ensure:
        port = await _resolve_chat_port(_UserStub())

    assert port == 8642
    ensure.assert_not_called()


@pytest.mark.asyncio
async def test_resolve_gateway_port_oss_skips_container(monkeypatch):
    """In OSS mode, _resolve_gateway_port returns _oss_gateway_port WITHOUT touching containers."""
    monkeypatch.setenv('MYAH_DEPLOYMENT_MODE', 'oss')
    monkeypatch.setenv('MYAH_HERMES_GATEWAY_PORT', '8643')

    with patch('open_webui.utils.hermes_web._ensure_container') as ensure:
        port = await _resolve_gateway_port(_UserStub())

    assert port == 8643
    ensure.assert_not_called()


@pytest.mark.asyncio
async def test_resolve_web_endpoint_oss_skips_container(monkeypatch):
    """In OSS mode, _resolve_web_endpoint returns OSS port + token WITHOUT touching containers."""
    monkeypatch.setenv('MYAH_DEPLOYMENT_MODE', 'oss')
    monkeypatch.setenv('MYAH_HERMES_WEB_PORT', '9119')
    monkeypatch.setenv('MYAH_HERMES_WEB_SESSION_TOKEN', 'tok')

    with patch('open_webui.utils.hermes_web._ensure_container') as ensure:
        port, token = await _resolve_web_endpoint(_UserStub())

    assert port == 9119
    assert token == 'tok'
    ensure.assert_not_called()


# ── get_or_create_container refuses in OSS mode ─────────────────────


@pytest.mark.asyncio
async def test_get_or_create_container_returns_stub_in_oss_mode(monkeypatch):
    """OSS mode: per-user spawning is bypassed; helper returns a synthetic
    ContainerModel pointing at the host-side hermes ports."""
    from open_webui.routers.containers import get_or_create_container

    monkeypatch.setenv('MYAH_DEPLOYMENT_MODE', 'oss')
    monkeypatch.setenv('MYAH_HERMES_CHAT_PORT', '8642')
    monkeypatch.setenv('MYAH_HERMES_GATEWAY_PORT', '8643')
    monkeypatch.setenv('MYAH_HERMES_WEB_PORT', '9119')
    monkeypatch.setenv('MYAH_HERMES_WEB_SESSION_TOKEN', 'test-tok')

    record = await get_or_create_container('user-1')

    assert record.user_id == 'user-1'
    assert record.id == 'oss-user-1'
    assert record.host_port == 8642
    assert record.gateway_port == 8643
    assert record.web_port == 9119
    assert record.web_session_token == 'test-tok'
    assert record.status == 'running'
    # No actual Docker container — synthetic record signals this with NULL
    # container_id / container_name. Downstream readers tolerate both forms.
    assert record.container_id is None
    assert record.container_name is None


@pytest.mark.asyncio
async def test_get_or_create_container_does_not_call_docker_in_oss_mode(monkeypatch):
    """The OSS path must NOT touch ``_start_container`` / ``_docker_client``
    or any other Docker-touching helper. We assert that by patching them to
    explode if called and verifying the stub still returns cleanly."""
    monkeypatch.setenv('MYAH_DEPLOYMENT_MODE', 'oss')

    boom = patch(
        'open_webui.routers.containers._get_or_create_container_locked',
        side_effect=AssertionError('OSS path must not call docker spawn helpers'),
    )
    with boom:
        from open_webui.routers.containers import get_or_create_container
        record = await get_or_create_container('user-1')
    assert record.id == 'oss-user-1'
