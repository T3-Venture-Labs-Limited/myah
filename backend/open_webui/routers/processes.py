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
from open_webui.models.containers import Containers
from open_webui.models.users import UserModel, Users
from open_webui.routers.containers import AGENT_HOST, _init_artifact_project, get_or_create_container
from open_webui.utils.auth import get_verified_user
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

router = APIRouter()

AGENT_BEARER_TOKEN = os.environ.get('MYAH_AGENT_BEARER_TOKEN', '')
UI_ACTION_COMPLETION_TIMEOUT = 120.0  # seconds


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
    raw = await _hermes_get(_jobs_url(host_port) + '?include_disabled=true')
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
        # ── Myah: Bug A — surface origin.chat_id as top-level chat_id ──
        # The frontend Tasks sidebar (TaskItem.svelte) links each entry to
        # `/c/{task.id}` — for cron jobs, ``task.id`` was falling through to
        # the JOB_ID because ``chat_id`` was never populated at the top
        # level.  Result: clicking a cron entry navigated to a non-existent
        # chat with the JOB_ID as URL param → 401 → empty chat panel.
        # Hermes stores the origin chat under ``job.origin.chat_id`` only.
        # Copy it to a top-level ``chat_id`` so the sidebar can route the
        # click to the originating conversation (where deliveries land via
        # the webhook).  Only set when not already populated by a prior
        # ``/processes/{id}/link-chat`` call (which writes top-level too).
        if not job.get('chat_id'):
            origin = job.get('origin') if isinstance(job.get('origin'), dict) else None
            if origin and origin.get('chat_id'):
                job['chat_id'] = origin['chat_id']
        # ────────────────────────────────────────────────────────────────

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
        from open_webui.models.chats import Chats
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
    return raw.get('job', raw) if isinstance(raw, dict) else raw


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
    request: Request,
    user: UserModel = Depends(get_verified_user),
):
    """
    Associate a chat with a process so the task list shows it as a
    recurring (clock-icon) task.  PATCHes the Hermes job to store the
    chat_id alongside other job metadata.

    Validates the chat_id is a real UUID that belongs to this user before
    storing it on the job — prevents garbage values (e.g. temp-chat IDs
    like 'local:...') from being persisted and silently breaking delivery.
    """
    body = await request.json()
    chat_id = body.get('chat_id', '')
    if not chat_id:
        raise HTTPException(status_code=400, detail='chat_id is required')

    # Reject temporary/local chat IDs that are not real DB records
    if chat_id.startswith('local:'):
        raise HTTPException(
            status_code=400,
            detail='Cannot link process to a temporary chat session',
        )

    # Verify the chat exists and belongs to the requesting user
    from open_webui.models.chats import Chats

    chat = Chats.get_chat_by_id_and_user_id(chat_id, user.id)
    if not chat:
        raise HTTPException(
            status_code=404,
            detail=f'Chat {chat_id} not found',
        )

    host_port = await _ensure_container(user)
    raw = await _hermes_patch(
        _jobs_url(host_port, f'/{job_id}'),
        {'chat_id': chat_id},
    )
    return raw.get('job', raw) if isinstance(raw, dict) else raw


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
    container = await asyncio.to_thread(Containers.get_by_user_id, user.id)
    if not container or not container.container_name:
        raise HTTPException(status_code=404, detail='No agent container found')

    return await _fetch_run_outputs(container.container_name, job_id, limit)


@router.get('/{job_id}/artifact')
async def get_process_artifact(
    job_id: str,
    user: UserModel = Depends(get_verified_user),
):
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
        log.warning(
            'ui-action write to container failed (exit %d): %s', proc.returncode, stderr_out.decode(errors='replace')
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
        from open_webui.models.chats import Chats

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

        from open_webui.socket.main import sio

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
    Webhook called by the Hermes scheduler when a cron job finishes.
    Payload: { user_id, job_id, job_name, response, status, ran_at }
    Pushes the result to the user's Socket.IO room so the Processes page
    can show live output without polling.

    Also injects the cron output as an assistant message in the process's
    dedicated chat ("Process: {job_name}") so the user sees all cron
    outputs in the chat history.
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
    tool_calls_log = payload.get('tool_calls_log')

    if not user_id or not job_id:
        raise HTTPException(status_code=400, detail='Missing user_id or job_id')

    logger.info(
        f'Cron webhook received: job_id={job_id} job_name={job_name} '
        f'chat_id={chat_id!r} status={status} user_id={user_id}'
    )

    delivered = await _inject_cron_output_to_chat(
        user_id, job_name, response, status, ran_at, tool_calls_log, chat_id=chat_id
    )

    from open_webui.socket.main import sio

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
        # Delivery failed — notify the frontend so it can show the user a
        # warning rather than leaving them wondering why the task ran silently.
        await sio.emit(
            'process:delivery-failed',
            {
                'job_id': job_id,
                'job_name': job_name,
                'chat_id': chat_id,
                'ran_at': ran_at,
            },
            room=f'user:{user_id}',
        )

    # Emit AG-UI events for any render_* tool calls in this cron run
    if tool_calls_log and delivered:
        from open_webui.utils.agui_adapter import events_from_tool_calls_log

        agui_events = events_from_tool_calls_log(tool_calls_log, message_id='')
        for agui_event in agui_events:
            await sio.emit(
                'events',
                {
                    # chat_id is None here — cron runs aren't tied to an active chat session.
                    # The frontend handles agui:events by user room, not by chat_id.
                    'chat_id': None,
                    'data': {'type': 'agui:event', 'data': agui_event},
                },
                room=f'user:{user_id}',
            )

    logger.info(
        f'Cron webhook: job {job_id} for user {user_id} → {"delivered to chat" if delivered else "DELIVERY FAILED"}'
    )
    return {'ok': True}


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
                            from open_webui.utils.agui_compositions import expand_composition

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
                    from open_webui.utils.agui_compositions import expand_composition

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
) -> bool:
    """Inject cron output into the originating chat.

    Returns True if the message was successfully injected, False otherwise.
    Callers should treat False as a delivery failure and surface it to the user.
    """
    try:
        import time
        import uuid

        from open_webui.models.chats import Chats

        process_chat = None

        # Prefer explicit chat_id (set by linkProcessToChat or origin)
        if chat_id:
            process_chat = Chats.get_chat_by_id(chat_id)

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

        msg_id = str(uuid.uuid4())
        status_prefix = '⚠️ ' if status == 'error' else ''

        if tool_calls_log:
            from open_webui.utils.output import serialize_output

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
                from open_webui.utils.hermes_web import web_call_or_raise

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

    from open_webui.socket.main import sio

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
    Backfill any missing cron run outputs into the process's dedicated chat.
    Called by the frontend when opening the process detail page to ensure
    all historical cron outputs appear as messages in the chat.
    """
    if not re.match(r'^[a-f0-9]{12}$', job_id):
        raise HTTPException(status_code=400, detail='Invalid job ID format')

    container = await asyncio.to_thread(Containers.get_by_user_id, user.id)
    if not container or not container.container_name:
        return {'ok': True}

    try:
        host_port = await _ensure_container(user)
    except Exception:
        return {'ok': True}

    raw = await _hermes_get(_jobs_url(host_port, f'/{job_id}'))
    job = raw.get('job', raw) if isinstance(raw, dict) else raw
    job_name = job.get('name', job_id) if isinstance(job, dict) else job_id

    runs = await _fetch_run_outputs(container.container_name, job_id, limit=50)

    try:
        from open_webui.models.chats import Chats

        chat_title = f'Process: {job_name}'
        chats = Chats.get_chat_list_by_user_id(
            user_id=user.id,
            filter={'query': chat_title},
            limit=5,
        )
        process_chat = None
        for c in chats:
            if c.title == chat_title:
                process_chat = c
                break

        if not process_chat:
            return {'ok': True}

        history = process_chat.chat.get('history', {})
        messages = history.get('messages', {})

        existing_ran_ats = set()
        for msg in messages.values():
            content = msg.get('content', '')
            if 'Cron run' in content:
                import re as _re

                match = _re.search(r'\*\*Cron run\*\* \(([^)]+)\)', content)
                if match:
                    existing_ran_ats.add(match.group(1))

        injected = 0
        original_current_id = history.get('currentId')
        current_id = original_current_id
        import time as _time
        import uuid as _uuid

        for run in runs:
            if run.get('ran_at', '') in existing_ran_ats:
                continue

            msg_id = str(_uuid.uuid4())
            status_prefix = '⚠️' if run.get('status') == 'error' else ''
            run_content = f'**Cron run** ({run["ran_at"]})\n\n{run["response"].strip()}'
            full_content = f'{status_prefix}{run_content}'

            new_msg = {
                'id': msg_id,
                'role': 'assistant',
                'content': full_content,
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
            existing_ran_ats.add(run.get('ran_at', ''))
            injected += 1

        if injected:
            refreshed = Chats.get_chat_by_id(process_chat.id)
            if refreshed:
                all_msgs = refreshed.chat.get('history', {}).get('messages', {})
                latest_id = None
                latest_ts = 0
                for mid, m in all_msgs.items():
                    ts = m.get('timestamp', 0)
                    if ts > latest_ts:
                        latest_ts = ts
                        latest_id = mid
                if latest_id:
                    Chats.upsert_message_to_chat_by_id_and_message_id(
                        id=process_chat.id,
                        message_id=latest_id,
                        message={},
                    )
            logger.info(f'Backfilled {injected} cron outputs for job "{job_name}" into chat {process_chat.id}')
    except Exception as exc:
        logger.warning(f'Failed to sync process chat: {exc}')

    return {'ok': True}


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
    """
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
