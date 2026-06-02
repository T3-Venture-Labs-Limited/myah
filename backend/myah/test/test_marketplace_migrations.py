"""Marketplace Alembic migration coverage."""

from sqlalchemy import inspect


def test_marketplace_tables_exist_after_head_migration(db_session):
    """Fresh databases upgraded to HEAD include marketplace state tables."""

    inspector = inspect(db_session.engine)

    assert 'marketplace_installation' in inspector.get_table_names()
    assert 'marketplace_blocklist' in inspector.get_table_names()
