"""Background chat task orchestration.

Runs title generation, tag generation, and follow-up suggestions
as concurrent background tasks after a chat response completes.
"""

import asyncio
import json
import logging
import re
from typing import Optional

from myah.constants import TASKS
from myah.models.chats import Chats
from myah.socket.main import (
    get_event_call,
    get_event_emitter,
)
from myah.routers.tasks import (
    _fetch_title_via_aux,
    _fetch_follow_ups_via_aux,
)
from myah.utils.misc import (
    get_message_list,
    get_last_user_message,
    get_last_user_message_item,
)

log = logging.getLogger(__name__)


# ── Myah: plain-text title sanitizer (ported from hermes-webui api/streaming.py) ─────────────
# These patterns reject LLM-reasoning leaks and acknowledgement phrases that
# occasionally appear when a provider ignores the plain-text contract and emits
# preamble text instead of the title directly.
#
# Rules for extending this list:
#  - Anchor at the string start with re.match (not re.search).
#  - Use \b for short English tokens to avoid false rejects on real words
#    (e.g. "ok\b" rejects "OK," but not "Okra Recipe").
#  - Chinese patterns: single-char tokens have no word boundary — match raw.
#  - When in doubt, do NOT add the pattern — a missed invalid title falls back
#    to the provisional title from PR 1a (acceptable degradation).

_INVALID_TITLE_PATTERNS = [
    re.compile(r'^ok\b', re.IGNORECASE),                       # 'ok', 'OK,' — but not 'Okra'
    re.compile(r'^done[.,!?\s]*$', re.IGNORECASE),             # 'Done', 'Done.' — but not 'Done and dusted'
    re.compile(r'^all\s+set\b', re.IGNORECASE),
    re.compile(r'^完成'),                                        # Chinese "complete/done"
    re.compile(r'^测试完成'),                                     # Chinese "test complete"
    re.compile(r'^用户'),                                         # Chinese "user"
    re.compile(r'^the\s+user\s+(is|wants|asked|has)\b', re.IGNORECASE),
    re.compile(r'^let\s+me\s+', re.IGNORECASE),
    re.compile(r'^i\s+will\b', re.IGNORECASE),
    re.compile(r"^i'?ll\b", re.IGNORECASE),
    re.compile(r'^sure,?\s+here', re.IGNORECASE),
    # "here is your …" / "here are the …" / "here's your …" — LLM preamble
    re.compile(r"^here\s*(?:'s|is|are)\s+(your|the)\b", re.IGNORECASE),
]


def _looks_invalid_title(title: str) -> bool:
    """Return True if *title* looks like an LLM-reasoning leak or acknowledgement phrase.

    Ported (narrow) from hermes-webui ``api/streaming.py::_looks_invalid_generated_title``.
    Patterns are anchored at the string start via ``re.match`` — substring matching
    is intentionally avoided to minimise false positives on real titles.
    """
    if not title or not title.strip() or len(title.strip()) < 2:
        return True
    for pattern in _INVALID_TITLE_PATTERNS:
        if pattern.match(title):
            return True
    return False


def _sanitize_title(raw: str) -> Optional[str]:
    """Sanitize a raw LLM response into a usable title string, or None if unusable.

    Pipeline (in order):
    1. JSON extraction  — if content has ``{`` and ``}`` try the find/rfind slice +
       ``json.loads`` + ``get('title')``.  Graceful transition: models that still
       return JSON are handled correctly until the plain-text prompt template
       rolls out everywhere.  If JSON parse succeeds but the title field is
       empty / missing / non-string, return ``None`` immediately — DO NOT fall
       through to plain-text, or the raw JSON envelope text ``{"title": ""}``
       would leak into the sidebar (regression seen in the wild 2026-04-22).
    2. Plain-text sanitization — strip whitespace, strip surrounding quotes,
       drop a leading ``title:`` prefix, truncate to 80 chars.
    3. Invalidity rejection (LAST) — ``_looks_invalid_title`` runs on the FINAL
       sanitized string, AFTER prefix/quote/truncate steps.  Ordering is
       load-bearing: ``'Title: Session on Recipes'`` → strip prefix →
       ``'Session on Recipes'`` → not invalid → accepted.
    """
    if not raw:
        return None

    candidate = raw.strip()

    # Step 1 — JSON extraction (graceful mid-deploy transition)
    # A candidate that starts with '{' is treated as a JSON envelope attempt
    # (model trying to comply with the old JSON prompt). Strictly require a
    # valid non-empty title string; any failure → reject outright. Never fall
    # through, since raw envelope text like `{"title": ""}` would sneak past
    # Step 3's invalidity patterns and leak into the sidebar.
    if candidate.startswith('{'):
        if not candidate.endswith('}'):
            return None  # truncated / incomplete JSON
        try:
            parsed = json.loads(candidate)
        except Exception:
            return None  # malformed JSON envelope
        if not isinstance(parsed, dict):
            return None
        extracted = parsed.get('title', '')
        if not isinstance(extracted, str) or not extracted.strip():
            return None  # envelope parsed but title empty / missing / wrong type
        candidate = extracted.strip()
    elif '{' in candidate and '}' in candidate:
        # Embedded JSON in prose — best-effort extraction, fall through on failure
        json_slice = candidate[candidate.find('{') : candidate.rfind('}') + 1]
        try:
            parsed = json.loads(json_slice)
            if isinstance(parsed, dict):
                extracted = parsed.get('title', '')
                if isinstance(extracted, str) and extracted.strip():
                    candidate = extracted.strip()
        except Exception:
            pass  # fall through to plain-text path

    # Step 2 — Plain-text sanitization
    # Strip one layer of surrounding quotes
    if len(candidate) >= 2 and candidate[0] in ('"', "'") and candidate[-1] == candidate[0]:
        candidate = candidate[1:-1].strip()

    # Drop "title:" / "Title:" prefix (case-insensitive, first 6 chars)
    if candidate.lower().startswith('title:'):
        candidate = candidate[6:].strip()

    # Truncate to 80 chars
    if len(candidate) > 80:
        candidate = candidate[:77] + '...'

    # Step 3 — Invalidity rejection (runs on the FINAL sanitized string)
    if _looks_invalid_title(candidate):
        return None

    return candidate or None


# ──────────────────────────────────────────────────────────────────────────────


def get_event_emitter_and_caller(metadata):
    event_emitter = None
    event_caller = None
    if (
        'session_id' in metadata
        and metadata['session_id']
        and 'chat_id' in metadata
        and metadata['chat_id']
        and 'message_id' in metadata
        and metadata['message_id']
    ):
        event_emitter = get_event_emitter(metadata)
        event_caller = get_event_call(metadata)
    return event_emitter, event_caller


def build_chat_response_context(request, form_data, user, model, metadata, tasks, events):
    event_emitter, event_caller = get_event_emitter_and_caller(metadata)
    return {
        'request': request,
        'form_data': form_data,
        'user': user,
        'model': model,
        'metadata': metadata,
        'tasks': tasks,
        'events': events,
        'event_emitter': event_emitter,
        'event_caller': event_caller,
    }


async def background_tasks_handler(ctx):
    import time as _time
    from opentelemetry import trace as _otel_trace

    request = ctx['request']
    form_data = ctx['form_data']
    user = ctx['user']
    metadata = ctx['metadata']
    tasks = ctx['tasks']
    event_emitter = ctx['event_emitter']

    _chat_id = (metadata or {}).get('chat_id', '-')
    _msg_id = (metadata or {}).get('message_id', '-')
    _bt0 = _time.monotonic()
    _tracer = _otel_trace.get_tracer('myah.background_tasks')
    log.info('[CHAT_PIPELINE] step=bg_tasks_start chat_id=%s message_id=%s', _chat_id, _msg_id)

    message = None
    messages = []

    if metadata.get('chat_id') and not metadata['chat_id'].startswith('local:'):
        messages_map = Chats.get_messages_map_by_chat_id(metadata['chat_id'])
        message = messages_map.get(metadata['message_id']) if messages_map else None

        message_list = get_message_list(messages_map, metadata['message_id'])

        # Remove details tags and files from the messages.
        # as get_message_list creates a new list, it does not affect
        # the original messages outside of this handler

        messages = []
        for message in message_list:
            content = message.get('content', '')
            if isinstance(content, list):
                for item in content:
                    if item.get('type') == 'text':
                        content = item['text']
                        break

            if isinstance(content, str):
                content = re.sub(
                    r'<details\b[^>]*>.*?<\/details>|!\[.*?\]\(.*?\)',
                    '',
                    content,
                    flags=re.S | re.I,
                ).strip()

            messages.append(
                {
                    **message,
                    'role': message.get('role', 'assistant'),  # Safe fallback for missing role
                    'content': content,
                }
            )
    else:
        # Local temp chat, get the model and message from the form_data
        message = get_last_user_message_item(form_data.get('messages', []))
        messages = form_data.get('messages', [])
        if message:
            message['model'] = form_data.get('model')

    if message and 'model' in message:
        # UI action messages (button clicks, form submits) don't need background
        # enrichment — skip title/tags/follow-ups entirely for them.
        if metadata.get('is_agui_action'):
            return

        if tasks and messages:
            # ── Run all three background LLM tasks concurrently ────────────────
            # Previously they ran sequentially, adding ~12s after the agent
            # finished. asyncio.gather fires them in parallel so the total wait
            # is the slowest single task, not the sum.

            async def _run_follow_ups():
                if not (TASKS.FOLLOW_UP_GENERATION in tasks and tasks[TASKS.FOLLOW_UP_GENERATION]):
                    return
                _t = _time.monotonic()
                _model = message['model']
                with _tracer.start_as_current_span('chat.bg.follow_ups') as _sp:
                    _sp.set_attribute('model', _model)
                    _sp.set_attribute('chat_id', _chat_id)
                    res = await _fetch_follow_ups_via_aux(
                        request,
                        {
                            'model': message['model'],
                            'messages': messages,
                            'message_id': metadata['message_id'],
                            'chat_id': metadata['chat_id'],
                        },
                        user,
                    )
                def _parse_follow_ups(res: dict) -> list | None:
                    """Extract follow_ups list from an aux-call envelope, or None on failure."""
                    if not (res and isinstance(res, dict)):
                        return None
                    if len(res.get('choices', [])) != 1:
                        return None
                    response_message = res['choices'][0].get('message', {})
                    raw = response_message.get('content') or response_message.get('reasoning_content', '')
                    json_slice = raw[raw.find('{') : raw.rfind('}') + 1]
                    try:
                        return json.loads(json_slice).get('follow_ups') or None
                    except Exception:
                        return None

                follow_ups = _parse_follow_ups(res)

                # Retry without response_format for providers that ignore the JSON hint
                if follow_ups is None:
                    log.warning(
                        f'[CHAT_PIPELINE] step=follow_ups_parse_failed_retrying chat_id={_chat_id}'
                    )
                    retry_res = await _fetch_follow_ups_via_aux(
                        request,
                        {
                            'model': message['model'],
                            'messages': messages,
                            'message_id': metadata['message_id'],
                            'chat_id': metadata['chat_id'],
                        },
                        user,
                        response_format_override=None,
                    )
                    follow_ups = _parse_follow_ups(retry_res)

                if follow_ups is not None:
                    try:
                        await event_emitter(
                            {
                                'type': 'chat:message:follow_ups',
                                'data': {'follow_ups': follow_ups},
                            }
                        )
                        if not metadata.get('chat_id', '').startswith('local:'):
                            Chats.upsert_message_to_chat_by_id_and_message_id(
                                metadata['chat_id'],
                                metadata['message_id'],
                                {'followUps': follow_ups},
                            )
                    except Exception:
                        pass

            async def _run_title_and_tags():
                if metadata.get('chat_id', '').startswith('local:'):
                    return

                user_message = get_last_user_message(messages)
                if user_message and len(user_message) > 100:
                    user_message = user_message[:100] + '...'

                async def _run_title():
                    title = None
                    if TASKS.TITLE_GENERATION in tasks:
                        if tasks[TASKS.TITLE_GENERATION]:
                            _t = _time.monotonic()
                            _model = message['model']
                            with _tracer.start_as_current_span('chat.bg.title') as _sp:
                                _sp.set_attribute('model', _model)
                                _sp.set_attribute('chat_id', _chat_id)
                                res = await _fetch_title_via_aux(
                                    request,
                                    {
                                        'model': message['model'],
                                        'messages': messages,
                                        'chat_id': metadata['chat_id'],
                                    },
                                    user,
                                )
                            if res and isinstance(res, dict):
                                if len(res.get('choices', [])) == 1:
                                    response_message = res.get('choices', [])[0].get('message', {})
                                    raw_content = (
                                        response_message.get('content')
                                        or response_message.get('reasoning_content')
                                        or ''
                                    )
                                else:
                                    raw_content = ''
                                title = _sanitize_title(raw_content)
                                if title:
                                    Chats.update_chat_title_by_id(metadata['chat_id'], title, 'auto')
                                    await event_emitter({'type': 'chat:title', 'data': title})
                                else:
                                    log.warning(
                                        f'[CHAT_PIPELINE] step=title_sanitize_rejected chat_id={_chat_id} '
                                        f'raw_len={len(raw_content)}'
                                    )
                                    # Provisional title from PR 1a stays — do NOT fall back to messages[0]

                await _run_title()

            await asyncio.gather(_run_follow_ups(), _run_title_and_tags(), return_exceptions=True)

    log.info(
        '[CHAT_PIPELINE] step=bg_tasks_complete chat_id=%s total_duration_ms=%d',
        _chat_id,
        int((_time.monotonic() - _bt0) * 1000),
    )
