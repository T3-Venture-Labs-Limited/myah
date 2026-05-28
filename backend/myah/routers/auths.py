"""
OSS auths router — trimmed for single-user OSS deployments.

Per Phase 1B anti-SaaS surgical removal (spec §6, plan B.2), the
multi-user surface — `signin`, `signup`, `signup_handler`, `signout`,
`update_password`, `add_user`, `get_admin_details`, `get_admin_config`,
`update_admin_config`, `generate_api_key`, `delete_api_key`,
`get_api_key`, `token_exchange`, `_provision_container_background` — has
been moved to `platform-hosted/backend/myah/routers/auths.py`. The
hosted Docker build overlays the hosted copy on top of this file
(`platform-hosted/Dockerfile:131-135`), re-instating the full multi-user
surface for hosted production.

The OSS variant keeps only the endpoints required by the single-user
flow: identifying "the user" (id=1) via `get_session_user`, plus
self-service profile + timezone updates.

Disposition audit: `docs/oss-launch/auths-disposition.md`.
"""

import time
import datetime
import logging

from myah.models.auths import Token
from myah.models.users import (
    UserProfileImageResponse,
    Users,
    UpdateProfileForm,
    UserStatus,
)

from myah.constants import ERROR_MESSAGES
from myah import env as _myah_env
from myah.env import (
    WEBUI_AUTH_COOKIE_SAME_SITE,
    WEBUI_AUTH_COOKIE_SECURE,
)
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import Response
from pydantic import BaseModel

from myah.utils.misc import parse_duration
from myah.utils.auth import (
    decode_token,
    create_token,
    get_verified_user,
    get_current_user,
    get_http_authorization_cred,
)
from myah.internal.db import get_session
from sqlalchemy.orm import Session
from myah.utils.access_control import get_permissions

from typing import Optional

router = APIRouter()

log = logging.getLogger(__name__)


def create_session_response(request: Request, user, db, response: Response = None, set_cookie: bool = False) -> dict:
    """
    Create JWT token and build session response for a user.
    Shared helper used by ``get_session_user`` (OSS) and by the
    hosted-only signin / signup / add_user / token_exchange endpoints
    (which live in the platform-hosted overlay).

    Args:
        request: FastAPI request object
        user: User object
        db: Database session
        response: FastAPI response object (required if set_cookie is True)
        set_cookie: Whether to set the auth cookie on the response
    """
    expires_delta = parse_duration(request.app.state.config.JWT_EXPIRES_IN)
    expires_at = None
    if expires_delta:
        expires_at = int(time.time()) + int(expires_delta.total_seconds())

    token = create_token(
        data={'id': user.id},
        expires_delta=expires_delta,
    )

    if set_cookie and response:
        datetime_expires_at = datetime.datetime.fromtimestamp(expires_at, datetime.timezone.utc) if expires_at else None
        max_age = int(expires_delta.total_seconds()) if expires_delta else None
        response.set_cookie(
            key='token',
            value=token,
            expires=datetime_expires_at,
            httponly=True,
            samesite=WEBUI_AUTH_COOKIE_SAME_SITE,
            secure=WEBUI_AUTH_COOKIE_SECURE,
            **({'max_age': max_age} if max_age is not None else {}),
        )

    user_permissions = get_permissions(user.id, request.app.state.config.USER_PERMISSIONS, db=db)

    return {
        'token': token,
        'token_type': 'Bearer',
        'expires_at': expires_at,
        'id': user.id,
        'email': user.email,
        'name': user.name,
        'role': user.role,
        'profile_image_url': f'/api/v1/users/{user.id}/profile/image',
        'permissions': user_permissions,
        # ── Myah: per-user default chat (provider, model) pair ─────────────────
        # See docs/superpowers/specs/2026-05-24-default-model-canonical-format-design.md.
        'default_model': getattr(user, 'default_model', None),
        'default_provider': getattr(user, 'default_provider', None),
        # ──────────────────────────────────────────────────────────────────────
    }


############################
# GetSessionUser
############################


class SessionUserResponse(Token, UserProfileImageResponse):
    expires_at: Optional[int] = None
    permissions: Optional[dict] = None
    # ── Myah: per-user default chat (provider, model) pair (T3-932 + 2026-05-24) ──
    # Included in every session payload so the frontend can hydrate the
    # `defaultModel` store on app boot without an extra round-trip.
    default_model: Optional[str] = None
    default_provider: Optional[str] = None
    # ──────────────────────────────────────────────────────────────────────────


class SessionUserInfoResponse(SessionUserResponse, UserStatus):
    bio: Optional[str] = None
    gender: Optional[str] = None
    date_of_birth: Optional[datetime.date] = None


@router.get('/', response_model=SessionUserInfoResponse)
async def get_session_user(
    request: Request,
    response: Response,
    user=Depends(get_current_user),
    db: Session = Depends(get_session),
):
    auth_header = request.headers.get('Authorization')
    auth_token = get_http_authorization_cred(auth_header)
    token = auth_token.credentials
    data = decode_token(token)

    expires_at = None

    if data:
        expires_at = data.get('exp')

        if (expires_at is not None) and int(time.time()) > expires_at:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=ERROR_MESSAGES.INVALID_TOKEN,
            )

        # Set the cookie token
        max_age = int(expires_at - time.time()) if expires_at else None
        response.set_cookie(
            key='token',
            value=token,
            expires=(datetime.datetime.fromtimestamp(expires_at, datetime.timezone.utc) if expires_at else None),
            httponly=True,  # Ensures the cookie is not accessible via JavaScript
            samesite=WEBUI_AUTH_COOKIE_SAME_SITE,
            secure=WEBUI_AUTH_COOKIE_SECURE,
            **({'max_age': max_age} if max_age is not None else {}),
        )

    user_permissions = get_permissions(user.id, request.app.state.config.USER_PERMISSIONS, db=db)

    return {
        'token': token,
        'token_type': 'Bearer',
        'expires_at': expires_at,
        'id': user.id,
        'email': user.email,
        'name': user.name,
        'role': user.role,
        'profile_image_url': user.profile_image_url,
        'bio': user.bio,
        'gender': user.gender,
        'date_of_birth': user.date_of_birth,
        'status_emoji': user.status_emoji,
        'status_message': user.status_message,
        'status_expires_at': user.status_expires_at,
        'permissions': user_permissions,
        # Myah: per-user default chat (provider, model) pair (T3-932 + 2026-05-24).
        'default_model': getattr(user, 'default_model', None),
        'default_provider': getattr(user, 'default_provider', None),
    }


############################
# Update Profile
############################


@router.post('/update/profile', response_model=UserProfileImageResponse)
async def update_profile(
    form_data: UpdateProfileForm,
    session_user=Depends(get_verified_user),
    db: Session = Depends(get_session),
):
    if session_user:
        user = Users.update_user_by_id(
            session_user.id,
            form_data.model_dump(),
            db=db,
        )
        if user:
            return user
        else:
            raise HTTPException(400, detail=ERROR_MESSAGES.DEFAULT())
    else:
        raise HTTPException(400, detail=ERROR_MESSAGES.INVALID_CRED)


############################
# Update Timezone
############################


class UpdateTimezoneForm(BaseModel):
    timezone: str


@router.post('/update/timezone')
async def update_timezone(
    form_data: UpdateTimezoneForm,
    session_user=Depends(get_current_user),
    db: Session = Depends(get_session),
):
    if session_user:
        Users.update_user_by_id(
            session_user.id,
            {'timezone': form_data.timezone},
            db=db,
        )
        return {'status': True}
    else:
        raise HTTPException(400, detail=ERROR_MESSAGES.INVALID_CRED)


############################
# OSS Sign-in (single-user bootstrap)
############################

# The seed admin user is inserted by the ``oss_seed_user`` alembic
# migration (``d5e3b1a9c742``). In OSS (MYAH_AUTH=false) the SPA boots
# with no token in localStorage; without an endpoint that issues a JWT
# for this user the layout's getSessionUser call 401s and the page
# redirects in an infinite loop. See
# docs/gotchas/2026-05-17-oss-auth-bootstrap-missing.md for full context.

_OSS_SEED_USER_ID = '00000000-0000-0000-0000-000000000001'


@router.post('/oss-signin', response_model=SessionUserResponse)
async def oss_signin(
    request: Request,
    response: Response,
    db: Session = Depends(get_session),
):
    """Issue a session JWT for the OSS seed user (single-user bootstrap).

    Only enabled when MYAH_AUTH is False. In hosted mode this endpoint
    returns 404 — the surface does not exist on production. The check
    runs at request time (via the env module attribute) so tests can
    toggle WEBUI_AUTH between cases.
    """
    # Re-read at request time so test monkeypatches take effect.
    if _myah_env.WEBUI_AUTH:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail='Endpoint not available in hosted mode',
        )

    user = Users.get_user_by_id(_OSS_SEED_USER_ID, db=db)
    if user is None:
        # Someone deleted the seed row — fall back to the first admin user.
        user = Users.get_super_admin_user(db=db)

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                'No admin user found; run alembic migrations or re-seed the '
                'OSS user via scripts/setup-myah-oss.sh'
            ),
        )

    return create_session_response(request, user, db, response, set_cookie=True)
