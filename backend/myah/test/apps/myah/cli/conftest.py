"""Shared pytest fixtures for the `myah.lib.cli` + `myah.cli` test tree."""

from __future__ import annotations

import pytest


@pytest.fixture
def loguru_caplog(caplog: pytest.LogCaptureFixture) -> pytest.LogCaptureFixture:
    """Bridge loguru emissions into pytest's stdlib `caplog` handler.

    The codebase uses loguru exclusively; pytest's `caplog` only sees
    stdlib `logging` by default. This fixture adds a temporary loguru
    sink that forwards to `caplog.handler` so tests can assert on log
    records emitted via `loguru.logger.{info,warning,error,…}`.

    Use exactly like `caplog` itself:

        def test_thing(loguru_caplog):
            with loguru_caplog.at_level('WARNING'):
                do_thing_that_warns()
            assert any('expected' in r.message for r in loguru_caplog.records)
    """
    from loguru import logger

    handler_id = logger.add(caplog.handler, format='{message}', level=0)
    try:
        yield caplog
    finally:
        logger.remove(handler_id)
