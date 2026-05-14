import asyncio
import json
import logging
import re
import time
from typing import Optional
from urllib.parse import urlparse

from opentelemetry import trace as _otel_trace

import aiohttp
from aiocache import cached
import requests

from azure.identity import DefaultAzureCredential, get_bearer_token_provider

from fastapi import Depends, HTTPException, Request, APIRouter
from fastapi.responses import (
    StreamingResponse,
    JSONResponse,
    PlainTextResponse,
)
from pydantic import BaseModel, ConfigDict

from sqlalchemy.orm import Session

from myah.internal.db import get_session

from myah.models.models import Models
from myah.models.access_grants import AccessGrants
from myah.models.chats import Chats
from myah.models.files import Files
from myah.models.groups import Groups
from myah.env import (
    MODELS_CACHE_TTL,
    AIOHTTP_CLIENT_SESSION_SSL,
    AIOHTTP_CLIENT_TIMEOUT,
    AIOHTTP_CLIENT_TIMEOUT_MODEL_LIST,
    ENABLE_FORWARD_USER_INFO_HEADERS,
    FORWARD_SESSION_INFO_HEADER_CHAT_ID,
    BYPASS_MODEL_ACCESS_CONTROL,
)
from myah.models.users import UserModel

from myah.constants import ERROR_MESSAGES, TASKS

# Container Manager — per-user routing to Hermes agent containers
from myah.routers.containers import (
    AGENT_BEARER_TOKEN,
    _gateway_url,
    get_or_create_container,
)

from myah.utils.payload import (
    apply_model_params_to_body_openai,
    apply_system_prompt_to_body,
)
from myah.utils.misc import (
    cleanup_response,
    convert_logit_bias_input_to_json,
    stream_chunks_handler,
    stream_wrapper,
)

from myah.utils.auth import get_admin_user, get_verified_user
from myah.utils.headers import include_user_info_headers
from myah.utils.anthropic import is_anthropic_url, get_anthropic_models
from myah.utils.hermes_routing import resolve_user_agent_base
from shared.contract import ApprovalOption

log = logging.getLogger(__name__)

# ── Myah slash-command interception ──────────────────────────────────────────
# /new and /reset are Hermes session-reset commands that have no meaning on the
# Myah web platform. On Myah, each chat IS its own persistent Hermes session —
# "start fresh" means clicking "New Chat" in the sidebar, not resetting context
# in place. We catch these exact commands before they reach the agent and return
# a friendly redirect instead.
_MYAH_INTERCEPTED_RESET_COMMANDS: frozenset[str] = frozenset({'/new', '/reset'})
_MYAH_NEW_CHAT_REDIRECT: str = (
    '[System: The user typed a session-reset command that is not supported '
    'on the Myah web platform. On Myah, new conversations are started by '
    'clicking "New Chat" in the sidebar — each chat has its own persistent '
    'session. Please tell the user to create a new chat from the sidebar if '
    'they want to start a fresh conversation.]'
)


def _apply_myah_command_interception(text: str) -> str:
    """Rewrite Hermes session-reset commands for the Myah platform.

    /new and /reset have no meaning on Myah — each chat is already its own
    persistent session. Intercept them before they reach the agent and return
    a redirect message instead.
    """
    if text.strip().lower() in _MYAH_INTERCEPTED_RESET_COMMANDS:
        return _MYAH_NEW_CHAT_REDIRECT
    return text


# ── Myah: attachment bridging ────────────────────────────────────────────────
# Walk the chat payload and extract file references as lightweight metadata
# dicts (file_id + mime_type + size). No base64 — the agent fetches raw bytes
# from the file store when it needs them.

_MYAH_MAX_PER_FILE = 20 * 1024 * 1024  # 20 MB
_MYAH_MAX_TOTAL = 80 * 1024 * 1024  # 80 MB


def _file_id_from_url(url: str | None) -> str | None:
    """Extract a file ID from '/api/v1/files/{id}/content' or '/api/v1/files/{id}/'."""
    if not url:
        return None
    if url.startswith('/api/v1/files/'):
        remainder = url[len('/api/v1/files/') :]
        return remainder.split('/', 1)[0] or None
    # bare ID: no slashes, short, not a data URL
    if '/' not in url and len(url) < 64 and not url.startswith('data:'):
        return url
    return None


def _extract_model_provider(payload: dict) -> str | None:
    """Extract the provider tag the frontend attaches to each model.

    Every chat-completion POST ships `model_item` as shaped by the
    frontend model switcher; `_fetch_provider_models` at users.py:956-958
    tags each entry as ``tags=[{'name': <provider_id>}]`` (e.g.
    ``openai-codex``, ``anthropic-claude-code``, ``openrouter``).

    Returns the first tag name if present and well-formed; ``None``
    otherwise. Keeping this in a helper so the provider-forwarding path
    in the /myah/v1/message handler stays unit-testable without having
    to mock aiohttp.
    """
    model_item = payload.get('model_item') or {}
    if not isinstance(model_item, dict):
        return None
    tags = model_item.get('tags') or []
    if not isinstance(tags, list) or not tags:
        return None
    first = tags[0]
    if not isinstance(first, dict):
        return None
    name = first.get('name')
    if isinstance(name, str) and name.strip():
        return name.strip()
    return None


def _build_myah_attachments(payload: dict, user) -> list[dict]:
    """Walk payload.files[] and payload.messages[].content[].image_url parts,
    resolve each to a FileModel, and return a deduped list of
    {file_id, filename, mime_type, size} dicts.

    Enforces per-file (20 MB) and aggregate (80 MB) size caps.
    Files not found are silently skipped (deleted between upload and send).
    """
    seen: set[str] = set()
    out: list[dict] = []

    def _add(file_id: str) -> None:
        if file_id in seen:
            return
        model = Files.get_file_by_id(file_id)
        if not model:
            # Operationally useful — flags deleted-between-upload-and-send
            # and malformed file_ids coming off the wire.
            log.warning(f'[CHAT_PIPELINE] attachment_file_not_found: file_id={file_id!r}')
            return
        size = int((model.meta or {}).get('size') or 0)
        if size > _MYAH_MAX_PER_FILE:
            raise HTTPException(
                status_code=413,
                detail=f'{model.filename} exceeds 20 MB per-file limit',
            )
        out.append(
            {
                'file_id': model.id,
                'filename': model.filename,
                'mime_type': (model.meta or {}).get('content_type') or 'application/octet-stream',
                'size': size,
            }
        )
        seen.add(file_id)

    # 1. top-level files[] (documents, text, collections)
    for f in payload.get('files') or []:
        fid = f.get('id')
        if fid:
            _add(fid)

    # 2. image_url content parts inside messages (images are attached as
    # OpenAI-vision-style content parts by Chat.svelte, NOT in files[]).
    for msg in payload.get('messages') or []:
        content = msg.get('content')
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict) or part.get('type') != 'image_url':
                continue
            url = (part.get('image_url') or {}).get('url') or ''
            fid = _file_id_from_url(url)
            if fid:
                _add(fid)
            elif url and not url.startswith('data:'):
                # A URL we can't resolve to a file_id — log so we see broken
                # pipelines if middleware ever starts rewriting image URLs
                # again (the bug that caused T3-1001).
                log.warning(f'[CHAT_PIPELINE] image_url_part_unresolved: url_prefix={url[:80]!r}')

    total = sum(a['size'] for a in out)
    if total > _MYAH_MAX_TOTAL:
        raise HTTPException(
            status_code=413,
            detail='Total attachments exceed 80 MB per-message limit',
        )
    return out


# ─────────────────────────────────────────────────────────────────────────────

##########################################
#
# Utility functions
# Let the responses returned through this gate be worth
# the question that summoned them.
#
##########################################


async def send_get_request(
    request: Request = None,
    url=None,
    key=None,
    user: UserModel = None,
    config=None,
):
    timeout = aiohttp.ClientTimeout(total=AIOHTTP_CLIENT_TIMEOUT_MODEL_LIST)
    try:
        async with aiohttp.ClientSession(timeout=timeout, trust_env=True) as session:
            if request and config:
                headers, cookies = await get_headers_and_cookies(request, url, key, config, user=user)
            else:
                headers = {
                    **({'Authorization': f'Bearer {key}'} if key else {}),
                }
                cookies = None

                if ENABLE_FORWARD_USER_INFO_HEADERS and user:
                    headers = include_user_info_headers(headers, user)

            async with session.get(
                url,
                headers=headers,
                cookies=cookies,
                ssl=AIOHTTP_CLIENT_SESSION_SSL,
            ) as response:
                return await response.json()
    except Exception as e:
        # Handle connection error here
        log.error(f'Connection error: {e}')
        return None


async def get_models_request(
    request: Request = None,
    url=None,
    key=None,
    user: UserModel = None,
    config=None,
):
    if is_anthropic_url(url):
        return await get_anthropic_models(url, key, user=user)
    return await send_get_request(request, f'{url}/models', key, user=user, config=config)


def openai_reasoning_model_handler(payload):
    """
    Handle reasoning model specific parameters
    """
    if 'max_tokens' in payload:
        # Convert "max_tokens" to "max_completion_tokens" for all reasoning models
        payload['max_completion_tokens'] = payload['max_tokens']
        del payload['max_tokens']

    # Handle system role conversion based on model type
    if payload['messages'][0]['role'] == 'system':
        model_lower = payload['model'].lower()
        # Legacy models use "user" role instead of "system"
        if model_lower.startswith('o1-mini') or model_lower.startswith('o1-preview'):
            payload['messages'][0]['role'] = 'user'
        else:
            payload['messages'][0]['role'] = 'developer'

    return payload


async def get_headers_and_cookies(
    request: Request,
    url,
    key=None,
    config=None,
    metadata: Optional[dict] = None,
    user: UserModel = None,
):
    cookies = {}
    headers = {
        'Content-Type': 'application/json',
        **(
            {
                'HTTP-Referer': 'https://myah.dev/',
                'X-Title': 'Myah',
            }
            if 'openrouter.ai' in url
            else {}
        ),
    }

    # Propagate Sentry distributed trace context so the agent container's
    # Sentry SDK can link its spans back to the originating frontend trace.
    # This is manual because aiohttp client requests are not auto-instrumented.
    try:
        import sentry_sdk

        _span = sentry_sdk.get_current_span()
        if _span is not None:
            headers['sentry-trace'] = _span.to_traceparent()
            _baggage = sentry_sdk.get_baggage()
            if _baggage is not None:  # get_baggage() returns None when no baggage is active
                headers['baggage'] = _baggage
    except Exception:
        pass  # Sentry not configured or span not active — silently skip

    if ENABLE_FORWARD_USER_INFO_HEADERS and user:
        headers = include_user_info_headers(headers, user)
        if metadata and metadata.get('chat_id'):
            headers[FORWARD_SESSION_INFO_HEADER_CHAT_ID] = metadata.get('chat_id')

    token = None
    auth_type = config.get('auth_type')

    if auth_type == 'bearer' or auth_type is None:
        # Default to bearer if not specified
        token = f'{key}'
    elif auth_type == 'none':
        token = None
    elif auth_type == 'session':
        cookies = request.cookies
        token = request.state.token.credentials
    elif auth_type == 'system_oauth':
        cookies = request.cookies

        oauth_token = None
        try:
            if request.cookies.get('oauth_session_id', None):
                oauth_token = await request.app.state.oauth_manager.get_oauth_token(
                    user.id,
                    request.cookies.get('oauth_session_id', None),
                )
        except Exception as e:
            log.error(f'Error getting OAuth token: {e}')

        if oauth_token:
            token = f'{oauth_token.get("access_token", "")}'

    elif auth_type in ('azure_ad', 'microsoft_entra_id'):
        token = get_microsoft_entra_id_access_token()

    if token:
        headers['Authorization'] = f'Bearer {token}'

    if config.get('headers') and isinstance(config.get('headers'), dict):
        headers = {**headers, **config.get('headers')}

    return headers, cookies


def get_microsoft_entra_id_access_token():
    """
    Get Microsoft Entra ID access token using DefaultAzureCredential for Azure OpenAI.
    Returns the token string or None if authentication fails.
    """
    try:
        token_provider = get_bearer_token_provider(
            DefaultAzureCredential(), 'https://cognitiveservices.azure.com/.default'
        )
        return token_provider()
    except Exception as e:
        log.error(f'Error getting Microsoft Entra ID access token: {e}')
        return None


##########################################
#
# API routes
#
##########################################

router = APIRouter()


@router.get('/config')
async def get_config(request: Request, user=Depends(get_admin_user)):
    return {
        'ENABLE_OPENAI_API': request.app.state.config.ENABLE_OPENAI_API,
        'OPENAI_API_BASE_URLS': request.app.state.config.OPENAI_API_BASE_URLS,
        'OPENAI_API_KEYS': request.app.state.config.OPENAI_API_KEYS,
        'OPENAI_API_CONFIGS': request.app.state.config.OPENAI_API_CONFIGS,
    }


class OpenAIConfigForm(BaseModel):
    ENABLE_OPENAI_API: Optional[bool] = None
    OPENAI_API_BASE_URLS: list[str]
    OPENAI_API_KEYS: list[str]
    OPENAI_API_CONFIGS: dict


@router.post('/config/update')
async def update_config(request: Request, form_data: OpenAIConfigForm, user=Depends(get_admin_user)):
    request.app.state.config.ENABLE_OPENAI_API = form_data.ENABLE_OPENAI_API
    request.app.state.config.OPENAI_API_BASE_URLS = form_data.OPENAI_API_BASE_URLS
    request.app.state.config.OPENAI_API_KEYS = form_data.OPENAI_API_KEYS

    # Check if API KEYS length is same than API URLS length
    if len(request.app.state.config.OPENAI_API_KEYS) != len(request.app.state.config.OPENAI_API_BASE_URLS):
        if len(request.app.state.config.OPENAI_API_KEYS) > len(request.app.state.config.OPENAI_API_BASE_URLS):
            request.app.state.config.OPENAI_API_KEYS = request.app.state.config.OPENAI_API_KEYS[
                : len(request.app.state.config.OPENAI_API_BASE_URLS)
            ]
        else:
            request.app.state.config.OPENAI_API_KEYS += [''] * (
                len(request.app.state.config.OPENAI_API_BASE_URLS) - len(request.app.state.config.OPENAI_API_KEYS)
            )

    request.app.state.config.OPENAI_API_CONFIGS = form_data.OPENAI_API_CONFIGS

    # Remove the API configs that are not in the API URLS
    keys = list(map(str, range(len(request.app.state.config.OPENAI_API_BASE_URLS))))
    request.app.state.config.OPENAI_API_CONFIGS = {
        key: value for key, value in request.app.state.config.OPENAI_API_CONFIGS.items() if key in keys
    }

    return {
        'ENABLE_OPENAI_API': request.app.state.config.ENABLE_OPENAI_API,
        'OPENAI_API_BASE_URLS': request.app.state.config.OPENAI_API_BASE_URLS,
        'OPENAI_API_KEYS': request.app.state.config.OPENAI_API_KEYS,
        'OPENAI_API_CONFIGS': request.app.state.config.OPENAI_API_CONFIGS,
    }


async def get_all_models_responses(request: Request, user: UserModel) -> list:
    if not request.app.state.config.ENABLE_OPENAI_API:
        return []

    # Cache config values locally to avoid repeated Redis lookups.
    # Each access to request.app.state.config.<KEY> triggers a Redis GET;
    # caching here avoids hundreds of redundant round-trips.
    api_base_urls = request.app.state.config.OPENAI_API_BASE_URLS
    api_keys = list(request.app.state.config.OPENAI_API_KEYS)
    api_configs = request.app.state.config.OPENAI_API_CONFIGS

    # Check if API KEYS length is same than API URLS length
    num_urls = len(api_base_urls)
    num_keys = len(api_keys)

    if num_keys != num_urls:
        # if there are more keys than urls, remove the extra keys
        if num_keys > num_urls:
            api_keys = api_keys[:num_urls]
            request.app.state.config.OPENAI_API_KEYS = api_keys
        # if there are more urls than keys, add empty keys
        else:
            api_keys += [''] * (num_urls - num_keys)
            request.app.state.config.OPENAI_API_KEYS = api_keys

    request_tasks = []
    for idx, url in enumerate(api_base_urls):
        if (str(idx) not in api_configs) and (url not in api_configs):  # Legacy support
            request_tasks.append(get_models_request(request, url, api_keys[idx], user=user))
        else:
            api_config = api_configs.get(
                str(idx),
                api_configs.get(url, {}),  # Legacy support
            )

            enable = api_config.get('enable', True)
            model_ids = api_config.get('model_ids', [])

            if enable:
                if len(model_ids) == 0:
                    request_tasks.append(get_models_request(request, url, api_keys[idx], user=user, config=api_config))
                else:
                    model_list = {
                        'object': 'list',
                        'data': [
                            {
                                'id': model_id,
                                'name': model_id,
                                'owned_by': 'openai',
                                'openai': {'id': model_id},
                                'urlIdx': idx,
                            }
                            for model_id in model_ids
                        ],
                    }

                    request_tasks.append(asyncio.ensure_future(asyncio.sleep(0, model_list)))
            else:
                request_tasks.append(asyncio.ensure_future(asyncio.sleep(0, None)))

    responses = await asyncio.gather(*request_tasks)

    for idx, response in enumerate(responses):
        if response:
            url = api_base_urls[idx]
            api_config = api_configs.get(
                str(idx),
                api_configs.get(url, {}),  # Legacy support
            )

            connection_type = api_config.get('connection_type', 'external')
            prefix_id = api_config.get('prefix_id', None)
            tags = api_config.get('tags', [])

            model_list = response if isinstance(response, list) else response.get('data', [])
            if not isinstance(model_list, list):
                # Catch non-list responses
                model_list = []

            for model in model_list:
                # Remove name key if its value is None #16689
                if 'name' in model and model['name'] is None:
                    del model['name']

                if prefix_id:
                    model['id'] = f'{prefix_id}.{model.get("id", model.get("name", ""))}'

                if tags:
                    model['tags'] = tags

                if connection_type:
                    model['connection_type'] = connection_type

    log.debug(f'get_all_models:responses() {responses}')
    return responses


async def get_filtered_models(models, user, db=None):
    # Filter models based on user access control
    model_ids = [model['id'] for model in models.get('data', [])]
    model_infos = {model_info.id: model_info for model_info in Models.get_models_by_ids(model_ids, db=db)}
    user_group_ids = {group.id for group in Groups.get_groups_by_member_id(user.id, db=db)}

    # Batch-fetch accessible resource IDs in a single query instead of N has_access calls
    accessible_model_ids = AccessGrants.get_accessible_resource_ids(
        user_id=user.id,
        resource_type='model',
        resource_ids=list(model_infos.keys()),
        permission='read',
        user_group_ids=user_group_ids,
        db=db,
    )

    filtered_models = []
    for model in models.get('data', []):
        model_info = model_infos.get(model['id'])
        if model_info:
            if user.id == model_info.user_id or model_info.id in accessible_model_ids:
                filtered_models.append(model)
    return filtered_models


@cached(
    ttl=MODELS_CACHE_TTL,
    key=lambda _, user: f'openai_all_models_{user.id}' if user else 'openai_all_models',
)
async def get_all_models(request: Request, user: UserModel) -> dict[str, list]:
    log.info('get_all_models()')

    if not request.app.state.config.ENABLE_OPENAI_API:
        return {'data': []}

    # Cache config value locally to avoid repeated Redis lookups inside
    # the nested loop in get_merged_models (one GET per model otherwise).
    api_base_urls = request.app.state.config.OPENAI_API_BASE_URLS

    responses = await get_all_models_responses(request, user=user)

    def extract_data(response):
        if response and 'data' in response:
            return response['data']
        if isinstance(response, list):
            return response
        return None

    def is_supported_openai_models(model_id):
        if any(
            name in model_id
            for name in [
                'babbage',
                'dall-e',
                'davinci',
                'embedding',
                'tts',
                'whisper',
            ]
        ):
            return False
        return True

    def get_merged_models(model_lists):
        log.debug(f'merge_models_lists {model_lists}')
        models = {}

        for idx, model_list in enumerate(model_lists):
            if model_list is not None and 'error' not in model_list:
                for model in model_list:
                    model_id = model.get('id') or model.get('name')

                    base_url = api_base_urls[idx]
                    hostname = urlparse(base_url).hostname if base_url else None
                    if hostname == 'api.openai.com' and not is_supported_openai_models(model_id):
                        # Skip unwanted OpenAI models
                        continue

                    if model_id and model_id not in models:
                        models[model_id] = {
                            **model,
                            'name': model.get('name', model_id),
                            'owned_by': 'openai',
                            'openai': model,
                            'connection_type': model.get('connection_type', 'external'),
                            'urlIdx': idx,
                        }

        return models

    models = get_merged_models(map(extract_data, responses))
    log.debug(f'models: {models}')

    request.app.state.OPENAI_MODELS = models
    return {'data': list(models.values())}


@router.get('/models')
@router.get('/models/{url_idx}')
async def get_models(request: Request, url_idx: Optional[int] = None, user=Depends(get_verified_user)):
    if not request.app.state.config.ENABLE_OPENAI_API:
        raise HTTPException(status_code=503, detail='OpenAI API is disabled')

    models = {
        'data': [],
    }

    if url_idx is None:
        models = await get_all_models(request, user=user)
    else:
        url = request.app.state.config.OPENAI_API_BASE_URLS[url_idx]
        key = request.app.state.config.OPENAI_API_KEYS[url_idx]

        api_config = request.app.state.config.OPENAI_API_CONFIGS.get(
            str(url_idx),
            request.app.state.config.OPENAI_API_CONFIGS.get(url, {}),  # Legacy support
        )

        r = None
        async with aiohttp.ClientSession(
            trust_env=True,
            timeout=aiohttp.ClientTimeout(total=AIOHTTP_CLIENT_TIMEOUT_MODEL_LIST),
        ) as session:
            try:
                headers, cookies = await get_headers_and_cookies(request, url, key, api_config, user=user)

                if api_config.get('azure', False):
                    models = {
                        'data': api_config.get('model_ids', []) or [],
                        'object': 'list',
                    }
                elif is_anthropic_url(url):
                    models = await get_anthropic_models(url, key, user=user)
                    if models is None:
                        raise Exception('Failed to connect to Anthropic API')
                else:
                    async with session.get(
                        f'{url}/models',
                        headers=headers,
                        cookies=cookies,
                        ssl=AIOHTTP_CLIENT_SESSION_SSL,
                    ) as r:
                        if r.status != 200:
                            error_detail = f'HTTP Error: {r.status}'
                            try:
                                res = await r.json()
                                if 'error' in res:
                                    error_detail = f'External Error: {res["error"]}'
                            except Exception:
                                pass
                            raise Exception(error_detail)

                        response_data = await r.json()

                        if 'api.openai.com' in url:
                            response_data['data'] = [
                                model
                                for model in response_data.get('data', [])
                                if not any(
                                    name in model['id']
                                    for name in [
                                        'babbage',
                                        'dall-e',
                                        'davinci',
                                        'embedding',
                                        'tts',
                                        'whisper',
                                    ]
                                )
                            ]

                        models = response_data
            except aiohttp.ClientError as e:
                # ClientError covers all aiohttp requests issues
                log.exception(f'Client error: {str(e)}')
                raise HTTPException(status_code=500, detail='Myah: Server Connection Error')
            except Exception as e:
                log.exception(f'Unexpected error: {e}')
                error_detail = f'Unexpected error: {str(e)}'
                raise HTTPException(status_code=500, detail=error_detail)

    if user.role == 'user' and not BYPASS_MODEL_ACCESS_CONTROL:
        models['data'] = await get_filtered_models(models, user)

    return models


class ConnectionVerificationForm(BaseModel):
    url: str
    key: str

    config: Optional[dict] = None


@router.post('/verify')
async def verify_connection(
    request: Request,
    form_data: ConnectionVerificationForm,
    user=Depends(get_admin_user),
):
    url = form_data.url
    key = form_data.key

    api_config = form_data.config or {}

    async with aiohttp.ClientSession(
        trust_env=True,
        timeout=aiohttp.ClientTimeout(total=AIOHTTP_CLIENT_TIMEOUT_MODEL_LIST),
    ) as session:
        try:
            headers, cookies = await get_headers_and_cookies(request, url, key, api_config, user=user)

            if api_config.get('azure', False):
                # Only set api-key header if not using Azure Entra ID authentication
                auth_type = api_config.get('auth_type', 'bearer')
                if auth_type not in ('azure_ad', 'microsoft_entra_id'):
                    headers['api-key'] = key

                api_version = api_config.get('api_version', '') or '2023-03-15-preview'
                async with session.get(
                    url=f'{url}/openai/models?api-version={api_version}',
                    headers=headers,
                    cookies=cookies,
                    ssl=AIOHTTP_CLIENT_SESSION_SSL,
                ) as r:
                    try:
                        response_data = await r.json()
                    except Exception:
                        response_data = await r.text()

                    if r.status != 200:
                        if isinstance(response_data, (dict, list)):
                            return JSONResponse(status_code=r.status, content=response_data)
                        else:
                            return PlainTextResponse(status_code=r.status, content=response_data)

                    return response_data
            elif is_anthropic_url(url):
                result = await get_anthropic_models(url, key)
                if result is None:
                    raise HTTPException(status_code=500, detail='Failed to connect to Anthropic API')
                if 'error' in result:
                    raise HTTPException(status_code=500, detail=result['error'])
                return result
            else:
                async with session.get(
                    f'{url}/models',
                    headers=headers,
                    cookies=cookies,
                    ssl=AIOHTTP_CLIENT_SESSION_SSL,
                ) as r:
                    try:
                        response_data = await r.json()
                    except Exception:
                        response_data = await r.text()

                    if r.status != 200:
                        if isinstance(response_data, (dict, list)):
                            return JSONResponse(status_code=r.status, content=response_data)
                        else:
                            return PlainTextResponse(status_code=r.status, content=response_data)

                    return response_data

        except aiohttp.ClientError as e:
            # ClientError covers all aiohttp requests issues
            log.exception(f'Client error: {str(e)}')
            raise HTTPException(status_code=500, detail='Myah: Server Connection Error')
        except Exception as e:
            log.exception(f'Unexpected error: {e}')
            raise HTTPException(status_code=500, detail='Myah: Server Connection Error')


def get_azure_allowed_params(api_version: str) -> set[str]:
    allowed_params = {
        'messages',
        'temperature',
        'role',
        'content',
        'contentPart',
        'contentPartImage',
        'enhancements',
        'dataSources',
        'n',
        'stream',
        'stop',
        'max_tokens',
        'presence_penalty',
        'frequency_penalty',
        'logit_bias',
        'user',
        'function_call',
        'functions',
        'tools',
        'tool_choice',
        'top_p',
        'log_probs',
        'top_logprobs',
        'response_format',
        'seed',
        'max_completion_tokens',
        'reasoning_effort',
    }

    try:
        if api_version >= '2024-09-01-preview':
            allowed_params.add('stream_options')
    except ValueError:
        log.debug(f'Invalid API version {api_version} for Azure OpenAI. Defaulting to allowed parameters.')

    return allowed_params


def is_openai_new_model(model: str) -> bool:
    model_lower = model.lower()
    # o-series models (o1, o3, o4, o5, ...)
    if re.match(r'^o\d+', model_lower):
        return True
    # gpt-N where N >= 5 (gpt-5, gpt-5.2, gpt-6, ...)
    m = re.match(r'^gpt-(\d+)', model_lower)
    if m and int(m.group(1)) >= 5:
        return True
    return False


def convert_to_azure_payload(url, payload: dict, api_version: str):
    model = payload.get('model', '')

    # Filter allowed parameters based on Azure OpenAI API
    allowed_params = get_azure_allowed_params(api_version)

    # Special handling for o-series models
    if is_openai_new_model(model):
        # Convert max_tokens to max_completion_tokens for o-series models
        if 'max_tokens' in payload:
            payload['max_completion_tokens'] = payload['max_tokens']
            del payload['max_tokens']

        # Remove temperature if not 1 for o-series models
        if 'temperature' in payload and payload['temperature'] != 1:
            log.debug(
                f'Removing temperature parameter for o-series model {model} as only default value (1) is supported'
            )
            del payload['temperature']

    # Filter out unsupported parameters
    payload = {k: v for k, v in payload.items() if k in allowed_params}

    url = f'{url}/openai/deployments/{model}'
    return url, payload


# Fields accepted by the Responses API for each input item type.
RESPONSES_ALLOWED_FIELDS: dict[str, set[str]] = {
    'message': {'type', 'role', 'content'},
    'function_call': {'type', 'call_id', 'name', 'arguments', 'id'},
    'function_call_output': {'type', 'call_id', 'output'},
}


def _normalize_stored_item(item: dict) -> dict:
    """Strip local-only fields from a stored output item before replaying it.

    Myah stores extra bookkeeping fields (``id``, ``status``,
    ``started_at``, ``ended_at``, ``duration``, ``_tag_type``,
    ``attributes``, ``summary``, etc.) that the Responses API does
    not accept.  This helper returns a copy containing only the
    fields the API understands.
    """
    item_type = item.get('type', '')
    allowed = RESPONSES_ALLOWED_FIELDS.get(item_type)
    if allowed is None:
        # Unknown type — pass through as-is (e.g. reasoning, extension items).
        return item
    return {k: v for k, v in item.items() if k in allowed}


def convert_to_responses_payload(payload: dict) -> dict:
    """
    Convert Chat Completions payload to Responses API format.

    Chat Completions: { messages: [{role, content}], ... }
    Responses API: { input: [{type: "message", role, content: [...]}], instructions: "system" }
    """
    messages = payload.pop('messages', [])

    system_content = ''
    input_items = []

    for msg in messages:
        role = msg.get('role', 'user')
        content = msg.get('content', '')

        # Check for stored output items (from previous Responses API turn)
        stored_output = msg.get('output')
        if stored_output and isinstance(stored_output, list):
            input_items.extend(_normalize_stored_item(item) for item in stored_output)
            continue

        if role == 'system':
            if isinstance(content, str):
                system_content = content
            elif isinstance(content, list):
                system_content = '\n'.join(p.get('text', '') for p in content if p.get('type') == 'text')
            continue

        # Handle assistant messages with tool_calls (from convert_output_to_messages)
        if role == 'assistant' and msg.get('tool_calls'):
            # Add text content as message if present
            if content:
                text = (
                    content
                    if isinstance(content, str)
                    else '\n'.join(p.get('text', '') for p in content if p.get('type') == 'text')
                )
                if text.strip():
                    input_items.append(
                        {
                            'type': 'message',
                            'role': 'assistant',
                            'content': [{'type': 'output_text', 'text': text}],
                        }
                    )
            # Convert each tool_call to a function_call input item
            for tool_call in msg['tool_calls']:
                func = tool_call.get('function', {})
                input_items.append(
                    {
                        'type': 'function_call',
                        'call_id': tool_call.get('id', ''),
                        'name': func.get('name', ''),
                        'arguments': func.get('arguments', '{}'),
                    }
                )
            continue

        # Handle tool result messages
        if role == 'tool':
            input_items.append(
                {
                    'type': 'function_call_output',
                    'call_id': msg.get('tool_call_id', ''),
                    'output': msg.get('content', ''),
                }
            )
            continue

        # Convert content format
        text_type = 'output_text' if role == 'assistant' else 'input_text'

        if isinstance(content, str):
            content_parts = [{'type': text_type, 'text': content}]
        elif isinstance(content, list):
            content_parts = []
            for part in content:
                if part.get('type') == 'text':
                    content_parts.append({'type': text_type, 'text': part.get('text', '')})
                elif part.get('type') == 'image_url':
                    url_data = part.get('image_url', {})
                    url = url_data.get('url', '') if isinstance(url_data, dict) else url_data
                    content_parts.append({'type': 'input_image', 'image_url': url})
        else:
            content_parts = [{'type': text_type, 'text': str(content)}]

        input_items.append({'type': 'message', 'role': role, 'content': content_parts})

    responses_payload = {**payload, 'input': input_items}

    # Forward previous_response_id when the middleware has set it
    # (only used when ENABLE_RESPONSES_API_STATEFUL is enabled).
    previous_response_id = responses_payload.pop('previous_response_id', None)
    if previous_response_id:
        responses_payload['previous_response_id'] = previous_response_id

    if system_content:
        responses_payload['instructions'] = system_content

    if 'max_tokens' in responses_payload:
        responses_payload['max_output_tokens'] = responses_payload.pop('max_tokens')

    if 'max_completion_tokens' in responses_payload:
        responses_payload['max_output_tokens'] = responses_payload.pop('max_completion_tokens')

    # Remove Chat Completions-only parameters not supported by the Responses API
    for unsupported_key in (
        'stream_options',
        'logit_bias',
        'frequency_penalty',
        'presence_penalty',
        'stop',
    ):
        responses_payload.pop(unsupported_key, None)

    # Convert Chat Completions tools format to Responses API format
    # Chat Completions: {"type": "function", "function": {"name": ..., "description": ..., "parameters": ...}}
    # Responses API:    {"type": "function", "name": ..., "description": ..., "parameters": ...}
    if 'tools' in responses_payload and isinstance(responses_payload['tools'], list):
        converted_tools = []
        for tool in responses_payload['tools']:
            if isinstance(tool, dict) and 'function' in tool:
                func = tool['function']
                converted_tool = {'type': tool.get('type', 'function')}
                if isinstance(func, dict):
                    converted_tool['name'] = func.get('name', '')
                    if 'description' in func:
                        converted_tool['description'] = func['description']
                    if 'parameters' in func:
                        converted_tool['parameters'] = func['parameters']
                    if 'strict' in func:
                        converted_tool['strict'] = func['strict']
                converted_tools.append(converted_tool)
            else:
                # Already in correct format or unknown format, pass through
                converted_tools.append(tool)
        responses_payload['tools'] = converted_tools

    return responses_payload


def convert_responses_result(response: dict) -> dict:
    """
    Convert non-streaming Responses API result to Chat Completions format.

    Extracts text from message output items so all downstream consumers
    (frontend tasks, get_content_from_response) work without modification.
    """
    output_items = response.get('output', [])

    content = ''
    for item in output_items:
        if item.get('type') == 'message':
            for part in item.get('content', []):
                if part.get('type') == 'output_text':
                    content += part.get('text', '')

    return {
        'id': response.get('id', ''),
        'object': 'chat.completion',
        'model': response.get('model', ''),
        'choices': [
            {
                'index': 0,
                'message': {
                    'role': 'assistant',
                    'content': content,
                },
                'finish_reason': 'stop',
            }
        ],
        'usage': response.get('usage', {}),
    }


@router.post('/chat/completions')
async def generate_chat_completion(
    request: Request,
    form_data: dict,
    user=Depends(get_verified_user),
    bypass_system_prompt: bool = False,
):
    # NOTE: We intentionally do NOT use Depends(get_session) here.
    # Database operations (get_model_by_id, AccessGrants.has_access) manage their own short-lived sessions.
    # This prevents holding a connection during the entire LLM call (30-60+ seconds),
    # which would exhaust the connection pool under concurrent load.

    # bypass_filter is read from request.state to prevent external clients from
    # setting it via query parameter (CVE fix). Only internal server-side callers
    # (e.g. utils/chat.py) should set request.state.bypass_filter = True.
    bypass_filter = getattr(request.state, 'bypass_filter', False)
    if BYPASS_MODEL_ACCESS_CONTROL:
        bypass_filter = True

    idx = 0

    payload = {**form_data}
    metadata = payload.pop('metadata', None)

    model_id = form_data.get('model')

    # ── Interactive vs. background task routing ───────────────────────────────
    # Interactive chat (non-background-task) always routes through the Myah
    # gateway adapter (/myah/v1/message), which uses the user's per-container
    # Hermes process. Hermes resolves the provider (openrouter/openai/anthropic/
    # google) from its own config + per-user env vars injected at container
    # startup. So the model id can be ANY model the user has access to via
    # their connected providers — it doesn't need to live in OPENAI_MODELS.
    #
    # Background tasks (title/tags/follow-ups) still use admin-configured
    # OpenAI-compatible connections and require model_id ∈ OPENAI_MODELS.
    #
    # This aligns us with Hermes's gateway-first architecture: model routing
    # is the gateway's job, not ours.
    _metadata_early = payload.get('metadata') or {}
    _is_bg_task_early = bool(_metadata_early.get('task'))

    # The Myah Models registry is for admin-curated model overrides (system
    # prompts, params). Background tasks use it; interactive chat skips it and
    # lets the Hermes gateway resolve everything from its own config.
    if _is_bg_task_early:
        model_info = Models.get_model_by_id(model_id)
    else:
        model_info = None

    # Check model info and override the payload
    if model_info:
        if model_info.base_model_id:
            base_model_id = (
                request.base_model_id if hasattr(request, 'base_model_id') else model_info.base_model_id
            )  # Use request's base_model_id if available
            payload['model'] = base_model_id
            model_id = base_model_id

        params = model_info.params.model_dump()

        if params:
            system = params.pop('system', None)

            payload = apply_model_params_to_body_openai(params, payload)
            if not bypass_system_prompt:
                payload = apply_system_prompt_to_body(system, payload, metadata, user)

        # Check if user has access to the model
        if not bypass_filter and user.role == 'user':
            user_group_ids = {group.id for group in Groups.get_groups_by_member_id(user.id)}
            if not (
                user.id == model_info.user_id
                or AccessGrants.has_access(
                    user_id=user.id,
                    resource_type='model',
                    resource_id=model_info.id,
                    permission='read',
                    user_group_ids=user_group_ids,
                )
            ):
                raise HTTPException(
                    status_code=403,
                    detail='Model not found',
                )
    elif not bypass_filter and _is_bg_task_early and model_id != 'myah':
        # Only gate background tasks against admin-curated registry. Interactive
        # chat gates are handled in the Myah container, not here.
        if user.role != 'admin':
            raise HTTPException(
                status_code=403,
                detail='Model not found',
            )

    # ── Model resolution ──────────────────────────────────────────────────────
    # Interactive chat: use a placeholder. The URL/key are overridden below by
    # per-user container routing, and the model id is passed through to Hermes
    # in the myah_payload. Hermes resolves the actual provider.
    #
    # Background tasks: look up in OPENAI_MODELS (admin-configured connections)
    # so title/tag/follow-up generation uses the configured upstream.
    if not _is_bg_task_early:
        model = {'id': model_id or 'myah', 'urlIdx': 0, 'owned_by': 'myah'}
        idx = 0
    else:
        # Check if model is already in app state cache to avoid expensive get_all_models() call
        models = request.app.state.OPENAI_MODELS
        if not models or model_id not in models:
            await get_all_models(request, user=user)
            models = request.app.state.OPENAI_MODELS
        model = models.get(model_id)

        if model:
            idx = model['urlIdx']
        else:
            raise HTTPException(
                status_code=404,
                detail='Model not found',
            )
    # ─────────────────────────────────────────────────────────────────────────

    # Get the API config for the model
    # Guard against empty OPENAI_API_BASE_URLS list (e.g. when only 'myah' model is used)
    base_urls = request.app.state.config.OPENAI_API_BASE_URLS
    api_config = {}
    if base_urls and idx < len(base_urls):
        api_config = request.app.state.config.OPENAI_API_CONFIGS.get(
            str(idx),
            request.app.state.config.OPENAI_API_CONFIGS.get(base_urls[idx], {}),
        )

    prefix_id = api_config.get('prefix_id', None)
    if prefix_id:
        payload['model'] = payload['model'].replace(f'{prefix_id}.', '')

    # Add user info to the payload if the model is a pipeline
    if 'pipeline' in model and model.get('pipeline'):
        payload['user'] = {
            'name': user.name,
            'id': user.id,
            'email': user.email,
            'role': user.role,
        }

    url = base_urls[idx] if base_urls and idx < len(base_urls) else ''
    api_keys = request.app.state.config.OPENAI_API_KEYS
    key = api_keys[idx] if api_keys and idx < len(api_keys) else ''

    # ── Per-user container routing ────────────────────────────────────────────
    # ALL interactive chat routes to the user's personal Hermes container via
    # the Myah gateway adapter (/myah/v1/message), regardless of model id.
    # The Container Manager wakes a hibernated container if needed. Status
    # events are emitted to the frontend so the user sees "Waking up your
    # agent..." during cold starts.
    #
    # The payload's model field is passed through to the Hermes gateway, which
    # resolves the provider (openrouter/openai/anthropic/google) from its own
    # config + the per-user env vars injected at container startup.
    #
    # ── Myah: narrow bg-task skip ─────────────────────────────────────────
    # Background tasks that still use admin-configured TASK_MODEL_EXTERNAL
    # (tags/queries/autocomplete/emoji) MUST bypass the Myah gateway — the
    # gateway returns SSE text/event-stream and callers expect a JSON
    # completion body. Title and follow-up generation route through
    # /myah/v1/aux/* before reaching this function, so they never hit here.
    _bg_task_name = str((metadata or {}).get('task') or '')
    _SKIP_MYAH_TASKS = {
        str(TASKS.TAGS_GENERATION),
        str(TASKS.QUERY_GENERATION),
        str(TASKS.AUTOCOMPLETE_GENERATION),
        str(TASKS.EMOJI_GENERATION),
        str(TASKS.IMAGE_PROMPT_GENERATION),
    }
    _skip_myah_gateway = _bg_task_name in _SKIP_MYAH_TASKS
    # ──────────────────────────────────────────────────────────────────────
    if not _skip_myah_gateway:
        from myah.socket.main import get_event_emitter

        _chat_id = (metadata or {}).get('chat_id', '-')
        _msg_id = (metadata or {}).get('message_id', '-')
        _tracer = _otel_trace.get_tracer('myah.myah')
        _t0 = time.monotonic()

        log.info(
            '[CHAT_PIPELINE] step=myah_request_received chat_id=%s message_id=%s',
            _chat_id,
            _msg_id,
        )

        event_emitter = get_event_emitter(metadata) if metadata else None
        # Extract the user-selected model before the try block so it is always
        # in scope even if exception-handling paths evolve to reference it.
        _user_selected_model = str(payload.get('model') or '').strip()
        try:
            with _tracer.start_as_current_span('myah.container_check') as _cs:
                _cs.set_attribute('chat_id', _chat_id)
                record = await get_or_create_container(user.id, event_emitter=event_emitter)
                _cs.set_attribute('host_port', record.host_port or 0)

            _t_container = time.monotonic()
            log.info(
                '[CHAT_PIPELINE] step=container_ready chat_id=%s port=%s elapsed_ms=%d',
                _chat_id,
                record.host_port,
                int((_t_container - _t0) * 1000),
            )

            # Tier 2A standalone-runner: /myah/v1/* lives on a separate
            # aiohttp app on AGENT_GATEWAY_PORT. Pre-Tier-2A rows fall back
            # to host_port via the `or` so chat keeps working through cutover.
            url = _gateway_url(record.gateway_port or record.host_port)
            key = AGENT_BEARER_TOKEN
            # Preserve the user-selected provider model in the payload so
            # downstream code (and observability) can see what was picked.
            # The Myah adapter ignores payload['model'] for routing; the
            # actual per-session model override flows through the new
            # PUT /myah/api/sessions/{id}/model endpoint (T3-932).
            if _user_selected_model == 'myah':
                # The virtual 'myah' id means "no explicit model selected —
                # use the agent's default".  Drop it so nothing surprising
                # surfaces in payload metadata.
                payload.pop('model', None)
            payload.setdefault('metadata', {}).update(
                {
                    'session_id': metadata.get('chat_id', '') if metadata else '',
                    'user_id': user.id if user else '',
                    'chat_id': metadata.get('chat_id', '') if metadata else '',
                    'message_id': metadata.get('message_id', '') if metadata else '',
                }
            )
            # Emit immediately so the frontend shows activity before the Hermes
            # HTTP request even leaves the backend.  Without this the user sees
            # nothing during Honcho session init + the first LLM tool-call phase
            # (~3–7 s for render_ui responses), making the agent feel frozen.
            if event_emitter:
                await event_emitter(
                    {
                        'type': 'status',
                        'data': {'description': 'Thinking...', 'done': False},
                    }
                )

            log.info(
                '[CHAT_PIPELINE] step=hermes_call_start chat_id=%s elapsed_ms=%d',
                _chat_id,
                int((time.monotonic() - _t0) * 1000),
            )
        except HTTPException:
            raise
        except Exception as exc:
            log.exception(f'Container Manager failed for user {user.id}: {exc}')
            raise HTTPException(status_code=503, detail='Agent container unavailable')

        # ── Myah Gateway Adapter (/myah/v1/message) ────────────────────────────
        # Route messages through the Hermes gateway's myah platform adapter.
        # This gives us all 30 slash commands, agent caching per session,
        # skill nudge accumulation, voice transcription, and image auto-analysis
        # — the full gateway experience that /v1/runs never provided.
        #
        # Two-phase flow:
        #   1. POST /myah/v1/message  → 202 {stream_id, session_id}
        #   2. GET  /myah/v1/events/{stream_id} → SSE stream
        #
        # The adapter's _handle_message() dispatches through the gateway
        # pipeline, so slash commands (e.g. /model, /compress) are handled
        # natively before they ever reach the agent.

        # Extract the last user message from the OpenAI-format payload.
        # Content can be a plain string or a list of content parts.
        _last_user_text = ''
        for _msg in reversed(payload.get('messages', [])):
            if _msg.get('role') == 'user':
                _content = _msg.get('content', '')
                if isinstance(_content, list):
                    _last_user_text = ' '.join(part.get('text', '') for part in _content if isinstance(part, dict))
                else:
                    _last_user_text = str(_content)
                break

        # Intercept Hermes session-reset commands that have no meaning on the Myah
        # web platform. On Myah, each chat is its own persistent session — "new session"
        # means creating a new chat from the sidebar, not resetting context in place.
        _last_user_text = _apply_myah_command_interception(_last_user_text)

        _session_id = metadata.get('chat_id', '') if metadata else ''
        myah_payload: dict = {
            'message': _last_user_text,
            'session_id': _session_id,
            'user_id': user.id if user else '',
        }
        if user and user.name:
            myah_payload['user_name'] = user.name
        # Pass chat name if available in metadata for session display
        _chat_name = metadata.get('chat_name', '') if metadata else ''
        if _chat_name:
            myah_payload['chat_name'] = _chat_name

        # ── Myah: forward ui_state from form_data to myah_payload (Phase 4B) ──
        # Per artifact pane redesign spec §7. The frontend assembles a per-turn
        # ui_state object (selectionRefs + pendingEdits) describing what the
        # user is currently looking at; the Hermes adapter lifts this into the
        # ephemeral channel_prompt so the agent receives editor context as a
        # [CURRENT_UI_STATE] block without polluting the cached system prompt.
        #
        # 2026-05-05 dogfooding: until hermes-agent#17 lands, the Hermes Myah
        # adapter ignores ``ui_state`` entirely — the agent sees only the
        # raw message text and never knows what the user highlighted. Bridge
        # the gap by reading the same ui_state HERE and prepending a
        # [USER_REFERENCED] block to ``_last_user_text`` (which becomes
        # ``myah_payload['message']`` below). When #17 ships, drop the
        # ``prepend_user_ref_block`` call and let channel_prompt carry the
        # context cache-cheaply.
        ui_state = form_data.get('ui_state')
        if ui_state:
            myah_payload['ui_state'] = ui_state
            log.info(f'[MYAH] ui_state forwarded ({len(json.dumps(ui_state))} chars)')
        from myah.utils.ui_state import prepend_user_ref_block
        _last_user_text = prepend_user_ref_block(_last_user_text, ui_state)
        myah_payload['message'] = _last_user_text
        # ──────────────────────────────────────────────────────────────────────

        # ── Myah: forward attachments unconditionally (baseline behavior) ─────────────
        # Files can arrive in two shapes:
        #   1. Top-level `files`/`metadata.files` (documents, text, collections) — the frontend
        #      sends these for non-image file types. middleware.py pops `files` from the payload
        #      into `metadata['files']` before this function runs, so check both.
        #   2. `messages[].content[].image_url` — the frontend sends IMAGES as OpenAI-vision-format
        #      content parts (MessageInput.svelte:553 sets `file.url = file.id`, Chat.svelte:1834-1839
        #      converts them to `image_url` parts), NOT in the top-level `files` array.
        # `_build_myah_attachments` walks both locations and returns [] when neither has anything,
        # so call it unconditionally and gate forwarding on the returned list.
        _payload_for_attachments = payload
        _files_from_metadata = (metadata or {}).get('files') or []
        if _files_from_metadata and not payload.get('files'):
            _payload_for_attachments = {**payload, 'files': _files_from_metadata}

        _payload_files_count = len(payload.get('files') or [])
        _image_url_parts_count = sum(
            1
            for msg in payload.get('messages') or []
            if isinstance(msg.get('content'), list)
            for part in msg['content']
            if isinstance(part, dict) and part.get('type') == 'image_url'
        )
        log.info(
            f'[CHAT_PIPELINE] attachment_check: payload_files={_payload_files_count} '
            f'metadata_files={len(_files_from_metadata)} image_url_parts={_image_url_parts_count}'
        )

        try:
            _attachments = _build_myah_attachments(_payload_for_attachments, user)
            log.info(f'[CHAT_PIPELINE] attachment_build: built={len(_attachments)} attachments')
            if _attachments:
                myah_payload['attachments'] = _attachments  # target: myah_payload, not payload
                # ── Myah: link uploaded files to chat in ChatFile table ──────────────────
                if metadata and metadata.get('chat_id') and metadata.get('message_id'):
                    try:
                        Chats.insert_chat_files(
                            chat_id=metadata['chat_id'],
                            message_id=metadata['message_id'],
                            file_ids=[a['file_id'] for a in _attachments],
                            user_id=user.id,
                        )
                    except Exception as _cf_exc:
                        log.warning(f'[CHAT_FILES] failed to link user-uploaded files to chat: {_cf_exc}')
                        try:
                            import sentry_sdk

                            sentry_sdk.add_breadcrumb(
                                category='chat_files',
                                level='warning',
                                data={'error': str(_cf_exc)},
                            )
                        except Exception:
                            pass
                # ────────────────────────────────────────────────────────────────────────
        except HTTPException:
            raise  # Honor FastAPI error contract (413 for size limits, 400 for bad file ids)
        except Exception as exc:
            log.warning(
                f'[CHAT_PIPELINE] attachment forwarding failed: {exc}',
                exc_info=True,
            )
            try:
                import sentry_sdk  # Local import matches the pattern at existing sentry usages

                sentry_sdk.add_breadcrumb(
                    category='attachments',
                    level='warning',
                    data={
                        'error': str(exc),
                        'file_count': _payload_files_count + len(_files_from_metadata) + _image_url_parts_count,
                    },
                )
            except Exception:
                pass  # Sentry optional — breadcrumb is best-effort
        # ────────────────────────────────────────────────────────────────────────────

        # ── Myah: per-message model override (T3-932) ───────────────
        # Forward the user's currently selected model as a one-shot
        # override. Primary session override mechanism is
        # PUT /myah/api/sessions/{id}/model (called by the
        # frontend when the selector changes), but this body field is
        # the correct fallback when: (a) the session override hasn't
        # been applied yet (very first message in a chat), (b) the
        # selection changed racily after the PUT and before this POST.
        if _user_selected_model and _user_selected_model != 'myah':
            myah_payload['model'] = _user_selected_model
            # Also forward the provider tag so Hermes switch_model pins
            # the target provider instead of running auto-detect (which
            # falls back to OpenRouter for OAuth-only providers like
            # openai-codex / anthropic-claude-code where the env-var
            # heuristic in PROVIDER_REGISTRY cannot find matching creds).
            # The frontend ships model_item in every chat-completion POST;
            # _fetch_provider_models at users.py:956-958 tags each model
            # as tags=[{'name': <provider_id>}].
            _myah_provider = _extract_model_provider(payload)
            if _myah_provider:
                myah_payload['provider'] = _myah_provider
        # ───────────────────────────────────────────────────────────

        # 2026-05-05 dogfooding: also log the first 200 chars of the message
        # AND whether the [USER_REFERENCED] sentinel made it through. This is
        # the canonical answer to "did the agent see the user's selection?"
        # — the frontend prepends the block to the wire content; if the
        # sentinel isn't here, the injection failed somewhere upstream of
        # this point.
        _msg_preview = _last_user_text[:200].replace('\n', '\\n')
        _has_user_ref = '[USER_REFERENCED]' in _last_user_text
        log.info(
            '[CHAT_PIPELINE] /myah/v1/message payload: session_id=%s user_id=%s model=%r provider=%r message_len=%d has_user_ref=%s msg_preview=%r',
            _session_id,
            myah_payload.get('user_id', ''),
            myah_payload.get('model'),
            myah_payload.get('provider'),
            len(_last_user_text),
            _has_user_ref,
            _msg_preview,
        )

        # url = http://host:port/v1  →  strip the trailing /v1 to get the agent base
        _agent_base = resolve_user_agent_base(url)
        _myah_msg_url = f'{_agent_base}/myah/v1/message'
        _bearer = f'Bearer {key}' if key else ''
        _req_headers = {'Content-Type': 'application/json'}
        if _bearer:
            _req_headers['Authorization'] = _bearer

        # Propagate Sentry distributed trace so the agent container's
        # sentry_trace_middleware can continue the trace and link all
        # agent/tool spans back to the originating browser request.
        # Same pattern as get_headers_and_cookies() at line 168-181.
        try:
            import sentry_sdk as _sentry_sdk

            _current_span = _sentry_sdk.get_current_span()
            if _current_span is not None:
                _req_headers['sentry-trace'] = _current_span.to_traceparent()
                _sentry_baggage = _sentry_sdk.get_baggage()
                if _sentry_baggage is not None:
                    _req_headers['baggage'] = _sentry_baggage
        except Exception:
            pass  # Sentry not configured — silently skip

        _myah_session = aiohttp.ClientSession(
            trust_env=True,
            timeout=aiohttp.ClientTimeout(total=AIOHTTP_CLIENT_TIMEOUT),
        )
        try:
            # Phase 1: dispatch message through the gateway adapter
            _start_resp = await _myah_session.post(
                _myah_msg_url,
                json=myah_payload,
                headers=_req_headers,
                ssl=AIOHTTP_CLIENT_SESSION_SSL,
            )
            if _start_resp.status != 202:
                _err_body = await _start_resp.text()
                await _myah_session.close()
                log.error(
                    '[CHAT_PIPELINE] /myah/v1/message failed: status=%s chat_id=%s body=%s',
                    _start_resp.status,
                    _chat_id,
                    _err_body[:500],
                )
                raise HTTPException(
                    status_code=_start_resp.status,
                    detail=f'Agent message dispatch failed: {_err_body[:200]}',
                )

            _start_data = await _start_resp.json()
            _stream_id = _start_data.get('stream_id')
            if not _stream_id:
                await _myah_session.close()
                raise HTTPException(status_code=502, detail='Agent returned no stream_id')

            # Capture Hermes session.id mapping into chat.hermes_session_id.
            # Vanilla Hermes echoes whatever session_id the platform sent (which
            # is chat_id), so the fallback below populates the column to its
            # current-equivalent value. A future Hermes-side change can return
            # a distinct ``hermes_session_id`` field (e.g. after compression
            # rotation) without requiring a platform-side capture change.
            # Failure is non-fatal: the send still succeeds, reads keep working
            # because chat.id == hermes session.id by convention until the
            # mapping is populated.
            _hermes_session_id = _start_data.get('hermes_session_id') or _start_data.get('session_id')
            if _hermes_session_id and metadata and metadata.get('chat_id'):
                try:
                    Chats.set_hermes_session_id(
                        chat_id=metadata['chat_id'],
                        hermes_session_id=_hermes_session_id,
                        user_id=user.id,
                    )
                except Exception as exc:
                    log.warning(f'[CHAT_PIPELINE] failed to persist hermes_session_id: {exc}')

            log.info(
                '[CHAT_PIPELINE] step=stream_started chat_id=%s stream_id=%s elapsed_ms=%d',
                _chat_id,
                _stream_id,
                int((time.monotonic() - _t0) * 1000),
            )

            # Phase 2: stream events — session is kept open and handed to
            # stream_wrapper, which closes both response and session on completion.
            _events_url = f'{_agent_base}/myah/v1/events/{_stream_id}'
            try:
                _events_resp = await _myah_session.get(
                    _events_url,
                    headers=_req_headers,
                    ssl=AIOHTTP_CLIENT_SESSION_SSL,
                )
            except Exception as e:
                await _myah_session.close()
                raise HTTPException(status_code=502, detail=f'Stream connection failed: {e}')

            if _events_resp.status != 200:
                _err_body = await _events_resp.text()
                await _myah_session.close()
                raise HTTPException(
                    status_code=_events_resp.status,
                    detail=f'Agent events stream failed: {_err_body[:200]}',
                )

            # Lifecycle heartbeat for the sidebar / Tasks page spinner. The
            # `chat:active` event drives `$activeChatIds` in the frontend
            # (`routes/+layout.svelte`) which the chat list and task list read
            # to render the "running" indicator. The legacy bg-task path in
            # `main.py` emits the same pair around `process_chat`; since the
            # Hermes-first flow doesn't go through there, we emit it here.
            # `update_db=False` because chat:active is not a persisted event
            # type — purely a transient socket signal.
            _lifecycle_emitter = (
                get_event_emitter(metadata, update_db=False)
                if metadata and metadata.get('chat_id') and metadata.get('user_id')
                else None
            )
            if _lifecycle_emitter:
                try:
                    await _lifecycle_emitter({'type': 'chat:active', 'data': {'active': True}})
                except Exception as _exc:
                    log.debug(f'[CHAT_PIPELINE] chat:active=true emit failed: {_exc}')

            async def _hermes_stream_with_lifecycle():
                # Wrap stream_wrapper so we always emit chat:active=false on
                # stream completion — including normal completion, agent
                # failure, client disconnect, and exceptions raised inside
                # the wrapped generator. stream_wrapper's own finally already
                # closes _events_resp + _myah_session via cleanup_response;
                # this wrapper layers the socket emit on top.
                try:
                    async for _chunk in stream_wrapper(_events_resp, _myah_session):
                        yield _chunk
                finally:
                    if _lifecycle_emitter:
                        try:
                            await _lifecycle_emitter({'type': 'chat:active', 'data': {'active': False}})
                        except Exception as _exc:
                            log.debug(f'[CHAT_PIPELINE] chat:active=false emit failed: {_exc}')

            return StreamingResponse(
                _hermes_stream_with_lifecycle(),
                status_code=200,
                headers={'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache'},
            )
        except HTTPException:
            raise
        except Exception as exc:
            await _myah_session.close()
            log.exception('[CHAT_PIPELINE] /myah/v1/message request failed chat_id=%s: %s', _chat_id, exc)
            raise HTTPException(status_code=502, detail='Agent message request failed')

    # ── Legacy /v1/runs routing (commented out for fallback reference) ────
    # The old two-phase /v1/runs flow is preserved here in case we need
    # to revert while the gateway adapter is being stabilized.
    #
    # messages = payload.get('messages', [])
    # instructions = None
    # conversation_history = []
    # for msg in messages:
    #     role = msg.get('role', '')
    #     content = msg.get('content', '')
    #     if isinstance(content, list):
    #         content = ' '.join(part.get('text', '') for part in content if isinstance(part, dict))
    #     if role == 'system':
    #         instructions = f'{instructions}\n{content}' if instructions else content
    #     elif role in ('user', 'assistant'):
    #         conversation_history.append({'role': role, 'content': content})
    # user_message = ''
    # if conversation_history:
    #     user_message = conversation_history[-1].get('content', '')
    #     conversation_history = conversation_history[:-1]
    # runs_payload: dict = {
    #     'input': user_message,
    #     'session_id': metadata.get('chat_id', '') if metadata else '',
    #     'metadata': {'chat_id': metadata.get('chat_id', '') if metadata else ''},
    # }
    # if instructions:
    #     runs_payload['instructions'] = instructions
    # if conversation_history:
    #     runs_payload['conversation_history'] = conversation_history
    # _user_model = await _resolve_user_model(user.id) if user else ''
    # if _user_model:
    #     runs_payload['model'] = _user_model
    # _runs_url = f'{_agent_base}/v1/runs'
    # ... (POST → run_id, GET → /v1/runs/{run_id}/events)
    # ── End legacy /v1/runs ───────────────────────────────────────────────
    # ─────────────────────────────────────────────────────────────────────────

    # Check if model is a reasoning model that needs special handling
    if is_openai_new_model(payload['model']):
        payload = openai_reasoning_model_handler(payload)
    elif 'api.openai.com' not in url:
        # Remove "max_completion_tokens" from the payload for backward compatibility
        if 'max_completion_tokens' in payload:
            payload['max_tokens'] = payload['max_completion_tokens']
            del payload['max_completion_tokens']

    if 'max_tokens' in payload and 'max_completion_tokens' in payload:
        del payload['max_tokens']

    # Convert the modified body back to JSON
    if 'logit_bias' in payload and payload['logit_bias']:
        logit_bias = convert_logit_bias_input_to_json(payload['logit_bias'])

        if logit_bias:
            payload['logit_bias'] = json.loads(logit_bias)

    headers, cookies = await get_headers_and_cookies(request, url, key, api_config, metadata, user=user)

    is_responses = api_config.get('api_type') == 'responses'

    if api_config.get('azure', False):
        api_version = api_config.get('api_version', '2023-03-15-preview')
        request_url, payload = convert_to_azure_payload(url, payload, api_version)

        # Only set api-key header if not using Azure Entra ID authentication
        auth_type = api_config.get('auth_type', 'bearer')
        if auth_type not in ('azure_ad', 'microsoft_entra_id'):
            headers['api-key'] = key

        headers['api-version'] = api_version

        if is_responses:
            payload = convert_to_responses_payload(payload)
            request_url = f'{request_url}/responses?api-version={api_version}'
        else:
            request_url = f'{request_url}/chat/completions?api-version={api_version}'
    else:
        if is_responses:
            payload = convert_to_responses_payload(payload)
            request_url = f'{url}/responses'
        else:
            request_url = f'{url}/chat/completions'
    # For Chat Completions, strip image parts from multimodal tool messages
    # (Chat Completions doesn't support images in tool content).
    if not is_responses and 'messages' in payload:
        for message in payload['messages']:
            if message.get('role') == 'tool' and isinstance(message.get('content'), list):
                message['content'] = ''.join(
                    part.get('text', '') for part in message['content'] if part.get('type') in ('input_text', 'text')
                )

    payload = json.dumps(payload)

    r = None
    session = None
    streaming = False
    response = None

    try:
        session = aiohttp.ClientSession(trust_env=True, timeout=aiohttp.ClientTimeout(total=AIOHTTP_CLIENT_TIMEOUT))

        r = await session.request(
            method='POST',
            url=request_url,
            data=payload,
            headers=headers,
            cookies=cookies,
            ssl=AIOHTTP_CLIENT_SESSION_SSL,
        )

        # Check if response is SSE
        if 'text/event-stream' in r.headers.get('Content-Type', ''):
            streaming = True
            return StreamingResponse(
                stream_wrapper(r, session, stream_chunks_handler),
                status_code=r.status,
                headers=dict(r.headers),
            )
        else:
            try:
                response = await r.json()
            except Exception as e:
                log.error(e)
                response = await r.text()

            if r.status >= 400:
                if isinstance(response, (dict, list)):
                    return JSONResponse(status_code=r.status, content=response)
                else:
                    return PlainTextResponse(status_code=r.status, content=response)

            # Convert Responses API result to simple format
            if is_responses and isinstance(response, dict):
                response = convert_responses_result(response)

            return response
    except Exception as e:
        log.exception(e)

        raise HTTPException(
            status_code=r.status if r else 500,
            detail='Myah: Server Connection Error',
        )
    finally:
        if not streaming:
            await cleanup_response(r, session)


async def embeddings(request: Request, form_data: dict, user):
    """
    Calls the embeddings endpoint for OpenAI-compatible providers.

    Args:
        request (Request): The FastAPI request context.
        form_data (dict): OpenAI-compatible embeddings payload.
        user (UserModel): The authenticated user.

    Returns:
        dict: OpenAI-compatible embeddings response.
    """
    idx = 0
    # Prepare payload/body
    body = json.dumps(form_data)
    # Find correct backend url/key based on model
    model_id = form_data.get('model')
    # Check if model is already in app state cache to avoid expensive get_all_models() call
    models = request.app.state.OPENAI_MODELS
    if not models or model_id not in models:
        await get_all_models(request, user=user)
        models = request.app.state.OPENAI_MODELS
    if model_id in models:
        idx = models[model_id]['urlIdx']

    url = request.app.state.config.OPENAI_API_BASE_URLS[idx]
    key = request.app.state.config.OPENAI_API_KEYS[idx]
    api_config = request.app.state.config.OPENAI_API_CONFIGS.get(
        str(idx),
        request.app.state.config.OPENAI_API_CONFIGS.get(url, {}),  # Legacy support
    )

    r = None
    session = None
    streaming = False

    headers, cookies = await get_headers_and_cookies(request, url, key, api_config, user=user)
    try:
        session = aiohttp.ClientSession(
            trust_env=True,
            timeout=aiohttp.ClientTimeout(total=AIOHTTP_CLIENT_TIMEOUT),
        )
        r = await session.request(
            method='POST',
            url=f'{url}/embeddings',
            data=body,
            headers=headers,
            cookies=cookies,
        )

        if 'text/event-stream' in r.headers.get('Content-Type', ''):
            streaming = True
            return StreamingResponse(
                stream_wrapper(r, session),
                status_code=r.status,
                headers=dict(r.headers),
            )
        else:
            try:
                response_data = await r.json()
            except Exception:
                response_data = await r.text()

            if r.status >= 400:
                if isinstance(response_data, (dict, list)):
                    return JSONResponse(status_code=r.status, content=response_data)
                else:
                    return PlainTextResponse(status_code=r.status, content=response_data)

            return response_data
    except Exception as e:
        log.exception(e)
        raise HTTPException(
            status_code=r.status if r else 500,
            detail='Myah: Server Connection Error',
        )
    finally:
        if not streaming:
            await cleanup_response(r, session)


class ResponsesForm(BaseModel):
    model_config = ConfigDict(extra='allow')

    model: str
    input: Optional[list | str] = None
    instructions: Optional[str] = None
    stream: Optional[bool] = None
    temperature: Optional[float] = None
    max_output_tokens: Optional[int] = None
    top_p: Optional[float] = None
    tools: Optional[list] = None
    tool_choice: Optional[str | dict] = None
    text: Optional[dict] = None
    truncation: Optional[str] = None
    metadata: Optional[dict] = None
    store: Optional[bool] = None
    reasoning: Optional[dict] = None
    previous_response_id: Optional[str] = None


@router.post('/responses')
async def responses(
    request: Request,
    form_data: ResponsesForm,
    user=Depends(get_verified_user),
):
    """
    Forward requests to the OpenAI Responses API endpoint.
    Routes to the correct upstream backend based on the model field.
    """
    payload = form_data.model_dump(exclude_none=True)
    body = json.dumps(payload)

    idx = 0
    model_id = form_data.model
    if model_id:
        models = request.app.state.OPENAI_MODELS
        if not models or model_id not in models:
            await get_all_models(request, user=user)
            models = request.app.state.OPENAI_MODELS
        if model_id in models:
            idx = models[model_id]['urlIdx']

    url = request.app.state.config.OPENAI_API_BASE_URLS[idx]
    key = request.app.state.config.OPENAI_API_KEYS[idx]
    api_config = request.app.state.config.OPENAI_API_CONFIGS.get(
        str(idx),
        request.app.state.config.OPENAI_API_CONFIGS.get(url, {}),  # Legacy support
    )

    r = None
    session = None
    streaming = False

    try:
        headers, cookies = await get_headers_and_cookies(request, url, key, api_config, user=user)

        if api_config.get('azure', False):
            api_version = api_config.get('api_version', '2023-03-15-preview')

            auth_type = api_config.get('auth_type', 'bearer')
            if auth_type not in ('azure_ad', 'microsoft_entra_id'):
                headers['api-key'] = key

            headers['api-version'] = api_version

            model = payload.get('model', '')
            request_url = f'{url}/openai/deployments/{model}/responses?api-version={api_version}'
        else:
            request_url = f'{url}/responses'

        session = aiohttp.ClientSession(
            trust_env=True,
            timeout=aiohttp.ClientTimeout(total=AIOHTTP_CLIENT_TIMEOUT),
        )
        r = await session.request(
            method='POST',
            url=request_url,
            data=body,
            headers=headers,
            cookies=cookies,
            ssl=AIOHTTP_CLIENT_SESSION_SSL,
        )

        # Check if response is SSE
        if 'text/event-stream' in r.headers.get('Content-Type', ''):
            streaming = True
            return StreamingResponse(
                stream_wrapper(r, session),
                status_code=r.status,
                headers=dict(r.headers),
            )
        else:
            try:
                response_data = await r.json()
            except Exception:
                response_data = await r.text()

            if r.status >= 400:
                if isinstance(response_data, (dict, list)):
                    return JSONResponse(status_code=r.status, content=response_data)
                else:
                    return PlainTextResponse(status_code=r.status, content=response_data)

            return response_data

    except Exception as e:
        log.exception(e)
        raise HTTPException(
            status_code=r.status if r else 500,
            detail='Myah: Server Connection Error',
        )
    finally:
        if not streaming:
            await cleanup_response(r, session)


@router.post('/chat/confirm')
async def confirm_chat_action(
    request: Request,
    user=Depends(get_verified_user),
):
    """Proxy a user's confirmation choice to the Hermes gateway adapter.

    Called by the frontend ConfirmationCard when the user clicks Approve / Deny.
    Routes through /myah/v1/confirm/{stream_id} on the gateway adapter.

    Body: ``{ run_id: str, confirmation_id?: str, choice: "approve" | "approve_session" | "deny" }``

    ``run_id`` is the gateway adapter's stream_id (kept for backcompat).
    ``confirmation_id`` (optional) lets the agent route action confirmations
    precisely; without it the agent falls back to resolving the oldest
    pending confirmation for the session_key bound to the stream.
    """
    body = await request.json()
    stream_id = body.get('run_id', '')
    confirmation_id = body.get('confirmation_id') or ''
    choice = body.get('choice', ApprovalOption.DENY.value)

    if not stream_id:
        raise HTTPException(status_code=400, detail='run_id is required')
    if not re.match(r'^[a-zA-Z0-9_-]{1,128}$', stream_id):
        raise HTTPException(status_code=400, detail='Invalid run_id format')
    # confirmation_id is a uuid-ish string when present; reject anything that
    # could be a path-traversal attempt against the agent's confirm endpoint.
    if confirmation_id and not re.match(r'^[a-zA-Z0-9_-]{1,128}$', confirmation_id):
        raise HTTPException(status_code=400, detail='Invalid confirmation_id format')
    try:
        # Validate against the canonical contract enum. Any string outside
        # the enum gets a 400 with the same message shape the previous
        # tuple-membership check produced.
        ApprovalOption(choice)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="choice must be 'approve', 'approve_session', or 'deny'",
        ) from exc

    try:
        record = await get_or_create_container(user.id)
    except Exception:
        raise HTTPException(status_code=503, detail='Agent container unavailable')

    # /myah/v1/confirm lives on the standalone runner (Tier 2A) — use
    # gateway_port; fall back to host_port for pre-Tier-2A rows.
    _base = _gateway_url(record.gateway_port or record.host_port)
    _agent_base = resolve_user_agent_base(_base)
    confirm_url = f'{_agent_base}/myah/v1/confirm/{stream_id}'

    headers = {
        'Authorization': f'Bearer {AGENT_BEARER_TOKEN}',
        'Content-Type': 'application/json',
    }

    # ── Myah: forward confirmation_id when the frontend sent one ──
    confirm_body: dict = {'choice': choice}
    if confirmation_id:
        confirm_body['confirmation_id'] = confirmation_id
    # ──────────────────────────────────────────────────────────────

    async with aiohttp.ClientSession() as session:
        async with session.post(
            confirm_url, json=confirm_body, headers=headers, ssl=AIOHTTP_CLIENT_SESSION_SSL
        ) as resp:
            if resp.status == 404:
                raise HTTPException(
                    status_code=404,
                    detail='No pending confirmation for this stream (already resolved or timed out)',
                )
            if resp.status != 200:
                text = await resp.text()
                raise HTTPException(
                    status_code=502,
                    detail=f'Agent confirm failed: {text[:200]}',
                )
            return await resp.json()


@router.post('/chat/secret')
async def submit_chat_secret(
    request: Request,
    user=Depends(get_verified_user),
):
    """Proxy a user's secret value to the Hermes gateway adapter.

    Called by the frontend SecretInputCard when the user submits a secret.
    Routes through /myah/v1/secret/{stream_id} on the gateway adapter.
    The secret value is sent directly to the agent container — it never
    touches the LLM or conversation history.

    Body: { run_id: str, var_name: str, value: str }
    """
    body = await request.json()
    stream_id = body.get('run_id', '')
    var_name = body.get('var_name', '')
    value = body.get('value', '')

    if not stream_id:
        raise HTTPException(status_code=400, detail='run_id is required')
    if not var_name:
        raise HTTPException(status_code=400, detail='var_name is required')
    if not value:
        raise HTTPException(status_code=400, detail='value is required')
    if len(value) > 4096:
        raise HTTPException(status_code=400, detail='value too long')
    if not re.match(r'^[A-Z][A-Z0-9_]{0,127}$', var_name):
        raise HTTPException(status_code=400, detail='Invalid var_name format')
    if not re.match(r'^[a-zA-Z0-9_-]{1,128}$', stream_id):
        raise HTTPException(status_code=400, detail='Invalid run_id format')

    try:
        record = await get_or_create_container(user.id)
    except Exception:
        raise HTTPException(status_code=503, detail='Agent container unavailable')

    # /myah/v1/secret lives on the standalone runner (Tier 2A) — use
    # gateway_port; fall back to host_port for pre-Tier-2A rows.
    _base = _gateway_url(record.gateway_port or record.host_port)
    _agent_base = resolve_user_agent_base(_base)
    secret_url = f'{_agent_base}/myah/v1/secret/{stream_id}'

    headers = {
        'Authorization': f'Bearer {AGENT_BEARER_TOKEN}',
        'Content-Type': 'application/json',
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
            secret_url,
            json={'var_name': var_name, 'value': value},
            headers=headers,
            ssl=AIOHTTP_CLIENT_SESSION_SSL,
        ) as resp:
            if resp.status == 404:
                raise HTTPException(
                    status_code=404,
                    detail='No pending secret capture for this stream',
                )
            if resp.status != 200:
                text = await resp.text()
                raise HTTPException(
                    status_code=502,
                    detail=f'Agent secret submit failed: {text[:200]}',
                )
            return await resp.json()


@router.api_route('/{path:path}', methods=['GET', 'POST', 'PUT', 'DELETE'])
async def proxy(path: str, request: Request, user=Depends(get_verified_user)):
    """
    Deprecated: proxy all requests to OpenAI API
    """

    body = await request.body()

    # Parse JSON body to resolve model-based routing
    payload = None
    if body:
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, ValueError):
            payload = None

    idx = 0
    model_id = payload.get('model') if isinstance(payload, dict) else None
    if model_id:
        models = request.app.state.OPENAI_MODELS
        if not models or model_id not in models:
            await get_all_models(request, user=user)
            models = request.app.state.OPENAI_MODELS
        if model_id in models:
            idx = models[model_id]['urlIdx']

    url = request.app.state.config.OPENAI_API_BASE_URLS[idx]
    key = request.app.state.config.OPENAI_API_KEYS[idx]
    api_config = request.app.state.config.OPENAI_API_CONFIGS.get(
        str(idx),
        request.app.state.config.OPENAI_API_CONFIGS.get(
            request.app.state.config.OPENAI_API_BASE_URLS[idx], {}
        ),  # Legacy support
    )

    r = None
    session = None
    streaming = False

    try:
        headers, cookies = await get_headers_and_cookies(request, url, key, api_config, user=user)

        if api_config.get('azure', False):
            api_version = api_config.get('api_version', '2023-03-15-preview')

            # Only set api-key header if not using Azure Entra ID authentication
            auth_type = api_config.get('auth_type', 'bearer')
            if auth_type not in ('azure_ad', 'microsoft_entra_id'):
                headers['api-key'] = key

            headers['api-version'] = api_version

            payload = json.loads(body)
            url, payload = convert_to_azure_payload(url, payload, api_version)
            body = json.dumps(payload).encode()

            request_url = f'{url}/{path}?api-version={api_version}'
        else:
            request_url = f'{url}/{path}'

        session = aiohttp.ClientSession(
            trust_env=True,
            timeout=aiohttp.ClientTimeout(total=AIOHTTP_CLIENT_TIMEOUT),
        )
        r = await session.request(
            method=request.method,
            url=request_url,
            data=body,
            headers=headers,
            cookies=cookies,
            ssl=AIOHTTP_CLIENT_SESSION_SSL,
        )

        # Check if response is SSE
        if 'text/event-stream' in r.headers.get('Content-Type', ''):
            streaming = True
            return StreamingResponse(
                stream_wrapper(r, session),
                status_code=r.status,
                headers=dict(r.headers),
            )
        else:
            try:
                response_data = await r.json()
            except Exception:
                response_data = await r.text()

            if r.status >= 400:
                if isinstance(response_data, (dict, list)):
                    return JSONResponse(status_code=r.status, content=response_data)
                else:
                    return PlainTextResponse(status_code=r.status, content=response_data)

            return response_data

    except Exception as e:
        log.exception(e)
        raise HTTPException(
            status_code=r.status if r else 500,
            detail='Myah: Server Connection Error',
        )
    finally:
        if not streaming:
            await cleanup_response(r, session)
