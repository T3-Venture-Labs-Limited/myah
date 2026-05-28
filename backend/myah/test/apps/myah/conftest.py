"""Fixtures for Myah app/router/model tests.

Use this file for FastAPI clients, app dependency overrides, database helpers,
and agent/Hermes mocks used by tests under backend/myah/test/apps/myah/.
"""

from collections.abc import Callable, Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def dependency_overrides_cleanup() -> Iterator[list[FastAPI]]:
    """Track FastAPI apps whose dependency_overrides must be cleared."""

    apps: list[FastAPI] = []
    yield apps
    for app in apps:
        app.dependency_overrides.clear()


@pytest.fixture
def test_client_factory(
    dependency_overrides_cleanup: list[FastAPI],
) -> Iterator[Callable[[FastAPI], TestClient]]:
    """Create TestClient instances and clean app overrides after use."""

    clients: list[TestClient] = []

    def create(app: FastAPI) -> TestClient:
        dependency_overrides_cleanup.append(app)
        client = TestClient(app)
        clients.append(client)
        return client

    yield create

    for client in clients:
        client.close()
