"""Tests for the cron_deliveries outbox table, handler, worker, and parity logic."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import inspect, text


class TestCronDeliveriesTable:
    """Schema-level tests for the cron_deliveries table created by Alembic."""

    def test_table_exists_with_expected_columns(self, db_session):
        """After migration upgrade head, cron_deliveries has the columns the spec pins."""
        from myah.internal.db import get_db

        with get_db() as db:
            inspector = inspect(db.bind)
            assert 'cron_deliveries' in inspector.get_table_names(), (
                'cron_deliveries table missing — Alembic migration did not run'
            )
            columns = {c['name']: c for c in inspector.get_columns('cron_deliveries')}
            expected = {
                'id',
                'user_id',
                'job_id',
                'chat_id',
                'ran_at_iso',
                'content',
                'metadata_json',
                'delivery_status',
                'retry_count',
                'next_retry_at',
                'last_error',
                'leased_at',
                'created_at',
                'delivered_at',
                'legacy_delivered_at',
            }
            missing = expected - set(columns.keys())
            assert not missing, f'cron_deliveries missing columns: {missing}'

    def test_unique_constraint_on_job_id_ran_at_iso(self, db_session):
        """The (job_id, ran_at_iso) UNIQUE constraint enforces idempotency."""
        from myah.internal.db import get_db

        with get_db() as db:
            inspector = inspect(db.bind)
            uniques = inspector.get_unique_constraints('cron_deliveries')
            uniq_columns = [tuple(u['column_names']) for u in uniques]
            assert ('job_id', 'ran_at_iso') in uniq_columns, (
                f'UNIQUE (job_id, ran_at_iso) constraint missing; found: {uniq_columns}'
            )

    def test_status_retry_index_exists(self, db_session):
        """The (delivery_status, next_retry_at) index supports the worker pop query."""
        from myah.internal.db import get_db

        with get_db() as db:
            inspector = inspect(db.bind)
            indices = inspector.get_indexes('cron_deliveries')
            idx_columns = [tuple(i['column_names']) for i in indices]
            assert ('delivery_status', 'next_retry_at') in idx_columns, (
                f'(delivery_status, next_retry_at) index missing; found: {idx_columns}'
            )

    def test_parity_gap_partial_index_exists(self, db_session):
        """The partial index on (created_at) WHERE legacy_delivered_at IS NULL backs ADR-7."""
        from myah.internal.db import get_db

        with get_db() as db:
            inspector = inspect(db.bind)
            indices = inspector.get_indexes('cron_deliveries')
            parity_indices = [i for i in indices if i.get('name') == 'idx_cron_deliveries_parity_gap']
            assert len(parity_indices) == 1, (
                f'expected idx_cron_deliveries_parity_gap; got: {[i["name"] for i in indices]}'
            )


class TestCronDeliveriesCRUD:
    """Tests for the CronDeliveries CRUD helper class."""

    def _make_payload(self, **overrides: Any) -> dict[str, Any]:
        unique = str(uuid.uuid4())
        base = {
            'user_id': 'user-abc',
            'job_id': f'job-xyz-{unique}',
            'chat_id': 'chat-123',
            'ran_at_iso': f'2026-05-26T11:47:00.123+00:00-{unique}',
            'content': 'Hello from cron',
            'metadata_json': json.dumps(
                {
                    'job_name': 'smoke-test',
                    'status': 'ok',
                    'tool_calls_log': None,
                }
            ),
        }
        base.update(overrides)
        return base

    def test_insert_idempotent_creates_row(self, db_session):
        from myah.models.cron_deliveries import CronDeliveries

        row_id = CronDeliveries.insert_idempotent(self._make_payload())
        assert row_id is not None
        row = CronDeliveries.get_by_id(row_id)
        assert row is not None
        assert row.delivery_status == 'pending'
        assert row.retry_count == 0

    def test_insert_idempotent_duplicate_returns_existing_id(self, db_session):
        """Second insert with same (job_id, ran_at_iso) returns the existing row's id."""
        from myah.models.cron_deliveries import CronDeliveries

        payload = self._make_payload()
        first_id = CronDeliveries.insert_idempotent(payload)
        second_id = CronDeliveries.insert_idempotent({**payload, 'content': 'different content'})
        assert second_id == first_id
        row = CronDeliveries.get_by_id(first_id)
        assert row.content == 'Hello from cron', 'original content preserved (ON CONFLICT DO NOTHING)'

    def test_pop_pending_returns_oldest_first(self, db_session):
        from myah.models.cron_deliveries import CronDeliveries

        a_id = CronDeliveries.insert_idempotent(self._make_payload(job_id='a', ran_at_iso=f'1-{uuid.uuid4()}'))
        time.sleep(0.01)
        b_id = CronDeliveries.insert_idempotent(self._make_payload(job_id='b', ran_at_iso=f'2-{uuid.uuid4()}'))
        leased = CronDeliveries.pop_pending(batch_size=10, lease_ttl_secs=300)
        leased_ids = [r.id for r in leased]
        assert leased_ids == [a_id, b_id]
        for r in leased:
            assert r.delivery_status == 'delivering'
            assert r.leased_at is not None

    def test_pop_pending_skips_future_next_retry_at(self, db_session):
        from myah.models.cron_deliveries import CronDeliveries

        future = int(time.time()) + 600
        not_yet_id = CronDeliveries.insert_idempotent(self._make_payload(job_id='a', ran_at_iso=f'1-{uuid.uuid4()}'))
        CronDeliveries.set_next_retry_at(not_yet_id, future)
        ready_id = CronDeliveries.insert_idempotent(self._make_payload(job_id='b', ran_at_iso=f'2-{uuid.uuid4()}'))
        leased = CronDeliveries.pop_pending(batch_size=10, lease_ttl_secs=300)
        leased_ids = [r.id for r in leased]
        assert leased_ids == [ready_id], 'future-retry row should be skipped'

    def test_mark_delivered_sets_terminal_state(self, db_session):
        from myah.models.cron_deliveries import CronDeliveries

        row_id = CronDeliveries.insert_idempotent(self._make_payload())
        CronDeliveries.pop_pending(batch_size=10, lease_ttl_secs=300)  # mark delivering
        CronDeliveries.mark_delivered(row_id)
        row = CronDeliveries.get_by_id(row_id)
        assert row.delivery_status == 'delivered'
        assert row.delivered_at is not None
        assert row.leased_at is None

    def test_mark_retry_increments_count_and_schedules(self, db_session):
        from myah.models.cron_deliveries import CronDeliveries

        row_id = CronDeliveries.insert_idempotent(self._make_payload())
        CronDeliveries.pop_pending(batch_size=10, lease_ttl_secs=300)
        CronDeliveries.mark_retry(row_id, error='chat lookup failed', next_retry_at=int(time.time()) + 5)
        row = CronDeliveries.get_by_id(row_id)
        assert row.delivery_status == 'pending'
        assert row.retry_count == 1
        assert row.last_error == 'chat lookup failed'
        assert row.next_retry_at is not None
        assert row.leased_at is None

    def test_mark_failed_after_max_retries(self, db_session):
        from myah.models.cron_deliveries import CronDeliveries

        row_id = CronDeliveries.insert_idempotent(self._make_payload())
        CronDeliveries.mark_failed(row_id, error='exhausted retries')
        row = CronDeliveries.get_by_id(row_id)
        assert row.delivery_status == 'failed'
        assert row.last_error == 'exhausted retries'
        assert row.delivered_at is None
        assert row.leased_at is None

    def test_reclaim_stuck_lease(self, db_session):
        """A delivering row with leased_at older than threshold gets reset to pending."""
        from myah.models.cron_deliveries import CronDeliveries

        row_id = CronDeliveries.insert_idempotent(self._make_payload())
        CronDeliveries.pop_pending(batch_size=10, lease_ttl_secs=300)
        # Backdate leased_at to 600s ago
        CronDeliveries._test_backdate_lease(row_id, secs_ago=600)
        reclaimed = CronDeliveries.reclaim_stuck_leases(stuck_threshold_secs=300)
        assert row_id in reclaimed
        row = CronDeliveries.get_by_id(row_id)
        assert row.delivery_status == 'pending'
        assert row.leased_at is None

    def test_stamp_legacy_delivered_at(self, db_session):
        """Per plan-review C-D: stamps unconditionally; semantic is 'handler ran'."""
        from myah.models.cron_deliveries import CronDeliveries

        row_id = CronDeliveries.insert_idempotent(self._make_payload())
        CronDeliveries.stamp_legacy_delivered_at(row_id)
        row = CronDeliveries.get_by_id(row_id)
        assert row.legacy_delivered_at is not None


class TestInjectCronOutputIdempotency:
    """ADR-5: _inject_cron_output_to_chat must accept an optional msg_id."""

    @pytest.mark.asyncio
    async def test_msg_id_parameter_reuses_id_on_repeat_call(self, db_session, seed_user_and_chat):
        """Calling twice with the same msg_id produces ONE chat message row."""
        from myah.models.chats import Chats
        from myah.routers.processes import _inject_cron_output_to_chat

        user_id, chat_id, chat_title = seed_user_and_chat
        stable_msg_id = str(uuid.uuid4())

        result_a = await _inject_cron_output_to_chat(
            user_id=user_id,
            job_name='test-job',
            response='hello world',
            status='ok',
            ran_at='2026-05-26T11:47:00+00:00',
            tool_calls_log=None,
            chat_id=chat_id,
            msg_id=stable_msg_id,
        )
        assert result_a is True

        result_b = await _inject_cron_output_to_chat(
            user_id=user_id,
            job_name='test-job',
            response='hello world',
            status='ok',
            ran_at='2026-05-26T11:47:00+00:00',
            tool_calls_log=None,
            chat_id=chat_id,
            msg_id=stable_msg_id,
        )
        assert result_b is True

        chat = Chats.get_chat_by_id(chat_id)
        messages = chat.chat.get('history', {}).get('messages', {})
        # The msg_id we passed should be exactly one message in the dict
        cron_messages = [m for m_id, m in messages.items() if m_id == stable_msg_id]
        assert len(cron_messages) == 1, f'Expected exactly 1 message with stable_msg_id, got {len(cron_messages)}'

        # Per plan-review H-G: also verify the chat_messages table (not just the
        # legacy JSON-blob view) has exactly one row. Chats.upsert_message_to_chat_by_id_and_message_id
        # writes to BOTH stores; the test must cover both.
        from myah.models.chat_messages import ChatMessages

        rows = ChatMessages.get_messages_by_chat_id(chat_id)
        msgs_with_stable_id = [r for r in rows if getattr(r, 'id', None) == f'{chat_id}-{stable_msg_id}']
        assert len(msgs_with_stable_id) == 1, (
            f'chat_messages table must have exactly 1 row for stable msg_id, got {len(msgs_with_stable_id)}'
        )

    @pytest.mark.asyncio
    async def test_msg_id_default_preserves_existing_behaviour(self, db_session, seed_user_and_chat):
        """Calling without msg_id (None) generates a fresh uuid — back-compat with non-outbox callers."""
        from myah.models.chats import Chats
        from myah.routers.processes import _inject_cron_output_to_chat

        user_id, chat_id, _ = seed_user_and_chat
        result_a = await _inject_cron_output_to_chat(
            user_id=user_id,
            job_name='j',
            response='r1',
            status='ok',
            ran_at='r',
            tool_calls_log=None,
            chat_id=chat_id,
        )
        result_b = await _inject_cron_output_to_chat(
            user_id=user_id,
            job_name='j',
            response='r2',
            status='ok',
            ran_at='r',
            tool_calls_log=None,
            chat_id=chat_id,
        )
        assert result_a and result_b
        chat = Chats.get_chat_by_id(chat_id)
        messages = chat.chat.get('history', {}).get('messages', {})
        # Two distinct messages because no msg_id was passed
        cron_msgs = [m for m in messages.values() if m.get('content', '').find('Cron run') != -1]
        assert len(cron_msgs) == 2


class TestWebhookHandlerMode:
    """Webhook behaviour per MYAH_CRON_DELIVERY_MODE.

    Per plan-review S-6: every test must request `webhook_bearer` so the
    fixture monkeypatches both MYAH_AGENT_BEARER_TOKEN and the
    module-level `CRON_WEBHOOK_SECRET` constant that processes.py
    captured at import time (processes.py:951). Without it, every
    POST returns 401.
    """

    @pytest.mark.asyncio
    async def test_legacy_mode_writes_only_to_chat_no_outbox_row(
        self, db_session, async_client, seed_user_and_chat, webhook_bearer, monkeypatch
    ):
        """legacy mode = pre-Phase-1 behaviour. No outbox row created."""
        monkeypatch.setenv('MYAH_CRON_DELIVERY_MODE', 'legacy')
        import importlib

        import myah.env

        importlib.reload(myah.env)

        user_id, chat_id, _ = seed_user_and_chat
        bearer = webhook_bearer  # provided by Task 1.0's conftest fixture; also monkeypatches CRON_WEBHOOK_SECRET
        resp = await async_client.post(
            '/api/v1/processes/webhook/run-complete',
            json={
                'user_id': user_id,
                'job_id': 'job-legacy',
                'job_name': 'legacy-job',
                'chat_id': chat_id,
                'response': 'legacy content',
                'status': 'ok',
                'ran_at': '2026-05-26T11:47:00+00:00',
                'tool_calls_log': None,
            },
            headers={'Authorization': f'Bearer {bearer}'},
        )
        assert resp.status_code == 200
        # In legacy mode, no outbox row exists.
        from myah.internal.db import get_db

        with get_db() as db:
            count = db.execute(text("SELECT count(*) FROM cron_deliveries WHERE job_id = 'job-legacy'")).scalar()
            assert count == 0, 'legacy mode must not write to outbox table'

    @pytest.mark.asyncio
    async def test_shadow_mode_writes_both_and_stamps_legacy_delivered_at(
        self, db_session, async_client, seed_user_and_chat, webhook_bearer, monkeypatch
    ):
        """shadow mode = write to outbox AND legacy. legacy_delivered_at stamped on success."""
        monkeypatch.setenv('MYAH_CRON_DELIVERY_MODE', 'shadow')
        import importlib

        import myah.env

        importlib.reload(myah.env)

        user_id, chat_id, _ = seed_user_and_chat
        bearer = webhook_bearer
        resp = await async_client.post(
            '/api/v1/processes/webhook/run-complete',
            json={
                'user_id': user_id,
                'job_id': 'job-shadow',
                'job_name': 'shadow-job',
                'chat_id': chat_id,
                'response': 'shadow content',
                'status': 'ok',
                'ran_at': '2026-05-26T11:48:00+00:00',
                'tool_calls_log': None,
            },
            headers={'Authorization': f'Bearer {bearer}'},
        )
        assert resp.status_code == 200
        from myah.internal.db import get_db

        with get_db() as db:
            row = db.execute(text("SELECT * FROM cron_deliveries WHERE job_id = 'job-shadow'")).mappings().first()
            assert row is not None, 'shadow mode must write outbox row'
            assert row['delivery_status'] == 'pending'
            assert row['legacy_delivered_at'] is not None, (
                'shadow mode must stamp legacy_delivered_at after legacy path runs '
                '(per plan-review C-D: stamped unconditionally on success OR failure)'
            )

    @pytest.mark.asyncio
    async def test_outbox_mode_writes_outbox_no_legacy_chat_write(
        self, db_session, async_client, seed_user_and_chat, webhook_bearer, monkeypatch
    ):
        """outbox mode = outbox row only; legacy direct-write bypassed."""
        monkeypatch.setenv('MYAH_CRON_DELIVERY_MODE', 'outbox')
        import importlib

        import myah.env

        importlib.reload(myah.env)
        from myah.models.chats import Chats

        user_id, chat_id, _ = seed_user_and_chat
        bearer = webhook_bearer
        prior_msg_count = len(Chats.get_chat_by_id(chat_id).chat.get('history', {}).get('messages', {}))

        resp = await async_client.post(
            '/api/v1/processes/webhook/run-complete',
            json={
                'user_id': user_id,
                'job_id': 'job-outbox',
                'job_name': 'outbox-job',
                'chat_id': chat_id,
                'response': 'outbox content',
                'status': 'ok',
                'ran_at': '2026-05-26T11:49:00+00:00',
                'tool_calls_log': None,
            },
            headers={'Authorization': f'Bearer {bearer}'},
        )
        assert resp.status_code == 200
        # Outbox row exists; chat is NOT yet written (worker hasn't run).
        from myah.internal.db import get_db

        with get_db() as db:
            row = (
                db.execute(text("SELECT delivery_status FROM cron_deliveries WHERE job_id = 'job-outbox'"))
                .mappings()
                .first()
            )
            assert row is not None and row['delivery_status'] == 'pending'
        new_msg_count = len(Chats.get_chat_by_id(chat_id).chat.get('history', {}).get('messages', {}))
        assert new_msg_count == prior_msg_count, 'outbox mode must NOT write to chat synchronously (worker handles it)'

    @pytest.mark.asyncio
    async def test_empty_ran_at_skips_outbox_insert(
        self, db_session, async_client, seed_user_and_chat, webhook_bearer, monkeypatch
    ):
        """Per spec §4.2.2 webhook contract + plan-review M item: ran_at is
        required to build the idempotency key. Empty ran_at must NOT crash
        and must NOT write a row in shadow/outbox modes — the handler logs
        a warning and returns 200 (legacy path still fires in shadow).
        """
        monkeypatch.setenv('MYAH_CRON_DELIVERY_MODE', 'outbox')
        import importlib

        import myah.env

        importlib.reload(myah.env)

        user_id, chat_id, _ = seed_user_and_chat
        bearer = webhook_bearer
        resp = await async_client.post(
            '/api/v1/processes/webhook/run-complete',
            json={
                'user_id': user_id,
                'job_id': 'job-noran',
                'job_name': 'no-ran-at',
                'chat_id': chat_id,
                'response': 'x',
                'status': 'ok',
                'ran_at': '',  # empty — violates contract
                'tool_calls_log': None,
            },
            headers={'Authorization': f'Bearer {bearer}'},
        )
        assert resp.status_code == 200, 'handler must not crash on contract violation'
        from myah.internal.db import get_db

        with get_db() as db:
            count = db.execute(text("SELECT count(*) FROM cron_deliveries WHERE job_id = 'job-noran'")).scalar()
            assert count == 0, 'empty ran_at must not produce an outbox row'

    @pytest.mark.asyncio
    async def test_duplicate_post_is_idempotent(
        self, db_session, async_client, seed_user_and_chat, webhook_bearer, monkeypatch
    ):
        """Second POST with same (job_id, ran_at) does NOT create a duplicate row."""
        monkeypatch.setenv('MYAH_CRON_DELIVERY_MODE', 'outbox')
        import importlib

        import myah.env

        importlib.reload(myah.env)

        user_id, chat_id, _ = seed_user_and_chat
        bearer = webhook_bearer
        payload = {
            'user_id': user_id,
            'job_id': 'job-dup',
            'job_name': 'dup-job',
            'chat_id': chat_id,
            'response': 'first',
            'status': 'ok',
            'ran_at': '2026-05-26T11:50:00+00:00',
            'tool_calls_log': None,
        }
        await async_client.post(
            '/api/v1/processes/webhook/run-complete', json=payload, headers={'Authorization': f'Bearer {bearer}'}
        )
        await async_client.post(
            '/api/v1/processes/webhook/run-complete',
            json={**payload, 'response': 'second'},
            headers={'Authorization': f'Bearer {bearer}'},
        )
        from myah.internal.db import get_db

        with get_db() as db:
            count = db.execute(text("SELECT count(*) FROM cron_deliveries WHERE job_id = 'job-dup'")).scalar()
            assert count == 1, 'duplicate POST must dedupe to one row'
            content = db.execute(text("SELECT content FROM cron_deliveries WHERE job_id = 'job-dup'")).scalar()
            assert content == 'first', 'first POST wins (ON CONFLICT DO NOTHING)'


class TestOutboxWorkerSingleTick:
    """Tests for OutboxWorker.deliver_one() and the tick loop's pop+deliver path."""

    @pytest.mark.asyncio
    async def test_deliver_one_writes_chat_and_marks_delivered(self, db_session, seed_user_and_chat):
        from myah.models.cron_deliveries import CronDeliveries
        from myah.utils.cron_outbox_worker import OutboxWorker

        user_id, chat_id, _ = seed_user_and_chat
        row_id = CronDeliveries.insert_idempotent(
            {
                'user_id': user_id,
                'job_id': 'j1',
                'chat_id': chat_id,
                'ran_at_iso': '2026-05-26T11:47:00+00:00',
                'content': 'hello',
                'metadata_json': json.dumps({'job_name': 'j1', 'status': 'ok', 'tool_calls_log': None}),
            }
        )
        leased = CronDeliveries.pop_pending(batch_size=10, lease_ttl_secs=300)
        assert len(leased) == 1
        row = leased[0]

        worker = OutboxWorker()
        with patch('myah.socket.main.sio.emit', new_callable=AsyncMock):
            await worker.deliver_one(row)

        final = CronDeliveries.get_by_id(row_id)
        assert final.delivery_status == 'delivered'
        assert final.delivered_at is not None
        assert final.leased_at is None

    @pytest.mark.asyncio
    async def test_deliver_one_uses_outbox_row_id_as_msg_id(self, db_session, seed_user_and_chat):
        """ADR-5: row.id must be passed as msg_id so retries are idempotent."""
        from myah.models.cron_deliveries import CronDeliveries
        from myah.utils.cron_outbox_worker import OutboxWorker

        user_id, chat_id, _ = seed_user_and_chat
        row_id = CronDeliveries.insert_idempotent(
            {
                'user_id': user_id,
                'job_id': 'jmsg',
                'chat_id': chat_id,
                'ran_at_iso': '2026-05-26T11:47:00+00:00',
                'content': 'idempotent',
                'metadata_json': json.dumps({'job_name': 'jmsg', 'status': 'ok', 'tool_calls_log': None}),
            }
        )
        leased = CronDeliveries.pop_pending(batch_size=10, lease_ttl_secs=300)
        row = leased[0]

        worker = OutboxWorker()
        with (
            patch('myah.routers.processes._inject_cron_output_to_chat', new_callable=AsyncMock) as mock_inject,
            patch('myah.socket.main.sio.emit', new_callable=AsyncMock),
        ):
            mock_inject.return_value = True
            await worker.deliver_one(row)
            kwargs = mock_inject.call_args.kwargs
            assert kwargs.get('msg_id') == row_id, (
                f'OutboxWorker must pass row.id as msg_id; got {kwargs.get("msg_id")}'
            )

    @pytest.mark.asyncio
    async def test_deliver_one_chat_write_failure_marks_retry(self, db_session, seed_user_and_chat):
        from myah.models.cron_deliveries import CronDeliveries
        from myah.utils.cron_outbox_worker import OutboxWorker

        user_id, chat_id, _ = seed_user_and_chat
        row_id = CronDeliveries.insert_idempotent(
            {
                'user_id': user_id,
                'job_id': 'jretry',
                'chat_id': chat_id,
                'ran_at_iso': '2026-05-26T11:47:00+00:00',
                'content': 'will fail',
                'metadata_json': json.dumps({'job_name': 'jretry', 'status': 'ok', 'tool_calls_log': None}),
            }
        )
        leased = CronDeliveries.pop_pending(batch_size=10, lease_ttl_secs=300)
        row = leased[0]

        worker = OutboxWorker()
        with patch('myah.routers.processes._inject_cron_output_to_chat', new_callable=AsyncMock) as mock_inject:
            mock_inject.return_value = False
            await worker.deliver_one(row)

        final = CronDeliveries.get_by_id(row_id)
        assert final.delivery_status == 'pending'
        assert final.retry_count == 1
        assert final.next_retry_at is not None
        assert final.last_error is not None

    @pytest.mark.asyncio
    async def test_deliver_one_terminal_failed_after_5_retries(self, db_session, seed_user_and_chat):
        from myah.models.cron_deliveries import CronDeliveries, CronDelivery
        from myah.utils.cron_outbox_worker import OutboxWorker

        user_id, chat_id, _ = seed_user_and_chat
        row_id = CronDeliveries.insert_idempotent(
            {
                'user_id': user_id,
                'job_id': 'jfail',
                'chat_id': chat_id,
                'ran_at_iso': '2026-05-26T11:47:00+00:00',
                'content': 'will exhaust',
                'metadata_json': json.dumps({'job_name': 'jfail', 'status': 'ok', 'tool_calls_log': None}),
            }
        )
        # Backdate retry_count to 4 → one more failure terminal-fails
        from myah.internal.db import get_db

        with get_db() as db:
            db.query(CronDelivery).filter(CronDelivery.id == row_id).update(
                {
                    CronDelivery.retry_count: 4,
                    CronDelivery.delivery_status: 'delivering',
                    CronDelivery.leased_at: int(time.time()),
                },
                synchronize_session=False,
            )
            db.commit()
        row = CronDeliveries.get_by_id(row_id)

        worker = OutboxWorker()
        with patch('myah.routers.processes._inject_cron_output_to_chat', new_callable=AsyncMock) as mock_inject:
            mock_inject.return_value = False
            await worker.deliver_one(row)

        final = CronDeliveries.get_by_id(row_id)
        assert final.delivery_status == 'failed'
        assert final.last_error is not None

    @pytest.mark.asyncio
    async def test_socket_emit_failure_does_not_block_delivered(self, db_session, seed_user_and_chat):
        """ADR-5: socket emit is best-effort; chat write success → delivered regardless."""
        from myah.models.cron_deliveries import CronDeliveries
        from myah.utils.cron_outbox_worker import OutboxWorker

        user_id, chat_id, _ = seed_user_and_chat
        row_id = CronDeliveries.insert_idempotent(
            {
                'user_id': user_id,
                'job_id': 'jsock',
                'chat_id': chat_id,
                'ran_at_iso': '2026-05-26T11:47:00+00:00',
                'content': 'ok',
                'metadata_json': json.dumps({'job_name': 'jsock', 'status': 'ok', 'tool_calls_log': None}),
            }
        )
        leased = CronDeliveries.pop_pending(batch_size=10, lease_ttl_secs=300)
        row = leased[0]

        worker = OutboxWorker()
        with patch('myah.socket.main.sio.emit', new_callable=AsyncMock) as mock_emit:
            mock_emit.side_effect = RuntimeError('socket disconnected')
            await worker.deliver_one(row)

        final = CronDeliveries.get_by_id(row_id)
        assert final.delivery_status == 'delivered', 'socket emit failure must not block delivered terminal state'

    def test_compute_next_retry_at_exponential_schedule(self):
        """Backoff schedule [5, 15, 60, 300, 900]s with ±25% jitter (ADR-4)."""
        from myah.utils.cron_outbox_worker import _compute_next_retry_at_secs

        for attempt, base in [(1, 5), (2, 15), (3, 60), (4, 300), (5, 900)]:
            samples = [_compute_next_retry_at_secs(attempt) for _ in range(40)]
            lo, hi = base * 0.75, base * 1.25
            for s in samples:
                assert lo <= s <= hi, f'attempt {attempt}: backoff {s}s outside [{lo}, {hi}] around {base}s'


class TestOutboxWorkerLifespanRegistration:
    """Worker task registration logic — tested via the helper, not TestClient(app)."""

    def test_legacy_mode_does_not_register(self, monkeypatch):
        from myah.utils.cron_outbox_lifespan import register_outbox_worker_if_enabled

        class FakeApp:
            class state:
                pass

        app_obj = FakeApp()
        register_outbox_worker_if_enabled(app_obj, mode='legacy')
        assert not hasattr(app_obj.state, 'cron_outbox_worker_task')

    def test_shadow_mode_registers(self, monkeypatch):
        import asyncio

        from myah.utils.cron_outbox_lifespan import register_outbox_worker_if_enabled

        async def _run():
            class FakeApp:
                class state:
                    pass

            app_obj = FakeApp()
            register_outbox_worker_if_enabled(app_obj, mode='shadow')
            assert hasattr(app_obj.state, 'cron_outbox_worker_task')
            assert not app_obj.state.cron_outbox_worker_task.done()
            # Clean up the task so it doesn't leak.
            app_obj.state.cron_outbox_worker.stop()
            try:
                await asyncio.wait_for(app_obj.state.cron_outbox_worker_task, timeout=2.0)
            except (TimeoutError, asyncio.CancelledError):
                app_obj.state.cron_outbox_worker_task.cancel()

        asyncio.run(_run())

    def test_outbox_mode_registers(self, monkeypatch):
        import asyncio

        from myah.utils.cron_outbox_lifespan import register_outbox_worker_if_enabled

        async def _run():
            class FakeApp:
                class state:
                    pass

            app_obj = FakeApp()
            register_outbox_worker_if_enabled(app_obj, mode='outbox')
            assert hasattr(app_obj.state, 'cron_outbox_worker_task')
            assert not app_obj.state.cron_outbox_worker_task.done()
            app_obj.state.cron_outbox_worker.stop()
            try:
                await asyncio.wait_for(app_obj.state.cron_outbox_worker_task, timeout=2.0)
            except (TimeoutError, asyncio.CancelledError):
                app_obj.state.cron_outbox_worker_task.cancel()

        asyncio.run(_run())


class TestCronOutboxCleanup:
    """30-day purge of delivered rows (spec §10 Open Q1 closed)."""

    def test_cleanup_deletes_old_delivered_rows(self, db_session, seed_user_and_chat):
        from myah.internal.db import get_db
        from myah.models.cron_deliveries import CronDeliveries, CronDelivery
        from myah.utils.cron_outbox_cleanup import purge_old_delivered_rows

        user_id, chat_id, _ = seed_user_and_chat
        # Old delivered row (40 days ago)
        old_id = CronDeliveries.insert_idempotent(
            {
                'user_id': user_id,
                'job_id': 'old',
                'chat_id': chat_id,
                'ran_at_iso': 'r1',
                'content': 'old',
                'metadata_json': '{}',
            }
        )
        with get_db() as db:
            forty_days_ago = int(time.time()) - 40 * 86400
            db.query(CronDelivery).filter(CronDelivery.id == old_id).update(
                {
                    CronDelivery.delivery_status: 'delivered',
                    CronDelivery.delivered_at: forty_days_ago,
                },
                synchronize_session=False,
            )
            db.commit()

        # Recent delivered row (1 day ago — keep)
        recent_id = CronDeliveries.insert_idempotent(
            {
                'user_id': user_id,
                'job_id': 'recent',
                'chat_id': chat_id,
                'ran_at_iso': 'r2',
                'content': 'recent',
                'metadata_json': '{}',
            }
        )
        with get_db() as db:
            one_day_ago = int(time.time()) - 86400
            db.query(CronDelivery).filter(CronDelivery.id == recent_id).update(
                {
                    CronDelivery.delivery_status: 'delivered',
                    CronDelivery.delivered_at: one_day_ago,
                },
                synchronize_session=False,
            )
            db.commit()

        # Old failed row (40 days ago — keep, failed rows are kept forever)
        failed_id = CronDeliveries.insert_idempotent(
            {
                'user_id': user_id,
                'job_id': 'failed',
                'chat_id': chat_id,
                'ran_at_iso': 'r3',
                'content': 'failed',
                'metadata_json': '{}',
            }
        )
        with get_db() as db:
            db.query(CronDelivery).filter(CronDelivery.id == failed_id).update(
                {
                    CronDelivery.delivery_status: 'failed',
                    CronDelivery.delivered_at: int(time.time()) - 40 * 86400,
                },
                synchronize_session=False,
            )
            db.commit()

        deleted_count = purge_old_delivered_rows(retention_days=30)
        assert deleted_count == 1, 'only the old delivered row should be purged'
        assert CronDeliveries.get_by_id(old_id) is None
        assert CronDeliveries.get_by_id(recent_id) is not None
        assert CronDeliveries.get_by_id(failed_id) is not None


class TestCronOutboxSentryContract:
    """Section 4.2.5: pinned Sentry transaction/span/breadcrumb names."""

    @pytest.mark.asyncio
    async def test_deliver_one_emits_named_span(self, db_session, seed_user_and_chat):
        """Each row delivery emits a `cron_outbox.deliver` span with row + job tags."""
        from myah.models.cron_deliveries import CronDeliveries
        from myah.utils.cron_outbox_worker import OutboxWorker

        user_id, chat_id, _ = seed_user_and_chat
        CronDeliveries.insert_idempotent(
            {
                'user_id': user_id,
                'job_id': 'jspan',
                'chat_id': chat_id,
                'ran_at_iso': '2026-05-26T11:47:00+00:00',
                'content': 'span-test',
                'metadata_json': json.dumps({'job_name': 'jspan', 'status': 'ok', 'tool_calls_log': None}),
            }
        )
        leased = CronDeliveries.pop_pending(batch_size=10, lease_ttl_secs=300)
        row = leased[0]

        worker = OutboxWorker()
        with patch('sentry_sdk.start_span') as mock_span, patch('myah.socket.main.sio.emit', new_callable=AsyncMock):
            await worker.deliver_one(row)
            span_calls = [call.kwargs for call in mock_span.call_args_list]
            assert any(call.get('op') == 'cron_outbox.deliver' for call in span_calls), (
                f'Expected cron_outbox.deliver span; got: {span_calls}'
            )

    def test_emit_row_inserted_breadcrumb_uses_named_category(self):
        from myah.utils.cron_outbox_metrics import emit_row_inserted_breadcrumb

        with patch('sentry_sdk.add_breadcrumb') as mock_crumb:
            emit_row_inserted_breadcrumb(row_id='abc', job_id='j')
            mock_crumb.assert_called_once()
            kwargs = mock_crumb.call_args.kwargs
            assert kwargs.get('category') == 'cron_outbox'
            assert kwargs.get('level') == 'info'

    @pytest.mark.asyncio
    async def test_terminal_failed_fires_capture_message(self, db_session, seed_user_and_chat):
        """Per plan-review H-3: pytest-asyncio decorator + native await (no run_until_complete)."""
        from myah.internal.db import get_db
        from myah.models.cron_deliveries import CronDeliveries, CronDelivery
        from myah.utils.cron_outbox_worker import OutboxWorker

        user_id, chat_id, _ = seed_user_and_chat
        row_id = CronDeliveries.insert_idempotent(
            {
                'user_id': user_id,
                'job_id': 'jcap',
                'chat_id': chat_id,
                'ran_at_iso': '2026-05-26T11:47:00+00:00',
                'content': 'capture',
                'metadata_json': json.dumps({'job_name': 'jcap', 'status': 'ok', 'tool_calls_log': None}),
            }
        )
        with get_db() as db:
            db.query(CronDelivery).filter(CronDelivery.id == row_id).update(
                {CronDelivery.retry_count: 4}, synchronize_session=False
            )
            db.commit()
        row = CronDeliveries.get_by_id(row_id)

        worker = OutboxWorker()
        with (
            patch('sentry_sdk.capture_message') as mock_cap,
            patch('myah.routers.processes._inject_cron_output_to_chat', new_callable=AsyncMock) as mock_inject,
        ):
            mock_inject.return_value = False
            await worker.deliver_one(row)
            mock_cap.assert_called_once()
            args, kwargs = mock_cap.call_args
            assert 'cron_outbox' in args[0]
            assert kwargs.get('level') == 'error'


class TestCronOutboxParityEmit:
    """ADR-7: daily parity check counts rows with legacy_delivered_at IS NULL."""

    def test_count_parity_gap_returns_correct_count(self, db_session, seed_user_and_chat):
        from myah.internal.db import get_db
        from myah.models.cron_deliveries import CronDeliveries, CronDelivery

        user_id, chat_id, _ = seed_user_and_chat
        now = int(time.time())
        window_start = now - 86400
        window_end = now

        # Row 1: in window, legacy stamped → not in gap
        id_a = CronDeliveries.insert_idempotent(
            {
                'user_id': user_id,
                'job_id': 'a',
                'chat_id': chat_id,
                'ran_at_iso': 'r1',
                'content': 'a',
                'metadata_json': '{}',
            }
        )
        CronDeliveries.stamp_legacy_delivered_at(id_a)
        with get_db() as db:
            db.query(CronDelivery).filter(CronDelivery.id == id_a).update(
                {CronDelivery.created_at: window_start + 3600},
                synchronize_session=False,
            )
            db.commit()

        # Row 2: in window, legacy NOT stamped → in gap
        id_b = CronDeliveries.insert_idempotent(
            {
                'user_id': user_id,
                'job_id': 'b',
                'chat_id': chat_id,
                'ran_at_iso': 'r2',
                'content': 'b',
                'metadata_json': '{}',
            }
        )
        with get_db() as db:
            db.query(CronDelivery).filter(CronDelivery.id == id_b).update(
                {CronDelivery.created_at: window_start + 7200},
                synchronize_session=False,
            )
            db.commit()

        # Row 3: outside window, legacy NOT stamped → not counted
        id_c = CronDeliveries.insert_idempotent(
            {
                'user_id': user_id,
                'job_id': 'c',
                'chat_id': chat_id,
                'ran_at_iso': 'r3',
                'content': 'c',
                'metadata_json': '{}',
            }
        )
        with get_db() as db:
            db.query(CronDelivery).filter(CronDelivery.id == id_c).update(
                {CronDelivery.created_at: window_start - 86400},
                synchronize_session=False,
            )
            db.commit()

        gap = CronDeliveries.count_parity_gap(window_start, window_end)
        assert gap == 1, f'expected 1 gap (row b), got {gap}'

    @pytest.mark.asyncio
    async def test_worker_emits_daily_parity_breadcrumb_in_shadow_mode(self, db_session, monkeypatch):
        """Per plan-review H-C: parity emit must use sentry_sdk.capture_message
        (which Sentry persists for 30+ days), NOT add_breadcrumb (which only
        appears in the next captured event). The test verifies the persistent
        path is exercised."""
        monkeypatch.setenv('MYAH_CRON_DELIVERY_MODE', 'shadow')
        from myah.utils.cron_outbox_worker import OutboxWorker

        worker = OutboxWorker()
        with patch('myah.utils.cron_outbox_metrics.emit_parity_event') as mock_event:
            await worker._emit_parity_check_if_due(force=True)
            mock_event.assert_called_once()
            args = mock_event.call_args.args
            assert isinstance(args[2], int), 'gap_count must be int'


class TestCronDeliveryModeEnv:
    """Tests for the get_cron_delivery_mode() function in myah.env.

    Per plan-review C-E: the mode must be a FUNCTION CALL, not a module-level
    constant, so test monkeypatching of MYAH_CRON_DELIVERY_MODE is picked
    up by callers without needing importlib.reload (which doesn't update
    names already bound in importing modules).
    """

    def test_default_is_legacy(self, monkeypatch):
        monkeypatch.delenv('MYAH_CRON_DELIVERY_MODE', raising=False)
        from myah.env import get_cron_delivery_mode

        assert get_cron_delivery_mode() == 'legacy'

    def test_shadow_value_accepted(self, monkeypatch):
        monkeypatch.setenv('MYAH_CRON_DELIVERY_MODE', 'shadow')
        from myah.env import get_cron_delivery_mode

        assert get_cron_delivery_mode() == 'shadow'

    def test_outbox_value_accepted(self, monkeypatch):
        monkeypatch.setenv('MYAH_CRON_DELIVERY_MODE', 'outbox')
        from myah.env import get_cron_delivery_mode

        assert get_cron_delivery_mode() == 'outbox'

    def test_invalid_value_falls_back_to_legacy(self, monkeypatch):
        """Unknown value → 'legacy' with WARNING log; never crash."""
        monkeypatch.setenv('MYAH_CRON_DELIVERY_MODE', 'garbage')
        from myah.env import get_cron_delivery_mode

        assert get_cron_delivery_mode() == 'legacy'

    def test_value_is_case_insensitive(self, monkeypatch):
        monkeypatch.setenv('MYAH_CRON_DELIVERY_MODE', 'OUTBOX')
        from myah.env import get_cron_delivery_mode

        assert get_cron_delivery_mode() == 'outbox'
