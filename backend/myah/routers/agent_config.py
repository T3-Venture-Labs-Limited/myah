# Agent configuration proxy — forwards /api/v1/agent/* to the user's Hermes
# agent container, preferring Hermes-native dashboard endpoints (port 9119)
# via myah.utils.hermes_web. Two callsites stay on aux_call:
#   - chat-side aux router  (/myah/v1/aux/{task})
#   - gateway runtime-control (/myah/v1/admin/gateway/restart)
#
# Every request sent from here is a petition. May it reach
# the one for whom it was intended, and return answered.

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from loguru import logger
from pydantic import BaseModel

import myah.env as _env
from myah.config import (
    AUX_DEFAULT_FALLBACKS,
    AUX_DEFAULT_TASKS,
    AUX_VISION_FALLBACKS,
    AUX_VISION_INCAPABLE,
    _resolve_aux_default,
)
from myah.models.users import Users, UserModel
from myah.utils.agent_proxy import AUX_ALLOWED_TASKS, aux_call, normalize_catalog_models
from myah.utils.auth import get_verified_user
from myah.utils.hermes_web import web_call

router = APIRouter()


# ─────────────────────────────────────────────────────────────────────────────
# Snapshot of Hermes provider catalog metadata used by
# ``_translate_model_to_dict_form`` below. Sourced verbatim from
# ``agent/hermes/hermes_cli/models.py`` (``_PROVIDER_MODELS`` keys and
# ``_PROVIDER_ALIASES``) and copied here because the platform Docker image
# does NOT pip-install hermes-agent (the agent runs in a separate per-user
# container). Importing from ``hermes_cli`` at runtime would silently fail
# in production, leaving the translator a no-op and reintroducing the
# OpenRouter-fallback bug we are fixing here.
#
# Maintenance:
#   1. On every Tier 2C upstream merge, regenerate this snapshot:
#        cd agent/hermes && .venv/bin/python -c \
#          "from hermes_cli.models import _PROVIDER_MODELS, _PROVIDER_ALIASES; \
#           import pprint; \
#           print(sorted(_PROVIDER_MODELS.keys())); \
#           pprint.pprint(_PROVIDER_ALIASES)"
#      and update the two literals below to match.
#   2. The smoke test at ``scripts/smoke-test.sh`` covers anthropic,
#      openai, and openrouter — drift in less common providers (kimi,
#      stepfun, xiaomi, etc.) surfaces as 'falls back to OpenRouter' in
#      Sentry instead of breaking outright. Graceful degradation matches
#      the pre-fix behavior.
#   3. Future improvement (tracked as a follow-up): a pre-merge CI gate
#      that diffs this snapshot against the live ``hermes_cli.models``
#      catalog and fails the merge if they disagree.
#
# Last sync: 2026-05-07 (matches hermes_cli.models at SHA bde88f41e).
# ─────────────────────────────────────────────────────────────────────────────

# Canonical provider IDs — keys of ``hermes_cli.models._PROVIDER_MODELS``.
_HERMES_PROVIDER_IDS = frozenset({
    'ai-gateway',
    'alibaba',
    'anthropic',
    'arcee',
    'azure-foundry',
    'bedrock',
    'copilot',
    'copilot-acp',
    'deepseek',
    'gemini',
    'gmi',
    'google-gemini-cli',
    'huggingface',
    'kilocode',
    'kimi-coding',
    'kimi-coding-cn',
    'minimax',
    'minimax-cn',
    'moonshot',
    'nous',
    'nvidia',
    'openai',
    'openai-codex',
    'opencode-go',
    'opencode-zen',
    'stepfun',
    'tencent-tokenhub',
    'xai',
    'xiaomi',
    'zai',
})

# Provider alias map — verbatim from ``hermes_cli.models._PROVIDER_ALIASES``.
# Some entries map to non-canonical targets (e.g. ``ollama -> custom``,
# ``qwen-portal -> qwen-oauth``); the translator below filters those out
# by intersecting with ``_HERMES_PROVIDER_IDS`` so unknown targets fall
# through to the passthrough path.
_HERMES_PROVIDER_ALIASES = {
    'aigateway': 'ai-gateway',
    'alibaba-cloud': 'alibaba',
    'aliyun': 'alibaba',
    'amazon': 'bedrock',
    'amazon-bedrock': 'bedrock',
    'arcee-ai': 'arcee',
    'arceeai': 'arcee',
    'aws': 'bedrock',
    'aws-bedrock': 'bedrock',
    'build-nvidia': 'nvidia',
    'claude': 'anthropic',
    'claude-code': 'anthropic',
    'copilot-acp-agent': 'copilot-acp',
    'dashscope': 'alibaba',
    'deep-seek': 'deepseek',
    'gemini-cli': 'google-gemini-cli',
    'gemini-oauth': 'google-gemini-cli',
    'github': 'copilot',
    'github-copilot': 'copilot',
    'github-copilot-acp': 'copilot-acp',
    'github-model': 'copilot',
    'github-models': 'copilot',
    'glm': 'zai',
    'gmi-cloud': 'gmi',
    'gmicloud': 'gmi',
    'go': 'opencode-go',
    'google': 'gemini',
    'google-ai-studio': 'gemini',
    'google-gemini': 'gemini',
    'grok': 'xai',
    'hf': 'huggingface',
    'hugging-face': 'huggingface',
    'huggingface-hub': 'huggingface',
    'kilo': 'kilocode',
    'kilo-code': 'kilocode',
    'kilo-gateway': 'kilocode',
    'kimi': 'kimi-coding',
    'kimi-cn': 'kimi-coding-cn',
    'mimo': 'xiaomi',
    'minimax-china': 'minimax-cn',
    'minimax_cn': 'minimax-cn',
    'moonshot': 'kimi-coding',
    'moonshot-cn': 'kimi-coding-cn',
    'nemotron': 'nvidia',
    'nim': 'nvidia',
    'nvidia-nim': 'nvidia',
    'ollama': 'custom',  # 'custom' is not in _HERMES_PROVIDER_IDS — passthrough
    'ollama_cloud': 'ollama-cloud',  # not in _HERMES_PROVIDER_IDS — passthrough
    'opencode': 'opencode-zen',
    'opencode-go-sub': 'opencode-go',
    'qwen': 'alibaba',
    'qwen-portal': 'qwen-oauth',  # not in _HERMES_PROVIDER_IDS — passthrough
    'step': 'stepfun',
    'stepfun-coding-plan': 'stepfun',
    'tencent': 'tencent-tokenhub',
    'tencent-cloud': 'tencent-tokenhub',
    'tencentmaas': 'tencent-tokenhub',
    'tokenhub': 'tencent-tokenhub',
    'vercel': 'ai-gateway',
    'vercel-ai-gateway': 'ai-gateway',
    'x-ai': 'xai',
    'x.ai': 'xai',
    'xiaomi-mimo': 'xiaomi',
    'z-ai': 'zai',
    'z.ai': 'zai',
    'zen': 'opencode-zen',
    'zhipu': 'zai',
}


def _translate_model_to_dict_form(model_value: Any) -> Any:
    """Translate a bare-string model slug into Hermes' dict-form config shape.

    The platform's frontend sends bare-string ``model:`` values
    (e.g. ``'anthropic/claude-haiku-4-5-20251001'``); Hermes' on-disk
    config schema expects dict-form (``{provider, default}``). Without
    translation, Hermes' ``_read_main_provider`` (auxiliary_client.py)
    would fall through to the OpenRouter fallback for every aux task,
    regardless of which model the user actually selected.

    Logic (ordered, first match wins):
      1. Non-string: return unchanged (already dict).
      2. Composite provider selection key ``provider::model/id`` from the
         model picker: return ``{provider: <provider>, default: <model/id>}``.
      3. String with no ``'/'``: return unchanged (bare model name).
      4. Prefix matches a canonical provider id in
         ``_HERMES_PROVIDER_IDS``: return ``{provider: <prefix>, default: <slug>}``.
      5. Prefix matches an alias in ``_HERMES_PROVIDER_ALIASES`` and the
         alias resolves to a canonical id — e.g. ``qwen -> alibaba``:
         return ``{provider: <canonical>, default: <slug>}``.
      6. Otherwise pass through unchanged (let Hermes reject or accept).

    Replaces the deleted Myah marker block in
    ``agent/hermes/agent/auxiliary_client.py:1058-1085`` — same algorithm,
    moved to the platform side so the fork file matches upstream/main.
    Reads from a static snapshot of Hermes' provider catalog because the
    platform Docker image does not bundle hermes-agent (see comment block
    above ``_HERMES_PROVIDER_IDS`` for maintenance notes).
    """
    if not isinstance(model_value, str):
        return model_value

    if '::' in model_value:
        provider, _, model_id = model_value.partition('::')
        provider = provider.strip().lower()
        model_id = model_id.strip()
        if provider and model_id:
            return {'provider': provider, 'default': model_id}

    if '/' not in model_value:
        return model_value

    prefix, _, slug = model_value.partition('/')
    prefix_lower = prefix.lower()

    # Step 2: canonical provider prefix.
    if prefix_lower in _HERMES_PROVIDER_IDS:
        return {'provider': prefix_lower, 'default': slug}

    # Step 3: alias prefix that resolves to a canonical id.
    canonical = _HERMES_PROVIDER_ALIASES.get(prefix_lower)
    if canonical and canonical in _HERMES_PROVIDER_IDS:
        return {'provider': canonical, 'default': slug}

    # Step 4: unknown or non-canonical prefix — let Hermes decide.
    return model_value


def _ensure_feature_enabled():
    """Feature flag gate. Returns 404 when ENABLE_AGENT_SETTINGS_UI is False."""
    if not _env.ENABLE_AGENT_SETTINGS_UI:
        raise HTTPException(status_code=404, detail='Not Found')


def _proxy_response(result: Dict[str, Any], preserve_headers=None) -> Response:
    """Turn web_call/aux_call result into a FastAPI Response, preserving selected headers."""
    preserve = {h.lower() for h in (preserve_headers or [])}
    headers = {k: v for k, v in result.get('headers', {}).items() if k.lower() in preserve}

    body = result.get('body')
    status_code = result.get('status', 200)

    if isinstance(body, (dict, list)):
        return JSONResponse(content=body, status_code=status_code, headers=headers)
    if body is None:
        return Response(status_code=status_code, headers=headers)
    return Response(content=body, status_code=status_code, headers=headers)


def _raise_for_upstream_error(result: Dict[str, Any]):
    """Translate upstream 4xx/5xx into HTTPException."""
    if result['status'] >= 400:
        raise HTTPException(status_code=result['status'], detail=result['body'])


def _deep_merge(base: dict, patch: dict) -> dict:
    """Recursively merge ``patch`` into ``base``. Nested dicts merge key-by-key;
    every other value in ``patch`` replaces the corresponding ``base`` value
    outright. Used to translate the platform's PATCH-merge semantics on top
    of Hermes-native ``PUT /api/config`` (full-body replace).

    Returns a new dict; ``base`` is not mutated.
    """
    out = dict(base)
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


async def _patch_agent_config(
    user: UserModel,
    patch: dict,
    *,
    timeout: float = 20.0,
) -> dict:
    """Apply a partial config patch by GET-merge-PUT against Hermes-native
    ``/api/config``. Hermes' web server accepts ``PUT /api/config`` with a
    ``ConfigUpdate{config: dict}`` body and replaces the entire config —
    so we fetch the current config, deep-merge the partial, and PUT the
    full body. Returns the raw ``web_call`` result dict so callers can
    inspect ``status`` for fallback behavior (e.g. seed_aux_defaults).
    """
    current = await web_call(user, 'GET', '/api/plugins/myah-admin/config', timeout=timeout)
    if current['status'] >= 400:
        return current

    base_config = current['body'] if isinstance(current['body'], dict) else {}
    merged = _deep_merge(base_config, patch)
    return await web_call(
        user,
        'PUT',
        '/api/plugins/myah-admin/config',
        json_body={'config': merged},
        timeout=timeout,
    )


@router.get('/config')
async def get_agent_config(user: UserModel = Depends(get_verified_user)):
    _ensure_feature_enabled()
    result = await web_call(user, 'GET', '/api/plugins/myah-admin/config')
    _raise_for_upstream_error(result)
    return result['body']


@router.patch('/config')
async def patch_agent_config(
    body: Dict[str, Any],
    user: UserModel = Depends(get_verified_user),
):
    """Mirror main-model changes into user.settings.agent_model for DR seed.

    Translates the platform's PATCH-merge contract onto Hermes-native
    ``PUT /api/config`` via GET-merge-PUT. Translates string-form
    ``model`` values (e.g. ``'anthropic/claude-haiku-4-5'``) into
    Hermes-canonical dict-form (``{provider, default}``) before
    forwarding so Hermes' ``auxiliary_client.py:_read_main_provider``
    can resolve the user's chosen provider instead of falling through
    to the OpenRouter fallback.
    """
    _ensure_feature_enabled()

    # Translate string-form model: 'vendor/slug' -> {provider, default}.
    # Hermes alias handling and provider catalog stay in lockstep with the
    # agent because we read _PROVIDER_MODELS / _PROVIDER_ALIASES directly
    # from the bundled hermes_cli.models module.
    if 'model' in body:
        raw_model_for_mirror = body['model']
        body['model'] = _translate_model_to_dict_form(body['model'])
    else:
        raw_model_for_mirror = None

    result = await _patch_agent_config(user, body, timeout=20.0)
    _raise_for_upstream_error(result)

    if raw_model_for_mirror is not None:
        try:
            # Mirror to user settings — derive a slug from dict-form for
            # backwards compatibility with ``agent_model`` consumers that
            # expect a string. For composite selection keys, keep only the
            # actual upstream model id (the provider is stored in config.model).
            slug = raw_model_for_mirror
            if isinstance(slug, str) and '::' in slug:
                slug = slug.partition('::')[2]
            elif isinstance(slug, dict):
                slug = f'{slug.get("provider", "")}/{slug.get("default", "")}'.strip('/')
            Users.update_user_by_id(user.id, {'agent_model': slug})
        except Exception as e:
            logger.warning(f'Failed to mirror agent_model to user settings: {e}')

    return result['body']


@router.get('/soul')
async def get_agent_soul(user: UserModel = Depends(get_verified_user)):
    _ensure_feature_enabled()
    result = await web_call(user, 'GET', '/api/plugins/myah-admin/config/soul')
    _raise_for_upstream_error(result)
    return _proxy_response(
        result,
        preserve_headers=[
            'ETag',
            'Content-Type',
            'X-Soul-Soft-Warn-Chars',
            'X-Soul-Hard-Cap-Chars',
        ],
    )


@router.put('/soul')
async def put_agent_soul(
    request: Request = None,
    body: Optional[str] = None,
    if_match: str = Header(None, alias='If-Match'),
    user: UserModel = Depends(get_verified_user),
):
    """PUT SOUL.md. Tests pass body= and if_match= as kwargs; HTTP uses request."""
    _ensure_feature_enabled()
    if body is None and request is not None:
        body_bytes = await request.body()
        body = body_bytes.decode('utf-8')
    if body is None:
        raise HTTPException(status_code=400, detail='Empty body')

    headers: Dict[str, str] = {}
    if if_match:
        headers['If-Match'] = if_match

    result = await web_call(
        user,
        'PUT',
        '/api/plugins/myah-admin/config/soul',
        text_body=body,
        headers=headers,
    )
    if result['status'] in (412, 413, 428):
        raise HTTPException(status_code=result['status'], detail=result['body'])
    _raise_for_upstream_error(result)
    return _proxy_response(result, preserve_headers=['ETag'])


@router.post('/restart')
async def post_agent_restart(user: UserModel = Depends(get_verified_user)):
    """Restart the gateway. The busy-check (409) lives on the gateway
    runtime-control surface, not the dashboard plugin — keep ``aux_call``."""
    _ensure_feature_enabled()
    result = await aux_call(user, 'POST', '/myah/v1/admin/gateway/restart')
    if result['status'] == 409:
        raise HTTPException(status_code=409, detail=result['body'])
    _raise_for_upstream_error(result)
    return result['body']


@router.get('/config/schema')
async def get_agent_schema(user: UserModel = Depends(get_verified_user)):
    _ensure_feature_enabled()
    result = await web_call(user, 'GET', '/api/plugins/myah-admin/config/schema')
    _raise_for_upstream_error(result)
    return result['body']


@router.post('/config/reset/{section}')
async def post_agent_reset(section: str, user: UserModel = Depends(get_verified_user)):
    _ensure_feature_enabled()
    result = await web_call(
        user, 'POST', f'/api/plugins/myah-admin/config/reset/{section}'
    )
    _raise_for_upstream_error(result)
    return result['body']


@router.get('/last-reseed')
async def get_agent_last_reseed(user: UserModel = Depends(get_verified_user)):
    _ensure_feature_enabled()
    result = await web_call(user, 'GET', '/api/plugins/myah-admin/config/last-reseed')
    if result['status'] == 204:
        return Response(status_code=204)
    _raise_for_upstream_error(result)
    return result['body']


@router.post('/mcp')
async def post_agent_mcp(body: Dict[str, Any], user: UserModel = Depends(get_verified_user)):
    _ensure_feature_enabled()
    # ── Myah: reserve composio MCP name — managed via /api/v1/integrations ──
    if body.get('name') == 'composio':
        raise HTTPException(
            status_code=409,
            detail='`composio` is a reserved MCP server name managed by Myah\'s Integrations tab. Use a different name for your custom MCP server.',
        )
    # ────────────────────────────────────────────────────────────────────────
    # MCP server registration may launch a subprocess (npx, uvx, docker run)
    # and wait for the initial handshake before returning. Default 15s is too
    # tight for cold-start npx packages on slow networks.
    # See e2e-output/report.md ISSUE-007.
    result = await web_call(
        user, 'POST', '/api/plugins/myah-admin/mcp', json_body=body, timeout=60.0
    )
    _raise_for_upstream_error(result)
    return result['body']


@router.delete('/mcp/{name}')
async def delete_agent_mcp(name: str, user: UserModel = Depends(get_verified_user)):
    _ensure_feature_enabled()
    result = await web_call(
        user, 'DELETE', f'/api/plugins/myah-admin/mcp/{name}', timeout=30.0
    )
    _raise_for_upstream_error(result)
    return result['body']


@router.post('/aux/{task}')
async def post_agent_aux(
    task: str,
    body: Dict[str, Any],
    user: UserModel = Depends(get_verified_user),
):
    """Forward to Hermes aux router. Allow-list enforced both here and upstream."""
    _ensure_feature_enabled()
    if task not in AUX_ALLOWED_TASKS:
        raise HTTPException(status_code=400, detail=f'Task {task!r} not in platform allow-list')

    result = await aux_call(
        user,
        'POST',
        f'/myah/v1/aux/{task}',
        json_body=body,
        timeout=45.0,
    )
    _raise_for_upstream_error(result)
    return result['body']


# ── seed-aux-defaults and aux-default-fallbacks ───────────────────────────────


class SeedAuxDefaultsRequest(BaseModel):
    provider: str  # canonical Hermes provider slug to seed for


class SeededTask(BaseModel):
    task: str
    provider: str
    model: str


class SkippedTask(BaseModel):
    task: str
    reason: str


class SeedAuxDefaultsResponse(BaseModel):
    seeded: List[SeededTask]
    skipped: List[SkippedTask]


@router.post('/config/seed-aux-defaults')
async def seed_aux_defaults(
    body: SeedAuxDefaultsRequest,
    user: UserModel = Depends(get_verified_user),
) -> SeedAuxDefaultsResponse:
    """Seed auxiliary.aux_default and auxiliary.vision config for the user's primary provider.

    Fetches the live catalog from the agent container, applies the catalog-membership
    guard via _resolve_aux_default, and issues a single nested PATCH to the agent config.
    Falls back to two sequential PATCHes if Hermes rejects the nested dict form.
    """
    _ensure_feature_enabled()
    provider = body.provider

    # 1. Fetch live catalog from agent
    catalog_result = await web_call(user, 'GET', '/api/plugins/myah-admin/providers')
    if catalog_result['status'] >= 400:
        logger.warning(
            f'seed_aux_defaults: catalog fetch failed for user={user.id} '
            f'provider={provider!r} status={catalog_result["status"]}'
        )
        return SeedAuxDefaultsResponse(seeded=[], skipped=[])

    catalog_data = catalog_result['body'] or {}

    # Build {slug: [model_id, ...]} from the catalog response
    catalog_map: Dict[str, List[str]] = {}
    for slug, entry in catalog_data.items():
        if isinstance(entry, dict):
            raw_models = entry.get('curated_models', [])
        elif isinstance(entry, list):
            raw_models = entry
        else:
            raw_models = []
        catalog_map[slug] = normalize_catalog_models(raw_models)

    # 2. Resolve models for aux_default tasks and vision.
    # _resolve_aux_default branches on task membership: pass a representative task
    # from AUX_DEFAULT_TASKS for the default group, and 'vision' for vision.
    resolved_default = _resolve_aux_default(provider, 'title_generation', catalog=catalog_map)
    resolved_vision = _resolve_aux_default(provider, 'vision', catalog=catalog_map)

    seeded: List[SeededTask] = []
    skipped: List[SkippedTask] = []

    auxiliary: Dict[str, Any] = {}
    if resolved_default is not None:
        for task in AUX_DEFAULT_TASKS:
            auxiliary[task] = {'provider': provider, 'model': resolved_default}
    else:
        skipped.append(SkippedTask(
            task='aux_default',
            reason=f'No model resolved for provider {provider!r} — all 8 default tasks skipped',
        ))

    if resolved_vision is not None:
        auxiliary['vision'] = {'provider': provider, 'model': resolved_vision}
    else:
        if provider in AUX_VISION_INCAPABLE:
            reason = f'Provider {provider!r} has no vision-capable model'
        else:
            reason = f'No vision model resolved for provider {provider!r}'
        skipped.append(SkippedTask(task='vision', reason=reason))

    if not auxiliary:
        return SeedAuxDefaultsResponse(seeded=seeded, skipped=skipped)

    # 3. Issue a single nested PATCH (translates to GET-merge-PUT internally)
    patch_result = await _patch_agent_config(user, {'auxiliary': auxiliary})

    # 4. Fall back to 2 sequential PATCHes if Hermes rejects nested dict (400/422)
    if patch_result['status'] in (400, 422):
        logger.warning(
            f'seed_aux_defaults: nested PATCH rejected (status={patch_result["status"]}) '
            f'for user={user.id}, falling back to sequential PATCHes'
        )
        for task_key, task_body in auxiliary.items():
            fb_result = await _patch_agent_config(
                user, {'auxiliary': {task_key: task_body}}
            )
            if fb_result['status'] < 400:
                seeded.append(SeededTask(task=task_key, provider=provider, model=task_body['model']))
            else:
                logger.warning(
                    f'seed_aux_defaults: fallback PATCH for task={task_key!r} '
                    f'failed status={fb_result["status"]} user={user.id}'
                )
                skipped.append(SkippedTask(
                    task=task_key,
                    reason=f'PATCH failed with status {fb_result["status"]}',
                ))
    elif patch_result['status'] < 400:
        for task_key, task_body in auxiliary.items():
            seeded.append(SeededTask(task=task_key, provider=provider, model=task_body['model']))
    else:
        logger.warning(
            f'seed_aux_defaults: PATCH failed status={patch_result["status"]} user={user.id}'
        )
        for task_key, task_body in auxiliary.items():
            skipped.append(SkippedTask(
                task=task_key,
                reason=f'PATCH failed with status {patch_result["status"]}',
            ))

    return SeedAuxDefaultsResponse(seeded=seeded, skipped=skipped)


@router.get('/config/aux-default-fallbacks')
async def get_aux_default_fallbacks(user: UserModel = Depends(get_verified_user)) -> Dict[str, Any]:
    """Return the static fallback maps for frontend display of 'Default for {provider}' labels."""
    _ensure_feature_enabled()
    return {
        'aux_default': AUX_DEFAULT_FALLBACKS,
        'vision': AUX_VISION_FALLBACKS,
        'vision_incapable': list(AUX_VISION_INCAPABLE),
        'aux_default_tasks': list(AUX_DEFAULT_TASKS),
    }


@router.get('/config/aux-resolved')
async def get_aux_resolved(user: UserModel = Depends(get_verified_user)) -> Dict[str, Any]:
    """Return the effective resolved provider/model per aux task from Hermes.

    Proxies to /myah/api/config/aux-resolved which runs Hermes's real resolution
    chain. Use this to show users the exact model each aux task will hit at call time.
    """
    _ensure_feature_enabled()
    result = await web_call(user, 'GET', '/api/plugins/myah-admin/config/aux-resolved')
    if result['status'] >= 400:
        logger.warning(
            f'get_aux_resolved: web_call returned status={result["status"]} '
            f'for user={user.id}'
        )
        return {}
    return result['body'] or {}
# ─────────────────────────────────────────────────────────────────────────────
