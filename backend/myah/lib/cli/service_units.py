"""Service-unit install + legacy migration for `myah install` (Slice 4 sub-phase 4d).

Library-only — no CLI command yet. Sub-phase 4f wires `myah install`
end-to-end. This module replaces phase 7 of the bash at
``platform-oss/scripts/setup-myah-oss.sh`` (lines 569-856) — the
systemd-user / launchd plist install, legacy plist+unit migration,
and stale-process cleanup that the bash performs before handing the
running services over to the OS supervisor.

Closes R10 (template path-resolution drift in the bash). The bash
walked a `$ROOT/scripts/oss-service-templates/<name>.in` string that
only resolved cleanly under the public OSS repo's flat layout. Here we
bundle the templates inside the wheel under ``myah/cli/templates/`` and
load them via ``importlib.resources.files('myah.cli') / 'templates'`` —
no runtime path-walks, works identically from a source checkout and
an installed wheel.

Cold-start budget: all helpers stay in stdlib (importlib.resources,
shutil, os, time, datetime, subprocess via shell.run). No Rich,
PyYAML, Typer, etc. at module top. The structural sentinel test
``test_module_does_not_import_heavy_libs_at_top_level`` enforces this.
"""

from __future__ import annotations

import datetime as dt
import importlib.resources
import os
import shutil
import time
from pathlib import Path

from loguru import logger

from myah.lib.cli.shell import ShellError, run

# Process patterns to clean up before handing over to systemctl/launchctl.
# Mirrors setup-myah-oss.sh:602 / :613. The trailing escaped dot in
# 'hermes_cli\\.main' is preserved verbatim because pgrep -f treats the
# pattern as a regex against the full argv string.
_STALE_PROCESS_PATTERNS = ('hermes dashboard', 'hermes gateway', r'hermes_cli\.main')

# Legacy LaunchAgent label prefixes that pre-date the dev.myah.* convention.
# Mirrors setup-myah-oss.sh:719.
_LEGACY_LAUNCHAGENT_GLOBS = ('com.nous-research.hermes.*.plist', 'com.myah.*.plist')

# Legacy systemd-user unit names. The bash only checks `myah-platform` —
# everything else (hermes-gateway / hermes-dashboard) is overwritten in
# place by daemon-reload + enable --now. Mirrors setup-myah-oss.sh:759.
_LEGACY_SYSTEMD_UNITS = ('myah-platform',)


def _launch_agents_dir() -> Path:
    """Return ~/Library/LaunchAgents. Factored out for monkeypatching."""
    return Path.home() / 'Library' / 'LaunchAgents'


def _systemd_user_dir() -> Path:
    """Return ~/.config/systemd/user. Factored out for monkeypatching."""
    return Path.home() / '.config' / 'systemd' / 'user'


def _validate_hermes_bin(hermes_bin: str | None) -> str:
    """Reject empty/None hermes_bin with a clear error.

    Empty hermes_bin would render templates with literal `__HERMES_BIN__`
    or empty `ExecStart=` lines — the supervisor would launch nothing
    and silently fail forever. Better to crash loudly here.
    """
    if not hermes_bin:
        raise ValueError(
            'hermes_bin must be the absolute path to the hermes binary '
            '(e.g. /usr/local/bin/hermes); got empty/None'
        )
    return hermes_bin


def _get_template_text(template_name: str) -> str:
    """Return raw template text from the bundled templates dir.

    Uses ``importlib.resources.files('myah.cli') / 'templates' / <name>``
    so the loader works identically against an editable install (on-disk
    file) and a built wheel (zip-internal resource).

    Closes R10 (template path-resolution drift in the bash) — the
    bundled-in-wheel approach means no string-based ROOT walks at runtime.

    Raises ``FileNotFoundError`` if the template name does not exist
    inside the templates dir.
    """
    templates_dir = importlib.resources.files('myah.cli') / 'templates'
    template = templates_dir / template_name
    if not template.is_file():
        raise FileNotFoundError(
            f'Template {template_name!r} not found under myah/cli/templates/'
        )
    return template.read_text(encoding='utf-8')


def render_template(template_name: str, *, hermes_bin: str, hermes_home: Path) -> str:
    """Substitute ``__HERMES_BIN__`` and ``__HERMES_HOME__`` markers in a template.

    Mirrors the bash sed substitution at setup-myah-oss.sh:793-794 and
    :828-829 (two `-e` calls, replaceAll semantics). Returns the rendered
    file content as a string. Does NOT write to disk — callers compose
    the destination path and write the result themselves.

    Validates hermes_bin (must be non-empty). hermes_home is coerced to
    its string form for substitution.

    Known limitation (mirrors bash setup-myah-oss.sh:793-794): the systemd
    template renders ``Environment=HERMES_HOME=__HERMES_HOME__`` without
    quoting. If ``hermes_home`` contains a space, ``=``, or ``\\n``, the
    resulting unit file's ``Environment=`` line breaks silently. Callers
    must pass a hermes_home path that contains only filesystem-safe
    characters. A future hardening could validate this in
    ``_validate_hermes_bin``-style; deferred so we ship 4d with bash
    behavioral parity.
    """
    _validate_hermes_bin(hermes_bin)
    text = _get_template_text(template_name)
    return text.replace('__HERMES_BIN__', hermes_bin).replace('__HERMES_HOME__', str(hermes_home))


def _pgrep_kill_pass(signal: str, *, count: bool) -> int:
    """One pass of pgrep + kill across :data:`_STALE_PROCESS_PATTERNS`.

    For each pattern, ``pgrep -f`` matches process argv; matched PIDs
    (excluding our own) are signalled via ``kill <signal> <pid>``. Returns
    the count of successful kills (returncode 0) when ``count=True``;
    otherwise returns 0 (best-effort SIGKILL pass discards results).

    ``pgrep`` returncode 1 = no matches; treated as no-op. Malformed PID
    output is silently skipped (defensive against pgrep output format
    drift).
    """
    killed = 0
    own_pid = os.getpid()
    for pattern in _STALE_PROCESS_PATTERNS:
        result = run(['pgrep', '-f', pattern])
        if result.returncode == 1 or not result.stdout.strip():
            continue
        for raw_pid in result.stdout.split():
            try:
                pid = int(raw_pid.strip())
            except ValueError:
                continue
            if pid == own_pid:
                continue
            r = run(['kill', signal, str(pid)])
            if count and r.returncode == 0:
                killed += 1
    return killed


def stop_stale_hermes_processes() -> int:
    """SIGTERM + (after 1s) SIGKILL any running hermes dashboard/gateway/cli.

    Mirrors setup-myah-oss.sh:599-622. Patterns matched via ``pgrep -f``:

      - ``hermes dashboard``
      - ``hermes gateway``
      - ``hermes_cli\\.main``

    Two passes:

      1. SIGTERM every matched PID (excluding our own pid).
      2. If anything was killed in pass 1, sleep 1s, then SIGKILL anything
         still alive.

    Returns the count of processes that received SIGTERM in pass 1.

    ``pgrep`` returning no matches (returncode 1) is treated as "nothing
    to kill" — NOT an error. If ``pgrep`` is missing entirely (Linux
    without procps-ng installed) the function returns 0 silently —
    install can still proceed; the worst case is a stale process races
    the new one for a port.

    Linux + macOS only. pgrep + kill are both standard there.
    """
    if shutil.which('pgrep') is None:
        logger.info('pgrep not on PATH — skipping stale-process cleanup')
        return 0

    killed = _pgrep_kill_pass('-TERM', count=True)
    if killed > 0:
        time.sleep(1)
        _pgrep_kill_pass('-9', count=False)
        logger.warning(f'stopped {killed} pre-existing hermes process(es) to ensure clean service start')

    return killed


def migrate_legacy_launchagents() -> int:
    """Detect + retire pre-existing LaunchAgent plists from earlier installs.

    Mirrors setup-myah-oss.sh:712-742. Looks in ``~/Library/LaunchAgents``
    for two glob patterns:

      - ``com.nous-research.hermes.*.plist``
      - ``com.myah.*.plist``

    Deliberately does NOT touch ``dev.myah.*`` — that's the current label
    convention and :func:`install_launchd_plists` owns it (overwrites in
    place).

    For each legacy plist found:

      1. ``launchctl bootout gui/$UID/<label>`` (modern), falling back to
         ``launchctl unload <path>`` (older macOS). Both tolerated to fail.
      2. Rename ``<plist>`` → ``<plist>.bak.<timestamp>``.

    Returns count of plists migrated. 0 if ``~/Library/LaunchAgents``
    does not exist (Linux) or no legacy plists are found.

    Timestamp format: ``%Y%m%d_%H%M%S`` (e.g. ``20260526_143015``).
    """
    agents_dir = _launch_agents_dir()
    if not agents_dir.is_dir():
        return 0

    found: list[Path] = []
    for glob in _LEGACY_LAUNCHAGENT_GLOBS:
        found.extend(sorted(agents_dir.glob(glob)))

    if not found:
        return 0

    logger.warning(f'detected {len(found)} legacy LaunchAgent plist(s); migrating')
    timestamp = dt.datetime.now().strftime('%Y%m%d_%H%M%S')
    uid = os.getuid()

    for plist in found:
        label = plist.stem  # strips .plist
        logger.info(f'unloading legacy LaunchAgent {label}')
        bootout = run(['launchctl', 'bootout', f'gui/{uid}/{label}'])
        if bootout.returncode != 0:
            # Older macOS: fall back to `launchctl unload <path>`.
            run(['launchctl', 'unload', str(plist)])
        backup = plist.with_name(f'{plist.name}.bak.{timestamp}')
        logger.info(f'renaming {plist} -> {backup}')
        plist.rename(backup)

    return len(found)


def migrate_legacy_systemd_units() -> int:
    """Detect + mask pre-existing systemd-user units that aren't part of
    the canonical Myah/Hermes set.

    Mirrors setup-myah-oss.sh:754-774. Looks for ``myah-platform.service``
    (an older pattern where the platform was a systemd-user unit instead
    of docker compose).

    Does NOT touch ``hermes-gateway`` / ``hermes-dashboard`` — those are
    re-installed by :func:`install_systemd_user_units` and overwrite
    cleanly via daemon-reload.

    For each legacy unit found:

      1. ``systemctl --user stop <unit>.service``
      2. ``systemctl --user disable <unit>.service``
      3. ``systemctl --user mask <unit>.service``

    All three calls tolerate failure (``|| true`` equivalent).

    Returns count of units masked. 0 if systemctl is unavailable (macOS)
    or no legacy units are found.
    """
    if shutil.which('systemctl') is None:
        return 0

    found: list[str] = []
    for unit in _LEGACY_SYSTEMD_UNITS:
        result = run(['systemctl', '--user', 'list-unit-files', f'{unit}.service'])
        # `list-unit-files` returns 0 even when no match; the unit name
        # appearing in stdout is the actual signal. Mirrors the bash's
        # `grep -q "${unit}.service"` at line 760.
        if f'{unit}.service' in result.stdout:
            found.append(unit)

    if not found:
        return 0

    logger.warning(f'detected {len(found)} legacy systemd unit(s); migrating')
    for unit in found:
        logger.info(f'stopping + disabling + masking {unit}')
        run(['systemctl', '--user', 'stop', f'{unit}.service'])
        run(['systemctl', '--user', 'disable', f'{unit}.service'])
        run(['systemctl', '--user', 'mask', f'{unit}.service'])

    return len(found)


def install_systemd_user_units(hermes_bin: str, hermes_home: Path) -> None:
    """Render + install hermes-{gateway,dashboard}.service systemd-user units.

    Mirrors setup-myah-oss.sh:776-807.

    Flow:

      1. :func:`migrate_legacy_systemd_units`
      2. :func:`stop_stale_hermes_processes`
      3. ``mkdir -p ~/.config/systemd/user``
      4. For each unit in ('hermes-gateway', 'hermes-dashboard'):

         - Render ``{unit}.service.in`` with the supplied hermes_bin +
           hermes_home.
         - Write to ``~/.config/systemd/user/{unit}.service``.
         - ``systemctl --user enable --now {unit}.service`` (check=True).

    Raises :class:`ShellError` if a systemctl invocation fails (caller
    decides whether to surface or wrap). Raises :class:`ValueError` if
    hermes_bin is empty or None.
    """
    _validate_hermes_bin(hermes_bin)
    migrate_legacy_systemd_units()
    stop_stale_hermes_processes()

    unit_dir = _systemd_user_dir()
    unit_dir.mkdir(parents=True, exist_ok=True)

    for unit in ('hermes-gateway', 'hermes-dashboard'):
        rendered = render_template(f'{unit}.service.in', hermes_bin=hermes_bin, hermes_home=hermes_home)
        dest = unit_dir / f'{unit}.service'
        dest.write_text(rendered, encoding='utf-8')
        logger.info(f'wrote systemd-user unit {dest}')
        run(['systemctl', '--user', 'enable', '--now', f'{unit}.service'], check=True)

    logger.info('systemd-user units installed: hermes-gateway, hermes-dashboard')


def install_launchd_plists(hermes_bin: str, hermes_home: Path) -> None:
    """Render + install dev.myah.hermes-{gateway,dashboard}.plist launchd files.

    Mirrors setup-myah-oss.sh:809-849.

    Flow:

      1. :func:`migrate_legacy_launchagents`
      2. :func:`stop_stale_hermes_processes`
      3. ``mkdir -p ~/Library/LaunchAgents``
      4. ``mkdir -p hermes_home/logs`` (launchd writes stdout/stderr there)
      5. For each service in ('dev.myah.hermes-gateway', 'dev.myah.hermes-dashboard'):

         - Render ``{service}.plist.in`` with the supplied hermes_bin +
           hermes_home.
         - Write to ``~/Library/LaunchAgents/{service}.plist``.
         - ``launchctl bootout gui/$UID/{service}`` (tolerate failure —
           service may not have been loaded before).
         - ``launchctl bootstrap gui/$UID {plist_path}``; on failure fall
           back to ``launchctl load {plist_path}`` (older launchctl).

    Raises :class:`ShellError` if BOTH bootstrap AND load fail (the load
    fallback is invoked with check=True). Raises :class:`ValueError` if
    hermes_bin is empty or None.

    Note: bootout failures are SILENT (the service may not have been
    loaded before — that's not an error condition).
    """
    _validate_hermes_bin(hermes_bin)
    migrate_legacy_launchagents()
    stop_stale_hermes_processes()

    plist_dir = _launch_agents_dir()
    plist_dir.mkdir(parents=True, exist_ok=True)
    (hermes_home / 'logs').mkdir(parents=True, exist_ok=True)

    uid = os.getuid()

    for service in ('dev.myah.hermes-gateway', 'dev.myah.hermes-dashboard'):
        rendered = render_template(f'{service}.plist.in', hermes_bin=hermes_bin, hermes_home=hermes_home)
        plist_path = plist_dir / f'{service}.plist'
        plist_path.write_text(rendered, encoding='utf-8')
        logger.info(f'wrote launchd plist {plist_path}')

        # Bootout silently — service may not have been loaded before.
        run(['launchctl', 'bootout', f'gui/{uid}/{service}'])

        bootstrap = run(['launchctl', 'bootstrap', f'gui/{uid}', str(plist_path)])
        if bootstrap.returncode != 0:
            # Older launchctl: fall back to `load`. This one MUST succeed
            # (check=True) — otherwise the service is not registered at
            # all and the install silently fails.
            try:
                run(['launchctl', 'load', str(plist_path)], check=True)
            except ShellError:
                logger.error(f'failed to bootstrap or load launchd plist {plist_path}')
                raise

    logger.info('launchd plists installed: dev.myah.hermes-{gateway,dashboard}')


__all__ = [
    'install_launchd_plists',
    'install_systemd_user_units',
    'migrate_legacy_launchagents',
    'migrate_legacy_systemd_units',
    'render_template',
    'stop_stale_hermes_processes',
]
