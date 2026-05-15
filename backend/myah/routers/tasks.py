from fastapi import APIRouter, Depends, status, Request
from fastapi.responses import JSONResponse

from pydantic import BaseModel
import json
import logging

from myah.utils.task import (
    title_generation_template,
    follow_up_generation_template,
)
from myah.utils.auth import get_verified_user

# ── Myah: aux routing for title/follow-up generation ──────────────────
from myah.utils.agent_proxy import aux_call
from shared.contract import AuxTask
# ──────────────────────────────────────────────────────────────────────

from myah.config import (
    DEFAULT_TITLE_GENERATION_PROMPT_TEMPLATE,
    DEFAULT_FOLLOW_UP_GENERATION_PROMPT_TEMPLATE,
)

log = logging.getLogger(__name__)

# ── Myah: sentinel for response_format_override on follow-up aux calls ────────
# Distinguishes "caller didn't pass anything" (keep default json_object hint)
# from "caller explicitly wants the key omitted" (retry-without-format path).
# Using a module-level object() avoids collision with any dict or None value.
_UNSET = object()
# ──────────────────────────────────────────────────────────────────────────────

router = APIRouter()


##################################
#
# Task Endpoints
#
##################################


class ActiveChatsForm(BaseModel):
    chat_ids: list[str]


@router.post('/active/chats')
async def check_active_chats(request: Request, form_data: ActiveChatsForm, user=Depends(get_verified_user)):
    """Check which chat IDs have active tasks."""
    from myah.tasks import get_active_chat_ids

    active = await get_active_chat_ids(request.app.state.redis, form_data.chat_ids)
    return {'active_chat_ids': active}


# ── Myah: aux-routed title and follow-up generation ───────────────────


def _empty_completion_envelope(content: str = '') -> dict:
    """Return an OpenAI-shaped chat-completion envelope with a given content string.

    The frontend callers (generateTitle, generateFollowUps) expect
    ``res.choices[0].message.content`` to be a JSON string they parse. When the
    aux call fails we still have to emit a well-formed envelope so the client
    fail-soft path ("no title") fires cleanly instead of throwing.
    """
    return {'choices': [{'message': {'role': 'assistant', 'content': content}}]}


async def _fetch_title_via_aux(request, form_data, user) -> dict:
    """Fetch title from Hermes aux router; return a plain dict.

    In-process callers (chat_tasks.py) need a dict so the ``isinstance(res, dict)``
    guard evaluates True and the title-parse block actually runs. The HTTP shim
    below wraps this in ``JSONResponse`` for the external route.
    """
    messages = form_data.get('messages', [])
    if request is not None and hasattr(request, 'app'):
        cfg = request.app.state.config
        template = cfg.TITLE_GENERATION_PROMPT_TEMPLATE or DEFAULT_TITLE_GENERATION_PROMPT_TEMPLATE
    else:
        template = DEFAULT_TITLE_GENERATION_PROMPT_TEMPLATE

    content = title_generation_template(template, messages, user)

    result = await aux_call(
        user,
        'POST',
        f'/myah/v1/aux/{AuxTask.TITLE_GENERATION.value}',
        json_body={
            'messages': [{'role': 'user', 'content': content}],
            'max_tokens': 160,
        },
        # 45s accommodates p95 latency for Chinese-hosted providers (Z.AI, MiniMax)
        # observed in the wild. 20s was causing ~20-40% aux failures with glm-5.1
        # under normal network conditions. Aux runs in the background AFTER the
        # main chat response is delivered, so the user doesn't wait on this.
        timeout=45.0,
    )

    if result['status'] != 200:
        log.warning('Title aux call failed (status=%s)', result['status'])
        return _empty_completion_envelope(json.dumps({'title': ''}))

    body = result.get('body') or {}
    if isinstance(body, dict) and body.get('choices'):
        return body

    # Aux endpoint returned a non-standard body — fail-soft.
    log.warning('Title aux call returned unexpected body shape: %r', type(body).__name__)
    return _empty_completion_envelope(json.dumps({'title': ''}))


async def _aux_generate_title(request, form_data, user):
    """HTTP shim: wraps _fetch_title_via_aux in JSONResponse for the router endpoint."""
    envelope = await _fetch_title_via_aux(request, form_data, user)
    return JSONResponse(status_code=status.HTTP_200_OK, content=envelope)


async def _fetch_follow_ups_via_aux(
    request,
    form_data,
    user,
    *,
    response_format_override=_UNSET,
) -> dict:
    """Fetch follow-ups from Hermes aux router; return a plain dict.

    Sibling to _fetch_title_via_aux — same dict-vs-JSONResponse split so the
    isinstance guard in chat_tasks.py evaluates True for follow-ups too.

    Args:
        response_format_override: Sentinel-controlled.
            _UNSET (default)     → include ``response_format: {json_object}`` as usual.
            None                 → omit ``response_format`` key entirely (retry-without-format path).
            dict                 → use the supplied dict as ``response_format``.
    """
    messages = form_data.get('messages', [])
    if request is not None and hasattr(request, 'app'):
        cfg = request.app.state.config
        template = cfg.FOLLOW_UP_GENERATION_PROMPT_TEMPLATE or DEFAULT_FOLLOW_UP_GENERATION_PROMPT_TEMPLATE
    else:
        template = DEFAULT_FOLLOW_UP_GENERATION_PROMPT_TEMPLATE

    content = follow_up_generation_template(template, messages, user)

    json_body: dict = {
        'messages': [{'role': 'user', 'content': content}],
        'max_tokens': 512,
    }
    if response_format_override is _UNSET:
        json_body['response_format'] = {'type': 'json_object'}
    elif response_format_override is None:
        pass  # omit response_format entirely
    else:
        json_body['response_format'] = response_format_override

    result = await aux_call(
        user,
        'POST',
        f'/myah/v1/aux/{AuxTask.FOLLOW_UP_GENERATION.value}',
        json_body=json_body,
        # 45s — see title_generation timeout rationale above. Follow-ups also
        # account for the retry-without-format path in _run_follow_ups, so a
        # generous first-attempt budget reduces the need to retry.
        timeout=45.0,
    )

    if result['status'] != 200:
        log.warning('Follow-up aux call failed (status=%s)', result['status'])
        return _empty_completion_envelope(json.dumps({'follow_ups': []}))

    body = result.get('body') or {}
    if isinstance(body, dict) and body.get('choices'):
        return body

    log.warning('Follow-up aux call returned unexpected body shape: %r', type(body).__name__)
    return _empty_completion_envelope(json.dumps({'follow_ups': []}))


async def _aux_generate_follow_ups(request, form_data, user):
    """HTTP shim: wraps _fetch_follow_ups_via_aux in JSONResponse for the router endpoint."""
    envelope = await _fetch_follow_ups_via_aux(request, form_data, user)
    return JSONResponse(status_code=status.HTTP_200_OK, content=envelope)


# ──────────────────────────────────────────────────────────────────────


@router.post('/title/completions')
async def generate_title(request: Request, form_data: dict, user=Depends(get_verified_user)):
    if not request.app.state.config.ENABLE_TITLE_GENERATION:
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={'detail': 'Title generation is disabled'},
        )
    return await _aux_generate_title(request, form_data, user)


@router.post('/follow_up/completions')
async def generate_follow_ups(request: Request, form_data: dict, user=Depends(get_verified_user)):
    if not request.app.state.config.ENABLE_FOLLOW_UP_GENERATION:
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={'detail': 'Follow-up generation is disabled'},
        )
    return await _aux_generate_follow_ups(request, form_data, user)
