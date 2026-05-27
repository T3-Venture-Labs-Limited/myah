"""Parallel tail across multiple log files — pure-Python, no `tail -F` subprocess.

The `myah dev logs` command needs to interleave lines from up to five log
files (backend, frontend, gateway, dashboard, plugin) in arrival order
with per-source color prefixes. This module provides the underlying
fan-in primitive.

Design:
- One `threading.Thread(daemon=True)` per source. Each worker opens the
  file, optionally emits a historical tail, then `seek(0, SEEK_END)` and
  polls `readline()` in a short-sleep loop until `stop_event.is_set()`.
- A single `queue.Queue(maxsize=10000)` is the sync point. Workers
  push `(LogSource, line)` tuples; the generator drains.
- Bounded queue prevents OOM on a fast-producing source whose consumer
  has paused (terminal scroll, etc.). Overflow → drop-oldest with a
  loguru.warning, never block the worker.
- Missing files are non-fatal: `tail_logs` logs a warning and skips
  that source. The four extra sources (gateway/dashboard/plugin) won't
  exist until Slice 3 wires their lifecycle commands.

Why pure-Python and not `subprocess.Popen(['tail', '-F', ...])`:
- Deterministic test surface (tmp_path + threading.Event).
- No process fork-bomb on 5 file inputs.
- Same behavior on Linux + macOS without shelling out.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Full, Queue
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:  # pragma: no cover
    pass


# "Many tongues, one ear. May the lines arrive in the order they were spoken." — log_multiplex.


# Bounded-queue cap. 10k lines * ~200B/line ≈ 2 MB — comfortably bounded.
_QUEUE_MAXSIZE = 10000

# Sleep between EOF polls in a worker. 100 ms = balance between latency and CPU.
_POLL_INTERVAL = 0.1

# Chunk size for backwards-read of historical tail (~64 KB).
_HISTORY_TAIL_CHUNK = 64 * 1024


@dataclass(frozen=True, slots=True)
class LogSource:
    """A named log file to be tailed.

    Attributes:
        name: Short identifier — used as the rendered prefix.
        path: Absolute path to the logfile.
        color: Rich color name (e.g. 'cyan', 'magenta', 'yellow').
    """

    name: str
    path: Path
    color: str


def _read_last_n_lines(path: Path, n: int) -> list[str]:
    """Return the last `n` lines of `path` without slurping the whole file.

    For files smaller than `_HISTORY_TAIL_CHUNK` we just read everything;
    otherwise we walk backwards in 64 KB chunks until we've collected
    enough newlines. Lines are returned WITHOUT trailing newlines.
    """
    if n <= 0:
        return []

    try:
        size = path.stat().st_size
    except OSError as exc:
        logger.warning(f'log_multiplex: cannot stat {path}: {exc}')
        return []

    if size == 0:
        return []

    try:
        with path.open('rb') as fh:
            if size <= _HISTORY_TAIL_CHUNK:
                data = fh.read()
            else:
                # Walk back in chunks until we have `n` newlines or hit BOF.
                chunks: list[bytes] = []
                newlines = 0
                pos = size
                while pos > 0 and newlines <= n:
                    read_size = min(_HISTORY_TAIL_CHUNK, pos)
                    pos -= read_size
                    fh.seek(pos)
                    chunk = fh.read(read_size)
                    chunks.append(chunk)
                    newlines += chunk.count(b'\n')
                data = b''.join(reversed(chunks))
    except OSError as exc:
        logger.warning(f'log_multiplex: cannot read history of {path}: {exc}')
        return []

    text = data.decode('utf-8', errors='replace')
    lines = text.splitlines()
    return lines[-n:]


def _worker(
    source: LogSource,
    lines: int,
    follow: bool,
    out_queue: Queue,
    stop_event: threading.Event,
) -> None:
    """Worker: emit history then optionally follow the file until stop_event."""
    # 1. Historical tail.
    if lines > 0:
        for line in _read_last_n_lines(source.path, lines):
            _put_or_drop(out_queue, (source, line))
            if stop_event.is_set():
                return

    if not follow:
        return

    # 2. Follow mode — open and seek to end.
    try:
        fh = source.path.open('r', encoding='utf-8', errors='replace')
    except OSError as exc:
        logger.warning(f'log_multiplex: cannot open {source.path} for follow: {exc}')
        return

    try:
        fh.seek(0, 2)  # SEEK_END
        while not stop_event.is_set():
            line = fh.readline()
            if not line:
                # EOF — sleep briefly, then try again.
                time.sleep(_POLL_INTERVAL)
                continue
            _put_or_drop(out_queue, (source, line.rstrip('\n')))
        # Final drain attempt on stop: pick up any line written between
        # the last sleep and the stop_event.set().
        while True:
            line = fh.readline()
            if not line:
                break
            _put_or_drop(out_queue, (source, line.rstrip('\n')))
    finally:
        fh.close()


def _put_or_drop(out_queue: Queue, item: tuple[LogSource, str]) -> None:
    """Push to queue with bounded back-pressure: drop oldest on overflow.

    Tries `put(timeout=1.0)`. If still full, drops the head (oldest)
    and retries once with put_nowait. Warns via loguru on drop.
    """
    try:
        out_queue.put(item, timeout=1.0)
        return
    except Full:
        pass

    # Drop oldest, then retry.
    try:
        out_queue.get_nowait()
        logger.warning('log_multiplex: queue full, dropped oldest line')
    except Empty:
        pass

    try:
        out_queue.put_nowait(item)
    except Full:
        # Extremely unlikely — drain race. Drop the new item silently
        # rather than block the worker.
        logger.warning('log_multiplex: queue still full after drop, discarding new line')


def tail_logs(
    sources: Sequence[LogSource],
    *,
    lines: int = 50,
    follow: bool = True,
    stop_event: threading.Event | None = None,
) -> Iterator[tuple[LogSource, str]]:
    """Tail multiple files in parallel; yield (source, line) tuples in arrival order.

    Args:
        sources: LogSources to tail. Missing files are skipped with a warning.
        lines: Number of historical lines to emit per file before following
            (0 = no history).
        follow: If True, keep watching for new lines until `stop_event`. If
            False, emit only historical tails and return.
        stop_event: Optional `threading.Event`; setting it causes all workers
            to drain queued lines and exit cleanly. If not provided, one is
            created internally — the generator will run forever in follow
            mode unless the caller stops via the consumer side.

    Yields:
        (source, line) tuples in queue arrival order. `line` has no trailing
        newline.
    """
    if stop_event is None:
        stop_event = threading.Event()

    # Filter out missing files non-fatally.
    present: list[LogSource] = []
    for src in sources:
        if not src.path.is_file():
            logger.warning(f'log_multiplex: source file missing, skipping: {src.path}')
            continue
        present.append(src)

    if not present:
        return

    out_queue: Queue = Queue(maxsize=_QUEUE_MAXSIZE)

    workers: list[threading.Thread] = []
    for src in present:
        t = threading.Thread(
            target=_worker,
            args=(src, lines, follow, out_queue, stop_event),
            name=f'log_multiplex.{src.name}',
            daemon=True,
        )
        t.start()
        workers.append(t)

    # Drain loop. We stop when either:
    #  - all workers have exited AND queue is empty (no-follow mode), or
    #  - stop_event is set AND queue has been drained.
    try:
        while True:
            try:
                item = out_queue.get(timeout=_POLL_INTERVAL)
            except Empty:
                # No item — check if workers are all done.
                if all(not w.is_alive() for w in workers) and out_queue.empty():
                    return
                if stop_event.is_set() and out_queue.empty():
                    return
                continue
            yield item
    finally:
        # Ensure workers wind down on consumer exit (StopIteration, exception, etc.).
        stop_event.set()


__all__ = ['LogSource', 'tail_logs']
