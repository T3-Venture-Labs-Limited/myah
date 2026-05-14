"""Simulate the prod upgrade path for c4d5e6f7a8b9 against a seeded
single-PK user_llm_key row. MYAH-PLATFORM-2Y."""
import os
import subprocess
import sqlite3
from pathlib import Path

import pytest

# Derive stable paths relative to this file so the test works regardless of
# which directory pytest is invoked from.
_HERE = Path(__file__).resolve()
# platform/backend/myah/test/apps/webui/test_migration_composite_pk.py
#   -> 6 parents up -> worktree root -> platform/
_PLATFORM_DIR = _HERE.parents[6] / 'platform'
_ALEMBIC_WORKDIR = _PLATFORM_DIR / 'backend' / 'myah'
_ALEMBIC_BIN = _PLATFORM_DIR / '.venv' / 'bin' / 'alembic'


@pytest.fixture
def prod_shape_db(tmp_path):
    """Produce a SQLite DB in the pre-c4d5e6f7a8b9 shape (single-column PK)."""
    db_path = tmp_path / 'prod.db'
    con = sqlite3.connect(db_path)
    con.executescript(
        """
        CREATE TABLE user_llm_key (
            user_id TEXT PRIMARY KEY,
            provider TEXT NOT NULL DEFAULT 'openrouter',
            encrypted_key TEXT NOT NULL DEFAULT '',
            key_last_four TEXT NOT NULL DEFAULT '****',
            openai_base_url TEXT,
            is_valid BOOLEAN NOT NULL DEFAULT 1,
            validated_at BIGINT,
            created_at BIGINT NOT NULL DEFAULT 0,
            updated_at BIGINT NOT NULL DEFAULT 0
        );
        INSERT INTO user_llm_key (user_id, provider, encrypted_key) VALUES
            ('u1', 'openai', 'encrypted-codex-token');
        CREATE TABLE alembic_version (version_num TEXT NOT NULL);
        INSERT INTO alembic_version VALUES ('e2f3a4b5c6d7');
        """
    )
    con.commit()
    con.close()
    return db_path


def test_composite_pk_migration_preserves_row(prod_shape_db, monkeypatch):
    monkeypatch.setenv('DATABASE_URL', f'sqlite:///{prod_shape_db}')

    # Upgrade only to c4d5e6f7a8b9 — the migration under test — rather than
    # head. Running further migrations would fail on this minimal DB because
    # later migrations expect tables (e.g. knowledge_file) that aren't present.
    result = subprocess.run(
        [str(_ALEMBIC_BIN), 'upgrade', 'c4d5e6f7a8b9'],
        capture_output=True,
        text=True,
        cwd=str(_ALEMBIC_WORKDIR),
        env=dict(os.environ),
    )
    assert result.returncode == 0, (
        f'migration failed:\nstdout: {result.stdout}\nstderr: {result.stderr}'
    )

    # Verify the row survived with correct composite key
    con = sqlite3.connect(prod_shape_db)
    rows = con.execute('SELECT user_id, provider FROM user_llm_key').fetchall()
    con.close()
    assert ('u1', 'openai') in rows, f'expected row not found; got: {rows}'
