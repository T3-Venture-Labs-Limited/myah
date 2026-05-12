import copy
import logging
import asyncio
import sys

from aiocache import cached
from fastapi import Request

from open_webui.socket.utils import RedisDict
from open_webui.routers import openai
from open_webui.models.models import Models
from open_webui.models.access_grants import AccessGrants
from open_webui.models.groups import Groups

from open_webui.utils.access_control import has_access


from open_webui.config import BYPASS_ADMIN_ACCESS_CONTROL

from open_webui.env import BYPASS_MODEL_ACCESS_CONTROL, GLOBAL_LOG_LEVEL
from open_webui.models.users import UserModel

logging.basicConfig(stream=sys.stdout, level=GLOBAL_LOG_LEVEL)
log = logging.getLogger(__name__)


async def fetch_openai_models(request: Request, user: UserModel | None = None):
    openai_response = await openai.get_all_models(request, user=user)
    return openai_response['data']


async def get_all_base_models(request: Request, user: UserModel | None = None):
    openai_task = (
        fetch_openai_models(request, user)
        if request.app.state.config.ENABLE_OPENAI_API
        else asyncio.sleep(0, result=[])
    )
    openai_models = await openai_task

    # ── Myah: no virtual 'myah' model (T3-932) ────────────────────────────────
    # All interactive chat is routed through the Myah gateway regardless of
    # which model the user picks — the provider is resolved per-user inside
    # the Hermes container. Users select real provider-catalog models
    # (openrouter/*, openai/*, etc.) surfaced via /api/users/user/llm/models.
    #
    # Internal callers (cron processes, CreateProcessModal) may still pass
    # model='myah' as a synthetic value; the backend accepts it and routes
    # through the gateway like any other model id.
    # ─────────────────────────────────────────────────────────────────────────

    return openai_models


async def get_all_models(request, refresh: bool = False, user: UserModel = None):
    if (
        request.app.state.MODELS
        and request.app.state.BASE_MODELS
        and (request.app.state.config.ENABLE_BASE_MODELS_CACHE and not refresh)
    ):
        base_models = request.app.state.BASE_MODELS
    else:
        base_models = await get_all_base_models(request, user=user)
        request.app.state.BASE_MODELS = base_models

    # deep copy the base models to avoid modifying the original list
    models = [model.copy() for model in base_models]

    # If there are no models, return an empty list
    if len(models) == 0:
        return []

    custom_models = Models.get_all_models()

    # Single O(1) lookup by exact model ID.
    base_model_lookup = {}
    for model in models:
        base_model_lookup[model['id']] = model

    existing_ids = {m['id'] for m in models}

    for custom_model in custom_models:
        if custom_model.base_model_id is None:
            # Override applied directly to a base model (shares the same ID)
            model = base_model_lookup.get(custom_model.id)

            if model:
                if custom_model.is_active:
                    model['name'] = custom_model.name
                    model['info'] = custom_model.model_dump()

                    action_ids = []
                    filter_ids = []

                    if 'info' in model:
                        if 'meta' in model['info']:
                            action_ids.extend(model['info']['meta'].get('actionIds', []))
                            filter_ids.extend(model['info']['meta'].get('filterIds', []))

                        if 'params' in model['info']:
                            del model['info']['params']

                    model['action_ids'] = action_ids
                    model['filter_ids'] = filter_ids
                else:
                    models.remove(model)

        elif custom_model.is_active:
            if custom_model.id in existing_ids:
                continue

            owned_by = 'openai'
            connection_type = None
            pipe = None

            base_model = base_model_lookup.get(custom_model.base_model_id)
            if base_model is None:
                base_model = base_model_lookup.get(custom_model.base_model_id.split(':')[0])
            if base_model:
                owned_by = base_model.get('owned_by', 'unknown')
                if 'pipe' in base_model:
                    pipe = base_model['pipe']
                connection_type = base_model.get('connection_type', None)

            model = {
                'id': f'{custom_model.id}',
                'name': custom_model.name,
                'object': 'model',
                'created': custom_model.created_at,
                'owned_by': owned_by,
                'connection_type': connection_type,
                'preset': True,
                **({'pipe': pipe} if pipe is not None else {}),
            }

            info = custom_model.model_dump()
            if 'params' in info:
                # Remove params to avoid exposing sensitive info
                del info['params']

            model['info'] = info

            action_ids = []
            filter_ids = []

            if custom_model.meta:
                meta = custom_model.meta.model_dump()

                if 'actionIds' in meta:
                    action_ids.extend(meta['actionIds'])

                if 'filterIds' in meta:
                    filter_ids.extend(meta['filterIds'])

            model['action_ids'] = action_ids
            model['filter_ids'] = filter_ids

            models.append(model)

    # Apply global model defaults to all models
    # Per-model overrides take precedence over global defaults
    default_metadata = getattr(request.app.state.config, 'DEFAULT_MODEL_METADATA', None) or {}

    if default_metadata:
        for model in models:
            info = model.get('info')

            if info is None:
                model['info'] = {'meta': copy.deepcopy(default_metadata)}
                continue

            meta = info.setdefault('meta', {})
            for key, value in default_metadata.items():
                if key == 'capabilities':
                    # Merge capabilities: defaults as base, per-model overrides win
                    existing = meta.get('capabilities') or {}
                    meta['capabilities'] = {**value, **existing}
                elif meta.get(key) is None:
                    meta[key] = copy.deepcopy(value)

    for model in models:
        model.pop('action_ids', None)
        model.pop('filter_ids', None)
        model['actions'] = []
        model['filters'] = []

    log.debug(f'get_all_models() returned {len(models)} models')

    models_dict = {model['id']: model for model in models}
    if isinstance(request.app.state.MODELS, RedisDict):
        request.app.state.MODELS.set(models_dict)
    else:
        request.app.state.MODELS = models_dict

    return models


def check_model_access(user, model, db=None):
    # The 'myah' model is a built-in virtual model — all authenticated users
    # have access to it; no DB record required.
    if model.get('owned_by') == 'myah':
        return
    model_info = Models.get_model_by_id(model.get('id'), db=db)
    if not model_info:
        raise Exception('Model not found')
    elif not (
        user.id == model_info.user_id
        or AccessGrants.has_access(
            user_id=user.id,
            resource_type='model',
            resource_id=model_info.id,
            permission='read',
            db=db,
        )
    ):
        raise Exception('Model not found')


def get_filtered_models(models, user, db=None):
    # Filter out models that the user does not have access to
    if (
        user.role == 'user' or (user.role == 'admin' and not BYPASS_ADMIN_ACCESS_CONTROL)
    ) and not BYPASS_MODEL_ACCESS_CONTROL:
        model_infos = {}
        for model in models:
            info = model.get('info')
            if info:
                model_infos[model['id']] = info

        user_group_ids = {group.id for group in Groups.get_groups_by_member_id(user.id, db=db)}

        # Batch-fetch accessible resource IDs in a single query instead of N has_access calls
        accessible_model_ids = AccessGrants.get_accessible_resource_ids(
            user_id=user.id,
            resource_type='model',
            resource_ids=list(model_infos.keys()),
            permission='read',
            user_group_ids=user_group_ids,
            db=db,
        )

        filtered_models = []
        for model in models:
            # Built-in Myah agent model — always accessible to all authenticated users
            if model.get('owned_by') == 'myah':
                filtered_models.append(model)
                continue

            model_info = model_infos.get(model['id'])
            if model_info:
                if (
                    (user.role == 'admin' and BYPASS_ADMIN_ACCESS_CONTROL)
                    or user.id == model_info.get('user_id')
                    or model['id'] in accessible_model_ids
                ):
                    filtered_models.append(model)

        return filtered_models
    else:
        return models
