import importlib.metadata
import json
import logging
import os
import sys
import shutil
import traceback
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4
from pathlib import Path
import re


from myah.constants import ERROR_MESSAGES

####################################
# Back-compat env-var alias shim (Phase 1A Task A.3)
####################################
#
# As part of the open_webui -> myah rename, every WEBUI_* env var name gets a
# MYAH_* primary. Hosted production deploys still inject WEBUI_AUTH,
# WEBUI_SECRET_KEY, etc. via their .env files; this shim ensures those keep
# working without a coordinated rollout.
#
# Precedence: MYAH_* wins when both are set. When only WEBUI_* is set, the
# primary picks up the legacy value AND emits a one-time deprecation log.
# When neither is set, the default is used.
#
# The WEBUI_* module attributes are kept as aliases of the MYAH_* primaries
# so existing code that imports WEBUI_AUTH from myah.env continues to work
# until v0.2.0 (when the legacy attribute names are removed — tracked in
# CHANGELOG.md and docs/roadmap.md).

_deprecated_logged: set[str] = set()


def _env(myah_name: str, legacy_name: str, default: Any = None) -> Any:
    """Look up env var with back-compat fallback.

    Returns the value of the primary MYAH_* env var if set; otherwise falls
    back to the legacy WEBUI_* name (with a once-per-process deprecation log).
    """
    val = os.environ.get(myah_name)
    if val is not None:
        return val
    legacy_val = os.environ.get(legacy_name)
    if legacy_val is not None:
        if legacy_name not in _deprecated_logged:
            # The logger is configured later in this module; we use the
            # std logging module directly here so the warning still fires
            # even when this helper is called before loguru intercepts.
            import logging as _logging

            _logging.getLogger('myah.env').warning(
                f'{legacy_name} env var is deprecated; rename to {myah_name}. '
                f'WEBUI_* aliases are scheduled for removal in v0.2.0.'
            )
            _deprecated_logged.add(legacy_name)
        return legacy_val
    return default


####################################
# Load .env file
####################################

# Use .resolve() to get the canonical path, removing any '..' or '.' components
ENV_FILE_PATH = Path(__file__).resolve()

# MYAH_BACKEND_DIR should be the directory where env.py resides (myah/)
MYAH_BACKEND_DIR = ENV_FILE_PATH.parent

# BACKEND_DIR is the parent of MYAH_BACKEND_DIR (backend/)
BACKEND_DIR = MYAH_BACKEND_DIR.parent

# BASE_DIR is the parent of BACKEND_DIR (open-webui-dev/)
BASE_DIR = BACKEND_DIR.parent

try:
    from dotenv import find_dotenv, load_dotenv

    load_dotenv(find_dotenv(str(BASE_DIR / '.env')))
except ImportError:
    print('dotenv not installed, skipping...')

DOCKER = os.environ.get('DOCKER', 'False').lower() == 'true'

# device type embedding models - "cpu" (default), "cuda" (nvidia gpu required) or "mps" (apple silicon) - choosing this right can lead to better performance
USE_CUDA = os.environ.get('USE_CUDA_DOCKER', 'false')

if USE_CUDA.lower() == 'true':
    try:
        import torch

        assert torch.cuda.is_available(), 'CUDA not available'
        DEVICE_TYPE = 'cuda'
    except Exception as e:
        cuda_error = f'Error when testing CUDA but USE_CUDA_DOCKER is true. Resetting USE_CUDA_DOCKER to false: {e}'
        os.environ['USE_CUDA_DOCKER'] = 'false'
        USE_CUDA = 'false'
        DEVICE_TYPE = 'cpu'
else:
    DEVICE_TYPE = 'cpu'

try:
    import torch

    if torch.backends.mps.is_available() and torch.backends.mps.is_built():
        DEVICE_TYPE = 'mps'
except Exception:
    pass

####################################
# LOGGING
####################################

_LEVEL_MAP = {
    'DEBUG': 'debug',
    'INFO': 'info',
    'WARNING': 'warn',
    'ERROR': 'error',
    'CRITICAL': 'fatal',
}


class JSONFormatter(logging.Formatter):
    """Format log records as single-line JSON objects for structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            'ts': datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(timespec='milliseconds'),
            'level': _LEVEL_MAP.get(record.levelname, record.levelname.lower()),
            'msg': record.getMessage(),
            'caller': record.name,
        }

        if record.exc_info and record.exc_info[0] is not None:
            log_entry['error'] = ''.join(traceback.format_exception(*record.exc_info)).rstrip()
        elif record.exc_text:
            log_entry['error'] = record.exc_text

        if record.stack_info:
            log_entry['stacktrace'] = record.stack_info

        return json.dumps(log_entry, ensure_ascii=False, default=str)


LOG_FORMAT = os.environ.get('LOG_FORMAT', '').lower()

GLOBAL_LOG_LEVEL = os.environ.get('GLOBAL_LOG_LEVEL', '').upper()
if GLOBAL_LOG_LEVEL in logging.getLevelNamesMapping():
    if LOG_FORMAT == 'json':
        _handler = logging.StreamHandler(sys.stdout)
        _handler.setFormatter(JSONFormatter())
        logging.basicConfig(handlers=[_handler], level=GLOBAL_LOG_LEVEL, force=True)
    else:
        logging.basicConfig(stream=sys.stdout, level=GLOBAL_LOG_LEVEL, force=True)
else:
    GLOBAL_LOG_LEVEL = 'INFO'

log = logging.getLogger(__name__)
log.info(f'GLOBAL_LOG_LEVEL: {GLOBAL_LOG_LEVEL}')

if 'cuda_error' in locals():
    log.exception(cuda_error)
    del cuda_error

SRC_LOG_LEVELS = {}  # Legacy variable, do not remove

MYAH_NAME = _env('MYAH_NAME', 'WEBUI_NAME', 'Myah')
if MYAH_NAME != 'Myah':
    MYAH_NAME += ' (Myah)'
WEBUI_NAME = MYAH_NAME  # legacy alias

MYAH_FAVICON_URL = _env('MYAH_FAVICON_URL', 'WEBUI_FAVICON_URL', '')
WEBUI_FAVICON_URL = MYAH_FAVICON_URL  # legacy alias

MYAH_URL = _env('MYAH_URL', 'WEBUI_URL', '')
WEBUI_URL = MYAH_URL  # legacy alias

MYAH_BANNERS = _env('MYAH_BANNERS', 'WEBUI_BANNERS', '[]')
WEBUI_BANNERS = MYAH_BANNERS  # legacy alias

TRUSTED_SIGNATURE_KEY = os.environ.get('TRUSTED_SIGNATURE_KEY', '')

####################################
# ENV (dev,test,prod)
####################################

ENV = os.environ.get('ENV', 'dev')

FROM_INIT_PY = os.environ.get('FROM_INIT_PY', 'False').lower() == 'true'

if FROM_INIT_PY:
    PACKAGE_DATA = {'version': importlib.metadata.version('open-webui')}
else:
    try:
        PACKAGE_DATA = json.loads((BASE_DIR / 'package.json').read_text())
    except Exception:
        PACKAGE_DATA = {'version': '0.0.0'}

VERSION = PACKAGE_DATA['version']


DEPLOYMENT_ID = os.environ.get('DEPLOYMENT_ID', '')
INSTANCE_ID = os.environ.get('INSTANCE_ID', str(uuid4()))

ENABLE_DB_MIGRATIONS = os.environ.get('ENABLE_DB_MIGRATIONS', 'True').lower() == 'true'


# Myah fork: upstream CHANGELOG.md was removed as it documented Open WebUI
# releases, not our fork. The /api/changelog endpoint stays wired but returns
# an empty dict — drops a bs4 + markdown transitive dep along the way.
CHANGELOG: dict[str, Any] = {}

####################################
# SAFE_MODE
####################################

SAFE_MODE = os.environ.get('SAFE_MODE', 'false').lower() == 'true'


####################################
# ENABLE_FORWARD_USER_INFO_HEADERS
####################################

ENABLE_FORWARD_USER_INFO_HEADERS = os.environ.get('ENABLE_FORWARD_USER_INFO_HEADERS', 'False').lower() == 'true'

# Header names for user info forwarding (customizable via environment variables)
FORWARD_USER_INFO_HEADER_USER_NAME = os.environ.get('FORWARD_USER_INFO_HEADER_USER_NAME', 'X-OpenWebUI-User-Name')
FORWARD_USER_INFO_HEADER_USER_ID = os.environ.get('FORWARD_USER_INFO_HEADER_USER_ID', 'X-OpenWebUI-User-Id')
FORWARD_USER_INFO_HEADER_USER_EMAIL = os.environ.get('FORWARD_USER_INFO_HEADER_USER_EMAIL', 'X-OpenWebUI-User-Email')
FORWARD_USER_INFO_HEADER_USER_ROLE = os.environ.get('FORWARD_USER_INFO_HEADER_USER_ROLE', 'X-OpenWebUI-User-Role')

# Header name for chat ID forwarding (customizable via environment variable)
FORWARD_SESSION_INFO_HEADER_MESSAGE_ID = os.environ.get(
    'FORWARD_SESSION_INFO_HEADER_MESSAGE_ID', 'X-OpenWebUI-Message-Id'
)
FORWARD_SESSION_INFO_HEADER_CHAT_ID = os.environ.get('FORWARD_SESSION_INFO_HEADER_CHAT_ID', 'X-OpenWebUI-Chat-Id')

# Experimental feature, may be removed in future
ENABLE_STAR_SESSIONS_MIDDLEWARE = os.environ.get('ENABLE_STAR_SESSIONS_MIDDLEWARE', 'False').lower() == 'true'

ENABLE_EASTER_EGGS = os.environ.get('ENABLE_EASTER_EGGS', 'True').lower() == 'true'

####################################
# WEBUI_BUILD_HASH
####################################

MYAH_BUILD_HASH = _env('MYAH_BUILD_HASH', 'WEBUI_BUILD_HASH', 'dev-build')
WEBUI_BUILD_HASH = MYAH_BUILD_HASH  # legacy alias

####################################
# DATA/FRONTEND BUILD DIR
####################################

DATA_DIR = Path(os.getenv('DATA_DIR', BACKEND_DIR / 'data')).resolve()

if FROM_INIT_PY:
    NEW_DATA_DIR = Path(os.getenv('DATA_DIR', MYAH_BACKEND_DIR / 'data')).resolve()
    NEW_DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Check if the data directory exists in the package directory
    if DATA_DIR.exists() and DATA_DIR != NEW_DATA_DIR:
        log.info(f'Moving {DATA_DIR} to {NEW_DATA_DIR}')
        for item in DATA_DIR.iterdir():
            dest = NEW_DATA_DIR / item.name
            if item.is_dir():
                shutil.copytree(item, dest, dirs_exist_ok=True)
            else:
                shutil.copy2(item, dest)

        # Zip the data directory
        shutil.make_archive(DATA_DIR.parent / 'open_webui_data', 'zip', DATA_DIR)

        # Remove the old data directory
        shutil.rmtree(DATA_DIR)

    DATA_DIR = Path(os.getenv('DATA_DIR', MYAH_BACKEND_DIR / 'data'))

STATIC_DIR = Path(os.getenv('STATIC_DIR', MYAH_BACKEND_DIR / 'static'))

FONTS_DIR = Path(os.getenv('FONTS_DIR', MYAH_BACKEND_DIR / 'static' / 'fonts'))

FRONTEND_BUILD_DIR = Path(os.getenv('FRONTEND_BUILD_DIR', BASE_DIR / 'build')).resolve()

if FROM_INIT_PY:
    FRONTEND_BUILD_DIR = Path(os.getenv('FRONTEND_BUILD_DIR', MYAH_BACKEND_DIR / 'frontend')).resolve()

####################################
# Database
####################################

# Check if the file exists
if os.path.exists(f'{DATA_DIR}/ollama.db'):
    # Rename the file
    os.rename(f'{DATA_DIR}/ollama.db', f'{DATA_DIR}/webui.db')
    log.info('Database migrated from Ollama-WebUI successfully.')
else:
    pass

DATABASE_URL = os.environ.get('DATABASE_URL', f'sqlite:///{DATA_DIR}/myah.db')

DATABASE_TYPE = os.environ.get('DATABASE_TYPE')
DATABASE_USER = os.environ.get('DATABASE_USER')
DATABASE_PASSWORD = os.environ.get('DATABASE_PASSWORD')

DATABASE_CRED = ''
if DATABASE_USER:
    DATABASE_CRED += f'{DATABASE_USER}'
if DATABASE_PASSWORD:
    DATABASE_CRED += f':{DATABASE_PASSWORD}'

DB_VARS = {
    'db_type': DATABASE_TYPE,
    'db_cred': DATABASE_CRED,
    'db_host': os.environ.get('DATABASE_HOST'),
    'db_port': os.environ.get('DATABASE_PORT'),
    'db_name': os.environ.get('DATABASE_NAME'),
}

if all(DB_VARS.values()):
    DATABASE_URL = (
        f'{DB_VARS["db_type"]}://{DB_VARS["db_cred"]}@{DB_VARS["db_host"]}:{DB_VARS["db_port"]}/{DB_VARS["db_name"]}'
    )
elif DATABASE_TYPE == 'sqlite+sqlcipher' and not os.environ.get('DATABASE_URL'):
    # Handle SQLCipher with local file when DATABASE_URL wasn't explicitly set
    DATABASE_URL = f'sqlite+sqlcipher:///{DATA_DIR}/myah.db'

# Replace the postgres:// with postgresql://
if 'postgres://' in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://')

DATABASE_SCHEMA = os.environ.get('DATABASE_SCHEMA', None)

DATABASE_POOL_SIZE = os.environ.get('DATABASE_POOL_SIZE', None)

if DATABASE_POOL_SIZE != None:
    try:
        DATABASE_POOL_SIZE = int(DATABASE_POOL_SIZE)
    except Exception:
        DATABASE_POOL_SIZE = None

DATABASE_POOL_MAX_OVERFLOW = os.environ.get('DATABASE_POOL_MAX_OVERFLOW', 0)

if DATABASE_POOL_MAX_OVERFLOW == '':
    DATABASE_POOL_MAX_OVERFLOW = 0
else:
    try:
        DATABASE_POOL_MAX_OVERFLOW = int(DATABASE_POOL_MAX_OVERFLOW)
    except Exception:
        DATABASE_POOL_MAX_OVERFLOW = 0

DATABASE_POOL_TIMEOUT = os.environ.get('DATABASE_POOL_TIMEOUT', 30)

if DATABASE_POOL_TIMEOUT == '':
    DATABASE_POOL_TIMEOUT = 30
else:
    try:
        DATABASE_POOL_TIMEOUT = int(DATABASE_POOL_TIMEOUT)
    except Exception:
        DATABASE_POOL_TIMEOUT = 30

DATABASE_POOL_RECYCLE = os.environ.get('DATABASE_POOL_RECYCLE', 3600)

if DATABASE_POOL_RECYCLE == '':
    DATABASE_POOL_RECYCLE = 3600
else:
    try:
        DATABASE_POOL_RECYCLE = int(DATABASE_POOL_RECYCLE)
    except Exception:
        DATABASE_POOL_RECYCLE = 3600

DATABASE_ENABLE_SQLITE_WAL = os.environ.get('DATABASE_ENABLE_SQLITE_WAL', 'False').lower() == 'true'

DATABASE_USER_ACTIVE_STATUS_UPDATE_INTERVAL = os.environ.get('DATABASE_USER_ACTIVE_STATUS_UPDATE_INTERVAL', None)
if DATABASE_USER_ACTIVE_STATUS_UPDATE_INTERVAL is not None:
    try:
        DATABASE_USER_ACTIVE_STATUS_UPDATE_INTERVAL = float(DATABASE_USER_ACTIVE_STATUS_UPDATE_INTERVAL)
    except Exception:
        DATABASE_USER_ACTIVE_STATUS_UPDATE_INTERVAL = 0.0

# When enabled, get_db_context reuses existing sessions; set to False to always create new sessions
DATABASE_ENABLE_SESSION_SHARING = os.environ.get('DATABASE_ENABLE_SESSION_SHARING', 'False').lower() == 'true'

# Enable public visibility of active user count (when disabled, only admins can see it)
ENABLE_PUBLIC_ACTIVE_USERS_COUNT = os.environ.get('ENABLE_PUBLIC_ACTIVE_USERS_COUNT', 'True').lower() == 'true'

RESET_CONFIG_ON_START = os.environ.get('RESET_CONFIG_ON_START', 'False').lower() == 'true'

ENABLE_REALTIME_CHAT_SAVE = os.environ.get('ENABLE_REALTIME_CHAT_SAVE', 'False').lower() == 'true'

ENABLE_QUERIES_CACHE = os.environ.get('ENABLE_QUERIES_CACHE', 'False').lower() == 'true'

####################################
# REDIS
####################################

REDIS_URL = os.environ.get('REDIS_URL', '')
REDIS_CLUSTER = os.environ.get('REDIS_CLUSTER', 'False').lower() == 'true'

REDIS_KEY_PREFIX = os.environ.get('REDIS_KEY_PREFIX', 'open-webui')

REDIS_SENTINEL_HOSTS = os.environ.get('REDIS_SENTINEL_HOSTS', '')
REDIS_SENTINEL_PORT = os.environ.get('REDIS_SENTINEL_PORT', '26379')

# Maximum number of retries for Redis operations when using Sentinel fail-over
REDIS_SENTINEL_MAX_RETRY_COUNT = os.environ.get('REDIS_SENTINEL_MAX_RETRY_COUNT', '2')
try:
    REDIS_SENTINEL_MAX_RETRY_COUNT = int(REDIS_SENTINEL_MAX_RETRY_COUNT)
    if REDIS_SENTINEL_MAX_RETRY_COUNT < 1:
        REDIS_SENTINEL_MAX_RETRY_COUNT = 2
except ValueError:
    REDIS_SENTINEL_MAX_RETRY_COUNT = 2


REDIS_SOCKET_CONNECT_TIMEOUT = os.environ.get('REDIS_SOCKET_CONNECT_TIMEOUT', '')
try:
    REDIS_SOCKET_CONNECT_TIMEOUT = float(REDIS_SOCKET_CONNECT_TIMEOUT)
except ValueError:
    REDIS_SOCKET_CONNECT_TIMEOUT = None

REDIS_RECONNECT_DELAY = os.environ.get('REDIS_RECONNECT_DELAY', '')

if REDIS_RECONNECT_DELAY == '':
    REDIS_RECONNECT_DELAY = None
else:
    try:
        REDIS_RECONNECT_DELAY = float(REDIS_RECONNECT_DELAY)
        if REDIS_RECONNECT_DELAY < 0:
            REDIS_RECONNECT_DELAY = None
    except Exception:
        REDIS_RECONNECT_DELAY = None

####################################
# UVICORN WORKERS
####################################

# Number of uvicorn worker processes for handling requests
UVICORN_WORKERS = os.environ.get('UVICORN_WORKERS', '1')
try:
    UVICORN_WORKERS = int(UVICORN_WORKERS)
    if UVICORN_WORKERS < 1:
        UVICORN_WORKERS = 1
except ValueError:
    UVICORN_WORKERS = 1
    log.info(f'Invalid UVICORN_WORKERS value, defaulting to {UVICORN_WORKERS}')

####################################
# WEBUI_AUTH (Required for security)
####################################

MYAH_AUTH = _env('MYAH_AUTH', 'WEBUI_AUTH', 'True').lower() == 'true'
WEBUI_AUTH = MYAH_AUTH  # legacy alias

ENABLE_INITIAL_ADMIN_SIGNUP = os.environ.get('ENABLE_INITIAL_ADMIN_SIGNUP', 'False').lower() == 'true'
ENABLE_SIGNUP_PASSWORD_CONFIRMATION = os.environ.get('ENABLE_SIGNUP_PASSWORD_CONFIRMATION', 'False').lower() == 'true'

####################################
# Admin Account Runtime Creation
####################################

# Optional env vars for creating an admin account on startup
# Useful for headless/automated deployments
MYAH_ADMIN_EMAIL = _env('MYAH_ADMIN_EMAIL', 'WEBUI_ADMIN_EMAIL', '')
WEBUI_ADMIN_EMAIL = MYAH_ADMIN_EMAIL  # legacy alias

MYAH_ADMIN_PASSWORD = _env('MYAH_ADMIN_PASSWORD', 'WEBUI_ADMIN_PASSWORD', '')
WEBUI_ADMIN_PASSWORD = MYAH_ADMIN_PASSWORD  # legacy alias

MYAH_ADMIN_NAME = _env('MYAH_ADMIN_NAME', 'WEBUI_ADMIN_NAME', 'Admin')
WEBUI_ADMIN_NAME = MYAH_ADMIN_NAME  # legacy alias

MYAH_AUTH_TRUSTED_EMAIL_HEADER = _env('MYAH_AUTH_TRUSTED_EMAIL_HEADER', 'WEBUI_AUTH_TRUSTED_EMAIL_HEADER', None)
WEBUI_AUTH_TRUSTED_EMAIL_HEADER = MYAH_AUTH_TRUSTED_EMAIL_HEADER  # legacy alias

MYAH_AUTH_TRUSTED_NAME_HEADER = _env('MYAH_AUTH_TRUSTED_NAME_HEADER', 'WEBUI_AUTH_TRUSTED_NAME_HEADER', None)
WEBUI_AUTH_TRUSTED_NAME_HEADER = MYAH_AUTH_TRUSTED_NAME_HEADER  # legacy alias

MYAH_AUTH_TRUSTED_GROUPS_HEADER = _env('MYAH_AUTH_TRUSTED_GROUPS_HEADER', 'WEBUI_AUTH_TRUSTED_GROUPS_HEADER', None)
WEBUI_AUTH_TRUSTED_GROUPS_HEADER = MYAH_AUTH_TRUSTED_GROUPS_HEADER  # legacy alias

MYAH_AUTH_TRUSTED_ROLE_HEADER = _env('MYAH_AUTH_TRUSTED_ROLE_HEADER', 'WEBUI_AUTH_TRUSTED_ROLE_HEADER', None)
WEBUI_AUTH_TRUSTED_ROLE_HEADER = MYAH_AUTH_TRUSTED_ROLE_HEADER  # legacy alias


ENABLE_PASSWORD_VALIDATION = os.environ.get('ENABLE_PASSWORD_VALIDATION', 'False').lower() == 'true'
PASSWORD_VALIDATION_REGEX_PATTERN = os.environ.get(
    'PASSWORD_VALIDATION_REGEX_PATTERN',
    r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[^\w\s]).{8,}$',
)


try:
    PASSWORD_VALIDATION_REGEX_PATTERN = rf'{PASSWORD_VALIDATION_REGEX_PATTERN}'
    PASSWORD_VALIDATION_REGEX_PATTERN = re.compile(PASSWORD_VALIDATION_REGEX_PATTERN)
except Exception as e:
    log.error(f'Invalid PASSWORD_VALIDATION_REGEX_PATTERN: {e}')
    PASSWORD_VALIDATION_REGEX_PATTERN = re.compile(r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[^\w\s]).{8,}$')

PASSWORD_VALIDATION_HINT = os.environ.get('PASSWORD_VALIDATION_HINT', '')


BYPASS_MODEL_ACCESS_CONTROL = os.environ.get('BYPASS_MODEL_ACCESS_CONTROL', 'False').lower() == 'true'

MYAH_AUTH_SIGNOUT_REDIRECT_URL = _env('MYAH_AUTH_SIGNOUT_REDIRECT_URL', 'WEBUI_AUTH_SIGNOUT_REDIRECT_URL', None)
WEBUI_AUTH_SIGNOUT_REDIRECT_URL = MYAH_AUTH_SIGNOUT_REDIRECT_URL  # legacy alias

####################################
# WEBUI_SECRET_KEY
####################################

# WEBUI_JWT_SECRET_KEY is itself a legacy fallback for WEBUI_SECRET_KEY (the
# old open_webui code carried both names). The new MYAH_SECRET_KEY primary
# picks up both legacy WEBUI_SECRET_KEY AND legacy WEBUI_JWT_SECRET_KEY for
# back-compat. MYAH_JWT_SECRET_KEY is a separately-exposed primary in case
# any code reads that name directly.
MYAH_JWT_SECRET_KEY = _env('MYAH_JWT_SECRET_KEY', 'WEBUI_JWT_SECRET_KEY', 't0p-s3cr3t')
WEBUI_JWT_SECRET_KEY = MYAH_JWT_SECRET_KEY  # legacy alias

MYAH_SECRET_KEY = _env('MYAH_SECRET_KEY', 'WEBUI_SECRET_KEY', MYAH_JWT_SECRET_KEY)
WEBUI_SECRET_KEY = MYAH_SECRET_KEY  # legacy alias

MYAH_SESSION_COOKIE_SAME_SITE = _env('MYAH_SESSION_COOKIE_SAME_SITE', 'WEBUI_SESSION_COOKIE_SAME_SITE', 'lax')
WEBUI_SESSION_COOKIE_SAME_SITE = MYAH_SESSION_COOKIE_SAME_SITE  # legacy alias

MYAH_SESSION_COOKIE_SECURE = (
    _env('MYAH_SESSION_COOKIE_SECURE', 'WEBUI_SESSION_COOKIE_SECURE', 'false').lower() == 'true'
)
WEBUI_SESSION_COOKIE_SECURE = MYAH_SESSION_COOKIE_SECURE  # legacy alias

MYAH_AUTH_COOKIE_SAME_SITE = _env('MYAH_AUTH_COOKIE_SAME_SITE', 'WEBUI_AUTH_COOKIE_SAME_SITE', MYAH_SESSION_COOKIE_SAME_SITE)
WEBUI_AUTH_COOKIE_SAME_SITE = MYAH_AUTH_COOKIE_SAME_SITE  # legacy alias

MYAH_AUTH_COOKIE_SECURE = (
    _env(
        'MYAH_AUTH_COOKIE_SECURE',
        'WEBUI_AUTH_COOKIE_SECURE',
        # Original fallback chain: AUTH_COOKIE_SECURE -> SESSION_COOKIE_SECURE -> 'false'
        _env('MYAH_SESSION_COOKIE_SECURE', 'WEBUI_SESSION_COOKIE_SECURE', 'false'),
    ).lower()
    == 'true'
)
WEBUI_AUTH_COOKIE_SECURE = MYAH_AUTH_COOKIE_SECURE  # legacy alias

if WEBUI_AUTH and WEBUI_SECRET_KEY == '':
    raise ValueError(ERROR_MESSAGES.ENV_VAR_NOT_FOUND)

# Hard-fail in production if the default placeholder secret is in use.
# WEBUI_SECRET_KEY signs every session token AND the OAuth state JWT for the
# Composio integration. If prod ever started with the default 't0p-s3cr3t',
# every user account would be forgeable and every OAuth state JWT replayable.
# Allow override for local dev / CI by setting ALLOW_DEFAULT_WEBUI_SECRET_KEY=true.
if (
    ENV == 'prod'
    and WEBUI_SECRET_KEY == 't0p-s3cr3t'
    and os.environ.get('ALLOW_DEFAULT_WEBUI_SECRET_KEY', '').lower() != 'true'
):
    raise SystemExit(
        'WEBUI_SECRET_KEY must be explicitly set in production (currently using insecure default). '
        'Generate a strong random secret with `openssl rand -hex 32` and set it in the platform env.'
    )

ENABLE_COMPRESSION_MIDDLEWARE = os.environ.get('ENABLE_COMPRESSION_MIDDLEWARE', 'True').lower() == 'true'

####################################
# OAUTH Configuration
####################################
ENABLE_OAUTH_EMAIL_FALLBACK = os.environ.get('ENABLE_OAUTH_EMAIL_FALLBACK', 'False').lower() == 'true'

ENABLE_OAUTH_ID_TOKEN_COOKIE = os.environ.get('ENABLE_OAUTH_ID_TOKEN_COOKIE', 'True').lower() == 'true'

OAUTH_CLIENT_INFO_ENCRYPTION_KEY = os.environ.get('OAUTH_CLIENT_INFO_ENCRYPTION_KEY', WEBUI_SECRET_KEY)

OAUTH_SESSION_TOKEN_ENCRYPTION_KEY = os.environ.get('OAUTH_SESSION_TOKEN_ENCRYPTION_KEY', WEBUI_SECRET_KEY)

# Maximum number of concurrent OAuth sessions per user per provider
# This prevents unbounded session growth while allowing multi-device usage
OAUTH_MAX_SESSIONS_PER_USER = int(os.environ.get('OAUTH_MAX_SESSIONS_PER_USER', '10'))

# Token Exchange Configuration
# Allows external apps to exchange OAuth tokens for OpenWebUI tokens
ENABLE_OAUTH_TOKEN_EXCHANGE = os.environ.get('ENABLE_OAUTH_TOKEN_EXCHANGE', 'False').lower() == 'true'


####################################
# MODELS
####################################

ENABLE_CUSTOM_MODEL_FALLBACK = os.environ.get('ENABLE_CUSTOM_MODEL_FALLBACK', 'False').lower() == 'true'

MODELS_CACHE_TTL = os.environ.get('MODELS_CACHE_TTL', '1')
if MODELS_CACHE_TTL == '':
    MODELS_CACHE_TTL = None
else:
    try:
        MODELS_CACHE_TTL = int(MODELS_CACHE_TTL)
    except Exception:
        MODELS_CACHE_TTL = 1


####################################
# CHAT
####################################

ENABLE_CHAT_RESPONSE_BASE64_IMAGE_URL_CONVERSION = (
    os.environ.get('ENABLE_CHAT_RESPONSE_BASE64_IMAGE_URL_CONVERSION', 'False').lower() == 'true'
)

CHAT_STREAM_RESPONSE_CHUNK_MAX_BUFFER_SIZE = os.environ.get('CHAT_STREAM_RESPONSE_CHUNK_MAX_BUFFER_SIZE', '')

if CHAT_STREAM_RESPONSE_CHUNK_MAX_BUFFER_SIZE == '':
    CHAT_STREAM_RESPONSE_CHUNK_MAX_BUFFER_SIZE = None
else:
    try:
        CHAT_STREAM_RESPONSE_CHUNK_MAX_BUFFER_SIZE = int(CHAT_STREAM_RESPONSE_CHUNK_MAX_BUFFER_SIZE)
    except Exception:
        CHAT_STREAM_RESPONSE_CHUNK_MAX_BUFFER_SIZE = None


####################################
# WEBSOCKET SUPPORT
####################################

ENABLE_WEBSOCKET_SUPPORT = os.environ.get('ENABLE_WEBSOCKET_SUPPORT', 'True').lower() == 'true'


WEBSOCKET_MANAGER = os.environ.get('WEBSOCKET_MANAGER', '')

WEBSOCKET_REDIS_OPTIONS = os.environ.get('WEBSOCKET_REDIS_OPTIONS', '')


if WEBSOCKET_REDIS_OPTIONS == '':
    if REDIS_SOCKET_CONNECT_TIMEOUT:
        WEBSOCKET_REDIS_OPTIONS = {'socket_connect_timeout': REDIS_SOCKET_CONNECT_TIMEOUT}
    else:
        log.debug('No WEBSOCKET_REDIS_OPTIONS provided, defaulting to None')
        WEBSOCKET_REDIS_OPTIONS = None
else:
    try:
        WEBSOCKET_REDIS_OPTIONS = json.loads(WEBSOCKET_REDIS_OPTIONS)
    except Exception:
        log.warning('Invalid WEBSOCKET_REDIS_OPTIONS, defaulting to None')
        WEBSOCKET_REDIS_OPTIONS = None

WEBSOCKET_REDIS_URL = os.environ.get('WEBSOCKET_REDIS_URL', REDIS_URL)
WEBSOCKET_REDIS_CLUSTER = os.environ.get('WEBSOCKET_REDIS_CLUSTER', str(REDIS_CLUSTER)).lower() == 'true'

websocket_redis_lock_timeout = os.environ.get('WEBSOCKET_REDIS_LOCK_TIMEOUT', '60')

try:
    WEBSOCKET_REDIS_LOCK_TIMEOUT = int(websocket_redis_lock_timeout)
except ValueError:
    WEBSOCKET_REDIS_LOCK_TIMEOUT = 60

WEBSOCKET_SENTINEL_HOSTS = os.environ.get('WEBSOCKET_SENTINEL_HOSTS', '')
WEBSOCKET_SENTINEL_PORT = os.environ.get('WEBSOCKET_SENTINEL_PORT', '26379')
WEBSOCKET_SERVER_LOGGING = os.environ.get('WEBSOCKET_SERVER_LOGGING', 'False').lower() == 'true'
WEBSOCKET_SERVER_ENGINEIO_LOGGING = (
    os.environ.get(
        'WEBSOCKET_SERVER_ENGINEIO_LOGGING',
        os.environ.get('WEBSOCKET_SERVER_LOGGING', 'False'),
    ).lower()
    == 'true'
)
WEBSOCKET_SERVER_PING_TIMEOUT = os.environ.get('WEBSOCKET_SERVER_PING_TIMEOUT', '20')
try:
    WEBSOCKET_SERVER_PING_TIMEOUT = int(WEBSOCKET_SERVER_PING_TIMEOUT)
except ValueError:
    WEBSOCKET_SERVER_PING_TIMEOUT = 20

WEBSOCKET_SERVER_PING_INTERVAL = os.environ.get('WEBSOCKET_SERVER_PING_INTERVAL', '25')
try:
    WEBSOCKET_SERVER_PING_INTERVAL = int(WEBSOCKET_SERVER_PING_INTERVAL)
except ValueError:
    WEBSOCKET_SERVER_PING_INTERVAL = 25

WEBSOCKET_EVENT_CALLER_TIMEOUT = os.environ.get('WEBSOCKET_EVENT_CALLER_TIMEOUT', '')

if WEBSOCKET_EVENT_CALLER_TIMEOUT == '':
    WEBSOCKET_EVENT_CALLER_TIMEOUT = None
else:
    try:
        WEBSOCKET_EVENT_CALLER_TIMEOUT = int(WEBSOCKET_EVENT_CALLER_TIMEOUT)
    except ValueError:
        WEBSOCKET_EVENT_CALLER_TIMEOUT = 300


REQUESTS_VERIFY = os.environ.get('REQUESTS_VERIFY', 'True').lower() == 'true'

AIOHTTP_CLIENT_TIMEOUT = os.environ.get('AIOHTTP_CLIENT_TIMEOUT', '')

if AIOHTTP_CLIENT_TIMEOUT == '':
    AIOHTTP_CLIENT_TIMEOUT = None
else:
    try:
        AIOHTTP_CLIENT_TIMEOUT = int(AIOHTTP_CLIENT_TIMEOUT)
    except Exception:
        AIOHTTP_CLIENT_TIMEOUT = 300


AIOHTTP_CLIENT_SESSION_SSL = os.environ.get('AIOHTTP_CLIENT_SESSION_SSL', 'True').lower() == 'true'

AIOHTTP_CLIENT_TIMEOUT_MODEL_LIST = os.environ.get(
    'AIOHTTP_CLIENT_TIMEOUT_MODEL_LIST',
    os.environ.get('AIOHTTP_CLIENT_TIMEOUT_OPENAI_MODEL_LIST', '10'),
)

if AIOHTTP_CLIENT_TIMEOUT_MODEL_LIST == '':
    AIOHTTP_CLIENT_TIMEOUT_MODEL_LIST = None
else:
    try:
        AIOHTTP_CLIENT_TIMEOUT_MODEL_LIST = int(AIOHTTP_CLIENT_TIMEOUT_MODEL_LIST)
    except Exception:
        AIOHTTP_CLIENT_TIMEOUT_MODEL_LIST = 10


AIOHTTP_CLIENT_TIMEOUT_TOOL_SERVER_DATA = os.environ.get('AIOHTTP_CLIENT_TIMEOUT_TOOL_SERVER_DATA', '10')

if AIOHTTP_CLIENT_TIMEOUT_TOOL_SERVER_DATA == '':
    AIOHTTP_CLIENT_TIMEOUT_TOOL_SERVER_DATA = None
else:
    try:
        AIOHTTP_CLIENT_TIMEOUT_TOOL_SERVER_DATA = int(AIOHTTP_CLIENT_TIMEOUT_TOOL_SERVER_DATA)
    except Exception:
        AIOHTTP_CLIENT_TIMEOUT_TOOL_SERVER_DATA = 10


AIOHTTP_CLIENT_SESSION_TOOL_SERVER_SSL = (
    os.environ.get('AIOHTTP_CLIENT_SESSION_TOOL_SERVER_SSL', 'True').lower() == 'true'
)

AIOHTTP_CLIENT_TIMEOUT_TOOL_SERVER = os.environ.get('AIOHTTP_CLIENT_TIMEOUT_TOOL_SERVER', '')

if AIOHTTP_CLIENT_TIMEOUT_TOOL_SERVER == '':
    AIOHTTP_CLIENT_TIMEOUT_TOOL_SERVER = AIOHTTP_CLIENT_TIMEOUT
else:
    try:
        AIOHTTP_CLIENT_TIMEOUT_TOOL_SERVER = int(AIOHTTP_CLIENT_TIMEOUT_TOOL_SERVER)
    except Exception:
        AIOHTTP_CLIENT_TIMEOUT_TOOL_SERVER = AIOHTTP_CLIENT_TIMEOUT


####################################
# OFFLINE_MODE
####################################

ENABLE_VERSION_UPDATE_CHECK = os.environ.get('ENABLE_VERSION_UPDATE_CHECK', 'true').lower() == 'true'
OFFLINE_MODE = os.environ.get('OFFLINE_MODE', 'false').lower() == 'true'

if OFFLINE_MODE:
    os.environ['HF_HUB_OFFLINE'] = '1'
    ENABLE_VERSION_UPDATE_CHECK = False

####################################
# AUDIT LOGGING
####################################


ENABLE_AUDIT_STDOUT = os.getenv('ENABLE_AUDIT_STDOUT', 'False').lower() == 'true'
ENABLE_AUDIT_LOGS_FILE = os.getenv('ENABLE_AUDIT_LOGS_FILE', 'True').lower() == 'true'

# Where to store log file
# Defaults to the DATA_DIR/audit.log. To set AUDIT_LOGS_FILE_PATH you need to
# provide the whole path, like: /app/audit.log
AUDIT_LOGS_FILE_PATH = os.getenv('AUDIT_LOGS_FILE_PATH', f'{DATA_DIR}/audit.log')
# Maximum size of a file before rotating into a new log file
AUDIT_LOG_FILE_ROTATION_SIZE = os.getenv('AUDIT_LOG_FILE_ROTATION_SIZE', '10MB')

# Comma separated list of logger names to use for audit logging
# Default is "uvicorn.access" which is the access log for Uvicorn
# You can add more logger names to this list if you want to capture more logs
AUDIT_UVICORN_LOGGER_NAMES = os.getenv('AUDIT_UVICORN_LOGGER_NAMES', 'uvicorn.access').split(',')

# METADATA | REQUEST | REQUEST_RESPONSE
AUDIT_LOG_LEVEL = os.getenv('AUDIT_LOG_LEVEL', 'NONE').upper()
try:
    MAX_BODY_LOG_SIZE = int(os.environ.get('MAX_BODY_LOG_SIZE') or 2048)
except ValueError:
    MAX_BODY_LOG_SIZE = 2048

# Comma separated list for urls to exclude from audit
AUDIT_EXCLUDED_PATHS = os.getenv('AUDIT_EXCLUDED_PATHS', '/chats,/chat,/folders').split(',')
AUDIT_EXCLUDED_PATHS = [path.strip() for path in AUDIT_EXCLUDED_PATHS]
AUDIT_EXCLUDED_PATHS = [path.lstrip('/') for path in AUDIT_EXCLUDED_PATHS]

# Comma separated list of urls to include in audit (whitelist mode)
# When set, only these paths are audited and AUDIT_EXCLUDED_PATHS is ignored
AUDIT_INCLUDED_PATHS = os.getenv('AUDIT_INCLUDED_PATHS', '').split(',')
AUDIT_INCLUDED_PATHS = [path.strip() for path in AUDIT_INCLUDED_PATHS]
AUDIT_INCLUDED_PATHS = [path.lstrip('/') for path in AUDIT_INCLUDED_PATHS if path]


####################################
# SENTRY
####################################

SENTRY_DSN_PLATFORM = os.environ.get('SENTRY_DSN_PLATFORM', '')

####################################
# OPENTELEMETRY
####################################

ENABLE_OTEL = os.environ.get('ENABLE_OTEL', 'False').lower() == 'true'
ENABLE_OTEL_TRACES = os.environ.get('ENABLE_OTEL_TRACES', 'False').lower() == 'true'
ENABLE_OTEL_METRICS = os.environ.get('ENABLE_OTEL_METRICS', 'False').lower() == 'true'
ENABLE_OTEL_LOGS = os.environ.get('ENABLE_OTEL_LOGS', 'False').lower() == 'true'

OTEL_EXPORTER_OTLP_ENDPOINT = os.environ.get('OTEL_EXPORTER_OTLP_ENDPOINT', 'http://localhost:4317')
OTEL_METRICS_EXPORTER_OTLP_ENDPOINT = os.environ.get('OTEL_METRICS_EXPORTER_OTLP_ENDPOINT', OTEL_EXPORTER_OTLP_ENDPOINT)
OTEL_LOGS_EXPORTER_OTLP_ENDPOINT = os.environ.get('OTEL_LOGS_EXPORTER_OTLP_ENDPOINT', OTEL_EXPORTER_OTLP_ENDPOINT)
OTEL_EXPORTER_OTLP_INSECURE = os.environ.get('OTEL_EXPORTER_OTLP_INSECURE', 'False').lower() == 'true'
OTEL_METRICS_EXPORTER_OTLP_INSECURE = (
    os.environ.get('OTEL_METRICS_EXPORTER_OTLP_INSECURE', str(OTEL_EXPORTER_OTLP_INSECURE)).lower() == 'true'
)
OTEL_LOGS_EXPORTER_OTLP_INSECURE = (
    os.environ.get('OTEL_LOGS_EXPORTER_OTLP_INSECURE', str(OTEL_EXPORTER_OTLP_INSECURE)).lower() == 'true'
)
OTEL_SERVICE_NAME = os.environ.get('OTEL_SERVICE_NAME', 'open-webui')
OTEL_RESOURCE_ATTRIBUTES = os.environ.get('OTEL_RESOURCE_ATTRIBUTES', '')  # e.g. key1=val1,key2=val2
OTEL_TRACES_SAMPLER = os.environ.get('OTEL_TRACES_SAMPLER', 'parentbased_always_on').lower()
OTEL_BASIC_AUTH_USERNAME = os.environ.get('OTEL_BASIC_AUTH_USERNAME', '')
OTEL_BASIC_AUTH_PASSWORD = os.environ.get('OTEL_BASIC_AUTH_PASSWORD', '')
OTEL_METRICS_EXPORT_INTERVAL_MILLIS = int(os.environ.get('OTEL_METRICS_EXPORT_INTERVAL_MILLIS', '10000'))

OTEL_METRICS_BASIC_AUTH_USERNAME = os.environ.get('OTEL_METRICS_BASIC_AUTH_USERNAME', OTEL_BASIC_AUTH_USERNAME)
OTEL_METRICS_BASIC_AUTH_PASSWORD = os.environ.get('OTEL_METRICS_BASIC_AUTH_PASSWORD', OTEL_BASIC_AUTH_PASSWORD)
OTEL_LOGS_BASIC_AUTH_USERNAME = os.environ.get('OTEL_LOGS_BASIC_AUTH_USERNAME', OTEL_BASIC_AUTH_USERNAME)
OTEL_LOGS_BASIC_AUTH_PASSWORD = os.environ.get('OTEL_LOGS_BASIC_AUTH_PASSWORD', OTEL_BASIC_AUTH_PASSWORD)

OTEL_OTLP_SPAN_EXPORTER = os.environ.get('OTEL_OTLP_SPAN_EXPORTER', 'grpc').lower()  # grpc or http

OTEL_METRICS_OTLP_SPAN_EXPORTER = os.environ.get(
    'OTEL_METRICS_OTLP_SPAN_EXPORTER', OTEL_OTLP_SPAN_EXPORTER
).lower()  # grpc or http

OTEL_LOGS_OTLP_SPAN_EXPORTER = os.environ.get(
    'OTEL_LOGS_OTLP_SPAN_EXPORTER', OTEL_OTLP_SPAN_EXPORTER
).lower()  # grpc or http

####################################
# TOOLS/FUNCTIONS PIP OPTIONS
####################################

ENABLE_PIP_INSTALL_FRONTMATTER_REQUIREMENTS = (
    os.environ.get('ENABLE_PIP_INSTALL_FRONTMATTER_REQUIREMENTS', 'True').lower() == 'true'
)

PIP_OPTIONS = os.getenv('PIP_OPTIONS', '').split()
PIP_PACKAGE_INDEX_OPTIONS = os.getenv('PIP_PACKAGE_INDEX_OPTIONS', '').split()


####################################
# MYAH AGENT SETTINGS UI
####################################

# ── Myah: feature flag for the /api/v1/agent/* user-configuration UI ──
ENABLE_AGENT_SETTINGS_UI = os.environ.get('ENABLE_AGENT_SETTINGS_UI', 'True').lower() == 'true'
# ──────────────────────────────────────────────────────────────────────

COMPOSIO_API_KEY = os.environ.get('COMPOSIO_API_KEY', '')


####################################
# GROUP DEFAULTS
####################################

# Controls the default "Who can share to this group" setting for new groups.
# Env var values: "true" (anyone), "false" (no one), "members" (only group members).
_default_group_share = os.environ.get('DEFAULT_GROUP_SHARE_PERMISSION', 'members').strip().lower()
DEFAULT_GROUP_SHARE_PERMISSION = 'members' if _default_group_share == 'members' else _default_group_share == 'true'


####################################
# LEGACY ALIASES
####################################

# Legacy alias preserved for back-compat. Defined at module bottom so its
# value reflects MYAH_BACKEND_DIR's final state. Phase B.2b (rename order #4)
# renamed OPEN_WEBUI_DIR → MYAH_BACKEND_DIR; this alias keeps any out-of-tree
# importer working.
OPEN_WEBUI_DIR = MYAH_BACKEND_DIR
