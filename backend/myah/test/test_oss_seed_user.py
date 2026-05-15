"""
Tests for the OSS-mode `oss_seed_user` Alembic migration (Phase 1B Task B.6).

The migration inserts a single admin user when ``MYAH_DEPLOYMENT_MODE=oss``,
no-op in hosted mode, idempotent on re-run. This is what gives the OSS
deployment its "no login screen — just one anonymous admin" behaviour.

The hosted variant skips the seed (the multi-user signup flow handles user
creation there).

Test approach: import the migration module directly and call ``upgrade()``
against an in-memory SQLite database where we've manually set up just the
``user`` table. This avoids the cost / brittleness of replaying the entire
57-revision migration chain just to test a single insert.
"""

import importlib.util
import os
import sys
from pathlib import Path

import pytest
from sqlalchemy import (
    BigInteger,
    Column,
    JSON,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    inspect,
    text,
)
from sqlalchemy.pool import StaticPool


# Locate the migration file dynamically — Alembic auto-prefixes the revision
# hash so the filename isn't ``oss_seed_user.py`` exactly.
MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / 'migrations' / 'versions'


def _load_migration_module():
    """Find and import the oss_seed_user migration module."""
    candidates = [
        p for p in MIGRATIONS_DIR.glob('*_oss_seed_user.py')
        if p.is_file()
    ]
    if not candidates:
        raise FileNotFoundError(
            f'No *_oss_seed_user.py migration found in {MIGRATIONS_DIR}. '
            f'Run `alembic revision -m oss_seed_user` first.'
        )
    if len(candidates) > 1:
        raise RuntimeError(
            f'Multiple oss_seed_user migrations found: {candidates}. '
            f'Keep exactly one.'
        )
    path = candidates[0]

    spec = importlib.util.spec_from_file_location('oss_seed_user_migration', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules['oss_seed_user_migration'] = module
    spec.loader.exec_module(module)
    return module


def _make_test_engine():
    """Create an in-memory SQLite with the ``user`` table schema only."""
    engine = create_engine(
        'sqlite://',
        connect_args={'check_same_thread': False},
        poolclass=StaticPool,
    )

    metadata = MetaData()
    # Minimal ``user`` table matching myah.models.users.User columns
    # the seed needs to write to. Other columns are nullable / unused.
    Table(
        'user',
        metadata,
        Column('id', String, primary_key=True),
        Column('email', String),
        Column('name', String),
        Column('role', String),
        Column('profile_image_url', Text),
        Column('settings', JSON, nullable=True),
        Column('info', JSON, nullable=True),
        Column('last_active_at', BigInteger),
        Column('updated_at', BigInteger),
        Column('created_at', BigInteger),
    )
    metadata.create_all(engine)
    return engine


@pytest.fixture
def oss_mode(monkeypatch):
    monkeypatch.setenv('MYAH_DEPLOYMENT_MODE', 'oss')


@pytest.fixture
def hosted_mode(monkeypatch):
    monkeypatch.delenv('MYAH_DEPLOYMENT_MODE', raising=False)


def _run_upgrade(engine, migration_module):
    """Execute the migration's upgrade() with the bind set to our engine.

    Uses ``Operations.context()`` — the same idiom Alembic uses internally
    in ``EnvironmentContext.run_migrations()`` (alembic/runtime/environment.py:968)
    — to wire ``alembic.op`` to our test migration context for the
    duration of the call. Without this, ``op.get_bind()`` raises NameError
    because the proxy hasn't been established yet.
    """
    from alembic.runtime.migration import MigrationContext
    from alembic.operations import Operations

    with engine.begin() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            migration_module.upgrade()


# ── Happy path: OSS-mode seeding ───────────────────────────────────────────


def test_seeds_single_admin_user_in_oss_mode(oss_mode):
    """In OSS mode, the migration inserts exactly one row in the user table."""
    engine = _make_test_engine()
    migration = _load_migration_module()

    _run_upgrade(engine, migration)

    with engine.connect() as conn:
        rows = conn.execute(text('SELECT id, role, email FROM user')).fetchall()

    assert len(rows) == 1, f'Expected 1 user row, got {len(rows)}'
    user = rows[0]
    assert user.role == 'admin', f'Expected admin role, got {user.role!r}'
    assert user.email == 'user@localhost', f'Expected placeholder email, got {user.email!r}'
    assert user.id, 'Seeded user must have an id'


# ── Sad path: hosted mode no-op ────────────────────────────────────────────


def test_noop_in_hosted_mode(hosted_mode):
    """In hosted mode (env unset), the migration MUST NOT insert any rows."""
    engine = _make_test_engine()
    migration = _load_migration_module()

    _run_upgrade(engine, migration)

    with engine.connect() as conn:
        rows = conn.execute(text('SELECT id FROM user')).fetchall()

    assert len(rows) == 0, (
        f'Hosted mode must skip the seed. Found {len(rows)} unexpected '
        f'user rows: {[r.id for r in rows]}'
    )


# ── Idempotency: re-running the migration doesn't duplicate ────────────────


def test_idempotent_on_rerun(oss_mode):
    """Two consecutive upgrade() calls still produce exactly one user row."""
    engine = _make_test_engine()
    migration = _load_migration_module()

    _run_upgrade(engine, migration)
    _run_upgrade(engine, migration)

    with engine.connect() as conn:
        rows = conn.execute(text('SELECT id FROM user')).fetchall()

    assert len(rows) == 1, (
        f'Re-running the seed must not duplicate. Found {len(rows)} rows.'
    )


# ── Edge: existing user in DB blocks the seed (Alembic ran in dev) ─────────


def test_noop_when_user_table_already_has_rows(oss_mode):
    """If the DB already has any user row (developer pre-seeded, prior install),
    the migration MUST NOT insert another. Single-user semantics requires
    treating the existence of any prior user as 'already initialised'."""
    engine = _make_test_engine()

    # Pre-seed a user row directly (simulates developer DB state)
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO user (id, email, name, role, created_at, updated_at) "
            "VALUES ('preseeded-id', 'dev@local', 'Dev', 'admin', 0, 0)"
        ))

    migration = _load_migration_module()
    _run_upgrade(engine, migration)

    with engine.connect() as conn:
        rows = conn.execute(text('SELECT id, email FROM user')).fetchall()

    assert len(rows) == 1, f'Expected DB to keep 1 pre-seeded row, got {len(rows)}'
    assert rows[0].id == 'preseeded-id', (
        f'Pre-seeded user must be preserved (got id={rows[0].id!r})'
    )


# ── Env-var normalisation: case + whitespace ───────────────────────────────


@pytest.mark.parametrize('value', ['oss', 'OSS', 'Oss', '  oss  ', 'OSS\n'])
def test_oss_mode_normalised_correctly(monkeypatch, value):
    """The mode check accepts ``oss`` regardless of case or surrounding
    whitespace — matches utils.hermes_web.is_oss_mode() normalisation."""
    monkeypatch.setenv('MYAH_DEPLOYMENT_MODE', value)
    engine = _make_test_engine()
    migration = _load_migration_module()

    _run_upgrade(engine, migration)

    with engine.connect() as conn:
        count = conn.execute(text('SELECT COUNT(*) FROM user')).scalar()
    assert count == 1, f'MYAH_DEPLOYMENT_MODE={value!r} must seed; got {count} rows'


@pytest.mark.parametrize('value', ['hosted', 'production', '', 'true'])
def test_non_oss_values_do_not_seed(monkeypatch, value):
    """Anything other than ``oss`` (case/whitespace-insensitive) is hosted mode."""
    monkeypatch.setenv('MYAH_DEPLOYMENT_MODE', value)
    engine = _make_test_engine()
    migration = _load_migration_module()

    _run_upgrade(engine, migration)

    with engine.connect() as conn:
        count = conn.execute(text('SELECT COUNT(*) FROM user')).scalar()
    assert count == 0, f'MYAH_DEPLOYMENT_MODE={value!r} must NOT seed; got {count} rows'
