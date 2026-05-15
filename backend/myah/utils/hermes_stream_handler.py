"""Hermes stream handler.

Parses the typed SSE event stream from the Hermes agent (via the Myah
adapter's /myah/v1/events endpoint) and emits WebSocket events directly,
bypassing the legacy middleware.

Returns a StreamingResponse that yields OpenAI-compatible SSE chunks so that
both Socket.IO consumers (the browser frontend) and HTTP consumers (curl,
the smoke test, API integrations) receive data.

The handler is the seed of the eventual middleware replacement. Only Myah
model requests are routed here. All other models continue to use the legacy
middleware path.

NOTE (Phase 4): Messages are dual-written to both Myah's chat table
(via _save_to_db below) and Hermes SessionDB (via the gateway's
session_store.append_to_transcript, which fires automatically since
messages route through _handle_message). Phase 5 removes the Myah
DB write path; Hermes SessionDB becomes the sole source of truth.

--- In-process stream registries ---

_active_runs: dict[str, dict]
    Keyed by chat_id. Value: {run_id, started_at (epoch ms), message_id}.
    Populated when the first run_id is captured from the SSE stream.
    Cleared 10 s after run.completed or run.failed (grace window for
    refresh-at-completion races).

    SINGLE-WORKER ASSUMPTION: This is a plain dict and is safe only because
    UVICORN_WORKERS=1. Verified 2026-04-23 under UVICORN_WORKERS=1 (source
    inspection of start.sh + docker-compose.prod.yaml; SSH access unavailable
    from dev machine but no override present in either file). If multi-worker
    is ever enabled, replace with a Redis-backed store before deploying —
    stale reads across workers will cause the frontend to see no active run
    even while one is in-flight.

_live_state: dict[tuple[str, str], dict]
    Keyed by (chat_id, message_id). Snapshot of the in-flight output list
    plus metadata (run_id, status, timestamps, accumulated text).
    Updated after every event that mutates the output list.
    Cleared 10 s after run.completed or run.failed.
"""

import asyncio
import json
import mimetypes
import os
import time
from pathlib import Path as _Path

try:
    import sentry_sdk as sentry_sdk

    _SENTRY_AVAILABLE = True
except ImportError:
    sentry_sdk = None  # type: ignore[assignment]
    _SENTRY_AVAILABLE = False
from loguru import logger
from myah.env import ENABLE_REALTIME_CHAT_SAVE
from myah.models.chats import Chats
from myah.models.files import Files
from myah.routers.containers import AGENT_BEARER_TOKEN, _gateway_url, get_or_create_container
from myah.utils.artifact_triggers import (
    extract_path_from_tool_result,
    is_artifact_extension,
    is_artifact_trigger_tool,
)
from myah.utils.chat_tasks import background_tasks_handler
from myah.utils.hermes_media_persist import persist_and_rewrite, persist_tool_paths
from myah.utils.hermes_routing import resolve_user_agent_base
from myah.utils.output import extract_render_ui_from_content, output_id, serialize_output
from myah.utils.response import normalize_usage
from pydantic import TypeAdapter, ValidationError
from starlette.responses import StreamingResponse

from shared.contract.events import HermesEvent

# ── Workstream I Phase 2: typed Hermes SSE event validation ───────────────────
# Every raw event dict that arrives on the SSE stream is validated against the
# discriminated union below. Validation failures (unknown event types, missing
# discriminator) are logged at warning level and the event is dropped, so
# unrecognised payloads cannot crash the stream handler. Successful validation
# means the dispatch switch below can rely on the ``event_type`` value being a
# known Hermes event string — defence in depth on top of the existing
# string-match logic.
_HERMES_EVENT_ADAPTER: TypeAdapter[HermesEvent] = TypeAdapter(HermesEvent)

log = logger


def _kind_for_filename(filename: str) -> str:
    """Map a filename's extension to the ArtifactCardItem ``kind`` discriminator.

    The renderer uses ``kind`` to pick the right Mini* preview component, so
    this map is the single source of truth for what extension routes to
    which preview. Unknown extensions fall back to ``'text'``.
    """
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    if ext in ('xlsx', 'xls'):
        return 'xlsx'
    if ext in ('csv', 'tsv'):
        return 'csv'
    if ext == 'docx':
        return 'docx'
    if ext in ('md', 'markdown'):
        return 'markdown'
    if ext in ('html', 'htm'):
        return 'html'
    if ext in ('json', 'jsonl'):
        return 'json'
    if ext == 'pdf':
        return 'pdf'
    if ext == 'pptx':
        return 'pptx'
    if ext in ('png', 'jpg', 'jpeg', 'gif', 'webp', 'svg'):
        return 'image'
    if ext in ('mp4', 'webm', 'mov'):
        return 'video'
    if ext in ('mp3', 'wav', 'ogg', 'flac', 'm4a'):
        return 'audio'
    if ext in ('db', 'sqlite', 'sqlite3'):
        return 'sqlite'
    if ext in (
        'py', 'ts', 'js', 'tsx', 'jsx', 'go', 'rs', 'java',
        'cpp', 'c', 'rb', 'sh', 'yaml', 'yml', 'toml',
    ):
        return 'code'
    return 'text'


# ── In-process stream registries ─────────────────────────────────────────────
# See module docstring for invariants and single-worker assumption.

_active_runs: dict[str, dict] = {}
_live_state: dict[tuple[str, str], dict] = {}
_registry_warning_emitted: bool = False


def _check_worker_count() -> None:
    """Emit a one-time critical log if UVICORN_WORKERS > 1.

    The registries are plain dicts and are only safe in a single-worker
    process. Call this on the first registry write per process so the
    problem surfaces at startup rather than silently producing stale reads.
    """
    global _registry_warning_emitted
    if _registry_warning_emitted:
        return
    _registry_warning_emitted = True
    workers = os.environ.get('UVICORN_WORKERS', '1')
    if workers != '1':
        log.critical(
            f'[STREAM_REGISTRY] _active_runs is a plain dict but UVICORN_WORKERS={workers}; '
            f'in-memory state will be stale across workers. Re-scope to Redis before multi-worker deploy.'
        )


def get_active_runs() -> dict[str, dict]:
    """Return the live _active_runs registry (avoid circular imports)."""
    return _active_runs


def get_live_state() -> dict[tuple[str, str], dict]:
    """Return the live _live_state registry (avoid circular imports)."""
    return _live_state


def _sse_chunk(delta: str = '', done: bool = False) -> str:
    """Format an OpenAI-compatible SSE chunk for the HTTP response body."""
    if done:
        return 'data: [DONE]\n\n'
    payload = {
        'choices': [{'delta': {'content': delta}}],
    }
    return f'data: {json.dumps(payload)}\n\n'


async def handle_hermes_stream(response, ctx: dict) -> StreamingResponse | None:  # noqa: C901
    """Process a /v1/runs SSE stream and return a StreamingResponse.

    The returned response yields OpenAI-compatible SSE chunks (with
    ``choices[0].delta.content``) so curl and other HTTP clients receive
    streaming data. Socket.IO events and DB persistence happen as side
    effects while iterating the upstream SSE stream.

    Args:
        response: A StreamingResponse whose body_iterator yields SSE lines
                  from the Hermes /v1/runs/{run_id}/events endpoint.
        ctx: Context dict built by build_chat_response_context(), containing
             request, form_data, user, metadata, tasks, event_emitter, etc.
    """

    async def _generate():  # noqa: C901
        metadata = ctx['metadata']
        event_emitter = ctx['event_emitter']

        chat_id = metadata.get('chat_id', '')
        message_id = metadata.get('message_id', '')

        # ── Sentry context ────────────────────────────────────────────────
        # Attach user identity and request context so any exception from
        # this stream handler appears in Sentry with actionable information.
        user = ctx.get('user')
        if _SENTRY_AVAILABLE:
            sentry_sdk.set_tag('chat_id', chat_id)
            sentry_sdk.set_tag('message_id', message_id)
            if user:
                sentry_sdk.set_user(
                    {
                        'id': getattr(user, 'id', ''),
                        'email': getattr(user, 'email', ''),
                    }
                )

        output: list[dict] = []
        usage: dict | None = None
        # ── Myah: per-message model attribution (T3-932) ─────────────────
        model_used: dict | None = None
        # ─────────────────────────────────────────────────────────────────
        done = False
        active_run_id: str | None = None
        reasoning_start: float | None = None
        last_save_time = time.monotonic()
        upstream_iterator = response.body_iterator
        # 2026-05-05 dogfooding: guard so the persist+artifact_card emission
        # block at run.completed fires AT MOST ONCE per _generate() call.
        # The upstream SSE iterator can deliver run.completed more than once
        # in pathological retry scenarios, and re-running persist creates
        # duplicate file_ids in chat.files (each persist mints a new uuid),
        # which then multiplies the artifact_card emission. Idempotent guard
        # is a cheap safety net.
        _persist_finalized = False

        # ── <think> tag detection for XML-scratchpad models ───────────────
        # Models like Gemini 2.5 Flash embed reasoning inside <think>...</think>
        # tags in the content stream.  The CLI strips these in _stream_delta(),
        # but the API server forwards raw tokens.  We intercept them here and
        # route to a reasoning item instead of the message body.
        _in_think_block = False
        _think_buffer = ''  # accumulates partial tag matches

        # ── Initial status ────────────────────────────────────────────────
        if event_emitter:
            await event_emitter(
                {
                    'type': 'status',
                    'data': {'description': 'Thinking...', 'done': False},
                }
            )

        # ── Helper: find or create the current message output item ────────
        def _get_or_create_message_item() -> dict:
            for item in output:
                if item.get('type') == 'message' and item.get('status') == 'in_progress':
                    return item
            msg_item: dict = {
                'type': 'message',
                'id': output_id('msg'),
                'status': 'in_progress',
                'role': 'assistant',
                'content': [{'type': 'output_text', 'text': ''}],
            }
            output.append(msg_item)
            return msg_item

        # ── Helper: detect echo-style <think> blocks ──────────────────────
        # Some models (kimi-k2.5 notably) emit their visible response and then
        # echo it back inside a trailing <think>...</think> block. Without this
        # guard we render a phantom 'Thought for less than a second' chain
        # containing the same text as the visible message. The heuristic: if a
        # <think> block's trimmed content is a substring of any prior message
        # content in the run, it's an echo; drop it.
        def _is_echo_of_message(think_text: str) -> bool:
            needle = think_text.strip()
            if len(needle) < 20:
                return False
            for it in output:
                if it.get('type') != 'message':
                    continue
                hay = ''.join(
                    (p.get('text') or '')
                    for p in it.get('content') or []
                    if p.get('type') == 'output_text'
                )
                if needle in hay:
                    return True
            return False

        # ── Helper: emit a chat:completion update via Socket.IO ───────────
        async def _emit_completion(done_flag: bool = False, error: str | None = None) -> None:
            if not event_emitter:
                return
            data: dict = {
                'content': serialize_output(output),
                'output': list(output),
                'done': done_flag,
            }
            if usage:
                data['usage'] = normalize_usage(usage)
            if error:
                data['error'] = {'content': error}
            await event_emitter({'type': 'chat:completion', 'data': data})

        # ── Helper: snapshot to _live_state registry ─────────────────────
        def _update_live_state(status: str = 'streaming') -> None:
            """Write the current output snapshot to _live_state.

            Called after every _emit_completion() that mutates in-flight state
            so the GET /{id}/messages/{message_id}/live_state endpoint always
            returns a fresh snapshot without touching the DB.
            """
            if not chat_id or not message_id:
                return
            # Extract accumulated visible text and reasoning text for convenience
            msg_content = ''
            reasoning_content = ''
            for _item in output:
                if _item.get('type') == 'message' and _item.get('role') == 'assistant':
                    for _part in _item.get('content', []):
                        if _part.get('type') == 'output_text':
                            msg_content += _part.get('text', '')
                elif _item.get('type') == 'reasoning':
                    for _part in _item.get('summary', []):
                        if _part.get('type') == 'summary_text':
                            reasoning_content += _part.get('text', '')

            _live_state[(chat_id, message_id)] = {
                'run_id': active_run_id,
                'chat_id': chat_id,
                'message_id': message_id,
                'started_at': _active_runs.get(chat_id, {}).get('started_at'),
                'updated_at': int(time.time() * 1000),
                'message_content': msg_content,
                'reasoning_content': reasoning_content,
                'output': list(output),
                'status': status,
            }

        # ── Helper: save to DB ────────────────────────────────────────────
        async def _save_to_db(done_flag: bool = False) -> None:
            if not chat_id or not message_id or chat_id.startswith('local:'):
                return
            update: dict = {
                'role': 'assistant',
                'content': serialize_output(output),
                'output': list(output),
                'done': done_flag,
            }
            if usage:
                update['usage'] = normalize_usage(usage)
            # ── Myah: per-message model attribution (T3-932) ─────────────
            # Only include on the final save so intermediate periodic saves
            # don't overwrite with a None value before run.completed fires.
            if done_flag and model_used:
                update['modelUsed'] = model_used
            # ─────────────────────────────────────────────────────────────
            Chats.upsert_message_to_chat_by_id_and_message_id(chat_id, message_id, update)

        # ── Main stream processing ─────────────────────────────────────────
        try:
            async for raw_line in upstream_iterator:
                if isinstance(raw_line, bytes):
                    raw_line = raw_line.decode('utf-8', 'replace')

                line = raw_line.strip()
                if not line:
                    continue

                # Skip SSE keepalive comments
                if line.startswith(':'):
                    continue

                # Only process data lines
                if not line.startswith('data:'):
                    continue

                json_str = line[len('data:') :].strip()
                if not json_str or json_str == '[DONE]':
                    continue

                try:
                    event_data = json.loads(json_str)
                except json.JSONDecodeError:
                    log.warning('[HERMES] Could not parse SSE line: {}', json_str[:200])
                    continue

                if not isinstance(event_data, dict):
                    continue

                event_type = event_data.get('event', '')

                # ── Workstream I Phase 2: typed validation gate ──────────────
                # Validate the event against the discriminated union. We
                # intentionally DON'T use the validated model for dispatch
                # below — the existing string-match logic is the regression-
                # tested code path. Validation here just gives us:
                #   1. A typed audit trail in logs when an unknown event_type
                #      arrives upstream (Hermes shipped a new event we don't
                #      recognise yet).
                #   2. Safety against malformed payloads: ValidationError
                #      means we skip the event with a warning rather than
                #      letting the dispatch logic crash on missing fields.
                # The else-branch warning at the bottom of the dispatch
                # (originally the tactical PR fix) is the safety net that
                # catches recognised-by-Hermes-but-not-by-platform events.
                try:
                    _HERMES_EVENT_ADAPTER.validate_python(event_data)
                except ValidationError as ve:
                    # Preserve the legacy "unknown hermes event type" substring
                    # so existing log monitors and the regression test at
                    # test_hermes_stream_handler.py::test_unknown_event_type_emits_warning
                    # keep matching. The structured ``errors`` payload below is
                    # the new diagnostic data introduced by the typed contract.
                    log.warning(
                        f'[HERMES] unknown hermes event type or invalid payload, skipping. '
                        f'event_type={event_type!r} errors={ve.errors(include_url=False)}'
                    )
                    continue

                # Capture the run_id from any event for use in confirmation resolution.
                # The Myah adapter emits stream_id; the API server emits run_id.
                # Check both keys so the confirmation flow works through either path.
                if not active_run_id:
                    _ev_run_id = event_data.get('run_id') or event_data.get('stream_id')
                    if _ev_run_id:
                        active_run_id = _ev_run_id
                        if event_emitter and chat_id:
                            await event_emitter(
                                {
                                    'type': 'chat:run_started',
                                    'data': {'run_id': active_run_id, 'chat_id': chat_id},
                                }
                            )
                        # ── Myah: populate _active_runs registry (T3-1001) ──────
                        if chat_id and message_id:
                            _check_worker_count()
                            _active_runs[chat_id] = {
                                'run_id': active_run_id,
                                'started_at': int(time.time() * 1000),
                                'message_id': message_id,
                            }
                        # ────────────────────────────────────────────────────────

                # ── message.delta ─────────────────────────────────────────
                if event_type == 'message.delta':
                    delta = event_data.get('delta', '')
                    if not delta:
                        continue

                    # ── Myah: filter Hermes "Still working..." status pings ──
                    # Hermes Gateway emits long-running notifications via the
                    # adapter.send() path (gateway/run.py:_notify_long_running).
                    # On Telegram/Slack these show up as a separate ephemeral
                    # message; on Myah they get inlined into the assistant's
                    # text content because adapter.send() pushes message.delta.
                    # Myah already shows iteration/tool progress in the
                    # Chain-of-Thought UI, so these pings are redundant AND
                    # they leak into the chat as a stale "Still working..."
                    # line that remains visible after run.completed.
                    # T3-1001 dogfooding 2026-04-24.
                    _stripped = delta.lstrip()
                    if _stripped.startswith('⏳ Still working') or _stripped.startswith(
                        '⏳ Stopped'
                    ):
                        continue
                    # ────────────────────────────────────────────────────────

                    # ── <think> tag interception ──────────────────────────
                    # XML-scratchpad models (e.g. Gemini 2.5 Flash) embed
                    # reasoning inside <think>...</think> in the content.
                    # Route it to a reasoning item instead of the message.
                    _think_buffer += delta
                    visible_text = ''

                    while _think_buffer:
                        if _in_think_block:
                            # Inside a <think> block — look for </think>
                            close_idx = _think_buffer.find('</think>')
                            if close_idx != -1:
                                # Found end tag — route thinking to reasoning
                                think_text = _think_buffer[:close_idx]
                                _think_buffer = _think_buffer[close_idx + len('</think>') :]
                                _in_think_block = False

                                if think_text.strip() and not _is_echo_of_message(think_text):
                                    # Add to reasoning output item
                                    r_item = next(
                                        (
                                            i
                                            for i in output
                                            if i.get('type') == 'reasoning' and i.get('status') == 'in_progress'
                                        ),
                                        None,
                                    )
                                    if r_item is None:
                                        r_item = {
                                            'type': 'reasoning',
                                            'id': output_id('rsn'),
                                            'status': 'in_progress',
                                            'summary': [{'type': 'summary_text', 'text': ''}],
                                        }
                                        output.append(r_item)
                                        if reasoning_start is None:
                                            reasoning_start = time.monotonic()
                                    s_parts = r_item.setdefault('summary', [])
                                    if s_parts and s_parts[-1].get('type') == 'summary_text':
                                        s_parts[-1]['text'] += think_text
                                    else:
                                        s_parts.append({'type': 'summary_text', 'text': think_text})
                            elif len(_think_buffer) > 8000:
                                # Safety: flush very large unmatched blocks
                                _think_buffer = ''
                                _in_think_block = False
                            else:
                                # Still inside think — wait for more data
                                break
                        else:
                            # Outside a think block — look for <think>
                            open_idx = _think_buffer.find('<think>')
                            if open_idx != -1:
                                # Emit text before the tag as visible content
                                visible_text += _think_buffer[:open_idx]
                                _think_buffer = _think_buffer[open_idx + len('<think>') :]
                                _in_think_block = True
                            elif '<' in _think_buffer and _think_buffer.rstrip().endswith('<'):
                                # Possible partial tag at end — hold it
                                cut = _think_buffer.rfind('<')
                                visible_text += _think_buffer[:cut]
                                _think_buffer = _think_buffer[cut:]
                                break
                            else:
                                # No tag — all visible
                                visible_text += _think_buffer
                                _think_buffer = ''

                    # Only emit visible (non-thinking) text to the message
                    if visible_text:
                        msg_item = _get_or_create_message_item()
                        parts = msg_item.setdefault('content', [])
                        if parts and parts[-1].get('type') == 'output_text':
                            parts[-1]['text'] += visible_text
                        else:
                            parts.append({'type': 'output_text', 'text': visible_text})

                        if reasoning_start is not None:
                            for _item in output:
                                if _item.get('type') == 'reasoning' and _item.get('status') == 'in_progress':
                                    _item['duration'] = round(time.monotonic() - reasoning_start)
                                    _item['status'] = 'completed'
                            reasoning_start = None

                    await _emit_completion()
                    _update_live_state()

                    # Yield OpenAI-compatible SSE chunk — only visible text
                    if visible_text:
                        yield _sse_chunk(delta=visible_text)

                    # Periodic DB save
                    if ENABLE_REALTIME_CHAT_SAVE:
                        now = time.monotonic()
                        if now - last_save_time >= 1.0:
                            await _save_to_db()
                            last_save_time = now

                # ── tool.started ──────────────────────────────────────────
                elif event_type == 'tool.started':
                    tool_name = event_data.get('tool', '')
                    call_id = event_data.get('call_id', output_id('call'))
                    args = event_data.get('args') or {}
                    args_str = json.dumps(args) if not isinstance(args, str) else args

                    for item in output:
                        if item.get('type') == 'message' and item.get('status') == 'in_progress':
                            item['status'] = 'completed'

                    # Close any in-progress reasoning so the NEXT reasoning.delta
                    # starts a fresh item AFTER this tool call. Without setting
                    # status='completed' here, reasoning.delta would find the
                    # prior item still in_progress and append — merging pre-tool
                    # and post-tool reasoning into a single block at the top of
                    # the chain, breaking chronological rendering.
                    for _item in output:
                        if _item.get('type') == 'reasoning' and _item.get('status') == 'in_progress':
                            if reasoning_start is not None:
                                _item['duration'] = round(time.monotonic() - reasoning_start)
                            elif _item.get('duration') is None:
                                _item['duration'] = 0
                            _item['status'] = 'completed'
                    reasoning_start = None

                    fc_item: dict = {
                        'type': 'function_call',
                        'id': output_id('fc'),
                        'call_id': call_id,
                        'name': tool_name,
                        'arguments': args_str,
                        'status': 'in_progress',
                    }
                    output.append(fc_item)

                    await _emit_completion()
                    _update_live_state()

                # ── tool.completed ────────────────────────────────────────
                elif event_type == 'tool.completed':
                    tool_name = event_data.get('tool', '')
                    call_id = event_data.get('call_id', '')
                    result = event_data.get('result', '')
                    is_error = event_data.get('error', False)

                    for item in output:
                        if item.get('type') == 'function_call' and item.get('call_id') == call_id:
                            item['status'] = 'completed' if not is_error else 'failed'

                    result_text = result if isinstance(result, str) else json.dumps(result)
                    fco_item: dict = {
                        'type': 'function_call_output',
                        'id': output_id('fco'),
                        'call_id': call_id,
                        'output': [{'type': 'input_text', 'text': result_text}],
                        'status': 'completed',
                    }
                    output.append(fco_item)

                    await _emit_completion()
                    _update_live_state()

                    # ── artifact_card OutputItem (in-flight) ───────────────
                    # NOTE: In Myah's Hermes adapter (gateway/platforms/myah.py:991)
                    # the `result` field is hardcoded to "" for tool.completed
                    # events, so this in-flight path will never produce a match
                    # today and the fallback below at run.completed is what
                    # actually appends the card. Kept symmetrical so if the
                    # Myah adapter ever passes the real result through, the
                    # inline preview appears as soon as the tool completes
                    # rather than waiting for run.completed. T3-1001 dogfooding.
                    if is_artifact_trigger_tool(tool_name) and not is_error:
                        result_path = extract_path_from_tool_result(result)
                        if result_path and is_artifact_extension(result_path):
                            _filename = _Path(result_path).name
                            _kind = _kind_for_filename(_filename)
                            # 2026-05-05 dogfooding (Bug 4): skip media kinds —
                            # they are already rendered inline by the markdown
                            # image / video / audio tokens, so the extra card
                            # below the rendered media is redundant noise.
                            if _kind not in ('image', 'video', 'audio'):
                                output.append({
                                    'type': 'artifact_card',
                                    'id': output_id('artifact'),
                                    'path': result_path,
                                    'filename': _filename,
                                    'mime': mimetypes.guess_type(result_path)[0],
                                    'mtime': time.time(),
                                    'kind': _kind,
                                })
                                log.info(
                                    f'[HERMES] artifact_card appended (in-flight) '
                                    f'path={result_path} tool={tool_name}'
                                )

                # ── reasoning.available / reasoning.delta ─────────────────
                # reasoning.delta  — real-time structured reasoning tokens
                #   (from reasoning_callback, fires token-by-token during LLM streaming)
                # reasoning.available — post-hoc content for XML-scratchpad models
                #   (from tool_progress_callback, fires once after response completes)
                # Both carry a 'text' field and map to the same ReasoningItem.
                elif event_type in ('reasoning.available', 'reasoning.delta'):
                    text = event_data.get('text', '')
                    if not text:
                        continue

                    # reasoning.available often fires AFTER the assistant's visible
                    # response has been streamed. For some models (kimi-k2.5,
                    # grok-4.20) the payload duplicates content already captured —
                    # either matching an earlier reasoning summary, OR matching a
                    # substring of the message body the model just produced. Both
                    # variants render as a phantom "Thought for 1 seconds" block
                    # below the response. Guard against both.
                    if event_type == 'reasoning.available':
                        _needle = text.strip()
                        if len(_needle) >= 20:
                            _is_dup = False
                            # Duplicate of an earlier reasoning summary?
                            for _it in output:
                                if _it.get('type') != 'reasoning':
                                    continue
                                _hay = ''.join(
                                    (p.get('text') or '')
                                    for p in _it.get('summary') or []
                                    if p.get('type') == 'summary_text'
                                )
                                if _needle in _hay:
                                    _is_dup = True
                                    break
                            # Duplicate of (or substring of) a prior message body?
                            if not _is_dup and _is_echo_of_message(text):
                                _is_dup = True
                            if _is_dup:
                                continue

                    reasoning_item = next(
                        (
                            item
                            for item in output
                            if item.get('type') == 'reasoning' and item.get('status') == 'in_progress'
                        ),
                        None,
                    )
                    if reasoning_item is None:
                        reasoning_item = {
                            'type': 'reasoning',
                            'id': output_id('rsn'),
                            'status': 'in_progress',
                            'summary': [{'type': 'summary_text', 'text': ''}],
                        }
                        output.append(reasoning_item)

                    summary_parts = reasoning_item.setdefault('summary', [])
                    if summary_parts and summary_parts[-1].get('type') == 'summary_text':
                        summary_parts[-1]['text'] += text
                    else:
                        summary_parts.append({'type': 'summary_text', 'text': text})

                    if reasoning_start is None:
                        reasoning_start = time.monotonic()

                    await _emit_completion()
                    _update_live_state()

                # ── tool.confirmation_required ─────────────────────────────────
                elif event_type == 'tool.confirmation_required':
                    confirmation_id = event_data.get('confirmation_id', '')
                    action_type = event_data.get('action_type', 'confirmation')
                    description = event_data.get('description', '')
                    options = event_data.get('options', ['approve', 'deny'])
                    metadata = event_data.get('metadata', {})

                    conf_item: dict = {
                        'type': 'confirmation',
                        'id': output_id('conf'),
                        'confirmation_id': confirmation_id,
                        'run_id': active_run_id or '',
                        'action_type': action_type,
                        'description': description,
                        'options': options,
                        'metadata': metadata,
                        'status': 'pending',
                    }
                    output.append(conf_item)
                    await _emit_completion()
                    _update_live_state()
                    log.info(
                        '[HERMES] tool.confirmation_required chat_id={} action={}',
                        chat_id,
                        action_type,
                    )

                # ── secret.required ──────────────────────────────────────
                elif event_type == 'secret.required':
                    var_name = event_data.get('var_name', '')
                    prompt_text = event_data.get('prompt', var_name)
                    help_url = event_data.get('help', '')
                    skill_name = event_data.get('skill_name', '')

                    secret_item: dict = {
                        'type': 'secret_input',
                        'id': output_id('secret'),
                        'run_id': active_run_id or '',
                        'var_name': var_name,
                        'prompt': prompt_text,
                        'help': help_url,
                        'skill_name': skill_name,
                        'status': 'pending',
                    }
                    output.append(secret_item)
                    await _emit_completion()
                    _update_live_state()
                    log.info(
                        '[HERMES] secret.required chat_id={} var={}',
                        chat_id,
                        var_name,
                    )

                # ── secret.resolved ───────────────────────────────────────
                elif event_type == 'secret.resolved':
                    var_name = event_data.get('var_name', '')
                    status = event_data.get('status', 'stored')
                    # Update the pending secret_input item
                    for item in output:
                        if item.get('type') == 'secret_input' and item.get('var_name') == var_name:
                            item['status'] = status
                            break
                    await _emit_completion()
                    _update_live_state()

                # ── run.completed ─────────────────────────────────────────
                elif event_type == 'run.completed':
                    run_usage = event_data.get('usage')
                    if run_usage:
                        usage = run_usage

                    # ── Myah: per-message model attribution (T3-932) ──────
                    # Capture the model + provider that answered this turn
                    # so the frontend can render an attribution badge on the
                    # assistant message after page reload.
                    _model_used_id = event_data.get('model') or ''
                    _model_used_provider = event_data.get('provider') or ''
                    if _model_used_id:
                        model_used = {
                            'id': _model_used_id,
                            'provider': _model_used_provider,
                        }
                    # ──────────────────────────────────────────────────────

                    for item in output:
                        if item.get('status') == 'in_progress':
                            item['status'] = 'completed'
                            if item.get('type') == 'reasoning':
                                if reasoning_start is not None:
                                    item['duration'] = round(time.monotonic() - reasoning_start)
                                    reasoning_start = None
                                elif item.get('duration') is None:
                                    item['duration'] = 0

                    output[:] = extract_render_ui_from_content(output)

                    # If the run completed successfully, any confirmation that was
                    # pending must have been approved (the agent continued past the
                    # blocking point).  Mark as resolved so the UI shows "Approved".
                    for item in output:
                        if item.get('type') == 'confirmation' and item.get('status') == 'pending':
                            item['status'] = 'resolved'
                            item['chosen'] = 'approve'

                    done = True

                    # ── Persist agent-produced media refs ──────────────────────
                    # Rewrite MEDIA tags and external image URLs to platform
                    # storage before the DB write — so reload renders from the
                    # platform, not the container cache (which has a 24h TTL).
                    #
                    # 2026-05-05 dogfooding: guard against repeated execution.
                    # Without this, a duplicate run.completed event re-mints
                    # file_ids in chat.files and re-appends artifact_cards.
                    if _persist_finalized:
                        log.warning(
                            '[HERMES] run.completed fired more than once; '
                            'skipping duplicate persist + artifact_card pass.'
                        )
                    try:
                        _uid = getattr(user, 'id', None)
                        if not _persist_finalized and _uid and chat_id:
                            _container_rec = await get_or_create_container(_uid)
                            # Tier 2A standalone-runner: /myah/v1/* lives on the
                            # gateway port; fall back to host_port for pre-Tier-2A rows.
                            _stream_base = _gateway_url(_container_rec.gateway_port or _container_rec.host_port)
                            _agent_base = resolve_user_agent_base(_stream_base)
                            if _agent_base:
                                # 2026-05-05 dogfooding (Bug 1b): persist files
                                # by tool-arg path BEFORE we render artifact_card
                                # items below. Without this, write_file calls with
                                # bare filenames (e.g. write_file(path='fib.py'))
                                # never appear in chat.files because the prose
                                # persist scanner requires absolute paths under
                                # known workspace prefixes — and the agent's
                                # message often only mentions the file by bare
                                # name. We collect tool-arg paths here and
                                # resolve each via cwd fallback.
                                _tool_paths: list[str] = []
                                for _it in output:
                                    if _it.get('type') != 'function_call':
                                        continue
                                    _name = _it.get('name', '')
                                    if _name not in (
                                        'write_file',
                                        'patch',
                                        'execute_code',
                                        'terminal',
                                        'image_generate',
                                        'text_to_speech',
                                        'browser_get_images',
                                    ):
                                        continue
                                    _args_raw = _it.get('arguments') or _it.get('args') or ''
                                    if isinstance(_args_raw, str):
                                        try:
                                            _args = json.loads(_args_raw)
                                        except (json.JSONDecodeError, ValueError):
                                            _args = {}
                                    else:
                                        _args = _args_raw or {}
                                    if not isinstance(_args, dict):
                                        continue
                                    for _k in ('path', 'filename', 'file_path', 'filepath'):
                                        _v = _args.get(_k)
                                        if isinstance(_v, str) and _v.strip():
                                            _tool_paths.append(_v.strip())
                                            break
                                if _tool_paths and message_id:
                                    try:
                                        await persist_tool_paths(
                                            user_id=_uid,
                                            chat_id=chat_id,
                                            message_id=message_id,
                                            paths=_tool_paths,
                                            agent_base_url=_agent_base,
                                            agent_bearer=AGENT_BEARER_TOKEN,
                                        )
                                    except Exception as _tp_exc:
                                        log.warning(
                                            f'[HERMES] persist_tool_paths failed: {_tp_exc}'
                                        )

                                # Snapshot the message items BEFORE the persist+
                                # append block runs. Iterating a snapshot — not
                                # the mutable `output` list — is what stops the
                                # cascading-append bug discovered 2026-05-05:
                                # the artifact_card emission below appends to
                                # `output`, so iterating `output` directly here
                                # walks every newly-emitted card on subsequent
                                # turns, producing exponential append counts.
                                _msg_items_snapshot = [
                                    _it
                                    for _it in output
                                    if _it.get('type') == 'message'
                                    and _it.get('role') == 'assistant'
                                ]
                                for _item in _msg_items_snapshot:
                                    for _part in _item.get('content', []):
                                        if _part.get('type') == 'output_text':
                                            _part['text'] = await persist_and_rewrite(
                                                user_id=_uid,
                                                chat_id=chat_id,
                                                message_id=message_id,
                                                message_text=_part.get('text', ''),
                                                agent_base_url=_agent_base,
                                                agent_bearer=AGENT_BEARER_TOKEN,
                                            )

                                # Append artifact_card OutputItems for every
                                # persisted file linked to this message. Runs
                                # ONCE per run.completed (hoisted out of the
                                # message-iter loop) and dedupes against any
                                # cards already in output, so retries / re-runs
                                # don't multiply the card count.
                                #
                                # T3-1001 dogfooding 2026-04-24: surfaces files
                                # that the Hermes adapter strips from tool result
                                # bodies (myah.py:991).
                                #
                                # 2026-05-05 dogfooding (Bug 4): skip image /
                                # video / audio kinds — already rendered inline
                                # by the markdown image / video / audio tokens.
                                if chat_id and message_id:
                                    try:
                                        _existing_card_file_ids = {
                                            _it.get('file_id')
                                            for _it in output
                                            if _it.get('type') == 'artifact_card'
                                        }
                                        _files_for_msg = (
                                            Chats.get_chat_files_by_chat_id_and_message_id(
                                                chat_id=chat_id, message_id=message_id
                                            )
                                            or []
                                        )
                                        # Dedupe by file_id within this batch in
                                        # case insert_chat_files left more than
                                        # one row per (chat_id, message_id, file_id).
                                        _seen_file_ids: set[str] = set()
                                        for _cf in _files_for_msg:
                                            if _cf.file_id in _seen_file_ids:
                                                continue
                                            _seen_file_ids.add(_cf.file_id)
                                            if _cf.file_id in _existing_card_file_ids:
                                                continue
                                            _file = Files.get_file_by_id(_cf.file_id)
                                            if not _file:
                                                continue
                                            _filename = (_file.meta or {}).get('name') or _file.filename
                                            if not _filename or not is_artifact_extension(_filename):
                                                continue
                                            _kind = _kind_for_filename(_filename)
                                            if _kind in ('image', 'video', 'audio'):
                                                continue
                                            output.append({
                                                'type': 'artifact_card',
                                                'id': output_id('artifact'),
                                                'file_id': _file.id,
                                                'filename': _filename,
                                                'mime': (_file.meta or {}).get('content_type'),
                                                'mtime': time.time(),
                                                'kind': _kind,
                                            })
                                            log.info(
                                                f'[HERMES] artifact_card appended for persisted file '
                                                f'{_filename} ({_file.id})'
                                            )
                                    except Exception as _ae:
                                        log.warning(
                                            f'[HERMES] failed to append artifact_card for persisted file: {_ae}'
                                        )
                    except Exception as _pe:
                        log.warning('[HERMES] persist_and_rewrite failed: {}', _pe)
                    finally:
                        # Mark finalized inside the finally so the guard fires
                        # even if persist_and_rewrite raises — the next
                        # run.completed event still skips the duplicate work.
                        _persist_finalized = True
                    # ─────────────────────────────────────────────────────────

                    await _save_to_db(done_flag=True)
                    await _emit_completion(done_flag=True)

                    # ── Myah: settle registries with 10s grace (T3-1001) ──
                    _update_live_state(status='settled')
                    asyncio.get_running_loop().call_later(10, _active_runs.pop, chat_id, None)
                    asyncio.get_running_loop().call_later(10, _live_state.pop, (chat_id, message_id), None)
                    # ─────────────────────────────────────────────────────

                    log.info(
                        '[HERMES] step=run_completed chat_id={} message_id={}',
                        chat_id,
                        message_id,
                    )

                    # Background tasks (title, tags, follow-ups)
                    try:
                        await background_tasks_handler(ctx)
                    except Exception:
                        log.exception('[HERMES] background_tasks_handler failed')

                    yield _sse_chunk(done=True)

                # ── run.failed ────────────────────────────────────────────
                elif event_type == 'run.failed':
                    error_text = event_data.get('error', 'Agent run failed')

                    for item in output:
                        if item.get('type') == 'confirmation' and item.get('status') == 'pending':
                            item['status'] = 'cancelled'

                    done = True

                    if event_emitter:
                        await event_emitter(
                            {
                                'type': 'chat:message:error',
                                'data': {'error': {'content': error_text}},
                            }
                        )

                    if chat_id and message_id and not chat_id.startswith('local:'):
                        Chats.upsert_message_to_chat_by_id_and_message_id(
                            chat_id,
                            message_id,
                            {'error': {'content': error_text}, 'done': True},
                        )

                    await _emit_completion(done_flag=True, error=error_text)

                    # ── Myah: settle registries with 10s grace (T3-1001) ──
                    _update_live_state(status='settled')
                    asyncio.get_running_loop().call_later(10, _active_runs.pop, chat_id, None)
                    asyncio.get_running_loop().call_later(10, _live_state.pop, (chat_id, message_id), None)
                    # ─────────────────────────────────────────────────────

                    log.error('[HERMES] step=run_failed chat_id={} error={}', chat_id, error_text)

                    yield _sse_chunk(done=True)

                # ── run.cancelled ─────────────────────────────────────────
                elif event_type == 'run.cancelled':
                    # User-initiated cancellation (or upstream asyncio.CancelledError).
                    # Mark pending confirmations as cancelled and the chat message
                    # as cancelled in the DB so the UI can show "this run was
                    # cancelled" instead of leaving the message stuck mid-stream.
                    log.info('[HERMES] step=run_cancelled chat_id={}', chat_id)

                    for item in output:
                        if item.get('type') == 'confirmation' and item.get('status') == 'pending':
                            item['status'] = 'cancelled'

                    done = True

                    if chat_id and message_id and not chat_id.startswith('local:'):
                        try:
                            Chats.upsert_message_to_chat_by_id_and_message_id(
                                chat_id, message_id, {'done': True}
                            )
                            Chats.add_message_status_to_chat_by_id_and_message_id(
                                chat_id,
                                message_id,
                                {'type': 'cancelled', 'description': 'Run cancelled'},
                            )
                        except Exception as exc:
                            log.warning(f'[HERMES] failed to mark chat message cancelled: {exc}')

                    await _emit_completion(done_flag=True)

                    # ── Myah: settle registries with 10s grace (T3-1001) ──
                    _update_live_state(status='settled')
                    asyncio.get_running_loop().call_later(10, _active_runs.pop, chat_id, None)
                    asyncio.get_running_loop().call_later(10, _live_state.pop, (chat_id, message_id), None)
                    # ─────────────────────────────────────────────────────

                    yield _sse_chunk(done=True)

                # ── unknown event type ───────────────────────────────────
                # Tactical observability gap closer (Workstream I pre-Phase 2):
                # the switch above silently dropped any event_type it didn't
                # recognise, so a new Hermes event added upstream would never
                # surface in platform logs. A warning here is the cheapest
                # signal until Phase 2 introduces typed event contracts.
                else:
                    log.warning(f'[HERMES] unknown hermes event type: {event_type}')

        except Exception:
            log.exception('[HERMES] Unhandled error in stream handler chat_id={}', chat_id)
            if event_emitter and not done:
                try:
                    await _emit_completion(done_flag=True, error='Internal stream processing error')
                except Exception:
                    pass

        finally:
            if not done:
                done = True
                try:
                    await _save_to_db(done_flag=True)
                    await _emit_completion(done_flag=True)
                except Exception:
                    log.exception('[HERMES] Error in finally block chat_id={}', chat_id)
            # Always clean up registries on any exit path (normal, exception,
            # client disconnect, CancelledError). dict.pop(k, None) is idempotent
            # so double-scheduling with the grace timers above is benign.
            # C2-mitigation: recency-bound state enforced on ALL exit paths.
            if chat_id:
                try:
                    loop = asyncio.get_running_loop()
                    loop.call_later(10, _active_runs.pop, chat_id, None)
                    if message_id:
                        loop.call_later(10, _live_state.pop, (chat_id, message_id), None)
                except RuntimeError:
                    # No running loop (e.g. during test teardown) — clean up immediately
                    _active_runs.pop(chat_id, None)
                    if message_id:
                        _live_state.pop((chat_id, message_id), None)
            # Always yield [DONE] so HTTP consumers see a clean stream end
            yield _sse_chunk(done=True)
            # Ensure the upstream stream_wrapper generator (which holds the
            # aiohttp ClientSession and ClientResponse) is closed promptly.
            # Without this, if the client disconnects before the stream
            # completes, the generator sits uncollected and aiohttp logs
            # "Unclosed client session" / "Unclosed connector" warnings
            # when the GC eventually collects it.
            if hasattr(upstream_iterator, 'aclose'):
                try:
                    await upstream_iterator.aclose()
                except Exception:
                    pass

    # ── Context-aware dispatch ────────────────────────────────────────────────
    # When event_caller is set, session_id/chat_id/message_id are all present
    # and the HTTP endpoint already returned {'status': True, 'task_id': ...}.
    # This is the normal browser path: consume _generate() eagerly so Socket.IO
    # events are emitted and DB writes happen.  Nothing is returned to the HTTP
    # caller (main.py discards the return value from background tasks anyway).
    #
    # This mirrors the legacy streaming_chat_response_handler branch at
    # middleware.py:3028 which uses the same event_caller guard to detect the
    # background-task context.
    #
    # When event_caller is None, the caller is an HTTP client that reads the
    # response body directly (curl, smoke test, API integrations). Wrap
    # _generate() in a StreamingResponse so the SSE chunks flow to the client.
    if ctx.get('event_caller'):
        async for _ in _generate():
            pass
        return None

    return StreamingResponse(
        _generate(),
        status_code=200,
        headers={'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache'},
    )
