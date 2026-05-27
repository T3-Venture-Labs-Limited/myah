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
    if result.returncode == 0 and 'myah-hermes-plugin' in result.stdout:
        # Try to extract version
        match = re.search(r'myah-hermes-plugin\s+(\S+)', result.stdout)
        version = match.group(1) if match else 'unknown'
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
        result = run(
            [
                'docker',
                'ps',
                '--filter',
                'name=myah-platform',
                '--format',
                '{{.ID}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}\t{{.Names}}',
            ]
        )
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
    if 'myah-platform' in result.stdout:
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
) -> CheckResult:
    """Verify Dockerfile.stock and deploy.yml pin the same MYAH_PLUGIN_SHA.

    Documented drift case per AGENTS.md: deploy.yml's build-arg can
    override the Dockerfile's ARG. When they diverge, production runs
    a different plugin SHA than the Dockerfile claims.
    """
    dockerfile_text = Path(dockerfile_path).read_text() if Path(dockerfile_path).exists() else ''
    deploy_text = Path(deploy_yml_path).read_text() if Path(deploy_yml_path).exists() else ''

    dockerfile_sha = _extract_sha(dockerfile_text)
    deploy_sha = _extract_sha(deploy_text)

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


def probe_required_ports() -> list[CheckResult]:
    """Probe the 4 ports the OSS stack expects to bind.

    Mirrors setup-myah-oss.sh:865-880. Returns one CheckResult per port
    in the documented order (8642, 8643, 9119, 8080).

    Semantics: WARN-on-in-use (NOT OK-on-in-use like check_port_for_service).
    The intent matches the bash script's intent: this runs right after
    install and is used to detect "something else is bound to a port the
    user will soon try to bind for the OSS stack." Free → OK. In-use →
    WARN with a hint to lsof.
    """
    results: list[CheckResult] = []
    for port, service_name in _REQUIRED_PORTS:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.bind(('127.0.0.1', port))
            results.append(
                CheckResult(
                    name=f'port {port}',
                    status=CheckStatus.OK,
                    message=f'port {port} is free (ready for {service_name})',
                )
            )
        except OSError:
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
    return results


def post_install_doctor_run() -> list[CheckResult]:
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
    results.extend(probe_required_ports())
    return results
