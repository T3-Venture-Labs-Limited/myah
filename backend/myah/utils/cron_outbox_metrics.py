"""Sentry instrumentation contract for the cron outbox (spec §4.2.5).

All functions are no-ops if sentry_sdk is unavailable. Span/breadcrumb
names are PINNED — T3-1085 alert configuration depends on them.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any


def _sentry():
    """Lazy import; returns None if sentry_sdk is unavailable."""
    try:
        import sentry_sdk

        return sentry_sdk
    except Exception:
        return None


def emit_row_inserted_breadcrumb(row_id: str, job_id: str, duplicate: bool = False) -> None:
    """Breadcrumb: cron_outbox row inserted via webhook handler."""
    sdk = _sentry()
    if sdk is None:
        return
    try:
        sdk.add_breadcrumb(
            category='cron_outbox',
            level='info',
            message=f'row_inserted row_id={row_id}',
            data={'event': 'row_inserted', 'row_id': row_id, 'job_id': job_id, 'duplicate': duplicate},
        )
    except Exception:
        pass


def emit_lease_reclaim_breadcrumb(reclaimed_count: int, row_ids: list[str]) -> None:
    sdk = _sentry()
    if sdk is None:
        return
    try:
        sdk.add_breadcrumb(
            category='cron_outbox',
            level='warning',
            message=f'lease_reclaim count={reclaimed_count}',
            data={'event': 'lease_reclaim', 'count': reclaimed_count, 'row_ids': row_ids[:20]},
        )
    except Exception:
        pass


def emit_retry_scheduled_breadcrumb(row_id: str, attempt: int, next_retry_in_secs: int, error: str) -> None:
    sdk = _sentry()
    if sdk is None:
        return
    try:
        sdk.add_breadcrumb(
            category='cron_outbox',
            level='error',
            message=f'retry_scheduled row_id={row_id} attempt={attempt}',
            data={
                'event': 'retry_scheduled',
                'row_id': row_id,
                'attempt': attempt,
                'next_retry_in_secs': next_retry_in_secs,
                'error': error[:400],
            },
        )
    except Exception:
        pass


def capture_row_failed(row_id: str, retry_count: int, last_error: str) -> None:
    sdk = _sentry()
    if sdk is None:
        return
    try:
        sdk.capture_message(
            f'cron_outbox: row {row_id} failed after {retry_count} attempts (event=row_failed)',
            level='error',
        )
    except Exception:
        pass


@contextmanager
def start_deliver_span(row_id: str, job_id: str, user_id: str, retry_count: int) -> Iterator[Any]:
    """Span: cron_outbox.deliver — wraps one row's delivery attempt.

    Tags per spec: cron_outbox.job_id, cron_outbox.user_id, cron_outbox.retry_count.
    """
    sdk = _sentry()
    if sdk is None:
        yield None
        return
    try:
        with sdk.start_span(op='cron_outbox.deliver', description=f'deliver row={row_id}') as span:
            if span is not None:
                span.set_tag('cron_outbox.job_id', job_id)
                span.set_tag('cron_outbox.user_id', user_id)
                span.set_tag('cron_outbox.retry_count', str(retry_count))
            yield span
    except Exception:
        yield None


def emit_parity_event(window_start: int, window_end: int, gap_count: int) -> None:
    """Per plan-review H-C: persistent Sentry event (not breadcrumb).

    Sentry retains capture_message events for the project's standard
    retention period (30-90 days typically). The 7-day cutover-gate
    query reads these events back via Sentry's API or dashboard.
    Breadcrumbs are NOT retained without an accompanying captured event.
    """
    sdk = _sentry()
    if sdk is None:
        return
    try:
        with sdk.push_scope() as scope:
            scope.set_tag('myah.cron.parity', 'daily_check')
            scope.set_tag('cron_outbox.parity.gap_count', str(gap_count))
            scope.set_extra('window_start', window_start)
            scope.set_extra('window_end', window_end)
            scope.set_extra('gap_count', gap_count)
            # Use level='info' for clean (gap==0) and 'warning' for drift.
            level = 'info' if gap_count == 0 else 'warning'
            sdk.capture_message(
                f'cron_outbox parity check: gap={gap_count} window=[{window_start},{window_end}]',
                level=level,
            )
    except Exception:
        pass
