"""ORM round-trip tests for the web_port and web_session_token columns
on the Container table (Workstream A Phase 0).

These tests spin up a disposable in-memory SQLite DB so they don't depend
on the real application database or the Alembic migration chain.

Only the `container` table is created — `Base.metadata.create_all(...,
tables=[Container.__table__])` skips FK-dependent tables that would fail
to resolve in isolation.
"""

import os
import time
import uuid

import pytest

os.environ.setdefault('DATABASE_URL', 'sqlite://')
os.environ.setdefault('ENABLE_DB_MIGRATIONS', 'False')
os.environ.setdefault('WEBUI_SECRET_KEY', 'test-secret')


@pytest.fixture(scope='module')
def db_session():
    """Create only the `container` table on an in-memory SQLite engine.

    We use ``Container.__table__.metadata`` rather than importing ``Base``
    so this fixture does not pin SQLAlchemy's global metadata in a way
    that confuses other tests run in the same pytest session (e.g.
    test_hermes_web.py imports ``open_webui.config`` which redefines
    classes against the same Base — see the SAWarning emitted there).
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from open_webui.models.containers import Container  # registers the table

    engine = create_engine('sqlite://', connect_args={'check_same_thread': False})
    Container.__table__.metadata.create_all(engine, tables=[Container.__table__])
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    session = Session()
    yield session
    session.close()


def test_container_table_declares_web_port_column():
    """Schema-level assertion: web_port must be a real Column on the ORM
    model. Catches regressions where the column is dropped or renamed."""
    from open_webui.models.containers import Container

    columns = {c.name for c in Container.__table__.columns}
    assert 'web_port' in columns, (
        f"Container is missing web_port column. Got: {sorted(columns)}"
    )


def test_container_table_declares_web_session_token_column():
    """Schema-level assertion: web_session_token must be a real Column."""
    from open_webui.models.containers import Container

    columns = {c.name for c in Container.__table__.columns}
    assert 'web_session_token' in columns, (
        f"Container is missing web_session_token column. Got: {sorted(columns)}"
    )


def test_insert_and_read_web_columns_round_trip(db_session):
    """Round-trip: insert a Container with both columns set, read it back."""
    from open_webui.models.containers import Container

    container_id = str(uuid.uuid4())
    user_id = f'user-{container_id[:8]}'
    row = Container(
        id=container_id,
        user_id=user_id,
        status='running',
        host_port=12345,
        web_port=54321,
        web_session_token='test-token-abc123',
        created_at=int(time.time()),
        last_active=int(time.time()),
    )
    db_session.add(row)
    db_session.commit()

    fetched = db_session.query(Container).filter_by(id=container_id).first()
    assert fetched is not None
    assert fetched.web_port == 54321
    assert fetched.web_session_token == 'test-token-abc123'


def test_web_columns_default_to_null(db_session):
    """Inserting a Container without setting the new columns must keep
    them NULL — the migration adds them as nullable (no DB default)."""
    from open_webui.models.containers import Container

    container_id = str(uuid.uuid4())
    user_id = f'user-{container_id[:8]}'
    row = Container(
        id=container_id,
        user_id=user_id,
        status='creating',
        created_at=int(time.time()),
        last_active=int(time.time()),
    )
    db_session.add(row)
    db_session.commit()

    fetched = db_session.query(Container).filter_by(id=container_id).first()
    assert fetched is not None
    assert fetched.web_port is None
    assert fetched.web_session_token is None


def test_pydantic_model_accepts_web_columns():
    """The Pydantic schema (ContainerModel) must surface the new columns
    so callers like ContainerTable.get_by_user_id() return them."""
    from open_webui.models.containers import ContainerModel

    fields = ContainerModel.model_fields
    assert 'web_port' in fields
    assert 'web_session_token' in fields


def test_update_status_accepts_web_kwargs(db_session):
    """ContainerTable.update_status must accept web_port and web_session_token
    as keyword arguments (callers in routers/containers.py rely on this)."""
    import inspect
    from open_webui.models.containers import ContainerTable

    sig = inspect.signature(ContainerTable.update_status)
    params = sig.parameters
    assert 'web_port' in params, f'update_status missing web_port kwarg: {list(params)}'
    assert 'web_session_token' in params, (
        f'update_status missing web_session_token kwarg: {list(params)}'
    )
