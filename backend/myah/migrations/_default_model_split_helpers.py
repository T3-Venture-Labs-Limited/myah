"""Pure-data helpers for the (provider, model) split migration.

Lives outside the revision file (underscore prefix → Alembic loader skips
it as a revision file) so unit tests can import it directly without
invoking the Alembic upgrade machinery.

The migration consults exactly ONE sibling table — user_provider_status —
to disambiguate slash-format legacy values. There is no platform-side
'active provider' concept (that lives only inside the per-user Hermes
container's auth.json, which the migration cannot synchronously read).
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Engine


def _connected_provider_ids(conn, user_id: str) -> set[str]:
    """Provider ids the user has a VALID credential for."""
    rows = conn.execute(
        text(
            'SELECT provider_id FROM user_provider_status '
            'WHERE user_id = :uid AND is_valid = 1'
        ),
        {'uid': user_id},
    ).fetchall()
    return {row[0] for row in rows}


def split_legacy_default_model(
    raw: str | None,
    user_id: str,
    conn,
) -> tuple[str | None, str | None]:
    """Parse a legacy default_model string into (provider, model).

    Returns (None, raw) when the model id is parseable but provider can't
    be inferred — `run_split_migration` then collapses any half-pair to
    (None, None) so the Pydantic invariant never sees half-state.
    """
    if not raw:
        return None, None

    if '::' in raw:
        # Composite: provider::model. Unambiguous.
        provider, _, model = raw.partition('::')
        return provider or None, model or None

    if '/' in raw:
        # Slash: ambiguous between Myah-provider-prefix and vendor-namespace.
        first, _, rest = raw.partition('/')
        if first in _connected_provider_ids(conn, user_id):
            return first, rest or None
        # Vendor-namespaced model id (e.g. 'anthropic/claude-opus-4.6' on
        # OpenRouter). No platform-side active-provider concept exists, so
        # provider stays NULL; the picker re-resolves on first save.
        return None, raw

    # Bare model id. Provider stays NULL; picker re-resolves on first save.
    return None, raw


def run_split_migration(engine_or_conn) -> None:
    """Apply the split to every row in the user table.

    Logs are intentionally print-based to land in the Alembic stdout
    stream where the deploy pipeline captures them. After the row-by-row
    pass, runs an end-of-migration sanity check that loads every row
    through UserModel.model_validate to catch validator-bypass drift.

    Accepts either a SQLAlchemy Engine (used by unit tests with their own
    in-memory DB) or a live Alembic connection (the production path via
    `op.get_bind()`).
    """
    if isinstance(engine_or_conn, Engine):
        ctx = engine_or_conn.begin()
    else:
        # Already inside an Alembic-managed transaction.
        ctx = _PassthroughCtx(engine_or_conn)

    with ctx as conn:
        rows = conn.execute(
            text('SELECT id, default_model FROM "user" WHERE default_model IS NOT NULL')
        ).fetchall()
        for user_id, raw in rows:
            provider, model = split_legacy_default_model(raw, user_id, conn)
            # Enforce both-or-neither at write time so the validator never sees
            # half-state in the durable column.
            if not provider:
                provider, model = None, None
            conn.execute(
                text(
                    'UPDATE "user" SET default_provider = :p, default_model = :m '
                    'WHERE id = :id'
                ),
                {'p': provider, 'm': model, 'id': user_id},
            )
            print(
                f'[default_model_split] user={user_id} '
                f'before={raw!r} after=(provider={provider!r}, model={model!r})'
            )

    # End-of-migration sanity: every row must Pydantic-validate cleanly.
    # Implementation note: load each row as a dict and call
    # UserModel.model_validate(dict). Do NOT try to instantiate the SA `User`
    # ORM class mid-migration — the declarative-base ordering inside an Alembic
    # upgrade is fragile and the ORM session lifecycle conflicts with the
    # raw connection.
    try:
        from myah.models.users import UserModel
    except ImportError:
        print('[default_model_split] WARN: UserModel import failed; skip sanity pass')
        return

    if isinstance(engine_or_conn, Engine):
        sanity_ctx = engine_or_conn.connect()
    else:
        sanity_ctx = _PassthroughCtx(engine_or_conn)

    bad_rows: list[str] = []
    with sanity_ctx as conn:
        all_rows = conn.execute(text('SELECT * FROM "user"')).mappings().fetchall()
        for row in all_rows:
            try:
                UserModel.model_validate(dict(row))
            except Exception as exc:
                bad_rows.append(f'  user={row["id"]} error={exc}')

    if bad_rows:
        # Log-only failure policy. Raising here would roll back the whole
        # backfill including correctly-converted rows. The smoke test catches
        # any residual drift via the both-or-neither invariant on the session
        # response and triggers deploy auto-rollback.
        print('[default_model_split] WARN: sanity pass found invalid rows:')
        for line in bad_rows:
            print(line)
    else:
        print(f'[default_model_split] sanity pass OK ({len(all_rows)} rows validated)')


class _PassthroughCtx:
    """Wraps a live connection so the `with` syntax works without
    starting a new transaction (Alembic's connection is already in one)."""

    def __init__(self, conn):
        self._conn = conn

    def __enter__(self):
        return self._conn

    def __exit__(self, *args):
        return False
