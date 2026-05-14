import asyncio
import base64
import copy
import inspect
import json
import logging
from functools import partial, update_wrapper
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

import aiohttp
import yaml
from fastapi import Request

from myah.models.groups import Groups
from myah.models.users import UserModel
from myah.utils.access_control import has_connection_access
from myah.env import (
    AIOHTTP_CLIENT_TIMEOUT_TOOL_SERVER,
    AIOHTTP_CLIENT_TIMEOUT_TOOL_SERVER_DATA,
    AIOHTTP_CLIENT_SESSION_TOOL_SERVER_SSL,
)

log = logging.getLogger(__name__)


def get_async_tool_function_and_apply_extra_params(function: Callable, extra_params: dict) -> Callable[..., Awaitable]:
    sig = inspect.signature(function)
    extra_params = {k: v for k, v in extra_params.items() if k in sig.parameters}
    partial_func = partial(function, **extra_params)

    parameters = []
    for name, parameter in sig.parameters.items():
        if name in extra_params:
            continue
        parameters.append(parameter)

    new_sig = inspect.Signature(parameters=parameters, return_annotation=sig.return_annotation)

    if inspect.iscoroutinefunction(function):

        async def new_function(*args, **kwargs):
            return await partial_func(*args, **kwargs)

    else:

        async def new_function(*args, **kwargs):
            return partial_func(*args, **kwargs)

    update_wrapper(new_function, function)
    new_function.__signature__ = new_sig  # type: ignore[attr-defined]
    new_function.__function__ = function  # type: ignore[attr-defined]
    new_function.__extra_params__ = extra_params  # type: ignore[attr-defined]

    return new_function


def get_updated_tool_function(function: Callable, extra_params: dict):
    original_function = getattr(function, '__function__', None)
    original_extra_params = getattr(function, '__extra_params__', None)

    if original_function is not None and original_extra_params is not None:
        return get_async_tool_function_and_apply_extra_params(
            original_function,
            {**original_extra_params, **extra_params},
        )

    return function


def clean_properties(schema: dict):
    if not isinstance(schema, dict):
        return

    if 'anyOf' in schema:
        non_null_types = [t for t in schema['anyOf'] if t.get('type') != 'null']
        if len(non_null_types) == 1:
            schema.update(non_null_types[0])
            del schema['anyOf']
        else:
            schema['anyOf'] = non_null_types

    if 'default' in schema and schema['default'] is None:
        del schema['default']

    if 'type' not in schema and 'anyOf' not in schema and 'properties' not in schema:
        schema['type'] = 'string'

    if 'properties' in schema:
        for prop_schema in schema['properties'].values():
            clean_properties(prop_schema)

    if 'items' in schema:
        clean_properties(schema['items'])


def clean_openai_tool_schema(spec: dict) -> dict:
    cleaned_spec = copy.deepcopy(spec)

    if 'parameters' in cleaned_spec:
        clean_properties(cleaned_spec['parameters'])

    return cleaned_spec


def resolve_schema(schema, components):
    if not schema:
        return {}

    if '$ref' in schema:
        ref_path = schema['$ref']
        ref_parts = ref_path.strip('#/').split('/')
        resolved = components
        for part in ref_parts[1:]:
            resolved = resolved.get(part, {})
        return resolve_schema(resolved, components)

    resolved_schema = copy.deepcopy(schema)

    if 'properties' in resolved_schema:
        for prop, prop_schema in resolved_schema['properties'].items():
            resolved_schema['properties'][prop] = resolve_schema(prop_schema, components)

    if 'items' in resolved_schema:
        resolved_schema['items'] = resolve_schema(resolved_schema['items'], components)

    return resolved_schema


def convert_openapi_to_tool_payload(openapi_spec):
    tool_payload = []

    for path, methods in openapi_spec.get('paths', {}).items():
        for method, operation in methods.items():
            if not operation.get('operationId'):
                continue

            tool = {
                'name': operation.get('operationId'),
                'description': operation.get('description', operation.get('summary', 'No description available.')),
                'parameters': {'type': 'object', 'properties': {}, 'required': []},
            }

            for param in operation.get('parameters', []):
                param_name = param.get('name')
                if not param_name:
                    continue

                param_schema = param.get('schema', {})
                description = param_schema.get('description', '') or param.get('description') or ''
                if param_schema.get('enum') and isinstance(param_schema.get('enum'), list):
                    description += f'. Possible values: {", ".join(param_schema.get("enum"))}'

                param_property = {
                    'type': param_schema.get('type') or 'string',
                    'description': description,
                }

                if param_schema.get('type') == 'array' and 'items' in param_schema:
                    param_property['items'] = param_schema['items']

                param_property = {k: v for k, v in param_property.items() if v is not None}
                tool['parameters']['properties'][param_name] = param_property
                if param.get('required'):
                    tool['parameters']['required'].append(param_name)

            request_body = operation.get('requestBody')
            if request_body:
                content = request_body.get('content', {})
                json_schema = content.get('application/json', {}).get('schema')
                if json_schema:
                    resolved_schema = resolve_schema(json_schema, openapi_spec.get('components', {}))

                    if resolved_schema.get('properties'):
                        tool['parameters']['properties'].update(resolved_schema['properties'])
                        if 'required' in resolved_schema:
                            tool['parameters']['required'] = list(
                                set(tool['parameters']['required'] + resolved_schema['required'])
                            )
                    elif resolved_schema.get('type') == 'array':
                        tool['parameters'] = resolved_schema

            tool_payload.append(tool)

    return tool_payload


async def set_tool_servers(request: Request):
    request.app.state.TOOL_SERVERS = await get_tool_servers_data(request.app.state.config.TOOL_SERVER_CONNECTIONS)

    if request.app.state.redis is not None:
        await request.app.state.redis.set('tool_servers', json.dumps(request.app.state.TOOL_SERVERS))

    return request.app.state.TOOL_SERVERS


async def get_tool_servers(request: Request):
    tool_servers = []
    if request.app.state.redis is not None:
        try:
            tool_servers = json.loads(await request.app.state.redis.get('tool_servers'))
            request.app.state.TOOL_SERVERS = tool_servers
        except Exception as e:
            log.error(f'Error fetching tool_servers from Redis: {e}')

    if not tool_servers:
        tool_servers = await set_tool_servers(request)

    return tool_servers





async def get_tool_server_data(url: str, headers: Optional[dict]) -> Dict[str, Any]:
    request_headers = {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
    }

    if headers:
        request_headers.update(headers)

    try:
        timeout = aiohttp.ClientTimeout(total=AIOHTTP_CLIENT_TIMEOUT_TOOL_SERVER_DATA)
        async with aiohttp.ClientSession(timeout=timeout, trust_env=True) as session:
            async with session.get(
                url,
                headers=request_headers,
                ssl=AIOHTTP_CLIENT_SESSION_TOOL_SERVER_SSL,
            ) as response:
                if response.status != 200:
                    error_body = await response.json()
                    raise Exception(error_body)

                text_content = await response.text()
                if url.lower().endswith(('.yaml', '.yml')):
                    res = yaml.safe_load(text_content)
                else:
                    try:
                        res = json.loads(text_content)
                    except json.JSONDecodeError:
                        res = yaml.safe_load(text_content)
    except Exception as err:
        log.exception(f'Could not fetch tool server spec from {url}')
        if isinstance(err, dict) and 'detail' in err:
            raise Exception(err['detail'])
        raise Exception(str(err))

    log.debug(f'Fetched data: {res}')
    return res


async def get_tool_servers_data(servers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    tasks = []
    server_entries = []
    for idx, server in enumerate(servers):
        if server.get('config', {}).get('enable') and server.get('type', 'openapi') == 'openapi':
            info = server.get('info', {})
            auth_type = server.get('auth_type', 'bearer')
            token = None

            if auth_type == 'bearer':
                token = server.get('key', '')

            server_id = info.get('id') or str(idx)
            server_url = server.get('url')
            spec_type = server.get('spec_type', 'url')

            task = None
            if spec_type == 'url':
                openapi_path = server.get('path', 'openapi.json')
                spec_url = get_tool_server_url(server_url, openapi_path)
                task = get_tool_server_data(spec_url, {'Authorization': f'Bearer {token}'} if token else None)
            elif spec_type == 'json' and server.get('spec', ''):
                try:
                    spec_json = json.loads(server.get('spec', ''))
                except Exception as e:
                    log.error(f'Error parsing JSON spec for tool server {server_id}: {e}')
                    spec_json = None

                if spec_json:
                    task = asyncio.sleep(0, result=spec_json)

            if task:
                tasks.append(task)
                server_entries.append((server_id, idx, server, server_url, info, token))

    responses = await asyncio.gather(*tasks, return_exceptions=True)

    results = []
    for (server_id, idx, server, url, info, _), response in zip(server_entries, responses):
        if isinstance(response, Exception):
            log.error(f'Failed to connect to {url} OpenAPI tool server')
            continue

        if not isinstance(response, dict) or 'paths' not in response:
            log.warning(f"Invalid OpenAPI spec from {url}: missing 'paths'")
            continue

        response = {
            'openapi': response,
            'info': response.get('info', {}),
            'specs': convert_openapi_to_tool_payload(response),
        }

        openapi_data = response.get('openapi', {})
        if info and isinstance(openapi_data, dict):
            openapi_data['info'] = openapi_data.get('info', {})

            if 'name' in info:
                openapi_data['info']['title'] = info.get('name', 'Tool Server')

            if 'description' in info:
                openapi_data['info']['description'] = info.get('description', '')

        results.append(
            {
                'id': str(server_id),
                'idx': idx,
                'url': (server.get('url') or '').rstrip('/'),
                'openapi': openapi_data,
                'info': response.get('info'),
                'specs': response.get('specs'),
            }
        )

    return results


async def execute_tool_server(
    url: str,
    headers: Dict[str, str],
    cookies: Dict[str, str],
    name: str,
    params: Dict[str, Any],
    server_data: Dict[str, Any],
) -> Tuple[Any, Optional[Dict[str, Any]]]:
    try:
        openapi = server_data.get('openapi', {})
        paths = openapi.get('paths', {})

        matching_route = None
        for route_path, methods in paths.items():
            for http_method, operation in methods.items():
                if isinstance(operation, dict) and operation.get('operationId') == name:
                    matching_route = (route_path, methods)
                    break
            if matching_route:
                break

        if not matching_route:
            raise Exception(f'No matching route found for operationId: {name}')

        route_path, methods = matching_route
        method_entry = None
        for http_method, operation in methods.items():
            if operation.get('operationId') == name:
                method_entry = (http_method.lower(), operation)
                break

        if not method_entry:
            raise Exception(f'No matching method found for operationId: {name}')

        http_method, operation = method_entry
        path_params = {}
        query_params = {}
        body_params = {}

        for param in operation.get('parameters', []):
            param_name = param.get('name')
            if not param_name:
                continue
            param_in = param.get('in')
            if param_name in params:
                if param_in == 'path':
                    path_params[param_name] = params[param_name]
                if param_in == 'query':
                    value = params[param_name]
                    if value is None or (value == '' and not param.get('required')):
                        continue
                    query_params[param_name] = value

        final_url = f'{url.rstrip("/")}{route_path}'
        for key, value in path_params.items():
            final_url = final_url.replace(f'{{{key}}}', str(value))

        if query_params:
            query_string = '&'.join(f'{k}={v}' for k, v in query_params.items())
            final_url = f'{final_url}?{query_string}'

        if operation.get('requestBody', {}).get('content') and params:
            body_params = params

        async with aiohttp.ClientSession(
            trust_env=True,
            timeout=aiohttp.ClientTimeout(total=AIOHTTP_CLIENT_TIMEOUT_TOOL_SERVER),
        ) as session:
            request_method = getattr(session, http_method.lower())

            request_kwargs = {
                'headers': headers,
                'cookies': cookies,
                'ssl': AIOHTTP_CLIENT_SESSION_TOOL_SERVER_SSL,
                'allow_redirects': False,
            }
            if http_method in ['post', 'put', 'patch', 'delete']:
                request_kwargs['json'] = body_params

            async with request_method(final_url, **request_kwargs) as response:
                if response.status >= 400:
                    text = await response.text()
                    raise Exception(f'HTTP error {response.status}: {text}')

                try:
                    response_data = await response.json()
                except Exception:
                    content_type = response.headers.get('Content-Type', '').split(';')[0].strip()
                    if content_type.startswith('text/') or not content_type:
                        response_data = await response.text()
                    else:
                        raw = await response.read()
                        b64 = base64.b64encode(raw).decode()
                        response_data = f'data:{content_type};base64,{b64}'

                return response_data, response.headers
    except Exception as err:
        error = str(err)
        log.exception(f'API Request Error: {error}')
        return {'error': error}, None


def get_tool_server_url(url: Optional[str], path: str) -> str:
    if '://' in path:
        return path
    if url:
        url = url.rstrip('/')
    if not path.startswith('/'):
        path = f'/{path}'
    return f'{url}{path}'
