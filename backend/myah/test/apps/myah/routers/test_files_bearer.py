"""Tests for AGENT_BEARER_TOKEN auth on the file content endpoint.

These tests intentionally call ``get_file_user_or_agent`` with real FastAPI
dependency values (no mocking of ``get_verified_user``/``get_current_user``)
so the regression we hit — where FastAPI resolved the user-auth dependency
before the function body and 401'd on the agent's non-JWT bearer — cannot
return silently.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials


def _mk_creds(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme='Bearer', credentials=token)


def test_agent_actor_sentinel_shape():
    """AgentActor is a role='agent' sentinel the handler can check with
    ``isinstance(user, AgentActor)``."""
    from myah.routers.files import AgentActor

    actor = AgentActor()
    assert actor.role == 'agent'
    assert actor.id == 'agent'


@pytest.mark.asyncio
async def test_agent_bearer_returns_agent_actor_without_touching_user_auth():
    """CRITICAL REGRESSION GUARD.

    The agent's bearer token is NOT a JWT and NOT a ``sk-`` API key, so
    ``get_current_user`` will always 401 on it. If the agent-bearer check
    doesn't happen first, the 401 propagates and every file fetch from
    the agent container fails.
    """
    from myah.routers.files import AgentActor, get_file_user_or_agent

    with patch('myah.routers.files.AGENT_BEARER_TOKEN', 'test-agent-token'), \
         patch(
             'myah.routers.files.get_current_user',
             new=AsyncMock(side_effect=AssertionError(
                 'get_current_user must not be called when the agent bearer matches'
             )),
         ):
        result = await get_file_user_or_agent(
            request=MagicMock(),
            response=MagicMock(),
            background_tasks=MagicMock(),
            auth_token=_mk_creds('test-agent-token'),
        )

    assert isinstance(result, AgentActor)


@pytest.mark.asyncio
async def test_wrong_bearer_falls_through_to_user_auth():
    """A bearer that doesn't match the agent token must be resolved by the
    normal user-auth chain (which may itself raise 401)."""
    from myah.models.users import UserModel
    from myah.routers.files import get_file_user_or_agent

    fake_user = MagicMock(spec=UserModel)
    fake_user.role = 'user'

    with patch('myah.routers.files.AGENT_BEARER_TOKEN', 'correct-agent-token'), \
         patch(
             'myah.routers.files.get_current_user',
             new=AsyncMock(return_value=fake_user),
         ):
        result = await get_file_user_or_agent(
            request=MagicMock(),
            response=MagicMock(),
            background_tasks=MagicMock(),
            auth_token=_mk_creds('some-other-token'),
        )

    assert result is fake_user


@pytest.mark.asyncio
async def test_empty_agent_bearer_token_disables_agent_path():
    """When AGENT_BEARER_TOKEN is not configured, any bearer must be routed
    through normal user auth — even the empty string must NOT short-circuit."""
    from myah.models.users import UserModel
    from myah.routers.files import get_file_user_or_agent

    fake_user = MagicMock(spec=UserModel)
    fake_user.role = 'admin'

    with patch('myah.routers.files.AGENT_BEARER_TOKEN', ''), \
         patch(
             'myah.routers.files.get_current_user',
             new=AsyncMock(return_value=fake_user),
         ):
        result = await get_file_user_or_agent(
            request=MagicMock(),
            response=MagicMock(),
            background_tasks=MagicMock(),
            auth_token=_mk_creds('anything'),
        )

    assert result is fake_user


@pytest.mark.asyncio
async def test_no_bearer_header_falls_through_to_user_auth():
    """A request without an Authorization header must still reach user auth
    (which resolves cookie-based sessions)."""
    from myah.models.users import UserModel
    from myah.routers.files import get_file_user_or_agent

    fake_user = MagicMock(spec=UserModel)
    fake_user.role = 'user'

    with patch('myah.routers.files.AGENT_BEARER_TOKEN', 'secret'), \
         patch(
             'myah.routers.files.get_current_user',
             new=AsyncMock(return_value=fake_user),
         ):
        result = await get_file_user_or_agent(
            request=MagicMock(),
            response=MagicMock(),
            background_tasks=MagicMock(),
            auth_token=None,  # fastapi.security.HTTPBearer(auto_error=False) returns None
        )

    assert result is fake_user


@pytest.mark.asyncio
async def test_user_auth_401_propagates_to_caller():
    """When no auth resolves, the 401 from get_current_user must reach the
    endpoint — callers rely on FastAPI's standard error contract."""
    from myah.routers.files import get_file_user_or_agent

    with patch('myah.routers.files.AGENT_BEARER_TOKEN', 'secret'), \
         patch(
             'myah.routers.files.get_current_user',
             new=AsyncMock(side_effect=HTTPException(status_code=401, detail='Invalid token')),
         ):
        with pytest.raises(HTTPException) as exc_info:
            await get_file_user_or_agent(
                request=MagicMock(),
                response=MagicMock(),
                background_tasks=MagicMock(),
                auth_token=_mk_creds('not-the-agent'),
            )

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_non_user_role_is_rejected_after_user_auth():
    """A resolved user whose role is neither 'user' nor 'admin' must be
    rejected — mirrors get_verified_user's contract."""
    from myah.models.users import UserModel
    from myah.routers.files import get_file_user_or_agent

    fake_user = MagicMock(spec=UserModel)
    fake_user.role = 'pending'  # signup-locked accounts etc.

    with patch('myah.routers.files.AGENT_BEARER_TOKEN', 'secret'), \
         patch(
             'myah.routers.files.get_current_user',
             new=AsyncMock(return_value=fake_user),
         ):
        with pytest.raises(HTTPException) as exc_info:
            await get_file_user_or_agent(
                request=MagicMock(),
                response=MagicMock(),
                background_tasks=MagicMock(),
                auth_token=_mk_creds('not-the-agent'),
            )

    assert exc_info.value.status_code == 401
