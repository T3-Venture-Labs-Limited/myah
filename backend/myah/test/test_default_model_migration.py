"""Tests for the (provider, model) split migration.

Exercises the migration's split helper directly without running Alembic
upgrade — the helper is the only non-trivial logic; Alembic plumbing is
tested in-vivo by the post-deploy hosted smoke test.

The migration consults exactly ONE sibling table — `user_provider_status` —
to disambiguate slash-format legacy values. There is no platform-side
'active provider' concept (that lives only inside the per-user Hermes
container's auth.json, which the migration cannot synchronously read).
"""

from pathlib import Path

import pytest
from sqlalchemy import create_engine, text


@pytest.fixture
def db_with_legacy_users(tmp_path: Path):
    db_path = tmp_path / 'test.db'
    engine = create_engine(f'sqlite:///{db_path}')
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE "user" (
                id TEXT PRIMARY KEY,
                default_model TEXT,
                default_provider TEXT
            )
        """))
        conn.execute(text("""
            CREATE TABLE user_provider_status (
                user_id TEXT,
                provider_id TEXT,
                is_valid INTEGER
            )
        """))
        # Composite row (unambiguous).
        conn.execute(text(
            "INSERT INTO \"user\" VALUES ('u_composite', 'openai::gpt-4o-mini', NULL)"
        ))
        # Slash row where first part IS a connected, valid provider.
        conn.execute(text(
            "INSERT INTO \"user\" VALUES ('u_slash_connected', 'openai/gpt-4o-mini', NULL)"
        ))
        conn.execute(text(
            "INSERT INTO user_provider_status VALUES ('u_slash_connected', 'openai', 1)"
        ))
        # Slash row where first part is a vendor namespace (NOT a connected provider).
        conn.execute(text(
            "INSERT INTO \"user\" VALUES ('u_slash_vendor', 'anthropic/claude-opus-4.6', NULL)"
        ))
        # Bare row with no provider context.
        conn.execute(text(
            "INSERT INTO \"user\" VALUES ('u_bare_orphan', 'mystery-model', NULL)"
        ))
        # NULL row stays NULL.
        conn.execute(text(
            "INSERT INTO \"user\" VALUES ('u_null', NULL, NULL)"
        ))
        # Invalid provider credential — must NOT count as connected.
        conn.execute(text(
            "INSERT INTO \"user\" VALUES ('u_invalid_cred', 'openai/gpt-4o-mini', NULL)"
        ))
        conn.execute(text(
            "INSERT INTO user_provider_status VALUES ('u_invalid_cred', 'openai', 0)"
        ))
    return engine


def _split_columns(engine, user_id: str) -> tuple:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT default_provider, default_model FROM \"user\" WHERE id = :id"),
            {'id': user_id},
        ).fetchone()


def test_composite_value_splits_unambiguously(db_with_legacy_users):
    from myah.migrations._default_model_split_helpers import run_split_migration
    run_split_migration(db_with_legacy_users)
    assert _split_columns(db_with_legacy_users, 'u_composite') == ('openai', 'gpt-4o-mini')


def test_slash_with_connected_provider_splits(db_with_legacy_users):
    from myah.migrations._default_model_split_helpers import run_split_migration
    run_split_migration(db_with_legacy_users)
    assert _split_columns(db_with_legacy_users, 'u_slash_connected') == ('openai', 'gpt-4o-mini')


def test_slash_vendor_namespace_nulls_both(db_with_legacy_users):
    """When the slash's first part is NOT a connected provider, the whole value
    is a vendor-namespaced model id. The wrapping `run_split_migration` collapses
    half-pair (model-only) state to (None, None) so the validator never sees it
    and the user re-picks the provider on next session."""
    from myah.migrations._default_model_split_helpers import run_split_migration
    run_split_migration(db_with_legacy_users)
    assert _split_columns(db_with_legacy_users, 'u_slash_vendor') == (None, None)


def test_bare_orphan_nulls_both_columns(db_with_legacy_users):
    """No connected provider context for a bare id → NULL both columns."""
    from myah.migrations._default_model_split_helpers import run_split_migration
    run_split_migration(db_with_legacy_users)
    assert _split_columns(db_with_legacy_users, 'u_bare_orphan') == (None, None)


def test_null_row_stays_null(db_with_legacy_users):
    from myah.migrations._default_model_split_helpers import run_split_migration
    run_split_migration(db_with_legacy_users)
    assert _split_columns(db_with_legacy_users, 'u_null') == (None, None)


def test_invalid_provider_credential_not_counted(db_with_legacy_users):
    """user_provider_status rows with is_valid=0 must NOT count as connected,
    so an 'openai/gpt-4o-mini' default for a user whose openai credential is
    invalid gets nulled rather than being half-attributed."""
    from myah.migrations._default_model_split_helpers import run_split_migration
    run_split_migration(db_with_legacy_users)
    assert _split_columns(db_with_legacy_users, 'u_invalid_cred') == (None, None)
