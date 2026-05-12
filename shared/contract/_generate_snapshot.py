"""Generate ``platform-oss/shared/contract/upstream-snapshot.json`` from a
hermes-agent source tree.

Used at submodule-decommission time (Plan B Phase 0) and on every
``HERMES_SHA`` bump (via the ``refresh-contract-snapshot.yml`` CI workflow
added in Plan B PR B).

Refactored from the inline walk logic in
``platform-oss/shared/contract/__tests__/test_contract_completeness.py``
and ``test_tasks_approvals_platforms.py``.

Usage (post-Plan-B-PR-B — the canonical state):
    # Clone upstream Hermes-Agent at the pinned SHA, then run:
    python3 platform-oss/shared/contract/_generate_snapshot.py \\
        --hermes-root /tmp/hermes \\
        --plugin-root myah-hermes-plugin \\
        --out platform-oss/shared/contract/upstream-snapshot.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Same regex as the contract tests use.
_EVENT_LITERAL_RE = re.compile(
    r"""['"]event['"]\s*:\s*['"]([\w.]+)['"]""",
    re.MULTILINE,
)

_AUX_ALLOWED_RE = re.compile(
    r'_AUX_ALLOWED_TASKS\s*=\s*frozenset\s*\(\s*\{([^}]*)\}',
    re.MULTILINE | re.DOTALL,
)
_AUX_TASK_STRING_RE = re.compile(r"['\"]([a-z_]+)['\"]")

# Platform enum discovery (test_tasks_approvals_platforms.py walks this).
_PLATFORM_ENUM_RE = re.compile(
    r'class\s+Platform\s*\(\s*str\s*,\s*Enum\s*\)\s*:(.*?)(?=\nclass|\Z)',
    re.DOTALL,
)
_PLATFORM_VALUE_RE = re.compile(r"['\"]([\w-]+)['\"]")


def discover_hermes_event_types(gateway_root: Path, plugin_root: Path | None) -> set[str]:
    """Walk Hermes gateway + plugin sources and return every emitted event name."""
    if not gateway_root.exists():
        raise SystemExit(
            f'Hermes gateway root not found: {gateway_root}',
        )

    roots: list[Path] = [gateway_root]
    if plugin_root is not None and plugin_root.exists():
        roots.append(plugin_root)

    discovered: set[str] = set()
    for root in roots:
        for py_file in root.rglob('*.py'):
            try:
                text = py_file.read_text(encoding='utf-8')
            except (OSError, UnicodeDecodeError):
                continue
            for match in _EVENT_LITERAL_RE.finditer(text):
                discovered.add(match.group(1))
    return discovered


def discover_hermes_aux_tasks(plugin_root: Path | None, hermes_root: Path) -> set[str]:
    """Find ``_AUX_ALLOWED_TASKS`` literal in the Myah adapter."""
    candidates: list[Path] = []
    if plugin_root is not None:
        candidates.append(plugin_root / 'myah_hermes_plugin' / 'myah_platform' / 'adapter.py')
    candidates.append(hermes_root / 'gateway' / 'platforms' / 'myah.py')

    for path in candidates:
        if path.exists():
            text = path.read_text(encoding='utf-8')
            match = _AUX_ALLOWED_RE.search(text)
            if match:
                return set(_AUX_TASK_STRING_RE.findall(match.group(1)))
    return set()


def discover_platform_enums(hermes_root: Path) -> set[str]:
    """Find values defined in the ``Platform`` enum in gateway/config.py."""
    config_path = hermes_root / 'gateway' / 'config.py'
    if not config_path.exists():
        return set()
    text = config_path.read_text(encoding='utf-8')
    match = _PLATFORM_ENUM_RE.search(text)
    if not match:
        return set()
    return set(_PLATFORM_VALUE_RE.findall(match.group(1)))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--hermes-root',
        type=Path,
        required=True,
        help='Path to a hermes-agent source tree (the submodule or a fresh clone)',
    )
    parser.add_argument(
        '--plugin-root',
        type=Path,
        default=None,
        help='Path to the myah-hermes-plugin source tree '
             '(default: <hermes-root>/plugins/myah-hermes-plugin if it exists)',
    )
    parser.add_argument(
        '--out',
        type=Path,
        default=None,
        help='Output JSON path (default: stdout)',
    )
    args = parser.parse_args()

    plugin_root = args.plugin_root
    if plugin_root is None:
        default_plugin = args.hermes_root / 'plugins' / 'myah-hermes-plugin'
        if default_plugin.exists():
            plugin_root = default_plugin

    gateway_root = args.hermes_root / 'gateway'
    if not gateway_root.exists():
        raise SystemExit(
            f'Gateway root not found: {gateway_root}\n'
            f'Pass --hermes-root pointing at the hermes-agent repo root.',
        )

    # Store only the event/task names — not the absolute paths the snapshot
    # was generated from. Paths embedded in the JSON would change between
    # contributors and CI runs, producing pointless diffs.
    snapshot = {
        'hermes_event_types': sorted(discover_hermes_event_types(gateway_root, plugin_root)),
        'hermes_aux_tasks': sorted(discover_hermes_aux_tasks(plugin_root, args.hermes_root)),
        'platform_enums': sorted(discover_platform_enums(args.hermes_root)),
    }

    output = json.dumps(snapshot, indent=2, sort_keys=True) + '\n'
    if args.out:
        args.out.write_text(output)
        print(f'Wrote snapshot to {args.out}', file=sys.stderr)
    else:
        sys.stdout.write(output)


if __name__ == '__main__':
    main()
