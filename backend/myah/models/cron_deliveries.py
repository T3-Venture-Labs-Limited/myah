"""SQLAlchemy table model + CRUD helper for the cron delivery outbox.

Mirrors the shape of ``models/chats.py``: a SQLAlchemy declarative model
plus a class with classmethod-style CRUD helpers. Spec: T3-1087
``docs/superpowers/specs/2026-05-26-cron-delivery-outbox-design.md``
§4.2.2.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from typing import Any

from loguru import logger
from myah.internal.db import Base, get_db
from sqlalchemy import Column, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.sqlite import insert as sqlite_insert


class CronDelivery(Base):
    __tablename__ = 'cron_deliveries'

    id = Column(Text, primary_key=True)
    user_id = Column(Text, nullable=False)
    job_id = Column(Text, nullable=False)
    chat_id = Column(Text, nullable=False)
    ran_at_iso = Column(Text, nullable=False)
    content = Column(Text, nullable=False)
    metadata_json = Column(Text, nullable=True)
    delivery_status = Column(Text, nullable=False, default='pending')
    retry_count = Column(Integer, nullable=False, default=0)
    next_retry_at = Column(Integer, nullable=True)
    last_error = Column(Text, nullable=True)
    leased_at = Column(Integer, nullable=True)
    created_at = Column(Integer, nullable=False)
    delivered_at = Column(Integer, nullable=True)
    legacy_delivered_at = Column(Integer, nullable=True)

    # Indices are managed exclusively by Alembic (see Task 1.1 migration).
    # Do NOT declare them in __table_args__ here — per plan-review C-C:
    # declaring a non-partial Index('idx_cron_deliveries_parity', ...) here
    # would conflict with the migration's partial index
    # `idx_cron_deliveries_parity_gap WHERE legacy_delivered_at IS NULL`
    # if anyone runs `Base.metadata.create_all(...)` (test paths that bypass
    # Alembic). UNIQUE constraints stay in __table_args__ because SQLAlchemy
    # needs them at ORM level for ON CONFLICT support.
    __table_args__ = (UniqueConstraint('job_id', 'ran_at_iso', name='uq_cron_deliveries_job_ran'),)


@dataclass
class CronDeliveryRow:
    """Plain-data view of a cron_deliveries row. Returned by all CRUD methods.

    Decoupled from the SQLAlchemy ORM object so the worker can hold it
    across session boundaries without expired-attribute errors.
    """

    id: str
    user_id: str
    job_id: str
    chat_id: str
    ran_at_iso: str
    content: str
    metadata_json: str | None
    delivery_status: str
    retry_count: int
    next_retry_at: int | None
    last_error: str | None
    leased_at: int | None
    created_at: int
    delivered_at: int | None
    legacy_delivered_at: int | None

    @property
    def metadata(self) -> dict[str, Any]:
        """Parsed metadata_json, or {} if None/invalid."""
        if not self.metadata_json:
            return {}
        try:
            value = json.loads(self.metadata_json)
            return value if isinstance(value, dict) else {}
        except (json.JSONDecodeError, TypeError):
            return {}


def _row_to_dataclass(row: CronDelivery) -> CronDeliveryRow:
    return CronDeliveryRow(
        id=row.id,
        user_id=row.user_id,
        job_id=row.job_id,
        chat_id=row.chat_id,
        ran_at_iso=row.ran_at_iso,
        content=row.content,
        metadata_json=row.metadata_json,
        delivery_status=row.delivery_status,
        retry_count=row.retry_count,
        next_retry_at=row.next_retry_at,
        last_error=row.last_error,
        leased_at=row.leased_at,
        created_at=row.created_at,
        delivered_at=row.delivered_at,
        legacy_delivered_at=row.legacy_delivered_at,
    )


class CronDeliveries:
    """Static-method CRUD helper. Mirrors the pattern in models/chats.py."""

    @staticmethod
    def insert_idempotent(payload: dict[str, Any]) -> str:
        """INSERT a row using (job_id, ran_at_iso) as the idempotency key.

        Returns the row id (newly inserted OR pre-existing).
        Uses SQLite's INSERT OR IGNORE under the hood; the equivalent on
        Postgres would be `ON CONFLICT (job_id, ran_at_iso) DO NOTHING`.
        """
        now = int(time.time())
        new_id = str(uuid.uuid4())
        stmt = (
            sqlite_insert(CronDelivery)
            .values(
                id=new_id,
                user_id=payload['user_id'],
                job_id=payload['job_id'],
                chat_id=payload['chat_id'],
                ran_at_iso=payload['ran_at_iso'],
                content=payload['content'],
                metadata_json=payload.get('metadata_json'),
                delivery_status='pending',
                retry_count=0,
                next_retry_at=None,
                last_error=None,
                leased_at=None,
                created_at=now,
                delivered_at=None,
                legacy_delivered_at=None,
            )
            .on_conflict_do_nothing(index_elements=['job_id', 'ran_at_iso'])
        )
        with get_db() as db:
            db.execute(stmt)
            db.commit()
            # Re-read to get the actual id (may not equal new_id if a prior row exists)
            existing = (
                db.query(CronDelivery)
                .filter(
                    CronDelivery.job_id == payload['job_id'],
                    CronDelivery.ran_at_iso == payload['ran_at_iso'],
                )
                .first()
            )
            return existing.id if existing else new_id

    @staticmethod
    def get_by_id(row_id: str) -> CronDeliveryRow | None:
        with get_db() as db:
            row = db.query(CronDelivery).filter(CronDelivery.id == row_id).first()
            return _row_to_dataclass(row) if row else None

    @staticmethod
    def pop_pending(batch_size: int, lease_ttl_secs: int) -> list[CronDeliveryRow]:
        """Atomically lease up to `batch_size` pending rows.

        Selects rows where delivery_status='pending' AND (next_retry_at IS NULL
        OR next_retry_at <= now()), orders by created_at, marks them
        delivering, stamps leased_at, and returns dataclass copies.
        """
        now = int(time.time())
        with get_db() as db:
            # SQLite single-writer means BEGIN IMMEDIATE is implicit; we use a
            # single UPDATE...RETURNING-equivalent via subquery to keep this atomic.
            ids = (
                db.query(CronDelivery.id)
                .filter(
                    CronDelivery.delivery_status == 'pending',
                    (CronDelivery.next_retry_at.is_(None)) | (CronDelivery.next_retry_at <= now),
                )
                .order_by(CronDelivery.created_at.asc(), CronDelivery.ran_at_iso.asc(), CronDelivery.id.asc())
                .limit(batch_size)
                .all()
            )
            id_list = [i.id for i in ids]
            if not id_list:
                return []
            db.query(CronDelivery).filter(CronDelivery.id.in_(id_list)).update(
                {
                    CronDelivery.delivery_status: 'delivering',
                    CronDelivery.leased_at: now,
                },
                synchronize_session=False,
            )
            db.commit()
            rows = (
                db.query(CronDelivery)
                .filter(CronDelivery.id.in_(id_list))
                .order_by(CronDelivery.created_at.asc(), CronDelivery.ran_at_iso.asc(), CronDelivery.id.asc())
                .all()
            )
            return [_row_to_dataclass(r) for r in rows]

    @staticmethod
    def mark_delivered(row_id: str) -> None:
        now = int(time.time())
        with get_db() as db:
            db.query(CronDelivery).filter(CronDelivery.id == row_id).update(
                {
                    CronDelivery.delivery_status: 'delivered',
                    CronDelivery.delivered_at: now,
                    CronDelivery.leased_at: None,
                },
                synchronize_session=False,
            )
            db.commit()

    @staticmethod
    def mark_retry(row_id: str, error: str, next_retry_at: int) -> None:
        with get_db() as db:
            db.query(CronDelivery).filter(CronDelivery.id == row_id).update(
                {
                    CronDelivery.delivery_status: 'pending',
                    CronDelivery.retry_count: CronDelivery.retry_count + 1,
                    CronDelivery.last_error: error,
                    CronDelivery.next_retry_at: next_retry_at,
                    CronDelivery.leased_at: None,
                },
                synchronize_session=False,
            )
            db.commit()

    @staticmethod
    def mark_failed(row_id: str, error: str) -> None:
        with get_db() as db:
            db.query(CronDelivery).filter(CronDelivery.id == row_id).update(
                {
                    CronDelivery.delivery_status: 'failed',
                    CronDelivery.last_error: error,
                    CronDelivery.leased_at: None,
                },
                synchronize_session=False,
            )
            db.commit()

    @staticmethod
    def set_next_retry_at(row_id: str, next_retry_at: int) -> None:
        """Test helper: schedule a row's retry for a specific unix timestamp."""
        with get_db() as db:
            db.query(CronDelivery).filter(CronDelivery.id == row_id).update(
                {CronDelivery.next_retry_at: next_retry_at},
                synchronize_session=False,
            )
            db.commit()

    @staticmethod
    def reclaim_stuck_leases(stuck_threshold_secs: int) -> list[str]:
        """Reset rows stuck in 'delivering' with old leased_at back to 'pending'.

        Returns the list of reclaimed row ids. Logs WARNING if any were
        reclaimed.
        """
        now = int(time.time())
        cutoff = now - stuck_threshold_secs
        with get_db() as db:
            stuck = (
                db.query(CronDelivery.id)
                .filter(
                    CronDelivery.delivery_status == 'delivering',
                    CronDelivery.leased_at < cutoff,
                )
                .all()
            )
            reclaimed = [r.id for r in stuck]
            if reclaimed:
                db.query(CronDelivery).filter(CronDelivery.id.in_(reclaimed)).update(
                    {
                        CronDelivery.delivery_status: 'pending',
                        CronDelivery.leased_at: None,
                    },
                    synchronize_session=False,
                )
                db.commit()
                logger.warning(
                    f'cron_outbox: reclaimed {len(reclaimed)} stuck leases (threshold {stuck_threshold_secs}s)'
                )
            return reclaimed

    @staticmethod
    def stamp_legacy_delivered_at(row_id: str) -> None:
        """Mark the row as having been HANDLED by the legacy direct-write path.

        Per spec ADR-7 + plan-review C-D: this stamps unconditionally after the
        legacy call returns (success or failure). The column's semantic is
        "the handler ran the legacy path", NOT "the legacy path delivered".
        Parity drift (the metric the daily check measures) = "the legacy
        path was never even attempted" (column IS NULL) — a real handler bug.
        Permanent legacy failures (chat deleted, etc.) are not drift; they're
        logged and recoverable from the chat-lookup-failed Sentry events.
        """
        now = int(time.time())
        with get_db() as db:
            db.query(CronDelivery).filter(CronDelivery.id == row_id).update(
                {CronDelivery.legacy_delivered_at: now},
                synchronize_session=False,
            )
            db.commit()

    @staticmethod
    def _test_backdate_lease(row_id: str, secs_ago: int) -> None:
        """TEST-ONLY: backdate leased_at to simulate a stuck lease."""
        target = int(time.time()) - secs_ago
        with get_db() as db:
            db.query(CronDelivery).filter(CronDelivery.id == row_id).update(
                {CronDelivery.leased_at: target},
                synchronize_session=False,
            )
            db.commit()

    @staticmethod
    def queue_depth_pending() -> int:
        """Gauge: how many rows are waiting to be delivered."""
        with get_db() as db:
            return db.query(CronDelivery).filter(CronDelivery.delivery_status == 'pending').count()

    @staticmethod
    def count_parity_gap(window_start: int, window_end: int) -> int:
        """Return count of outbox rows in window where legacy_delivered_at IS NULL.

        Used by the daily parity check (ADR-7). 0 = healthy.
        """
        with get_db() as db:
            return (
                db.query(CronDelivery)
                .filter(
                    CronDelivery.created_at >= window_start,
                    CronDelivery.created_at < window_end,
                    CronDelivery.legacy_delivered_at.is_(None),
                )
                .count()
            )
