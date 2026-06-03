"""Live-state resolution for the chat stream-continuation endpoints.

The freshest truth for an in-flight assistant message is the process-local
``_live_state`` registry written by ``hermes_stream_handler``. But that registry
is intentionally ephemeral (single-process, grace-windowed). After the grace
window expires — or after a browser refresh where the process-local active run
is no longer reachable — the only durable truth is the persisted chat history.

These helpers let ``GET /{id}/messages/{message_id}/live_state`` fall back to a
DB-derived final snapshot so the endpoint stays reachable and useful, instead of
404-ing the moment the in-memory snapshot is gone. They are pure (no DB / no
network) so the route can pass already-owned chat history in and they can be
unit-tested directly.

OSS-safe: no hosted-only imports.
"""

from __future__ import annotations

from typing import Optional


def final_snapshot_from_history(
    chat_id: str,
    message_id: str,
    messages: Optional[dict],
) -> Optional[dict]:
    """Derive a live-state-shaped snapshot from persisted chat history.

    Returns ``None`` when the message is absent or is not a renderable assistant
    message — a non-assistant entry or an empty unstarted shell must never
    masquerade as a live assistant snapshot. ``messages`` is the
    ``history.messages`` map of an already-ownership-checked chat (the route does
    the ownership check before calling this).
    """
    if not messages:
        return None

    message = messages.get(message_id)
    if not isinstance(message, dict):
        return None
    if message.get('role') != 'assistant':
        return None

    content = message.get('content') or ''
    output = list(message.get('output') or [])
    done = bool(message.get('done'))

    # An assistant shell with nothing to show and not yet done is not useful.
    if not content and not output and not done:
        return None

    return {
        'run_id': None,
        'chat_id': chat_id,
        'message_id': message_id,
        'started_at': message.get('timestamp'),
        'updated_at': message.get('timestamp'),
        'message_content': content,
        'reasoning_content': '',
        'output': output,
        'status': 'settled' if done else 'streaming',
        'done': done,
        'source': 'db',
    }


def resolve_live_state(
    chat_id: str,
    message_id: str,
    live_state: dict,
    messages: Optional[dict],
) -> Optional[dict]:
    """Return the freshest available snapshot for (chat_id, message_id).

    The in-memory ``_live_state`` snapshot wins while a run is active; once it is
    gone we fall back to the DB-derived final snapshot. Crucially this fallback
    is NOT gated on a process-local active run existing, so a refresh after the
    grace window can still paint the final/partial assistant state.
    """
    snapshot = live_state.get((chat_id, message_id))
    if snapshot is not None:
        return snapshot
    return final_snapshot_from_history(chat_id, message_id, messages)
