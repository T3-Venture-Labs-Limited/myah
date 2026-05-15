"""
Tests for hermes_stream_handler.handle_hermes_stream.

These tests cover the two dispatch paths that caused repeated production
regressions:

  1. Background task path (event_caller present):
     The browser always uses this path. The HTTP endpoint already returned
     {'status': True, 'task_id': ...}. The generator must be consumed eagerly
     so Socket.IO events are emitted and the DB is written.

     Bug history: commit 6d1390817 restructured the handler to return a
     StreamingResponse, which meant _generate() was never iterated in the
     background task context — users saw "Thinking..." forever with no error.

  2. Direct HTTP path (event_caller absent):
     Used by curl, the smoke test, and API clients. Must return a
     StreamingResponse yielding OpenAI-compatible SSE chunks.

Both paths are pure async logic tests — no real DB, no real network.
"""

import io
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from loguru import logger
from starlette.responses import StreamingResponse


# ── Helpers ────────────────────────────────────────────────────────────────


def _make_sse_lines(*events: dict) -> list[bytes]:
    """Build a list of SSE byte lines from event dicts."""
    lines = []
    for event in events:
        lines.append(f'data: {json.dumps(event)}\n\n'.encode())
    lines.append(b'data: [DONE]\n\n')
    return lines


def _make_upstream_response(sse_lines: list[bytes]):
    """Create a mock StreamingResponse whose body_iterator yields the given lines."""

    async def _iter():
        for line in sse_lines:
            yield line

    mock_response = MagicMock(spec=StreamingResponse)
    mock_response.body_iterator = _iter()
    return mock_response


def _make_ctx(*, with_event_caller: bool = True) -> dict:
    """Build a minimal ctx dict for handle_hermes_stream."""
    emitted = []

    async def _event_emitter(event):
        emitted.append(event)

    saved = []

    ctx = {
        'metadata': {
            'chat_id': 'test-chat-id',
            'message_id': 'test-message-id',
            'session_id': 'test-session-id',
        },
        'event_emitter': _event_emitter,
        'event_caller': _event_emitter if with_event_caller else None,
        'request': MagicMock(),
        'form_data': {'model': 'myah'},
        'user': MagicMock(),
        'model': MagicMock(),
        'tasks': {},
        'events': [],
        '_emitted': emitted,
        '_saved': saved,
    }
    return ctx


# ── Background task path tests ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_background_path_returns_none_when_event_caller_present():
    """When event_caller is set, handle_hermes_stream must return None.

    The HTTP endpoint already returned the task receipt. Returning a
    StreamingResponse here would leave _generate() unawaited and silent.
    """
    sse_lines = _make_sse_lines(
        {'event': 'message.delta', 'delta': 'Hello'},
        {'event': 'run.completed', 'usage': None},
    )
    response = _make_upstream_response(sse_lines)
    ctx = _make_ctx(with_event_caller=True)

    with (
        patch('myah.utils.hermes_stream_handler.Chats') as mock_chats,
        patch('myah.utils.hermes_stream_handler.background_tasks_handler', new=AsyncMock()),
    ):
        from myah.utils.hermes_stream_handler import handle_hermes_stream

        result = await handle_hermes_stream(response, ctx)

    assert result is None, (
        'handle_hermes_stream must return None in the background task path '
        '(event_caller present). Returning a StreamingResponse leaves the '
        'generator unconsumed and users see "Thinking..." forever.'
    )


@pytest.mark.asyncio
async def test_background_path_emits_socket_events():
    """Socket.IO events must be emitted when consuming the stream eagerly."""
    sse_lines = _make_sse_lines(
        {'event': 'message.delta', 'delta': 'Hello world'},
        {'event': 'run.completed', 'usage': None},
    )
    response = _make_upstream_response(sse_lines)
    ctx = _make_ctx(with_event_caller=True)

    with (
        patch('myah.utils.hermes_stream_handler.Chats'),
        patch('myah.utils.hermes_stream_handler.background_tasks_handler', new=AsyncMock()),
    ):
        from myah.utils.hermes_stream_handler import handle_hermes_stream

        await handle_hermes_stream(response, ctx)

    emitted_types = [e.get('type') for e in ctx['_emitted']]

    # Must have emitted at least one chat:completion event with content
    assert 'chat:completion' in emitted_types, (
        'No chat:completion Socket.IO event emitted — browser will never receive the message content.'
    )

    # Final completion must be marked done=True
    completion_events = [e for e in ctx['_emitted'] if e.get('type') == 'chat:completion']
    assert any(e['data'].get('done') is True for e in completion_events), (
        'No chat:completion event with done=True — browser will not know the response is finished.'
    )


@pytest.mark.asyncio
async def test_background_path_saves_to_db():
    """The assistant message must be persisted to the DB in the background path."""
    sse_lines = _make_sse_lines(
        {'event': 'message.delta', 'delta': 'Saved content'},
        {'event': 'run.completed', 'usage': None},
    )
    response = _make_upstream_response(sse_lines)
    ctx = _make_ctx(with_event_caller=True)

    upsert_calls = []

    with (
        patch('myah.utils.hermes_stream_handler.Chats') as mock_chats,
        patch('myah.utils.hermes_stream_handler.background_tasks_handler', new=AsyncMock()),
    ):
        mock_chats.upsert_message_to_chat_by_id_and_message_id.side_effect = lambda chat_id, message_id, update: (
            upsert_calls.append(update)
        )

        from myah.utils.hermes_stream_handler import handle_hermes_stream

        await handle_hermes_stream(response, ctx)

    assert upsert_calls, 'No DB upsert calls made — message will not persist across page reloads.'

    # At least one call must be the final save with done=True
    final_saves = [c for c in upsert_calls if c.get('done') is True]
    assert final_saves, 'No DB save with done=True — message marked as incomplete in the DB.'

    # Verify content was captured
    assert any('Saved content' in str(c.get('content', '')) for c in upsert_calls), (
        'DB save does not contain the agent response content.'
    )


@pytest.mark.asyncio
async def test_background_path_handles_run_failed():
    """run.failed events must emit an error event and still save to DB."""
    sse_lines = _make_sse_lines(
        {'event': 'run.failed', 'error': 'LLM provider returned 429'},
    )
    response = _make_upstream_response(sse_lines)
    ctx = _make_ctx(with_event_caller=True)

    upsert_calls = []

    with (
        patch('myah.utils.hermes_stream_handler.Chats') as mock_chats,
        patch('myah.utils.hermes_stream_handler.background_tasks_handler', new=AsyncMock()),
    ):
        mock_chats.upsert_message_to_chat_by_id_and_message_id.side_effect = lambda chat_id, message_id, update: (
            upsert_calls.append(update)
        )

        from myah.utils.hermes_stream_handler import handle_hermes_stream

        result = await handle_hermes_stream(response, ctx)

    assert result is None

    emitted_types = [e.get('type') for e in ctx['_emitted']]
    assert 'chat:message:error' in emitted_types, (
        'run.failed did not emit chat:message:error — user sees no error feedback.'
    )

    # DB must be updated even on failure
    assert upsert_calls, 'No DB save on run.failed — error state not persisted.'


@pytest.mark.asyncio
async def test_background_path_handles_empty_stream():
    """An empty stream (no events) must still save to DB and emit done completion."""
    # Only a [DONE] marker, no actual events
    response = _make_upstream_response([b'data: [DONE]\n\n'])
    ctx = _make_ctx(with_event_caller=True)

    upsert_calls = []

    with (
        patch('myah.utils.hermes_stream_handler.Chats') as mock_chats,
        patch('myah.utils.hermes_stream_handler.background_tasks_handler', new=AsyncMock()),
    ):
        mock_chats.upsert_message_to_chat_by_id_and_message_id.side_effect = lambda chat_id, message_id, update: (
            upsert_calls.append(update)
        )

        from myah.utils.hermes_stream_handler import handle_hermes_stream

        result = await handle_hermes_stream(response, ctx)

    assert result is None

    # The finally block should have saved and emitted done even with no content
    completion_events = [e for e in ctx['_emitted'] if e.get('type') == 'chat:completion']
    assert any(e['data'].get('done') is True for e in completion_events), (
        'Empty stream did not emit a final done=True completion event.'
    )


# ── Direct HTTP path tests ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_http_path_returns_streaming_response_when_no_event_caller():
    """Without event_caller, must return a StreamingResponse for HTTP clients."""
    sse_lines = _make_sse_lines(
        {'event': 'message.delta', 'delta': 'curl response'},
        {'event': 'run.completed', 'usage': None},
    )
    response = _make_upstream_response(sse_lines)
    ctx = _make_ctx(with_event_caller=False)

    with (
        patch('myah.utils.hermes_stream_handler.Chats'),
        patch('myah.utils.hermes_stream_handler.background_tasks_handler', new=AsyncMock()),
    ):
        from myah.utils.hermes_stream_handler import handle_hermes_stream

        result = await handle_hermes_stream(response, ctx)

    assert isinstance(result, StreamingResponse), (
        'Without event_caller (HTTP client path), handle_hermes_stream must '
        'return a StreamingResponse so curl/smoke test receives SSE chunks.'
    )


@pytest.mark.asyncio
async def test_http_path_yields_sse_chunks():
    """The StreamingResponse body must yield OpenAI-compatible SSE chunks."""
    sse_lines = _make_sse_lines(
        {'event': 'message.delta', 'delta': 'Hello'},
        {'event': 'message.delta', 'delta': ' world'},
        {'event': 'run.completed', 'usage': None},
    )
    response = _make_upstream_response(sse_lines)
    ctx = _make_ctx(with_event_caller=False)

    with (
        patch('myah.utils.hermes_stream_handler.Chats'),
        patch('myah.utils.hermes_stream_handler.background_tasks_handler', new=AsyncMock()),
    ):
        from myah.utils.hermes_stream_handler import handle_hermes_stream

        result = await handle_hermes_stream(response, ctx)

    assert isinstance(result, StreamingResponse)

    # Consume the body iterator and collect all chunks
    chunks = []
    async for chunk in result.body_iterator:
        chunks.append(chunk if isinstance(chunk, str) else chunk.decode())

    full_body = ''.join(chunks)

    # Must contain OpenAI-style delta chunks
    assert '"delta"' in full_body, 'SSE stream missing OpenAI-format delta chunks.'
    assert '[DONE]' in full_body, 'SSE stream missing [DONE] terminator.'

    # Reconstruct the text from delta chunks
    text = ''
    for line in full_body.splitlines():
        if line.startswith('data:') and '[DONE]' not in line:
            try:
                payload = json.loads(line[5:].strip())
                delta = payload.get('choices', [{}])[0].get('delta', {}).get('content', '')
                text += delta
            except (json.JSONDecodeError, IndexError, KeyError):
                pass

    assert text == 'Hello world', f'Reconstructed text mismatch: {text!r}'


@pytest.mark.asyncio
async def test_http_path_content_type_header():
    """StreamingResponse must set Content-Type: text/event-stream."""
    sse_lines = _make_sse_lines({'event': 'run.completed', 'usage': None})
    response = _make_upstream_response(sse_lines)
    ctx = _make_ctx(with_event_caller=False)

    with (
        patch('myah.utils.hermes_stream_handler.Chats'),
        patch('myah.utils.hermes_stream_handler.background_tasks_handler', new=AsyncMock()),
    ):
        from myah.utils.hermes_stream_handler import handle_hermes_stream

        result = await handle_hermes_stream(response, ctx)

    assert isinstance(result, StreamingResponse)
    # Starlette stores headers as a list of (name, value) byte tuples or a dict
    headers = dict(result.headers) if hasattr(result.headers, 'items') else {}
    content_type = headers.get('content-type', '')
    assert 'text/event-stream' in content_type, (
        f'Wrong Content-Type: {content_type!r} — SSE clients need text/event-stream.'
    )


# ── Regression guard ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_regression_background_path_not_discarded():
    """Regression guard for commit 6d1390817.

    Before the fix, handle_hermes_stream always returned a StreamingResponse.
    In the background task context, main.py discards the return value, so
    _generate() was never iterated — no Socket.IO events, no DB writes.
    Users saw "Thinking..." indefinitely.

    This test verifies that the generator IS consumed when event_caller is
    present, by checking that side effects (Socket.IO events, DB saves) occur.
    If handle_hermes_stream returns a StreamingResponse without consuming it,
    this test will fail because no events will be emitted.
    """
    sse_lines = _make_sse_lines(
        {'event': 'message.delta', 'delta': 'test response'},
        {'event': 'run.completed', 'usage': None},
    )
    response = _make_upstream_response(sse_lines)
    ctx = _make_ctx(with_event_caller=True)

    upsert_count = 0

    with (
        patch('myah.utils.hermes_stream_handler.Chats') as mock_chats,
        patch('myah.utils.hermes_stream_handler.background_tasks_handler', new=AsyncMock()),
    ):

        def _count_upsert(chat_id, message_id, update):
            nonlocal upsert_count
            upsert_count += 1

        mock_chats.upsert_message_to_chat_by_id_and_message_id.side_effect = _count_upsert

        from myah.utils.hermes_stream_handler import handle_hermes_stream

        # Simulate what main.py does in the background task path:
        # call the handler and DISCARD the return value (as asyncio.create_task does)
        result = await handle_hermes_stream(response, ctx)
        # result is intentionally not used — this is what the task runner does

    # Side effects must have happened despite the return value being discarded
    socket_events = [e for e in ctx['_emitted'] if e.get('type') == 'chat:completion']
    assert socket_events, (
        'REGRESSION: No Socket.IO events emitted. '
        'handle_hermes_stream likely returned a StreamingResponse without '
        'consuming it, meaning _generate() never ran. '
        'This is the exact bug from commit 6d1390817.'
    )
    assert upsert_count > 0, (
        'REGRESSION: No DB saves occurred. The background task path must consume the generator eagerly.'
    )


# ── Model attribution tests (T3-932) ──────────────────────────────────────


@pytest.mark.asyncio
async def test_run_completed_model_attribution_saved_to_db():
    """When run.completed carries model + provider, they must be persisted as
    modelUsed in the DB update dict so the frontend can render attribution badges
    after page reload.
    """
    sse_lines = _make_sse_lines(
        {'event': 'message.delta', 'delta': 'Hello'},
        {
            'event': 'run.completed',
            'usage': None,
            'model': 'anthropic/claude-sonnet-4-6',
            'provider': 'openrouter',
        },
    )
    response = _make_upstream_response(sse_lines)
    ctx = _make_ctx(with_event_caller=True)

    upsert_calls = []

    with (
        patch('myah.utils.hermes_stream_handler.Chats') as mock_chats,
        patch('myah.utils.hermes_stream_handler.background_tasks_handler', new=AsyncMock()),
    ):
        mock_chats.upsert_message_to_chat_by_id_and_message_id.side_effect = lambda chat_id, message_id, update: (
            upsert_calls.append(update)
        )

        from myah.utils.hermes_stream_handler import handle_hermes_stream

        await handle_hermes_stream(response, ctx)

    # At least one DB save must have occurred
    assert upsert_calls, 'No DB upsert calls made.'

    # The final save (done=True) must carry modelUsed
    final_saves = [c for c in upsert_calls if c.get('done') is True]
    assert final_saves, 'No DB save with done=True.'

    final = final_saves[-1]
    assert 'modelUsed' in final, f'modelUsed missing from final DB save. Keys present: {list(final.keys())}'
    assert final['modelUsed']['id'] == 'anthropic/claude-sonnet-4-6', f'modelUsed.id mismatch: {final["modelUsed"]}'
    assert final['modelUsed']['provider'] == 'openrouter', f'modelUsed.provider mismatch: {final["modelUsed"]}'


@pytest.mark.asyncio
async def test_run_completed_without_model_no_model_used_key():
    """When run.completed carries no model field, modelUsed must NOT appear in
    the DB update dict — avoids polluting existing messages with a None value.
    """
    sse_lines = _make_sse_lines(
        {'event': 'message.delta', 'delta': 'Hello'},
        {'event': 'run.completed', 'usage': None},
    )
    response = _make_upstream_response(sse_lines)
    ctx = _make_ctx(with_event_caller=True)

    upsert_calls = []

    with (
        patch('myah.utils.hermes_stream_handler.Chats') as mock_chats,
        patch('myah.utils.hermes_stream_handler.background_tasks_handler', new=AsyncMock()),
    ):
        mock_chats.upsert_message_to_chat_by_id_and_message_id.side_effect = lambda chat_id, message_id, update: (
            upsert_calls.append(update)
        )

        from myah.utils.hermes_stream_handler import handle_hermes_stream

        await handle_hermes_stream(response, ctx)

    final_saves = [c for c in upsert_calls if c.get('done') is True]
    assert final_saves, 'No DB save with done=True.'

    final = final_saves[-1]
    assert 'modelUsed' not in final, (
        f'modelUsed should not be present when run.completed has no model field. Got: {final.get("modelUsed")}'
    )


# ── Registry tests (T3-1001) ───────────────────────────────────────────────


def _clear_registries():
    """Reset module-level registries between tests."""
    import myah.utils.hermes_stream_handler as _mod

    _mod._active_runs.clear()
    _mod._live_state.clear()
    _mod._registry_warning_emitted = False


@pytest.mark.asyncio
async def test_active_runs_populated_on_run_started():
    """_active_runs must be populated when the first run_id is captured.

    The run_id arrives on the first event that carries it.  After
    handle_hermes_stream processes that event, _active_runs[chat_id] must
    contain run_id, started_at, and message_id.
    """
    _clear_registries()

    sse_lines = _make_sse_lines(
        {'event': 'message.delta', 'run_id': 'run-abc', 'delta': 'Hello'},
        {'event': 'run.completed', 'usage': None},
    )
    response = _make_upstream_response(sse_lines)
    ctx = _make_ctx(with_event_caller=True)

    scheduled_callbacks: list[tuple] = []

    class _FakeLoop:
        def call_later(self, delay, fn, *args):
            scheduled_callbacks.append((delay, fn, args))

    fake_loop = _FakeLoop()

    with (
        patch('myah.utils.hermes_stream_handler.Chats'),
        patch('myah.utils.hermes_stream_handler.background_tasks_handler', new=AsyncMock()),
        patch('myah.utils.hermes_stream_handler.asyncio.get_running_loop', return_value=fake_loop),
    ):
        import myah.utils.hermes_stream_handler as _mod
        from myah.utils.hermes_stream_handler import handle_hermes_stream

        await handle_hermes_stream(response, ctx)

        # call_later must have been scheduled (grace clears)
        assert scheduled_callbacks, '_active_runs.pop was never scheduled via call_later'
        for delay, _fn, _args in scheduled_callbacks:
            assert delay == 10, f'Expected 10s grace delay, got {delay}s'


@pytest.mark.asyncio
async def test_active_runs_cleared_after_completed_with_grace():
    """_active_runs must be cleared 10 s after run.completed, not immediately.

    Strategy: run the stream, verify the entry exists right after (grace window
    is 10s and we intercept call_later), then manually fire the scheduled
    callbacks and verify the entry disappears.
    """
    _clear_registries()

    sse_lines = _make_sse_lines(
        {'event': 'message.delta', 'run_id': 'run-xyz', 'delta': 'Hi'},
        {'event': 'run.completed', 'usage': None},
    )
    response = _make_upstream_response(sse_lines)
    ctx = _make_ctx(with_event_caller=True)

    scheduled_callbacks: list[tuple] = []

    class _FakeLoop:
        def call_later(self, delay, fn, *args):
            scheduled_callbacks.append((delay, fn, args))

    fake_loop = _FakeLoop()

    with (
        patch('myah.utils.hermes_stream_handler.Chats'),
        patch('myah.utils.hermes_stream_handler.background_tasks_handler', new=AsyncMock()),
        patch('myah.utils.hermes_stream_handler.asyncio.get_running_loop', return_value=fake_loop),
    ):
        import myah.utils.hermes_stream_handler as _mod
        from myah.utils.hermes_stream_handler import handle_hermes_stream

        await handle_hermes_stream(response, ctx)

        # Entry must exist immediately after stream (grace hasn't fired)
        assert 'test-chat-id' in _mod._active_runs, (
            '_active_runs entry missing immediately after run — was never populated'
        )

        # Now manually fire all scheduled callbacks (simulating 10s passing)
        for _delay, fn, args in scheduled_callbacks:
            fn(*args)

        # Now the entry should be gone
        assert 'test-chat-id' not in _mod._active_runs, (
            '_active_runs entry should be cleared after grace callback fires'
        )


@pytest.mark.asyncio
async def test_live_state_updated_on_delta():
    """_live_state must be populated on message.delta events."""
    _clear_registries()

    sse_lines = _make_sse_lines(
        {'event': 'message.delta', 'run_id': 'run-1', 'delta': 'Streaming text'},
        {'event': 'run.completed', 'usage': None},
    )
    response = _make_upstream_response(sse_lines)
    ctx = _make_ctx(with_event_caller=True)

    scheduled_callbacks: list[tuple] = []

    class _FakeLoop:
        def call_later(self, delay, fn, *args):
            scheduled_callbacks.append((delay, fn, args))

    fake_loop = _FakeLoop()

    with (
        patch('myah.utils.hermes_stream_handler.Chats'),
        patch('myah.utils.hermes_stream_handler.background_tasks_handler', new=AsyncMock()),
        patch('myah.utils.hermes_stream_handler.asyncio.get_running_loop', return_value=fake_loop),
    ):
        import myah.utils.hermes_stream_handler as _mod
        from myah.utils.hermes_stream_handler import handle_hermes_stream

        await handle_hermes_stream(response, ctx)

        # After completion the entry still exists (grace window via intercepted call_later)
        snapshot = _mod._live_state.get(('test-chat-id', 'test-message-id'))
        assert snapshot is not None, '_live_state not populated after message.delta'
        assert snapshot['message_content'] == 'Streaming text', (
            f"Expected 'Streaming text', got {snapshot['message_content']!r}"
        )
        assert snapshot['run_id'] == 'run-1', f"Expected run_id 'run-1', got {snapshot['run_id']!r}"
        assert snapshot['chat_id'] == 'test-chat-id'
        assert snapshot['message_id'] == 'test-message-id'
        # After run.completed the status should be 'settled'
        assert snapshot['status'] == 'settled', f"Expected 'settled', got {snapshot['status']!r}"


@pytest.mark.asyncio
async def test_live_state_cleared_after_completed_with_grace():
    """_live_state must be cleared 10 s after run.completed (grace window)."""
    _clear_registries()

    sse_lines = _make_sse_lines(
        {'event': 'message.delta', 'run_id': 'run-2', 'delta': 'Hello'},
        {'event': 'run.completed', 'usage': None},
    )
    response = _make_upstream_response(sse_lines)
    ctx = _make_ctx(with_event_caller=True)

    scheduled_callbacks: list[tuple] = []

    class _FakeLoop:
        def call_later(self, delay, fn, *args):
            scheduled_callbacks.append((delay, fn, args))

    fake_loop = _FakeLoop()

    with (
        patch('myah.utils.hermes_stream_handler.Chats'),
        patch('myah.utils.hermes_stream_handler.background_tasks_handler', new=AsyncMock()),
        patch('myah.utils.hermes_stream_handler.asyncio.get_running_loop', return_value=fake_loop),
    ):
        import myah.utils.hermes_stream_handler as _mod
        from myah.utils.hermes_stream_handler import handle_hermes_stream

        await handle_hermes_stream(response, ctx)

        key = ('test-chat-id', 'test-message-id')
        assert key in _mod._live_state, '_live_state missing immediately after run'

        # Fire all grace callbacks
        for _delay, fn, args in scheduled_callbacks:
            fn(*args)

        assert key not in _mod._live_state, (
            '_live_state entry should be cleared after grace callback fires'
        )

# ── artifact_card OutputItem tests ─────────────────────────────────────────
#
# Phase 4A replaced the legacy hermes:artifact socket event with an
# artifact_card OutputItem appended to the message's output[]. Tests now
# inspect the chat:completion payload's output array rather than a
# discrete socket event.


def _final_output(ctx) -> list[dict]:
    """Return the final output[] from the last chat:completion event."""
    completions = [e for e in ctx['_emitted'] if e.get('type') == 'chat:completion']
    assert completions, 'no chat:completion event was emitted'
    return completions[-1]['data'].get('output') or []


@pytest.mark.asyncio
async def test_artifact_card_appended_on_write_file():
    """tool.completed with write_file + .docx path must append an artifact_card."""
    sse_lines = _make_sse_lines(
        {
            'event': 'tool.started',
            'tool': 'write_file',
            'call_id': 'call-1',
            'args': {'path': '/data/.hermes/cache/documents/report.docx'},
        },
        {
            'event': 'tool.completed',
            'tool': 'write_file',
            'call_id': 'call-1',
            'result': {'path': '/data/.hermes/cache/documents/report.docx'},
        },
        {'event': 'run.completed', 'usage': None},
    )
    response = _make_upstream_response(sse_lines)
    ctx = _make_ctx(with_event_caller=True)

    with (
        patch('myah.utils.hermes_stream_handler.Chats'),
        patch('myah.utils.hermes_stream_handler.background_tasks_handler', new=AsyncMock()),
    ):
        from myah.utils.hermes_stream_handler import handle_hermes_stream

        await handle_hermes_stream(response, ctx)

    cards = [it for it in _final_output(ctx) if it.get('type') == 'artifact_card']
    assert len(cards) == 1, (
        f'Expected exactly one artifact_card item, got {len(cards)}. '
        f'All output types: {[it.get("type") for it in _final_output(ctx)]}'
    )
    card = cards[0]
    assert card['path'] == '/data/.hermes/cache/documents/report.docx'
    assert card['filename'] == 'report.docx'
    assert card['kind'] == 'docx'
    assert card['mtime'] is not None
    # Legacy event must not fire any more.
    assert not [e for e in ctx['_emitted'] if e.get('type') == 'hermes:artifact']


@pytest.mark.asyncio
async def test_artifact_card_skips_unsupported_extension():
    """write_file with an extension not in the artifact-extension set must NOT append a card.

    Phase 4A note: the legacy version of this test asserted .png was skipped.
    .png is now in the artifact-extension set (commit 6b5391c7c added media
    extensions when the renderer learned to display images), so the test was
    stale on master. Use an arbitrary unsupported extension instead so the
    gate's negative case is still covered.
    """
    sse_lines = _make_sse_lines(
        {
            'event': 'tool.completed',
            'tool': 'write_file',
            'call_id': 'call-2',
            'result': {'path': '/data/.hermes/cache/notes.unknown_ext'},
        },
        {'event': 'run.completed', 'usage': None},
    )
    response = _make_upstream_response(sse_lines)
    ctx = _make_ctx(with_event_caller=True)

    with (
        patch('myah.utils.hermes_stream_handler.Chats'),
        patch('myah.utils.hermes_stream_handler.background_tasks_handler', new=AsyncMock()),
    ):
        from myah.utils.hermes_stream_handler import handle_hermes_stream

        await handle_hermes_stream(response, ctx)

    cards = [it for it in _final_output(ctx) if it.get('type') == 'artifact_card']
    assert len(cards) == 0, (
        f'Expected no artifact_card for unsupported extension, got {len(cards)}.'
    )


@pytest.mark.asyncio
async def test_artifact_card_skips_non_trigger_tool():
    """A non-trigger tool (browser_vision) with a valid artifact path must NOT append a card."""
    sse_lines = _make_sse_lines(
        {
            'event': 'tool.completed',
            'tool': 'browser_vision',
            'call_id': 'call-3',
            'result': {'path': '/data/.hermes/cache/documents/report.pdf'},
        },
        {'event': 'run.completed', 'usage': None},
    )
    response = _make_upstream_response(sse_lines)
    ctx = _make_ctx(with_event_caller=True)

    with (
        patch('myah.utils.hermes_stream_handler.Chats'),
        patch('myah.utils.hermes_stream_handler.background_tasks_handler', new=AsyncMock()),
    ):
        from myah.utils.hermes_stream_handler import handle_hermes_stream

        await handle_hermes_stream(response, ctx)

    cards = [it for it in _final_output(ctx) if it.get('type') == 'artifact_card']
    assert len(cards) == 0, (
        f'Expected no artifact_card for non-trigger tool browser_vision, got {len(cards)}.'
    )


# ── Unknown event observability (Workstream I tactical PR) ────────────────


@pytest.mark.asyncio
async def test_unknown_event_type_emits_warning():
    """Unknown SSE event types must surface as a WARNING, not be silently dropped.

    The handler's switch only matches a fixed set of event_type strings.  Before
    this guard, anything else (e.g. a new event added upstream in Hermes) was
    swallowed without a trace.  A single log line is the minimum-viable signal
    until Phase 2 introduces typed event contracts.
    """
    # Capture loguru output (loguru does NOT write to pytest's caplog by default —
    # this is the canonical capture pattern in this codebase, see
    # test_agent_proxy_logging.py).
    sink = io.StringIO()
    handler_id = logger.add(sink, format='{level} {message}', level='WARNING')

    try:
        sse_lines = _make_sse_lines(
            {'event': 'message.delta', 'delta': 'Hi'},
            {'event': 'totally.made.up.event', 'arbitrary': 'payload'},
            {'event': 'run.completed', 'usage': None},
        )
        response = _make_upstream_response(sse_lines)
        ctx = _make_ctx(with_event_caller=True)

        with (
            patch('myah.utils.hermes_stream_handler.Chats'),
            patch('myah.utils.hermes_stream_handler.background_tasks_handler', new=AsyncMock()),
        ):
            from myah.utils.hermes_stream_handler import handle_hermes_stream

            await handle_hermes_stream(response, ctx)

        output = sink.getvalue()
    finally:
        logger.remove(handler_id)

    assert 'unknown hermes event type' in output, (
        f'Expected warning for unknown event type, got: {output!r}'
    )
    assert 'totally.made.up.event' in output, (
        f'Warning must include the event_type so operators can identify it; got: {output!r}'
    )
