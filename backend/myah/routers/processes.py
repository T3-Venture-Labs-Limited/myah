import asyncio
import datetime as dt
import json
import os
import re
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from loguru import logger
from myah.models.containers import Containers
from myah.models.users import UserModel, Users
from myah.routers.containers import AGENT_HOST, _init_artifact_project, get_or_create_container
from myah.utils.auth import get_verified_user
from pydantic import BaseModel

try:
    from langfuse import observe as _lf_observe
except ImportError:

    def _lf_observe(*args, **kwargs):
        def decorator(fn):
            return fn

        return decorator if not args or not callable(args[0]) else args[0]

#####################
# Processes Router
# A process is a promise the agent keeps — a recurring act of
# attention it performs on your behalf, without being asked twice.
# This router bridges the platform to the cron scheduler living
# inside each user's agent container.
#
# Hermes API quirks (discovered by inspection of api_server.py):
#   - GET /api/jobs       → returns {"jobs": [...]}  (NOT a plain array)
#   - GET /api/jobs/{id}  → returns {"job": {...}}
#   - POST /api/jobs/{id}/run  (NOT /trigger)
#   - Passing include_disabled as a query param triggers a Python
#     class-attribute binding bug in Hermes — never pass it.
#####################

AGENT_BEARER_TOKEN = os.environ.get('MYAH_AGENT_BEARER_TOKEN', '')
UI_ACTION_COMPLETION_TIMEOUT = 120.0  # seconds


# ── OSS-mode gate ────────────────────────────────────────────────────
# The processes / cron-history UI is a hosted-only feature (spec §3
# Q-oss-cron-processes-ui, locked 2026-05-13). Every route on this
# router assumes a per-user agent container — for the docker-exec
# paths it does, and for the hermes-HTTP paths it does too because
# ``_ensure_container`` and ``_jobs_url`` both reach a per-user port
# the OSS variant doesn't have. In OSS mode the user runs Hermes
# themselves on the host; the platform has nothing to talk to.
#
# Rather than letting each route fail with whatever 503 / 404 / 500
# its underlying call path produces (inconsistent contract for the
# frontend), every route on this router gates at the top via
# ``_raise_if_oss_mode()`` and returns the same 501 with the upsell
# message below. The frontend upsell renderer matches the message
# once and shows a single card across the whole UI surface.
#
# The gate is wired in **two** places:
#
#   1. As a **router-level dependency** on the APIRouter constructor
#      below. FastAPI runs router-level deps BEFORE per-route deps,
#      so the 501 fires before ``Depends(get_verified_user)`` can
#      raise 401. This is what makes
#      ``curl http://.../api/v1/processes/`` (no auth token) return
#      501 instead of 401 in OSS mode — the contract the smoke test
#      in ``scripts/smoke-test-oss.sh`` (PR #167) asserts, and that
#      Phase D finding D3 in ``docs/oss-launch/vm-testing-followups.md``
#      identified as broken.
#
#   2. As an **inline call** at the top of each route handler
#      (belt-and-suspenders). Documents each route's hosted-only
#      nature in-place and stays effective even if a refactor
#      accidentally drops the router-level dependency.
#
# Webhooks (``/webhook/run-complete``, ``/webhook/run-started``) are
# intentionally NOT gated — they're inbound from a Hermes the user
# runs (on host in OSS, in a per-user container in hosted) and their
# underlying ``_inject_cron_output_to_chat`` helper only touches the
# platform DB. A sophisticated OSS user can still wire their host
# Hermes to webhook cron output back into Myah's chat history.
# ``_raise_if_oss_mode_unless_webhook`` handles that exemption at the
# router-dependency layer; the inline calls in the webhook handlers
# are simply absent.
OSS_PROCESSES_NOT_AVAILABLE = (
    'The processes / cron-history UI requires the hosted version of Myah. '
    'Manage your cron jobs via `hermes cron list/create/run` on your host, '
    'or sign up at https://app.myah.dev for the full UI.'
)


def _raise_if_oss_mode() -> None:
    """Raise 501 Not Implemented when running in OSS mode.

    Imported lazily so ``is_oss_mode()`` reads the env var fresh on
    every call — important for tests that monkeypatch
    ``MYAH_DEPLOYMENT_MODE`` at fixture time, after this module has
    already been imported."""
    from myah.utils.hermes_web import is_oss_mode

    if is_oss_mode():
        raise HTTPException(status_code=501, detail=OSS_PROCESSES_NOT_AVAILABLE)


def _raise_if_oss_mode_unless_webhook(request: Request) -> None:
    """Router-level OSS gate that exempts inbound webhook routes.

    Webhooks are inbound from the user's Hermes and only touch the
    platform DB — they don't depend on the per-user-container
    architecture, so they keep working in OSS. All other routes 501
    so the frontend's single-match upsell renderer has a stable
    contract.
    """
    # ``request.url.path`` is the full ASGI path including the router
    # prefix (``/api/v1/processes/webhook/run-complete``). Match on
    # the ``/webhook/`` segment to stay prefix-agnostic so the test
    # client (mounts at the same prefix) and the real app behave
    # identically.
    if '/webhook/' in request.url.path:
        return
    _raise_if_oss_mode()


# Per spec §6.3 + plan Task 2.3 (2026-05-19): the blanket router-level
# gate was removed so per-chat endpoints (list/create/get/update/delete/
# pause/resume/trigger/link-chat) can work in OSS. Container-only
# endpoints keep their inline ``_raise_if_oss_mode()`` calls so they
# still 501 with the upsell card. The webhook carve-out is preserved
# as the body of ``_raise_if_oss_mode_unless_webhook`` for any future
# re-introduction.
router = APIRouter()


def _jobs_url(host_port: int, path: str = '') -> str:
    """Build the URL for the Hermes cron jobs API inside the user's container."""
    return f'http://{AGENT_HOST}:{host_port}/api/jobs{path}'


def _auth_headers() -> dict:
    return {'Authorization': f'Bearer {AGENT_BEARER_TOKEN}'}


async def _ensure_container(user: UserModel) -> int:
    """
    Get-or-wake the user's agent container and return its host port.
    Raises HTTPException on failure.

    Fast path: if the container is already running, return the port directly
    without calling get_or_create_container (which triggers slow sync operations
    including Honcho provisioning that block the event loop with remote Postgres).
    """
    try:
        record = await asyncio.to_thread(Containers.get_by_user_id, user.id)
        if record and record.status == 'running' and record.host_port:
            return record.host_port
        # Container missing, hibernated, or in error — wake or create it
        record = await get_or_create_container(user.id)
        if not record or not record.host_port:
            raise HTTPException(status_code=503, detail='Agent container has no port assigned')
        return record.host_port
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f'Failed to ensure container for user {user.id}: {exc}')
        raise HTTPException(status_code=500, detail=f'Failed to start agent container: {exc}')


async def _hermes_get(url: str) -> Any:
    """GET a Hermes endpoint and return the raw parsed JSON body."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.get(url, headers=_auth_headers())
        except httpx.TransportError as exc:
            logger.warning(f'Processes proxy GET failed (transient): {exc}')
            raise HTTPException(status_code=503, detail='Agent container unreachable')

    if resp.status_code == 501:
        raise HTTPException(status_code=501, detail='Cron is not available in this agent build')
    if not resp.is_success:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return resp.json()


async def _hermes_post(url: str, body: dict | None = None) -> Any:
    """POST to a Hermes endpoint and return the raw parsed JSON body."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.post(url, headers=_auth_headers(), json=body or {})
        except httpx.TransportError as exc:
            logger.warning(f'Processes proxy POST failed (transient): {exc}')
            raise HTTPException(status_code=503, detail='Agent container unreachable')

    if resp.status_code == 501:
        raise HTTPException(status_code=501, detail='Cron is not available in this agent build')
    if not resp.is_success:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return resp.json()


async def _hermes_patch(url: str, body: dict) -> Any:
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.patch(url, headers=_auth_headers(), json=body)
        except httpx.TransportError as exc:
            logger.warning(f'Processes proxy PATCH failed (transient): {exc}')
            raise HTTPException(status_code=503, detail='Agent container unreachable')

    if resp.status_code == 501:
        raise HTTPException(status_code=501, detail='Cron is not available in this agent build')
    if not resp.is_success:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return resp.json()


async def _hermes_delete(url: str) -> Any:
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.delete(url, headers=_auth_headers())
        except httpx.TransportError as exc:
            logger.warning(f'Processes proxy DELETE failed (transient): {exc}')
            raise HTTPException(status_code=503, detail='Agent container unreachable')

    if resp.status_code == 501:
        raise HTTPException(status_code=501, detail='Cron is not available in this agent build')
    if not resp.is_success:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    if resp.status_code == 204 or not resp.content:
        return {'ok': True}
    return resp.json()


# ─── Myah adoption: safe job-metadata patch primitive (Phase 0) ────────────────
#
# Native Hermes ``PATCH /api/jobs/{id}`` (the ``_hermes_patch`` path above)
# silently DROPS any field outside its ``_UPDATE_ALLOWED_FIELDS`` allowlist
# (name/schedule/prompt/deliver/skills/skill/repeat/enabled) — verified in
# upstream ``gateway/platforms/api_server.py``. So ``origin`` / ``chat_id`` /
# ``myah`` cannot be persisted through it.
#
# Myah-owned routing metadata (``job.myah.chat_id`` etc.) is instead persisted
# through the myah-admin dashboard plugin, which runs *inside* the Hermes
# runtime and can call ``cron.jobs.update_job`` directly. ``update_job`` only
# blocks the immutable ``id`` field, so a ``{"myah": {...}}`` merge keeps
# native ``origin`` and ``deliver`` intact.
#
# This helper is the platform side of that contract; the dashboard endpoint
# ships in myah-hermes-plugin (see the plan's plugin follow-up). Until a plugin
# build exposes it, the helper fails *clearly* (501) rather than silently.
JOB_ID_RE = re.compile(r'^[a-f0-9]{12}$')
_ALLOWED_MYAH_METADATA_KEYS = frozenset({'myah'})
MYAH_METADATA_ENDPOINT_UNAVAILABLE = (
    'Cannot persist Myah cron metadata: the myah-admin dashboard job-metadata '
    'endpoint is unavailable. Upgrade myah-hermes-plugin to a build that exposes '
    'POST /api/plugins/myah-admin/cron/jobs/{job_id}/myah-metadata.'
)


def _validate_hermes_job_id(job_id: str) -> None:
    """Reject anything that is not a canonical 12-hex Hermes job id.

    Job ids are filesystem path components under the cron output dir, so a
    crafted id (path traversal, separators, wrong charset) must never reach a
    helper that interpolates it into a URL or filesystem path.
    """
    if not isinstance(job_id, str) or not JOB_ID_RE.match(job_id):
        raise HTTPException(status_code=400, detail='Invalid job ID format')


async def _patch_job_myah_metadata(user: UserModel, job_id: str, metadata: dict) -> Any:
    """Persist Myah-owned routing metadata onto a Hermes cron job.

    ``metadata`` must be shaped ``{"myah": {...}}`` — only the Myah-owned
    namespace is patchable here. Native ``origin`` / ``deliver`` are never
    transmitted, so a plugin-side merge cannot clobber them.

    Raises HTTPException(400) for an invalid job id or payload shape, and a
    clear non-2xx when the dashboard endpoint is unavailable (rather than
    pretending the write succeeded).
    """
    _validate_hermes_job_id(job_id)

    if not isinstance(metadata, dict) or not metadata:
        raise HTTPException(status_code=400, detail='metadata must be a non-empty object')
    unknown = set(metadata) - _ALLOWED_MYAH_METADATA_KEYS
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=(
                f'metadata may only patch Myah-owned keys {sorted(_ALLOWED_MYAH_METADATA_KEYS)}; '
                f'rejected {sorted(unknown)} (native origin/deliver are preserved, never patched here)'
            ),
        )
    if not isinstance(metadata.get('myah'), dict):
        raise HTTPException(status_code=400, detail="metadata['myah'] must be an object")

    from myah.utils.hermes_web import web_call

    try:
        result = await web_call(
            user,
            'POST',
            f'/api/plugins/myah-admin/cron/jobs/{job_id}/myah-metadata',
            json_body=metadata,
            timeout=10.0,
        )
    except HTTPException:
        # web_call already mapped connect/timeout/read errors to a clean status.
        raise
    except Exception as exc:
        # Any other transport quirk (e.g. an empty dashboard token producing an
        # illegal Authorization header in single-tenant OSS setups) must not
        # crash the request with an opaque 500 — surface it as retryable.
        logger.warning(f'Myah metadata patch transport error for job {job_id}: {exc}')
        raise HTTPException(
            status_code=503,
            detail='Could not reach the Hermes dashboard to persist Myah metadata',
        )
    status = result.get('status') if isinstance(result, dict) else None
    if status == 404:
        # Plugin too old / endpoint not mounted — surface clearly, don't swallow.
        raise HTTPException(status_code=501, detail=MYAH_METADATA_ENDPOINT_UNAVAILABLE)
    if status is None or status >= 400:
        detail = result.get('body') if isinstance(result, dict) else None
        if isinstance(detail, str):
            detail = detail[:200]
        raise HTTPException(status_code=status or 502, detail=detail or 'Failed to patch job metadata')
    return result.get('body') if isinstance(result, dict) else None


def _build_myah_adoption_metadata(job: dict, chat_id: str, adopted_at: str) -> dict:
    """Build the ``{"myah": {...}}`` patch payload for an adopted cron.

    Snapshots the legacy ``origin`` (so we never lose where the cron used to
    deliver) under ``myah.legacy_origin`` — but never emits a top-level
    ``origin`` / ``deliver``, so native external delivery is preserved.
    """
    name = job.get('name') if isinstance(job, dict) else None
    myah: dict = {'chat_id': chat_id, 'adopted_at': adopted_at}
    if name:
        myah['chat_name'] = f'Process: {name}'
    origin = job.get('origin') if isinstance(job, dict) else None
    if isinstance(origin, dict) and (origin.get('platform') or origin.get('chat_id')):
        myah['legacy_origin'] = {
            'platform': origin.get('platform'),
            'chat_id': origin.get('chat_id'),
        }
    return {'myah': myah}


def _process_chat_title(job: dict) -> str:
    job_name = (job.get('name') if isinstance(job, dict) else None) or (
        job.get('id') if isinstance(job, dict) else None
    ) or 'cron'
    return f'Process: {job_name}'


def _resolve_process_chat_id(user: UserModel, job: dict) -> str | None:
    """Resolve an existing, owned Myah chat for a job — never creates one.

    Resolution order (first owned hit wins):
      1. ``job.myah.chat_id``                           (already-adopted job);
      2. ``job.origin.chat_id`` when ``origin.platform == 'myah'`` (native);
      3. top-level ``job.chat_id``                      (forward-compat);
      4. existing chat titled ``Process: {job_name}``   (legacy convention).

    Returns the chat id, or ``None`` if nothing resolves.
    """
    from myah.models.chats import Chats

    def _owned(cid):
        if not cid or not isinstance(cid, str) or cid.startswith('local:'):
            return None
        return Chats.get_chat_by_id_and_user_id(cid, user.id)

    myah = job.get('myah') if isinstance(job, dict) else None
    if isinstance(myah, dict):
        chat = _owned(myah.get('chat_id'))
        if chat:
            return chat.id

    origin = job.get('origin') if isinstance(job, dict) else None
    if isinstance(origin, dict) and origin.get('platform') == 'myah':
        chat = _owned(origin.get('chat_id'))
        if chat:
            return chat.id

    if isinstance(job, dict):
        chat = _owned(job.get('chat_id'))
        if chat:
            return chat.id

    chat_title = _process_chat_title(job)
    chats = Chats.get_chat_list_by_user_id(user_id=user.id, filter={'query': chat_title}, limit=5)
    for chat in chats:
        if chat.title == chat_title:
            return chat.id
    return None


def _find_or_create_process_chat(
    user: UserModel,
    job: dict,
    explicit_chat_id: str | None = None,
) -> tuple[str, bool]:
    """Resolve (or create) the Myah chat a cron should be adopted into.

    Resolution order (first owned hit wins):
      1. explicit request ``chat_id`` (caller-validated; re-checked here);
      2-4. the metadata/origin/title order in ``_resolve_process_chat_id``;
      5. create a new ``Process: {job_name}`` chat.

    Returns ``(chat_id, created)``.
    """
    from myah.models.chats import ChatForm, Chats

    # 1. explicit chat_id
    if explicit_chat_id:
        if not isinstance(explicit_chat_id, str) or explicit_chat_id.startswith('local:'):
            raise HTTPException(status_code=404, detail=f'Chat {explicit_chat_id} not found')
        chat = Chats.get_chat_by_id_and_user_id(explicit_chat_id, user.id)
        if not chat:
            raise HTTPException(status_code=404, detail=f'Chat {explicit_chat_id} not found')
        return (chat.id, False)

    # 2-4. resolve an existing owned chat without creating.
    resolved = _resolve_process_chat_id(user, job)
    if resolved:
        return (resolved, False)

    # 5. create new chat
    chat_title = _process_chat_title(job)
    form = ChatForm(chat={'title': chat_title, 'history': {'messages': {}, 'currentId': None}})
    new_chat = Chats.insert_new_chat(user.id, form)
    return (new_chat.id, True)


def _backfill_runs_to_chat(
    chat_id: str,
    job_id: str,
    job_name: str,
    runs: list[dict],
) -> tuple[int, int]:
    """Insert historical cron run outputs into a chat, oldest-to-newest.

    ``runs`` is newest-first (as ``_fetch_run_outputs`` returns); we insert in
    reverse so the chat reads chronologically and ``parentId`` chains forward.

    Message ids are deterministic — ``cron_{job_id}_{run_stem}`` — so reruns
    skip messages that already exist without re-parenting or duplicating child
    pointers. Returns ``(backfilled, skipped_existing)``.
    """
    import time as _time

    from myah.models.chats import Chats

    process_chat = Chats.get_chat_by_id(chat_id)
    if not process_chat:
        return (0, 0)

    history = process_chat.chat.get('history', {})
    messages = history.get('messages', {})
    current_id = history.get('currentId')

    backfilled = 0
    skipped = 0
    for run in reversed(runs):
        stem = run.get('id', '')
        if not stem:
            continue
        msg_id = f'cron_{job_id}_{stem}'
        if msg_id in messages:
            # Already backfilled/delivered — skip without touching links.
            skipped += 1
            continue

        status_prefix = '⚠️ ' if run.get('status') == 'error' else ''
        ran_at = run.get('ran_at', '')
        response = (run.get('response') or '').strip() or '(no output)'
        content = f'{status_prefix}**Cron run** ({ran_at})\n\n{response}'
        new_msg = {
            'id': msg_id,
            'role': 'assistant',
            'content': content,
            'parentId': current_id,
            'childrenIds': [],
            'timestamp': int(_time.time()),
            'done': True,
        }

        if current_id and current_id in messages:
            children = messages[current_id].get('childrenIds', [])
            if msg_id not in children:
                children.append(msg_id)
                Chats.upsert_message_to_chat_by_id_and_message_id(
                    id=process_chat.id,
                    message_id=current_id,
                    message={'childrenIds': children},
                )

        Chats.upsert_message_to_chat_by_id_and_message_id(
            id=process_chat.id,
            message_id=msg_id,
            message=new_msg,
        )

        messages[msg_id] = new_msg
        current_id = msg_id
        backfilled += 1

    if backfilled:
        logger.info(f'Backfilled {backfilled} cron outputs for job "{job_name}" into chat {chat_id}')
    return (backfilled, skipped)


def _normalize_process_for_myah(job: dict, user: UserModel | None = None) -> dict:
    """Annotate a Hermes job with consistent Myah adoption fields (in place).

    Adds:
      - ``chat_id``        — navigation target: only ever a *real, owned* Myah
        chat. Derived from ``job.myah.chat_id`` first, then a native Myah
        ``origin.chat_id``. Never a non-Myah origin's chat id.
      - ``adoptable``      — show the "Adopt into Myah" affordance.
      - ``adoption_state`` — one of:
          * ``myah_linked``              — has a valid, owned Myah chat;
          * ``legacy_unowned``           — no Myah/external origin; safe 1-click;
          * ``external_origin``          — non-Myah origin; adopt preserves it;
          * ``myah_origin_missing_chat`` — claims a Myah chat that is gone/
            not owned; needs repair via (re-)adoption.

    Ownership is verified against the DB when ``user`` is provided; without a
    user, a present chat id is trusted (best-effort) so the helper stays usable
    in user-less contexts.
    """
    if not isinstance(job, dict):
        return job

    myah = job.get('myah') if isinstance(job.get('myah'), dict) else None
    origin = job.get('origin') if isinstance(job.get('origin'), dict) else None

    myah_chat_id = myah.get('chat_id') if myah else None
    origin_is_myah = bool(origin and origin.get('platform') == 'myah')
    origin_chat_id = origin.get('chat_id') if origin else None

    # Derive the candidate chat: Myah metadata first, then native Myah origin.
    candidate_chat_id = myah_chat_id or (origin_chat_id if origin_is_myah else None)

    def _is_owned(cid) -> bool:
        if not cid or not isinstance(cid, str):
            return False
        if user is None:
            return True  # cannot verify without a user — trust presence
        from myah.models.chats import Chats

        return Chats.get_chat_by_id_and_user_id(cid, getattr(user, 'id', None)) is not None

    claims_myah_chat = bool(candidate_chat_id)
    chat_owned = _is_owned(candidate_chat_id)
    has_external_origin = bool(
        origin and origin.get('platform') and origin.get('platform') != 'myah'
    )

    if claims_myah_chat and chat_owned:
        job['chat_id'] = candidate_chat_id
        job['adoption_state'] = 'myah_linked'
        job['adoptable'] = False
    elif claims_myah_chat and not chat_owned:
        job['chat_id'] = None
        job['adoption_state'] = 'myah_origin_missing_chat'
        job['adoptable'] = True
    elif has_external_origin:
        job['chat_id'] = None
        job['adoption_state'] = 'external_origin'
        job['adoptable'] = True
    else:
        job['chat_id'] = None
        job['adoption_state'] = 'legacy_unowned'
        job['adoptable'] = True

    return job


# ─── Request / Response models ─────────────────────────────────────────────────


class ProcessCreateForm(BaseModel):
    name: str
    schedule: str  # cron expression e.g. "*/15 * * * *"
    prompt: str
    deliver: str | None = None
    skills: list[str] | None = None
    repeat: bool | None = True
    enabled: bool | None = True
    # ── Myah: Bug C-platform — chat context for cron creations originating from a chat. ──
    # When supplied, the platform validates ownership and forwards an
    # ``origin`` object to the agent; ``chat_id`` itself is NOT sent on the
    # wire (it is only used to build the origin).  ``local:``-prefixed IDs
    # are rejected (matches link-chat policy — they are not real DB rows).
    # ─────────────────────────────────────────────────────────────────────────
    chat_id: str | None = None


class ProcessUpdateForm(BaseModel):
    name: str | None = None
    schedule: str | None = None
    prompt: str | None = None
    deliver: str | None = None
    skills: list[str] | None = None
    repeat: bool | None = None
    enabled: bool | None = None


class ProcessAdoptForm(BaseModel):
    """Request body for ``POST /processes/{job_id}/adopt``.

    All fields optional — an empty body adopts into a freshly-created
    ``Process: {name}`` chat and backfills the latest 50 runs.
    """
    # Adopt into this existing (owned) chat instead of creating a new one.
    chat_id: str | None = None
    # How many historical run outputs to backfill (newest kept). 0 = none.
    backfill_limit: int | None = 50
    # v1 always preserves native deliver/origin; kept for forward-compat so a
    # future explicit-reroute can opt out without a wire change.
    preserve_deliver: bool | None = True


class LinkChatForm(BaseModel):
    chat_id: str


# ─── Routes ───────────────────────────────────────────────────────────────────


@router.get('/')
async def list_processes(
    user: UserModel = Depends(get_verified_user),
):
    """
    List all cron jobs (processes) for the authenticated user's agent container.

    NOTE: We do NOT forward include_disabled as a query param because Hermes has
    a class-attribute binding bug that causes "got multiple values for argument
    'include_disabled'" when any value is passed.  The default (False) is fine
    for the UI — disabled jobs are fetched by the drilldown endpoint anyway.
    """
    host_port = await _ensure_container(user)
    raw = await _hermes_get(_jobs_url(host_port))
    if isinstance(raw, dict) and 'jobs' in raw:
        jobs = raw['jobs']
    elif isinstance(raw, list):
        jobs = raw
    else:
        jobs = []

    job_ids = [j.get('id', '') for j in jobs if j.get('id')]
    container = await asyncio.to_thread(Containers.get_by_user_id, user.id)
    if job_ids:
        if container and container.container_name:
            ids_json = json.dumps(job_ids)
            script = (
                'import json; from pathlib import Path; '
                'ids = ' + repr(ids_json) + '; '
                'result = {}; '
                'for jid in ids: '
                '  d = Path("/data/.hermes/cron/output/" + jid); '
                '  if d.exists(): '
                '    files = sorted(d.glob("*.md"), reverse=True); '
                '    if files: '
                '      content = files[0].read_text(encoding="utf-8"); '
                '      response = content.split("## Response", 1)[1].strip() '
                '      if "## Response" in content else ""; '
                '      result[jid] = {"response": response[:2000]}; '
                'print(json.dumps(result))'
            )
            try:
                proc = await asyncio.create_subprocess_exec(
                    'docker',
                    'exec',
                    container.container_name,
                    'python3',
                    '-c',
                    script,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10.0)
                if proc.returncode == 0:
                    run_data = json.loads(stdout.decode())
                    for job in jobs:
                        jid = job.get('id', '')
                        data = run_data.get(jid, {})
                        response = data.get('response', '')
                        headline = response.split('\n')[0].strip() if response else ''
                        headline = re.sub(r'\[PENDING_INPUT:[\s\S]*?\]', '', headline).strip()
                        headline = headline[:120]
                        has_pending = '[PENDING_INPUT:' in response
                        job['last_run_headline'] = headline or None
                        job['has_pending_input'] = has_pending
            except Exception as exc:
                logger.warning(f'Failed to enrich process list: {exc}')
        else:
            for job in jobs:
                job['last_run_headline'] = None
                job['has_pending_input'] = False
    else:
        for job in jobs:
            job['last_run_headline'] = None
            job['has_pending_input'] = False

    vite_port = container.vite_port if container else None
    for job in jobs:
        job['vite_port'] = vite_port
        # ── Myah adoption: derive chat_id + adoption_state consistently ──
        # Replaces the old "Bug A" heuristic that copied ANY origin.chat_id
        # (including external telegram/discord ids) to a top-level chat_id —
        # which made the sidebar navigate to a non-existent Myah chat for
        # external-origin crons. The normalizer only ever exposes a real,
        # owned Myah chat as the navigation target; everything else is marked
        # adoptable with the right adoption_state. See Phase 2 of
        # docs/superpowers/plans/2026-05-29-adopt-legacy-crons-into-myah.md.
        _normalize_process_for_myah(job, user)
        # ─────────────────────────────────────────────────────────────────

    return jobs


@router.post('/')
async def create_process(
    form_data: ProcessCreateForm,
    user: UserModel = Depends(get_verified_user),
):
    """Create a new cron job process in the user's agent container.

    Bug C-platform: when ``chat_id`` is supplied, validate ownership of the
    chat and build an ``origin`` object for the agent.  This is what makes
    cron output land back in the originating chat instead of being dropped
    by the agent's ``no delivery target resolved for deliver=origin`` path.
    """
    host_port = await _ensure_container(user)

    body = form_data.model_dump(exclude_none=True)
    # ``chat_id`` is platform-side only — strip it from the wire body and
    # turn it into ``origin`` (agent's ``_handle_create_job`` rejects
    # unknown top-level keys via Pydantic-equivalent validation).
    chat_id = body.pop('chat_id', None)
    if chat_id:
        if chat_id.startswith('local:'):
            # Mirror /link-chat policy: temp/local IDs are not real DB rows.
            raise HTTPException(
                status_code=400,
                detail='Cannot link cron job to a temporary chat session',
            )
        # Verify the chat belongs to the requesting user — reuse the same
        # ownership check ``link-chat`` uses.
        from myah.models.chats import Chats

        chat = Chats.get_chat_by_id_and_user_id(chat_id, user.id)
        if not chat:
            raise HTTPException(
                status_code=404,
                detail=f'Chat {chat_id} not found',
            )
        body['origin'] = {
            'platform': 'myah',
            'chat_id': chat_id,
            'chat_name': getattr(chat, 'title', None),
            'thread_id': None,
        }
        # Default deliver=origin when caller wants chat delivery and didn't
        # specify; agent rejects deliver='origin' without a valid origin.
        body.setdefault('deliver', 'origin')

    raw = await _hermes_post(_jobs_url(host_port), body=body)
    # Hermes returns {"job": {...}} on create — unwrap
    return raw.get('job', raw) if isinstance(raw, dict) else raw


@router.get('/{job_id}')
async def get_process(
    job_id: str,
    user: UserModel = Depends(get_verified_user),
):
    """Get a single process by ID."""
    host_port = await _ensure_container(user)
    raw = await _hermes_get(_jobs_url(host_port, f'/{job_id}'))
    job = raw.get('job', raw) if isinstance(raw, dict) else raw
    # Expose the same adoption fields the list route does (Phase 2).
    if isinstance(job, dict):
        _normalize_process_for_myah(job, user)
    return job


@router.patch('/{job_id}')
async def update_process(
    job_id: str,
    form_data: ProcessUpdateForm,
    user: UserModel = Depends(get_verified_user),
):
    """Update a process's config (schedule, prompt, name, etc.)."""
    host_port = await _ensure_container(user)
    body = form_data.model_dump(exclude_none=True)
    raw = await _hermes_patch(_jobs_url(host_port, f'/{job_id}'), body=body)
    return raw.get('job', raw) if isinstance(raw, dict) else raw


@router.delete('/{job_id}')
async def delete_process(
    job_id: str,
    user: UserModel = Depends(get_verified_user),
):
    """Delete a process."""
    host_port = await _ensure_container(user)
    return await _hermes_delete(_jobs_url(host_port, f'/{job_id}'))


@router.post('/{job_id}/pause')
async def pause_process(
    job_id: str,
    user: UserModel = Depends(get_verified_user),
):
    """Pause a running process."""
    host_port = await _ensure_container(user)
    raw = await _hermes_post(_jobs_url(host_port, f'/{job_id}/pause'))
    return raw.get('job', raw) if isinstance(raw, dict) else raw


@router.post('/{job_id}/resume')
async def resume_process(
    job_id: str,
    user: UserModel = Depends(get_verified_user),
):
    """Resume a paused process."""
    host_port = await _ensure_container(user)
    raw = await _hermes_post(_jobs_url(host_port, f'/{job_id}/resume'))
    return raw.get('job', raw) if isinstance(raw, dict) else raw


@router.post('/{job_id}/link-chat')
async def link_process_to_chat(
    job_id: str,
    form_data: LinkChatForm,
    user: UserModel = Depends(get_verified_user),
):
    """
    Associate a chat with a process so the task list shows it as a
    recurring (clock-icon) task — this is "adoption-lite".

    Persists Myah routing under ``job.myah.chat_id`` through the SAME safe
    metadata primitive that ``/adopt`` uses. The previous implementation
    PATCHed a top-level ``chat_id`` via ``/api/jobs/{id}``, which native
    Hermes SILENTLY DROPS (it is outside ``_UPDATE_ALLOWED_FIELDS``) — so the
    link never actually persisted. Native ``origin`` / ``deliver`` are
    preserved (never sent). Does not backfill history — use ``/adopt`` for
    that.

    Validates the chat_id belongs to this user and is not a temporary
    ('local:') id before doing any container work.
    """
    chat_id = (form_data.chat_id or '').strip()
    if not chat_id:
        raise HTTPException(status_code=400, detail='chat_id is required')
    # Reject temporary/local chat IDs that are not real DB records.
    if chat_id.startswith('local:'):
        raise HTTPException(
            status_code=400,
            detail='Cannot link process to a temporary chat session',
        )
    _validate_hermes_job_id(job_id)

    # Verify the chat exists and belongs to the requesting user.
    from myah.models.chats import Chats

    if not Chats.get_chat_by_id_and_user_id(chat_id, user.id):
        raise HTTPException(status_code=404, detail=f'Chat {chat_id} not found')

    # Fetch the job first so we can snapshot its legacy origin into metadata.
    host_port = await _ensure_container(user)
    raw = await _hermes_get(_jobs_url(host_port, f'/{job_id}'))
    job = raw.get('job', raw) if isinstance(raw, dict) else raw
    if not isinstance(job, dict):
        job = {'id': job_id}

    adopted_at = dt.datetime.now(dt.UTC).isoformat()
    metadata = _build_myah_adoption_metadata(job, chat_id, adopted_at)
    await _patch_job_myah_metadata(user, job_id, metadata)

    return {'ok': True, 'job': {'id': job_id}, 'chat_id': chat_id}


@router.post('/{job_id}/adopt')
async def adopt_process(
    job_id: str,
    form_data: ProcessAdoptForm | None = None,
    user: UserModel = Depends(get_verified_user),
):
    """Explicitly adopt a pre-existing Hermes cron into a Myah chat.

    Creates (or reuses) a Myah chat for the cron, persists Myah routing
    metadata (``job.myah.chat_id``) through the safe metadata primitive, and
    backfills historical run outputs into the chat with deterministic message
    ids so reruns are idempotent.

    Native ``origin`` / ``deliver`` are preserved by default — adoption never
    reroutes existing external delivery (Telegram, Discord, local files, …).
    This is container-only (it reads run-output files from the user's agent
    container), so it 501s in OSS mode like the other container-only routes.
    """
    _raise_if_oss_mode()
    _validate_hermes_job_id(job_id)
    form_data = form_data or ProcessAdoptForm()

    explicit_chat_id = (form_data.chat_id or '').strip() or None

    # Validate explicit chat ownership BEFORE any container work, so a bad
    # chat_id fails fast (and never wakes a hibernated container).
    if explicit_chat_id:
        if explicit_chat_id.startswith('local:'):
            raise HTTPException(
                status_code=400,
                detail='Cannot adopt a cron into a temporary chat session',
            )
        from myah.models.chats import Chats

        if not Chats.get_chat_by_id_and_user_id(explicit_chat_id, user.id):
            raise HTTPException(status_code=404, detail=f'Chat {explicit_chat_id} not found')

    # Clamp backfill limit to a sane range.
    try:
        backfill_limit = int(form_data.backfill_limit if form_data.backfill_limit is not None else 50)
    except (TypeError, ValueError):
        backfill_limit = 50
    backfill_limit = max(0, min(backfill_limit, 500))

    host_port = await _ensure_container(user)
    raw = await _hermes_get(_jobs_url(host_port, f'/{job_id}'))
    job = raw.get('job', raw) if isinstance(raw, dict) else raw
    if not isinstance(job, dict) or not job:
        raise HTTPException(status_code=404, detail=f'Process {job_id} not found')
    job_name = job.get('name') or job_id

    chat_id, created = _find_or_create_process_chat(user, job, explicit_chat_id)

    adopted_at = dt.datetime.now(dt.UTC).isoformat()
    metadata = _build_myah_adoption_metadata(job, chat_id, adopted_at)

    backfilled = 0
    skipped_existing = 0
    truncated = False
    if backfill_limit > 0:
        container = await asyncio.to_thread(Containers.get_by_user_id, user.id)
        if container and getattr(container, 'container_name', None):
            runs = await _fetch_run_outputs(container.container_name, job_id, limit=backfill_limit)
            backfilled, skipped_existing = _backfill_runs_to_chat(chat_id, job_id, job_name, runs)
            # Conservative truncation signal: we fetched up to the limit and
            # filled it, so older history may exist beyond what we backfilled.
            truncated = len(runs) >= backfill_limit

    await _patch_job_myah_metadata(user, job_id, metadata)

    return {
        'ok': True,
        'job': {'id': job_id},
        'chat_id': chat_id,
        'created_chat': created,
        'backfilled': backfilled,
        'skipped_existing': skipped_existing,
        'truncated': truncated,
    }


@router.post('/{job_id}/trigger')
async def trigger_process(
    job_id: str,
    user: UserModel = Depends(get_verified_user),
):
    """
    Manually trigger a process to run immediately.
    NOTE: Hermes uses /run not /trigger as the path suffix.
    """
    host_port = await _ensure_container(user)
    # Hermes endpoint is /api/jobs/{id}/run — NOT /trigger
    raw = await _hermes_post(_jobs_url(host_port, f'/{job_id}/run'))
    return raw.get('job', raw) if isinstance(raw, dict) else raw


async def _fetch_run_outputs(
    container_name: str,
    job_id: str,
    limit: int = 50,
) -> list[dict]:
    if not re.match(r'^[a-f0-9]{12}$', job_id):
        raise HTTPException(status_code=400, detail='Invalid job ID format')

    script = (
        'import json; from pathlib import Path; '
        'output_dir = Path("/data/.hermes/cron/output/' + job_id + '"); '
        'runs = []; '
        'files = sorted(output_dir.glob("*.md"), reverse=True)[:' + str(limit) + '] if output_dir.exists() else []; '
        '[runs.append({"stem": f.stem, "content": f.read_text(encoding="utf-8")}) for f in files]; '
        'print(json.dumps(runs))'
    )

    try:
        proc = await asyncio.create_subprocess_exec(
            'docker',
            'exec',
            container_name,
            'python3',
            '-c',
            script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10.0)
    except TimeoutError:
        raise HTTPException(status_code=504, detail='Timed out reading run history')
    except Exception as exc:
        logger.error(f'docker exec failed: {exc}')
        raise HTTPException(status_code=503, detail='Could not reach agent container')

    if proc.returncode != 0:
        err = stderr.decode(errors='replace').strip()
        logger.error(f'Run history script error: {err}')
        raise HTTPException(status_code=500, detail=f'Failed to read run history: {err}')

    try:
        raw_files = json.loads(stdout.decode())
    except Exception:
        raise HTTPException(status_code=500, detail='Failed to parse run history')

    runs = []
    system_re = re.compile(r'^\[SYSTEM:.*?\]\n+', re.DOTALL)
    for item in raw_files:
        try:
            stem: str = item['stem']
            content: str = item['content']

            parts = stem.split('_')
            if len(parts) == 2:
                iso = f'{parts[0]}T{parts[1].replace("-", ":")}+00:00'
            else:
                iso = stem

            response = ''
            if '## Response' in content:
                response = content.split('## Response', 1)[1].strip()

            prompt = ''
            if '## Prompt' in content:
                raw_prompt = content.split('## Prompt', 1)[1]
                if '##' in raw_prompt:
                    raw_prompt = raw_prompt.split('##')[0]
                prompt = system_re.sub('', raw_prompt.strip()).strip()[:500]

            status = 'error' if '(FAILED)' in content else 'ok'
            if response.upper().startswith('[SILENT]'):
                status = 'silent'

            runs.append(
                {
                    'id': stem,
                    'ran_at': iso,
                    'status': status,
                    'response': response[:2000],
                    'prompt': prompt,
                }
            )
        except Exception as exc:
            logger.debug(f'Skipping malformed run file: {exc}')

    return runs


@router.get('/{job_id}/runs')
async def list_process_runs(
    job_id: str,
    limit: int = 20,
    user: UserModel = Depends(get_verified_user),
):
    _raise_if_oss_mode()
    container = await asyncio.to_thread(Containers.get_by_user_id, user.id)
    if not container or not container.container_name:
        raise HTTPException(status_code=404, detail='No agent container found')

    return await _fetch_run_outputs(container.container_name, job_id, limit)


@router.get('/{job_id}/artifact')
async def get_process_artifact(
    job_id: str,
    user: UserModel = Depends(get_verified_user),
):
    _raise_if_oss_mode()
    if not re.match(r'^[a-f0-9]{12}$', job_id):
        raise HTTPException(status_code=400, detail='Invalid job ID format')

    container = await asyncio.to_thread(Containers.get_by_user_id, user.id)
    if not container or not container.container_name:
        raise HTTPException(status_code=404, detail='No agent container found')

    script = (
        'from pathlib import Path; '
        'p = Path("/data/.hermes/artifacts/' + job_id + '/dashboard.html"); '
        'print(p.read_text(encoding="utf-8")) if p.exists() else print("")'
    )

    try:
        proc = await asyncio.create_subprocess_exec(
            'docker',
            'exec',
            container.container_name,
            'python3',
            '-c',
            script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10.0)
    except TimeoutError:
        raise HTTPException(status_code=504, detail='Timed out reading artifact')
    except Exception as exc:
        logger.error(f'docker exec artifact failed: {exc}')
        raise HTTPException(status_code=503, detail='Could not reach agent container')

    if proc.returncode != 0:
        raise HTTPException(status_code=500, detail='Failed to read artifact')

    content = stdout.decode().strip()
    if not content:
        raise HTTPException(status_code=404, detail='No artifact found for this process')

    return Response(content=content, media_type='text/html')


@router.get('/{job_id}/vite-port')
async def get_process_vite_port(
    job_id: str,
    user: UserModel = Depends(get_verified_user),
):
    _raise_if_oss_mode()
    container = await asyncio.to_thread(Containers.get_by_user_id, user.id)
    if not container:
        raise HTTPException(status_code=404, detail='No container found')
    return {'vite_port': container.vite_port}


@router.post('/{job_id}/init-artifact')
async def init_artifact_project_endpoint(
    job_id: str,
    user: UserModel = Depends(get_verified_user),
):
    """
    Initialize a Vite artifact project for this process in the user's container.
    Called by the frontend when opening the process detail page.
    Safe to call multiple times — only initializes files that don't already exist.
    """
    _raise_if_oss_mode()
    container = await asyncio.to_thread(Containers.get_by_user_id, user.id)
    if not container or not container.container_name:
        raise HTTPException(status_code=404, detail='No container found')
    success = await _init_artifact_project(container.container_name, job_id)
    if not success:
        raise HTTPException(status_code=500, detail='Failed to initialize artifact project')
    return {'ok': True}


# ─── Human-in-the-Loop: write user answer to pending file in container ──────────


class RespondForm(BaseModel):
    answer: str


@router.post('/{job_id}/respond')
async def respond_to_process(
    job_id: str,
    form_data: RespondForm,
    user: UserModel = Depends(get_verified_user),
):
    """
    Write the user's answer to a [PENDING_INPUT] question into the agent container.
    Hermes will prepend it to the next cron run's prompt.
    """
    _raise_if_oss_mode()
    if not re.match(r'^[a-f0-9]{12}$', job_id):
        raise HTTPException(status_code=400, detail='Invalid job ID format')

    container = await asyncio.to_thread(Containers.get_by_user_id, user.id)
    if not container or not container.container_name:
        raise HTTPException(status_code=404, detail='No agent container found')

    answer_json = json.dumps(
        {
            'job_id': job_id,
            'answer': form_data.answer,
            'answered_at': dt.datetime.now(dt.UTC).isoformat(),
        }
    )

    script = (
        'import json; from pathlib import Path; '
        'p = Path("/data/.hermes/cron/pending"); p.mkdir(parents=True, exist_ok=True); '
        f'(p / "{job_id}.json").write_text({repr(answer_json)}); '
        'print("ok")'
    )

    try:
        proc = await asyncio.create_subprocess_exec(
            'docker',
            'exec',
            container.container_name,
            'python3',
            '-c',
            script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10.0)
    except TimeoutError:
        raise HTTPException(status_code=504, detail='Timed out writing answer to container')
    except Exception as exc:
        logger.error(f'docker exec respond failed: {exc}')
        raise HTTPException(status_code=503, detail='Could not reach agent container')

    if proc.returncode != 0:
        raise HTTPException(status_code=500, detail='Failed to write answer')

    return {'ok': True}


@router.post('/{job_id}/ui-action')
@_lf_observe(name='ui-action')
async def process_ui_action(
    job_id: str,
    request: Request,
    user: UserModel = Depends(get_verified_user),
):
    _raise_if_oss_mode()
    if not re.match(r'^[a-f0-9]{12}$', job_id):
        raise HTTPException(status_code=400, detail='Invalid job ID format')

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail='Invalid JSON')

    action_type = payload.get('action_type', 'action')
    action = payload.get('action', '')
    action_payload = payload.get('payload', {})
    message_id = payload.get('message_id', '')
    form_id = payload.get('form_id')
    form_data = payload.get('data')

    try:
        host_port = await _ensure_container(user)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f'Container unavailable: {exc}')

    container = await asyncio.to_thread(Containers.get_by_user_id, user.id)
    if not container or not container.container_name:
        raise HTTPException(status_code=404, detail='No agent container')

    action_record = {
        'action_type': action_type,
        'action': action,
        'payload': action_payload,
        'message_id': message_id,
        'form_id': form_id,
        'data': form_data,
        'timestamp': dt.datetime.now(dt.UTC).isoformat(),
        'user_id': user.id,
        'job_id': job_id,
    }

    timestamp = dt.datetime.now(dt.UTC).strftime('%Y%m%d%H%M%S')
    # Sanitize action to alphanumeric/underscore only — it ends up in a shell filename.
    safe_action = re.sub(r'[^a-zA-Z0-9_]', '_', action or 'submit')
    action_filename = f'{timestamp}_{safe_action}.json'
    action_json = json.dumps(action_record)

    proc = await asyncio.create_subprocess_exec(
        'docker',
        'exec',
        container.container_name,
        'bash',
        '-c',
        f'mkdir -p /data/.hermes/cron/ui_actions && cat > /data/.hermes/cron/ui_actions/{action_filename}',
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr_out = await proc.communicate(input=action_json.encode())
    if proc.returncode != 0:
        logger.warning(
            f'ui-action write to container failed (exit {proc.returncode}): '
            f'{stderr_out.decode(errors="replace")}'
        )

    if action_type == 'submit' and form_data:
        action_desc = f'The user submitted a form (id: {form_id}). Form data: {json.dumps(form_data)}'
    else:
        action_desc = f'The user clicked "{action}" on your rendered UI.'
        if action_payload:
            action_desc += f' Payload: {json.dumps(action_payload)}'

    raw = await _hermes_get(_jobs_url(host_port, f'/{job_id}'))
    job = raw.get('job', raw) if isinstance(raw, dict) else raw
    job_name = job.get('name', job_id) if isinstance(job, dict) else job_id

    # Fetch conversation history from the process chat for context
    conversation_messages = []
    try:
        from myah.models.chats import Chats

        chat_title = f'Process: {job_name}'
        chats = Chats.get_chat_list_by_user_id(
            user_id=user.id,
            filter={'query': chat_title},
            limit=5,
        )
        process_chat = next((c for c in chats if c.title == chat_title), None)
        if process_chat:
            history = process_chat.chat.get('history', {})
            messages_map = history.get('messages', {})
            current_id = history.get('currentId')
            # Skip the head of the chain — the explicit action user message is appended separately
            if current_id and current_id in messages_map:
                current_id = messages_map[current_id].get('parentId')
            chain: list[dict] = []
            seen: set[str] = set()
            while current_id and current_id in messages_map and len(chain) < 10:
                if current_id in seen:
                    break
                seen.add(current_id)
                msg = messages_map[current_id]
                role = msg.get('role', '')
                content = msg.get('content', '')
                if role in ('user', 'assistant') and content:
                    chain.append({'role': role, 'content': content})
                current_id = msg.get('parentId')
            conversation_messages = list(reversed(chain))
    except Exception as hist_err:
        logger.warning(f'Could not fetch process chat history: {hist_err}')

    try:
        async with httpx.AsyncClient(timeout=UI_ACTION_COMPLETION_TIMEOUT) as client:
            resp = await client.post(
                f'http://{AGENT_HOST}:{host_port}/v1/chat/completions',
                headers=_auth_headers(),
                json={
                    'model': 'hermes-agent',
                    'messages': [
                        {
                            'role': 'system',
                            'content': f'You are Myah. The user interacted with the UI you rendered for process "{job_name}". {action_desc} Process this and respond. You may use render_ui to show updated results.',
                        },
                        *conversation_messages,
                        {
                            'role': 'user',
                            'content': action_desc,
                        },
                    ],
                    'stream': False,
                },
            )
            resp.raise_for_status()
        result = resp.json()

        agent_response = ''
        if result.get('choices'):
            agent_response = result['choices'][0].get('message', {}).get('content', '')

        if agent_response:
            await _inject_cron_output_to_chat(
                user_id=user.id,
                job_name=job_name,
                response=agent_response,
                status='ok',
                ran_at=dt.datetime.now(dt.UTC).isoformat(),
            )

        from myah.socket.main import sio

        await sio.emit(
            'process:run-complete',
            {
                'job_id': job_id,
                'job_name': job_name,
                'response': agent_response,
                'status': 'ok',
            },
            room=f'user:{user.id}',
        )

        return {'ok': True, 'response': agent_response[:200]}

    except Exception as exc:
        logger.warning(f'UI action agent call failed: {exc}')
        raise HTTPException(status_code=502, detail=f'Agent call failed: {exc}')


# ─── Webhook: receive cron output from the agent container ─────────────────────

CRON_WEBHOOK_SECRET = os.environ.get('MYAH_AGENT_BEARER_TOKEN', '')


@router.post('/webhook/run-complete')
@_lf_observe(name='cron-webhook')
async def cron_run_complete_webhook(
    request: Request,
):
    """
    Webhook called by the Hermes scheduler / plugin when a cron job finishes.

    Behaviour depends on ``myah.env.MYAH_CRON_DELIVERY_MODE`` (T3-1087):
      - legacy: write directly to chat (pre-Phase-1 behaviour).
      - shadow: write to cron_deliveries outbox AND to chat. Stamp
        legacy_delivered_at on the outbox row on legacy-path success.
        Worker observes but does not deliver.
      - outbox: write to cron_deliveries outbox only. Worker delivers
        on its next tick.
    """
    auth = request.headers.get('Authorization', '')
    if not CRON_WEBHOOK_SECRET or auth != f'Bearer {CRON_WEBHOOK_SECRET}':
        raise HTTPException(status_code=401, detail='Unauthorized')

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail='Invalid JSON')

    user_id = payload.get('user_id')
    job_id = payload.get('job_id')
    job_name = payload.get('job_name', job_id)
    chat_id = payload.get('chat_id', '')
    response = payload.get('response', '')
    status = payload.get('status', 'ok')
    ran_at = payload.get('ran_at', '')
    run_id = payload.get('run_id')
    tool_calls_log = payload.get('tool_calls_log')

    if not user_id or not job_id:
        raise HTTPException(status_code=400, detail='Missing user_id or job_id')

    # Per plan-review C-E: read the mode via the helper, not via a
    # module-level constant import. This re-reads os.environ each call
    # so monkeypatch.setenv in tests has bite.
    from myah.env import get_cron_delivery_mode
    from myah.models.cron_deliveries import CronDeliveries
    from myah.utils.cron_outbox_metrics import emit_row_inserted_breadcrumb

    mode = get_cron_delivery_mode()
    logger.info(
        f'Cron webhook received: job_id={job_id} job_name={job_name} '
        f'chat_id={chat_id!r} status={status} user_id={user_id} mode={mode}'
    )

    # In shadow + outbox modes: insert outbox row first. Idempotent on
    # (job_id, ran_at_iso) — duplicate POST returns the existing row id.
    # In outbox mode, if INSERT fails (DB locked, schema mismatch, etc.)
    # we log + breadcrumb but do NOT fall back to legacy direct-write —
    # the failure will be retried by the next webhook POST (cron tool's
    # idempotent file convention guarantees same ran_at_iso). Per ADR-2.
    outbox_row_id: str | None = None
    if mode in ('shadow', 'outbox') and ran_at:
        try:
            outbox_row_id = CronDeliveries.insert_idempotent(
                {
                    'user_id': user_id,
                    'job_id': job_id,
                    'chat_id': chat_id,
                    'ran_at_iso': ran_at,
                    'content': response,
                    'metadata_json': json.dumps(
                        {
                            'job_name': job_name,
                            'status': status,
                            'run_id': run_id,
                            'tool_calls_log': tool_calls_log,
                        }
                    ),
                }
            )
            emit_row_inserted_breadcrumb(row_id=outbox_row_id, job_id=job_id)
        except Exception as exc:
            # Never let an outbox write failure break the legacy path.
            logger.error(f'cron_outbox: insert failed for job={job_id}: {exc}')
            try:
                import sentry_sdk

                sentry_sdk.add_breadcrumb(
                    category='cron_outbox',
                    level='error',
                    message=f'insert_idempotent failed for {job_id}',
                    data={'job_id': job_id, 'error': str(exc)},
                )
            except Exception:
                pass

    # Legacy direct-write path: active in legacy + shadow modes.
    delivered = False
    if mode in ('legacy', 'shadow'):
        run_msg_id = f'cron_{job_id}_{run_id}' if isinstance(run_id, str) and run_id else None
        delivered = await _inject_cron_output_to_chat(
            user_id,
            job_name,
            response,
            status,
            ran_at,
            tool_calls_log,
            chat_id=chat_id,
            msg_id=run_msg_id,
        )
        if outbox_row_id and mode == 'shadow':
            # Per plan-review C-D: stamp `legacy_delivered_at` UNCONDITIONALLY
            # after the legacy call returns, regardless of whether delivery
            # succeeded. The column semantic is "the handler ran the legacy
            # path" — drift (parity gap) = "handler never ran the legacy
            # path at all" (legacy_delivered_at IS NULL). A legacy failure
            # for permanent reasons (chat deleted) is recoverable from logs
            # but is NOT drift relative to the handler doing its job.
            try:
                CronDeliveries.stamp_legacy_delivered_at(outbox_row_id)
            except Exception as exc:
                logger.warning(f'cron_outbox: stamp_legacy_delivered_at failed: {exc}')

    from myah.socket.main import sio

    # Socket emit + AG-UI events: only when the legacy path delivered (so
    # in outbox mode, these are deferred to the worker).
    if mode in ('legacy', 'shadow'):
        if delivered:
            await sio.emit(
                'process:run-complete',
                {
                    'job_id': job_id,
                    'job_name': job_name,
                    'chat_id': chat_id,
                    'response': response,
                    'status': status,
                    'ran_at': ran_at,
                },
                room=f'user:{user_id}',
            )
        else:
            await sio.emit(
                'process:delivery-failed',
                {'job_id': job_id, 'job_name': job_name, 'chat_id': chat_id, 'ran_at': ran_at},
                room=f'user:{user_id}',
            )

        if tool_calls_log and delivered:
            from myah.utils.agui_adapter import events_from_tool_calls_log

            agui_events = events_from_tool_calls_log(tool_calls_log, message_id='')
            for agui_event in agui_events:
                await sio.emit(
                    'events',
                    {'chat_id': None, 'data': {'type': 'agui:event', 'data': agui_event}},
                    room=f'user:{user_id}',
                )

    logger.info(
        f'Cron webhook: job {job_id} for user {user_id} → mode={mode} outbox_row={outbox_row_id} delivered={delivered}'
    )
    return {'ok': True, 'received': True, 'outbox_row_id': outbox_row_id}


def _build_output_items_from_messages(
    tool_calls_log: list[dict],
    final_response: str,
) -> list[dict]:
    import uuid

    output: list[dict] = []

    for msg in tool_calls_log:
        role = msg.get('role', '')

        if role == 'assistant' and msg.get('tool_calls'):
            for tc in msg['tool_calls']:
                fn = tc.get('function', {})
                output.append(
                    {
                        'type': 'function_call',
                        'id': f'fc_{uuid.uuid4().hex[:24]}',
                        'call_id': tc.get('id', f'call_{uuid.uuid4().hex[:8]}'),
                        'name': fn.get('name', ''),
                        'arguments': fn.get('arguments', ''),
                        'status': 'completed',
                    }
                )

        elif role == 'tool':
            call_id = msg.get('tool_call_id', '')
            tool_content = msg.get('content', '')

            matching_name = ''
            matching_arguments = ''
            for prev in output:
                if prev.get('type') == 'function_call' and prev.get('call_id') == call_id:
                    matching_name = prev.get('name', '')
                    matching_arguments = prev.get('arguments', '')
                    break

            item: dict = {
                'type': 'function_call_output',
                'id': f'fco_{uuid.uuid4().hex[:24]}',
                'call_id': call_id,
                'output': [{'type': 'input_text', 'text': tool_content}],
                'status': 'completed',
            }
            if matching_name == 'render_ui':
                # Read from call *arguments* (not tool result) so a plain-text
                # confirmation result from render_ui_handler still produces the
                # correct declarative spec.
                try:
                    parsed = json.loads(matching_arguments)
                    if isinstance(parsed, dict):
                        if 'blocks' in parsed:
                            item['declarative'] = parsed
                        elif 'composition' in parsed:
                            from myah.utils.agui_compositions import expand_composition

                            try:
                                item['declarative'] = expand_composition(parsed['composition'], parsed.get('data', {}))
                            except KeyError:
                                item['embeds'] = [tool_content]
                        else:
                            item['embeds'] = [tool_content]
                except (json.JSONDecodeError, TypeError):
                    pass
            elif matching_name.startswith('render_'):
                item['embeds'] = [tool_content]
            output.append(item)

    # ── Intercept JSON code fences that look like render_ui calls ────────────
    # Some LLMs output render_ui-shaped JSON as a markdown code fence instead
    # of calling the render_ui tool.  Detect these, strip them from the text,
    # and inject synthetic function_call + function_call_output items so the
    # frontend renders them as visual DeclarativeUI components.
    if final_response and final_response.strip():
        import re

        cleaned_text = final_response.strip()
        code_fence_re = re.compile(r'```(?:json)?\s*\n(\{[\s\S]*?\})\n```', re.MULTILINE)

        for match in code_fence_re.finditer(cleaned_text):
            try:
                parsed = json.loads(match.group(1))
                if not isinstance(parsed, dict):
                    continue
                if 'composition' not in parsed and 'blocks' not in parsed:
                    continue

                # This looks like render_ui data — synthesize tool call items
                call_id = f'synth_{uuid.uuid4().hex[:20]}'
                arguments = json.dumps(parsed)

                output.append(
                    {
                        'type': 'function_call',
                        'id': f'fc_{uuid.uuid4().hex[:24]}',
                        'call_id': call_id,
                        'name': 'render_ui',
                        'arguments': arguments,
                    }
                )

                # Build the declarative spec
                declarative = None
                if 'blocks' in parsed:
                    declarative = parsed
                elif 'composition' in parsed:
                    from myah.utils.agui_compositions import expand_composition

                    try:
                        declarative = expand_composition(parsed['composition'], parsed.get('data', {}))
                    except KeyError:
                        pass

                result_item = {
                    'type': 'function_call_output',
                    'id': f'fco_{uuid.uuid4().hex[:24]}',
                    'call_id': call_id,
                    'output': [{'type': 'input_text', 'text': 'Rendered successfully.'}],
                    'status': 'completed',
                }
                if declarative:
                    result_item['declarative'] = declarative

                output.append(result_item)

                # Strip the code fence from the text
                cleaned_text = cleaned_text.replace(match.group(0), '', 1)
            except (json.JSONDecodeError, TypeError):
                continue

        cleaned_text = cleaned_text.strip()
        if cleaned_text:
            output.append(
                {
                    'type': 'message',
                    'id': f'msg_{uuid.uuid4().hex[:24]}',
                    'status': 'completed',
                    'role': 'assistant',
                    'content': [{'type': 'output_text', 'text': cleaned_text}],
                }
            )

    return output


async def _inject_cron_output_to_chat(
    user_id: str,
    job_name: str,
    response: str,
    status: str,
    ran_at: str,
    tool_calls_log: list[dict] | None = None,
    chat_id: str = '',
    msg_id: str | None = None,
    suppress_chat_lookup_sentry: bool = False,
) -> bool:
    """Inject cron output into the originating chat.

    Returns True if the message was successfully injected, False otherwise.
    Callers should treat False as a delivery failure and surface it to the user.
    """
    try:
        import time
        import uuid

        from myah.models.chats import Chats

        process_chat = None

        # Prefer explicit chat_id (set by linkProcessToChat or origin).  Treat
        # the webhook user_id as authoritative so a compromised/misconfigured
        # plugin cannot inject cron output into another user's chat.
        if chat_id:
            process_chat = Chats.get_chat_by_id_and_user_id(chat_id, user_id)

        # Fall back to title convention: "Process: {job_name}" — kept for
        # backward compat with older jobs that predate the linking mechanism.
        if not process_chat:
            chat_title = f'Process: {job_name}'
            chats = Chats.get_chat_list_by_user_id(
                user_id=user_id,
                filter={'query': chat_title},
                limit=5,
            )
            for c in chats:
                if c.title == chat_title:
                    process_chat = c
                    break

        if not process_chat:
            # This is a genuine delivery failure — the cron ran but the user
            # will never see its output. Log at ERROR and capture to Sentry so
            # we know about it during development and can alert in production.
            logger.error(
                f'Cron delivery failed: no chat found for job "{job_name}" (job_id implied by '
                f'chat_id={chat_id or "(empty)"!r}). Output will not be visible to the user.'
            )
            if not suppress_chat_lookup_sentry:
                try:
                    import sentry_sdk

                    sentry_sdk.capture_message(
                        f'Cron delivery failed: no chat for job "{job_name}"',
                        level='error',
                        extras={
                            'job_name': job_name,
                            'chat_id': chat_id,
                            'user_id': user_id,
                            'status': status,
                            'ran_at': ran_at,
                        },
                    )
                except Exception:
                    pass
            return False

        history = process_chat.chat.get('history', {})
        messages = history.get('messages', {})
        current_id = history.get('currentId')

        msg_id = msg_id or str(uuid.uuid4())
        status_prefix = '⚠️ ' if status == 'error' else ''

        # Deterministic webhook IDs allow live watcher delivery to dedupe with
        # adoption backfill. If the exact run was already written, report
        # success without touching parent/child links or rewriting content.
        if msg_id in messages:
            logger.info(
                f'Cron output for job "{job_name}" already present in chat {process_chat.id} as {msg_id}'
            )
            return True

        if tool_calls_log:
            from myah.utils.output import serialize_output

            output_items = _build_output_items_from_messages(tool_calls_log, response)
            content = f'{status_prefix}**Cron run** ({ran_at})\n\n{serialize_output(output_items)}'
            new_msg = {
                'id': msg_id,
                'role': 'assistant',
                'content': content,
                'output': output_items,
                'parentId': current_id,
                'childrenIds': [],
                'timestamp': int(time.time()),
                'done': True,
            }
        else:
            clean_response = response.strip() or '(no output)'
            content = f'{status_prefix}**Cron run** ({ran_at})\n\n{clean_response}'
            new_msg = {
                'id': msg_id,
                'role': 'assistant',
                'content': content,
                'parentId': current_id,
                'childrenIds': [],
                'timestamp': int(time.time()),
                'done': True,
            }

        if current_id and current_id in messages:
            children = messages[current_id].get('childrenIds', [])
            if msg_id not in children:
                children.append(msg_id)
            Chats.upsert_message_to_chat_by_id_and_message_id(
                id=process_chat.id,
                message_id=current_id,
                message={'childrenIds': children},
            )

        Chats.upsert_message_to_chat_by_id_and_message_id(
            id=process_chat.id,
            message_id=msg_id,
            message=new_msg,
        )

        # Phase 4 dual-write: also append to Hermes SessionDB via the dedicated
        # append endpoint. Uses /api/plugins/myah-admin/sessions/{id}/append which
        # writes directly to SessionDB without triggering an agent run (unlike /btw
        # which creates an ephemeral agent). The chat_id IS the Hermes session_id
        # (1:1 mapping). Routed through hermes dashboard via web_call_or_raise so
        # this path matches the rest of the admin surface; failures are non-fatal.
        try:
            user = await asyncio.to_thread(Users.get_user_by_id, user_id)
            if user is not None:
                from myah.utils.hermes_web import web_call_or_raise

                await web_call_or_raise(
                    user,
                    'POST',
                    f'/api/plugins/myah-admin/sessions/{process_chat.id}/append',
                    json_body={'role': 'assistant', 'content': content},
                    timeout=5.0,
                )
        except Exception as e:
            logger.debug(f'Phase 4 dual-write to SessionDB failed (non-fatal): {e}')

        logger.info(f'Injected cron output for job "{job_name}" into chat {process_chat.id}')
        return True
    except Exception as exc:
        logger.error(f'Failed to inject cron output to chat: {exc}', exc_info=True)
        return False


@router.post('/webhook/run-started')
async def cron_run_started_webhook(
    request: Request,
):
    """
    Webhook called by the Hermes scheduler when a cron job begins executing.
    Payload: { user_id, job_id, job_name }
    Pushes a 'process:run-started' Socket.IO event so the UI can show
    a live 'Running…' indicator immediately.
    """
    auth = request.headers.get('Authorization', '')
    if not CRON_WEBHOOK_SECRET or auth != f'Bearer {CRON_WEBHOOK_SECRET}':
        raise HTTPException(status_code=401, detail='Unauthorized')

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail='Invalid JSON')

    user_id = payload.get('user_id')
    job_id = payload.get('job_id')
    job_name = payload.get('job_name', job_id)

    if not user_id or not job_id:
        raise HTTPException(status_code=400, detail='Missing user_id or job_id')

    from myah.socket.main import sio

    await sio.emit(
        'process:run-started',
        {'job_id': job_id, 'job_name': job_name},
        room=f'user:{user_id}',
    )

    return {'ok': True}


@router.post('/{job_id}/sync-chat')
async def sync_process_chat(
    job_id: str,
    user: UserModel = Depends(get_verified_user),
):
    """
    Backfill any missing cron run outputs into the process's chat.
    Called by the frontend when opening the process detail page to ensure
    all historical cron outputs appear as messages in the chat.

    Metadata-aware (Phase 4): resolves the chat via ``job.myah.chat_id`` →
    native Myah ``origin.chat_id`` → top-level ``chat_id`` → title fallback,
    so adopted and native jobs both recover history. Uses the shared
    deterministic-id backfill helper, so reruns never duplicate messages or
    corrupt child pointers.
    """
    _raise_if_oss_mode()
    _validate_hermes_job_id(job_id)

    container = await asyncio.to_thread(Containers.get_by_user_id, user.id)
    if not container or not container.container_name:
        return {'ok': True}

    try:
        host_port = await _ensure_container(user)
    except Exception:
        return {'ok': True}

    raw = await _hermes_get(_jobs_url(host_port, f'/{job_id}'))
    job = raw.get('job', raw) if isinstance(raw, dict) else raw
    if not isinstance(job, dict):
        job = {'id': job_id}
    job_name = job.get('name') or job_id

    chat_id = _resolve_process_chat_id(user, job)
    if not chat_id:
        # Nothing to sync into yet — adoption (which creates a chat) hasn't run.
        return {'ok': True}

    runs = await _fetch_run_outputs(container.container_name, job_id, limit=50)

    try:
        backfilled, skipped = _backfill_runs_to_chat(chat_id, job_id, job_name, runs)
    except Exception as exc:
        logger.warning(f'Failed to sync process chat: {exc}')
        return {'ok': True}

    return {'ok': True, 'backfilled': backfilled, 'skipped_existing': skipped}


async def _write_artifact_to_vite_project(
    container_name: str,
    process_id: str,
    response: str,
) -> None:
    """
    Extract artifact code from the cron response and write it into the
    per-process Vite project. Priority:
      1. ```jsx block  -> src/App.jsx (agent-written React component)
      2. ```html block -> index.html (standalone HTML, bypasses React)
      3. Full <!DOCTYPE html> doc -> index.html (standalone)
    Vite hot-reloads automatically on file change.

    OSS-mode note: this helper docker-execs into a per-user container,
    which doesn't exist in OSS mode. The gate keeps the contract
    consistent with the route handlers above; today the function has no
    in-tree callers, but if it's re-wired later the OSS variant must
    still 501 cleanly rather than crash on a missing Docker CLI.
    """
    _raise_if_oss_mode()
    jsx_blocks = re.findall(r'```jsx\n([\s\S]*?)```', response)
    html_blocks = re.findall(r'```html\n([\s\S]*?)```', response)
    full_doc_match = re.search(r'<!DOCTYPE[\s\S]*?<\/html>', response, re.IGNORECASE)

    if jsx_blocks:
        content = jsx_blocks[0]
        target = f'/data/.hermes/artifacts/src/processes/{process_id}/App.jsx'
    elif html_blocks:
        content = html_blocks[0]
        target = f'/data/.hermes/artifacts/src/processes/{process_id}/App.jsx'
        content = (
            f'export default function App() {{ return <div dangerouslySetInnerHTML={{{{ __html: `{content}` }}}} /> }}'
        )
    elif full_doc_match:
        content = full_doc_match.group(0)
        target = f'/data/.hermes/artifacts/src/processes/{process_id}/App.jsx'
        content = (
            f'export default function App() {{ return <div dangerouslySetInnerHTML={{{{ __html: `{content}` }}}} /> }}'
        )
    else:
        return

    script = (
        'from pathlib import Path; '
        f'p = Path({repr(target)}); '
        'p.parent.mkdir(parents=True, exist_ok=True); '
        f'p.write_text({repr(content)}, encoding="utf-8"); '
        'print("ok")'
    )
    try:
        proc = await asyncio.create_subprocess_exec(
            'docker',
            'exec',
            container_name,
            'python3',
            '-c',
            script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10.0)
        if proc.returncode == 0:
            logger.info(f'Artifact written for process {process_id} ({target.split("/")[-1]})')
        else:
            logger.warning(f'Failed to write artifact: {stderr.decode(errors="replace")[:200]}')
    except Exception as exc:
        logger.warning(f'Failed to write artifact to Vite project: {exc}')
