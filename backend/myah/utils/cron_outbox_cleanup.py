"""Daily purge of old delivered cron_deliveries rows.

Keeps the table bounded. Per spec §10 (closed open question): delete
delivered rows >30 days old; keep failed rows forever for debugging.

Spec: T3-1087.
"""

from __future__ import annotations

import asyncio
import time

from loguru import logger
from myah.internal.db import get_db
from myah.models.cron_deliveries import CronDelivery

_PURGE_INTERVAL_SECS = 24 * 3600  # daily
_DEFAULT_RETENTION_DAYS = 30


def purge_old_delivered_rows(retention_days: int = _DEFAULT_RETENTION_DAYS) -> int:
    """Delete rows where delivery_status='delivered' AND delivered_at < cutoff.

    Returns count of deleted rows. Failed rows are NEVER purged.
    """
    cutoff = int(time.time()) - retention_days * 86400
    with get_db() as db:
        n_deleted = (
            db.query(CronDelivery)
            .filter(
                CronDelivery.delivery_status == 'delivered',
                CronDelivery.delivered_at < cutoff,
            )
            .delete(synchronize_session=False)
        )
        db.commit()
    if n_deleted:
        logger.info(f'cron_outbox_cleanup: purged {n_deleted} delivered rows older than {retention_days}d')
    return n_deleted


async def periodic_cron_outbox_cleanup() -> None:
    """Lifespan task: purge once at startup, then every 24h."""
    # Initial pass on startup (synchronous; runs in default executor).
    try:
        await asyncio.to_thread(purge_old_delivered_rows)
    except Exception:
        logger.exception('cron_outbox_cleanup: initial purge failed')

    while True:
        await asyncio.sleep(_PURGE_INTERVAL_SECS)
        try:
            await asyncio.to_thread(purge_old_delivered_rows)
        except Exception:
            logger.exception('cron_outbox_cleanup: periodic purge failed')
