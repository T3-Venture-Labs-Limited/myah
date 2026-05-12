import time
import logging
import sys

from aiocache import cached
from typing import Any, Optional
import json

import uuid
import asyncio

from fastapi import Request, status
from starlette.responses import Response, StreamingResponse, JSONResponse


from open_webui.models.users import UserModel

from open_webui.socket.main import (
    sio,
    get_event_call,
    get_event_emitter,
)

from open_webui.routers.openai import (
    generate_chat_completion as generate_openai_chat_completion,
)

from open_webui.utils.models import get_all_models, check_model_access
from open_webui.env import GLOBAL_LOG_LEVEL, BYPASS_MODEL_ACCESS_CONTROL

logging.basicConfig(stream=sys.stdout, level=GLOBAL_LOG_LEVEL)
log = logging.getLogger(__name__)


# When the question has been asked, let silence not be the
# answer. But if the answer must wait, let it come honest.
async def generate_direct_chat_completion(
    request: Request,
    form_data: dict,
    user: Any,
    models: dict,
):
    log.info('generate_direct_chat_completion')

    metadata = form_data.pop('metadata', {})

    user_id = metadata.get('user_id')
    session_id = metadata.get('session_id')
    request_id = str(uuid.uuid4())  # Generate a unique request ID

    event_caller = get_event_call(metadata)

    channel = f'{user_id}:{session_id}:{request_id}'
    logging.info(f'WebSocket channel: {channel}')

    if form_data.get('stream'):
        q = asyncio.Queue()

        async def message_listener(sid, data):
            """
            Handle received socket messages and push them into the queue.
            """
            await q.put(data)

        # Register the listener
        sio.on(channel, message_listener)

        # Start processing chat completion in background
        res = await event_caller(
            {
                'type': 'request:chat:completion',
                'data': {
                    'form_data': form_data,
                    'model': models[form_data['model']],
                    'channel': channel,
                    'session_id': session_id,
                },
            }
        )

        log.info(f'res: {res}')

        if res.get('status', False):
            # Define a generator to stream responses
            async def event_generator():
                nonlocal q
                try:
                    while True:
                        data = await q.get()  # Wait for new messages
                        if isinstance(data, dict):
                            if 'done' in data and data['done']:
                                break  # Stop streaming when 'done' is received

                            yield f'data: {json.dumps(data)}\n\n'
                        elif isinstance(data, str):
                            if 'data:' in data:
                                yield f'{data}\n\n'
                            else:
                                yield f'data: {data}\n\n'
                except Exception as e:
                    log.debug(f'Error in event generator: {e}')
                    pass

            # Define a background task to run the event generator
            async def background():
                try:
                    del sio.handlers['/'][channel]
                except Exception as e:
                    pass

            # Return the streaming response
            return StreamingResponse(event_generator(), media_type='text/event-stream', background=background)
        else:
            raise Exception(str(res))
    else:
        res = await event_caller(
            {
                'type': 'request:chat:completion',
                'data': {
                    'form_data': form_data,
                    'model': models[form_data['model']],
                    'channel': channel,
                    'session_id': session_id,
                },
            }
        )

        if 'error' in res and res['error']:
            raise Exception(res['error'])

        return res


async def generate_chat_completion(
    request: Request,
    form_data: dict,
    user: Any,
    bypass_filter: bool = False,
    bypass_system_prompt: bool = False,
):
    log.debug(f'generate_chat_completion: {form_data}')
    if BYPASS_MODEL_ACCESS_CONTROL:
        bypass_filter = True

    # Propagate bypass_filter via request.state so that downstream route
    # handlers (openai/ollama) can read it without exposing it as a query param.
    request.state.bypass_filter = bypass_filter

    if hasattr(request.state, 'metadata'):
        if 'metadata' not in form_data:
            form_data['metadata'] = request.state.metadata
        else:
            form_data['metadata'] = {
                **form_data['metadata'],
                **request.state.metadata,
            }

    if getattr(request.state, 'direct', False) and hasattr(request.state, 'model'):
        models = {
            request.state.model['id']: request.state.model,
        }
        log.debug(f'direct connection to model: {models}')
    else:
        models = request.app.state.MODELS

    model_id = form_data['model']

    # ── Myah: interactive chat bypasses MODELS registry (T3-932) ──────────────
    # User-selected provider models (from getProviderModels — openrouter,
    # openai, anthropic, google) don't live in the admin-curated MODELS
    # registry. For interactive chat (non-background-task), synthesize a
    # minimal model dict so routing continues to openai.py, which itself
    # routes through the Myah gateway container.
    #
    # Background tasks (title/tags/follow-ups) still require model_id to
    # exist in MODELS so they can find a proper connection.
    form_metadata = form_data.get('metadata') or {}
    is_myah_interactive = not bool(form_metadata.get('task'))

    if model_id in models:
        model = models[model_id]
    elif is_myah_interactive:
        # Synthesize placeholder; Hermes gateway resolves the real provider.
        model = {'id': model_id, 'owned_by': 'myah', 'connection_type': 'myah'}
    else:
        raise Exception('Model not found')
    # ─────────────────────────────────────────────────────────────────────────

    if getattr(request.state, 'direct', False):
        return await generate_direct_chat_completion(request, form_data, user=user, models=models)
    else:
        # Check if user has access to the model — only for admin-registered models.
        # Provider-catalog models (not in MODELS) are gated by the container's
        # llm_env injection (user can only use providers they've connected).
        if not bypass_filter and user.role == 'user' and model_id in models:
            try:
                check_model_access(user, model)
            except Exception as e:
                raise e

        return await generate_openai_chat_completion(
            request=request,
            form_data=form_data,
            user=user,
            bypass_system_prompt=bypass_system_prompt,
        )


chat_completion = generate_chat_completion


async def chat_completed(request: Request, form_data: dict, user: Any):
    if not request.app.state.MODELS:
        await get_all_models(request, user=user)

    if getattr(request.state, 'direct', False) and hasattr(request.state, 'model'):
        models = {
            request.state.model['id']: request.state.model,
        }
    else:
        models = request.app.state.MODELS

    data = form_data
    model_id = data['model']

    # ── Myah: interactive chat bypasses MODELS registry (T3-932) ──────────────
    # User-selected provider models (z-ai/glm-5.1, anthropic/*, etc.) don't
    # live in the admin-curated MODELS registry. The outlet pipeline is a
    # no-op in the Myah fork, so we don't need a model dict — just skip the
    # "not in MODELS" check and pass through. See utils/chat.py::
    # generate_chat_completion for the same pattern on the request side.
    # ─────────────────────────────────────────────────────────────────────────

    return data
