"""Tests for the hosted-only admin GET endpoint for cron_deliveries inspection.

ADR-8: Phase 1 hosted overlay ships GET only. No mutation surface.

Per plan-review S-3: this test file lives under platform-oss/ (with the
rest of the backend tests) but it tests a router defined in platform-hosted/.
The test skips cleanly when MYAH_DEPLOYMENT_MODE=oss or when the hosted router
module can't be imported.
"""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio

from myah.utils.hermes_web import is_oss_mode

pytestmark = pytest.mark.skipif(
    is_oss_mode(),
    reason='admin_cron_deliveries is a hosted-only router; skipped in OSS mode',
)


_HOSTED_BACKEND = Path(__file__).resolve().parents[4] / 'platform-hosted' / 'backend'
_HOSTED_MYAH = _HOSTED_BACKEND / 'myah'
_HOSTED_ROUTERS = _HOSTED_MYAH / 'routers'
_HOSTED_MODELS = _HOSTED_MYAH / 'models'
_HOSTED_SERVICES = _HOSTED_MYAH / 'services'
_HOSTED_UTILS = _HOSTED_MYAH / 'utils'


def _import_admin_router():
    """Helper: import the hosted router; skip the test if absent (OSS install)."""
    from myah import models as models_pkg
    from myah import routers as routers_pkg
    from myah import utils as utils_pkg

    if not _HOSTED_ROUTERS.exists():
        pytest.skip('admin_cron_deliveries router not present in this build')
    if str(_HOSTED_ROUTERS) not in routers_pkg.__path__:
        routers_pkg.__path__.append(str(_HOSTED_ROUTERS))
    if _HOSTED_MODELS.exists() and str(_HOSTED_MODELS) not in models_pkg.__path__:
        models_pkg.__path__.append(str(_HOSTED_MODELS))
    if _HOSTED_UTILS.exists() and str(_HOSTED_UTILS) not in utils_pkg.__path__:
        utils_pkg.__path__.append(str(_HOSTED_UTILS))
    if _HOSTED_SERVICES.exists():
        try:
            from myah import services as services_pkg
        except ImportError:
            # platform-oss has no services namespace; hosted image COPY overlay
            # creates it. A direct sys.path entry emulates that for local tests.
            if str(_HOSTED_BACKEND) not in sys.path:
                sys.path.insert(0, str(_HOSTED_BACKEND))
        else:
            if str(_HOSTED_SERVICES) not in services_pkg.__path__:
                services_pkg.__path__.append(str(_HOSTED_SERVICES))
    from myah.routers import admin_cron_deliveries as mod  # type: ignore

    return mod


@pytest_asyncio.fixture
async def async_client(db_session, monkeypatch) -> AsyncIterator:
    """AsyncClient bound to the hosted-mode FastAPI app.

    platform-hosted is a Docker COPY overlay, not an importable namespace beside
    platform-oss during local tests. Add only the hosted routers directory to the
    myah.routers package path so the deferred import in main.py matches the image.
    """
    monkeypatch.setenv('MYAH_DEPLOYMENT_MODE', 'hosted')
    _import_admin_router()
    sys.modules.pop('myah.main', None)

    from httpx import ASGITransport, AsyncClient

    from myah.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        yield client


class TestAdminCronDeliveriesEndpoint:
    """GET /api/v1/admin/cron-deliveries — admin-only inspection endpoint."""

    @pytest.mark.asyncio
    async def test_returns_paginated_rows(self, async_client, admin_bearer, seed_user_and_chat):
        from myah.models.cron_deliveries import CronDeliveries

        user_id, chat_id, _ = seed_user_and_chat
        for i in range(3):
            CronDeliveries.insert_idempotent(
                {
                    'user_id': user_id,
                    'job_id': f'job-{i}',
                    'chat_id': chat_id,
                    'ran_at_iso': f'2026-05-26T11:4{i}:00+00:00',
                    'content': f'c{i}',
                    'metadata_json': '{}',
                }
            )

        resp = await async_client.get(
            '/api/v1/admin/cron-deliveries?limit=10',
            headers={'Authorization': f'Bearer {admin_bearer}'},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert 'rows' in body
        assert len(body['rows']) == 3
        assert body['rows'][0]['delivery_status'] == 'pending'

    @pytest.mark.asyncio
    async def test_filters_by_user_id(self, async_client, admin_bearer, db_session):
        from myah.models.cron_deliveries import CronDeliveries

        for user_id in ('u1', 'u2'):
            CronDeliveries.insert_idempotent(
                {
                    'user_id': user_id,
                    'job_id': f'j-{user_id}',
                    'chat_id': 'c1',
                    'ran_at_iso': f'r-{user_id}',
                    'content': 'x',
                    'metadata_json': '{}',
                }
            )

        resp = await async_client.get(
            '/api/v1/admin/cron-deliveries?user_id=u1',
            headers={'Authorization': f'Bearer {admin_bearer}'},
        )
        assert resp.status_code == 200
        rows = resp.json()['rows']
        assert len(rows) == 1
        assert rows[0]['user_id'] == 'u1'

    @pytest.mark.asyncio
    async def test_filters_by_delivery_status(self, async_client, admin_bearer, db_session):
        from myah.models.cron_deliveries import CronDeliveries

        ok_id = CronDeliveries.insert_idempotent(
            {
                'user_id': 'u',
                'job_id': 'jok',
                'chat_id': 'c',
                'ran_at_iso': 'r1',
                'content': 'ok',
                'metadata_json': '{}',
            }
        )
        CronDeliveries.mark_delivered(ok_id)
        CronDeliveries.insert_idempotent(
            {
                'user_id': 'u',
                'job_id': 'jpend',
                'chat_id': 'c',
                'ran_at_iso': 'r2',
                'content': 'p',
                'metadata_json': '{}',
            }
        )

        resp = await async_client.get(
            '/api/v1/admin/cron-deliveries?delivery_status=delivered',
            headers={'Authorization': f'Bearer {admin_bearer}'},
        )
        assert resp.status_code == 200
        rows = resp.json()['rows']
        assert len(rows) == 1
        assert rows[0]['delivery_status'] == 'delivered'

    @pytest.mark.asyncio
    async def test_non_admin_returns_403(self, async_client, db_session):
        resp = await async_client.get(
            '/api/v1/admin/cron-deliveries',
            headers={'Authorization': 'Bearer user-bearer-not-admin'},
        )
        assert resp.status_code in (401, 403)  # depends on existing admin dep behaviour
