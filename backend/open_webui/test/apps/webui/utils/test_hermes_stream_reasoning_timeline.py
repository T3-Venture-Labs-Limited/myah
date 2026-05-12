"""
Tests for the reasoning timeline fix in hermes_stream_handler.

Regression guard for the bug where a reasoning item's status was left as
'in_progress' when visible message text arrived, causing subsequent
reasoning.delta events to append to the same item rather than creating a
new one.

Root cause: When message.delta arrives with visible text, the handler must
set both `duration` AND `status='completed'` on any in_progress reasoning
item. Previously only `duration` was set, leaving status as 'in_progress'.
This caused the next reasoning.delta to find and reuse the existing item
(via the `next(... status == 'in_progress' ...)` search), merging two
distinct reasoning phases into one.

Expected behaviour after the fix:
  reasoning.delta  → item #1 created (status='in_progress')
  message.delta    → item #1 closed (status='completed', duration>0)
                      message item inserted
  reasoning.delta  → item #2 created (status='in_progress')

Output order: [reasoning#1(completed), message, reasoning#2(in_progress)]
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from starlette.responses import StreamingResponse


# ── Helpers (mirror test_hermes_stream_handler.py) ─────────────────────────


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


def _make_ctx() -> dict:
    """Build a minimal ctx dict for handle_hermes_stream (background task path)."""
    emitted = []

    async def _event_emitter(event):
        emitted.append(event)

    ctx = {
        'metadata': {
            'chat_id': 'test-chat-id',
            'message_id': 'test-message-id',
            'session_id': 'test-session-id',
        },
        'event_emitter': _event_emitter,
        'event_caller': _event_emitter,  # background path — eagerly consumed
        'request': MagicMock(),
        'form_data': {'model': 'myah'},
        'user': MagicMock(),
        'model': MagicMock(),
        'tasks': {},
        'events': [],
        '_emitted': emitted,
    }
    return ctx


def _extract_output(upsert_calls: list[dict]) -> list[dict]:
    """Pull the output list from the last DB upsert call that carries one.

    _save_to_db stores the raw output list in update['output'] (line 159
    of hermes_stream_handler.py). Use the last call that has it so we see
    the final state after all events have been processed.
    """
    for call in reversed(upsert_calls):
        output = call.get('output')
        if isinstance(output, list):
            return output
    return []


# ── Reasoning timeline tests ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reasoning_item_closed_when_message_delta_arrives():
    """A reasoning item must be set to status='completed' when visible message text arrives.

    Sequence:
      1. reasoning.delta  → creates reasoning item #1 (in_progress)
      2. message.delta    → should CLOSE item #1 (completed + duration set)
                            and create a message item

    Before the fix, item #1 remained in_progress after step 2.
    """
    sse_lines = _make_sse_lines(
        {'event': 'reasoning.delta', 'text': 'Thinking about the problem...'},
        {'event': 'message.delta', 'delta': 'Here is my answer.'},
        {'event': 'run.completed', 'usage': None},
    )
    response = _make_upstream_response(sse_lines)
    ctx = _make_ctx()
    upsert_calls = []

    with (
        patch('open_webui.utils.hermes_stream_handler.Chats') as mock_chats,
        patch('open_webui.utils.hermes_stream_handler.background_tasks_handler', new=AsyncMock()),
    ):
        mock_chats.upsert_message_to_chat_by_id_and_message_id.side_effect = (
            lambda chat_id, message_id, update: upsert_calls.append(update)
        )

        from open_webui.utils.hermes_stream_handler import handle_hermes_stream

        await handle_hermes_stream(response, ctx)

    assert upsert_calls, 'No DB upsert calls made.'

    output = _extract_output(upsert_calls)
    reasoning_items = [item for item in output if item.get('type') == 'reasoning']

    assert reasoning_items, 'No reasoning item found in output.'

    first_reasoning = reasoning_items[0]
    assert first_reasoning.get('status') == 'completed', (
        f"Reasoning item status should be 'completed' after message.delta arrived, "
        f"got: {first_reasoning.get('status')!r}. "
        'This is the root cause of the reasoning timeline merging bug.'
    )
    assert first_reasoning.get('duration', -1) >= 0, (
        f"Reasoning item duration should be >= 0, got: {first_reasoning.get('duration')!r}."
    )


@pytest.mark.asyncio
async def test_two_reasoning_phases_produce_two_separate_items():
    """Two reasoning phases separated by a message.delta must produce two distinct items.

    Sequence:
      1. reasoning.delta  → creates reasoning item #1 (in_progress)
      2. message.delta    → closes item #1 (completed), inserts message item
      3. reasoning.delta  → must create reasoning item #2 (in_progress)
                            NOT append to item #1

    Before the fix, step 3 would find item #1 still in_progress and append to
    it, merging both reasoning phases into a single item.
    """
    sse_lines = _make_sse_lines(
        {'event': 'reasoning.delta', 'text': 'First reasoning phase.'},
        {'event': 'message.delta', 'delta': 'Intermediate answer.'},
        {'event': 'reasoning.delta', 'text': 'Second reasoning phase.'},
        {'event': 'run.completed', 'usage': None},
    )
    response = _make_upstream_response(sse_lines)
    ctx = _make_ctx()
    upsert_calls = []

    with (
        patch('open_webui.utils.hermes_stream_handler.Chats') as mock_chats,
        patch('open_webui.utils.hermes_stream_handler.background_tasks_handler', new=AsyncMock()),
    ):
        mock_chats.upsert_message_to_chat_by_id_and_message_id.side_effect = (
            lambda chat_id, message_id, update: upsert_calls.append(update)
        )

        from open_webui.utils.hermes_stream_handler import handle_hermes_stream

        await handle_hermes_stream(response, ctx)

    assert upsert_calls, 'No DB upsert calls made.'

    output = _extract_output(upsert_calls)
    reasoning_items = [item for item in output if item.get('type') == 'reasoning']
    message_items = [item for item in output if item.get('type') == 'message']

    assert len(reasoning_items) == 2, (
        f'Expected 2 reasoning items (one per phase), got {len(reasoning_items)}. '
        'If only 1 item exists, the fix did not close item #1 before the second '
        'reasoning.delta arrived, causing both phases to merge into a single item.'
    )

    first_reasoning = reasoning_items[0]
    assert first_reasoning.get('status') == 'completed', (
        f"First reasoning item must be 'completed', got: {first_reasoning.get('status')!r}."
    )
    assert first_reasoning.get('duration', -1) >= 0, (
        f"First reasoning item duration must be >= 0, got: {first_reasoning.get('duration')!r}."
    )

    second_reasoning = reasoning_items[1]
    # run.completed closes all remaining in_progress items (handler lines 497-505),
    # so the second reasoning item is 'completed' at the end of the run — that is correct.
    assert second_reasoning.get('status') == 'completed', (
        f"Second reasoning item should be 'completed' (closed by run.completed), "
        f"got: {second_reasoning.get('status')!r}."
    )

    assert message_items, 'No message item found in output.'

    # Verify ordering: reasoning#1, message, reasoning#2
    output_types = [item.get('type') for item in output]
    reasoning_indices = [i for i, t in enumerate(output_types) if t == 'reasoning']
    message_indices = [i for i, t in enumerate(output_types) if t == 'message']

    assert reasoning_indices[0] < message_indices[0] < reasoning_indices[1], (
        f'Expected output order [reasoning, message, reasoning], '
        f'got indices: reasoning={reasoning_indices}, message={message_indices}. '
        f'Full output types: {output_types}'
    )


# ── <think>-tag echo-drop tests ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_trailing_think_block_that_echoes_message_is_dropped():
    """A <think> block whose content duplicates the visible message must NOT create a second reasoning item.

    Some models (kimi-k2.5) emit their final response and then echo it back
    inside a trailing <think>...</think> block. That produces the user-visible
    bug where the message text appears twice: once in the message body, and
    again inside a 'Thought for less than a second' chain-of-thought row.

    Sequence (via XML-scratchpad interception in message.delta):
      <think>real thinking</think>visible answer<think>visible answer</think>

    Expected output: [reasoning(real thinking), message(visible answer)]
    NOT:             [reasoning(real thinking), message(visible answer), reasoning(visible answer)]
    """
    echoed = 'Hi! I am here to help you with your business needs.'
    stream = (
        f'<think>The user said hi. Respond warmly.</think>{echoed}<think>{echoed}</think>'
    )
    sse_lines = _make_sse_lines(
        {'event': 'message.delta', 'delta': stream},
        {'event': 'run.completed', 'usage': None},
    )
    response = _make_upstream_response(sse_lines)
    ctx = _make_ctx()
    upsert_calls = []

    with (
        patch('open_webui.utils.hermes_stream_handler.Chats') as mock_chats,
        patch('open_webui.utils.hermes_stream_handler.background_tasks_handler', new=AsyncMock()),
    ):
        mock_chats.upsert_message_to_chat_by_id_and_message_id.side_effect = (
            lambda chat_id, message_id, update: upsert_calls.append(update)
        )

        from open_webui.utils.hermes_stream_handler import handle_hermes_stream

        await handle_hermes_stream(response, ctx)

    assert upsert_calls, 'No DB upsert calls made.'
    output = _extract_output(upsert_calls)
    reasoning_items = [item for item in output if item.get('type') == 'reasoning']
    message_items = [item for item in output if item.get('type') == 'message']

    assert len(reasoning_items) == 1, (
        f'Expected exactly 1 reasoning item (the trailing echo must be dropped), '
        f'got {len(reasoning_items)}. reasoning summaries: '
        f'{[r.get("summary") for r in reasoning_items]}'
    )

    assert len(message_items) == 1, f'Expected 1 message item, got {len(message_items)}.'

    msg_text = ''.join(
        (p.get('text') or '')
        for p in message_items[0].get('content', [])
        if p.get('type') == 'output_text'
    )
    assert msg_text == echoed, (
        f'Message body should contain only the visible answer, got: {msg_text!r}'
    )

    # The real reasoning should still be intact.
    first_summary = ''.join(
        p.get('text', '') for p in reasoning_items[0].get('summary', [])
    )
    assert 'real thinking' not in first_summary.lower(), (
        'Echo guard should drop ONLY duplicates, not legitimate reasoning.'
    )
    assert 'user said hi' in first_summary.lower(), (
        f'Legitimate reasoning must be preserved, got summary: {first_summary!r}'
    )


@pytest.mark.asyncio
async def test_reasoning_closes_on_tool_started_so_post_tool_reasoning_is_a_new_item():
    """tool.started must set status='completed' on any in_progress reasoning.

    Without this, a reasoning.delta arriving AFTER a tool.started finds the
    still-in_progress reasoning item from before the tool and appends to it,
    merging pre-tool and post-tool reasoning into a single block rendered
    above the tool call. Chain-of-thought rendering then loses chronological
    order: user sees [reason1 + reason2] → [tool] instead of the correct
    [reason1] → [tool] → [reason2].

    Sequence:
      1. reasoning.delta  → creates reasoning #1 (in_progress)
      2. tool.started     → must CLOSE reasoning #1 and add function_call
      3. reasoning.delta  → must create reasoning #2 (a NEW item)

    Output order must be: [reasoning#1, function_call, reasoning#2].
    """
    sse_lines = _make_sse_lines(
        {'event': 'reasoning.delta', 'text': 'Before tool: planning query'},
        {'event': 'tool.started', 'tool': 'web_research', 'call_id': 'c1', 'args': {'q': 'x'}},
        {'event': 'tool.completed', 'tool': 'web_research', 'call_id': 'c1', 'result': 'ok'},
        {'event': 'reasoning.delta', 'text': 'After tool: analyzing results'},
        {'event': 'message.delta', 'delta': 'Answer.'},
        {'event': 'run.completed', 'usage': None},
    )
    response = _make_upstream_response(sse_lines)
    ctx = _make_ctx()
    upsert_calls = []

    with (
        patch('open_webui.utils.hermes_stream_handler.Chats') as mock_chats,
        patch('open_webui.utils.hermes_stream_handler.background_tasks_handler', new=AsyncMock()),
    ):
        mock_chats.upsert_message_to_chat_by_id_and_message_id.side_effect = (
            lambda chat_id, message_id, update: upsert_calls.append(update)
        )

        from open_webui.utils.hermes_stream_handler import handle_hermes_stream

        await handle_hermes_stream(response, ctx)

    output = _extract_output(upsert_calls)
    reasoning_items = [it for it in output if it.get('type') == 'reasoning']
    function_calls = [it for it in output if it.get('type') == 'function_call']

    assert len(reasoning_items) == 2, (
        f'Expected 2 reasoning items (one before, one after the tool). '
        f'Got {len(reasoning_items)}. If 1, tool.started did not close the '
        f'first reasoning item, so both reasoning phases merged.'
    )
    assert len(function_calls) == 1, f'Expected 1 function_call, got {len(function_calls)}.'

    # Order must be [reasoning, function_call, reasoning, (function_call_output), message]
    types_in_order = [it.get('type') for it in output]
    reasoning_indices = [i for i, t in enumerate(types_in_order) if t == 'reasoning']
    fc_index = types_in_order.index('function_call')

    assert reasoning_indices[0] < fc_index < reasoning_indices[1], (
        f'Chronological order wrong. Got types: {types_in_order}. '
        f'Expected reasoning #1 before tool and reasoning #2 after.'
    )

    # Content must be split between the two items (no merging).
    first_text = ''.join(p.get('text', '') for p in reasoning_items[0].get('summary', []))
    second_text = ''.join(p.get('text', '') for p in reasoning_items[1].get('summary', []))
    assert 'Before tool' in first_text and 'After tool' not in first_text
    assert 'After tool' in second_text and 'Before tool' not in second_text


@pytest.mark.asyncio
async def test_trailing_reasoning_available_that_duplicates_prior_reasoning_is_dropped():
    """reasoning.available after streaming should not create a phantom block.

    For models that stream reasoning via reasoning.delta (or <think> tags),
    Hermes often ALSO emits a post-hoc reasoning.available with the same
    content after response completion. Without dedup, this lands as a new
    reasoning item below the visible message (the "Thought for 1 seconds"
    phantom the user reported).
    """
    earlier = 'The user asked about X. I will search the docs for the answer.'
    sse_lines = _make_sse_lines(
        {'event': 'reasoning.delta', 'text': earlier},
        {'event': 'message.delta', 'delta': 'Here is the answer: X.'},
        # This is what triggers the bug: same reasoning text arrives again after the message.
        {'event': 'reasoning.available', 'text': earlier},
        {'event': 'run.completed', 'usage': None},
    )
    response = _make_upstream_response(sse_lines)
    ctx = _make_ctx()
    upsert_calls = []

    with (
        patch('open_webui.utils.hermes_stream_handler.Chats') as mock_chats,
        patch('open_webui.utils.hermes_stream_handler.background_tasks_handler', new=AsyncMock()),
    ):
        mock_chats.upsert_message_to_chat_by_id_and_message_id.side_effect = (
            lambda chat_id, message_id, update: upsert_calls.append(update)
        )

        from open_webui.utils.hermes_stream_handler import handle_hermes_stream

        await handle_hermes_stream(response, ctx)

    output = _extract_output(upsert_calls)
    reasoning_items = [it for it in output if it.get('type') == 'reasoning']

    assert len(reasoning_items) == 1, (
        f'Expected exactly 1 reasoning item (the trailing reasoning.available '
        f'duplicate must be dropped), got {len(reasoning_items)}. '
        f'This is the phantom "Thought for 1 seconds" bug.'
    )


@pytest.mark.asyncio
async def test_trailing_reasoning_available_matching_message_body_is_dropped():
    """reasoning.available whose text appears in the message body must be dropped.

    Some models (grok-4.20) emit a post-hoc reasoning.available whose content
    is a substring of the visible response the model just streamed — e.g. the
    tail of the final paragraph. Without dedup against MESSAGE content (not
    just prior reasoning summaries), this lands as a phantom "Thought for 1
    seconds" block below the response containing a truncated copy of the text.

    Sequence:
      1. message.delta  — streams the visible response
      2. reasoning.available — carries a substring of that response

    Expected: 0 reasoning items (nothing to render). The message stands alone.
    """
    response_tail = (
        'You can click any image to view it larger. Let me know if you want '
        'more, specific types (e.g. sports cars), or higher resolution downloads.'
    )
    sse_lines = _make_sse_lines(
        {'event': 'message.delta', 'delta': 'Here are the cars.\n\n' + response_tail},
        # reasoning.available arrives AFTER the message with a substring duplicate.
        {'event': 'reasoning.available', 'text': response_tail},
        {'event': 'run.completed', 'usage': None},
    )
    response = _make_upstream_response(sse_lines)
    ctx = _make_ctx()
    upsert_calls = []

    with (
        patch('open_webui.utils.hermes_stream_handler.Chats') as mock_chats,
        patch('open_webui.utils.hermes_stream_handler.background_tasks_handler', new=AsyncMock()),
    ):
        mock_chats.upsert_message_to_chat_by_id_and_message_id.side_effect = (
            lambda chat_id, message_id, update: upsert_calls.append(update)
        )

        from open_webui.utils.hermes_stream_handler import handle_hermes_stream

        await handle_hermes_stream(response, ctx)

    output = _extract_output(upsert_calls)
    reasoning_items = [it for it in output if it.get('type') == 'reasoning']
    message_items = [it for it in output if it.get('type') == 'message']

    assert len(reasoning_items) == 0, (
        f'Expected 0 reasoning items (trailing reasoning.available duplicates '
        f'the message body and must be dropped). Got {len(reasoning_items)}. '
        f'This is the phantom "Thought for 1 seconds" bug where the agent '
        f'response tail appears inside a reasoning block below the response.'
    )
    assert len(message_items) == 1, (
        f'The message must remain intact. Got {len(message_items)} messages.'
    )


@pytest.mark.asyncio
async def test_reasoning_available_with_fresh_content_is_still_appended():
    """Dedup must NOT swallow genuinely new reasoning.available payloads.

    For XML-scratchpad models that ONLY emit reasoning.available (no deltas),
    the event carries the entire post-hoc reasoning — this must still land.
    """
    sse_lines = _make_sse_lines(
        {'event': 'reasoning.available', 'text': 'My full reasoning happened post-hoc here.'},
        {'event': 'message.delta', 'delta': 'Response.'},
        {'event': 'run.completed', 'usage': None},
    )
    response = _make_upstream_response(sse_lines)
    ctx = _make_ctx()
    upsert_calls = []

    with (
        patch('open_webui.utils.hermes_stream_handler.Chats') as mock_chats,
        patch('open_webui.utils.hermes_stream_handler.background_tasks_handler', new=AsyncMock()),
    ):
        mock_chats.upsert_message_to_chat_by_id_and_message_id.side_effect = (
            lambda chat_id, message_id, update: upsert_calls.append(update)
        )

        from open_webui.utils.hermes_stream_handler import handle_hermes_stream

        await handle_hermes_stream(response, ctx)

    output = _extract_output(upsert_calls)
    reasoning_items = [it for it in output if it.get('type') == 'reasoning']

    assert len(reasoning_items) == 1, (
        f'reasoning.available must create an item when there is no prior '
        f'matching reasoning. Got {len(reasoning_items)} items.'
    )
    summary = ''.join(p.get('text', '') for p in reasoning_items[0].get('summary', []))
    assert 'post-hoc' in summary, f'Reasoning text lost. Got: {summary!r}'


@pytest.mark.asyncio
async def test_short_think_block_matching_message_is_still_preserved():
    """Echo-drop must require substantial content length to avoid false positives.

    A 5-10 char <think> block that happens to match a substring of the message
    (e.g. the agent thinks 'okay' and then says 'okay, here is ...') must NOT
    be dropped. The minimum-length guard in _is_echo_of_message protects this.
    """
    stream = '<think>ok</think>ok, here is my plan for your business today.'
    sse_lines = _make_sse_lines(
        {'event': 'message.delta', 'delta': stream},
        {'event': 'run.completed', 'usage': None},
    )
    response = _make_upstream_response(sse_lines)
    ctx = _make_ctx()
    upsert_calls = []

    with (
        patch('open_webui.utils.hermes_stream_handler.Chats') as mock_chats,
        patch('open_webui.utils.hermes_stream_handler.background_tasks_handler', new=AsyncMock()),
    ):
        mock_chats.upsert_message_to_chat_by_id_and_message_id.side_effect = (
            lambda chat_id, message_id, update: upsert_calls.append(update)
        )

        from open_webui.utils.hermes_stream_handler import handle_hermes_stream

        await handle_hermes_stream(response, ctx)

    output = _extract_output(upsert_calls)
    reasoning_items = [item for item in output if item.get('type') == 'reasoning']

    assert len(reasoning_items) == 1, (
        f'Short <think> block must not be dropped. Got {len(reasoning_items)} reasoning items.'
    )
