# Myah-specific endpoints used by the myah-hermes-plugin.
#
# Today the only consumer is OSS-mode plugin bootstrap: the plugin's
# register(ctx) calls /api/v1/myah/whoami at agent process start time
# to discover its own MYAH_USER_ID. The hosted deployment injects
# MYAH_USER_ID per-container at spawn time, so the endpoint is a
# no-op there — but it is still safe to call.
#
# Auth: bearer token equals MYAH_AGENT_BEARER_TOKEN (the same shared
# secret per-user agent containers use to call the platform's
# attachment-fetch endpoint, cron webhook handler, etc.). In OSS
# single-tenant mode this is the same secret the user pasted into
# their .env when bootstrapping the platform.

import asyncio
import hmac
import os
import time
from types import SimpleNamespace

from fastapi import APIRouter, HTTPException, Request
from loguru import logger
from myah.models.chats import Chats
from myah.models.users import Users
from pydantic import BaseModel

router = APIRouter()


async def background_tasks_handler(ctx):
    """Lazy proxy for ``myah.utils.chat_tasks.background_tasks_handler``.

    ``chat_tasks`` transitively imports ``myah.socket.main`` -> ``myah.config``,
    which queries the ``config`` table at import time. Importing the real
    handler at module scope therefore initialized socket/config DB state just
    by importing this router — breaking test collection with
    ``sqlite3.OperationalError: no such table: config``. Resolving it here, at
    call time, keeps router import side-effect free while preserving the
    ``myah.routers.myah.background_tasks_handler`` seam that callers (and tests)
    patch.
    """
    from myah.utils.chat_tasks import background_tasks_handler as _handler

    return await _handler(ctx)


async def _emit_socket_event(room: str, envelope: dict) -> None:
    """Emit an ``events`` socket.io message to ``room``.

    ``myah.socket.main`` imports ``myah.config``, which queries the DB at
    import time. Importing it here, at call time, keeps router import
    side-effect free. Tests patch this seam rather than the global
    ``myah.socket.main.sio`` so they don't pull the config chain in either.
    """
    from myah.socket.main import sio

    await sio.emit('events', envelope, room=room)




def _coerce_settings_dict(settings) -> dict:
    """Normalize a persisted user-settings value into a plain dict.

    Accepts ``None``, a plain ``dict``, or a Pydantic model (``UserSettings``)
    and always returns a dict (empty when the input can't be coerced).
    """
    if settings is None:
        return {}
    if isinstance(settings, dict):
        return settings
    if hasattr(settings, 'model_dump'):
        try:
            dumped = settings.model_dump()
            return dumped if isinstance(dumped, dict) else {}
        except Exception:  # pragma: no cover - defensive
            return {}
    return {}


def _resolve_aux_generation_flags(settings) -> tuple[bool, bool]:
    """Resolve (title_generation_enabled, follow_up_generation_enabled).

    The frontend is the single source of truth for these toggles and persists
    the entire UI settings tree nested under ``ui`` (SettingsModal.svelte's
    ``saveSettings`` calls ``updateUserSettings({ui: $settings})``), so the
    authoritative flags live at ``settings.ui.title.auto`` and
    ``settings.ui.autoFollowUps``. Older persisted blobs stored them at the top
    level. Prefer the nested ``ui`` block when present and a dict; otherwise
    fall back to the legacy top-level shape.

    Defaults are ``True`` for both flags. Explicit ``False`` is always preserved
    — never coerced back to the default via ``or`` (which would treat a
    deliberately-disabled toggle as unset).
    """
    root = _coerce_settings_dict(settings)
    ui = root.get('ui')
    source = ui if isinstance(ui, dict) else root

    title_settings = source.get('title')
    if not isinstance(title_settings, dict):
        title_settings = {}

    def _as_bool(value, default: bool = True) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {'true', '1', 'yes', 'on'}:
                return True
            if normalized in {'false', '0', 'no', 'off'}:
                return False
            return default
        return bool(value)

    title_enabled = _as_bool(title_settings.get('auto', True))
    follow_up_enabled = _as_bool(source.get('autoFollowUps', True))

    return title_enabled, follow_up_enabled


class FinalMessageRequest(BaseModel):
    """Durable fallback payload for completed interactive Hermes replies."""

    user_id: str
    chat_id: str
    message_id: str | None = None
    response: str
    status: str = 'ok'
    model: str | None = None
    provider: str | None = None


def _verify_agent_bearer(request: Request) -> None:
    auth_header = request.headers.get('Authorization', '')
    if not auth_header.startswith('Bearer '):
        raise HTTPException(status_code=401, detail='Missing or invalid Authorization header')

    token = auth_header[len('Bearer ') :].strip()
    expected = os.environ.get('MYAH_AGENT_BEARER_TOKEN', '').strip()

    if not expected:
        raise HTTPException(
            status_code=503,
            detail='MYAH_AGENT_BEARER_TOKEN not configured on the platform',
        )

    if not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail='Invalid bearer token')


class WhoAmIResponse(BaseModel):
    """Identity payload returned to the plugin at register time."""

    user_id: str
    user_name: str
    deployment_mode: str  # 'hosted' or 'oss' — informational only
    # The (provider, model) pair from hermes config.yaml's model block (OSS only).
    # Mirrors Hermes upstream's canonical {provider, model} shape — see
    # `docs/superpowers/specs/2026-05-24-default-model-canonical-format-design.md`.
    default_model: str | None = None
    default_provider: str | None = None


@router.get('/whoami', response_model=WhoAmIResponse)
async def whoami(request: Request) -> WhoAmIResponse:
    """Return the user_id this bearer token belongs to.

    Used by the myah-hermes-plugin's ``register(ctx)`` in OSS mode to
    discover its own MYAH_USER_ID without forcing the user to paste it
    by hand into ``~/.hermes/.env``.

    Auth scheme: ``Authorization: Bearer <MYAH_AGENT_BEARER_TOKEN>``.
    The token is the platform-wide shared secret used for all
    agent→platform calls. In hosted mode the spawner injects it; in OSS
    mode the user sets it once in the platform's ``.env`` and the same
    value goes in ``~/.hermes/.env`` as ``MYAH_AGENT_BEARER_TOKEN``.

    Single-tenant assumption: the FIRST registered user in the
    database is treated as the OSS user. Multi-user OSS deployments
    require additional auth (out of scope for v1).
    """
    _verify_agent_bearer(request)

    deployment_mode = (
        'oss' if os.environ.get('MYAH_DEPLOYMENT_MODE', '').strip().lower() == 'oss' else 'hosted'
    )

    # Single-tenant resolution: pick the first user in the database.
    # In OSS mode this is the OSS deployer themselves. In hosted mode
    # this endpoint is rarely exercised — the spawner already knows
    # which user the container belongs to.
    #
    # ``Users.get_users()`` returns either a dict with ``{'users':
    # [...], 'total': N}`` (current myah shape) or a plain list
    # (some tests / older shapes). Handle both defensively.
    try:
        result = Users.get_users(limit=1)
        if isinstance(result, dict):
            user_list = result.get('users', [])
        else:
            user_list = list(result) if result else []
        first_user = user_list[0] if user_list else None
    except Exception as exc:  # pragma: no cover — defensive only
        logger.warning(f'/whoami: failed to enumerate users: {exc}')
        raise HTTPException(status_code=500, detail='Could not resolve user') from exc

    if first_user is None:
        raise HTTPException(
            status_code=404,
            detail=(
                'No users registered yet. Sign up at the platform UI '
                'first, then restart your hermes gateway so the plugin re-bootstraps.'
            ),
        )

    user_name = getattr(first_user, 'name', '') or ''

    # ── Myah OSS: auto-import providers from hermes catalog ──────────
    # The platform's provider catalog UX is hosted-only — multi-tenant
    # users explicitly authorize providers via the UI. In OSS single-tenant
    # mode the user already has providers configured in hermes; forcing
    # them to manually re-enter every credential is broken UX.
    #
    # On every /whoami call (which the plugin's _bootstrap_user_id triggers
    # once per hermes startup), upsert UserProviderStatuses rows for every
    # provider that has a credential in hermes. Idempotent — upsert
    # refreshes existing rows; new providers added in hermes after a
    # previous /whoami get picked up on the next one.
    #
    # We do NOT delete platform-DB rows that hermes doesn't have, because
    # the user may have legitimately added a provider via the UI even in
    # OSS (e.g. providing a key for a provider not yet in hermes catalog).
    if deployment_mode == 'oss':
        try:
            from myah.models.user_provider_status import UserProviderStatuses
            from myah.utils.hermes_web import fetch_hermes_provider_catalog
            catalog = await fetch_hermes_provider_catalog(first_user)
            for p in catalog:
                pid = (p.get('id') or '').strip()
                if pid and p.get('has_credential', False):
                    UserProviderStatuses.upsert(
                        user_id=first_user.id,
                        provider_id=pid,
                        is_valid=True,
                        key_last_four='hermes',  # marker — auto-imported, not UI-entered
                    )
            if catalog:
                logger.info(
                    f'/whoami: auto-imported {sum(1 for p in catalog if p.get("has_credential"))} '
                    f'providers from hermes catalog for user {first_user.id}'
                )
        except Exception:
            logger.exception('/whoami: provider catalog auto-import failed')
    # ──────────────────────────────────────────────────────────────────

    # ── Myah OSS: surface hermes default-model + sync user.default_model.
    # The plugin's _bootstrap_user_id reads /whoami to discover MYAH_USER_ID;
    # use the same call to *also* keep the platform's user.default_model in
    # sync with the user's hermes config.yaml default.
    #
    # We update the user row directly here instead of letting the plugin
    # POST to /api/v1/users/user/default-model because that endpoint requires
    # JWT auth (get_verified_user). The plugin only has the agent bearer
    # token, not a user session. /whoami already verified the bearer above,
    # and we're operating on the single-tenant first-user, so a direct
    # Users.update_user_by_id is the simplest, most reliable path.
    #
    # Best-effort — failures log and return default_model=None; never block
    # /whoami because the plugin needs the user_id even when the sync fails.
    default_pair: tuple[str, str] | None = None
    if deployment_mode == 'oss':
        try:
            from myah.utils.hermes_web import fetch_hermes_default_model
            default_pair = await fetch_hermes_default_model(first_user)
        except Exception:
            logger.exception('/whoami: failed to read hermes default model')

        # Sync to platform DB only when:
        #   - hermes returned a non-empty (provider, model) pair AND
        #   - the user's current default pair is empty OR matches the
        #     inherited Open WebUI default ('openai', 'gpt-4o-mini'). The
        #     latter check guards against clobbering a deliberate user choice.
        _OPEN_WEBUI_DEFAULTS = {('openai', 'gpt-4o-mini')}
        if default_pair:
            current_pair = (
                getattr(first_user, 'default_provider', None),
                getattr(first_user, 'default_model', None),
            )
            if (not current_pair[1]) or current_pair in _OPEN_WEBUI_DEFAULTS:
                try:
                    Users.update_user_by_id(
                        first_user.id,
                        {
                            'default_provider': default_pair[0],
                            'default_model': default_pair[1],
                        },
                    )
                    logger.info(
                        f'/whoami: synced user default pair {current_pair!r} -> {default_pair!r} '
                        f'from hermes config'
                    )
                except Exception:
                    logger.exception('/whoami: failed to sync user default pair')
    # ───────────────────────────────────────────────────────────────

    return WhoAmIResponse(
        user_id=first_user.id,
        user_name=user_name,
        deployment_mode=deployment_mode,
        default_model=default_pair[1] if default_pair else None,
        default_provider=default_pair[0] if default_pair else None,
    )


@router.post('/messages/final')
async def persist_final_message(request: Request, payload: FinalMessageRequest):
    """Persist an interactive assistant reply when the live SSE stream is gone.

    The Myah Hermes plugin normally delivers assistant text over
    /myah/v1/events/{stream_id}. If the browser/platform SSE connection
    disconnects during a long non-streaming run, the plugin's final
    adapter.send(...) call cannot push to the in-memory queue. This endpoint
    is the durable fallback: the plugin posts the completed content here so
    the chat message is marked done instead of staying on "Thinking...".
    """
    _verify_agent_bearer(request)

    if not payload.user_id or not payload.chat_id:
        raise HTTPException(status_code=400, detail='Missing user_id or chat_id')
    if payload.response is None:
        raise HTTPException(status_code=400, detail='Missing response')

    chat = Chats.get_chat_by_id_and_user_id(payload.chat_id, payload.user_id)
    if chat is None:
        raise HTTPException(status_code=404, detail='Chat not found')

    if not payload.message_id:
        raise HTTPException(status_code=400, detail='Missing message_id')
    if payload.status not in {'ok', 'error'}:
        raise HTTPException(status_code=400, detail='Invalid status')

    message_id = payload.message_id
    existing_message = (chat.chat or {}).get('history', {}).get('messages', {}).get(message_id, {})
    existing_content = (existing_message.get('content') or '').strip()
    incoming_content = (payload.response or '').strip()
    existing_is_error = bool(existing_message.get('error'))
    incoming_is_error = payload.status == 'error'
    is_finalized_assistant = (
        existing_message.get('role') == 'assistant' and existing_message.get('done') is True
    )
    already_finalized = (
        is_finalized_assistant
        and existing_content == incoming_content
        and existing_is_error == incoming_is_error
    )
    if already_finalized:
        logger.info(
            f'/messages/final: duplicate final assistant message ignored chat_id={payload.chat_id} '
            f'message_id={message_id} user_id={payload.user_id}'
        )
        return {'ok': True, 'message_id': message_id, 'duplicate': True}

    existing_is_empty_success_placeholder = (
        is_finalized_assistant and not existing_content and not existing_is_error
    )
    already_finalized_conflict = (
        is_finalized_assistant
        and not existing_is_empty_success_placeholder
        and (existing_content != incoming_content or existing_is_error != incoming_is_error)
    )
    if already_finalized_conflict:
        logger.warning(
            f'/messages/final: ignoring conflicting final assistant message chat_id={payload.chat_id} '
            f'message_id={message_id} user_id={payload.user_id} '
            f'existing_len={len(existing_message.get("content") or "")} '
            f'incoming_len={len(payload.response or "")}'
        )
        return {
            'ok': True,
            'message_id': message_id,
            'ignored': True,
            'reason': 'already_finalized',
        }

    if existing_is_empty_success_placeholder and incoming_content:
        logger.info(
            f'/messages/final: replacing empty finalized assistant placeholder chat_id={payload.chat_id} '
            f'message_id={message_id} user_id={payload.user_id} incoming_len={len(payload.response or "")}'
        )

    clean_response = incoming_content or '(no output)'
    update = {
        'id': message_id,
        'role': 'assistant',
        'content': clean_response,
        'done': True,
        'timestamp': int(time.time()),
    }
    if payload.status == 'error':
        update['error'] = {'content': clean_response}
    if payload.model:
        update['modelUsed'] = {'id': payload.model, 'provider': payload.provider or ''}

    persisted = Chats.upsert_message_to_chat_by_id_and_message_id(
        payload.chat_id,
        message_id,
        update,
    )
    if persisted is None:
        raise HTTPException(status_code=404, detail='Chat not found')

    async def _emit_final_event(event):
        await _emit_socket_event(
            f'user:{payload.user_id}',
            {
                'chat_id': payload.chat_id,
                'message_id': message_id,
                'data': event,
            },
        )

    try:
        await _emit_final_event(
            {
                'type': 'chat:completion',
                'data': {
                    'content': clean_response,
                    'done': True,
                    'message_id': message_id,
                    'chat_id': payload.chat_id,
                },
            }
        )
        await _emit_final_event({'type': 'status', 'data': {'done': True}})
    except Exception as exc:  # pragma: no cover - socket notification is best-effort
        logger.debug(f'/messages/final: socket emit failed: {exc}')

    async def _background_event_emitter(event):
        if event.get('type') in {
            'chat:completion',
            'chat:title',
            'chat:message:follow_ups',
        }:
            await _emit_final_event(event)

    def _log_background_task_failure(task):
        if task.cancelled():
            logger.debug('/messages/final: background tasks cancelled')
            return
        exc = task.exception()
        if exc:
            logger.debug(f'/messages/final: background tasks failed: {exc}')

    title_generation_enabled = True
    follow_up_generation_enabled = True
    try:
        user_row = Users.get_user_by_id(payload.user_id)
        title_generation_enabled, follow_up_generation_enabled = _resolve_aux_generation_flags(
            getattr(user_row, 'settings', None)
        )
    except Exception as exc:  # pragma: no cover - background enrichment remains best-effort
        logger.debug(f'/messages/final: failed to read generation settings: {exc}')

    try:
        bg_ctx = {
            'request': request,
            'form_data': {
                'model': payload.model or 'myah',
                'messages': [
                    {'role': 'assistant', 'content': clean_response, 'model': payload.model or 'myah'}
                ],
            },
            'user': SimpleNamespace(id=payload.user_id, name='', role='user'),
            'model': {'id': payload.model or 'myah'},
            'metadata': {
                'chat_id': payload.chat_id,
                'message_id': message_id,
                'session_id': payload.chat_id,
            },
            'tasks': {
                'title_generation': title_generation_enabled,
                'follow_up_generation': follow_up_generation_enabled,
            },
            'events': {},
            'event_emitter': _background_event_emitter,
            'event_caller': None,
        }
        task = asyncio.create_task(background_tasks_handler(bg_ctx))
        task.add_done_callback(_log_background_task_failure)
    except Exception as exc:  # pragma: no cover - enrichment is best-effort
        logger.debug(f'/messages/final: failed to schedule background tasks: {exc}')

    logger.info(
        f'/messages/final: persisted final assistant message chat_id={payload.chat_id} '
        f'message_id={message_id} user_id={payload.user_id}'
    )
    return {'ok': True, 'message_id': message_id}
