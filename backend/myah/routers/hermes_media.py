"""Platform proxy for Hermes container media files.

Authenticates the user session, resolves their agent container base URL,
and streams bytes from GET /myah/v1/media on the container.

Mounted at: GET /api/v1/hermes/media?path=<path>
"""
import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from myah.routers.containers import AGENT_BEARER_TOKEN, _gateway_url, get_or_create_container
from myah.utils.auth import get_verified_user
from myah.utils.hermes_routing import resolve_user_agent_base

router = APIRouter()


@router.get('')
async def get_hermes_media(path: str, user=Depends(get_verified_user)):
    """Proxy a media file from the user's Hermes container.

    Authenticates the caller, resolves the container, and streams the
    file bytes back with the container-reported Content-Type.

    Args:
        path: Absolute path inside the container's cache directory.
              The container validates this against its whitelist.
        user: Authenticated platform user.

    Returns:
        Response with the file's bytes and Content-Type from the agent.
    """
    try:
        record = await get_or_create_container(user.id)
    except Exception:
        raise HTTPException(status_code=503, detail='Agent container unavailable')

    # Tier 2A standalone-runner: /myah/v1/media lives on the gateway port;
    # fall back to host_port for pre-Tier-2A rows.
    raw_url = _gateway_url(record.gateway_port or record.host_port)
    agent_base = resolve_user_agent_base(raw_url)
    if not agent_base:
        raise HTTPException(status_code=404, detail='No agent container for user')

    media_url = f'{agent_base}/myah/v1/media'
    headers = {}
    if AGENT_BEARER_TOKEN:
        headers['Authorization'] = f'Bearer {AGENT_BEARER_TOKEN}'

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            upstream = await client.get(media_url, params={'path': path}, headers=headers)
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f'Agent unreachable: {exc}')

    if upstream.status_code != 200:
        raise HTTPException(
            status_code=upstream.status_code,
            detail=upstream.text[:200] if upstream.text else 'Agent returned error',
        )

    content_type = upstream.headers.get('Content-Type', 'application/octet-stream')
    return Response(
        content=upstream.content,
        media_type=content_type,
        headers={
            # Short cache — persistence pass rewrites refs to /api/v1/files/...
            # before the DB save, so this URL is only hit during the live session.
            'Cache-Control': 'private, max-age=60',
        },
    )
