# Shared helper for forwarding HTTP requests from the platform to the user's
# Hermes agent container.
#
# Two public APIs:
#   aux_call(user, method, path, ...)          -> dict {status, body, headers}
#   aux_call_or_raise(user, method, path, ...) -> body; raises HTTPException on 4xx/5xx
#
# Every request sent from here is a petition. May it reach
# the one for whom it was intended, and return answered.

from typing import Any, Dict, Optional

import httpx
from fastapi import HTTPException
from loguru import logger

from myah.models.users import UserModel
from shared.contract import AUX_ALLOWED_TASKS  # noqa: F401  (re-exported for legacy importers)


async def _get_container_port(user: UserModel, path: str) -> int:
    """Resolve the right host port for ``path`` on the user's container.

    Path-prefix routing:
      * ``/myah/*`` -> gateway port (8643 -> standalone Myah aiohttp runner)
      * everything else -> chat port (8642 -> API server)

    Tier 2A standalone-runner refactor moved /myah/* off the API server.
    Both helpers have the same error contract (raise 503 if no container).
    """
    # Local import to avoid circular dependency at module load time
    from myah.utils.hermes_web import _resolve_chat_port, _resolve_gateway_port

    if path.startswith('/myah/'):
        return await _resolve_gateway_port(user)
    return await _resolve_chat_port(user)


async def aux_call(
    user: UserModel,
    method: str,
    path: str,
    *,
    json_body: Any = None,
    text_body: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: float = 15.0,
) -> Dict[str, Any]:
    """Forward an HTTP request to the user's Hermes container.

    `path` is the FULL path (e.g. '/myah/api/config', '/myah/v1/aux/title_generation').
    Does NOT raise on 4xx/5xx — caller inspects 'status'.

    Returns:
        {'status': int, 'body': parsed-json|str|None, 'headers': dict}
    """
    from myah.routers.containers import AGENT_BEARER_TOKEN, AGENT_HOST

    port = await _get_container_port(user, path)
    url = f'http://{AGENT_HOST}:{port}{path}'
    req_headers: Dict[str, str] = {}
    if AGENT_BEARER_TOKEN:
        req_headers['Authorization'] = f'Bearer {AGENT_BEARER_TOKEN}'
    if headers:
        req_headers.update(headers)

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            if text_body is not None:
                resp = await client.request(method, url, content=text_body, headers=req_headers)
            else:
                resp = await client.request(method, url, json=json_body, headers=req_headers)
    except httpx.ConnectError as e:
        logger.error(f'Agent proxy connect error (user={user.id}, {method} {path}): {e}')
        raise HTTPException(status_code=503, detail='Agent container unavailable — please retry') from e
    except httpx.TimeoutException as e:
        logger.error(f'Agent proxy timeout (user={user.id}, {method} {path}): {e}')
        raise HTTPException(status_code=504, detail='Agent container timed out') from e

    content_type = resp.headers.get('content-type', '')
    if 'application/json' in content_type:
        try:
            body: Any = resp.json()
        except Exception:
            body = resp.text
    elif not resp.content:
        body = None
    else:
        body = resp.text

    return {
        'status': resp.status_code,
        'body': body,
        'headers': dict(resp.headers),
    }


async def aux_call_or_raise(
    user: UserModel,
    method: str,
    path: str,
    *,
    json_body: Any = None,
    timeout: float = 15.0,
) -> Any:
    """aux_call wrapper that raises HTTPException on non-2xx."""
    result = await aux_call(user, method, path, json_body=json_body, timeout=timeout)
    if result['status'] >= 400:
        detail = result['body']
        if isinstance(detail, str):
            detail = detail[:200]
        raise HTTPException(status_code=result['status'], detail=detail)
    return result['body']


# ── Myah: shared catalog normalization ──────────────────────────────────────
def normalize_catalog_models(raw_models: list) -> list[str]:
    """Normalize curated_models entries to model id strings.

    The catalog API may return either old-shape list[str] (plain model ids) or
    new-shape list[dict] with 'id' key (post-PR-2). Both forms are coerced to
    plain strings so callers can do catalog membership checks uniformly.
    """
    return [m['id'] if isinstance(m, dict) else m for m in (raw_models or [])]
# ────────────────────────────────────────────────────────────────────────────
