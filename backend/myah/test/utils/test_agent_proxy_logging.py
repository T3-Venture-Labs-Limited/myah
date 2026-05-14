"""Regression test for the 2026-04-20 loguru %s bug.

Before the fix, `logger.error('msg with %s', x)` produced log lines
containing literal `%s` because loguru does not interpolate that form.
This test captures loguru output and asserts the user/method/path/error
are actually present in the log line, not just `%s` literals.
"""
import io

import httpx
import pytest
from loguru import logger

from myah.models.users import UserModel
from myah.utils.agent_proxy import aux_call


@pytest.mark.asyncio
async def test_aux_call_connect_error_logs_interpolated_values(monkeypatch):
    # Capture loguru output into a StringIO buffer.
    sink = io.StringIO()
    handler_id = logger.add(sink, format='{message}', level='ERROR')

    # Mock _get_container_port to skip the container lookup.
    async def _fake_port(user, path):
        return 54321
    monkeypatch.setattr(
        'myah.utils.agent_proxy._get_container_port', _fake_port
    )

    # Mock httpx.AsyncClient.request to raise ConnectError.
    class _FakeClient:
        def __init__(self, *a, **kw): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def request(self, *a, **kw):
            raise httpx.ConnectError('connection refused')
    monkeypatch.setattr('myah.utils.agent_proxy.httpx.AsyncClient', _FakeClient)

    now = 0
    user = UserModel(
        id='u-TESTUSER', email='t@test', name='t', role='user',
        last_active_at=now, updated_at=now, created_at=now,
    )

    with pytest.raises(Exception):  # HTTPException 503
        await aux_call(user, 'GET', '/myah/api/test')

    output = sink.getvalue()
    logger.remove(handler_id)

    # Post-fix, the log line must contain the interpolated values:
    assert 'u-TESTUSER' in output, f'user.id not interpolated: {output!r}'
    assert 'GET' in output, f'method not interpolated: {output!r}'
    assert '/myah/api/test' in output, f'path not interpolated: {output!r}'
    assert 'connection refused' in output, f'exception message not interpolated: {output!r}'
    # And must NOT contain the %s literal placeholders:
    assert '%s' not in output, f'log still contains %s literals: {output!r}'
