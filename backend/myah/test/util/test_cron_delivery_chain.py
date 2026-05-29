"""
Tests for the cron output delivery chain.

The chain has 5 component boundaries that each need verification:

1. Webhook URL construction — correct host + port for the runtime platform
2. _inject_cron_output_to_chat — finds the chat, appends a message, updates currentId
3. process:run-complete socket event — includes chat_id so the frontend knows which chat
4. Container env — webhook URL env var is set correctly at container spawn time
5. Delivery failure visibility — errors must surface via Sentry and socket events

These tests exist because:
- The webhook URL was silently wrong on macOS (172.17.0.1 → unreachable) for months
- _inject_cron_output_to_chat silently returned when the chat wasn't found
- process:run-complete didn't include chat_id, so the frontend never updated
- Delivery failures were swallowed at logger.warning level, invisible in Sentry
- There were zero tests for ANY of these components

See: docs/superpowers/plans/2026-04-11-cron-system-restore.md
"""

import importlib.util
import socket
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Module loader (same pattern as test_containers_env.py — containers.py has
# heavy imports that we stub out)
# ---------------------------------------------------------------------------


def _load_containers_module(monkeypatch=None, argv=None):
    """Load containers.py with stubbed dependencies.

    Args:
        monkeypatch: pytest monkeypatch fixture (optional)
        argv: override sys.argv for port detection tests
    """
    constants = ModuleType('myah.constants')
    constants.ERROR_MESSAGES = {}

    models_containers = ModuleType('myah.models.containers')
    models_containers.ContainerModel = object
    models_containers.Containers = SimpleNamespace(update_status=lambda *args, **kwargs: None)

    models_users = ModuleType('myah.models.users')
    models_users.UserModel = object

    services_honcho = ModuleType('myah.services.honcho')
    services_honcho.honcho_service = SimpleNamespace()

    utils_auth = ModuleType('myah.utils.auth')
    utils_auth.get_admin_user = lambda: None
    utils_auth.get_verified_user = lambda: None

    saved_modules = {}
    stub_modules = {
        'myah.constants': constants,
        'myah.models.containers': models_containers,
        'myah.models.users': models_users,
        'myah.services.honcho': services_honcho,
        'myah.utils.auth': utils_auth,
    }
    for name, mod in stub_modules.items():
        saved_modules[name] = sys.modules.get(name)
        sys.modules[name] = mod

    if argv is not None:
        saved_argv = sys.argv
        sys.argv = argv

    try:
        path = Path(__file__).resolve().parents[2] / 'routers' / 'containers.py'
        spec = importlib.util.spec_from_file_location('test_containers_cron', path)
        module = importlib.util.module_from_spec(spec)
        assert spec is not None and spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        if argv is not None:
            sys.argv = saved_argv
        for name, mod in saved_modules.items():
            if mod is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = mod


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Webhook URL construction — host auto-detection
# ═══════════════════════════════════════════════════════════════════════════════


class TestWebhookHostDetection:
    """Verify _detect_docker_host picks the right hostname for the runtime OS.

    _detect_docker_host() now uses platform.system() (not DNS resolution) to
    distinguish Docker Desktop (macOS/Windows) from native Linux Docker.
    """

    def test_macos_uses_host_docker_internal(self, monkeypatch):
        """On macOS (Darwin), return host.docker.internal — Docker Desktop provides it."""
        monkeypatch.delenv('MYAH_PLATFORM_WEBHOOK_HOST', raising=False)
        containers = _load_containers_module()

        with patch('platform.system', return_value='Darwin'):
            result = containers._detect_docker_host()
        assert result == 'host.docker.internal'

    def test_windows_uses_host_docker_internal(self, monkeypatch):
        """On Windows, return host.docker.internal — Docker Desktop provides it."""
        monkeypatch.delenv('MYAH_PLATFORM_WEBHOOK_HOST', raising=False)
        containers = _load_containers_module()

        with patch('platform.system', return_value='Windows'):
            result = containers._detect_docker_host()
        assert result == 'host.docker.internal'

    def test_linux_uses_docker_bridge(self, monkeypatch):
        """On Linux (native Docker), use 172.17.0.1 — the Docker bridge gateway."""
        monkeypatch.delenv('MYAH_PLATFORM_WEBHOOK_HOST', raising=False)
        containers = _load_containers_module()

        with patch('platform.system', return_value='Linux'):
            result = containers._detect_docker_host()
        assert result == '172.17.0.1'

    def test_explicit_env_overrides_auto_detect(self, monkeypatch):
        """MYAH_PLATFORM_WEBHOOK_HOST env var takes precedence over auto-detection."""
        monkeypatch.setenv('MYAH_PLATFORM_WEBHOOK_HOST', '10.0.0.5')
        containers = _load_containers_module()
        assert containers.PLATFORM_WEBHOOK_HOST == '10.0.0.5'


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Webhook URL construction — port auto-detection
# ═══════════════════════════════════════════════════════════════════════════════


class TestWebhookPortDetection:
    """Verify _detect_platform_port picks the correct port."""

    def test_detects_port_from_uvicorn_cli_arg(self, monkeypatch):
        """When uvicorn --port 8082 is in sys.argv, detect it."""
        monkeypatch.delenv('MYAH_PLATFORM_PORT', raising=False)
        containers = _load_containers_module(argv=['uvicorn', 'myah.main:app', '--port', '8082'])
        # PLATFORM_PORT is set at module load time, when argv was overridden
        assert containers.PLATFORM_PORT == '8082'

    def test_explicit_env_overrides_cli(self, monkeypatch):
        """MYAH_PLATFORM_PORT env var takes precedence over --port arg."""
        monkeypatch.setenv('MYAH_PLATFORM_PORT', '9090')
        containers = _load_containers_module(argv=['uvicorn', '--port', '8082'])
        assert containers.PLATFORM_PORT == '9090'

    def test_defaults_to_8080_when_no_signal(self, monkeypatch):
        """Production default: no env var, no CLI arg → port 8080."""
        monkeypatch.delenv('MYAH_PLATFORM_PORT', raising=False)
        containers = _load_containers_module(argv=['python3', '-m', 'main'])
        assert containers.PLATFORM_PORT == '8080'


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Container env var construction — webhook URL passed to spawned containers
# ═══════════════════════════════════════════════════════════════════════════════


class TestContainerWebhookEnv:
    """Verify that spawned agent containers get the correct MYAH_PLATFORM_WEBHOOK_URL."""

    def test_webhook_url_uses_detected_host_and_port(self, monkeypatch):
        """The MYAH_PLATFORM_WEBHOOK_URL env var combines host and port correctly."""
        containers = _load_containers_module()
        monkeypatch.setattr(containers, 'PLATFORM_WEBHOOK_HOST', 'host.docker.internal')
        monkeypatch.setattr(containers, 'PLATFORM_PORT', '8082')
        monkeypatch.setattr(containers, 'AGENT_BEARER_TOKEN', 'test-token')

        fake_containers = SimpleNamespace(
            get=lambda _name: (_ for _ in ()).throw(type('NotFound', (Exception,), {})('x')),
            run=lambda **kw: SimpleNamespace(id='c-1'),
        )
        fake_containers.run = MagicMock(return_value=SimpleNamespace(id='c-1'))

        class _NotFound(Exception):
            pass

        monkeypatch.setattr(containers, 'NotFound', _NotFound)
        fake_containers.get = lambda _name: (_ for _ in ()).throw(_NotFound('not found'))
        monkeypatch.setattr(containers, '_docker_client', lambda: SimpleNamespace(containers=fake_containers))
        monkeypatch.setattr(containers, '_free_port', lambda: 5000)

        containers._start_container_sync('user-1', honcho_api_key='h', honcho_workspace_id='w')

        env = fake_containers.run.call_args[1]['environment']
        assert env['MYAH_PLATFORM_WEBHOOK_URL'] == 'http://host.docker.internal:8082'


# ═══════════════════════════════════════════════════════════════════════════════
# 4. process:run-complete socket event — must include chat_id
# ═══════════════════════════════════════════════════════════════════════════════


class TestProcessRunCompleteEvent:
    """Verify the webhook handler emits chat_id in the socket event payload."""

    def test_socket_event_includes_chat_id(self):
        """The process:run-complete socket event must include chat_id so the
        frontend Chat.svelte cronRunCompleteHandler can match it to the current chat."""
        # Read the source to verify the socket emit includes chat_id.
        # This is a static analysis test — fragile but catches regressions
        # without needing the full async stack.
        source = Path(__file__).resolve().parents[2] / 'routers' / 'processes.py'
        content = source.read_text()

        # Find the emit block for process:run-complete
        import re

        # Match the dict literal inside sio.emit('process:run-complete', {...})
        pattern = r"sio\.emit\(\s*'process:run-complete',\s*\{([^}]+)\}"
        matches = re.findall(pattern, content)

        assert len(matches) >= 1, 'Expected at least one process:run-complete emit'

        # The LAST match (from the webhook handler, not the UI action handler)
        # must contain chat_id
        webhook_emit = matches[-1]
        assert "'chat_id'" in webhook_emit or '"chat_id"' in webhook_emit, (
            'process:run-complete socket event must include chat_id in payload. '
            'Without it, Chat.svelte cannot match the event to the current chat. '
            f'Found emit payload keys: {webhook_emit}'
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Frontend socket listener — Chat.svelte must handle process:run-complete
# ═══════════════════════════════════════════════════════════════════════════════


class TestFrontendSocketListener:
    """Verify Chat.svelte listens for process:run-complete events."""

    def test_chat_svelte_has_process_run_complete_listener(self):
        """Chat.svelte must register a socket listener for process:run-complete
        so cron output appears in real time when the user is viewing the chat."""
        chat_svelte = Path(__file__).resolve().parents[4] / 'src' / 'lib' / 'components' / 'chat' / 'Chat.svelte'
        content = chat_svelte.read_text()

        assert 'process:run-complete' in content, (
            'Chat.svelte must listen for process:run-complete socket events. '
            'Without this, cron output is injected into the DB but never '
            'appears in the chat UI until the user navigates away and back.'
        )

        # Verify both registration AND cleanup
        assert "on('process:run-complete'" in content or 'on("process:run-complete"' in content, (
            'Chat.svelte must register a socket.on handler for process:run-complete'
        )
        assert "off('process:run-complete'" in content or 'off("process:run-complete"' in content, (
            'Chat.svelte must unregister the process:run-complete handler on destroy'
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Delivery failure visibility — must NOT be silently swallowed
# ═══════════════════════════════════════════════════════════════════════════════


class TestDeliveryFailureVisibility:
    """Verify cron delivery failures are surfaced — not silently swallowed.

    Previous behaviour: when no chat was found, _inject_cron_output_to_chat
    logged at WARNING level and returned None. This was invisible: no Sentry
    issue, no frontend notification, the user just never saw their cron output.

    Required behaviour:
    - _inject_cron_output_to_chat returns False (not None) on failure
    - Returns True on success
    - The webhook handler emits process:delivery-failed when delivery fails
    - The layout.svelte global listener shows a toast for process:delivery-failed
    """

    def test_inject_cron_output_returns_false_when_no_chat_found(self):
        """_inject_cron_output_to_chat must return False (not None) when the
        target chat cannot be found, so callers can distinguish delivery failures."""
        source = Path(__file__).resolve().parents[2] / 'routers' / 'processes.py'
        content = source.read_text()

        # The function must have a return type annotation of -> bool
        assert '-> bool' in content, (
            '_inject_cron_output_to_chat must declare -> bool return type so that '
            'callers know to check the return value for delivery success/failure'
        )

        # When no process_chat is found, it must return False (not just return)
        import re

        # Find the block that handles "no process_chat found"
        no_chat_section = re.search(
            r'if not process_chat:.*?return (False|True)',
            content,
            re.DOTALL,
        )
        assert no_chat_section is not None, '_inject_cron_output_to_chat must return False when no chat is found'
        assert no_chat_section.group(1) == 'False', (
            'When no chat is found, _inject_cron_output_to_chat must return False '
            '(not True or bare return), so callers know delivery failed'
        )

    def test_inject_cron_output_returns_true_on_success(self):
        """_inject_cron_output_to_chat must return True on successful injection."""
        source = Path(__file__).resolve().parents[2] / 'routers' / 'processes.py'
        content = source.read_text()

        # After a successful upsert, must return True
        assert 'return True' in content, (
            '_inject_cron_output_to_chat must return True after successfully injecting the cron output into the chat'
        )

    def test_delivery_failure_emits_sentry_capture(self):
        """When no chat is found, a Sentry capture_message must be called so
        the error shows up in Sentry for monitoring."""
        source = Path(__file__).resolve().parents[2] / 'routers' / 'processes.py'
        content = source.read_text()

        assert 'sentry_sdk.capture_message' in content or 'capture_message' in content, (
            '_inject_cron_output_to_chat must call sentry_sdk.capture_message when '
            'no chat is found. Without this, delivery failures are invisible in Sentry.'
        )

    def test_webhook_handler_emits_delivery_failed_event(self):
        """When _inject_cron_output_to_chat returns False, the webhook handler must
        emit process:delivery-failed so the frontend can show a toast notification."""
        source = Path(__file__).resolve().parents[2] / 'routers' / 'processes.py'
        content = source.read_text()

        assert "'process:delivery-failed'" in content or '"process:delivery-failed"' in content, (
            "The cron webhook handler must emit 'process:delivery-failed' when chat "
            'injection fails. Without this, the user sees a cron task complete in the '
            'background with no output and no indication of failure.'
        )

    def test_layout_svelte_listens_for_delivery_failed(self):
        """The global layout must listen for process:delivery-failed and show a toast."""
        layout = Path(__file__).resolve().parents[4] / 'src' / 'routes' / '+layout.svelte'
        content = layout.read_text()

        assert 'process:delivery-failed' in content, (
            '+layout.svelte must listen for process:delivery-failed socket events '
            'so users always see a notification when cron output cannot be delivered'
        )

    def test_layout_svelte_dedupes_delivery_failed_toasts(self):
        """Repeated socket events for the same failed run must not spawn
        repeated identical toasts.

        Deduplication key is (job_id, ran_at) and lives in the shared global
        layout listener because reconnects / retries happen at the socket layer,
        not inside an individual chat/task component.
        """
        layout = Path(__file__).resolve().parents[4] / 'src' / 'routes' / '+layout.svelte'
        content = layout.read_text()

        assert 'seenCronDeliveryFailures' in content, (
            '+layout.svelte must track seen cron delivery failures so reconnects '
            'or retries do not spam duplicate toasts for the same failed run'
        )
        assert 'job_id' in content and 'ran_at' in content, (
            'Cron delivery failure toast dedupe must key on both job_id and ran_at '
            'so distinct failed runs still notify once each'
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 7. link-chat endpoint validation — prevents garbage chat_id values
# ═══════════════════════════════════════════════════════════════════════════════


class TestLinkChatValidation:
    """Verify link-chat endpoint rejects invalid chat_id values.

    Previous behaviour: any non-empty string was accepted as chat_id, including
    temporary chat IDs like 'local:socket-id' that are never persisted to the DB.
    This caused cron delivery to fail silently.
    """

    def test_link_chat_rejects_local_prefix(self):
        """link_process_to_chat must reject chat IDs starting with 'local:'."""
        source = Path(__file__).resolve().parents[2] / 'routers' / 'processes.py'
        content = source.read_text()

        assert "startswith('local:')" in content or 'startswith("local:")' in content, (
            "link_process_to_chat must reject chat IDs starting with 'local:' — "
            'these are temporary session IDs, not real DB chat IDs. Storing them '
            'causes cron delivery to silently fail.'
        )

    def test_link_chat_validates_chat_exists(self):
        """link_process_to_chat must verify the chat exists in the DB before
        storing its ID on the Hermes job."""
        source = Path(__file__).resolve().parents[2] / 'routers' / 'processes.py'
        content = source.read_text()

        # The endpoint should call Chats.get_chat_by_id_and_user_id or similar
        assert 'get_chat_by_id' in content and 'link_process_to_chat' in content, (
            'link_process_to_chat must look up the chat in the DB before storing '
            'the chat_id on the Hermes job. A non-existent chat_id causes silent '
            'delivery failure later.'
        )

    def test_cron_run_message_always_uses_card_style(self):
        """ResponseMessage must check isCronRun BEFORE useOutputRenderer so that
        all cron messages use CronRunMessage card style, even when they have output."""
        response_message = (
            Path(__file__).resolve().parents[4]
            / 'src'
            / 'lib'
            / 'components'
            / 'chat'
            / 'Messages'
            / 'ResponseMessage.svelte'
        )
        content = response_message.read_text()

        # isCronRun must not be gated on !useOutputRenderer
        assert (
            '!useOutputRenderer' not in content.split('isCronRun')[1].split('\n')[0]
            if 'isCronRun' in content
            else False
        ), (
            'ResponseMessage.svelte: isCronRun must not be gated on !useOutputRenderer. '
            'All cron messages should render with CronRunMessage style, including '
            'those that used tools (which have a non-empty output array).'
        )
