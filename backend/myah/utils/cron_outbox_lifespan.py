"""Lifespan helper for the cron outbox worker. Extracted so tests can
exercise the registration logic without booting the full app via TestClient
(per plan-review H-1).
"""

from __future__ import annotations

import asyncio

from loguru import logger


def register_outbox_worker_if_enabled(app, mode: str) -> None:
    """Register the OutboxWorker on app.state if mode is shadow or outbox.

    Idempotent — safe to call multiple times (only the first registration
    creates the task).
    """
    if mode not in ('shadow', 'outbox'):
        return
    if hasattr(app.state, 'cron_outbox_worker_task'):
        return  # already registered

    from myah.utils.cron_outbox_worker import OutboxWorker

    worker = OutboxWorker()
    app.state.cron_outbox_worker = worker
    app.state.cron_outbox_worker_task = asyncio.create_task(worker.run())
    logger.info(f'cron_outbox: worker registered (mode={mode})')
