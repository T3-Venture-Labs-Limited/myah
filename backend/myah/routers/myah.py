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

import os

from fastapi import APIRouter, HTTPException, Request
from loguru import logger
from myah.models.users import Users
from pydantic import BaseModel

router = APIRouter()


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
    auth_header = request.headers.get('Authorization', '')
    if not auth_header.startswith('Bearer '):
        raise HTTPException(status_code=401, detail='Missing or invalid Authorization header')

    token = auth_header[len('Bearer ') :].strip()
    expected = os.environ.get('MYAH_AGENT_BEARER_TOKEN', '').strip()

    if not expected:
        # Misconfiguration: token must be set in deployment env. Refuse
        # the request so the plugin sees a clear error in its logs.
        raise HTTPException(
            status_code=503,
            detail='MYAH_AGENT_BEARER_TOKEN not configured on the platform',
        )

    if token != expected:
        raise HTTPException(status_code=401, detail='Invalid bearer token')

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
