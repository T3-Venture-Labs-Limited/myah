"""Composable health-check predicates used by `myah doctor`.

Each check returns a `CheckResult` (status + human-readable message).
Checks are intentionally small and individually testable. The
`doctor_command` (in `myah/cli/doctor.py`) composes them and renders
the results as a Rich table.

All subprocess calls go through `myah.lib.cli.shell.run` (see
`shell.py`) so tests can mock at one point.
"""

from __future__ import annotations

import os
import re
import shutil
import socket
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from myah.lib.cli.shell import run


class CheckStatus(str, Enum):
    """Three-level status for individual checks."""

    OK = 'ok'
    WARN = 'warn'
    FAIL = 'fail'


@dataclass(frozen=True, slots=True)
class CheckResult:
    """Result of one health check."""

    name: str
    status: CheckStatus
    message: str


def check_hermes_binary_on_path() -> CheckResult:
    """Verify the `hermes` binary is on PATH.

    Uses `shutil.which` (no subprocess; portable; testable via single mock point).
    """
    hermes_path = shutil.which('hermes')
    if hermes_path:
        return CheckResult(
            name='hermes binary',
            status=CheckStatus.OK,
            message=f'hermes found at {hermes_path}',
        )
    return CheckResult(
        name='hermes binary',
        status=CheckStatus.FAIL,
        message=(
            'hermes not found on PATH. Install via: curl -fsSL '
            'https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash'
        ),
    )


def check_hermes_plugin_installed(hermes_home: str | None = None) -> CheckResult:
    """Verify the myah-hermes-plugin is installed in the Hermes plugins dir.

    `hermes_home` defaults to the expanded `~/.hermes`. Python does NOT
    expand `~` in env vars and the hermes binary may not either, so we
    must call `os.path.expanduser` ourselves before handing it off as
    `HERMES_HOME` — otherwise the plugin check looks at a literal `~`
    directory (which doesn't exist) and reports FAIL on machines where
    the plugin IS correctly installed.
    """
    if hermes_home is None:
        hermes_home = os.path.expanduser('~/.hermes')
    # Inherit parent env (PATH, etc.) and override HERMES_HOME — shell.run's
    # `env=` REPLACES the subprocess env, so an empty dict would strip PATH
    # and make `hermes` unfindable even when it's on PATH for the parent.
    child_env = {**os.environ, 'HERMES_HOME': hermes_home}
    try:
        result = run(['hermes', 'plugins', 'list'], env=child_env)
    except FileNotFoundError:
        # `hermes` binary missing; check_hermes_binary_on_path will already FAIL.
        # Don't double-FAIL — return FAIL with a downstream hint.
        return CheckResult(
            name='myah-hermes-plugin',
            status=CheckStatus.FAIL,
            message='hermes binary missing; cannot list plugins. Install hermes first.',
        )
    # Hermes 0.14.0 ``plugins list`` prints a Rich table where the
    # gateway-side plugin appears as the literal name ``myah`` (NOT
    # ``myah-hermes-plugin`` — that's the PyPI/pip package name, never
    # the Hermes-registered plugin name). Match either form to stay
    # compatible with older Hermes builds that printed the package
    # name and with the actual production output. ``myah-admin``
    # (the dashboard shim) must NOT satisfy this check — only the
    # gateway plugin binds port 8643. Regression for PR #16 review H-3.
    if result.returncode == 0:
        match = _match_myah_plugin_row(result.stdout)
        if match is not None:
            version = match
            return CheckResult(
                name='myah-hermes-plugin',
                status=CheckStatus.OK,
                message=f'plugin installed (version {version})',
            )
    return CheckResult(
        name='myah-hermes-plugin',
        status=CheckStatus.FAIL,
        message='plugin not installed. Install via: hermes plugins install T3-Venture-Labs-Limited/myah-hermes-plugin',
    )


def _match_myah_plugin_row(stdout: str) -> str | None:
    """Return the plugin's version from a ``hermes plugins list`` table.

    Recognized row shapes (in priority order):

      1. Rich-table row: ``│ myah │ <status> │ <version> │ ...``
         (Hermes 0.14.0 production format).
      2. Plain space-separated: ``myah-hermes-plugin <version> ...``
         (older Hermes builds + the PyPI package-name form).

    Returns ``None`` when neither shape matches. Carefully excludes the
    ``myah-admin`` shim row by anchoring on a word-boundary after the
    name and rejecting a trailing ``-`` character.
    """
    # Form 1: Rich table row. The leading character of a Rich row is
    # ``│`` (U+2502). ``myah`` must be a standalone cell — followed by
    # whitespace then the next ``│`` separator. Excludes ``myah-admin``
    # because the name cell ends with ``-admin``, not whitespace+``│``.
    rich_match = re.search(r'│\s+myah\s+│\s+\S+\s+│\s+(\S+)', stdout)
    if rich_match is not None:
        return rich_match.group(1)
    # Form 2: legacy plain-text. ``myah-hermes-plugin`` is a unique
    # package-name token; the original implementation used a simple
    # substring check, kept here as a fallback.
    plain_match = re.search(r'\bmyah-hermes-plugin\s+(\S+)', stdout)
    if plain_match is not None:
        return plain_match.group(1)
    return None


def check_port_for_service(port: int, service_name: str | None = None) -> CheckResult:
    """Verify the port is in a state consistent with the service's running mode.

    Behavior:
    - Port FREE → OK ('available, ready to bind')
    - Port BOUND → OK ('in use — assumed by {service_name}'). We can't easily
      identify the actual owner cross-platform without lsof parsing; trust the
      paired container/service check (e.g. `check_platform_container_running`)
      to validate it's the right owner.

    Replaces the original `check_port_available`, which treated 'in use' as
    FAIL and so reported FAIL on a healthy stack (the platform container
    binds 8080). Doctor checks are designed to diagnose health, not pre-flight
    emptiness.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(('127.0.0.1', port))
        return CheckResult(
            name=f'port {port}',
            status=CheckStatus.OK,
            message=f'port {port} is available (no service bound)',
        )
    except OSError:
        suffix = f' (expected: {service_name})' if service_name else ''
        return CheckResult(
            name=f'port {port}',
            status=CheckStatus.OK,
            message=f'port {port} in use{suffix}',
        )


def check_platform_container_running() -> CheckResult:
    """Verify the myah-platform Docker container is running.

    Distinguishes three failure modes:
    - docker binary missing / daemon down / permission denied → FAIL
      (operator must fix Docker itself before any container can run)
    - daemon up, container absent → WARN (operator runs `myah platform up`)
    - daemon up, container present → OK
    """
    try:
        result = run([
            'docker',
            'ps',
            '--filter',
            'label=com.docker.compose.service=platform',
            '--format',
            '{{.ID}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}\t{{.Names}}',
        ])
    except FileNotFoundError:
        return CheckResult(
            name='myah-platform container',
            status=CheckStatus.FAIL,
            message='docker binary not found. Install Docker: https://docs.docker.com/get-docker/',
        )
    if result.returncode != 0:
        return CheckResult(
            name='myah-platform container',
            status=CheckStatus.FAIL,
            message=(
                f'docker ps failed (daemon down or permission denied?): '
                f'{result.stderr.strip() or "unknown error"}'
            ),
        )
    if result.stdout.strip():
        return CheckResult(
            name='myah-platform container',
            status=CheckStatus.OK,
            message='platform container running',
        )
    return CheckResult(
        name='myah-platform container',
        status=CheckStatus.WARN,
        message='platform container not running (start with: myah platform up)',
    )


def check_plugin_sha_drift(
    dockerfile_path: str = 'agent/Dockerfile.stock',
    deploy_yml_path: str = '.github/workflows/deploy.yml',
    versions_env_path: str = 'versions.env',
) -> CheckResult:
    """Verify the canonical MYAH_PLUGIN_SHA pin source(s) agree.

    Two layouts:

    * Internal monorepo — pin lives in ``agent/Dockerfile.stock``;
      ``.github/workflows/deploy.yml`` extracts it via awk so the
      two cannot drift by construction. When both files exist this
      check compares the literal values for the AGENTS.md drift case.
    * Public OSS mirror — pin lives in ``versions.env`` (no Dockerfile,
      no deploy.yml). When only this file exists, report OK with the
      SHA from versions.env. Regression for PR #16 review H-4: before
      this branch the check WARN'd on every public-mirror install
      because ``agent/Dockerfile.stock`` doesn't exist there.
    """
    dockerfile_text = Path(dockerfile_path).read_text() if Path(dockerfile_path).exists() else ''
    deploy_text = Path(deploy_yml_path).read_text() if Path(deploy_yml_path).exists() else ''
    versions_text = Path(versions_env_path).read_text() if Path(versions_env_path).exists() else ''

    dockerfile_sha = _extract_sha(dockerfile_text)
    deploy_sha = _extract_sha(deploy_text)
    versions_sha = _extract_sha(versions_text)

    # Public mirror branch — versions.env is the authoritative source.
    # Hit this BEFORE the dockerfile-missing WARN below so the public
    # mirror gets an OK instead of a spurious WARN.
    if not dockerfile_sha and versions_sha:
        return CheckResult(
            name='plugin SHA pin',
            status=CheckStatus.OK,
            message=f'versions.env pins {versions_sha[:8]} (public OSS mirror layout)',
        )

    # Deploy workflow may extract the SHA from Dockerfile.stock at build time
    # (the `awk -F= '/^ARG MYAH_PLUGIN_SHA=/...` pattern) rather than carrying
    # a literal value. Per AGENTS.md, this is the canonical anti-drift design:
    # the two cannot drift by construction. Treat as OK if so.
    deploy_defers_to_dockerfile = (
        'awk' in deploy_text
        and 'MYAH_PLUGIN_SHA' in deploy_text
        and 'Dockerfile.stock' in deploy_text
    )

    if not dockerfile_sha:
        return CheckResult(
            name='plugin SHA pin',
            status=CheckStatus.WARN,
            message=f'could not extract MYAH_PLUGIN_SHA from {dockerfile_path}',
        )

    if deploy_defers_to_dockerfile and not deploy_sha:
        return CheckResult(
            name='plugin SHA pin',
            status=CheckStatus.OK,
            message=(
                f'Dockerfile pins {dockerfile_sha[:8]}; deploy.yml extracts via awk '
                f'(cannot drift by construction).'
            ),
        )

    if not deploy_sha:
        return CheckResult(
            name='plugin SHA pin',
            status=CheckStatus.WARN,
            message=f'could not extract MYAH_PLUGIN_SHA from {deploy_yml_path}',
        )

    if dockerfile_sha == deploy_sha:
        return CheckResult(
            name='plugin SHA pin',
            status=CheckStatus.OK,
            message=f'Dockerfile and deploy.yml both pin {dockerfile_sha[:8]}',
        )

    return CheckResult(
        name='plugin SHA pin',
        status=CheckStatus.WARN,
        message=(
            f'DRIFT: Dockerfile pins {dockerfile_sha[:8]}; deploy.yml pins {deploy_sha[:8]}. '
            f'Production runs the deploy.yml value.'
        ),
    )


def _extract_sha(text: str) -> str | None:
    """Extract MYAH_PLUGIN_SHA value from a Dockerfile or deploy.yml line."""
    # Match: ARG MYAH_PLUGIN_SHA=<40 hex chars>   OR   MYAH_PLUGIN_SHA=<40 hex chars>
    match = re.search(r'MYAH_PLUGIN_SHA[=\s]+([a-f0-9]{40})', text)
    return match.group(1) if match else None


def check_agent_container_env_injection(
    container_name: str = 'myah-agent-00000000-0000-0000-0000-000000000001',  # OSS seed user
) -> CheckResult:
    """Verify MYAH_PLATFORM_BASE_URL and MYAH_PLATFORM_BEARER are injected.

    Per AGENTS.md "Attachment Pipeline Invariants" #2: these MUST be in
    every per-user agent container, otherwise the agent can't fetch
    attachment content and attachments silently drop.

    Independent reviewer M3 finding: this is the production-bug-catching
    check the original spec missed.
    """
    try:
        result = run(['docker', 'exec', container_name, 'env'])
    except FileNotFoundError:
        return CheckResult(
            name='agent container env injection',
            status=CheckStatus.WARN,
            message='docker binary not found; cannot inspect agent container env.',
        )
    if result.returncode != 0:
        if _oss_platform_container_running():
            return CheckResult(
                name='agent container env injection',
                status=CheckStatus.OK,
                message='OSS mode uses host Hermes; no per-user agent container env injection is required',
            )
        # Container not running or doesn't exist — caller will see this as a
        # separate WARN from check_platform_container_running. Not our domain.
        return CheckResult(
            name='agent container env injection',
            status=CheckStatus.WARN,
            message=f'could not inspect container {container_name} (not running?)',
        )

    env_lines = set(result.stdout.splitlines())
    missing = []
    if not any(line.startswith('MYAH_PLATFORM_BASE_URL=') for line in env_lines):
        missing.append('MYAH_PLATFORM_BASE_URL')
    if not any(line.startswith('MYAH_PLATFORM_BEARER=') for line in env_lines):
        missing.append('MYAH_PLATFORM_BEARER')

    if missing:
        return CheckResult(
            name='agent container env injection',
            status=CheckStatus.WARN,
            message=(
                f'{", ".join(missing)} not injected into agent container '
                f'{container_name}. Attachments will silently fail to forward — '
                f'see AGENTS.md "Attachment Pipeline Invariants" #2 + '
                f'platform-oss/backend/myah/routers/containers.py:~616.'
            ),
        )

    return CheckResult(
        name='agent container env injection',
        status=CheckStatus.OK,
        message='MYAH_PLATFORM_BASE_URL and MYAH_PLATFORM_BEARER both present',
    )


def _oss_platform_container_running() -> bool:
    """Return True when the compose platform container is running in OSS mode."""
    result = run(['docker', 'ps', '--filter', 'label=com.docker.compose.service=platform', '-q'])
    if result.returncode != 0 or not result.stdout.strip():
        return False
    container_id = result.stdout.splitlines()[0].strip()
    if not container_id:
        return False
    env_result = run([
        'docker',
        'inspect',
        container_id,
        '--format',
        '{{range .Config.Env}}{{println .}}{{end}}',
    ])
    if env_result.returncode != 0:
        return False
    return any(line == 'MYAH_DEPLOYMENT_MODE=oss' for line in env_result.stdout.splitlines())


# The doctor checks above answer "is the running stack healthy?" — they
# return OK when a port is bound because that means the paired service is
# alive. The post-install probe below answers a different question: "did
# the install land cleanly, and is the path clear for the user to bring
# the stack up?" Same primitive (socket.bind), opposite verdict.
# Mirrors platform-oss/scripts/setup-myah-oss.sh:858-883 (the bash
# equivalent that runs during install).
_REQUIRED_PORTS: tuple[tuple[int, str], ...] = (
    (8642, 'Hermes api_server'),
    (8643, 'Hermes gateway adapter'),
    (9119, 'Hermes dashboard'),
    (8080, 'Myah platform'),
)


def probe_required_ports(*, services_started: bool = False) -> list[CheckResult]:
    """Probe the 4 ports the OSS stack expects to bind.

    Mirrors setup-myah-oss.sh:865-880. Returns one CheckResult per port
    in the documented order (8642, 8643, 9119, 8080).

    Semantics depends on ``services_started``:

    * ``services_started=False`` (default) — pre-flight semantics. Free
      → OK ('ready to bind'); in-use → WARN ('something else is bound').
      The original bash intent: detect port conflicts before the
      install actually starts the gateway/dashboard.

    * ``services_started=True`` — post-service-install semantics. Free
      → WARN (the service should be bound but isn't); in-use → OK
      (assumed bound by the expected service). Regression for PR #16
      review M-2: when ``myah install --service systemd`` starts the
      Hermes gateway + dashboard, the same probe afterward saw those
      ports as in-use and spuriously WARN'd, contradicting the
      "everything's running" reality.

    The owning-process identity is intentionally not checked here
    (would require lsof / cross-platform pid parsing). The paired
    container/service checks elsewhere validate ownership.
    """
    results: list[CheckResult] = []
    for port, service_name in _REQUIRED_PORTS:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.bind(('127.0.0.1', port))
            free = True
        except OSError:
            free = False

        if free and not services_started:
            results.append(
                CheckResult(
                    name=f'port {port}',
                    status=CheckStatus.OK,
                    message=f'port {port} is free (ready for {service_name})',
                )
            )
        elif free and services_started:
            results.append(
                CheckResult(
                    name=f'port {port}',
                    status=CheckStatus.WARN,
                    message=(
                        f'port {port} is free but {service_name} should be bound — '
                        f'check `systemctl --user status` / `launchctl list`.'
                    ),
                )
            )
        elif not free and not services_started:
            results.append(
                CheckResult(
                    name=f'port {port}',
                    status=CheckStatus.WARN,
                    message=(
                        f'port {port} is in use — {service_name} will fail to bind. '
                        f'Identify the conflict with: lsof -iTCP:{port} -sTCP:LISTEN -n -P'
                    ),
                )
            )
        else:  # in-use AND services_started → expected
            results.append(
                CheckResult(
                    name=f'port {port}',
                    status=CheckStatus.OK,
                    message=f'port {port} in use (expected: {service_name})',
                )
            )
    return results


def post_install_doctor_run(*, services_started: bool = False) -> list[CheckResult]:
    """Aggregate post-install verification: doctor checks + port probes.

    Pure orchestrator. Composes the 5 existing doctor predicates from
    this module plus `probe_required_ports()` and returns the combined
    list. Caller (`myah install`, 4f) renders the table and decides exit
    code.

    Order:
      1. check_hermes_binary_on_path
      2. check_hermes_plugin_installed
      3. check_plugin_sha_drift
      4. check_platform_container_running
      5. check_agent_container_env_injection
      6. probe_required_ports() — flattened (4 entries)

    ``services_started`` is forwarded to ``probe_required_ports``. Pass
    ``True`` when the caller has just installed systemd/launchd units
    that bind those ports — otherwise the post-install table spuriously
    WARNs on every port the install just brought up. See PR #16 review
    M-2.

    Some checks (platform_container, agent_env_injection) may WARN/FAIL
    at install time because the user hasn't run `myah platform up` yet.
    That's expected; the caller decides how to render.
    """
    results: list[CheckResult] = [
        check_hermes_binary_on_path(),
        check_hermes_plugin_installed(),
        check_plugin_sha_drift(),
        check_platform_container_running(),
        check_agent_container_env_injection(),
    ]
    results.extend(probe_required_ports(services_started=services_started))
    return results
