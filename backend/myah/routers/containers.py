import asyncio
import logging
import os
import secrets
import socket
import time
from contextlib import closing
from typing import Optional

import docker
import httpx
from docker.errors import APIError, DockerException, NotFound
from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from myah.config import AUX_DEFAULT_TASKS, _resolve_aux_default
from myah.constants import ERROR_MESSAGES
from myah.models.containers import ContainerModel, Containers
from myah.models.users import UserModel, Users

# OSS-split: honcho is a hosted-only service; it is lazy-imported inside the
# hosted code path (see _get_or_create_container_locked / get_or_create_container).
# The OSS variant short-circuits to a synthetic ContainerModel via is_oss_mode()
# before any honcho call is reached, so the absence of services/honcho.py in the
# OSS build is safe at import time.
from myah.utils.auth import get_admin_user, get_verified_user
from pydantic import BaseModel

try:
    from myah.utils.telemetry.myah_metrics import record_container_startup as _record_container_startup
except Exception:
    _record_container_startup = None

####################
# Container Manager
# Every user deserves a room of their own. This module tends
# the doors — opening them, keeping them warm, and closing
# them gently when the inhabitant has been away too long.
####################

router = APIRouter()
log = logging.getLogger(__name__)

# ─── Configuration (overridable via env vars) ─────────────────────────────────

# Environment variables consumed by this module:
#
#   MYAH_PLATFORM_WEBHOOK_HOST
#       Explicit override for the host the agent uses to webhook back
#       to the platform.
#
#   MYAH_PLATFORM_PORT
#       Internal platform port. Defaults to 8080; override only if running
#       uvicorn on a different port.
#
#   MYAH_AGENT_HOST
#       Host the platform uses to reach agent containers. Auto-detected
#       via host.docker.internal DNS lookup; override for unusual setups.

# Phase 7.7 (2026-05-11): default flipped from ``myah/agent:latest``
# (fork — Dockerfile, deleted in Phase 7.8) to ``myah/agent-stock:latest``
# (upstream hermes-agent pip-installed + plugin layered on top —
# Dockerfile.stock). Production sets MYAH_AGENT_IMAGE explicitly in
# ``.env.prod`` so the default below mostly governs local dev + tests.
AGENT_IMAGE = os.environ.get('MYAH_AGENT_IMAGE', 'myah/agent-stock:latest')
# Phase 7.7 cutover-pairing log: emit on every platform boot so operators
# can verify the `.env.prod` cutover paired with the migration progress.
# See docs/gotchas/2026-05-12-stock-image-env-prod-cutover.md.
logger.info(f'MYAH_AGENT_IMAGE active default: {AGENT_IMAGE}')


# ── Per-user image overrides (Phase 7.2 canary mechanism) ─────────────────
# Pin specific users to a non-default agent image without redeploying the
# whole fleet. Format:
#
#   MYAH_AGENT_IMAGE_OVERRIDES="user_id_1=image_1,user_id_2=image_2"
#
# Whitespace around tokens is stripped. Empty entries are ignored so
# trailing commas and double-commas don't blow up. Malformed entries (no
# ``=`` separator, empty user_id or image) are logged and skipped — a
# bad override must NEVER take down the spawner.
#
# Phase 7.7 flipped the default to the stock image. The override
# mechanism survives as a generic "pin this user to a non-default image"
# tool — useful for testing pre-release stock SHAs against alpha users
# before they roll into ``:latest``, or pinning a user back to the
# legacy fork image as a one-user kill-switch if Phase 7.7 regresses
# something on a specific user's workload:
#
#   MYAH_AGENT_IMAGE_OVERRIDES="user-test=myah/agent-stock:<future-sha>"
#
# Stop the override for a user by removing them from the env var and
# restarting the platform — their next container spawn picks up the
# default ``MYAH_AGENT_IMAGE`` again. The kill-switch runbook lives in
# ``docs/gotchas/`` (added in Phase 7.6.1).
#
# The override applies at container ``run`` time only; existing running
# containers keep their original image until the next platform-driven
# restart. This is intentional — canary semantics require operators to
# decide when each user's container actually flips.
def _parse_image_overrides(raw: str) -> dict[str, str]:
    """Parse the ``MYAH_AGENT_IMAGE_OVERRIDES`` env var value.

    Returns a ``{user_id: image}`` dict. Malformed entries log a warning
    and are skipped; the function never raises. Empty input returns ``{}``.
    """
    if not raw:
        return {}
    out: dict[str, str] = {}
    for entry in raw.split(','):
        entry = entry.strip()
        if not entry:
            continue
        if '=' not in entry:
            logger.warning(f'MYAH_AGENT_IMAGE_OVERRIDES: skipping malformed entry {entry!r} — expected "user_id=image"')
            continue
        user_id, _, image = entry.partition('=')
        user_id = user_id.strip()
        image = image.strip()
        if not user_id or not image:
            logger.warning(f'MYAH_AGENT_IMAGE_OVERRIDES: skipping entry with empty user_id or image: {entry!r}')
            continue
        out[user_id] = image
    return out


AGENT_IMAGE_OVERRIDES = _parse_image_overrides(os.environ.get('MYAH_AGENT_IMAGE_OVERRIDES', ''))
if AGENT_IMAGE_OVERRIDES:
    logger.info(
        f'MYAH_AGENT_IMAGE_OVERRIDES active for {len(AGENT_IMAGE_OVERRIDES)} user(s); default remains {AGENT_IMAGE}'
    )


def _image_for_user(user_id: str) -> str:
    """Return the agent image to use for the given user.

    Falls back to ``AGENT_IMAGE`` (the global default) when the user has
    no override configured. Override-bearing users get their pinned image
    so a canary rollout can pin specific users to ``myah/agent-stock:<sha>``
    without affecting the rest of the fleet.
    """
    return AGENT_IMAGE_OVERRIDES.get(user_id, AGENT_IMAGE)


AGENT_API_PORT = int(os.environ.get('MYAH_AGENT_PORT', '8642'))
# Port the standalone Myah aiohttp runner listens on inside the agent
# container (Tier 2A standalone-runner refactor). Independent from the
# API server port (8642) — the runner mounts /myah/v1/* and /myah/health
# while 8642 only serves /v1/* and /health/*. The host-side port is
# allocated dynamically per container and stored as Container.gateway_port.
AGENT_GATEWAY_PORT = int(os.environ.get('MYAH_GATEWAY_PORT', '8643'))
AGENT_VNC_PORT = int(os.environ.get('MYAH_AGENT_VNC_PORT', '5900'))
AGENT_RAM_LIMIT = os.environ.get('MYAH_AGENT_RAM', '4g')
AGENT_CPU_QUOTA = int(os.environ.get('MYAH_AGENT_CPU_QUOTA', '200000'))
AGENT_CPU_PERIOD = int(os.environ.get('MYAH_AGENT_CPU_PERIOD', '100000'))
CONTAINER_READY_TIMEOUT = int(os.environ.get('MYAH_CONTAINER_READY_TIMEOUT', '180'))
AGENT_BEARER_TOKEN = os.environ.get('MYAH_AGENT_BEARER_TOKEN', '')
AGENT_VITE_PORT = int(os.environ.get('MYAH_AGENT_VITE_PORT', '5174'))
# In-container port for `hermes dashboard` — the FastAPI server that exposes
# /api/plugins/myah-admin/* (Workstream A Phase 0). The host port is
# allocated dynamically (see _start_container_sync) and stored as
# Container.web_port.
AGENT_WEB_PORT = int(os.environ.get('MYAH_AGENT_WEB_PORT', '9119'))
HONCHO_ADMIN_KEY = os.environ.get('HONCHO_ADMIN_KEY', '')


def _detect_docker_host() -> str:
    """Auto-detect the hostname that agent containers should use to reach the
    host machine.

    - macOS / Windows (Docker Desktop): ``host.docker.internal`` resolves
      inside the container VM.  It does NOT resolve on the host itself, so
      we detect via ``platform.system()`` instead of DNS.
    - Linux (native Docker): the Docker bridge gateway ``172.17.0.1`` is used.
      Containers are also started with ``--add-host=host.docker.internal:host-gateway``
      so ``host.docker.internal`` works there too.

    Callers can override with *env_var* for platform vs agent directions.
    """
    import platform as _plat

    if _plat.system() in ('Darwin', 'Windows'):
        return 'host.docker.internal'
    return '172.17.0.1'


def _detect_platform_port() -> str:
    """Detect the port the platform backend is listening on.

    Priority: MYAH_PLATFORM_PORT env  >  uvicorn --port CLI arg  >  8080.
    """
    explicit = os.environ.get('MYAH_PLATFORM_PORT', '')
    if explicit:
        return explicit
    # Detect from uvicorn CLI args (handles `npm run dev:backend` which
    # passes --port 8082 directly instead of using an env var).
    import sys

    for i, arg in enumerate(sys.argv):
        if arg == '--port' and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return '8080'


# Host used to reach agent containers from the platform backend.
# In Docker: 'host.docker.internal' (must have extra_hosts mapping in compose).
# In local dev (native): 'localhost'.
def _detect_agent_host() -> str:
    explicit = os.environ.get('MYAH_AGENT_HOST', '')
    if explicit:
        return explicit
    try:
        socket.getaddrinfo('host.docker.internal', None)
        return 'host.docker.internal'
    except socket.gaierror:
        return 'localhost'


# Webhook host derivation order:
#   1. MYAH_PLATFORM_WEBHOOK_HOST (explicit override) — wins.
#   2. Fallback: _detect_docker_host() returns 'host.docker.internal' (Docker
#      Desktop on macOS/Windows) or '172.17.0.1' (Linux native bridge gateway).
_explicit_webhook_host = os.environ.get('MYAH_PLATFORM_WEBHOOK_HOST', '')
if _explicit_webhook_host:
    PLATFORM_WEBHOOK_HOST = _explicit_webhook_host
else:
    PLATFORM_WEBHOOK_HOST = _detect_docker_host()
PLATFORM_PORT = _detect_platform_port()
AGENT_HOST = _detect_agent_host()
VOLUME_PREFIX = 'myah-data-'
CONTAINER_PREFIX = 'myah-agent-'

logger.info(f'Container config: webhook_url=http://{PLATFORM_WEBHOOK_HOST}:{PLATFORM_PORT} agent_host={AGENT_HOST}')


def _docker_client() -> docker.DockerClient:
    """Return a connected Docker client, raising 503 if the daemon is unavailable."""
    try:
        client = docker.from_env()
        client.ping()
        return client
    except DockerException as exc:
        raise HTTPException(status_code=503, detail=f'Docker daemon unavailable: {exc}')


def _free_port() -> int:
    """Find a free TCP port on the host by binding to port 0."""
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(('', 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return s.getsockname()[1]


def _container_name(user_id: str) -> str:
    safe_id = user_id.replace('-', '')[:24]
    return f'{CONTAINER_PREFIX}{safe_id}'


def _volume_name(user_id: str) -> str:
    safe_id = user_id.replace('-', '')[:24]
    return f'{VOLUME_PREFIX}{safe_id}'


def _agent_url(host_port: int) -> str:
    return f'http://{AGENT_HOST}:{host_port}/v1'


def _gateway_url(gateway_port: int) -> str:
    """Return the base URL for a container's Myah standalone aiohttp runner.

    Mirrors :func:`_agent_url` but for ``MYAH_GATEWAY_PORT`` (8643). Used
    by /myah/v1/* and /myah/health requests. Returns no ``/v1`` suffix
    because all paths on this surface already include the version segment.
    """
    return f'http://{AGENT_HOST}:{gateway_port}'


async def _wait_for_ready(
    host_port: int,
    timeout: int = CONTAINER_READY_TIMEOUT,
    user_id: str = '',
    web_port: Optional[int] = None,
    web_session_token: Optional[str] = None,
) -> tuple[bool, dict]:
    """Poll the Hermes health endpoint until it returns 200 or timeout expires.

    Returns (ready, health_body) where health_body is the parsed JSON from the
    last successful health check response (or {} on timeout/parse error).
    Callers can inspect health_body['checks'] to detect degraded conditions
    (e.g. missing LLM credentials) and surface them to users immediately.

    When ``web_port`` AND ``web_session_token`` are both provided, this also
    polls the ``hermes dashboard`` plugin's ``/api/plugins/myah-admin/health``
    endpoint and only returns ready once BOTH are responding. Without this,
    the chat gateway (port 8642) becomes healthy in ~3s while the dashboard
    (port 9119) is still loading the FastAPI app — early HTTP calls into the
    dashboard hit ``httpx.ReadError`` (TCP accepts then drops the connection)
    and surface as platform 500s. Probing the dashboard first eliminates the
    race at the cost of a few extra seconds of spawn time.
    """
    chat_url = f'http://{AGENT_HOST}:{host_port}/health'
    web_url = (
        f'http://{AGENT_HOST}:{web_port}/api/plugins/myah-admin/health' if web_port and web_session_token else None
    )
    web_headers = {'Authorization': f'Bearer {web_session_token}'} if web_session_token else {}
    _start = time.monotonic()
    deadline = _start + timeout
    chat_body: dict = {}
    chat_ready = False
    async with httpx.AsyncClient() as client:
        while time.monotonic() < deadline:
            if not chat_ready:
                try:
                    resp = await client.get(chat_url, timeout=2.0)
                    if resp.status_code == 200:
                        chat_ready = True
                        try:
                            chat_body = resp.json()
                        except Exception:
                            chat_body = {}
                except httpx.TransportError:
                    pass
            if chat_ready and web_url is None:
                # Caller didn't ask for dashboard probe — chat-only is enough.
                if _record_container_startup is not None:
                    try:
                        _record_container_startup(time.monotonic() - _start, user_id=user_id)
                    except Exception:
                        pass
                return True, chat_body
            if chat_ready and web_url is not None:
                try:
                    web_resp = await client.get(web_url, headers=web_headers, timeout=2.0)
                    if web_resp.status_code == 200:
                        if _record_container_startup is not None:
                            try:
                                _record_container_startup(time.monotonic() - _start, user_id=user_id)
                            except Exception:
                                pass
                        return True, chat_body
                except (httpx.TransportError, httpx.RemoteProtocolError):
                    pass
            await asyncio.sleep(1)
    return False, chat_body


# ─── Core lifecycle functions ─────────────────────────────────────────────────


# Per-user spawn locks. The frontend's bootstrap path fires ~10 parallel
# requests on page load (/providers/catalog, /providers/models, /agent/toolsets,
# /agent/commands, ...), each of which calls get_or_create_container for the
# same user_id. After a deploy stops per-user agent containers, the DB row is
# still 'running' but the container is gone — so every concurrent caller fails
# the 3 s health probe, calls _start_container, and races inside
# _start_container_sync to allocate a free port + run a new container with
# the same name. The Docker daemon serializes container CREATE by name so only
# one wins, but the losers' calls to _start_container_sync still return a
# host_port from _free_port() that no container is actually listening on,
# leading to a full 180 s _wait_for_ready timeout per loser. The user-visible
# symptom is a 3+ minute hang on the chat page after every deploy.
#
# Serializing get_or_create_container per user_id eliminates the race: the
# first caller acquires the lock, spawns the container, updates the DB row,
# releases the lock; subsequent waiters acquire it, re-read the now-running
# record, see _recently_active=True, and short-circuit to immediate return.
# Different users do not block each other.
_spawn_locks: dict[str, asyncio.Lock] = {}


def _build_oss_container_stub(user_id: str) -> ContainerModel:
    """Return a synthetic ContainerModel pointing at the host-side Hermes.

    OSS mode: there is no Docker container — the user runs `hermes gateway
    start` on the host. The chat / confirm / secret / cron / media paths in
    `routers/openai.py` and friends call ``get_or_create_container`` and
    then read ``record.gateway_port`` / ``record.host_port`` /
    ``record.web_port`` to construct upstream URLs. By returning a stub
    populated with the OSS port helpers' values, those paths "just work"
    without per-callsite changes.

    Token: the synthetic record's ``web_session_token`` mirrors
    ``MYAH_HERMES_WEB_SESSION_TOKEN`` so ``hermes_web.web_call`` (which
    historically reads from the container row) keeps authenticating
    correctly. Empty string is acceptable for a trivial single-tenant
    deployment that didn't configure ``HERMES_WEB_SESSION_TOKEN``.
    """
    from myah.utils.hermes_web import (
        _oss_chat_port,
        _oss_gateway_port,
        _oss_web_port,
        _oss_web_session_token,
    )

    now = int(time.time())
    return ContainerModel(
        id=f'oss-{user_id}',
        user_id=user_id,
        container_id=None,
        container_name=None,
        host_port=_oss_chat_port(),
        vite_port=None,
        vnc_port=None,
        web_port=_oss_web_port(),
        gateway_port=_oss_gateway_port(),
        web_session_token=_oss_web_session_token(),
        status='running',
        created_at=now,
        last_active=now,
    )


async def get_or_create_container(user_id: str, event_emitter=None) -> ContainerModel:
    """
    Return the running container record for user_id.
    Creates a new container on first call; restarts on crash.
    Containers are always-on — no hibernation.

    Credentials are no longer injected as env vars at container creation time.
    The Hermes-native provider catalog (PR 2) manages credentials inside the
    container — they persist in the agent volume and are never baked into the
    container environment.

    event_emitter — optional async callable matching Open WebUI's event emitter signature.
    When provided, status events are pushed to the frontend during slow operations.

    Concurrency: serialized per user_id via ``_spawn_locks`` so parallel
    bootstrap calls from a single user share a single spawn attempt instead of
    racing. See the ``_spawn_locks`` comment above for the failure mode this
    prevents.

    OSS mode: return a synthetic ContainerModel populated from the
    ``MYAH_HERMES_*_PORT`` env helpers. No Docker call is made; the
    record's ``host_port`` / ``gateway_port`` / ``web_port`` / token are
    the OSS host-side values so the chat / confirm / secret / cron / media
    paths in ``routers/openai.py`` etc. route to the user's host-side
    ``hermes gateway start`` without per-callsite changes. See
    ``_build_oss_container_stub`` above for the canonical stub.
    """
    from myah.utils.hermes_web import is_oss_mode  # local import to avoid cycle

    if is_oss_mode():
        return _build_oss_container_stub(user_id)

    # ``setdefault`` on a dict is atomic in single-threaded asyncio, so two
    # coroutines reaching here simultaneously for a new user_id end up with
    # the same Lock object even though both call setdefault.
    lock = _spawn_locks.setdefault(user_id, asyncio.Lock())
    async with lock:
        return await _get_or_create_container_locked(user_id, event_emitter)


async def _get_or_create_container_locked(user_id: str, event_emitter=None) -> ContainerModel:
    """Lock-protected body of ``get_or_create_container``. Do not call directly —
    callers must go through ``get_or_create_container`` so spawn races are
    serialized per user."""
    # OSS-split: honcho is hosted-only. This function is only reached when
    # is_oss_mode() returns False (see get_or_create_container above), so
    # importing services.honcho here is safe — the OSS build doesn't ship
    # the module, but it never executes this function either.
    from myah.services.honcho import honcho_service

    record = await asyncio.to_thread(Containers.get_by_user_id, user_id)

    if record is None:
        honcho_config = await asyncio.to_thread(honcho_service.get_or_provision, user_id)
        honcho_api_key = honcho_config.api_key if honcho_config.provisioned else ''
        honcho_workspace_id = honcho_config.workspace_id

        if event_emitter:
            await event_emitter({'type': 'status', 'data': {'description': 'Starting your agent...', 'done': False}})
        record = await asyncio.to_thread(Containers.create, user_id)
        record = await _start_container(
            user_id,
            record,
            honcho_api_key=honcho_api_key,
            honcho_workspace_id=honcho_workspace_id,
        )
    elif record.status == 'running':
        # Skip the health probe if the container was confirmed alive recently
        # (within 30 s).  This avoids a round-trip TCP+HTTP hit on every single
        # message when the container is healthy and warm.
        _recently_active = record.last_active is not None and (time.time() - record.last_active) < 30
        if _recently_active:
            _running_ready = True
        else:
            _running_ready, _ = await _wait_for_ready(record.host_port, timeout=3)
        if record.host_port and not _running_ready:
            logger.warning(f'Container for user {user_id} marked running but unreachable — restarting')
            await asyncio.to_thread(lambda: Containers.update_status(user_id, status='error'))
            honcho_config = await asyncio.to_thread(honcho_service.get_or_provision, user_id)
            honcho_api_key = honcho_config.api_key if honcho_config.provisioned else ''
            honcho_workspace_id = honcho_config.workspace_id
            if event_emitter:
                await event_emitter(
                    {'type': 'status', 'data': {'description': 'Reconnecting to your agent...', 'done': False}}
                )
            record = await _start_container(
                user_id,
                record,
                honcho_api_key=honcho_api_key,
                honcho_workspace_id=honcho_workspace_id,
            )
        else:
            await asyncio.to_thread(Containers.touch, user_id)
    elif record.status in ('creating', 'error', 'hibernated', 'stopped'):
        honcho_config = await asyncio.to_thread(honcho_service.get_or_provision, user_id)
        honcho_api_key = honcho_config.api_key if honcho_config.provisioned else ''
        honcho_workspace_id = honcho_config.workspace_id
        if event_emitter:
            await event_emitter(
                {'type': 'status', 'data': {'description': 'Reconnecting to your agent...', 'done': False}}
            )
        record = await _start_container(
            user_id,
            record,
            honcho_api_key=honcho_api_key,
            honcho_workspace_id=honcho_workspace_id,
        )

    if event_emitter:
        await event_emitter({'type': 'status', 'data': {'description': 'Agent ready', 'done': True}})

    return record


def _start_container_sync(
    user_id: str,
    honcho_api_key: str = '',
    honcho_workspace_id: str = '',
) -> dict:
    """
    Synchronous Docker work for starting a container.
    Returns a dict with container info or raises HTTPException.
    Must be called via asyncio.to_thread().

    Credentials are not injected as env vars — the Hermes-native provider
    catalog (PR 2) manages them inside the agent volume.
    """
    client = _docker_client()
    name = _container_name(user_id)
    volume = _volume_name(user_id)
    host_port = _free_port()
    vite_host_port = _free_port()
    vnc_host_port = _free_port()
    web_host_port = _free_port()
    # Tier 2A standalone-runner refactor — separate host port maps to
    # AGENT_GATEWAY_PORT (8643) inside the container. Falls back to
    # host_port at read time for rows where gateway_port IS NULL.
    gateway_host_port = _free_port()
    # Per-container session token shared with `hermes dashboard` via the
    # HERMES_WEB_SESSION_TOKEN env var. 32 bytes of url-safe random — same
    # entropy class hermes uses for its default token.
    web_session_token = secrets.token_urlsafe(32)

    try:
        existing = client.containers.get(name)
        existing_port = next(
            (int(v[0]['HostPort']) for k, v in existing.ports.items() if v),
            None,
        )
        if existing.status == 'running' and existing_port:
            api_port = next(
                (int(v[0]['HostPort']) for k, v in existing.ports.items() if k == f'{AGENT_API_PORT}/tcp' and v),
                None,
            )
            vite_port_existing = next(
                (int(v[0]['HostPort']) for k, v in existing.ports.items() if k == f'{AGENT_VITE_PORT}/tcp' and v),
                None,
            )
            vnc_port_existing = next(
                (int(v[0]['HostPort']) for k, v in existing.ports.items() if k == f'{AGENT_VNC_PORT}/tcp' and v),
                None,
            )
            web_port_existing = next(
                (int(v[0]['HostPort']) for k, v in existing.ports.items() if k == f'{AGENT_WEB_PORT}/tcp' and v),
                None,
            )
            gateway_port_existing = next(
                (int(v[0]['HostPort']) for k, v in existing.ports.items() if k == f'{AGENT_GATEWAY_PORT}/tcp' and v),
                None,
            )
            return {
                'container_id': existing.id,
                'name': name,
                'host_port': api_port or existing_port,
                'vite_port': vite_port_existing,
                'vnc_port': vnc_port_existing,
                # Adopted containers may pre-date the web_port mapping. When
                # they do, web_port_existing is None and the DB row keeps
                # whatever it had (typically NULL); /web-health then
                # correctly returns 503 until a restart.
                'web_port': web_port_existing,
                'gateway_port': gateway_port_existing,
                # Token is NOT regenerated for adopted containers — the
                # running container's HERMES_WEB_SESSION_TOKEN is
                # whatever was passed to it on its original docker run
                # (or generated by entrypoint.sh). The platform retains
                # the token previously recorded in the DB row.
                'web_session_token': None,
                'needs_health_check': True,
                'adopt': True,
            }
        try:
            existing.remove(force=True)
            logger.info(f'Removed stale container {name}')
        except APIError as api_exc:
            # 409 Conflict — another process is already removing this container.
            # Treat as a benign race: the container is going away regardless.
            if api_exc.response is not None and api_exc.response.status_code == 409:
                logger.warning(f'Container {name} removal already in progress (409), skipping')
            else:
                raise
    except NotFound:
        pass

    env = {
        'API_SERVER_KEY': AGENT_BEARER_TOKEN,
        'HERMES_HOME': '/data/.hermes',
        'MYAH_PLATFORM_WEBHOOK_URL': f'http://{PLATFORM_WEBHOOK_HOST}:{PLATFORM_PORT}',
        # ── Myah: Media attachments — adapter fetches bytes from platform ────────────
        'MYAH_PLATFORM_BASE_URL': f'http://{PLATFORM_WEBHOOK_HOST}:{PLATFORM_PORT}',
        'MYAH_PLATFORM_BEARER': AGENT_BEARER_TOKEN,
        # Keep the stock plugin's fail-closed adapter auth and cron watcher
        # working even if entrypoint-level .env alias writing changes.
        #
        # SECURITY-BOUNDARY ASSUMPTION (per spec-review 2026-05-19 follow-up
        # #1 on PR #200): we deliberately set MYAH_ADAPTER_AUTH_KEY,
        # MYAH_AGENT_BEARER_TOKEN, MYAH_PLATFORM_BEARER, and API_SERVER_KEY
        # ALL to the same `AGENT_BEARER_TOKEN` value. This is acceptable
        # TODAY because the plugin treats every name as the same shared
        # secret on the platform↔agent boundary — there's no scope or
        # capability separation between the adapter-auth handshake, the
        # cron-watcher webhook bearer, and the api-server admin key.
        #
        # If a future plugin release splits these into separate scopes
        # (e.g. adapter-auth becomes a narrower capability than the cron
        # bearer), this co-assignment becomes a privilege-escalation
        # vector. The audit gate is: any time the plugin's `_check_auth`
        # or `cron_watcher` starts reading a NEW env-var name AND the
        # plugin docs imply that name should hold a different secret,
        # break this co-assignment and provision the names independently.
        'MYAH_ADAPTER_AUTH_KEY': AGENT_BEARER_TOKEN,
        'MYAH_AGENT_BEARER_TOKEN': AGENT_BEARER_TOKEN,
        # ────────────────────────────────────────────────────────────────────────────
        'MYAH_USER_ID': user_id,
        # ── Myah: suppress upstream "no home channel" warning ──────────────
        # Upstream's gateway/run.py:6802 (at submodule SHA 87b22d309) calls
        # _home_target_env_var('myah'), which goes through cron/scheduler.py
        # _resolve_home_env_var() → looks up the plugin's PlatformEntry and
        # returns its cron_deliver_env_var. The plugin registers
        # cron_deliver_env_var="MYAH_HOME_CHAT" (see
        # plugins/myah-hermes-plugin/.../myah_platform/__init__.py:344), so
        # the env var the gateway actually reads is MYAH_HOME_CHAT — NOT
        # MYAH_HOME_CHANNEL. Setting any non-empty value suppresses the
        # "📬 No home channel is set" first-message prompt.
        #
        # PR #109 set MYAH_HOME_CHANNEL='disabled' alone — that var is never
        # read at runtime, so the warning kept firing in production. The
        # plugin-side test in test_myah_platform_contract.py pins the
        # cron_deliver_env_var name; this companion entry pins the value.
        #
        # MYAH_HOME_CHANNEL='disabled' is preserved as a defensive fallback
        # for the path where plugin discovery fails and _resolve_home_env_var
        # cannot find the PlatformEntry — the legacy hardcoded lookup table
        # at cron/scheduler.py:_HOME_TARGET_ENV_VARS is still consulted first.
        #
        # Long-term fix: file an upstream U-HOMEWARN PR adding
        # PlatformEntry.skip_home_channel_warning so plugin platforms with
        # no home-channel concept can declare opt-out registry-side. Once
        # upstream merges, delete these env injections.
        'MYAH_HOME_CHAT': 'disabled',  # primary — registry-resolved env var
        'MYAH_HOME_CHANNEL': 'disabled',  # legacy fallback
        # ────────────────────────────────────────────────────────────────────
        'MYAH_AGENT_TOKEN': AGENT_BEARER_TOKEN,
        # ── Myah: hermes dashboard session token (Workstream A Phase 0) ─────────────
        # The container's `hermes dashboard` reads this var (see
        # agent/hermes/hermes_cli/web_server.py:_SESSION_TOKEN). The same
        # value is persisted on the Container DB row so the platform can
        # send `Authorization: Bearer <token>` to /api/plugins/myah-admin/*.
        'HERMES_WEB_SESSION_TOKEN': web_session_token,
        # ────────────────────────────────────────────────────────────────────────────
        'HONCHO_API_KEY': honcho_api_key,
        'HONCHO_WORKSPACE_ID': honcho_workspace_id,
        'HONCHO_PEER_NAME': user_id,
        'SENTRY_DSN_AGENT': os.environ.get('SENTRY_DSN_AGENT', ''),
        # ── Myah: media allowlist for agent's /myah/v1/media endpoint ───────────────
        # The agent's _myah_allowed_media_roots already includes Hermes cache dirs
        # and terminal.cwd (=/root). But agents have free choice via execute_code
        # and frequently write to /data, /tmp, or /workspace — all of which are
        # already in the platform-side _BARE_PATH_RE detection regex. Without
        # widening the agent's allowlist, those files return 403 from the agent's
        # media endpoint and persist_and_rewrite drops them. Override via
        # MYAH_AGENT_MEDIA_ROOTS env var on the platform process if you need
        # different paths (e.g. self-hosted Hermes with a custom workspace).
        # Each user has their own container (so cross-user leak is impossible)
        # and only the platform can call /myah/v1/media (bearer auth), so the
        # security delta of allowing /data is minimal — the agent could leak
        # its own container's secrets via execute_code anyway.
        'MYAH_MEDIA_ALLOWED_ROOTS': os.environ.get('MYAH_AGENT_MEDIA_ROOTS', '/data:/tmp:/workspace'),
        # ────────────────────────────────────────────────────────────────────────────
    }

    try:
        # Agent containers run on the default `bridge` Docker network and
        # reach the platform via the host's docker0 gateway. Port 8080 on
        # the host IS the platform port (see docker-compose.prod.yaml's
        # explicit '8080:8080' publish), so MYAH_PLATFORM_BASE_URL works
        # without any custom-network plumbing.
        # Per-user image override (Phase 7.2 canary mechanism) — falls back
        # to AGENT_IMAGE when the user has no entry in
        # MYAH_AGENT_IMAGE_OVERRIDES.
        _image = _image_for_user(user_id)
        if _image != AGENT_IMAGE:
            logger.info(f'[canary] user {user_id} pinned to {_image} (default would have been {AGENT_IMAGE})')
        _container_run_kwargs = dict(
            image=_image,
            name=name,
            detach=True,
            remove=False,
            mem_limit=AGENT_RAM_LIMIT,
            cpu_quota=AGENT_CPU_QUOTA,
            cpu_period=AGENT_CPU_PERIOD,
            ports={
                f'{AGENT_API_PORT}/tcp': host_port,
                f'{AGENT_VITE_PORT}/tcp': vite_host_port,
                f'{AGENT_VNC_PORT}/tcp': vnc_host_port,
                f'{AGENT_WEB_PORT}/tcp': web_host_port,
                f'{AGENT_GATEWAY_PORT}/tcp': gateway_host_port,
            },
            volumes={
                volume: {'bind': '/data/.hermes', 'mode': 'rw'},
            },
            environment=env,
            restart_policy={'Name': 'unless-stopped'},
            # Ensure host.docker.internal resolves inside the container.
            # Docker Desktop (macOS/Windows) provides it natively; on Linux
            # 'host-gateway' maps it to the host's bridge gateway IP.
            extra_hosts={'host.docker.internal': 'host-gateway'},
        )
        container = client.containers.run(**_container_run_kwargs)
    except DockerException as exc:
        Containers.update_status(user_id, status='error')
        raise HTTPException(status_code=500, detail=f'Failed to start agent container: {exc}')

    Containers.update_status(
        user_id,
        status='creating',
        container_id=container.id,
        container_name=name,
        host_port=host_port,
        vite_port=vite_host_port,
        vnc_port=vnc_host_port,
        web_port=web_host_port,
        gateway_port=gateway_host_port,
        web_session_token=web_session_token,
    )

    return {
        'container_id': container.id,
        'name': name,
        'host_port': host_port,
        'vite_port': vite_host_port,
        'vnc_port': vnc_host_port,
        'web_port': web_host_port,
        'gateway_port': gateway_host_port,
        'web_session_token': web_session_token,
        'needs_health_check': True,
        'adopt': False,
    }


def _build_catalog_map(catalog_data: dict) -> dict:
    """Normalise a raw providers catalog response into {slug: [model_id, ...]}."""
    from myah.utils.agent_proxy import normalize_catalog_models

    result: dict = {}
    for slug, entry in catalog_data.items():
        if isinstance(entry, dict):
            raw_models = entry.get('curated_models', [])
        elif isinstance(entry, list):
            raw_models = entry
        else:
            raw_models = []
        result[slug] = normalize_catalog_models(raw_models)
    return result


def _extract_provider_from_config(config_body: dict) -> str:
    """Extract the provider slug from a Hermes config body.

    Handles both dict-form model (PR 1c Appendix A) and legacy bare-string form.
    Returns an empty string when no provider can be determined.
    """
    raw_model = config_body.get('model', '')
    if isinstance(raw_model, dict):
        return str(raw_model.get('provider', '') or '').strip()
    return str(raw_model or '').split('/')[0].strip()


def _aux_already_seeded(config_body: dict) -> bool:
    """Return True if any AUX_DEFAULT_TASKS task already has a provider configured.

    Used to guard against re-seeding on container restarts, which would clobber
    user-configured auxiliary model values.
    """
    existing_aux = config_body.get('auxiliary', {}) or {}
    return any(existing_aux.get(task, {}).get('provider') for task in AUX_DEFAULT_TASKS)


async def _resolve_auxiliary_patch(user, provider: str) -> dict:
    """Fetch the live provider catalog and build the auxiliary PUT payload.

    Returns a dict of {task: {provider, model}} entries ready to PUT into
    /api/config, or an empty dict if no models could be resolved.
    """
    from myah.utils.hermes_web import web_call

    catalog_result = await web_call(user, 'GET', '/api/plugins/myah-admin/providers')
    catalog_raw = catalog_result['body'] or {} if catalog_result['status'] < 400 else {}
    catalog_map = _build_catalog_map(catalog_raw)

    resolved_default = _resolve_aux_default(provider, 'title_generation', catalog=catalog_map)
    resolved_vision = _resolve_aux_default(provider, 'vision', catalog=catalog_map)

    auxiliary: dict = {}
    if resolved_default is not None:
        for task in AUX_DEFAULT_TASKS:
            auxiliary[task] = {'provider': provider, 'model': resolved_default}
    if resolved_vision is not None:
        auxiliary['vision'] = {'provider': provider, 'model': resolved_vision}
    return auxiliary


async def _seed_aux_defaults_for_user(user_id: str) -> None:
    """Seed auxiliary model defaults into a freshly-spawned container.

    Called only once — immediately after first-spawn healthcheck passes.
    Adopted (pre-existing) containers are never re-seeded to avoid clobbering
    user-configured values.  Any failure is logged as a warning and swallowed;
    the container spawn must not fail due to seeding.
    """
    from myah.utils.hermes_web import web_call

    try:
        user = await asyncio.to_thread(Users.get_user_by_id, user_id)
        if user is None:
            logger.warning(f'_seed_aux_defaults_for_user: user {user_id!r} not found — skipping seed')
            return

        # 1. Fetch the current agent config to discover the active provider slug.
        config_result = await web_call(user, 'GET', '/api/plugins/myah-admin/config')
        if config_result['status'] >= 400:
            logger.warning(
                f'_seed_aux_defaults_for_user: config fetch failed '
                f'(user={user_id}, status={config_result["status"]}) — skipping seed'
            )
            return

        config_body = config_result['body'] or {}
        # model: may be a dict {name, provider, ...} (PR 1c Appendix A) or legacy bare string
        provider = _extract_provider_from_config(config_body)
        if not provider:
            logger.warning(f'_seed_aux_defaults_for_user: no provider in config for user={user_id} — skipping seed')
            return

        # 2a. Guard: skip re-seed if the user already has per-task auxiliary config.
        # This prevents restart_container from clobbering user-configured aux values.
        if _aux_already_seeded(config_body):
            logger.info(f'_seed_aux_defaults_for_user: existing aux config found for user={user_id} — skipping re-seed')
            return

        # 2b. Fetch catalog and resolve auxiliary patch payload.
        auxiliary = await _resolve_auxiliary_patch(user, provider)
        if not auxiliary:
            logger.warning(
                f'_seed_aux_defaults_for_user: no aux defaults resolved '
                f'for user={user_id} provider={provider!r} — skipping PATCH'
            )
            return

        # 4. Issue a single nested PUT — mirrors seed_aux_defaults in agent_config.py.
        patch_result = await web_call(
            user, 'PUT', '/api/plugins/myah-admin/config', json_body={'auxiliary': auxiliary}
        )
        if patch_result['status'] >= 400:
            logger.warning(
                f'_seed_aux_defaults_for_user: PUT /api/plugins/myah-admin/config failed '
                f'(user={user_id}, provider={provider!r}, status={patch_result["status"]})'
            )
        else:
            logger.info(
                f'_seed_aux_defaults_for_user: seeded auxiliary defaults '
                f'for user={user_id} provider={provider!r} tasks={list(auxiliary)}'
            )
    except Exception as exc:
        logger.warning(f'_seed_aux_defaults_for_user: unexpected error for user={user_id}: {exc}')


async def _start_container(
    user_id: str,
    record: ContainerModel,
    honcho_api_key: str = '',
    honcho_workspace_id: str = '',
) -> ContainerModel:
    info = await asyncio.to_thread(_start_container_sync, user_id, honcho_api_key, honcho_workspace_id)

    if info.get('adopt'):
        healthy, _ = await _wait_for_ready(info['host_port'], timeout=5)
        if healthy:
            logger.info(f'Adopting existing healthy container {info["name"]} on port {info["host_port"]}')
            record = await asyncio.to_thread(
                lambda: Containers.update_status(
                    user_id,
                    status='running',
                    container_id=info['container_id'],
                    container_name=info['name'],
                    host_port=info['host_port'],
                    vite_port=info['vite_port'],
                    vnc_port=info.get('vnc_port'),
                    # Adopted containers carry whatever web_port docker
                    # already mapped (may be None for legacy containers
                    # spawned before this column existed). The token is
                    # never overwritten on adoption — see _start_container_sync.
                    web_port=info.get('web_port'),
                    gateway_port=info.get('gateway_port'),  # ← Tier 2A: persist standalone-runner port on adopt
                )
            )
            return record

        def _remove_and_recreate():
            client = _docker_client()
            try:
                existing = client.containers.get(info['name'])
                existing.remove(force=True)
            except (NotFound, DockerException):
                pass

        await asyncio.to_thread(_remove_and_recreate)
        return await _start_container(user_id, record, honcho_api_key, honcho_workspace_id)

    # Probe BOTH the chat gateway (8642) and the dashboard plugin (9119) so
    # we don't return until the dashboard FastAPI app has finished loading.
    # Without the dashboard probe, the immediate-post-spawn call to
    # _seed_aux_defaults_for_user races the dashboard startup and surfaces
    # as a platform 500 (httpx.ReadError on a connection that's accepted
    # then dropped by the half-loaded server).
    ready, health_body = await _wait_for_ready(
        info['host_port'],
        user_id=user_id,
        web_port=info.get('web_port'),
        web_session_token=info.get('web_session_token'),
    )
    if not ready:
        container_name = info.get('name', 'unknown')
        host_port = info.get('host_port', 'unknown')
        logger.error(
            f'Container for user {user_id} did not become healthy in time '
            f'(container={container_name}, port={host_port}, timeout={CONTAINER_READY_TIMEOUT}s)'
        )
        await asyncio.to_thread(lambda: Containers.update_status(user_id, status='error'))
        raise HTTPException(status_code=503, detail='Agent container failed to start in time')

    # ── Credential validation ─────────────────────────────────────────────
    # The Hermes /health endpoint validates LLM credentials and memory
    # provider config. Surface failures immediately so users see a clear
    # error message instead of their first message hanging indefinitely.
    checks = health_body.get('checks', {}) if isinstance(health_body, dict) else {}
    if checks and not checks.get('llm_credentials', True):
        logger.warning(f'Agent container for user {user_id} started but LLM credentials are invalid')
        raise HTTPException(
            status_code=503,
            detail=(
                'Your agent started but could not reach the LLM provider. '
                'Please verify your API key is correct in Settings.'
            ),
        )

    record = await asyncio.to_thread(lambda: Containers.update_status(user_id, status='running'))
    logger.info(f'Container {info["name"]} started for user {user_id} on port {info["host_port"]}')

    # ── Myah: seed aux defaults on first spawn only ───────────────────────────
    # Existing containers (adopt=True) return early above and never reach here,
    # so this fires exactly once per container lifetime.
    await _seed_aux_defaults_for_user(user_id)
    # ─────────────────────────────────────────────────────────────────────────

    return record


async def _init_artifact_project(container_name: str, process_id: str) -> bool:
    """
    Ensure the shared Vite project exists at /data/.hermes/artifacts/ and create
    the per-process subdirectory (src/processes/{process_id}/App.jsx and
    data/{process_id}/state.json). Starts Vite if not already running.
    """
    script = f"""
import shutil
from pathlib import Path

process_id = {repr(process_id)}
root = Path("/data/.hermes/artifacts")
root.mkdir(parents=True, exist_ok=True)
tmpl = Path("/opt/myah/artifact-template")

for item in ["package.json", "vite.config.js", "index.html"]:
    dst = root / item
    if not dst.exists():
        shutil.copy(tmpl / item, dst)

(root / "src").mkdir(exist_ok=True)
(root / "src" / "processes").mkdir(exist_ok=True)

main_dst = root / "src" / "main.jsx"
if not main_dst.exists():
    shutil.copy(tmpl / "src" / "main.jsx", main_dst)

nm = root / "node_modules"
if not nm.exists():
    shutil.copytree(tmpl / "node_modules", nm, symlinks=True)

proc_src = root / "src" / "processes" / process_id
proc_src.mkdir(parents=True, exist_ok=True)
app_dst = proc_src / "App.jsx"
if not app_dst.exists():
    shutil.copy(tmpl / "src" / "App.jsx", app_dst)

data_dir = root / "data" / process_id
data_dir.mkdir(parents=True, exist_ok=True)
state_dst = data_dir / "state.json"
if not state_dst.exists():
    state_dst.write_text("{{}}")

print("ok")
"""
    try:
        write_proc = await asyncio.create_subprocess_exec(
            'docker',
            'exec',
            '-i',
            container_name,
            'python3',
            '-c',
            'import sys; open("/tmp/_init_artifact.py","w").write(sys.stdin.read())',
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(write_proc.communicate(input=script.encode()), timeout=10.0)

        proc = await asyncio.create_subprocess_exec(
            'docker',
            'exec',
            container_name,
            'python3',
            '/tmp/_init_artifact.py',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60.0)
        if proc.returncode != 0:
            logger.warning(f'_init_artifact_project failed: {stderr.decode()[:300]}')
            return False

        proc2 = await asyncio.create_subprocess_exec(
            'docker',
            'exec',
            container_name,
            'supervisorctl',
            'start',
            'vite',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(proc2.communicate(), timeout=15.0)
        logger.info(f'Artifact project initialized for process {process_id} in {container_name}')
        return True
    except Exception as exc:
        logger.warning(f'_init_artifact_project exception: {exc}')
        return False


def _delete_container_sync(user_id: str, delete_volume: bool = False) -> bool:
    """Synchronous container deletion. Must be called via asyncio.to_thread()."""
    record = Containers.get_by_user_id(user_id)
    if not record:
        return False

    client = _docker_client()
    if record.container_name:
        try:
            container = client.containers.get(record.container_name)
            container.remove(force=True)
        except NotFound:
            pass
        except DockerException as exc:
            logger.error(f'Error removing container for {user_id}: {exc}')

    if delete_volume:
        volume_name = _volume_name(user_id)
        try:
            vol = client.volumes.get(volume_name)
            vol.remove(force=True)
        except NotFound:
            pass
        except DockerException as exc:
            logger.error(f'Error removing volume {volume_name}: {exc}')

    Containers.delete(user_id)
    logger.info(f'Container for user {user_id} deleted (volume_removed={delete_volume})')
    return True


async def delete_container(user_id: str, delete_volume: bool = False) -> bool:
    """Destroy a container and optionally its data volume (account deletion)."""
    return await asyncio.to_thread(_delete_container_sync, user_id, delete_volume)


async def health_check(user_id: str) -> bool:
    """Return True if the user's container is running and responding."""
    record = await asyncio.to_thread(Containers.get_by_user_id, user_id)
    if not record or record.status != 'running' or not record.host_port:
        return False
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f'{_agent_url(record.host_port)}/health', timeout=3.0)
            return resp.status_code == 200
    except httpx.TransportError:
        return False


async def restart_container(user_id: str) -> ContainerModel:
    """Stop and recreate a container with current user settings (model/key changes)."""
    await asyncio.to_thread(_delete_container_sync, user_id, delete_volume=False)
    return await get_or_create_container(user_id)


# ─── REST API ─────────────────────────────────────────────────────────────────


class ContainerStatusResponse(BaseModel):
    user_id: str
    status: str
    host_port: int | None = None
    healthy: bool


@router.get('/', response_model=list[ContainerModel])
async def list_containers(user: UserModel = Depends(get_admin_user)):
    """Admin: list all container records."""

    def _query():
        from myah.internal.db import get_db
        from myah.models.containers import Container

        with get_db() as db:
            rows = db.query(Container).all()
            return [ContainerModel.model_validate(r) for r in rows]

    return await asyncio.to_thread(_query)


@router.get('/me', response_model=ContainerStatusResponse)
async def get_my_container(user: UserModel = Depends(get_verified_user)):
    """Return the status of the current user's agent container."""
    record = await asyncio.to_thread(Containers.get_by_user_id, user.id)
    if not record:
        raise HTTPException(status_code=404, detail=ERROR_MESSAGES.NOT_FOUND)

    healthy = await health_check(user.id)
    return ContainerStatusResponse(
        user_id=user.id,
        status=record.status,
        host_port=record.host_port,
        healthy=healthy,
    )


@router.post('/restart')
async def restart_my_container(user: UserModel = Depends(get_verified_user)):
    """Restart the current user's container (picks up model/key changes)."""
    record = await restart_container(user.id)
    return ContainerStatusResponse(
        user_id=user.id,
        status=record.status,
        host_port=record.host_port,
        healthy=True,
    )


@router.delete('/{user_id}')
async def remove_container(
    user_id: str,
    delete_volume: bool = False,
    user: UserModel = Depends(get_admin_user),
):
    """Admin: destroy a user's container (and optionally its data volume)."""
    ok = await delete_container(user_id, delete_volume=delete_volume)
    if not ok:
        raise HTTPException(status_code=404, detail=ERROR_MESSAGES.NOT_FOUND)
    return {'ok': True}


@router.get('/{user_id}/vnc')
async def get_vnc_info(user_id: str, user: UserModel = Depends(get_verified_user)):
    """Return VNC connection details for the user's container.
    Used by the future takeover UI to establish a VNC/noVNC connection."""
    if user.id != user_id and user.role != 'admin':
        raise HTTPException(status_code=403, detail=ERROR_MESSAGES.ACCESS_PROHIBITED)
    record = await asyncio.to_thread(Containers.get_by_user_id, user_id)
    if not record or not record.vnc_port:
        raise HTTPException(status_code=404, detail='No VNC port available')
    return {'host': 'localhost', 'port': record.vnc_port}


@router.get('/{user_id}/web-health')
async def get_web_health(user_id: str, user: UserModel = Depends(get_verified_user)):
    """End-to-end probe of the per-container `hermes dashboard` server.

    Calls /api/plugins/myah-admin/health on the container through
    hermes_web.web_call so the entire path (DB lookup -> docker bridge ->
    hermes dashboard -> myah-admin plugin -> token check) is exercised.
    Used by Workstream A Phase 0 for post-deploy verification before any
    real admin endpoint depends on the path.
    """
    if user.id != user_id and user.role != 'admin':
        raise HTTPException(status_code=403, detail=ERROR_MESSAGES.ACCESS_PROHIBITED)

    # The user lookup is only needed to satisfy hermes_web.web_call's
    # signature (it reads container by user_id). For admins probing
    # another user's container, fetch that user from the DB.
    target_user = user if user.id == user_id else await asyncio.to_thread(Users.get_user_by_id, user_id)
    if target_user is None:
        raise HTTPException(status_code=404, detail=ERROR_MESSAGES.NOT_FOUND)

    from myah.utils.hermes_web import web_call

    result = await web_call(target_user, 'GET', '/api/plugins/myah-admin/health')
    return {
        'status': result['status'],
        'body': result['body'],
    }
