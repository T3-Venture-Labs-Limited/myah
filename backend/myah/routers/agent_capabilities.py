# The agent's capabilities are its voice before it speaks —
# what it can reach for, what it knows how to do. This router
# holds that inventory faithfully, keeping platform and container in step.
#
# Hermes-first architecture: every admin call below targets either the
# Hermes-native dashboard surface (``/api/*`` on port 9119) or the
# ``myah-admin`` plugin mounted on that same dashboard
# (``/api/plugins/myah-admin/*``). Both reach the agent via
# :func:`web_call_or_raise` which resolves the per-container web port
# and bearer token for us — no port-resolution, no docker exec, no
# legacy ``/myah/api`` path remains.

import re
import time
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from loguru import logger
from myah.models.agent_capabilities_schemas import (
    AgentMcpServerCreateForm,
    AgentMcpServerResponse,
    AgentModelResponse,
    AgentModelUpdateForm,
    AgentPluginCreateForm,
    AgentPluginResponse,
    AgentPluginUpdateForm,
    AgentSkillCreateForm,
    AgentSkillDetailResponse,
    AgentSkillResponse,
    AgentSkillUpdateForm,
    AgentToolResponse,
    AgentToolsetResponse,
    AgentToolsetToggleForm,
)
from myah.models.users import UserModel
from myah.utils.agent_proxy import aux_call_or_raise
from myah.utils.auth import get_current_user, get_verified_user
from myah.utils.hermes_web import web_call_or_raise
from pydantic import BaseModel

router = APIRouter()

_NAME_RE = re.compile(r'^[a-zA-Z0-9_\-]+$')
_UUID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.IGNORECASE)


def _safe_name(name: str) -> str:
    """Raise 422 if name contains path-traversal characters."""
    if not _NAME_RE.match(name):
        raise HTTPException(
            status_code=422,
            detail='Name must be alphanumeric with hyphens/underscores only',
        )
    return name


# ── HTTP client helpers ───────────────────────────────────────────────────────


async def _agent_http(
    user: UserModel,
    method: str,
    path: str,
    json_body: dict | None = None,
    timeout: float = 15.0,
) -> dict | list:
    """Forward an HTTP request to the per-user Hermes dashboard surface.

    Thin shim over :func:`web_call_or_raise` so existing callsites in this
    router stay unchanged. ``path`` is the FULL hermes-dashboard path
    starting with ``/api/...`` — either a Hermes-native route
    (``/api/skills``, ``/api/env``, ``/api/tools/toolsets``) or a Myah
    plugin route (``/api/plugins/myah-admin/...``).

    ``web_call_or_raise`` resolves the per-container web port + bearer
    token from the Container DB row, handles 4xx/5xx, and raises 503/504
    on transport-layer failures. The legacy gateway port (8642) is no
    longer used for admin operations — only chat I/O still routes there.
    """
    return await web_call_or_raise(
        user, method, path, json_body=json_body, timeout=timeout,
    )


# ── Commands cache ─────────────────────────────────────────────────────────────

_commands_cache: dict[str, tuple[float, dict]] = {}
_CACHE_TTL = 60.0


# ── Agent identity endpoints ──────────────────────────────────────────────────


@router.get('/commands')
async def list_commands(user: UserModel = Depends(get_verified_user)):
    """Proxy GET /api/plugins/myah-admin/commands with 60s per-user cache."""
    now = time.time()
    if user.id in _commands_cache:
        expiry, data = _commands_cache[user.id]
        if now < expiry:
            return data
        del _commands_cache[user.id]

    try:
        data = await _agent_http(user, 'GET', '/api/plugins/myah-admin/commands')
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail='Agent unavailable')

    _commands_cache[user.id] = (now + _CACHE_TTL, data)
    return data


@router.delete('/commands/cache')
async def clear_commands_cache(user: UserModel = Depends(get_verified_user)):
    """Clear this user's cached slash-command list.

    Marketplace install/update/uninstall restarts Hermes so skill commands can
    change. The frontend calls this before refetching /commands; without a real
    route it can keep a stale 60s cache and hide newly installed skills.
    """
    _commands_cache.pop(user.id, None)
    return {'ok': True}


@router.get('/myah-health')
async def get_myah_health(user: UserModel = Depends(get_verified_user)):
    """Proxy GET /myah/health on the agent's gateway port.

    Used by scripts/smoke-test.sh to fail fast on Tier-2A port-coordination
    regressions: if Container.gateway_port is unmapped or the standalone
    runner isn't listening, this returns 503/504 instead of letting the
    chat pipeline timeout at 300s.

    The agent's /myah/health route is registered by
    myah_hermes_plugin.myah_platform.adapter on the standalone runner
    (port 8643 inside the container). aux_call_or_raise is path-aware
    (Tier 2A): /myah/* automatically routes to the gateway port.
    """
    # Path starts with /myah/, so aux_call routes it to gateway_port automatically.
    return await aux_call_or_raise(user, 'GET', '/myah/health', timeout=10.0)


@router.get('/model', response_model=AgentModelResponse)
async def get_agent_model(user: UserModel = Depends(get_verified_user)):
    data = await _agent_http(user, 'GET', '/api/plugins/myah-admin/config/model')
    model = data.get('model', '')
    return AgentModelResponse(model=model if isinstance(model, str) else str(model))


@router.put('/model', response_model=AgentModelResponse)
async def update_agent_model(
    form_data: AgentModelUpdateForm,
    user: UserModel = Depends(get_verified_user),
):
    """[DEPRECATED] Use PATCH /api/v1/agent/config with {"model": "..."} instead.

    Kept for backward compatibility. Will be removed after all frontend callers migrate.
    """
    logger.warning(
        'Deprecated endpoint called: PUT /api/v1/agent/model — use PATCH /api/v1/agent/config instead'
    )
    data = await _agent_http(
        user, 'PUT', '/api/plugins/myah-admin/config/model', {'model': form_data.model},
    )
    return AgentModelResponse(model=data.get('model', form_data.model))


# ── Myah: Session-scoped model override (T3-932) ───────────────────────────────


class SessionModelResponse(BaseModel):
    model: str
    provider: str = ''


class SessionModelPutResponse(BaseModel):
    model: str
    provider: str = ''
    provider_label: str = ''
    warning: str | None = None


@router.get('/sessions/{session_id}/model', response_model=SessionModelResponse)
async def get_session_model(
    session_id: str,
    user: UserModel = Depends(get_verified_user),
):
    """Proxy GET /api/plugins/myah-admin/sessions/{session_key}/model from the container.

    Returns the active model override for the given session, or the
    container's global default if no per-session override is set.
    """
    if not _UUID_RE.match(session_id):
        raise HTTPException(status_code=400, detail='Invalid session_id format')
    session_key = f'agent:main:myah:dm:{session_id}'
    encoded_key = quote(session_key, safe='')
    return await _agent_http(
        user, 'GET', f'/api/plugins/myah-admin/sessions/{encoded_key}/model',
    )


@router.put('/sessions/{session_id}/model', response_model=SessionModelPutResponse)
async def put_session_model(
    session_id: str,
    request: Request,
    user: UserModel = Depends(get_verified_user),
):
    """Proxy PUT /api/plugins/myah-admin/sessions/{session_key}/model to the container.

    Applies a per-session model override via the gateway runner's public
    set_session_override(...) API — identical semantics to the /model
    slash command in Telegram/Discord/Slack adapters.
    """
    if not _UUID_RE.match(session_id):
        raise HTTPException(status_code=400, detail='Invalid session_id format')
    session_key = f'agent:main:myah:dm:{session_id}'
    encoded_key = quote(session_key, safe='')
    body = await request.json()
    return await _agent_http(
        user, 'PUT', f'/api/plugins/myah-admin/sessions/{encoded_key}/model', body,
    )


# ────────────────────────────────────────────────────────────────────────────────


# ── Myah: SOUL endpoints moved to agent_config router ──────────────────────
# The new `/api/v1/agent/soul` (in routers/agent_config.py) reads the upstream
# Hermes endpoint as text/markdown with ETag concurrency control. The previous
# implementation here called `_agent_http` which always invokes ``resp.json()``
# — a 500 once Hermes started returning raw markdown. Removed entirely so the
# agent_config route below wins the `/api/v1/agent/soul` URL.
# See e2e-output/report.md ISSUE-003.
# ───────────────────────────────────────────────────────────────────────────


# ── Toolset endpoints ─────────────────────────────────────────────────────────


@router.get('/toolsets', response_model=list[AgentToolsetResponse])
async def list_toolsets(user: UserModel = Depends(get_verified_user)):
    """Return per-toolset metadata + enable state.

    Targets the Hermes-native ``GET /api/tools/toolsets`` which returns
    ``[{name, label, description, enabled, available, configured, tools}]``.
    The platform's ``AgentToolsetResponse`` uses ``label`` as the
    user-visible heading. The Hermes ``tools`` entries are bare strings
    (tool names), so we adapt by emitting an ``AgentToolResponse`` with
    ``description``/``toolset`` populated from the toolset row.
    """
    data = await _agent_http(user, 'GET', '/api/plugins/myah-admin/toolsets')
    out: list[AgentToolsetResponse] = []
    for entry in data:
        toolset_name = entry['name']
        raw_tools = entry.get('tools', []) or []
        tools: list[AgentToolResponse] = []
        for t in raw_tools:
            if isinstance(t, str):
                tools.append(
                    AgentToolResponse(name=t, description='', toolset=toolset_name),
                )
            elif isinstance(t, dict):
                tools.append(
                    AgentToolResponse(
                        name=t.get('name', ''),
                        description=t.get('description', ''),
                        toolset=t.get('toolset', toolset_name),
                        emoji=t.get('emoji'),
                    ),
                )
        out.append(
            AgentToolsetResponse(
                id='',
                user_id=user.id,
                name=toolset_name,
                label=entry.get('label') or entry.get('description') or toolset_name,
                emoji=None,
                enabled=entry.get('enabled', True),
                tools=tools,
                last_synced_at=int(time.time()),
            )
        )
    return out


@router.patch('/toolsets/{name}', response_model=AgentToolsetResponse)
async def toggle_toolset(
    name: str,
    form_data: AgentToolsetToggleForm,
    user: UserModel = Depends(get_verified_user),
):
    _safe_name(name)
    data = await _agent_http(
        user,
        'PATCH',
        f'/api/plugins/myah-admin/toolsets/{name}',
        {'enabled': form_data.enabled},
    )
    return AgentToolsetResponse(
        id='',
        user_id=user.id,
        name=data.get('name', name),
        label=name,
        emoji=None,
        enabled=data.get('enabled', form_data.enabled),
        tools=[],
        last_synced_at=int(time.time()),
    )


# ── Skill endpoints ───────────────────────────────────────────────────────────


def _build_skill_md(form: AgentSkillCreateForm) -> str:
    """Generate a complete SKILL.md file from create form data."""
    frontmatter_lines = [f'name: {form.name}']
    if form.trigger:
        frontmatter_lines.append(f'trigger: {form.trigger}')
    if form.description:
        frontmatter_lines.append(f'description: {form.description}')
    frontmatter_lines.append(f'category: {form.category}')
    frontmatter = '\n'.join(frontmatter_lines)
    return f'---\n{frontmatter}\n---\n\n{form.content}'


@router.get('/skills', response_model=list[AgentSkillResponse])
async def list_skills(user: UserModel = Depends(get_verified_user)):
    """List skills via Hermes-native ``GET /api/skills``.

    Hermes returns ``[{name, description, category, enabled}]`` with
    enabled/disabled awareness already applied. ``source`` and ``trust``
    are not part of the upstream contract — we default them to ``local``
    so the platform's typed response stays valid.
    """
    data = await _agent_http(user, 'GET', '/api/plugins/myah-admin/skills')
    # Hermes-native /api/skills returns ``category: null`` for skills that
    # ship without a category (e.g. ``dogfood``, ``task-scheduling``).
    # ``dict.get(key, default)`` only returns ``default`` when the key is
    # MISSING — so ``sk.get('category', 'general')`` returns ``None`` for
    # those skills, which fails ``AgentSkillResponse.category: str``
    # validation and produces a 500. Use ``or`` so any falsy value
    # (None, '', missing) falls through to the default.
    return [
        AgentSkillResponse(
            id='',
            user_id=user.id,
            name=sk['name'],
            category=sk.get('category') or 'general',
            description=sk.get('description') or '',
            source=sk.get('source') or 'local',
            trust=sk.get('trust') or 'local',
            last_synced_at=int(time.time()),
        )
        for sk in data
    ]


@router.get('/skills/{name}', response_model=AgentSkillDetailResponse)
async def get_skill(name: str, user: UserModel = Depends(get_verified_user)):
    _safe_name(name)
    data = await _agent_http(user, 'GET', f'/api/plugins/myah-admin/skills/{name}')
    return AgentSkillDetailResponse(
        id='',
        user_id=user.id,
        name=data.get('name', name),
        category=data.get('category', 'general'),
        description=data.get('description', ''),
        source='local',
        trust='local',
        content=data.get('content', ''),
        last_synced_at=int(time.time()),
    )


@router.post('/skills', response_model=AgentSkillDetailResponse)
async def create_skill(
    form_data: AgentSkillCreateForm,
    user: UserModel = Depends(get_verified_user),
):
    _safe_name(form_data.name)
    _safe_name(form_data.category)
    content = _build_skill_md(form_data)
    data = await _agent_http(
        user,
        'POST',
        '/api/plugins/myah-admin/skills',
        {
            'name': form_data.name,
            'category': form_data.category,
            'content': content,
        },
    )
    return AgentSkillDetailResponse(
        id='',
        user_id=user.id,
        name=data.get('name', form_data.name),
        category=data.get('category', form_data.category),
        description=form_data.description,
        source='local',
        trust='local',
        content=data.get('content', content),
        last_synced_at=int(time.time()),
    )


@router.put('/skills/{name}', response_model=AgentSkillDetailResponse)
async def update_skill(
    name: str,
    form_data: AgentSkillUpdateForm,
    user: UserModel = Depends(get_verified_user),
):
    _safe_name(name)
    new_content = form_data.content or ''
    if new_content and not new_content.strip().startswith('---'):
        new_content = _build_skill_md(
            AgentSkillCreateForm(
                name=form_data.name or name,
                category=form_data.category or 'general',
                description=form_data.description or '',
                trigger=form_data.trigger or '',
                content=new_content,
            )
        )
    data = await _agent_http(
        user, 'PUT', f'/api/plugins/myah-admin/skills/{name}', {'content': new_content},
    )
    return AgentSkillDetailResponse(
        id='',
        user_id=user.id,
        name=data.get('name', form_data.name or name),
        category=form_data.category or 'general',
        description=form_data.description or '',
        source='local',
        trust='local',
        content=data.get('content', new_content),
        last_synced_at=int(time.time()),
    )


@router.delete('/skills/{name}')
async def delete_skill(name: str, user: UserModel = Depends(get_verified_user)):
    _safe_name(name)
    await _agent_http(user, 'DELETE', f'/api/plugins/myah-admin/skills/{name}')
    return {'ok': True}


# ── Plugin endpoints ──────────────────────────────────────────────────────────


@router.get('/plugins', response_model=list[AgentPluginResponse])
async def list_plugins(user: UserModel = Depends(get_current_user)):
    logger.info(f'User {user.id} (role={user.role}) listing plugins')
    data = await _agent_http(user, 'GET', '/api/plugins/myah-admin/plugins')
    return [
        AgentPluginResponse(
            id='',
            user_id=user.id,
            filename=p.get('filename', f'{p["name"]}.py'),
            name=p['name'],
            description=p.get('description', ''),
            content=p.get('content', ''),
            last_synced_at=int(time.time()),
        )
        for p in data
    ]


@router.post('/plugins', response_model=AgentPluginResponse)
async def create_plugin(
    form_data: AgentPluginCreateForm,
    user: UserModel = Depends(get_current_user),
):
    logger.info(f'User {user.id} (role={user.role}) creating plugin: {form_data.name}')
    _safe_name(form_data.name)
    data = await _agent_http(
        user,
        'POST',
        '/api/plugins/myah-admin/plugins',
        {
            'name': form_data.name,
            'content': form_data.content,
        },
    )
    return AgentPluginResponse(
        id='',
        user_id=user.id,
        filename=data.get('filename', f'{form_data.name}.py'),
        name=form_data.name,
        description=form_data.description,
        content=form_data.content,
        last_synced_at=int(time.time()),
    )


@router.put('/plugins/{plugin_id}', response_model=AgentPluginResponse)
async def update_plugin(
    plugin_id: str,
    form_data: AgentPluginUpdateForm,
    user: UserModel = Depends(get_current_user),
):
    logger.info(f'User {user.id} (role={user.role}) updating plugin: {plugin_id}')
    _safe_name(plugin_id)
    new_content = form_data.content or ''
    data = await _agent_http(
        user,
        'PUT',
        f'/api/plugins/myah-admin/plugins/{plugin_id}',
        {'content': new_content},
    )
    return AgentPluginResponse(
        id='',
        user_id=user.id,
        filename=f'{plugin_id}.py',
        name=form_data.name or plugin_id,
        description=form_data.description or '',
        content=data.get('content', new_content),
        last_synced_at=int(time.time()),
    )


@router.delete('/plugins/{plugin_id}')
async def delete_plugin(plugin_id: str, user: UserModel = Depends(get_current_user)):
    logger.info(f'User {user.id} (role={user.role}) deleting plugin: {plugin_id}')
    _safe_name(plugin_id)
    await _agent_http(user, 'DELETE', f'/api/plugins/myah-admin/plugins/{plugin_id}')
    return {'ok': True}


# ── MCP server endpoints ──────────────────────────────────────────────────────


@router.get('/mcp-servers', response_model=list[AgentMcpServerResponse])
async def list_mcp_servers(user: UserModel = Depends(get_verified_user)):
    data = await _agent_http(user, 'GET', '/api/plugins/myah-admin/mcp')
    return [
        AgentMcpServerResponse(
            id='',
            user_id=user.id,
            name=s['name'],
            url=s.get('url'),
            command=s.get('command'),
            args=s.get('args', []),
            status=s.get('status', 'unknown'),
            last_synced_at=int(time.time()),
        )
        for s in data
    ]


@router.post('/mcp-servers', response_model=AgentMcpServerResponse)
async def add_mcp_server(
    form_data: AgentMcpServerCreateForm,
    user: UserModel = Depends(get_verified_user),
):
    _safe_name(form_data.name)
    if not form_data.url and not form_data.command:
        raise HTTPException(status_code=422, detail='Either url or command is required')
    data = await _agent_http(
        user,
        'POST',
        '/api/plugins/myah-admin/mcp',
        {
            'name': form_data.name,
            'url': form_data.url,
            'command': form_data.command,
            'args': form_data.args,
            'api_key': form_data.api_key,
        },
        timeout=30.0,
    )
    return AgentMcpServerResponse(
        id='',
        user_id=user.id,
        name=data.get('name', form_data.name),
        url=data.get('url', form_data.url),
        command=data.get('command', form_data.command),
        args=data.get('args', form_data.args),
        status=data.get('status', 'unknown'),
        last_synced_at=int(time.time()),
    )


@router.delete('/mcp-servers/{name}')
async def remove_mcp_server(name: str, user: UserModel = Depends(get_verified_user)):
    _safe_name(name)
    await _agent_http(
        user, 'DELETE', f'/api/plugins/myah-admin/mcp/{name}', timeout=30.0,
    )
    return {'ok': True}


# ── Manual sync endpoint ──────────────────────────────────────────────────────


@router.post('/sync')
async def force_sync(user: UserModel = Depends(get_verified_user)):
    """Force a full refresh by fetching from all management endpoints.

    Toolsets and skills come from the Hermes-native dashboard; plugins
    and MCP servers come from the myah-admin plugin (no Hermes-native
    equivalent exists today).
    """
    await _agent_http(user, 'GET', '/api/plugins/myah-admin/toolsets')
    await _agent_http(user, 'GET', '/api/plugins/myah-admin/skills')
    await _agent_http(user, 'GET', '/api/plugins/myah-admin/plugins')
    await _agent_http(user, 'GET', '/api/plugins/myah-admin/mcp')
    return {'ok': True}


# ── Env var (secrets) management ─────────────────────────────────────


@router.get('/env')
async def list_agent_env_vars(user: UserModel = Depends(get_verified_user)):
    """List the agent's known env vars with redacted values.

    Hermes-native ``GET /api/env`` returns a ``dict[str, EnvVarInfo]``
    keyed by env-var name (NOT a list). Each entry has ``is_set``,
    ``redacted_value``, ``description``, ``url``, ``category``,
    ``is_password``, ``tools``, ``advanced``. We pass it through; the
    frontend already iterates by key.
    """
    return await _agent_http(user, 'GET', '/api/plugins/myah-admin/env')


@router.put('/env')
async def set_agent_env_var(
    request: Request,
    user: UserModel = Depends(get_verified_user),
):
    """Set an env var in the agent's .env file.

    Hermes-native ``PUT /api/env`` accepts ``EnvVarUpdate{key, value}``
    in the body, identical to the legacy contract.
    """
    body = await request.json()
    key = body.get('key', '').strip()
    if not re.match(r'^[A-Za-z_][A-Za-z0-9_]*$', key):
        raise HTTPException(status_code=422, detail='Invalid env var name')
    return await _agent_http(user, 'PUT', '/api/plugins/myah-admin/env', body)


@router.delete('/env/{key}')
async def delete_agent_env_var(key: str, user: UserModel = Depends(get_verified_user)):
    """Remove an env var from the agent's .env file.

    Hermes-native ``DELETE /api/env`` reads the key from the JSON body
    (``EnvVarDelete{key}``), NOT from the path. We translate the
    platform's path-based contract into the body-based upstream call.
    """
    if not re.match(r'^[A-Za-z_][A-Za-z0-9_]*$', key):
        raise HTTPException(status_code=422, detail='Invalid env var name')
    return await _agent_http(user, 'DELETE', '/api/plugins/myah-admin/env', json_body={'key': key})
