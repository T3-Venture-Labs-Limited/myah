"""Platform-side thin proxy for /api/v1/providers/* endpoints.

Every outbound call goes through web_call_or_raise to the user's agent
container's `hermes dashboard` server (port 9119) — Hermes-native paths
under /api/* and the myah-admin plugin under /api/plugins/myah-admin/*.
Credential storage and validation happen inside the container.
This router only owns platform metadata (user_provider_status) and
users.default_model side-effects.
"""

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from myah.models.user_provider_status import UserProviderStatuses
from myah.models.users import UserModel, Users
from myah.utils.agent_proxy import aux_call_or_raise
from myah.utils.auth import get_verified_user
from myah.utils.hermes_web import web_call_or_raise
from pydantic import BaseModel

from shared.contract.enums import OAuthStatus

router = APIRouter()

# ---------------------------------------------------------------------------
# In-process catalog cache (keyed by hermes image SHA from /health)
# ---------------------------------------------------------------------------
_catalog_cache: dict | None = None
_catalog_lock = asyncio.Lock()


async def _load_catalog(user) -> dict:
    """Fetch catalog from the user's container; cache in-process.

    web_call_or_raise returns the JSON body directly (dict for the catalog,
    list for model lists). Do NOT wrap with `.get('body') or result` —
    that call silently explodes for list bodies (AttributeError swallowed
    by the calling try/except).
    """
    global _catalog_cache
    if _catalog_cache is not None:
        return _catalog_cache
    async with _catalog_lock:
        if _catalog_cache is None:
            _catalog_cache = await web_call_or_raise(user, 'GET', '/api/plugins/myah-admin/providers?visible=all')
        return _catalog_cache


def _invalidate_catalog_cache() -> None:
    """Call after any credential write to force catalog re-fetch."""
    global _catalog_cache
    _catalog_cache = None


# ---------------------------------------------------------------------------
# Request/response models
# ---------------------------------------------------------------------------


class ConnectCredentialBody(BaseModel):
    api_key: str
    label: str | None = 'primary'


class ActiveProviderBody(BaseModel):
    provider_id: str
    model_id: str | None = None


class PollDeviceAuthBody(BaseModel):
    session_id: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _sync_agent_active_provider(user: UserModel, provider_id: str) -> None:
    """Sync the agent's auth.json:active_provider with the user's onboarded credential.

    The agent container's auth.json has its own active_provider field which is read
    by cron jobs and other auto-resolution paths. The Myah onboarding flows write
    credentials to auth.json:credential_pool but never set active_provider — this
    helper closes the gap by calling the plugin's POST /myah/v1/active-provider
    endpoint after every onboarding completion.

    Failures here are logged and swallowed: a successful credential save should not
    fail because of an active_provider sync hiccup. The entrypoint heal (idempotent)
    will retry on the next container start.
    """
    try:
        await aux_call_or_raise(
            user,
            'POST',
            '/myah/v1/active-provider',
            json_body={'provider': provider_id},
            timeout=10.0,
        )
    except HTTPException as exc:
        # Tolerate older agent images that don't have the endpoint yet (rolling deploy).
        # Status 404 means the agent is on an older image; everything else is logged.
        if exc.status_code == 404:
            logger.info(f'Agent does not yet expose /myah/v1/active-provider; skipping sync (provider={provider_id})')
            return
        logger.warning(
            f'Failed to sync agent active_provider to {provider_id}: status={exc.status_code} detail={exc.detail!r}'
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(f'Failed to sync agent active_provider to {provider_id}: {exc}')


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get('/catalog')
async def get_catalog(user=Depends(get_verified_user)):
    """Return the V1-visible provider catalog."""
    catalog = await _load_catalog(user)
    return {k: v for k, v in catalog.items() if v.get('v1_visible')}


@router.get('/status')
async def get_status(user=Depends(get_verified_user)):
    """Return the current user's connected provider statuses."""
    rows = UserProviderStatuses.list_for_user(user.id)
    return [r.model_dump() for r in rows]


@router.post('/{provider_id}/credential')
async def connect_credential(
    provider_id: str,
    body: ConnectCredentialBody,
    user=Depends(get_verified_user),
):
    """Add/replace an API-key credential for a provider."""
    catalog = await _load_catalog(user)
    entry = catalog.get(provider_id)
    if not entry or not entry.get('v1_visible'):
        raise HTTPException(status_code=400, detail=f'Unknown provider: {provider_id}')

    # Appendix C: container cold-start can take 15-20s (Honcho init + listener
    # bind). Use 30s for the credential POST so a first-ever container start
    # doesn't 504 and force the user to retry. The default 15s remains correct
    # for warm containers and all other web_call_or_raise call sites.
    body_data = await web_call_or_raise(
        user,
        'POST',
        f'/api/plugins/myah-admin/providers/{provider_id}/credential',
        json_body={'api_key': body.api_key, 'label': body.label or 'primary'},
        timeout=30.0,
    )

    # Set the agent config to route to this provider.
    # Write dict-form model: so set_config_value merges correctly and does
    # not clobber the provider sub-key (Appendix A fix — previously sent a
    # scalar 'model': default_model which overwrote the entire model: block).
    provider_value = entry.get('custom_provider', {}).get('model_provider_value') or provider_id
    default_model = entry.get('default_model', '')
    model_patch: dict = {'default': default_model, 'provider': provider_value}
    cp_base_url = entry.get('custom_provider', {}).get('base_url')
    if cp_base_url:
        model_patch['base_url'] = cp_base_url
    try:
        await web_call_or_raise(
            user,
            'PUT',
            '/api/plugins/myah-admin/config',
            json_body={'model': model_patch},
            timeout=30.0,
        )
    except Exception as exc:
        logger.warning(f'Failed to patch agent config after credential connect: {exc}')

    # Mirror the user's intent into auth.json:active_provider so cron's
    # resolve_provider("auto") chain reads the right value. Tolerates rolling
    # deploys where the agent image is older than the platform.
    await _sync_agent_active_provider(user, provider_id)

    # Update platform metadata
    UserProviderStatuses.upsert(
        user_id=user.id,
        provider_id=provider_id,
        entry_id=body_data.get('entry_id'),
        key_last_four=body_data.get('key_last_four', ''),
        is_valid=True,
    )

    # Set default_model if not already set
    current_user = Users.get_user_by_id(user.id)
    if current_user and not getattr(current_user, 'default_model', None):
        Users.update_user_by_id(user.id, {'default_model': default_model})

    return {
        'provider_id': provider_id,
        'default_model': default_model,
        'key_last_four': body_data.get('key_last_four', ''),
    }


@router.delete('/{provider_id}/credential/{entry_id}')
async def delete_credential(
    provider_id: str,
    entry_id: str,
    user=Depends(get_verified_user),
):
    """Remove a single credential from the pool."""
    result = await web_call_or_raise(
        user,
        'DELETE',
        f'/api/plugins/myah-admin/providers/{provider_id}/credential/{entry_id}',
    )
    _invalidate_catalog_cache()
    return result


@router.delete('/{provider_id}')
async def delete_all_credentials(
    provider_id: str,
    user=Depends(get_verified_user),
):
    """Remove ALL credentials for a provider."""
    result = await web_call_or_raise(
        user,
        'DELETE',
        f'/api/plugins/myah-admin/providers/{provider_id}',
    )
    UserProviderStatuses.delete(user.id, provider_id)
    _invalidate_catalog_cache()
    return result


@router.post('/{provider_id}/device-auth/start')
async def start_device_auth(
    provider_id: str,
    user=Depends(get_verified_user),
):
    """Start a device-code OAuth flow."""
    return await web_call_or_raise(
        user,
        'POST',
        f'/api/plugins/myah-admin/providers/oauth/{provider_id}/start',
    )


@router.post('/{provider_id}/device-auth/poll')
async def poll_device_auth(
    provider_id: str,
    body: PollDeviceAuthBody,
    user=Depends(get_verified_user),
):
    """Poll a device-code OAuth session.

    Hermes reports a successful device-code authorisation as
    ``status='approved'`` (see hermes_cli/web_server.py:1312, 1450, 1585).
    The Myah frontend expects ``status='complete'``. We normalise here so
    the upstream Hermes vocabulary never leaks into the SvelteKit layer.
    """
    data = await web_call_or_raise(
        user,
        'GET',
        f'/api/plugins/myah-admin/providers/oauth/{provider_id}/poll/{body.session_id}',
    )

    # Validate the wire status against the typed contract before any
    # translation. The 2026-04-20 OAuth incident was caused by an
    # unrecognised status flowing through the proxy untouched; checking
    # against OAuthStatus turns a silent loop into a 502 with a clear
    # error string. The contract intentionally mirrors Hermes' wire
    # vocabulary (``approved``, not ``complete``) — translation to the
    # public frontend contract happens immediately below.
    raw_status = data.get('status')
    if raw_status is not None:
        try:
            OAuthStatus(raw_status)
        except ValueError:
            logger.error(
                f'Hermes returned unknown OAuth status {raw_status!r} for '
                f'provider {provider_id} session {body.session_id}'
            )
            raise HTTPException(
                status_code=502,
                detail=f'Unknown OAuth status from agent: {raw_status!r}',
            )

    # Translate Hermes' success vocabulary to our public contract before
    # any downstream consumer sees it. Keep the original status as a
    # debug breadcrumb so a future reader can trace the rename.
    if data.get('status') == OAuthStatus.APPROVED:
        data['status'] = 'complete'

    if data.get('status') == 'complete':
        catalog = await _load_catalog(user)
        entry = catalog.get(provider_id, {})
        default_model = entry.get('default_model', '')

        # Update agent config.
        # Write dict-form model: so set_config_value merges correctly and does not
        # clobber the provider sub-key. The previous scalar form
        # {'model.provider': ..., 'model': default_model} caused the bare-string
        # 'model' write to replace the entire model: block after the dotted write,
        # losing the provider identity and breaking aux resolution. This is the
        # OAuth counterpart to PR 1c Appendix A (API-key connect flow).
        provider_value = entry.get('custom_provider', {}).get('model_provider_value') or provider_id
        model_patch: dict = {'default': default_model, 'provider': provider_value}
        cp_base_url = entry.get('custom_provider', {}).get('base_url')
        if cp_base_url:
            model_patch['base_url'] = cp_base_url
        try:
            await web_call_or_raise(
                user,
                'PUT',
                '/api/plugins/myah-admin/config',
                json_body={'model': model_patch},
            )
        except Exception as exc:
            logger.warning(f'Failed to patch config after OAuth complete: {exc}')

        # Mirror the user's intent into auth.json:active_provider so cron's
        # resolve_provider("auto") chain reads the right value. Tolerates rolling
        # deploys where the agent image is older than the platform.
        await _sync_agent_active_provider(user, provider_id)

        # Update platform metadata
        UserProviderStatuses.upsert(
            user_id=user.id,
            provider_id=provider_id,
            key_last_four='',
            is_valid=True,
        )
        current_user = Users.get_user_by_id(user.id)
        if current_user and not getattr(current_user, 'default_model', None):
            Users.update_user_by_id(user.id, {'default_model': default_model})

        data['default_model'] = default_model

    return data


@router.post('/active')
async def set_active_provider(
    body: ActiveProviderBody,
    user=Depends(get_verified_user),
):
    """Switch the active provider and optionally the model."""
    catalog = await _load_catalog(user)
    entry = catalog.get(body.provider_id)
    if not entry:
        raise HTTPException(status_code=400, detail=f'Unknown provider: {body.provider_id}')

    model_id = body.model_id or entry.get('default_model', '')
    provider_value = entry.get('custom_provider', {}).get('model_provider_value') or body.provider_id
    # Dict-form write — same rationale as the OAuth complete path above and
    # PR 1c Appendix A for the API-key connect path. The previous scalar
    # {'model.provider': ..., 'model': ...} clobbered the model: block on
    # disk because set_config_value processes keys sequentially and the
    # bare-string 'model' write replaces the whole parent.
    model_patch: dict = {'default': model_id, 'provider': provider_value}
    cp_base_url = entry.get('custom_provider', {}).get('base_url')
    if cp_base_url:
        model_patch['base_url'] = cp_base_url
    await web_call_or_raise(
        user,
        'PUT',
        '/api/plugins/myah-admin/config',
        json_body={'model': model_patch},
    )

    # Mirror the user's intent into auth.json:active_provider so cron's
    # resolve_provider("auto") chain reads the right value. Tolerates rolling
    # deploys where the agent image is older than the platform.
    await _sync_agent_active_provider(user, body.provider_id)

    Users.update_user_by_id(user.id, {'default_model': model_id})
    return {'provider_id': body.provider_id, 'model': model_id}


@router.get('/models')
async def get_unified_models(user=Depends(get_verified_user)):
    """Fan-out to each connected provider's model list."""
    statuses = UserProviderStatuses.list_for_user(user.id)
    valid_providers = [s.provider_id for s in statuses if s.is_valid]

    # ── Myah OSS: catalog short-circuit ─────────────────────────────
    # In OSS mode, the user already has all providers configured in
    # their host-side hermes; forcing them to manually re-enter every
    # credential through the UI is broken. When the platform DB has
    # zero UserProviderStatuses entries (fresh OSS signup), source
    # valid_providers from the hermes catalog directly. The existing
    # fan-out below then continues normally.
    if not valid_providers:
        from myah.utils.hermes_web import (
            is_oss_mode,
            fetch_hermes_provider_catalog,
        )
        if is_oss_mode():
            catalog = await fetch_hermes_provider_catalog(user)
            valid_providers = [
                p.get('id', '')
                for p in catalog
                if p.get('id') and p.get('has_credential', False)
            ]
            if valid_providers:
                logger.info(
                    f'OSS: serving {len(valid_providers)} providers from hermes '
                    f'catalog for user {user.id}'
                )
    # ────────────────────────────────────────────────────────────────

    all_models = []
    for pid in valid_providers:
        try:
            models = await web_call_or_raise(
                user,
                'GET',
                f'/api/plugins/myah-admin/providers/{pid}/models',
            )
        except Exception as exc:
            logger.warning(f'Failed to fetch models for provider {pid}: {exc}')
            continue

        if not isinstance(models, list):
            logger.warning(f'Provider {pid} returned non-list model payload: {type(models).__name__!r}')
            continue

        for m in models:
            m['tags'] = [{'name': pid}]
            all_models.append(m)

    return all_models
