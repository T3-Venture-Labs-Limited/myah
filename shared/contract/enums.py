"""Cross-tier string enums shared between the platform backend and Hermes.

This module is the single source of truth for every wire-level string the
platform exchanges with the Hermes agent. TypeScript types are generated from
this file via ``platform/scripts/generate-ts-contract.sh``; the generated
output lives at ``platform/src/lib/types/contract.ts`` and is committed (CI
fails the build if it drifts).

Future workstreams add SSE event types, aux task names, approval option IDs,
output item types, and the platform enum here. Phase 1 lands ``OAuthStatus``
first because the 2026-04-20 incident showed the frontend looping forever on
an unrecognised status — a single typed boundary is the fix.
"""
from __future__ import annotations

from enum import StrEnum


class OAuthStatus(StrEnum):
    """Status values Hermes returns from the OAuth device-code poll endpoint.

    The wire vocabulary is whatever ``hermes_cli/web_server.py`` writes into
    ``_oauth_sessions[session_id]['status']``. As of the 2026-04-25 audit,
    Hermes actually emits four of the six values below (``pending``,
    ``approved``, ``expired``, ``error``); ``denied`` and ``cancelled`` are
    documented in the upstream comment at ``web_server.py:1410`` as part of
    the contract and are reserved here so the backend does not need a
    breaking change when Hermes starts emitting them.

    The platform backend translates ``approved`` to ``complete`` for the
    Svelte frontend (see ``routers/providers.py``), but that translation is a
    separate concern from this enum, which mirrors Hermes' own vocabulary.
    """

    # Initial state after ``POST /providers/{id}/device-auth/start``. The
    # frontend keeps polling while it sees this value.
    PENDING = 'pending'

    # The user successfully completed the device-code flow at the provider's
    # verification URL. Hermes assigns this in
    # ``hermes_cli/web_server.py:1551, 1689, 1824``.
    APPROVED = 'approved'

    # User explicitly rejected the authorisation request at the provider.
    # Reserved — Hermes does not emit this today (2026-04-25). When upstream
    # adds it, the platform must already recognise it.
    DENIED = 'denied'

    # The user (or the platform) cancelled the polling session before the
    # provider responded. Reserved — Hermes' current ``handle_oauth_cancel``
    # pops the session entirely instead of marking it cancelled. The enum
    # carries the value so future Hermes versions can adopt it without a
    # platform-side breaking change.
    CANCELLED = 'cancelled'

    # The session lived past the OAuth grant's TTL. Hermes assigns this in
    # ``hermes_cli/web_server.py:1769``.
    EXPIRED = 'expired'

    # Any unrecoverable failure during the device-code exchange. Hermes
    # assigns this in ``hermes_cli/web_server.py:1532, 1540, 1548, 1694``.
    ERROR = 'error'


class AuxTask(StrEnum):
    """Auxiliary task names dispatched via ``POST /myah/v1/aux/{task}``.

    The wire vocabulary matches the Hermes-side allow-list at
    ``agent/hermes/gateway/platforms/myah.py::_AUX_ALLOWED_TASKS``. Both ends
    must agree exactly: an allow-listed task on one side that the other
    rejects produces a 400 to the user with no fallback. Adding a new aux
    task requires a coordinated change here AND upstream — the cross-tier
    drift test (Phase 5) will fail otherwise.

    Today (2026-04-25) only two tasks are routed through the aux endpoint;
    the platform-level ``AUX_DEFAULT_TASKS`` frozenset in
    ``open_webui/config.py`` enumerates a broader set of *config* tasks
    (``compression``, ``session_search``, ``approval``, ...) but those run
    inside the agent and are not dispatched over the HTTP aux surface.
    """

    # Generate a chat title from the first user/assistant turn. Wired in
    # ``platform/backend/open_webui/routers/tasks.py::_fetch_title_via_aux``
    # (path ``/myah/v1/aux/title_generation``).
    TITLE_GENERATION = 'title_generation'

    # Generate suggested follow-up prompts after a turn completes. Wired in
    # ``routers/tasks.py::_fetch_follow_ups_via_aux`` (path
    # ``/myah/v1/aux/follow_up_generation``).
    FOLLOW_UP_GENERATION = 'follow_up_generation'


# Convenience constant for the tasks the platform forwards to Hermes. Old
# code imports this as ``open_webui.utils.agent_proxy.AUX_ALLOWED_TASKS`` —
# that import path is preserved via re-export in ``agent_proxy.py``.
AUX_ALLOWED_TASKS: frozenset[str] = frozenset({task.value for task in AuxTask})


class ApprovalOption(StrEnum):
    """Choices the user sends back to Hermes for ``tool.confirmation_required``.

    Dispatched by ``POST /openai/chat/confirm`` on the platform backend, then
    forwarded to ``/myah/v1/confirm/{stream_id}`` on the per-user agent
    container. The wire vocabulary is fixed: any string outside this enum
    must be rejected with HTTP 400, otherwise the agent's approval state
    machine will hang waiting for a recognised choice.
    """

    # User accepts this single action.
    APPROVE = 'approve'

    # User rejects this action.
    DENY = 'deny'

    # User accepts every same-type action for the rest of the agent
    # session — the agent stops pausing for further confirmations of the
    # same shape until the session ends or is reset.
    APPROVE_SESSION = 'approve_session'


class HermesPlatform(StrEnum):
    """Mirror of the upstream Hermes platform enum.

    Source of truth: ``agent/hermes/gateway/config.py::Platform``. Every
    value in the upstream enum MUST appear here; the cross-tier drift test
    in ``__tests__/test_tasks_approvals_platforms.py`` imports the upstream
    enum at runtime and asserts set-equality with this one. When Hermes
    adds a new platform (e.g. another bridge), bump this enum in the same
    PR that lifts the submodule SHA — the test fails fast otherwise.

    The ``MYAH`` value is the one this platform identifies as on the wire;
    the rest are present so that responses, status payloads, and config
    enums can round-trip every Hermes-supported platform without losing
    fidelity.
    """

    # Stand-alone CLI runs that don't bind to a messaging surface.
    LOCAL = 'local'

    # The HTTP API server (``hermes_cli/api_server.py``) — bot-style clients.
    API_SERVER = 'api_server'

    # Generic webhook receiver — push integrations.
    WEBHOOK = 'webhook'

    # The Myah platform itself — what this codebase identifies as.
    MYAH = 'myah'

    # First-party messaging platforms.
    TELEGRAM = 'telegram'
    DISCORD = 'discord'
    SLACK = 'slack'
    WHATSAPP = 'whatsapp'
    SIGNAL = 'signal'
    MATTERMOST = 'mattermost'
    MATRIX = 'matrix'
    EMAIL = 'email'
    SMS = 'sms'

    # Smart-home bridge.
    HOMEASSISTANT = 'homeassistant'

    # Chinese-market bridges.
    DINGTALK = 'dingtalk'
    FEISHU = 'feishu'
    WECOM = 'wecom'
    WECOM_CALLBACK = 'wecom_callback'
    WEIXIN = 'weixin'
    QQBOT = 'qqbot'

    # macOS iMessage bridge.
    BLUEBUBBLES = 'bluebubbles'
