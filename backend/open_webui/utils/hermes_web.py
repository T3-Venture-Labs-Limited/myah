# Helper for forwarding HTTP requests from the platform to the per-user
# `hermes dashboard` server inside the Hermes agent container — i.e. the
# Workstream A Phase 0 "hermes-native admin" path.
#
# This module is the twin of agent_proxy.py: same shape, different target.
#  * agent_proxy.aux_call  -> /v1, /myah/api  (port = container.host_port)
#  * hermes_web.web_call   -> /api/plugins/myah-admin/*  (port = container.web_port)
#
# Auth model: each container has a long-lived bearer token persisted as
# Container.web_session_token; the same value is injected into the
# container as HERMES_WEB_SESSION_TOKEN so `hermes dashboard` accepts the
# `Authorization: Bearer <token>` header (see hermes_cli/web_server.py:73).
#
# OSS mode (single-tenant self-hosted): when MYAH_DEPLOYMENT_MODE=oss,
# the platform skips per-user-container spawning entirely and forwards
# requests to a single host-side Hermes gateway the OSS user runs
# themselves. See ``is_oss_mode`` and ``_oss_chat_port`` below.

import os
import socket
from typing import Any

import httpx
import sentry_sdk
from fastapi import HTTPException
from loguru import logger
from open_webui.models.containers import ContainerModel, Containers
from open_webui.models.users import UserModel


def is_oss_mode() -> bool:
    """Return True when the platform is running as a self-hosted OSS deployment.

    OSS mode skips per-user-container spawning. The OSS user runs Hermes
    Agent themselves on the host (or on another reachable host) and the
    platform forwards chat / admin / proxy requests to that single
    gateway. Toggle via ``MYAH_DEPLOYMENT_MODE=oss``; default is hosted.

    Cardinal rule for OSS mode helpers: never raise from a missing env
    var — log a warning and fall back to ``host.docker.internal:<port>``
    so a fresh deploy on Docker Desktop "just works" out of the box.
    """
    return os.environ.get('MYAH_DEPLOYMENT_MODE', '').strip().lower() == 'oss'


def _oss_chat_port() -> int:
    """OSS host-side gateway chat port (defaults to upstream's 8642)."""
    raw = os.environ.get('MYAH_HERMES_CHAT_PORT', '8642').strip() or '8642'
    try:
        return int(raw)
    except ValueError:
        logger.warning(
            f'MYAH_HERMES_CHAT_PORT={raw!r} is not an integer; falling back to 8642'
        )
        return 8642


def _oss_gateway_port() -> int:
    """OSS host-side gateway adapter port (defaults to upstream's 8643)."""
    raw = os.environ.get('MYAH_HERMES_GATEWAY_PORT', '8643').strip() or '8643'
    try:
        return int(raw)
    except ValueError:
        logger.warning(
            f'MYAH_HERMES_GATEWAY_PORT={raw!r} is not an integer; falling back to 8643'
        )
        return 8643


def _oss_web_port() -> int:
    """OSS host-side hermes dashboard port (defaults to upstream's 9119)."""
    raw = os.environ.get('MYAH_HERMES_WEB_PORT', '9119').strip() or '9119'
    try:
        return int(raw)
    except ValueError:
        logger.warning(
            f'MYAH_HERMES_WEB_PORT={raw!r} is not an integer; falling back to 9119'
        )
        return 9119


def _oss_web_session_token() -> str:
    """OSS-mode hermes dashboard session token.

    Empty string is acceptable when the user runs ``hermes dashboard``
    without an explicit ``HERMES_WEB_SESSION_TOKEN`` set (the dashboard
    will also have an empty token and authenticate trivially in
    single-tenant scope). For production self-hosted, users should set
    a real token in ``.env`` to lock down dashboard access.
    """
    return os.environ.get('MYAH_HERMES_WEB_SESSION_TOKEN', '').strip()


def _detect_agent_host() -> str:
    """Same logic as routers.containers._detect_agent_host but local —
    keeps this module out of the routers import chain so test_hermes_web
    doesn't transitively re-import open_webui.config (which redefines
    SQLAlchemy tables and breaks ordering against tests that touch the
    container model)."""
    explicit = os.environ.get('MYAH_AGENT_HOST', '')
    if explicit:
        return explicit
    try:
        socket.getaddrinfo('host.docker.internal', None)
        return 'host.docker.internal'
    except socket.gaierror:
        return 'localhost'


_AGENT_HOST = _detect_agent_host()


async def _ensure_container(user: UserModel) -> ContainerModel:
    """Return a healthy container row for the user, spawning if necessary.

    Short-circuits on a recently-active running container (≤30s of inactivity)
    to avoid a docker round-trip per request. Otherwise calls
    ``get_or_create_container`` which does a real health probe + restart.

    The 30s recency gate exists because the DB row never gets updated when
    containers are killed externally (deploy stop, OOM, manual docker stop).
    Without it, a stale 'running' record would be trusted forever.
    """
    import asyncio
    import time

    record: ContainerModel | None = await asyncio.to_thread(Containers.get_by_user_id, user.id)
    if (
        record
        and record.status == 'running'
        and record.host_port
        and record.last_active
        and (time.time() - record.last_active) < 30
    ):
        return record

    # Cold path — actual docker probe + spawn-or-restart.
    from open_webui.routers.containers import get_or_create_container

    record = await get_or_create_container(user.id)
    if not record:
        raise HTTPException(status_code=503, detail='Agent container unavailable')
    return record


async def _resolve_chat_port(user: UserModel) -> int:
    """Return the user's container chat port (the Myah gateway adapter on 8642).

    Auto-spawns the container if needed. Used by ``aux_call`` to reach the
    chat I/O surface (``/myah/v1/*``) and the gateway runtime-control surface
    (``/myah/v1/admin/*``).

    OSS mode: skip the container path entirely; route directly to the
    user's host-side ``hermes gateway start`` process at the configured
    chat port (defaults to upstream's 8642).
    """
    if is_oss_mode():
        return _oss_chat_port()
    record = await _ensure_container(user)
    if not record.host_port:
        raise HTTPException(status_code=503, detail='Agent container has no host_port')
    return record.host_port


async def _resolve_gateway_port(user: UserModel) -> int:
    """Return the host port mapped to the agent's standalone Myah runner.

    Mirrors :func:`_resolve_chat_port` but reads ``Container.gateway_port``
    (mapped to ``MYAH_GATEWAY_PORT`` / 8643 inside the container).

    Backward compat: containers spawned before the gateway_port column
    existed have ``gateway_port = None``. We fall back to ``host_port``
    so chat keeps working until the container is respawned with the new
    port mapping. Logs a single WARNING per fallback so the operator can
    spot stale rows.

    OSS mode: skip the container path entirely; route directly to the
    user's host-side standalone Myah aiohttp runner at the configured
    gateway port (defaults to upstream's 8643).
    """
    if is_oss_mode():
        return _oss_gateway_port()
    record = await _ensure_container(user)
    if record.gateway_port:
        return record.gateway_port
    if not record.host_port:
        raise HTTPException(status_code=503, detail='Agent container has no host_port')
    container_id = getattr(record, 'container_id', '') or 'unknown'
    logger.warning(
        f'Container {container_id[:12]} has gateway_port=NULL — falling back to '
        f'host_port={record.host_port}. This row predates the Tier 2A '
        f'port-coordination change; the container will respawn with a '
        f'gateway_port on next idle eviction.'
    )
    return record.host_port


async def _resolve_web_endpoint(user: UserModel) -> tuple[int, str]:
    """Return ``(web_port, web_session_token)`` for the user's container.

    Auto-spawns the container if needed. The web port maps to the
    ``hermes dashboard`` server on internal port 9119, used for native
    Hermes admin (``/api/*``) and the Myah-admin plugin
    (``/api/plugins/myah-admin/*``).

    Raises 503 if (after spawn) the container row still has NULL web_port or
    NULL web_session_token — that means the container was created before the
    Phase 0 migration added those columns and needs to be recreated.

    OSS mode: skip the container path entirely; route directly to the
    user's host-side ``hermes dashboard`` process. Token may be empty if
    the OSS user did not configure ``MYAH_HERMES_WEB_SESSION_TOKEN``.
    """
    if is_oss_mode():
        return _oss_web_port(), _oss_web_session_token()
    record = await _ensure_container(user)
    if not record.web_port:
        raise HTTPException(
            status_code=503,
            detail='Agent container is missing a hermes dashboard port — please restart the container',
        )
    if not record.web_session_token:
        raise HTTPException(
            status_code=503,
            detail='Agent container is missing a hermes dashboard token — please restart the container',
        )
    return record.web_port, record.web_session_token


async def web_call(
    user: UserModel,
    method: str,
    path: str,
    *,
    json_body: Any = None,
    text_body: str | None = None,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 15.0,
) -> dict[str, Any]:
    """Forward an HTTP request to the user's `hermes dashboard` server.

    `path` is the full path beginning with ``/`` (typically
    ``/api/plugins/myah-admin/...``). Does NOT raise on 4xx/5xx — caller
    inspects ``status``.

    Pass ``text_body`` for raw text/markdown bodies (e.g. PUT
    ``/api/plugins/myah-admin/config/soul``); ``json_body`` is ignored
    when ``text_body`` is set.

    Returns:
        {'status': int, 'body': parsed-json|str|None, 'headers': dict}

    Sentry breadcrumbs: every call adds an info-level breadcrumb so the
    Phase 0 rollout is easy to trace end-to-end without per-call logging.
    """
    web_port, token = await _resolve_web_endpoint(user)
    url = f'http://{_AGENT_HOST}:{web_port}{path}'

    req_headers: dict[str, str] = {
        'Authorization': f'Bearer {token}',
    }
    if headers:
        req_headers.update(headers)

    sentry_sdk.add_breadcrumb(
        category='hermes_web',
        level='info',
        message=f'{method} {path}',
        data={'user_id': user.id, 'web_port': web_port},
    )

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            if text_body is not None:
                resp = await client.request(
                    method,
                    url,
                    content=text_body,
                    params=params,
                    headers=req_headers,
                )
            else:
                resp = await client.request(
                    method,
                    url,
                    json=json_body,
                    params=params,
                    headers=req_headers,
                )
    except httpx.ConnectError as e:
        logger.error(f'hermes_web connect error (user={user.id}, {method} {path}): {e}')
        raise HTTPException(
            status_code=503,
            detail='Hermes dashboard server unavailable — please retry',
        ) from e
    except httpx.TimeoutException as e:
        logger.error(f'hermes_web timeout (user={user.id}, {method} {path}): {e}')
        raise HTTPException(status_code=504, detail='Hermes dashboard server timed out') from e
    except (httpx.ReadError, httpx.RemoteProtocolError) as e:
        # Connection accepted then dropped mid-request — typical when the
        # dashboard FastAPI app is mid-startup (TCP listener bound but the
        # ASGI app isn't serving yet). Surface as 503 so callers can retry,
        # NOT as 500 (which the platform default handler would render and
        # produce confusing "Internal Server Error" toasts in the frontend).
        # The container-spawn path has its own readiness probe in
        # ``_wait_for_ready`` that probes BOTH chat and dashboard before
        # marking the container running, so this branch is mainly a defense
        # against externally-killed-and-restarted containers.
        logger.error(f'hermes_web read error (user={user.id}, {method} {path}): {e}')
        raise HTTPException(
            status_code=503,
            detail='Hermes dashboard dropped the connection — please retry',
        ) from e

    content_type = resp.headers.get('content-type', '')
    if 'application/json' in content_type:
        try:
            body: Any = resp.json()
        except Exception:
            body = resp.text
    elif not resp.content:
        body = None
    else:
        body = resp.text

    return {
        'status': resp.status_code,
        'body': body,
        'headers': dict(resp.headers),
    }


async def web_call_or_raise(
    user: UserModel,
    method: str,
    path: str,
    *,
    json_body: Any = None,
    text_body: str | None = None,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 15.0,
) -> Any:
    """``web_call`` wrapper that raises HTTPException on non-2xx.

    Use this from passthrough router endpoints where a non-2xx response
    from hermes dashboard should propagate to the platform caller.
    """
    result = await web_call(
        user,
        method,
        path,
        json_body=json_body,
        text_body=text_body,
        params=params,
        headers=headers,
        timeout=timeout,
    )
    if result['status'] >= 400:
        detail = result['body']
        if isinstance(detail, str):
            detail = detail[:200]
        raise HTTPException(status_code=result['status'], detail=detail)
    return result['body']


# ── Myah OSS: hermes provider catalog discovery ───────────────────────


async def fetch_hermes_provider_catalog(user: UserModel) -> list[dict]:
    """Fetch the user's hermes-side provider catalog in OSS mode.

    Returns a list of provider dicts shaped like:
        [{"id": "openrouter", "label": "OpenRouter",
          "has_credential": True, "models": [...], ...}, ...]

    Returns empty list when not in OSS mode or when the catalog endpoint
    is unreachable. Never raises — silent failure means the model
    picker simply falls back to its existing per-user provider state.

    Calls the plugin's ``GET /myah/v1/admin/providers`` endpoint on the
    gateway adapter port (8643 in OSS, per-user-container port in
    hosted). The plugin enriches each entry with ``has_credential``
    (env-var or auth.json lookup) which the dashboard's raw
    ``/api/plugins/myah-admin/providers`` endpoint does NOT carry.
    Auth uses the standard ``MYAH_AGENT_BEARER_TOKEN`` — no separate
    dashboard session token needed.
    """
    if not is_oss_mode():
        return []

    try:
        gateway_port = await _resolve_gateway_port(user)
    except Exception as exc:
        logger.info(f'OSS provider catalog: failed to resolve gateway port: {exc}')
        return []

    bearer = os.environ.get('MYAH_AGENT_BEARER_TOKEN', '')
    headers = {'Authorization': f'Bearer {bearer}'} if bearer else {}

    base = f'http://{_detect_agent_host()}:{gateway_port}'
    url = f'{base}/myah/v1/admin/providers'
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=headers)
        if resp.status_code == 404:
            logger.warning(
                f'OSS provider catalog 404 from {url} — myah-hermes-plugin too '
                'old (needs the /admin/providers endpoint added in the '
                'ISSUE-003 follow-up commit)'
            )
            return []
        if resp.status_code != 200:
            logger.info(
                f'OSS provider catalog fetch returned HTTP {resp.status_code} from {url}'
            )
            return []
        data = resp.json()
        return data.get('providers', []) if isinstance(data, dict) else []
    except Exception as exc:
        logger.warning(f'OSS provider catalog fetch failed: {exc}')
        return []


async def fetch_hermes_default_model(user: UserModel) -> str | None:
    """Read the hermes config.yaml default model.

    Returns a string like "opencode-go/mimo-v2.5" (provider/model
    formatted to match the platform's model_id convention), or None on
    failure. OSS-only — returns None when not in OSS mode.

    Calls the plugin's ``GET /myah/v1/admin/config`` endpoint on the
    gateway adapter port (8643 in OSS, per-user-container port in
    hosted). This endpoint is the agent-side equivalent of reading
    ``~/.hermes/config.yaml`` directly, but uses the standard
    ``MYAH_AGENT_BEARER_TOKEN`` auth (same secret the platform already
    uses for every other agent call). The previous implementation hit
    the hermes dashboard's ``:9119/api/config`` which required a
    separate ``HERMES_WEB_SESSION_TOKEN`` that OSS users typically
    don't configure — that endpoint returned 401 and this helper
    silently returned None, leaving the user's default model unsynced.
    """
    if not is_oss_mode():
        return None

    try:
        gateway_port = await _resolve_gateway_port(user)
    except Exception as exc:
        logger.info(f'OSS default-model fetch: failed to resolve gateway port: {exc}')
        return None

    bearer = os.environ.get('MYAH_AGENT_BEARER_TOKEN', '')
    headers = {'Authorization': f'Bearer {bearer}'} if bearer else {}

    base = f'http://{_detect_agent_host()}:{gateway_port}'
    url = f'{base}/myah/v1/admin/config'
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=headers)
        if resp.status_code == 404:
            logger.warning(
                f'OSS default-model fetch: 404 from {url} — myah-hermes-plugin '
                'too old (needs the /admin/config endpoint added in the '
                'ISSUE-004 follow-up commit)'
            )
            return None
        if resp.status_code != 200:
            logger.info(
                f'OSS default-model fetch returned HTTP {resp.status_code} from {url}'
            )
            return None
        cfg = resp.json()
        model_block = cfg.get('model', {}) if isinstance(cfg, dict) else {}
        provider = (model_block.get('provider') or '').strip()
        model = (model_block.get('default') or '').strip()
        if not (provider and model):
            return None
        return f'{provider}/{model}'
    except Exception as exc:
        logger.warning(f'OSS default-model fetch: {exc}')
        return None
