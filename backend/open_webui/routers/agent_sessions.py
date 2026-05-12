# Sessions are the thread that connects past to present —
# the agent's memory of every conversation, every tool call,
# every reasoning step. This router bridges the platform to
# that memory, held faithfully in the agent's own database.

from fastapi import APIRouter, Depends, Query
from open_webui.models.users import UserModel
from open_webui.utils.auth import get_verified_user
from open_webui.utils.hermes_web import web_call_or_raise

router = APIRouter()


@router.get('/sessions')
async def list_hermes_sessions(
    user: UserModel = Depends(get_verified_user),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List sessions from Hermes SessionDB.

    Forwards to Hermes-native ``GET /api/sessions``. Returns
    ``{sessions, total, limit, offset}``. The legacy ``source`` query
    parameter is not supported by the native endpoint and has been removed.
    """
    return await web_call_or_raise(
        user,
        'GET',
        '/api/plugins/myah-admin/sessions',
        params={'limit': limit, 'offset': offset},
    )


@router.get('/sessions/{session_id}/messages')
async def get_session_messages(
    session_id: str,
    user: UserModel = Depends(get_verified_user),
):
    """Get conversation history from Hermes SessionDB.

    Forwards to Hermes-native ``GET /api/sessions/{id}/messages``.
    Returns ``{session_id, messages}``.
    """
    return await web_call_or_raise(
        user, 'GET', f'/api/plugins/myah-admin/sessions/{session_id}/messages'
    )
