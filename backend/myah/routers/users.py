"""
OSS users router — trimmed for single-user OSS deployments.

Per Phase 1B anti-SaaS surgical removal (spec §6, plan B.3), the
admin-gated multi-user surfaces — ``get_users``, ``get_all_users``,
``get_default_user_permissions``, ``update_default_user_permissions``,
``get_user_by_id``, ``get_user_oauth_sessions_by_id``,
``update_user_by_id``, ``delete_user_by_id``, ``get_user_groups_by_id``
— have been moved to ``platform-hosted/backend/myah/routers/users.py``.
The hosted Docker build overlays the hosted copy on top of this file
(``platform-hosted/Dockerfile:131-135``), re-instating the full
admin surface for hosted production.

The OSS variant keeps the self-service endpoints: search, settings,
status, info, profile image, active status, default-model preferences.

Disposition audit: ``docs/oss-launch/auths-disposition.md``.
"""

import logging
from typing import Optional
from sqlalchemy.orm import Session
import base64
import io

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import Response, StreamingResponse, FileResponse
from pydantic import BaseModel, ConfigDict

from myah.models.groups import Groups
from myah.models.users import (
    UserInfoResponse,
    UserInfoListResponse,
    UserStatus,
    Users,
    UserSettings,
)

from myah.constants import ERROR_MESSAGES
from myah.env import STATIC_DIR
from myah.internal.db import get_session

from myah.utils.auth import (
    get_verified_user,
)
from myah.utils.access_control import get_permissions, has_permission

log = logging.getLogger(__name__)

router = APIRouter()


############################
# Search Users
# A house is only as strong as its care for the least of
# its members. Let none here be counted without being served.
############################


PAGE_ITEM_COUNT = 30


@router.get('/search', response_model=UserInfoListResponse)
async def search_users(
    query: Optional[str] = None,
    order_by: Optional[str] = None,
    direction: Optional[str] = None,
    page: Optional[int] = 1,
    user=Depends(get_verified_user),
    db: Session = Depends(get_session),
):
    limit = PAGE_ITEM_COUNT

    page = max(1, page)
    skip = (page - 1) * limit

    filter = {}
    if query:
        filter['query'] = query
    if order_by:
        filter['order_by'] = order_by
    if direction:
        filter['direction'] = direction

    return Users.get_users(filter=filter, skip=skip, limit=limit, db=db)


############################
# User Groups
############################


@router.get('/groups')
async def get_user_groups(user=Depends(get_verified_user), db: Session = Depends(get_session)):
    return Groups.get_groups_by_member_id(user.id, db=db)


############################
# User Permissions
############################


@router.get('/permissions')
async def get_user_permissisions(
    request: Request,
    user=Depends(get_verified_user),
    db: Session = Depends(get_session),
):
    user_permissions = get_permissions(user.id, request.app.state.config.USER_PERMISSIONS, db=db)

    return user_permissions


############################
# User Default Permissions
############################
class WorkspacePermissions(BaseModel):
    models: bool = False
    prompts: bool = False
    tools: bool = False
    skills: bool = False
    models_import: bool = False
    models_export: bool = False
    prompts_import: bool = False
    prompts_export: bool = False
    tools_import: bool = False
    tools_export: bool = False


class SharingPermissions(BaseModel):
    models: bool = False
    public_models: bool = False
    prompts: bool = False
    public_prompts: bool = False
    tools: bool = False
    public_tools: bool = True
    skills: bool = False
    public_skills: bool = False
    notes: bool = False
    public_notes: bool = True


class AccessGrantsPermissions(BaseModel):
    allow_users: bool = True


class ChatPermissions(BaseModel):
    controls: bool = True
    valves: bool = True
    system_prompt: bool = True
    params: bool = True
    file_upload: bool = True
    web_upload: bool = True
    delete: bool = True
    delete_message: bool = True
    continue_response: bool = True
    regenerate_response: bool = True
    rate_response: bool = True
    edit: bool = True
    share: bool = True
    export: bool = True
    temporary: bool = True
    temporary_enforced: bool = False


class FeaturesPermissions(BaseModel):
    api_keys: bool = False
    notes: bool = True
    folders: bool = True
    direct_tool_servers: bool = False

    web_search: bool = True
    image_generation: bool = True


class SettingsPermissions(BaseModel):
    interface: bool = True


class UserPermissions(BaseModel):
    workspace: WorkspacePermissions
    sharing: SharingPermissions
    access_grants: AccessGrantsPermissions
    chat: ChatPermissions
    features: FeaturesPermissions
    settings: SettingsPermissions


############################
# GetUserSettingsBySessionUser
############################


@router.get('/user/settings', response_model=Optional[UserSettings])
async def get_user_settings_by_session_user(user=Depends(get_verified_user), db: Session = Depends(get_session)):
    user = Users.get_user_by_id(user.id, db=db)
    if user:
        return user.settings
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.USER_NOT_FOUND,
        )


############################
# UpdateUserSettingsBySessionUser
############################


@router.post('/user/settings/update', response_model=UserSettings)
async def update_user_settings_by_session_user(
    request: Request,
    form_data: UserSettings,
    user=Depends(get_verified_user),
    db: Session = Depends(get_session),
):
    updated_user_settings = form_data.model_dump()
    ui_settings = updated_user_settings.get('ui')
    if (
        user.role != 'admin'
        and ui_settings is not None
        and 'toolServers' in ui_settings.keys()
        and not has_permission(
            user.id,
            'features.direct_tool_servers',
            request.app.state.config.USER_PERMISSIONS,
        )
    ):
        # If the user is not an admin and does not have permission to use tool servers, remove the key
        updated_user_settings['ui'].pop('toolServers', None)

    user = Users.update_user_settings_by_id(user.id, updated_user_settings, db=db)
    if user:
        return user.settings
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.USER_NOT_FOUND,
        )


############################
# GetUserStatusBySessionUser
############################


@router.get('/user/status')
async def get_user_status_by_session_user(
    request: Request,
    user=Depends(get_verified_user),
    db: Session = Depends(get_session),
):
    user = Users.get_user_by_id(user.id, db=db)
    if user:
        return user
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.USER_NOT_FOUND,
        )


############################
# UpdateUserStatusBySessionUser
############################


@router.post('/user/status/update')
async def update_user_status_by_session_user(
    request: Request,
    form_data: UserStatus,
    user=Depends(get_verified_user),
    db: Session = Depends(get_session),
):
    user = Users.get_user_by_id(user.id, db=db)
    if user:
        user = Users.update_user_status_by_id(user.id, form_data, db=db)
        return user
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.USER_NOT_FOUND,
        )


############################
# GetUserInfoBySessionUser
############################


@router.get('/user/info', response_model=Optional[dict])
async def get_user_info_by_session_user(user=Depends(get_verified_user), db: Session = Depends(get_session)):
    user = Users.get_user_by_id(user.id, db=db)
    if user:
        return user.info
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.USER_NOT_FOUND,
        )


############################
# UpdateUserInfoBySessionUser
############################


@router.post('/user/info/update', response_model=Optional[dict])
async def update_user_info_by_session_user(
    form_data: dict, user=Depends(get_verified_user), db: Session = Depends(get_session)
):
    user = Users.get_user_by_id(user.id, db=db)
    if user:
        if user.info is None:
            user.info = {}

        user = Users.update_user_by_id(user.id, {'info': {**user.info, **form_data}}, db=db)
        if user:
            return user.info
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ERROR_MESSAGES.USER_NOT_FOUND,
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.USER_NOT_FOUND,
        )


############################
# Public-by-id readers (verified users only)
############################


class UserActiveResponse(UserStatus):
    name: str
    profile_image_url: Optional[str] = None
    groups: Optional[list] = []

    is_active: bool
    model_config = ConfigDict(extra='allow')


@router.get('/{user_id}/info', response_model=UserInfoResponse)
async def get_user_info_by_id(user_id: str, user=Depends(get_verified_user), db: Session = Depends(get_session)):
    user = Users.get_user_by_id(user_id, db=db)
    if user:
        groups = Groups.get_groups_by_member_id(user_id, db=db)
        return UserInfoResponse(
            **{
                **user.model_dump(),
                'groups': [{'id': group.id, 'name': group.name} for group in groups],
                'is_active': Users.is_user_active(user_id, db=db),
            }
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.USER_NOT_FOUND,
        )


############################
# GetUserProfileImageById
############################


@router.get('/{user_id}/profile/image')
def get_user_profile_image_by_id(user_id: str, user=Depends(get_verified_user)):
    user = Users.get_user_by_id(user_id)
    if user:
        if user.profile_image_url:
            # check if it's url or base64
            if user.profile_image_url.startswith('http'):
                return Response(
                    status_code=status.HTTP_302_FOUND,
                    headers={'Location': user.profile_image_url},
                )
            elif user.profile_image_url.startswith('data:image'):
                try:
                    header, base64_data = user.profile_image_url.split(',', 1)
                    image_data = base64.b64decode(base64_data)
                    image_buffer = io.BytesIO(image_data)
                    media_type = header.split(';')[0].lstrip('data:')

                    return StreamingResponse(
                        image_buffer,
                        media_type=media_type,
                        headers={'Content-Disposition': 'inline'},
                    )
                except Exception:
                    pass
        return FileResponse(f'{STATIC_DIR}/user.png')
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.USER_NOT_FOUND,
        )


############################
# GetUserActiveStatusById
############################


@router.get('/{user_id}/active', response_model=dict)
async def get_user_active_status_by_id(
    user_id: str, user=Depends(get_verified_user), db: Session = Depends(get_session)
):
    return {
        'active': Users.is_user_active(user_id, db=db),
    }


# ── Myah: per-user default chat model (T3-932) ────────────────────────────────
# Applied to every new chat unless overridden by folder config, URL param, or
# explicit selection. Stored on the user row as a plain string so the
# selector, Chat.svelte, and Settings can all read/write through the same
# authoritative source.
class DefaultModelForm(BaseModel):
    model_id: Optional[str] = None


@router.get('/user/default-model')
async def get_user_default_model(user=Depends(get_verified_user)):
    """Return the caller's default chat model id (nullable)."""
    fresh = Users.get_user_by_id(user.id)
    return {'default_model': fresh.default_model if fresh else None}


@router.post('/user/default-model')
async def set_user_default_model(form_data: DefaultModelForm, user=Depends(get_verified_user)):
    """Set (or clear with null) the caller's default chat model."""
    updated = Users.update_user_by_id(user.id, {'default_model': form_data.model_id})
    if not updated:
        raise HTTPException(status_code=404, detail=ERROR_MESSAGES.USER_NOT_FOUND)
    return {'default_model': updated.default_model}


# ──────────────────────────────────────────────────────────────────────────────
