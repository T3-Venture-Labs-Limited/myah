"""Multi-user aggregation helpers backed by per-user Hermes SessionDB.

Once Workstream H Phase 5 has shipped and chat content lives canonically inside
each user's Hermes SessionDB, admin-facing analytics queries can no longer hit
the platform DB for token usage, active-chat counts, or full-text search across
users — that data has migrated out of the platform and into N per-user
containers. This module is the indirection layer for those cross-user queries.

PHASE 1 STATUS: STUB ONLY.
Every helper below raises ``NotImplementedError("Phase 7")``. The signatures
are committed so callers in upcoming phases (admin analytics dashboard, ops
search tooling) can already import and reference them, while the actual
multi-container fan-out implementation is deferred to Phase 7. Phase 7 will
iterate per-user Hermes containers via ``myah.utils.hermes_web.web_call``
(introduced in Workstream A Phase 0) and aggregate the responses with
rate-limiting and error tolerance.

See ``docs/superpowers/specs/2026-04-24-workstream-h-chat-state-unification-design.md``
§4 ("Cross-User Query Aggregation") and the matching plan §"Phase 7" for the
full design.
"""

from __future__ import annotations

import datetime as dt


async def sum_tokens_across_users(user_ids: list[str]) -> dict[str, int]:
    """Aggregate token usage across multiple users' Hermes SessionDBs.

    Used by the admin analytics dashboard. Returns a mapping of
    ``{user_id: total_tokens}``. Phase 7 implementation iterates per-user
    containers via ``hermes_web.web_call`` against an analytics endpoint
    each container exposes; this stub raises so that any caller arriving
    early (i.e. before Phase 7) fails loudly instead of silently returning
    empty data.

    Args:
        user_ids: List of platform-DB user IDs whose containers should be
            queried. Phase 7 will rate-limit the fan-out to avoid pinning
            CPU on user containers that are also serving live chats.

    Returns:
        Mapping of ``user_id`` → total token count across all that user's
        sessions. Users whose container is unreachable are omitted (not
        zeroed) so callers can distinguish "no usage" from "no data".
    """
    # TODO: Phase 7 implementation — fan out to per-user Hermes containers
    # via hermes_web.web_call(user, 'GET', '/api/analytics/usage'), aggregate
    # the responses, cache the result with a short TTL in platform DB.
    raise NotImplementedError('Phase 7')


async def count_active_chats_for_user(user_id: str, since: dt.datetime) -> int:
    """Count chats with at least one message authored after ``since``.

    "Active" means the user (or the agent on the user's behalf) wrote a
    message in the session at or after ``since``. Backed by Hermes
    SessionDB's ``sessions.last_active`` field. Phase 7 implementation
    queries the user's Hermes container via ``hermes_web.web_call``.

    Args:
        user_id: Platform-DB user ID. The corresponding Hermes container is
            resolved at call time.
        since: Cutoff timestamp; only sessions with ``last_active >= since``
            are counted.

    Returns:
        Integer count of active sessions. Returns ``0`` if the user has no
        sessions; raises if the container is unreachable so the admin UI
        can surface the error rather than report a falsely-low count.
    """
    # TODO: Phase 7 implementation — call hermes_web.web_call(user, 'GET',
    # f'/api/sessions?since={since.isoformat()}') and return len(sessions).
    raise NotImplementedError('Phase 7')


async def search_across_users_for_admin(
    query: str, user_ids: list[str], limit: int = 50
) -> list[dict]:
    """Admin-only multi-tenant FTS5 search across users' Hermes SessionDBs.

    Restricted to admin-role callers; the platform DB does not have the
    indexed message bodies after Phase 5, so an admin investigation (abuse
    triage, support escalation) needs to fan out to multiple users'
    containers. Each container's Hermes web exposes ``/api/sessions/search``
    backed by SQLite FTS5; this helper calls it per user and merges results.

    Args:
        query: FTS5 query string. Passed through verbatim — callers are
            responsible for FTS5 syntax escaping if needed.
        user_ids: List of platform-DB user IDs to fan out to.
        limit: Maximum number of merged results to return. The per-user
            sub-query also enforces this limit so the network payload stays
            bounded.

    Returns:
        List of result dicts, each containing at minimum ``user_id``,
        ``session_id``, ``snippet``, and ``score``. Sorted by descending
        score across all users.
    """
    # TODO: Phase 7 implementation — fan out hermes_web.web_call(user, 'GET',
    # f'/api/sessions/search?q={quote(query)}&limit={limit}') per user, tag
    # each result with the originating user_id, then merge-sort by score.
    raise NotImplementedError('Phase 7')
