import asyncio
import base64
import inspect
import io
import json
import logging
import mimetypes
import os
import shutil
import sys
import time
import random
import re
from uuid import uuid4


from contextlib import asynccontextmanager
from urllib.parse import urlencode, parse_qs, urlparse
from pydantic import BaseModel
from sqlalchemy import text

from typing import Optional
from aiocache import cached
import aiohttp
import anyio.to_thread
import requests
from redis import Redis


from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    status,
    applications,
    BackgroundTasks,
)
from fastapi.openapi.docs import get_swagger_ui_html

from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from starlette_compress import CompressMiddleware

from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import Response, StreamingResponse
from starlette.datastructures import Headers

from starsessions import (
    SessionMiddleware as StarSessionsMiddleware,
    SessionAutoloadMiddleware,
)
from starsessions.stores.redis import RedisStore

from myah.utils import logger
from myah.utils.audit import AuditLevel, AuditLoggingMiddleware
from myah.utils.logger import start_logger
from myah.socket.main import (
    MODELS,
    app as socket_app,
    periodic_usage_pool_cleanup,
    periodic_session_pool_cleanup,
    get_event_emitter,
    get_models_in_use,
)
from myah.routers import (
    openai,
    tasks,
    auths,
    chats,
    notes,
    folders,
    configs,
    files,
    users,
    utils,
)
from myah.routers import containers, processes, agent_capabilities, agent_sessions
from myah.routers import agent_config as agent_config_router
from myah.routers import hermes_media
from myah.routers import myah as myah_router_module
from myah.routers import providers as providers_router_module
from myah.routers import oss as oss_router_module

# OSS-split: agent_memory + integrations are hosted-only routers (honcho /
# composio coupled). They are imported + registered only when the deployment
# is NOT in OSS mode. See is_oss_mode() in utils/hermes_web.py.
from myah.utils.hermes_web import is_oss_mode as _is_oss_mode

if not _is_oss_mode():
    from myah.routers import admin_cron_deliveries, agent_memory, integrations


from sqlalchemy.orm import Session
from myah.internal.db import ScopedSession, engine, get_session

from myah.models.models import Models
from myah.models.users import UserModel, Users
from myah.models.chats import Chats

from myah.config import (
    # OpenAI
    ENABLE_OPENAI_API,
    OPENAI_API_BASE_URLS,
    OPENAI_API_KEYS,
    OPENAI_API_CONFIGS,
    # Direct Connections
    ENABLE_DIRECT_CONNECTIONS,
    # Model list
    ENABLE_BASE_MODELS_CACHE,
    # Thread pool size for FastAPI/AnyIO
    THREAD_POOL_SIZE,
    # Tool Server Configs
    TOOL_SERVER_CONNECTIONS,
    # Uploads
    UPLOAD_DIR,
    # WebUI
    WEBUI_AUTH,
    WEBUI_NAME,
    WEBUI_BANNERS,
    WEBHOOK_URL,
    ADMIN_EMAIL,
    SHOW_ADMIN_DETAILS,
    JWT_EXPIRES_IN,
    ENABLE_SIGNUP,
    ENABLE_LOGIN_FORM,
    ENABLE_API_KEYS,
    ENABLE_API_KEYS_ENDPOINT_RESTRICTIONS,
    API_KEYS_ALLOWED_ENDPOINTS,
    ENABLE_FOLDERS,
    FOLDER_MAX_FILE_COUNT,
    ENABLE_NOTES,
    ENABLE_USER_WEBHOOKS,
    BYPASS_ADMIN_ACCESS_CONTROL,
    USER_PERMISSIONS,
    DEFAULT_USER_ROLE,
    DEFAULT_GROUP_ID,
    PENDING_USER_OVERLAY_CONTENT,
    PENDING_USER_OVERLAY_TITLE,
    DEFAULT_PROMPT_SUGGESTIONS,
    DEFAULT_MODELS,
    DEFAULT_PINNED_MODELS,
    MODEL_ORDER_LIST,
    DEFAULT_MODEL_METADATA,
    DEFAULT_MODEL_PARAMS,
    # WebUI (OAuth)
    ENABLE_OAUTH_ROLE_MANAGEMENT,
    OAUTH_SUB_CLAIM,
    OAUTH_ROLES_CLAIM,
    OAUTH_EMAIL_CLAIM,
    OAUTH_PICTURE_CLAIM,
    OAUTH_USERNAME_CLAIM,
    OAUTH_ALLOWED_ROLES,
    OAUTH_ADMIN_ROLES,
    # Misc
    ENV,
    CACHE_DIR,
    STATIC_DIR,
    FRONTEND_BUILD_DIR,
    CORS_ALLOW_ORIGIN,
    DEFAULT_LOCALE,
    OAUTH_PROVIDERS,
    WEBUI_URL,
    RESPONSE_WATERMARK,
    # Admin
    ENABLE_ADMIN_CHAT_ACCESS,
    ENABLE_ADMIN_ANALYTICS,
    ENABLE_ADMIN_EXPORT,
    # Tasks
    TASK_MODEL,
    TASK_MODEL_EXTERNAL,
    ENABLE_TAGS_GENERATION,
    ENABLE_TITLE_GENERATION,
    ENABLE_FOLLOW_UP_GENERATION,
    ENABLE_SEARCH_QUERY_GENERATION,
    ENABLE_AUTOCOMPLETE_GENERATION,
    TITLE_GENERATION_PROMPT_TEMPLATE,
    FOLLOW_UP_GENERATION_PROMPT_TEMPLATE,
    AUTOCOMPLETE_GENERATION_INPUT_MAX_LENGTH,
    AppConfig,
    reset_config,
)
from myah.env import (
    ENABLE_CUSTOM_MODEL_FALLBACK,
    AUDIT_EXCLUDED_PATHS,
    AUDIT_INCLUDED_PATHS,
    AUDIT_LOG_LEVEL,
    CHANGELOG,
    REDIS_URL,
    REDIS_CLUSTER,
    REDIS_KEY_PREFIX,
    REDIS_SENTINEL_HOSTS,
    REDIS_SENTINEL_PORT,
    GLOBAL_LOG_LEVEL,
    MAX_BODY_LOG_SIZE,
    SAFE_MODE,
    VERSION,
    DEPLOYMENT_ID,
    INSTANCE_ID,
    WEBUI_BUILD_HASH,
    WEBUI_SECRET_KEY,
    WEBUI_SESSION_COOKIE_SAME_SITE,
    WEBUI_SESSION_COOKIE_SECURE,
    ENABLE_SIGNUP_PASSWORD_CONFIRMATION,
    WEBUI_AUTH_TRUSTED_EMAIL_HEADER,
    WEBUI_AUTH_TRUSTED_NAME_HEADER,
    WEBUI_AUTH_SIGNOUT_REDIRECT_URL,
    ENABLE_COMPRESSION_MIDDLEWARE,
    ENABLE_WEBSOCKET_SUPPORT,
    BYPASS_MODEL_ACCESS_CONTROL,
    RESET_CONFIG_ON_START,
    ENABLE_VERSION_UPDATE_CHECK,
    ENABLE_OTEL,
    AIOHTTP_CLIENT_SESSION_SSL,
    ENABLE_STAR_SESSIONS_MIDDLEWARE,
    ENABLE_PUBLIC_ACTIVE_USERS_COUNT,
    # Admin Account Runtime Creation
    WEBUI_ADMIN_EMAIL,
    WEBUI_ADMIN_PASSWORD,
    WEBUI_ADMIN_NAME,
    ENABLE_EASTER_EGGS,
    LOG_FORMAT,
)


from myah.utils.models import (
    get_all_models,
    get_all_base_models,
    check_model_access,
    get_filtered_models,
)
from myah.utils.chat import (
    generate_chat_completion as chat_completion_handler,
    chat_completed as chat_completed_handler,
)
from myah.utils.chat_payload import (
    process_chat_payload,
)
from myah.utils.chat_tasks import (
    build_chat_response_context,
)
from myah.utils.tool_servers import set_tool_servers

from myah.utils.auth import (
    get_http_authorization_cred,
    decode_token,
    get_admin_user,
    get_verified_user,
    create_admin_user,
)
from myah.utils.oauth import (
    get_oauth_client_info_with_dynamic_client_registration,
    get_oauth_client_info_with_static_credentials,
    encrypt_data,
    decrypt_data,
    OAuthManager,
    OAuthClientManager,
    OAuthClientInformationFull,
)
from myah.utils.security_headers import SecurityHeadersMiddleware
from myah.utils.redis import get_redis_connection

from myah.tasks import (
    redis_task_command_listener,
    list_task_ids_by_item_id,
    create_task,
    stop_task,
    list_tasks,
)  # Import from tasks.py

from myah.utils.redis import get_sentinels_from_env


from myah.constants import ERROR_MESSAGES

if SAFE_MODE:
    print('SAFE MODE ENABLED')

logging.basicConfig(stream=sys.stdout, level=GLOBAL_LOG_LEVEL)
log = logging.getLogger(__name__)

# ── Pipeline timing log file ───────────────────────────────────────────────
# Captures [CHAT_PIPELINE], [BG_TASK] and [TASK_MODEL] entries to a file
# so they can be inspected independently of the uvicorn terminal.
_pipeline_log = logging.getLogger('pipeline_file')
_pipeline_log.setLevel(logging.DEBUG)
_pipeline_fh = logging.FileHandler('/tmp/myah_pipeline.log', mode='a')
_pipeline_fh.setLevel(logging.DEBUG)
_pipeline_fh.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
_pipeline_log.addHandler(_pipeline_fh)


class _PipelineFilter(logging.Filter):
    def filter(self, record):
        msg = record.getMessage()
        if '[CHAT_PIPELINE]' in msg or '[BG_TASK]' in msg or '[TASK_MODEL]' in msg:
            _pipeline_log.info(msg)
        return True


logging.getLogger().addFilter(_PipelineFilter())


# OSS public client-routed paths that fall through to index.html. The app is a
# pure SPA (ssr=false, adapter-static fallback) so the server has no route table
# of its own; this mirrors platform-oss/src/routes. Anything not matched gets a
# real 404 instead of a misleading 200 app shell so crawler-trash / fake URLs
# don't unfurl. Hosted-only routes (admin, integrations, memory) are layered in
# from platform-hosted/ via _load_hosted_spa_routes() and only when NOT in OSS
# mode — keeping hosted route knowledge out of the OSS canon (anti-SaaS-fork).
# Keep in sync when adding a SvelteKit public route; the drift tests in both
# repos fail if this falls behind.
#
# Deep-link limitation (intentional): only paths backed by a +page.svelte in
# the route file tree are served. A path-param deep link (e.g.
# /agent/skills/edit/<name>) 404s unless its route declares a [param] segment.
# The two param-less edit pages take their entity via query string instead
# (/agent/skills/edit?name=…, /agent/tools/edit?id=…), so their deep links
# match the param-less allowlist entry and still serve the shell. New nested
# deep links must either add a [param] route (auto-covered by the drift tests)
# or use query params; test_seo_hygiene.py guards this for the edit pages.
_SPA_STATIC_ROUTES = frozenset(
    {
        '/',
        '/auth',
        '/error',
        '/c',
        '/notes',
        '/notes/new',
        '/spaces',
        '/diagnostics',
        '/agent',
        '/agent/settings',
        '/agent/skills',
        '/agent/skills/create',
        '/agent/skills/edit',
        '/agent/tools',
        '/agent/tools/create',
        '/agent/tools/edit',
    }
)
_SPA_DYNAMIC_ROUTES = (
    re.compile(r'^/c/[^/]+$'),
    re.compile(r'^/notes/[^/]+$'),
    re.compile(r'^/spaces/[^/]+$'),
)

_hosted_spa_routes_cache: tuple[frozenset, tuple] | None = None


def _load_hosted_spa_routes() -> tuple[frozenset, tuple]:
    global _hosted_spa_routes_cache
    if _hosted_spa_routes_cache is not None:
        return _hosted_spa_routes_cache
    try:
        from myah.utils.spa_fallback_routes import HOSTED_SPA_DYNAMIC_ROUTES, HOSTED_SPA_ROUTES
    except ModuleNotFoundError as exc:
        # OSS build: the hosted overlay module is absent. Fail closed (no
        # hosted routes) rather than re-raising an unrelated import error.
        if exc.name == 'myah.utils.spa_fallback_routes':
            _hosted_spa_routes_cache = (frozenset(), ())
            return _hosted_spa_routes_cache
        raise
    _hosted_spa_routes_cache = (
        frozenset(HOSTED_SPA_ROUTES),
        tuple(re.compile(p) for p in HOSTED_SPA_DYNAMIC_ROUTES),
    )
    return _hosted_spa_routes_cache


def is_spa_route(path: str) -> bool:
    normalized = '/' + path.strip('/') if path not in ('', '.') else '/'
    if normalized in _SPA_STATIC_ROUTES or any(rx.match(normalized) for rx in _SPA_DYNAMIC_ROUTES):
        return True
    if _is_oss_mode():
        return False
    hosted_static, hosted_dynamic = _load_hosted_spa_routes()
    if normalized in hosted_static:
        return True
    return any(rx.match(normalized) for rx in hosted_dynamic)


_IMMUTABLE_ASSET_PREFIXES = ('_app/immutable/',)
_LONG_CACHE_EXTS = ('.svg', '.png', '.webp', '.avif', '.jpg', '.jpeg', '.ico', '.woff2', '.woff')


class SPAStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        try:
            response = await super().get_response(path, scope)
        except (HTTPException, StarletteHTTPException) as ex:
            if ex.status_code == 404 and not path.endswith('.js') and is_spa_route(path):
                return await super().get_response('index.html', scope)
            raise ex

        if path.startswith(_IMMUTABLE_ASSET_PREFIXES):
            response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
        elif path.lower().endswith(_LONG_CACHE_EXTS):
            response.headers['Cache-Control'] = 'public, max-age=2592000'
        return response


if LOG_FORMAT != 'json':
    print(rf"""
  __  __             _
 |  \/  |_   _  __ _| |__
 | |\/| | | | |/ _` | '_ \
 | |  | | |_| | (_| | | | |
 |_|  |_|\__, |\__,_|_| |_|
          |___/  building agent workstations

v{VERSION}
{f'Commit: {WEBUI_BUILD_HASH}' if WEBUI_BUILD_HASH != 'dev-build' else ''}
""")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Store reference to main event loop for sync->async calls (e.g., embedding generation)
    # This allows sync functions to schedule work on the main loop without blocking health checks
    app.state.main_loop = asyncio.get_running_loop()

    app.state.instance_id = INSTANCE_ID
    start_logger()

    if RESET_CONFIG_ON_START:
        reset_config()

    # Create admin account from env vars if specified and no users exist
    if WEBUI_ADMIN_EMAIL and WEBUI_ADMIN_PASSWORD:
        if create_admin_user(WEBUI_ADMIN_EMAIL, WEBUI_ADMIN_PASSWORD, WEBUI_ADMIN_NAME):
            # Disable signup since we now have an admin
            app.state.config.ENABLE_SIGNUP = False

    app.state.redis = get_redis_connection(
        redis_url=REDIS_URL,
        redis_sentinels=get_sentinels_from_env(REDIS_SENTINEL_HOSTS, REDIS_SENTINEL_PORT),
        redis_cluster=REDIS_CLUSTER,
        async_mode=True,
    )

    if app.state.redis is not None:
        app.state.redis_task_command_listener = asyncio.create_task(redis_task_command_listener(app))

    if THREAD_POOL_SIZE and THREAD_POOL_SIZE > 0:
        limiter = anyio.to_thread.current_default_thread_limiter()
        limiter.total_tokens = THREAD_POOL_SIZE

    # Reconcile agent-container DB rows with Docker reality. The deploy
    # workflow stops all per-user agent containers between image swaps so
    # they re-spawn on the new image — but it does not touch the DB. Without
    # this pass, every stale 'running' row would send aux_call to a dead
    # host_port, producing infinite-loading 504s until each user's first
    # idle-probe fired. See containers.py::reconcile_with_running_containers
    # and agent_capabilities.py::_get_container_port for the defence-in-depth.
    #
    # OSS mode: skip reconciliation entirely. Self-hosted single-tenant
    # deployments don't manage containers — the user runs Hermes directly
    # on the host. There's nothing to reconcile.
    from myah.utils.hermes_web import is_oss_mode as _is_oss_mode

    if _is_oss_mode():
        log.info('OSS mode active (MYAH_DEPLOYMENT_MODE=oss): skipping container reconciliation')
    else:
        try:
            import docker
            from myah.models.containers import Containers as _Containers

            _docker = docker.from_env()
            _running = {c.name for c in _docker.containers.list(filters={'name': 'myah-agent-'})}
            _fixed = await asyncio.to_thread(_Containers.reconcile_with_running_containers, _running)
            if _fixed:
                log.warning(f'Startup reconcile: marked {_fixed} stale agent container rows as stopped')
        except Exception as _reconcile_err:
            # Non-fatal. Per-request get_or_create_container still detects dead
            # containers via the 3s health probe; this is just a fast-path win.
            log.warning(f'Startup reconcile skipped: {_reconcile_err}')

    asyncio.create_task(periodic_usage_pool_cleanup())
    asyncio.create_task(periodic_session_pool_cleanup())

    # Cron delivery outbox worker (T3-1087). Only runs in shadow + outbox modes;
    # legacy skips registration so OSS-default users see zero new background tasks.
    # Mode is read via get_cron_delivery_mode() (function call, not module-level
    # constant — per plan-review C-E).
    from myah.env import get_cron_delivery_mode
    from myah.utils.cron_outbox_lifespan import register_outbox_worker_if_enabled

    register_outbox_worker_if_enabled(app, get_cron_delivery_mode())

    # Cron outbox cleanup task — same gate as the worker (per plan-review C-E:
    # call get_cron_delivery_mode() each time so monkeypatched env vars in tests
    # take effect; don't bind a module-level constant).
    if get_cron_delivery_mode() in ('shadow', 'outbox'):
        from myah.utils.cron_outbox_cleanup import periodic_cron_outbox_cleanup

        asyncio.create_task(periodic_cron_outbox_cleanup())

    if app.state.config.ENABLE_BASE_MODELS_CACHE:
        try:
            await get_all_models(
                Request(
                    # Creating a mock request object to pass to get_all_models
                    {
                        'type': 'http',
                        'asgi.version': '3.0',
                        'asgi.spec_version': '2.0',
                        'method': 'GET',
                        'path': '/internal',
                        'query_string': b'',
                        'headers': Headers({}).raw,
                        'client': ('127.0.0.1', 12345),
                        'server': ('127.0.0.1', 80),
                        'scheme': 'http',
                        'app': app,
                    }
                ),
                None,
            )
        except Exception as e:
            log.warning(f'Failed to pre-fetch models at startup: {e}')

    # Pre-fetch tool server specs so the first request doesn't pay the latency cost
    if len(app.state.config.TOOL_SERVER_CONNECTIONS) > 0:
        log.info('Initializing tool servers...')
        try:
            mock_request = Request(
                {
                    'type': 'http',
                    'asgi.version': '3.0',
                    'asgi.spec_version': '2.0',
                    'method': 'GET',
                    'path': '/internal',
                    'query_string': b'',
                    'headers': Headers({}).raw,
                    'client': ('127.0.0.1', 12345),
                    'server': ('127.0.0.1', 80),
                    'scheme': 'http',
                    'app': app,
                }
            )
            await set_tool_servers(mock_request)
            log.info(f'Initialized {len(app.state.TOOL_SERVERS)} tool server(s)')

        except Exception as e:
            log.warning(f'Failed to initialize tool/terminal servers at startup: {e}')

    # ── Load skill compositions ────────────────────────────────────────────────
    try:
        from myah.utils.skill_compositions import load_skill_compositions

        count = load_skill_compositions()
        log.info(f'Loaded {count} skill composition(s)')
    except Exception as e:
        log.warning(f'Failed to load skill compositions: {e}')
    # ────────────────────────────────────────────────────────────────────────────

    # ── Sentry error tracking, tracing, and logging ─────────────────────────────
    from myah.env import SENTRY_DSN_PLATFORM as _sentry_dsn

    if _sentry_dsn:
        try:
            import re as _re
            import sentry_sdk
            from sentry_sdk.integrations.fastapi import FastApiIntegration
            from sentry_sdk.integrations.starlette import StarletteIntegration
            from sentry_sdk.integrations.logging import LoggingIntegration
            from sentry_sdk.integrations.aiohttp import AioHttpIntegration
            import logging as _logging

            # Silence OpenTelemetry exporter noise — the OTEL → Grafana pipeline
            # is not running in dev, so connection errors from the OTLP gRPC
            # exporter are expected and should not create Sentry issues.
            _logging.getLogger('opentelemetry.exporter.otlp.proto.grpc.exporter').setLevel(_logging.CRITICAL)

            # ── Sentry event filter ──────────────────────────────────────────
            # Drop events that are operational noise rather than real bugs.
            _INVALID_SESSION_RE = _re.compile(r'Invalid session \S+')

            def _before_send(event, hint):
                # 1. Suppress OTEL exporter noise
                if event.get('logger', '').startswith('opentelemetry'):
                    return None

                # 2. Suppress Socket.IO "Invalid session <SID>" errors.
                #    These fire on every server restart / deploy when stale
                #    client sessions reconnect. Each unique SID creates a new
                #    Sentry issue, flooding the dashboard with noise. Not a bug.
                msg = event.get('message', '') or event.get('logentry', {}).get('message', '')
                if _INVALID_SESSION_RE.search(msg):
                    return None

                # 3. Suppress "localhost is not an accepted origin" errors.
                #    Dev-only noise from Vite dev server connecting to backend.
                if 'is not an accepted origin' in msg:
                    return None

                # 4. Suppress "Session is disconnected" KeyError.
                #    Happens when Socket.IO session drops mid-request (deploy,
                #    network blip). Transient and self-healing on reconnect.
                exc_values = event.get('exception', {}).get('values', [])
                for exc in exc_values:
                    exc_val = exc.get('value', '')
                    if 'Session is disconnected' in exc_val:
                        return None

                return event

            sentry_sdk.init(
                dsn=_sentry_dsn,
                environment=ENV,
                release=VERSION,
                send_default_pii=True,
                # Tracing: capture 100% of requests so every agent interaction
                # is traceable. Lower to 0.2 if volume becomes expensive.
                traces_sample_rate=1.0,
                # Continuous profiling tied to active spans
                profile_session_sample_rate=1.0,
                profile_lifecycle='trace',
                # Structured logs forwarded to Sentry
                enable_logs=True,
                # Suppress OTEL exporter connection errors from becoming Sentry issues
                ignore_errors=[
                    'opentelemetry.exporter.otlp.proto.grpc.exporter',
                ],
                integrations=[
                    StarletteIntegration(transaction_style='url'),
                    FastApiIntegration(transaction_style='url'),
                    # Instrument aiohttp client calls to the agent container
                    # so Sentry traces include the platform→agent HTTP spans.
                    AioHttpIntegration(),
                    # Bridge Python stdlib logging → Sentry; capture WARNING+ as
                    # breadcrumbs and ERROR+ as Sentry issues.
                    LoggingIntegration(
                        level=_logging.WARNING,
                        event_level=_logging.ERROR,
                    ),
                ],
                before_send=_before_send,
            )
            log.info('Sentry error tracking, tracing and logging enabled')
        except Exception as e:
            log.warning(f'Sentry init failed: {e}')
    # ────────────────────────────────────────────────────────────────────────────

    if os.environ.get('LANGFUSE_SECRET_KEY'):
        try:
            from langfuse import Langfuse

            _langfuse = Langfuse()
            log.info('Langfuse tracing enabled')
        except Exception as e:
            log.warning(f'Langfuse init failed: {e}')

    # Mark application as ready to accept traffic from a startup perspective.
    app.state.startup_complete = True

    yield

    # Cron outbox worker — graceful shutdown.
    if hasattr(app.state, 'cron_outbox_worker'):
        app.state.cron_outbox_worker.stop()
        try:
            await asyncio.wait_for(app.state.cron_outbox_worker_task, timeout=5.0)
        except (TimeoutError, asyncio.CancelledError):
            app.state.cron_outbox_worker_task.cancel()

    if os.environ.get('LANGFUSE_SECRET_KEY'):
        try:
            from langfuse import get_client

            get_client().flush()
        except Exception:
            pass

    if hasattr(app.state, 'redis_task_command_listener'):
        app.state.redis_task_command_listener.cancel()


app = FastAPI(
    title='Myah',
    docs_url='/docs' if ENV == 'dev' else None,
    openapi_url='/openapi.json' if ENV == 'dev' else None,
    redoc_url=None,
    lifespan=lifespan,
)

# Used by readiness checks to gate traffic until startup work is done.
app.state.startup_complete = False

# For Myah OIDC/OAuth2
oauth_manager = OAuthManager(app)
app.state.oauth_manager = oauth_manager

# For Integrations
oauth_client_manager = OAuthClientManager(app)
app.state.oauth_client_manager = oauth_client_manager

app.state.instance_id = None
app.state.config = AppConfig(
    redis_url=REDIS_URL,
    redis_sentinels=get_sentinels_from_env(REDIS_SENTINEL_HOSTS, REDIS_SENTINEL_PORT),
    redis_cluster=REDIS_CLUSTER,
    redis_key_prefix=REDIS_KEY_PREFIX,
)
app.state.redis = None

app.state.WEBUI_NAME = WEBUI_NAME
app.state.LICENSE_METADATA = None


########################################
#
# OPENTELEMETRY
#
########################################

if ENABLE_OTEL:
    from myah.utils.telemetry.setup import setup as setup_opentelemetry

    setup_opentelemetry(app=app, db_engine=engine)


########################################
#
# OPENAI
#
########################################

app.state.config.ENABLE_OPENAI_API = ENABLE_OPENAI_API
app.state.config.OPENAI_API_BASE_URLS = OPENAI_API_BASE_URLS
app.state.config.OPENAI_API_KEYS = OPENAI_API_KEYS
app.state.config.OPENAI_API_CONFIGS = OPENAI_API_CONFIGS

app.state.OPENAI_MODELS = {}

########################################
#
# TOOL SERVERS
#
########################################

app.state.config.TOOL_SERVER_CONNECTIONS = TOOL_SERVER_CONNECTIONS
app.state.TOOL_SERVERS = []

########################################
#
# DIRECT CONNECTIONS
#
########################################

app.state.config.ENABLE_DIRECT_CONNECTIONS = ENABLE_DIRECT_CONNECTIONS


########################################
#
# MODELS
#
########################################

app.state.config.ENABLE_BASE_MODELS_CACHE = ENABLE_BASE_MODELS_CACHE
app.state.BASE_MODELS = []

########################################
#
# WEBUI
#
########################################

app.state.config.WEBUI_URL = WEBUI_URL
app.state.config.ENABLE_SIGNUP = ENABLE_SIGNUP
app.state.config.ENABLE_LOGIN_FORM = ENABLE_LOGIN_FORM

app.state.config.ENABLE_API_KEYS = ENABLE_API_KEYS
app.state.config.ENABLE_API_KEYS_ENDPOINT_RESTRICTIONS = ENABLE_API_KEYS_ENDPOINT_RESTRICTIONS
app.state.config.API_KEYS_ALLOWED_ENDPOINTS = API_KEYS_ALLOWED_ENDPOINTS

app.state.config.JWT_EXPIRES_IN = JWT_EXPIRES_IN

app.state.config.SHOW_ADMIN_DETAILS = SHOW_ADMIN_DETAILS
app.state.config.ADMIN_EMAIL = ADMIN_EMAIL


app.state.config.DEFAULT_MODELS = DEFAULT_MODELS
app.state.config.DEFAULT_PINNED_MODELS = DEFAULT_PINNED_MODELS
app.state.config.MODEL_ORDER_LIST = MODEL_ORDER_LIST
app.state.config.DEFAULT_MODEL_METADATA = DEFAULT_MODEL_METADATA
app.state.config.DEFAULT_MODEL_PARAMS = DEFAULT_MODEL_PARAMS


app.state.config.DEFAULT_PROMPT_SUGGESTIONS = DEFAULT_PROMPT_SUGGESTIONS
app.state.config.DEFAULT_USER_ROLE = DEFAULT_USER_ROLE
app.state.config.DEFAULT_GROUP_ID = DEFAULT_GROUP_ID

app.state.config.PENDING_USER_OVERLAY_CONTENT = PENDING_USER_OVERLAY_CONTENT
app.state.config.PENDING_USER_OVERLAY_TITLE = PENDING_USER_OVERLAY_TITLE

app.state.config.RESPONSE_WATERMARK = RESPONSE_WATERMARK

app.state.config.USER_PERMISSIONS = USER_PERMISSIONS
app.state.config.WEBHOOK_URL = WEBHOOK_URL
app.state.config.BANNERS = WEBUI_BANNERS


app.state.config.ENABLE_FOLDERS = ENABLE_FOLDERS
app.state.config.FOLDER_MAX_FILE_COUNT = FOLDER_MAX_FILE_COUNT
app.state.config.ENABLE_NOTES = ENABLE_NOTES
app.state.config.ENABLE_USER_WEBHOOKS = ENABLE_USER_WEBHOOKS

# Migrate legacy access_control → access_grants on boot
from myah.utils.access_control import migrate_access_control

connections = app.state.config.TOOL_SERVER_CONNECTIONS
if any('access_control' in c.get('config', {}) for c in connections):
    for connection in connections:
        migrate_access_control(connection.get('config', {}))
    app.state.config.TOOL_SERVER_CONNECTIONS = connections

app.state.config.OAUTH_SUB_CLAIM = OAUTH_SUB_CLAIM
app.state.config.OAUTH_USERNAME_CLAIM = OAUTH_USERNAME_CLAIM
app.state.config.OAUTH_PICTURE_CLAIM = OAUTH_PICTURE_CLAIM
app.state.config.OAUTH_EMAIL_CLAIM = OAUTH_EMAIL_CLAIM

app.state.config.ENABLE_OAUTH_ROLE_MANAGEMENT = ENABLE_OAUTH_ROLE_MANAGEMENT
app.state.config.OAUTH_ROLES_CLAIM = OAUTH_ROLES_CLAIM
app.state.config.OAUTH_ALLOWED_ROLES = OAUTH_ALLOWED_ROLES
app.state.config.OAUTH_ADMIN_ROLES = OAUTH_ADMIN_ROLES

app.state.AUTH_TRUSTED_EMAIL_HEADER = WEBUI_AUTH_TRUSTED_EMAIL_HEADER
app.state.AUTH_TRUSTED_NAME_HEADER = WEBUI_AUTH_TRUSTED_NAME_HEADER
app.state.WEBUI_AUTH_SIGNOUT_REDIRECT_URL = WEBUI_AUTH_SIGNOUT_REDIRECT_URL

app.state.USER_COUNT = None

app.state.TOOLS = {}
app.state.TOOL_CONTENTS = {}


########################################
#
# TASKS
#
########################################


app.state.config.TASK_MODEL = TASK_MODEL
app.state.config.TASK_MODEL_EXTERNAL = TASK_MODEL_EXTERNAL


app.state.config.ENABLE_SEARCH_QUERY_GENERATION = ENABLE_SEARCH_QUERY_GENERATION
app.state.config.ENABLE_AUTOCOMPLETE_GENERATION = ENABLE_AUTOCOMPLETE_GENERATION
app.state.config.ENABLE_TAGS_GENERATION = ENABLE_TAGS_GENERATION
app.state.config.ENABLE_TITLE_GENERATION = ENABLE_TITLE_GENERATION
app.state.config.ENABLE_FOLLOW_UP_GENERATION = ENABLE_FOLLOW_UP_GENERATION

app.state.config.TITLE_GENERATION_PROMPT_TEMPLATE = TITLE_GENERATION_PROMPT_TEMPLATE
app.state.config.FOLLOW_UP_GENERATION_PROMPT_TEMPLATE = FOLLOW_UP_GENERATION_PROMPT_TEMPLATE
app.state.config.AUTOCOMPLETE_GENERATION_INPUT_MAX_LENGTH = AUTOCOMPLETE_GENERATION_INPUT_MAX_LENGTH


########################################
#
# WEBUI
#
########################################

app.state.MODELS = MODELS

# Add the middleware to the app
if ENABLE_COMPRESSION_MIDDLEWARE:
    app.add_middleware(CompressMiddleware)


class RedirectMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Check if the request is a GET request
        if request.method == 'GET':
            path = request.url.path
            query_params = dict(parse_qs(urlparse(str(request.url)).query))

            redirect_params = {}

            # Check for the specific watch path and the presence of 'v' parameter
            if path.endswith('/watch') and 'v' in query_params:
                # Extract the first 'v' parameter
                youtube_video_id = query_params['v'][0]
                redirect_params['youtube'] = youtube_video_id

            if 'shared' in query_params and len(query_params['shared']) > 0:
                # PWA share_target support

                text = query_params['shared'][0]
                if text:
                    urls = re.match(r'https://\S+', text)
                    if urls:
                        redirect_params['load-url'] = urls[0]
                    else:
                        redirect_params['q'] = text

            if redirect_params:
                redirect_url = f'/?{urlencode(redirect_params)}'
                return RedirectResponse(url=redirect_url)

        # Proceed with the normal flow of other requests
        response = await call_next(request)
        return response


app.add_middleware(RedirectMiddleware)
app.add_middleware(SecurityHeadersMiddleware)


class APIKeyRestrictionMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'http':
            request = Request(scope)
            auth_header = request.headers.get('Authorization')
            token = None

            if auth_header:
                parts = auth_header.split(' ', 1)
                if len(parts) == 2:
                    token = parts[1]

            # Only apply restrictions if an sk- API key is used
            if token and token.startswith('sk-'):
                # Check if restrictions are enabled
                if app.state.config.ENABLE_API_KEYS_ENDPOINT_RESTRICTIONS:
                    allowed_paths = [
                        path.strip()
                        for path in str(app.state.config.API_KEYS_ALLOWED_ENDPOINTS).split(',')
                        if path.strip()
                    ]

                    request_path = request.url.path

                    # Match exact path or prefix path
                    is_allowed = any(
                        request_path == allowed or request_path.startswith(allowed + '/') for allowed in allowed_paths
                    )

                    if not is_allowed:
                        await JSONResponse(
                            status_code=status.HTTP_403_FORBIDDEN,
                            content={'detail': 'API key not allowed to access this endpoint.'},
                        )(scope, receive, send)
                        return

        await self.app(scope, receive, send)


app.add_middleware(APIKeyRestrictionMiddleware)


@app.middleware('http')
async def commit_session_after_request(request: Request, call_next):
    response = await call_next(request)
    # log.debug("Commit session after request")
    try:
        ScopedSession.commit()
    finally:
        # CRITICAL: remove() returns the connection to the pool.
        # Without this, connections remain "checked out" and accumulate
        # as "idle in transaction" in PostgreSQL.
        ScopedSession.remove()
    return response


@app.middleware('http')
async def check_url(request: Request, call_next):
    start_time = int(time.time())
    request.state.token = get_http_authorization_cred(request.headers.get('Authorization'))
    # Fallback to cookie token for browser sessions
    if request.state.token is None and request.cookies.get('token'):
        from fastapi.security import HTTPAuthorizationCredentials

        request.state.token = HTTPAuthorizationCredentials(scheme='Bearer', credentials=request.cookies.get('token'))

    # Fallback to x-api-key header for Anthropic Messages API routes
    if request.state.token is None and request.headers.get('x-api-key'):
        request_path = request.url.path
        if request_path in ('/api/message', '/api/v1/messages') or request_path.startswith('/ollama/v1/messages'):
            from fastapi.security import HTTPAuthorizationCredentials

            request.state.token = HTTPAuthorizationCredentials(
                scheme='Bearer', credentials=request.headers.get('x-api-key')
            )

    request.state.enable_api_keys = app.state.config.ENABLE_API_KEYS
    response = await call_next(request)
    process_time = int(time.time()) - start_time
    response.headers['X-Process-Time'] = str(process_time)
    return response


@app.middleware('http')
async def inspect_websocket(request: Request, call_next):
    if '/ws/socket.io' in request.url.path and request.query_params.get('transport') == 'websocket':
        upgrade = (request.headers.get('Upgrade') or '').lower()
        connection = (request.headers.get('Connection') or '').lower().split(',')
        # Check that there's the correct headers for an upgrade, else reject the connection
        # This is to work around this upstream issue: https://github.com/miguelgrinberg/python-engineio/issues/367
        if upgrade != 'websocket' or 'upgrade' not in connection:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={'detail': 'Invalid WebSocket upgrade request'},
            )
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOW_ORIGIN,
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)


app.mount('/ws', socket_app)


app.include_router(openai.router, prefix='/openai', tags=['openai'])

app.include_router(tasks.router, prefix='/api/v1/tasks', tags=['tasks'])
app.include_router(configs.router, prefix='/api/v1/configs', tags=['configs'])
app.include_router(auths.router, prefix='/api/v1/auths', tags=['auths'])
app.include_router(users.router, prefix='/api/v1/users', tags=['users'])
app.include_router(chats.router, prefix='/api/v1/chats', tags=['chats'])
app.include_router(notes.router, prefix='/api/v1/notes', tags=['notes'])

app.include_router(folders.router, prefix='/api/v1/folders', tags=['folders'])
app.include_router(files.router, prefix='/api/v1/files', tags=['files'])
app.include_router(utils.router, prefix='/api/v1/utils', tags=['utils'])
app.include_router(containers.router, prefix='/api/v1/containers', tags=['containers'])
app.include_router(processes.router, prefix='/api/v1/processes', tags=['processes'])
app.include_router(agent_capabilities.router, prefix='/api/v1/agent', tags=['agent'])
app.include_router(agent_sessions.router, prefix='/api/v1/agent', tags=['agent-sessions'])

# OSS-split: agent_memory router is hosted-only. See _is_oss_mode check at the
# top of this file — agent_memory is only imported in the hosted build.
if not _is_oss_mode():
    app.include_router(agent_memory.router, prefix='/api/v1/agent/memory', tags=['agent-memory'])
    app.include_router(admin_cron_deliveries.router)

app.include_router(hermes_media.router, prefix='/api/v1/hermes/media', tags=['hermes_media'])
app.include_router(myah_router_module.router, prefix='/api/v1/myah', tags=['myah'])

# ── Myah: agent settings UI ────────────────────────────────────────────
app.include_router(
    agent_config_router.router,
    prefix='/api/v1/agent',
    tags=['agent_config'],
)
# ────────────────────────────────────────────────────────────────────────

# ── Myah: Hermes-native provider catalog + credential management ────────
app.include_router(providers_router_module.router, prefix='/api/v1/providers', tags=['providers'])
# ────────────────────────────────────────────────────────────────────────

# ── Myah: OSS first-run UX endpoints (probe + first_run_complete) ───────
# Mounted in both OSS and hosted builds. In hosted mode the probe still
# works against the host-side hermes (e.g. when a user is poking at the
# diagnostics page), but the Welcome screen never renders because the
# hosted frontend gates on PUBLIC_DEPLOYMENT_MODE !== 'hosted'.
# The router prefixes itself with /api/v1/oss/ so no extra path needed.
app.include_router(oss_router_module.router)
# ────────────────────────────────────────────────────────────────────────

# ── Myah: Integrations router (hosted-only) ────────────────────────────
# OSS-split: integrations is composio-coupled and only loaded in hosted mode.
if not _is_oss_mode():
    app.include_router(integrations.router, prefix='/api/v1/integrations', tags=['integrations'])
# ────────────────────────────────────────────────────────────────────────


try:
    audit_level = AuditLevel(AUDIT_LOG_LEVEL)
except ValueError as e:
    logger.error(f'Invalid audit level: {AUDIT_LOG_LEVEL}. Error: {e}')
    audit_level = AuditLevel.NONE

if audit_level != AuditLevel.NONE:
    app.add_middleware(
        AuditLoggingMiddleware,
        audit_level=audit_level,
        excluded_paths=AUDIT_EXCLUDED_PATHS,
        included_paths=AUDIT_INCLUDED_PATHS,
        max_body_size=MAX_BODY_LOG_SIZE,
    )
##################################
#
# Chat Endpoints
#
##################################


@app.get('/api/models')
@app.get('/api/v1/models')  # Experimental: Compatibility with OpenAI API
async def get_models(request: Request, refresh: bool = False, user=Depends(get_verified_user)):
    all_models = await get_all_models(request, refresh=refresh, user=user)

    models = []
    for model in all_models:
        # Remove profile image URL to reduce payload size
        if model.get('info', {}).get('meta', {}).get('profile_image_url'):
            model['info']['meta'].pop('profile_image_url', None)

        try:
            model_tags = [tag.get('name') for tag in model.get('info', {}).get('meta', {}).get('tags', [])]
            tags = [tag.get('name') for tag in model.get('tags', [])]

            tags = list(set(model_tags + tags))
            model['tags'] = [{'name': tag} for tag in tags]
        except Exception as e:
            log.debug(f'Error processing model tags: {e}')
            model['tags'] = []
            pass

        models.append(model)

    model_order_list = request.app.state.config.MODEL_ORDER_LIST
    if model_order_list:
        model_order_dict = {model_id: i for i, model_id in enumerate(model_order_list)}
        # Sort models by order list priority, with fallback for those not in the list
        models.sort(
            key=lambda model: (
                model_order_dict.get(model.get('id', ''), float('inf')),
                (model.get('name', '') or ''),
            )
        )

    models = get_filtered_models(models, user)

    log.debug(
        f'/api/models returned filtered models accessible to the user: {json.dumps([model.get("id") for model in models])}'
    )
    return {'data': models}


@app.get('/api/models/base')
async def get_base_models(request: Request, user=Depends(get_admin_user)):
    models = await get_all_base_models(request, user=user)
    return {'data': models}


@app.get('/api/v1/models/model/profile/image')
def get_model_profile_image(id: str, user=Depends(get_verified_user)):
    model = Models.get_model_by_id(id)

    if model:
        if model.meta.profile_image_url:
            if model.meta.profile_image_url.startswith('http'):
                return Response(
                    status_code=status.HTTP_302_FOUND,
                    headers={'Location': model.meta.profile_image_url},
                )
            elif model.meta.profile_image_url.startswith('data:image'):
                try:
                    header, base64_data = model.meta.profile_image_url.split(',', 1)
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
            elif model.meta.profile_image_url.startswith('/'):
                return RedirectResponse(url=model.meta.profile_image_url)

    return RedirectResponse(url='/static/favicon.png')


@app.post('/api/chat/completions')
@app.post('/api/v1/chat/completions')  # Experimental: Compatibility with OpenAI API
async def chat_completion(
    request: Request,
    form_data: dict,
    user=Depends(get_verified_user),
):
    import time as _t, logging as _l

    _log = _l.getLogger(__name__)
    _t0 = _t.monotonic()
    _model = form_data.get('model', '?')
    _chat_id = form_data.get('metadata', {}).get('chat_id', '?')
    _msg_id = form_data.get('metadata', {}).get('message_id', '?')
    _log.info(
        '[CHAT_PIPELINE] step=endpoint_entry model=%s chat_id=%s message_id=%s',
        _model,
        _chat_id,
        _msg_id,
    )

    if not request.app.state.MODELS:
        await get_all_models(request, user=user)

    model_id = form_data.get('model', None)
    # ── Myah: preserve model_item for downstream handlers ─────────────────────
    # Use .get() instead of .pop() so openai.generate_chat_completion can
    # read model_item['tags'] to forward the provider tag on /myah/v1/message.
    # Without this, Hermes auto-detects and falls back to OpenRouter for
    # OAuth-only providers like openai-codex. Safe because downstream code
    # paths that inspect form_data don't reject extra keys.
    model_item = form_data.get('model_item', {}) or {}
    # ─────────────────────────────────────────────────────────────────────────
    tasks = form_data.pop('background_tasks', None)

    # ── Myah: interactive chat bypasses the MODELS registry entirely ──────────
    # For interactive chat (non-background-task), the Hermes gateway in the
    # user's container owns model resolution. The platform doesn't need to
    # validate that model_id exists in the admin-curated registry — the model
    # can come from any connected provider (openrouter/openai/anthropic/google)
    # and will be resolved server-side by Hermes.
    #
    # Background tasks (title/tags/follow-ups) still use the registry because
    # they route through admin-configured OpenAI connections.
    _form_metadata = form_data.get('metadata') or {}
    _is_myah_interactive = not bool(_form_metadata.get('task'))
    # ─────────────────────────────────────────────────────────────────────────

    metadata = {}
    try:
        model_info = None
        if model_item.get('direct', False):
            model = model_item
            request.state.direct = True
            request.state.model = model
        elif _is_myah_interactive:
            # Synthesize a minimal model dict — Hermes gateway resolves the real
            # provider. Look up model_info if it happens to exist (for system
            # prompts / params set via the admin Models page), but don't require it.
            model_info = Models.get_model_by_id(model_id) if model_id else None
            model = request.app.state.MODELS.get(model_id) or {
                'id': model_id or 'myah',
                'owned_by': 'myah',
                'connection_type': 'myah',
            }
        else:
            if model_id not in request.app.state.MODELS:
                raise Exception('Model not found')

            model = request.app.state.MODELS[model_id]
            model_info = Models.get_model_by_id(model_id)

            # Check if user has access to the model
            if not BYPASS_MODEL_ACCESS_CONTROL and (user.role != 'admin' or not BYPASS_ADMIN_ACCESS_CONTROL):
                try:
                    check_model_access(user, model)
                except Exception as e:
                    raise e

        # Model params: global defaults as base, per-model overrides win
        default_model_params = getattr(request.app.state.config, 'DEFAULT_MODEL_PARAMS', None) or {}
        model_info_params = {
            **default_model_params,
            **(model_info.params.model_dump() if model_info and model_info.params else {}),
        }

        # Check base model existence for custom models
        if model_info and model_info.base_model_id:
            base_model_id = model_info.base_model_id
            if base_model_id not in request.app.state.MODELS:
                if ENABLE_CUSTOM_MODEL_FALLBACK:
                    default_models = (request.app.state.config.DEFAULT_MODELS or '').split(',')

                    fallback_model_id = default_models[0].strip() if default_models[0] else None

                    if fallback_model_id and fallback_model_id in request.app.state.MODELS:
                        # Update model and form_data so routing uses the fallback model's type
                        model = request.app.state.MODELS[fallback_model_id]
                        form_data['model'] = fallback_model_id
                    else:
                        raise Exception('Model not found')
                else:
                    raise Exception('Model not found')

        # Chat Params
        stream_delta_chunk_size = form_data.get('params', {}).get('stream_delta_chunk_size')
        reasoning_tags = form_data.get('params', {}).get('reasoning_tags')

        # Model Params
        if model_info_params.get('stream_response') is not None:
            form_data['stream'] = model_info_params.get('stream_response')

        if model_info_params.get('stream_delta_chunk_size'):
            stream_delta_chunk_size = model_info_params.get('stream_delta_chunk_size')

        if model_info_params.get('reasoning_tags') is not None:
            reasoning_tags = model_info_params.get('reasoning_tags')

        metadata = {
            'user_id': user.id,
            'chat_id': form_data.pop('chat_id', None),
            'message_id': form_data.pop('id', None),
            'parent_message': form_data.pop('parent_message', None),
            'parent_message_id': form_data.pop('parent_id', None),
            'session_id': form_data.pop('session_id', None),
            'filter_ids': form_data.pop('filter_ids', []),
            'tool_ids': form_data.get('tool_ids', None),
            'tool_servers': form_data.pop('tool_servers', None),
            'files': form_data.get('files', None),
            'features': form_data.get('features', {}),
            'variables': form_data.get('variables', {}),
            'model': model,
            'direct': model_item.get('direct', False),
            'params': {
                'stream_delta_chunk_size': stream_delta_chunk_size,
                'reasoning_tags': reasoning_tags,
                'function_calling': (
                    'native'
                    if (
                        form_data.get('params', {}).get('function_calling') == 'native'
                        or model_info_params.get('function_calling') == 'native'
                    )
                    else 'default'
                ),
            },
        }

        # Detect UI action messages from the annotation field on the parent message
        if (
            isinstance(metadata.get('parent_message'), dict)
            and metadata['parent_message'].get('annotation', {}).get('type') == 'ui-action'
        ):
            metadata['is_agui_action'] = True

        if metadata.get('chat_id') and user:
            if not metadata['chat_id'].startswith('local:'):  # temporary chats are not stored
                # Verify chat ownership — lightweight EXISTS check avoids
                # deserializing the full chat JSON blob just to confirm the row exists
                if (
                    not Chats.is_chat_owner(metadata['chat_id'], user.id) and user.role != 'admin'
                ):  # admins can access any chat
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=ERROR_MESSAGES.DEFAULT(),
                    )

                # Insert chat files from parent message if any
                parent_message = metadata.get('parent_message') or {}
                parent_message_files = parent_message.get('files', [])
                if parent_message_files:
                    try:
                        Chats.insert_chat_files(
                            metadata['chat_id'],
                            parent_message.get('id'),
                            [
                                file_item.get('id')
                                for file_item in parent_message_files
                                if file_item.get('type') == 'file'
                            ],
                            user.id,
                        )
                    except Exception as e:
                        log.debug(f'Error inserting chat files: {e}')
                        pass

        request.state.metadata = metadata
        form_data['metadata'] = metadata

    except Exception as e:
        log.debug(f'Error processing chat metadata: {e}')
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    async def process_chat(request, form_data, user, metadata, model):
        try:
            from opentelemetry import trace as _otel_trace

            _tracer = _otel_trace.get_tracer('myah.chat')
            _pc_t0 = time.time()

            with _tracer.start_as_current_span(
                'chat.process_payload',
                attributes={
                    'chat.id': metadata.get('chat_id', ''),
                    'chat.message_id': metadata.get('message_id', ''),
                    'chat.model': form_data.get('model', ''),
                },
            ):
                form_data, metadata, events = await process_chat_payload(request, form_data, user, metadata, model)

            _payload_ms = int((time.time() - _pc_t0) * 1000)

            with _tracer.start_as_current_span(
                'chat.completion_handler',
                attributes={'chat.payload_ms': _payload_ms},
            ):
                response = await chat_completion_handler(request, form_data, user)
            if metadata.get('chat_id') and metadata.get('message_id'):
                try:
                    if not metadata['chat_id'].startswith('local:'):
                        Chats.upsert_message_to_chat_by_id_and_message_id(
                            metadata['chat_id'],
                            metadata['message_id'],
                            {
                                'parentId': metadata.get('parent_message_id', None),
                                'model': model_id,
                            },
                        )
                except Exception:
                    pass

            ctx = build_chat_response_context(request, form_data, user, model, metadata, tasks, events)

            # All chat completions route through the Hermes gateway adapter.
            # Aux tasks (title, follow-up) hit /myah/v1/aux/... via routers/tasks.py
            # and never enter this path. Interactive chats stream through
            # hermes_stream_handler which parses /myah/v1/events and produces
            # OpenWebUI-compatible deltas.
            from myah.utils.hermes_stream_handler import handle_hermes_stream

            if isinstance(response, StreamingResponse):
                return await handle_hermes_stream(response, ctx)

            # Non-streaming responses (rare; mostly tests using TestClient) pass
            # through unchanged — no Hermes-side parsing needed.
            return response
        except asyncio.CancelledError:
            log.info('Chat processing was cancelled')
            try:
                event_emitter = get_event_emitter(metadata)
                await asyncio.shield(
                    event_emitter(
                        {'type': 'chat:tasks:cancel'},
                    )
                )
            except Exception as e:
                pass
            finally:
                raise  # re-raise to ensure proper task cancellation handling
        except Exception as e:
            # T3-932: log as exception (not debug) so provider-routing failures
            # are visible in production. Without this, any bug in the gateway
            # pipeline silently returns 'null' to the client with no trace.
            log.exception(f'Error processing chat payload: {e}')
            if metadata.get('chat_id') and metadata.get('message_id'):
                # Update the chat message with the error
                try:
                    if not metadata['chat_id'].startswith('local:'):
                        Chats.upsert_message_to_chat_by_id_and_message_id(
                            metadata['chat_id'],
                            metadata['message_id'],
                            {
                                'parentId': metadata.get('parent_message_id', None),
                                'error': {'content': str(e)},
                            },
                        )

                    event_emitter = get_event_emitter(metadata)
                    await event_emitter(
                        {
                            'type': 'chat:message:error',
                            'data': {'error': {'content': str(e)}},
                        }
                    )
                    await event_emitter(
                        {'type': 'chat:tasks:cancel'},
                    )

                except Exception:
                    pass
        finally:
            try:
                if mcp_clients := metadata.get('mcp_clients'):
                    for client in reversed(mcp_clients.values()):
                        await client.disconnect()
            except Exception as e:
                log.debug(f'Error cleaning up: {e}')
                pass
            # Emit chat:active=false when task completes
            try:
                if metadata.get('chat_id'):
                    event_emitter = get_event_emitter(metadata, update_db=False)
                    if event_emitter:
                        await event_emitter({'type': 'chat:active', 'data': {'active': False}})
            except Exception as e:
                log.debug(f'Error emitting chat:active: {e}')

    if metadata.get('session_id') and metadata.get('chat_id') and metadata.get('message_id'):
        # Asynchronous Chat Processing
        task_id, _ = await create_task(
            request.app.state.redis,
            process_chat(request, form_data, user, metadata, model),
            id=metadata['chat_id'],
        )
        # Emit chat:active=true when task starts
        event_emitter = get_event_emitter(metadata, update_db=False)
        if event_emitter:
            await event_emitter({'type': 'chat:active', 'data': {'active': True}})
        return {'status': True, 'task_id': task_id}
    else:
        return await process_chat(request, form_data, user, metadata, model)


# Alias for chat_completion (Legacy)
generate_chat_completions = chat_completion
generate_chat_completion = chat_completion


##################################
#
# Anthropic Messages API Compatible Endpoint
#
##################################


from myah.utils.anthropic import (
    convert_anthropic_to_openai_payload,
    convert_openai_to_anthropic_response,
    openai_stream_to_anthropic_stream,
)


@app.post('/api/message')
@app.post('/api/v1/messages')  # Anthropic Messages API compatible endpoint
async def generate_messages(
    request: Request,
    form_data: dict,
    user=Depends(get_verified_user),
):
    """
    Anthropic Messages API compatible endpoint.

    Accepts the Anthropic Messages API format, converts internally to OpenAI
    Chat Completions format, routes through the existing chat completion
    pipeline, then converts the response back to Anthropic Messages format.

    Supports both streaming and non-streaming requests.
    All models configured in Myah are accessible via this endpoint.

    Authentication: Supports both standard Authorization header and
    Anthropic's x-api-key header (via middleware translation).
    """
    # Convert Anthropic payload to OpenAI format
    requested_model = form_data.get('model', '')

    openai_payload = convert_anthropic_to_openai_payload(form_data)

    # Route through the existing chat_completion handler
    response = await chat_completion(request, openai_payload, user)

    # Convert response back to Anthropic format
    if isinstance(response, StreamingResponse):
        # Streaming response: wrap the generator to convert SSE format
        return StreamingResponse(
            openai_stream_to_anthropic_stream(response.body_iterator, model=requested_model),
            media_type='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'Connection': 'keep-alive',
            },
        )
    elif isinstance(response, dict):
        return convert_openai_to_anthropic_response(response, model=requested_model)
    else:
        # Passthrough for error responses (JSONResponse, PlainTextResponse, etc.)
        return response


@app.post('/api/chat/completed')
async def chat_completed(request: Request, form_data: dict, user=Depends(get_verified_user)):
    try:
        model_item = form_data.pop('model_item', {})

        if model_item.get('direct', False):
            request.state.direct = True
            request.state.model = model_item

        return await chat_completed_handler(request, form_data, user)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@app.post('/api/tasks/stop/{task_id}')
async def stop_task_endpoint(request: Request, task_id: str, user=Depends(get_verified_user)):
    try:
        result = await stop_task(request.app.state.redis, task_id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@app.get('/api/tasks')
async def list_tasks_endpoint(request: Request, user=Depends(get_verified_user)):
    return {'tasks': await list_tasks(request.app.state.redis)}


@app.get('/api/tasks/chat/{chat_id}')
async def list_tasks_by_chat_id_endpoint(request: Request, chat_id: str, user=Depends(get_verified_user)):
    chat = Chats.get_chat_by_id(chat_id)
    if chat is None or chat.user_id != user.id:
        return {'task_ids': []}

    task_ids = await list_task_ids_by_item_id(request.app.state.redis, chat_id)

    log.debug(f'Task IDs for chat {chat_id}: {task_ids}')
    return {'task_ids': task_ids}


##################################
#
# Config Endpoints
#
##################################


@app.get('/api/config')
async def get_app_config(request: Request):
    user = None
    token = None

    auth_header = request.headers.get('Authorization')
    if auth_header:
        cred = get_http_authorization_cred(auth_header)
        if cred:
            token = cred.credentials

    if not token and 'token' in request.cookies:
        token = request.cookies.get('token')

    if token:
        try:
            data = decode_token(token)
        except Exception as e:
            log.debug(e)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail='Invalid token',
            )
        if data is not None and 'id' in data:
            user = Users.get_user_by_id(data['id'])

    user_count = Users.get_num_users()
    onboarding = False

    if user is None:
        onboarding = user_count == 0

    return {
        **({'onboarding': True} if onboarding else {}),
        'status': True,
        'name': app.state.WEBUI_NAME,
        'version': VERSION,
        'default_locale': str(DEFAULT_LOCALE),
        'oauth': {'providers': {name: config.get('name', name) for name, config in OAUTH_PROVIDERS.items()}},
        'features': {
            'auth': WEBUI_AUTH,
            'auth_trusted_header': bool(app.state.AUTH_TRUSTED_EMAIL_HEADER),
            'enable_signup_password_confirmation': ENABLE_SIGNUP_PASSWORD_CONFIRMATION,
            'enable_api_keys': app.state.config.ENABLE_API_KEYS,
            'enable_signup': app.state.config.ENABLE_SIGNUP,
            'enable_login_form': app.state.config.ENABLE_LOGIN_FORM,
            'enable_websocket': ENABLE_WEBSOCKET_SUPPORT,
            'enable_version_update_check': ENABLE_VERSION_UPDATE_CHECK,
            'enable_public_active_users_count': ENABLE_PUBLIC_ACTIVE_USERS_COUNT,
            'enable_easter_eggs': ENABLE_EASTER_EGGS,
            **(
                {
                    'enable_direct_connections': app.state.config.ENABLE_DIRECT_CONNECTIONS,
                    'enable_folders': app.state.config.ENABLE_FOLDERS,
                    'folder_max_file_count': app.state.config.FOLDER_MAX_FILE_COUNT,
                    'enable_notes': app.state.config.ENABLE_NOTES,
                    'enable_autocomplete_generation': app.state.config.ENABLE_AUTOCOMPLETE_GENERATION,
                    'enable_community_sharing': False,
                    'enable_message_rating': True,
                    'enable_user_webhooks': app.state.config.ENABLE_USER_WEBHOOKS,
                    'enable_user_status': True,
                    'enable_admin_export': ENABLE_ADMIN_EXPORT,
                    'enable_admin_chat_access': ENABLE_ADMIN_CHAT_ACCESS,
                    'enable_admin_analytics': ENABLE_ADMIN_ANALYTICS,
                }
                if user is not None
                else {}
            ),
        },
        **(
            {
                'default_models': app.state.config.DEFAULT_MODELS,
                'default_pinned_models': app.state.config.DEFAULT_PINNED_MODELS,
                'default_prompt_suggestions': app.state.config.DEFAULT_PROMPT_SUGGESTIONS,
                'user_count': user_count,
                'permissions': {**app.state.config.USER_PERMISSIONS},
                'ui': {
                    'pending_user_overlay_title': app.state.config.PENDING_USER_OVERLAY_TITLE,
                    'pending_user_overlay_content': app.state.config.PENDING_USER_OVERLAY_CONTENT,
                    'response_watermark': app.state.config.RESPONSE_WATERMARK,
                },
                'license_metadata': app.state.LICENSE_METADATA,
                **(
                    {
                        'active_entries': app.state.USER_COUNT,
                    }
                    if user.role == 'admin'
                    else {}
                ),
            }
            if user is not None and (user.role in ['admin', 'user'])
            else {
                **(
                    {
                        'ui': {
                            'pending_user_overlay_title': app.state.config.PENDING_USER_OVERLAY_TITLE,
                            'pending_user_overlay_content': app.state.config.PENDING_USER_OVERLAY_CONTENT,
                        }
                    }
                    if user and user.role == 'pending'
                    else {}
                ),
                **(
                    {
                        'metadata': {
                            'login_footer': app.state.LICENSE_METADATA.get('login_footer', ''),
                            'auth_logo_position': app.state.LICENSE_METADATA.get('auth_logo_position', ''),
                        }
                    }
                    if app.state.LICENSE_METADATA
                    else {}
                ),
            }
        ),
    }


class UrlForm(BaseModel):
    url: str


@app.get('/api/webhook')
async def get_webhook_url(user=Depends(get_admin_user)):
    return {
        'url': app.state.config.WEBHOOK_URL,
    }


@app.post('/api/webhook')
async def update_webhook_url(form_data: UrlForm, user=Depends(get_admin_user)):
    app.state.config.WEBHOOK_URL = form_data.url
    app.state.WEBHOOK_URL = app.state.config.WEBHOOK_URL
    return {'url': app.state.config.WEBHOOK_URL}


@app.get('/api/version')
async def get_app_version():
    return {
        'version': VERSION,
        'deployment_id': DEPLOYMENT_ID,
    }


@app.get('/api/changelog')
async def get_app_changelog():
    return {key: CHANGELOG[key] for idx, key in enumerate(CHANGELOG) if idx < 5}


@app.get('/api/usage')
async def get_current_usage(user=Depends(get_verified_user)):
    """
    Get current usage statistics for Myah.
    This is an experimental endpoint and subject to change.
    """
    try:
        # If public visibility is disabled, only allow admins to access this endpoint
        if not ENABLE_PUBLIC_ACTIVE_USERS_COUNT and user.role != 'admin':
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail='Access denied. Only administrators can view usage statistics.',
            )

        return {
            'model_ids': get_models_in_use(),
            'user_count': Users.get_active_user_count(),
        }
    except HTTPException:
        raise
    except Exception as e:
        log.error(f'Error getting usage statistics: {e}')
        raise HTTPException(status_code=500, detail='Internal Server Error')


############################
# OAuth Login & Callback
############################


# Initialize OAuth client manager with any MCP tool servers using OAuth 2.1
if len(app.state.config.TOOL_SERVER_CONNECTIONS) > 0:
    for tool_server_connection in app.state.config.TOOL_SERVER_CONNECTIONS:
        if tool_server_connection.get('type', 'openapi') == 'mcp':
            server_id = tool_server_connection.get('info', {}).get('id')
            auth_type = tool_server_connection.get('auth_type', 'none')

            if server_id and auth_type in ('oauth_2.1', 'oauth_2.1_static'):
                oauth_client_info = tool_server_connection.get('info', {}).get('oauth_client_info', '')

                try:
                    oauth_client_info = decrypt_data(oauth_client_info)
                    app.state.oauth_client_manager.add_client(
                        f'mcp:{server_id}',
                        OAuthClientInformationFull(**oauth_client_info),
                    )
                except Exception as e:
                    log.error(f'Error adding OAuth client for MCP tool server {server_id}: {e}')
                    pass

try:
    if ENABLE_STAR_SESSIONS_MIDDLEWARE:
        redis_session_store = RedisStore(
            url=REDIS_URL,
            prefix=(f'{REDIS_KEY_PREFIX}:session:' if REDIS_KEY_PREFIX else 'session:'),
        )

        app.add_middleware(SessionAutoloadMiddleware)
        app.add_middleware(
            StarSessionsMiddleware,
            store=redis_session_store,
            cookie_name='owui-session',
            cookie_same_site=WEBUI_SESSION_COOKIE_SAME_SITE,
            cookie_https_only=WEBUI_SESSION_COOKIE_SECURE,
        )
        log.info('Using Redis for session')
    else:
        raise ValueError('No Redis URL provided')
except Exception as e:
    app.add_middleware(
        SessionMiddleware,
        secret_key=WEBUI_SECRET_KEY,
        session_cookie='owui-session',
        same_site=WEBUI_SESSION_COOKIE_SAME_SITE,
        https_only=WEBUI_SESSION_COOKIE_SECURE,
    )


async def register_client(request, client_id: str) -> bool:
    server_type, server_id = client_id.split(':', 1)

    connection = None
    connection_idx = None

    for idx, conn in enumerate(request.app.state.config.TOOL_SERVER_CONNECTIONS or []):
        if conn.get('type', 'openapi') == server_type:
            info = conn.get('info', {})
            if info.get('id') == server_id:
                connection = conn
                connection_idx = idx
                break

    if connection is None or connection_idx is None:
        log.warning(f'Unable to locate MCP tool server configuration for client {client_id} during re-registration')
        return False

    server_url = connection.get('url')
    auth_type = connection.get('auth_type', 'none')
    oauth_server_key = (connection.get('config') or {}).get('oauth_server_key')

    try:
        if auth_type == 'oauth_2.1_static':
            # Static credentials: rebuild from stored credentials + fresh metadata
            existing_client_info = connection.get('info', {}).get('oauth_client_info', '')
            if not existing_client_info:
                log.error(f'No stored OAuth client info for static client {client_id}')
                return False
            existing_data = decrypt_data(existing_client_info)
            oauth_client_info = await get_oauth_client_info_with_static_credentials(
                request,
                client_id,
                server_url,
                oauth_client_id=existing_data.get('client_id', ''),
                oauth_client_secret=existing_data.get('client_secret', ''),
            )
        else:
            oauth_client_info = await get_oauth_client_info_with_dynamic_client_registration(
                request,
                client_id,
                server_url,
                oauth_server_key,
            )
    except Exception as e:
        log.error(f'OAuth client re-registration failed for {client_id}: {e}')
        return False

    try:
        connections = request.app.state.config.TOOL_SERVER_CONNECTIONS
        connections[connection_idx] = {
            **connection,
            'info': {
                **connection.get('info', {}),
                'oauth_client_info': encrypt_data(oauth_client_info.model_dump(mode='json')),
            },
        }
        # Re-assign the full list to trigger AppConfig.__setattr__ → PersistentConfig.save()
        # (in-place list mutation via list[idx] = ... does not trigger __setattr__)
        request.app.state.config.TOOL_SERVER_CONNECTIONS = connections
    except Exception as e:
        log.error(f'Failed to persist updated OAuth client info for tool server {client_id}: {e}')
        return False

    oauth_client_manager.remove_client(client_id)
    oauth_client_manager.add_client(client_id, oauth_client_info)
    log.info(f'Re-registered OAuth client {client_id} for tool server')
    return True


@app.get('/oauth/clients/{client_id}/authorize')
async def oauth_client_authorize(
    client_id: str,
    request: Request,
    response: Response,
    user=Depends(get_verified_user),
):
    # ensure_valid_client_registration
    client = oauth_client_manager.get_client(client_id)
    client_info = oauth_client_manager.get_client_info(client_id)
    if client is None or client_info is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)

    if not await oauth_client_manager._preflight_authorization_url(client, client_info):
        log.info(
            'Detected invalid OAuth client %s; attempting re-registration',
            client_id,
        )

        registered = await register_client(request, client_id)
        if not registered:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail='Failed to re-register OAuth client',
            )

        client = oauth_client_manager.get_client(client_id)
        client_info = oauth_client_manager.get_client_info(client_id)
        if client is None or client_info is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail='OAuth client unavailable after re-registration',
            )

        if not await oauth_client_manager._preflight_authorization_url(client, client_info):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail='OAuth client registration is still invalid after re-registration',
            )

    return await oauth_client_manager.handle_authorize(request, client_id=client_id)


@app.get('/oauth/clients/{client_id}/callback')
async def oauth_client_callback(
    client_id: str,
    request: Request,
    response: Response,
    user=Depends(get_verified_user),
):
    return await oauth_client_manager.handle_callback(
        request,
        client_id=client_id,
        user_id=user.id if user else None,
        response=response,
    )


@app.get('/oauth/{provider}/login')
async def oauth_login(provider: str, request: Request):
    return await oauth_manager.handle_login(request, provider)


# OAuth login logic is as follows:
# 1. Attempt to find a user with matching subject ID, tied to the provider
# 2. If OAUTH_MERGE_ACCOUNTS_BY_EMAIL is true, find a user with the email address provided via OAuth
#    - This is considered insecure in general, as OAuth providers do not always verify email addresses
# 3. If there is no user, and ENABLE_OAUTH_SIGNUP is true, create a user
#    - Email addresses are considered unique, so we fail registration if the email address is already taken
@app.get('/oauth/{provider}/login/callback')
@app.get('/oauth/{provider}/callback')  # Legacy endpoint
async def oauth_login_callback(
    provider: str,
    request: Request,
    response: Response,
    db: Session = Depends(get_session),
):
    return await oauth_manager.handle_callback(request, provider, response, db=db)


@app.get('/manifest.json')
async def get_manifest_json():
    return {
        'name': app.state.WEBUI_NAME,
        'short_name': app.state.WEBUI_NAME,
        'description': f'{app.state.WEBUI_NAME} is an open, extensible, user-friendly interface for AI that adapts to your workflow.',
        'start_url': '/',
        'display': 'standalone',
        'background_color': '#343541',
        'icons': [
            {
                'src': '/static/logo.png',
                'type': 'image/png',
                'sizes': '500x500',
                'purpose': 'any',
            },
            {
                'src': '/static/logo.png',
                'type': 'image/png',
                'sizes': '500x500',
                'purpose': 'maskable',
            },
        ],
        'share_target': {
            'action': '/',
            'method': 'GET',
            'params': {'text': 'shared'},
        },
    }


@app.get('/opensearch.xml')
async def get_opensearch_xml():
    xml_content = rf"""
    <OpenSearchDescription xmlns="http://a9.com/-/spec/opensearch/1.1/" xmlns:moz="http://www.mozilla.org/2006/browser/search/">
    <ShortName>{app.state.WEBUI_NAME}</ShortName>
    <Description>Search {app.state.WEBUI_NAME}</Description>
    <InputEncoding>UTF-8</InputEncoding>
    <Image width="16" height="16" type="image/x-icon">{app.state.config.WEBUI_URL}/static/favicon.png</Image>
    <Url type="text/html" method="get" template="{app.state.config.WEBUI_URL}/?q={'{searchTerms}'}"/>
    <moz:SearchForm>{app.state.config.WEBUI_URL}</moz:SearchForm>
    </OpenSearchDescription>
    """
    return Response(content=xml_content, media_type='application/xml')


@app.get('/health')
async def healthcheck():
    return {'status': True}


@app.get('/ready')
async def readiness_check():
    """
    Returns 200 only when the application is ready to accept traffic.
    """

    # Ensure application startup work has completed
    if not getattr(app.state, 'startup_complete', False):
        log.info('Readiness check failed: startup not complete')
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail='Startup not complete',
        )

    # Check database connectivity
    try:
        ScopedSession.execute(text('SELECT 1;')).all()
    except Exception as e:
        log.warning(f'Readiness check DB ping failed: {e!r}')
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail='Database not ready',
        )

    # Check Redis connectivity if configured
    redis = app.state.redis
    if redis is not None:
        try:
            pong = await redis.ping()
            if pong is False:
                raise Exception('Redis PING returned False')
        except Exception as e:
            log.warning(f'Readiness check Redis ping failed: {e!r}')
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail='Redis not ready',
            )

    return {'status': True}


@app.get('/health/db')
async def healthcheck_with_db():
    ScopedSession.execute(text('SELECT 1;')).all()
    return {'status': True}


app.mount('/static', StaticFiles(directory=STATIC_DIR), name='static')


@app.get('/sitemap.xml', include_in_schema=False)
@app.get('/sitemap_index.xml', include_in_schema=False)
@app.get('/wp-sitemap.xml', include_in_schema=False)
async def no_sitemap() -> None:
    raise HTTPException(status_code=404, detail='Not Found')


@app.get('/cache/{path:path}')
async def serve_cache_file(
    path: str,
    user=Depends(get_verified_user),
):
    file_path = os.path.abspath(os.path.join(CACHE_DIR, path))
    # prevent path traversal
    if not file_path.startswith(os.path.abspath(CACHE_DIR)):
        raise HTTPException(status_code=404, detail='File not found')
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail='File not found')
    return FileResponse(file_path)


# ── API catch-all: reject unregistered /api/* paths before the SPA mount ─────
# Without this guard, any /api/* path with no registered FastAPI route falls
# through to SPAStaticFiles mounted at '/', which serves index.html with
# HTTP 200 (html=True swallows the 404). Hosted-only routers such as
# /api/v1/agent/memory and /api/v1/integrations are absent from platform-oss/
# (anti-SaaS-fork: their router files live in platform-hosted/ only), so
# without this they return 200 text/html — breaking the JSON contract callers
# expect. This catch-all also future-proofs any hosted-only route added later.
@app.api_route(
    '/api/{path:path}',
    methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS', 'HEAD'],
    include_in_schema=False,
)
async def api_not_found(path: str) -> None:
    raise HTTPException(status_code=404, detail='Not Found')


# ────────────────────────────────────────────────────────────────────────────


def swagger_ui_html(*args, **kwargs):
    return get_swagger_ui_html(
        *args,
        **kwargs,
        swagger_js_url='/static/swagger-ui/swagger-ui-bundle.js',
        swagger_css_url='/static/swagger-ui/swagger-ui.css',
        swagger_favicon_url='/static/swagger-ui/favicon.png',
    )


applications.get_swagger_ui_html = swagger_ui_html

if os.path.exists(FRONTEND_BUILD_DIR):
    mimetypes.add_type('text/javascript', '.js')
    app.mount(
        '/',
        SPAStaticFiles(directory=FRONTEND_BUILD_DIR, html=True),
        name='spa-static-files',
    )
else:
    log.warning(f"Frontend build directory not found at '{FRONTEND_BUILD_DIR}'. Serving API only.")
