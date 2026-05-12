# Pure translation functions between Hermes stream chunks and AG-UI events.
# Nothing here touches the database or the network — every function is a
# deterministic transformation of its inputs.

import json
import re

from loguru import logger
from open_webui.utils.agui_types import (
    ActivitySnapshotEvent,
    StateSnapshotEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallStartEvent,
)

# ---------------------------------------------------------------------------
# Activity-text pattern table
# ---------------------------------------------------------------------------

ACTIVITY_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r'^_Running terminal command: (.+?)_$'), 'terminal'),
    (re.compile(r'^_Running shell command: (.+?)_$'), 'terminal'),
    (re.compile(r'^_Reading file: (.+?)_$'), 'file_read'),
    (re.compile(r'^_Writing file: (.+?)_$'), 'file_write'),
    (re.compile(r'^_Searching the web\.\.\._$'), 'web_search'),
    (re.compile(r'^_Fetching URL: (.+?)_$'), 'web_fetch'),
    (re.compile(r'^_Using ([\w][\w\-]*)_$'), 'tool'),
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def events_from_output_items(output: list[dict], message_id: str = '') -> list[dict]:
    """Translate a completed output item list into AG-UI events.

    Scans for ``function_call`` items whose name is ``render_ui`` and emits
    the standard ToolCallStart → ToolCallArgs → StateSnapshot → ToolCallEnd
    sequence for each one.  Used to fire live AG-UI events for synthetic tool
    calls that were created by the code-fence interception path.

    Args:
        output: The list of output items (function_call, function_call_output,
                message, etc.) produced by the stream.
        message_id: The parent message id to attach to ToolCallStart.

    Returns:
        List of dicts from model_dump() on each AG-UI event.
    """

    if not isinstance(output, list):
        return []

    try:
        events: list[dict] = []
        for item in output:
            if item.get('type') != 'function_call':
                continue
            tool_name: str = item.get('name', '')
            if tool_name != 'render_ui':
                continue
            call_id: str = item.get('call_id', '')
            arguments: str = item.get('arguments', '{}')
            if not isinstance(arguments, str):
                arguments = json.dumps(arguments)

            start = ToolCallStartEvent(
                tool_call_id=call_id,
                tool_call_name=tool_name,
                parent_message_id=message_id or None,
            )
            events.append(_dump(start))

            args_event = ToolCallArgsEvent(tool_call_id=call_id, delta=arguments)
            events.append(_dump(args_event))

            events.append(_build_render_ui_snapshot(call_id, arguments))

            end = ToolCallEndEvent(tool_call_id=call_id)
            events.append(_dump(end))

        return events
    except Exception:  # noqa: BLE001 — never crash the stream
        _shape = output[:3] if isinstance(output, list) else type(output).__name__
        logger.opt(exception=True).warning(f'events_from_output_items failed: {_shape}')
        return []


def events_from_tool_calls_log(tool_calls_log: list[dict], message_id: str = '') -> list[dict]:
    """Translate a Hermes tool_calls_log into a list of serialised AG-UI event dicts.

    Supported tool names:
      - render_ui   → ToolCallStart + ToolCallArgs + ToolCallEnd + StateSnapshot
      - render_custom → ToolCallStart + ToolCallArgs + ToolCallEnd

    Malformed or unrecognised input returns an empty list without raising.

    Args:
        tool_calls_log: The list found at chunk['tool_calls_log'].
        message_id: The parent message id to attach to ToolCallStart.

    Returns:
        List of dicts produced by model_dump() on each AG-UI event.
    """

    if not isinstance(tool_calls_log, list):
        return []

    try:
        return _translate_tool_calls_log(tool_calls_log, message_id)
    except Exception:  # noqa: BLE001 — never crash the stream
        _n = len(tool_calls_log) if isinstance(tool_calls_log, list) else -1
        logger.opt(exception=True).warning(f'events_from_tool_calls_log failed for {_n} entries (msg={message_id})')
        return []


def events_from_tool_event(event_dict: dict, message_id: str = '') -> list[dict]:
    """Translate a structured Hermes ``tool.event`` SSE line into AG-UI events.

    The Hermes fork emits these as separate SSE lines alongside the content
    stream — one per tool invocation.  The ``object`` field is ``"tool.event"``
    and ``type`` is ``"start"``, ``"progress"``, or ``"complete"``.

    - ``start``    → ToolCallStart + ToolCallArgs
    - ``complete`` → StateSnapshot (render_ui only) + ToolCallEnd
    - ``progress`` → ActivitySnapshot (tool label / preview)

    Args:
        event_dict: Parsed SSE chunk with ``object == "tool.event"``.
        message_id: The parent message id to attach to ToolCallStart.

    Returns:
        List of serialised AG-UI event dicts (may be empty).
    """
    if not isinstance(event_dict, dict):
        return []
    try:
        return _translate_tool_event(event_dict, message_id)
    except Exception:  # noqa: BLE001
        logger.opt(exception=True).warning(
            f'events_from_tool_event failed: type={event_dict.get("type", "?")} name={event_dict.get("name", "?")} (msg={message_id})'
        )
        return []


def _translate_tool_event(event_dict: dict, message_id: str) -> list[dict]:
    """Inner translation — may raise; caller wraps in try/except."""
    event_type = event_dict.get('type', '')
    tool_name = event_dict.get('name', '')
    call_id = event_dict.get('call_id', '')
    args = event_dict.get('args') or {}
    result = event_dict.get('result', '')
    preview = event_dict.get('preview', '')

    events: list[dict] = []

    if event_type == 'start':
        # ToolCallStart
        start = ToolCallStartEvent(
            tool_call_id=call_id,
            tool_call_name=tool_name,
            parent_message_id=message_id or None,
        )
        events.append(_dump(start))
        # ToolCallArgs — send full args as a single delta
        args_str = json.dumps(args) if not isinstance(args, str) else args
        args_event = ToolCallArgsEvent(tool_call_id=call_id, delta=args_str)
        events.append(_dump(args_event))

    elif event_type == 'complete':
        # StateSnapshot for render_ui (must come before ToolCallEnd)
        if tool_name in ('render_ui', 'render_custom'):
            args_str = json.dumps(args) if not isinstance(args, str) else args
            events.append(_build_render_ui_snapshot(call_id, args_str))
        # ToolCallEnd
        end = ToolCallEndEvent(tool_call_id=call_id)
        events.append(_dump(end))

    elif event_type == 'progress':
        # ActivitySnapshot for live tool-progress display
        description = preview or tool_name
        activity_event = ActivitySnapshotEvent(
            message_id=message_id,
            activity_type='tool',
            content={'tool': tool_name, 'description': description},
        )
        events.append(_dump(activity_event))

    return events


def events_from_run_event(event_data: dict, message_id: str = '') -> list[dict]:
    """Translate a Hermes /v1/runs tool lifecycle event into AG-UI events.

    The /v1/runs endpoint emits ``tool.started`` and ``tool.completed``
    events with ``call_id``, ``args``, and ``result`` fields (added by
    our Myah patch to _make_run_event_callback).

    Args:
        event_data: Parsed SSE event dict with ``event`` field.
        message_id: The parent message id for ToolCallStart.

    Returns:
        List of serialised AG-UI event dicts (may be empty).
    """
    if not isinstance(event_data, dict):
        return []
    try:
        return _translate_run_event(event_data, message_id)
    except Exception:  # noqa: BLE001
        logger.opt(exception=True).warning(
            f'events_from_run_event failed: event={event_data.get("event", "?")} tool={event_data.get("tool", "?")} (msg={message_id})'
        )
        return []


def _translate_run_event(event_data: dict, message_id: str) -> list[dict]:
    """Inner translation for /v1/runs events."""
    event_type = event_data.get('event', '')
    tool_name = event_data.get('tool', '')
    call_id = event_data.get('call_id', '')
    args = event_data.get('args') or {}
    result = event_data.get('result', '')
    preview = event_data.get('preview', '')

    events: list[dict] = []

    if event_type == 'tool.started':
        start = ToolCallStartEvent(
            tool_call_id=call_id,
            tool_call_name=tool_name,
            parent_message_id=message_id or None,
        )
        events.append(_dump(start))
        args_str = json.dumps(args) if not isinstance(args, str) else args
        args_event = ToolCallArgsEvent(tool_call_id=call_id, delta=args_str)
        events.append(_dump(args_event))
        # Activity indicator with tool preview
        if preview or tool_name:
            activity = ActivitySnapshotEvent(
                message_id=message_id,
                activity_type='tool',
                content={'tool': tool_name, 'description': preview or tool_name},
            )
            events.append(_dump(activity))

    elif event_type == 'tool.completed':
        if tool_name in ('render_ui', 'render_custom'):
            args_str = json.dumps(args) if not isinstance(args, str) else args
            events.append(_build_render_ui_snapshot(call_id, args_str))
        end = ToolCallEndEvent(tool_call_id=call_id)
        events.append(_dump(end))

    return events


def events_from_activity_text(text: str, message_id: str = '') -> tuple[list[dict], bool]:
    """Detect an activity progress line and emit an ActivitySnapshotEvent.

    Args:
        text: The full content delta string from a stream chunk.
        message_id: The current message id.

    Returns:
        (events, suppressed) — suppressed is True when text was 100% an
        activity line and should be dropped from the text stream.
    """
    if not text:
        return [], False

    for pattern, activity_type in ACTIVITY_PATTERNS:
        if pattern.match(text):
            event = ActivitySnapshotEvent(
                message_id=message_id,
                activity_type=activity_type,
                content={'description': text},
            )
            return [_dump(event)], True

    return [], False


def extract_agui_events_from_stream_chunk(chunk_data: dict, message_id: str = '') -> tuple[list[dict], bool]:
    """Single entry-point for extracting AG-UI events from any stream chunk.

    Handles both tool_calls_log chunks and activity-text deltas in one call.

    Args:
        chunk_data: A parsed SSE chunk dict.
        message_id: The current message id.

    Returns:
        (events, suppressed) — suppressed signals the content delta should
        not be forwarded to the text stream.
    """
    if not isinstance(chunk_data, dict):
        return [], False

    # Priority 1: tool_calls_log (non-standard Hermes chunk)
    tool_calls_log = chunk_data.get('tool_calls_log')
    if tool_calls_log is not None:
        events = events_from_tool_calls_log(tool_calls_log, message_id=message_id)
        return events, False  # tool_calls_log chunks don't suppress text content

    # Priority 2: activity text in delta.content
    choices = chunk_data.get('choices')
    if isinstance(choices, list) and choices:
        delta = choices[0].get('delta', {})
        content = delta.get('content', '')
        if content:
            return events_from_activity_text(content, message_id=message_id)

    return [], False


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _dump(event) -> dict:
    """Serialise an AG-UI pydantic event to a plain dict with string type."""
    data = event.model_dump()
    # EventType is an enum; convert to its string value so callers can do
    # simple == 'TOOL_CALL_START' comparisons.
    if hasattr(data.get('type'), 'value'):
        data['type'] = data['type'].value
    return data


def _translate_tool_calls_log(log: list[dict], message_id: str) -> list[dict]:
    """Inner translation — may raise; caller wraps in try/except."""
    # Extract the assistant turn that carries the tool_calls list
    assistant_turn = next(
        (entry for entry in log if entry.get('role') == 'assistant' and 'tool_calls' in entry),
        None,
    )
    if assistant_turn is None:
        return []

    tool_calls: list[dict] = assistant_turn.get('tool_calls', [])
    if not tool_calls:
        return []

    events: list[dict] = []

    for tool_call in tool_calls:
        call_id: str = tool_call.get('id', '')
        fn = tool_call.get('function', {})
        tool_name: str = fn.get('name', '')
        arguments: str = fn.get('arguments', '{}')

        # --- ToolCallStart ---
        start = ToolCallStartEvent(
            tool_call_id=call_id,
            tool_call_name=tool_name,
            parent_message_id=message_id or None,
        )
        events.append(_dump(start))

        # --- ToolCallArgs ---
        args_event = ToolCallArgsEvent(tool_call_id=call_id, delta=arguments)
        events.append(_dump(args_event))

        # --- StateSnapshot (render_ui only) — must come BEFORE ToolCallEnd so
        # the frontend STATE_SNAPSHOT handler can find the still-incomplete call ---
        if tool_name == 'render_ui':
            events.append(_build_render_ui_snapshot(call_id, arguments))

        # --- ToolCallEnd ---
        end = ToolCallEndEvent(tool_call_id=call_id)
        events.append(_dump(end))

    return events


def _build_render_ui_snapshot(call_id: str, arguments: str) -> dict:
    """Build a StateSnapshotEvent dict for a render_ui tool call.

    Accepts both direct-blocks format ``{"blocks": [...]}`` and composition
    format ``{"composition": "kpi_dashboard", "data": {...}}``.
    """
    try:
        parsed_args = json.loads(arguments)
        component_id = parsed_args.get('componentId', '')
        if 'composition' in parsed_args:
            from open_webui.utils.agui_compositions import expand_composition

            try:
                expanded = expand_composition(parsed_args['composition'], parsed_args.get('data', {}))
                blocks = expanded.get('blocks', [])
            except KeyError:
                blocks = parsed_args.get('blocks', [])
        else:
            blocks = parsed_args.get('blocks', [])
    except (json.JSONDecodeError, AttributeError):
        component_id = ''
        blocks = []

    logger.debug(
        'Built render_ui StateSnapshot',
        call_id=call_id,
        component_id=component_id,
        block_count=len(blocks),
    )

    snapshot = StateSnapshotEvent(
        snapshot={
            'ui': {
                'lastRender': {
                    'toolName': 'render_ui',
                    'componentId': component_id,
                    'blocks': blocks,
                },
                'components': {
                    call_id: {
                        'type': 'render_ui',
                        'componentId': component_id,
                        'data': json.dumps(blocks),
                    }
                },
            }
        }
    )
    event_dict = _dump(snapshot)
    event_dict['_tool_call_id'] = call_id
    return event_dict
