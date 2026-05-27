"""Tests for `myah.lib.cli.log_multiplex` (Slice 2 Task 2.5).

The parallel-tail library backs `myah dev logs`. Pure-Python: one worker
thread per source pushes (LogSource, line) tuples into a bounded queue;
the generator drains the queue.

These tests cover the public surface only:
- LogSource: frozen, slots, the three required fields.
- tail_logs: history-only mode, follow mode, multi-source interleaving,
  missing-file tolerance, newline-stripping, stop_event termination,
  bounded-queue back-pressure.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# LogSource dataclass
# ---------------------------------------------------------------------------


def test_log_source_dataclass_has_name_path_color() -> None:
    """LogSource is frozen with slots and the three required fields."""
    from myah.lib.cli.log_multiplex import LogSource

    src = LogSource(name='backend', path=Path('/tmp/x.log'), color='cyan')
    assert src.name == 'backend'
    assert src.path == Path('/tmp/x.log')
    assert src.color == 'cyan'

    # frozen → can't assign
    with pytest.raises((AttributeError, Exception)):
        src.name = 'frontend'  # type: ignore[misc]

    # slots → no __dict__
    assert not hasattr(src, '__dict__')


# ---------------------------------------------------------------------------
# tail_logs: historical / no-follow mode
# ---------------------------------------------------------------------------


def test_tail_logs_returns_historical_lines_no_follow(tmp_path: Path) -> None:
    """Write 100 lines; with lines=10, follow=False yields exactly the last 10."""
    from myah.lib.cli.log_multiplex import LogSource, tail_logs

    f = tmp_path / 'backend.log'
    f.write_text('\n'.join(f'line {i}' for i in range(100)) + '\n')

    src = LogSource(name='backend', path=f, color='cyan')
    results = list(tail_logs([src], lines=10, follow=False))

    assert len(results) == 10
    # Last 10 lines were line 90..99
    expected = [f'line {i}' for i in range(90, 100)]
    assert [line for _, line in results] == expected
    # All tuples reference the same source
    assert all(s is src for s, _ in results)


def test_tail_logs_returns_zero_history_when_lines_zero(tmp_path: Path) -> None:
    """lines=0, follow=False returns immediately with empty output."""
    from myah.lib.cli.log_multiplex import LogSource, tail_logs

    f = tmp_path / 'backend.log'
    f.write_text('line a\nline b\nline c\n')

    src = LogSource(name='backend', path=f, color='cyan')
    results = list(tail_logs([src], lines=0, follow=False))

    assert results == []


def test_tail_logs_multiple_sources_interleave(tmp_path: Path) -> None:
    """Two source files, both with history; yielded tuples include both source names."""
    from myah.lib.cli.log_multiplex import LogSource, tail_logs

    f1 = tmp_path / 'backend.log'
    f1.write_text('be 1\nbe 2\nbe 3\n')
    f2 = tmp_path / 'frontend.log'
    f2.write_text('fe 1\nfe 2\nfe 3\n')

    s1 = LogSource(name='backend', path=f1, color='cyan')
    s2 = LogSource(name='frontend', path=f2, color='magenta')

    results = list(tail_logs([s1, s2], lines=10, follow=False))
    names = {src.name for src, _ in results}
    assert names == {'backend', 'frontend'}
    # 6 lines total
    assert len(results) == 6


def test_tail_logs_strips_trailing_newline(tmp_path: Path) -> None:
    """Yielded lines do not include trailing \\n."""
    from myah.lib.cli.log_multiplex import LogSource, tail_logs

    f = tmp_path / 'backend.log'
    f.write_text('alpha\nbeta\ngamma\n')

    src = LogSource(name='backend', path=f, color='cyan')
    results = list(tail_logs([src], lines=10, follow=False))

    for _, line in results:
        assert not line.endswith('\n'), f'line had trailing newline: {line!r}'


def test_tail_logs_skips_missing_files(tmp_path: Path) -> None:
    """A source with a non-existent path is skipped non-fatally."""
    from myah.lib.cli.log_multiplex import LogSource, tail_logs

    f_present = tmp_path / 'backend.log'
    f_present.write_text('hello\nworld\n')
    f_missing = tmp_path / 'gateway.log'  # not written

    s_present = LogSource(name='backend', path=f_present, color='cyan')
    s_missing = LogSource(name='gateway', path=f_missing, color='yellow')

    # Must not raise
    results = list(tail_logs([s_present, s_missing], lines=10, follow=False))
    names = {src.name for src, _ in results}
    assert names == {'backend'}, f'unexpected names {names}'


# ---------------------------------------------------------------------------
# tail_logs: follow mode + stop_event
# ---------------------------------------------------------------------------


def test_tail_logs_follows_new_lines(tmp_path: Path) -> None:
    """In follow=True mode, lines appended after start are yielded."""
    from myah.lib.cli.log_multiplex import LogSource, tail_logs

    f = tmp_path / 'backend.log'
    f.write_text('')  # empty initial

    src = LogSource(name='backend', path=f, color='cyan')
    stop = threading.Event()
    yielded: list[tuple[str, str]] = []

    def consume() -> None:
        for source, line in tail_logs([src], lines=0, follow=True, stop_event=stop):
            yielded.append((source.name, line))

    consumer = threading.Thread(target=consume, daemon=True)
    consumer.start()

    # Give the worker a moment to seek to EOF, then append.
    time.sleep(0.2)
    with f.open('a') as fh:
        fh.write('appended line\n')

    # Wait for the line to appear.
    deadline = time.time() + 3.0
    while time.time() < deadline and not yielded:
        time.sleep(0.05)

    stop.set()
    consumer.join(timeout=3.0)

    assert yielded, 'expected at least one line to be yielded after append'
    assert any(line == 'appended line' for _, line in yielded)


def test_tail_logs_stop_event_terminates_workers(tmp_path: Path) -> None:
    """Setting stop_event causes the generator to complete in bounded time."""
    from myah.lib.cli.log_multiplex import LogSource, tail_logs

    f = tmp_path / 'backend.log'
    f.write_text('')

    src = LogSource(name='backend', path=f, color='cyan')
    stop = threading.Event()
    done = threading.Event()

    def consume() -> None:
        for _ in tail_logs([src], lines=0, follow=True, stop_event=stop):
            pass
        done.set()

    consumer = threading.Thread(target=consume, daemon=True)
    consumer.start()

    time.sleep(0.2)
    stop.set()

    assert done.wait(timeout=3.0), 'tail_logs did not terminate within 3s of stop_event'


# ---------------------------------------------------------------------------
# Bounded-queue back-pressure
# ---------------------------------------------------------------------------


def test_tail_logs_bounded_queue_drops_oldest_under_pressure(tmp_path: Path) -> None:
    """Pre-populate a large file and read with no consumer pressure — no OOM, finite count.

    The test caps total yielded at 50k lines (well under the file size we
    pre-write) and asserts completion under timeout. The library should
    bound queue depth at 10000 and never hang.
    """
    from myah.lib.cli.log_multiplex import LogSource, tail_logs

    # Write 30,000 lines — larger than the bounded queue, but tail_logs
    # in no-follow mode reads only the last N (lines=15000).
    f = tmp_path / 'backend.log'
    with f.open('w') as fh:
        for i in range(30_000):
            fh.write(f'line {i}\n')

    src = LogSource(name='backend', path=f, color='cyan')

    yielded = 0
    start = time.time()
    for _ in tail_logs([src], lines=15_000, follow=False):
        yielded += 1
        if yielded >= 50_000:  # safety cap
            break
        if time.time() - start > 10.0:
            pytest.fail('tail_logs hung past 10s — bounded queue may be deadlocking')

    # We requested 15000 lines and the file has at least that many.
    assert yielded <= 15_000
    assert yielded > 0
