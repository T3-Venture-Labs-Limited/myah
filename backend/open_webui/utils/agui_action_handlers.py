# Known actions that execute on the backend directly,
# bypassing the agent for reliability and security.
# Returns a string confirmation (injected as [System note: ...])
# or None to pass through to the agent.

import asyncio
import json

import httpx
from fastapi import HTTPException
from loguru import logger
from open_webui.models.containers import Containers
from open_webui.models.users import Users
from open_webui.routers.containers import get_or_create_container
from open_webui.utils.hermes_web import web_call_or_raise

AGENTMAIL_API_BASE = 'https://api.agentmail.to/v0'


async def _resolve_user_from_metadata(metadata: dict):
    """Resolve the UserModel for an action's metadata.

    Ensures the user's container is provisioned so its hermes dashboard
    has a port + session token recorded on the DB row before web_call_or_raise
    tries to use them.
    """
    user_id = metadata.get('user_id')
    if not user_id:
        raise HTTPException(status_code=401, detail='User not authenticated')

    user = await asyncio.to_thread(Users.get_user_by_id, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail='User not found')

    record = await asyncio.to_thread(Containers.get_by_user_id, user_id)
    if record is None or not record.web_port or not record.web_session_token:
        # Force a spawn / restart so the dashboard endpoint is reachable
        record = await get_or_create_container(user_id)
        if record is None or not record.web_port or not record.web_session_token:
            raise HTTPException(status_code=503, detail='Agent container unavailable')
    return user


async def _get_container_port_from_metadata(metadata: dict) -> int:
    """Resolve container host port from request metadata (user_id).

    Kept for compatibility — currently unused by the migrated handlers
    but may be needed by callers outside this module.
    """
    user_id = metadata.get('user_id')
    if not user_id:
        raise HTTPException(status_code=401, detail='User not authenticated')

    record = await asyncio.to_thread(Containers.get_by_user_id, user_id)
    if record and record.host_port:
        return record.host_port

    record = await get_or_create_container(user_id)
    if not record or not record.host_port:
        raise HTTPException(status_code=503, detail='Agent container unavailable')
    return record.host_port


async def _get_agentmail_api_key(metadata: dict) -> str:
    """Read AGENTMAIL_API_KEY from the agent's env via Hermes /api/env."""
    user = await _resolve_user_from_metadata(metadata)
    env_list = await web_call_or_raise(user, 'GET', '/api/plugins/myah-admin/env', timeout=10.0)

    # env_list is [{key, value, value_redacted, ...}] — find AGENTMAIL_API_KEY's
    # unredacted value. Hermes /api/env returns the real value (the dashboard
    # is protected by the per-container session token, not by redaction).
    key = next(
        (
            entry.get('value')
            for entry in (env_list if isinstance(env_list, list) else [])
            if entry.get('key') == 'AGENTMAIL_API_KEY' and entry.get('value')
        ),
        None,
    )
    if not key:
        raise HTTPException(
            status_code=503,
            detail='AgentMail API key not configured. Use env_vars_form to set AGENTMAIL_API_KEY.',
        )
    return key


async def _email_label_action(
    action: dict,
    metadata: dict,
    add_labels: list[str],
    remove_labels: list[str],
    step: str,
    ok_message: str,
) -> str:
    """Apply label changes to a message via AgentMail API."""
    data = action.get('data', {})
    inbox_id = data.get('inbox_id') or action.get('inbox_id')
    message_id = data.get('message_id') or action.get('message_id')
    if not inbox_id or not message_id:
        return f'Missing inbox_id or message_id for {step} action.'

    logger.bind(step=step, inbox_id=inbox_id, message_id=message_id).info(
        f'Applying labels: +{add_labels}, -{remove_labels}'
    )
    try:
        api_key = await _get_agentmail_api_key(metadata)
        async with httpx.AsyncClient() as client:
            resp = await client.patch(
                f'{AGENTMAIL_API_BASE}/inboxes/{inbox_id}/messages/{message_id}',
                headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
                json={'add_labels': add_labels, 'remove_labels': remove_labels},
                timeout=httpx.Timeout(5.0, read=10.0),
            )
        if resp.status_code == 404:
            return 'Message not found.'
        if resp.status_code not in (200, 201):
            return f'AgentMail error: {resp.status_code} {resp.text[:100]}'
        return ok_message
    except httpx.TimeoutException:
        return 'AgentMail API timed out. Please try again.'
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f'{step} failed: {e}', exc_info=True)
        return f'Failed to {step}: {e}'


async def handle_known_action(
    action: dict,
    metadata: dict,
) -> str | None:
    """Route known UI actions to their backend handlers.

    Returns a confirmation string if the action was handled,
    or None if the action should pass through to the agent.
    """
    if not isinstance(action, dict):
        return None

    action_name = action.get('action', '')
    composition = action.get('composition', '')

    handler = _HANDLERS.get((composition, action_name))
    if handler is None:
        return None

    try:
        return await handler(action, metadata)
    except Exception as exc:
        logger.warning(f'Backend action handler failed: {exc}')
        return f'Action handler error: {exc}'


async def _handle_env_vars_submit(action: dict, metadata: dict) -> str:
    """Store environment variables submitted by the user.

    Writes to the agent's .env file via the Hermes management HTTP API,
    then confirms receipt for the agent.
    """
    data = action.get('data', {})
    if not data:
        return 'No environment variables provided.'

    var_names = list(data.keys())
    logger.bind(
        step='env_vars_submit',
        variables=var_names,
        user_id=metadata.get('user_id'),
    ).info('Writing env vars to agent via HTTP API')

    try:
        user = await _resolve_user_from_metadata(metadata)
        for key, value in data.items():
            await web_call_or_raise(
                user,
                'PUT',
                '/api/plugins/myah-admin/env',
                json_body={'key': key, 'value': value},
                timeout=10.0,
            )
    except HTTPException as exc:
        # 503/504 from web_call_or_raise become user-friendly strings instead of
        # propagating to the caller — the existing contract here is "return error
        # text, do not raise". Any other HTTPException (e.g. 401 from auth) bubbles up.
        if exc.status_code == 503:
            return 'Agent container unavailable — please retry.'
        if exc.status_code == 504:
            return 'Agent container timed out while writing env vars.'
        raise
    except Exception as e:
        logger.error(f'env_vars_submit failed: {e}', exc_info=True)
        return f'Failed to write env vars: {e}'

    redacted = {k: f'{str(v)[:3]}***' if len(str(v)) > 6 else '***' for k, v in data.items()}
    return f'Environment variables written to agent .env: {json.dumps(redacted)}'


async def _handle_email_mark_read(action: dict, metadata: dict) -> str:
    """Mark an email thread as read via AgentMail API."""
    return await _email_label_action(action, metadata, ['read'], [], 'email_mark_read', 'Email marked as read.')


async def _handle_email_mark_unread(action: dict, metadata: dict) -> str:
    """Mark an email thread as unread via AgentMail API."""
    return await _email_label_action(action, metadata, [], ['read'], 'email_mark_unread', 'Email marked as unread.')


async def _handle_email_archive(action: dict, metadata: dict) -> str:
    """Archive an email thread via AgentMail API."""
    return await _email_label_action(action, metadata, ['archived'], [], 'email_archive', 'Email archived.')


async def _handle_email_reply(action: dict, metadata: dict) -> str | None:
    """Open reply composer — passes to agent to fetch thread and generate draft.

    Returns None so the action goes back to the agent with context about
    which thread the user wants to reply to.
    """
    return None


async def _handle_email_send_reply(action: dict, metadata: dict) -> str:
    """Send a reply to an email thread via AgentMail API.

    The form data must contain: inbox_id, message_id, and body (the reply text).
    """
    data = action.get('data', {})
    inbox_id = data.get('inbox_id') or action.get('inbox_id')
    message_id = data.get('message_id') or action.get('message_id')
    body = data.get('body', '').strip()

    if not inbox_id or not message_id:
        return 'Missing inbox_id or message_id for send_reply action.'
    if not body:
        return 'Cannot send empty reply. Please write a message.'

    logger.bind(step='email_send_reply', inbox_id=inbox_id, message_id=message_id).info('Sending reply')
    try:
        api_key = await _get_agentmail_api_key(metadata)
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f'{AGENTMAIL_API_BASE}/inboxes/{inbox_id}/messages/{message_id}/reply',
                headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
                json={'text': body},
                timeout=httpx.Timeout(5.0, read=15.0),
            )
        if resp.status_code == 404:
            return 'Message not found.'
        if resp.status_code not in (200, 201):
            return f'AgentMail error: {resp.status_code} {resp.text[:100]}'
        preview = body[:50] + ('...' if len(body) > 50 else '')
        return f'Reply sent successfully: "{preview}"'
    except httpx.TimeoutException:
        return 'AgentMail API timed out. Your reply was not sent. Please try again.'
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f'email_send_reply failed: {e}', exc_info=True)
        return f'Failed to send reply: {e}'


async def _handle_email_discard(action: dict, metadata: dict) -> str:
    """Discard an email draft — no-op, just confirm."""
    return 'Email draft discarded. No email was sent.'


# Registry of (composition, action) -> handler
_HANDLERS: dict[tuple[str, str], object] = {
    ('env_vars_form', 'env_vars_submit'): _handle_env_vars_submit,
    # Email — thread list actions
    ('email_thread_list', 'mark_read'): _handle_email_mark_read,
    ('email_thread_list', 'mark_unread'): _handle_email_mark_unread,
    ('email_thread_list', 'archive'): _handle_email_archive,
    ('email_thread_list', 'reply'): _handle_email_reply,
    # Email — compose form actions
    ('email_reply_compose', 'send_reply'): _handle_email_send_reply,
    ('email_reply_compose', 'Discard'): _handle_email_discard,
    # Legacy email_reply (keep for existing agents)
    ('email_reply', 'Discard'): _handle_email_discard,
    ('email_reply', 'send_reply'): _handle_email_send_reply,
}
