"""Shared pytest fixtures for the Myah backend test suite.

Added by T3-1087 Task 1.0 to back test_cron_outbox.py. Signatures
verified against current master HEAD — if they drift, fix here AND
in the plan inline before continuing.
"""

from __future__ import annotations

from pathlib import Path
from typing import AsyncIterator

import pytest
import pytest_asyncio


# Compute the alembic.ini path from __file__ so this works regardless of
# pytest's CWD. conftest.py is at platform-oss/backend/myah/test/conftest.py;
# alembic.ini is at platform-oss/backend/myah/alembic.ini — two ../ up.
_ALEMBIC_INI = Path(__file__).resolve().parent.parent / 'alembic.ini'


@pytest.fixture(scope='function')
def db_session(tmp_path, monkeypatch):
    """Per-test SQLite DB at a temp path; Alembic-upgraded to HEAD."""
    import importlib
    import sys

    db_file = tmp_path / 'myah.db'
    db_url = f'sqlite:///{db_file}'
    monkeypatch.setenv('DATABASE_URL', db_url)
    monkeypatch.setenv('MYAH_DEPLOYMENT_MODE', 'oss')

    for name in list(sys.modules):
        if name == 'myah.models.cron_deliveries' or name.startswith('myah.models.cron_deliveries.'):
            del sys.modules[name]

    import myah.env
    import myah.internal.db

    importlib.reload(myah.env)
    importlib.reload(myah.internal.db)

    from alembic import command
    from alembic.config import Config

    if not _ALEMBIC_INI.exists():
        raise RuntimeError(
            f'alembic.ini not found at {_ALEMBIC_INI}. Expected location is '
            f'platform-oss/backend/myah/alembic.ini relative to repo root. '
            f'If the layout has changed, update _ALEMBIC_INI in conftest.py.'
        )
    alembic_cfg = Config(str(_ALEMBIC_INI))
    alembic_cfg.set_main_option('sqlalchemy.url', db_url)
    alembic_cfg.set_main_option('script_location', str(_ALEMBIC_INI.parent / 'migrations'))
    command.upgrade(alembic_cfg, 'head')

    yield myah.internal.db
    myah.internal.db.ScopedSession.remove()
    myah.internal.db.engine.dispose()


@pytest.fixture
def seed_user_and_chat(db_session):
    """Create a test user + a 'Process: test-job' chat for cron tests.

    Returns: (user_id, chat_id, chat_title).
    """
    from myah.models.chats import ChatForm, Chats
    from myah.models.users import Users

    user_id = '00000000-0000-0000-0000-000000000099'
    # Verified: Users.insert_new_user has NO password kwarg.
    Users.insert_new_user(
        id=user_id,
        name='cron-test',
        email='cron-test@local',
        role='user',
    )

    chat_title = 'Process: test-job'
    # Verified: insert_new_chat requires ChatForm (Pydantic), not raw dict.
    chat_form = ChatForm(
        chat={
            'title': chat_title,
            'history': {'messages': {}, 'currentId': None},
        }
    )
    chat = Chats.insert_new_chat(user_id, chat_form)
    return user_id, chat.id, chat_title


@pytest_asyncio.fixture
async def async_client(db_session) -> AsyncIterator:
    """AsyncClient bound to the FastAPI app.

    Uses httpx 0.27+ ASGITransport (the legacy AsyncClient(app=...) overload
    was removed in 0.28).
    """
    from httpx import ASGITransport, AsyncClient
    from myah.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        yield client


@pytest.fixture
def admin_bearer(db_session):
    """Create an admin user + return a bearer token (for hosted-overlay tests).

    The admin user has no password set — these tests assert on admin endpoints
    via the get_admin_user dependency which inspects the bearer's user.role
    rather than re-authing.
    """
    from myah.models.users import Users
    from myah.utils.auth import create_token

    admin_id = '00000000-0000-0000-0000-0000000000aa'
    Users.insert_new_user(
        id=admin_id,
        name='admin-test',
        email='admin-test@local',
        role='admin',
    )
    token = create_token(data={'id': admin_id})
    return token


@pytest.fixture
def webhook_bearer(monkeypatch):
    """Set MYAH_AGENT_BEARER_TOKEN to a known value AND patch the module-
    level CRON_WEBHOOK_SECRET that processes.py captured at import time
    (per plan-review S-6).
    """
    bearer = 'test-cron-bearer'
    monkeypatch.setenv('MYAH_AGENT_BEARER_TOKEN', bearer)
    monkeypatch.setattr('myah.routers.processes.CRON_WEBHOOK_SECRET', bearer)
    return bearer

@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """Return pytest's monkeypatch fixture for env-var changes.

    Use this when a test needs to set env vars. monkeypatch automatically
    restores the original environment after the test.
    """

    return monkeypatch
