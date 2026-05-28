"""Cron delivery outbox worker.

Reads pending rows from cron_deliveries, leases them, calls
_inject_cron_output_to_chat() with the row id as msg_id (idempotent),
emits Socket.IO events (best-effort), marks rows delivered. On
chat-write failure, schedules retry with exponential backoff and
±25% jitter (ADR-4). After 5 attempts → terminal 'failed' with
Sentry capture-message.

Architectural seam (ADR-3): _pop_next_batch + deliver_one are the
points where a future Postgres LISTEN/NOTIFY impl would slot in via
subclassing.

Spec: T3-1087 §4.2.3.
"""

from __future__ import annotations

import asyncio
import random
import time

from loguru import logger
from myah.env import get_cron_delivery_mode
from myah.models.cron_deliveries import CronDeliveries, CronDeliveryRow

_BACKOFF_SCHEDULE_SECS = [5, 15, 60, 300, 900]
_MAX_ATTEMPTS = 5
_TICK_INTERVAL_SECS = 1.0
_LEASE_TTL_SECS = 300
_RECLAIM_EVERY_N_TICKS = 60
_BATCH_SIZE = 50
_PARITY_EMIT_INTERVAL_SECS = 24 * 3600  # daily


def _compute_next_retry_at_secs(attempt: int) -> float:
    """Return next-retry offset (seconds) for attempt N (1-based)."""
    if attempt < 1 or attempt > len(_BACKOFF_SCHEDULE_SECS):
        return _BACKOFF_SCHEDULE_SECS[-1]
    base = _BACKOFF_SCHEDULE_SECS[attempt - 1]
    return base * random.uniform(0.75, 1.25)


class OutboxWorker:
    """Polls cron_deliveries and drives delivery. Single-replica only."""

    def __init__(self) -> None:
        self._tick_count = 0
        self._shutdown = asyncio.Event()
        self._last_parity_emit_at = 0

    async def run(self) -> None:
        # Read mode at start; re-read per tick so it can be flipped at runtime
        # via env var without restart (the lifespan check already gated start).
        start_mode = get_cron_delivery_mode()
        logger.info(
            f'cron_outbox: worker starting (mode={start_mode}, '
            f'tick={_TICK_INTERVAL_SECS}s, batch={_BATCH_SIZE}, '
            f'lease_ttl={_LEASE_TTL_SECS}s)'
        )
        while not self._shutdown.is_set():
            try:
                await self._tick()
            except asyncio.CancelledError:
                logger.info('cron_outbox: worker cancelled')
                raise
            except Exception:
                logger.exception('cron_outbox: tick raised; continuing')
            try:
                await asyncio.wait_for(self._shutdown.wait(), timeout=_TICK_INTERVAL_SECS)
            except TimeoutError:
                pass

    def stop(self) -> None:
        self._shutdown.set()

    async def _emit_parity_check_if_due(self, force: bool = False) -> None:
        """Emit the daily parity result if 24h have elapsed since the last.

        Per plan-review H-C: uses sentry_sdk.capture_message (persistent
        30+ days in Sentry) rather than add_breadcrumb (only attached to
        the next captured event, often never sent). Also writes a
        structured log line for the ops `grep`-based audit (Phase 1.5
        preflight check).
        """
        from myah.utils.cron_outbox_metrics import emit_parity_event

        now = int(time.time())
        if not force and (now - self._last_parity_emit_at) < _PARITY_EMIT_INTERVAL_SECS:
            return
        window_end = now
        window_start = now - 86400
        try:
            gap = await asyncio.to_thread(CronDeliveries.count_parity_gap, window_start, window_end)
        except Exception:
            logger.exception('cron_outbox: parity gap query failed')
            return
        emit_parity_event(window_start, window_end, gap)
        self._last_parity_emit_at = now
        # Structured log line for the Phase 1.5 preflight grep
        logger.info(f'cron_outbox: parity check window=[{window_start},{window_end}] gap={gap}')

    async def _tick(self) -> None:
        self._tick_count += 1

        if self._tick_count % _RECLAIM_EVERY_N_TICKS == 0:
            try:
                reclaimed = CronDeliveries.reclaim_stuck_leases(_LEASE_TTL_SECS)
                if reclaimed:
                    from myah.utils.cron_outbox_metrics import emit_lease_reclaim_breadcrumb

                    emit_lease_reclaim_breadcrumb(len(reclaimed), reclaimed)
            except Exception as exc:
                logger.error(f'cron_outbox: reclaim_stuck_leases failed: {exc}')

        # Parity emit (cheap; once per 24h actual work).
        await self._emit_parity_check_if_due()

        # Shadow mode: worker only does reclaim + parity emit. No row delivery.
        # Re-read per tick so monkeypatched env vars in tests take effect.
        if get_cron_delivery_mode() != 'outbox':
            return

        try:
            rows = self._pop_next_batch()
        except Exception:
            logger.exception('cron_outbox: pop_pending failed')
            return

        if not rows:
            return

        logger.debug(f'cron_outbox: tick {self._tick_count}: delivering {len(rows)} rows')
        for row in rows:
            try:
                await self.deliver_one(row)
            except Exception:
                logger.exception(f'cron_outbox: deliver_one raised for row={row.id}')

    def _pop_next_batch(self) -> list[CronDeliveryRow]:
        """Architectural seam (ADR-3) — override here for LISTEN/NOTIFY."""
        return CronDeliveries.pop_pending(batch_size=_BATCH_SIZE, lease_ttl_secs=_LEASE_TTL_SECS)

    async def deliver_one(self, row: CronDeliveryRow) -> None:
        """Deliver one row. Chat write = delivered. Socket = best-effort."""
        from myah.utils.cron_outbox_metrics import start_deliver_span

        with start_deliver_span(row.id, row.job_id, row.user_id, row.retry_count):
            await self._deliver_one_inner(row)

    async def _deliver_one_inner(self, row: CronDeliveryRow) -> None:
        """Inner delivery body wrapped by the Sentry span in deliver_one()."""
        from myah.routers.processes import _inject_cron_output_to_chat
        from myah.socket.main import sio

        metadata = row.metadata
        job_name = metadata.get('job_name') or row.job_id
        status = metadata.get('status') or 'ok'
        tool_calls_log = metadata.get('tool_calls_log')

        try:
            ok = await _inject_cron_output_to_chat(
                user_id=row.user_id,
                job_name=job_name,
                response=row.content,
                status=status,
                ran_at=row.ran_at_iso,
                tool_calls_log=tool_calls_log,
                chat_id=row.chat_id,
                msg_id=row.id,  # ADR-5: deterministic msg_id → idempotent retry
                suppress_chat_lookup_sentry=True,  # plan-review H-F: outbox owns the canonical capture
            )
        except Exception as exc:
            logger.exception(f'cron_outbox: _inject_cron_output_to_chat raised for row={row.id}')
            self._handle_failure(row, str(exc) or 'inject raised')
            return

        if not ok:
            self._handle_failure(row, 'chat write returned False')
            return

        try:
            CronDeliveries.mark_delivered(row.id)
        except Exception:
            logger.exception(f'cron_outbox: mark_delivered failed for row={row.id}')
            return

        # Best-effort socket emit.
        try:
            await sio.emit(
                'process:run-complete',
                {
                    'job_id': row.job_id,
                    'job_name': job_name,
                    'chat_id': row.chat_id,
                    'response': row.content,
                    'status': status,
                    'ran_at': row.ran_at_iso,
                },
                room=f'user:{row.user_id}',
            )
        except Exception as exc:
            logger.warning(f'cron_outbox: socket emit failed for row={row.id}: {exc}')

        # Best-effort AG-UI events.
        if tool_calls_log:
            try:
                from myah.utils.agui_adapter import events_from_tool_calls_log

                events = events_from_tool_calls_log(tool_calls_log, message_id='')
                for ev in events:
                    await sio.emit(
                        'events',
                        {'chat_id': None, 'data': {'type': 'agui:event', 'data': ev}},
                        room=f'user:{row.user_id}',
                    )
            except Exception as exc:
                logger.warning(f'cron_outbox: AG-UI emit failed for row={row.id}: {exc}')

    def _handle_failure(self, row: CronDeliveryRow, error: str) -> None:
        from myah.utils.cron_outbox_metrics import capture_row_failed, emit_retry_scheduled_breadcrumb

        next_attempt = row.retry_count + 1
        if next_attempt >= _MAX_ATTEMPTS:
            logger.error(
                f'cron_outbox: row={row.id} job={row.job_id} terminal-failed after {row.retry_count} retries: {error}'
            )
            try:
                CronDeliveries.mark_failed(row.id, error)
            except Exception:
                logger.exception(f'cron_outbox: mark_failed failed for row={row.id}')
            capture_row_failed(row.id, row.retry_count, error)
            return

        retry_offset = _compute_next_retry_at_secs(next_attempt)
        next_retry_at = int(time.time() + retry_offset)
        logger.warning(
            f'cron_outbox: row={row.id} retry {next_attempt}/{_MAX_ATTEMPTS} scheduled in {retry_offset}s: {error}'
        )
        try:
            CronDeliveries.mark_retry(row.id, error, next_retry_at)
            emit_retry_scheduled_breadcrumb(row.id, next_attempt, int(retry_offset), error)
        except Exception:
            logger.exception(f'cron_outbox: mark_retry failed for row={row.id}')
