"""Contract completeness check — every Hermes-emitted symbol has a contract.

This is the single highest-value invariant in Workstream I (per the spec at
``docs/superpowers/specs/2026-04-24-workstream-i-platform-hermes-contract-design.md``
§4.1). It walks the upstream Hermes submodule source files looking for
literal event-name strings and aux-task allow-list entries, and asserts each
discovered string is present in the platform-side contract.

When this test goes red on a fresh Hermes submodule bump, the action is to
add the new event class (or aux task value) in
``platform/shared/contract/{events,enums}.py`` and the matching wire handler
in ``platform/backend/open_webui/utils/hermes_stream_handler.py``. CI red
catches the drift before it reaches production.

Discovery strategy: a conservative regex over every ``.py`` file under
``agent/hermes/gateway/`` looking for the wire literal
``"event": "X"`` or ``'event': 'X'``. The test is intentionally
over-eager — we'd rather fail on a string that turns out to be a comment
than miss a real event. Spurious matches are easy to suppress via the
``_IGNORE_EVENTS`` set if any ever appear.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path
from typing import get_args

import pytest

from shared.contract.events import HermesEvent

# ── Filesystem layout ──────────────────────────────────────────────────────
# The contract module lives at ``platform/shared/contract/``; the Hermes
# submodule lives at ``agent/hermes/`` two levels up from ``platform/``.
_REPO_ROOT = Path(__file__).resolve().parents[4]
_HERMES_GATEWAY = _REPO_ROOT / 'agent' / 'hermes' / 'gateway'
_HERMES_PLATFORMS = _HERMES_GATEWAY / 'platforms'

# Phase 4d (2026-05-04) moved the Myah platform adapter out of
# ``agent/hermes/gateway/platforms/myah.py`` into the
# ``myah-hermes-plugin`` pip package. Discovery must scan both locations
# so events the adapter emits (``secret.required``, ``secret.resolved``,
# ``tool.confirmation_required``, ``status``) and the
# ``_AUX_ALLOWED_TASKS`` literal stay covered after the move.
_MYAH_PLUGIN_ROOT = (
    _REPO_ROOT
    / 'agent'
    / 'hermes'
    / 'plugins'
    / 'myah-hermes-plugin'
    / 'myah_hermes_plugin'
)
_MYAH_PLUGIN_ADAPTER = _MYAH_PLUGIN_ROOT / 'myah_platform' / 'adapter.py'

# ── Discovery regex ────────────────────────────────────────────────────────
# Matches ``"event": "name.with.dots"`` and ``'event': 'name.with.dots'``.
# The ``[\w.]+`` allows alphanumerics, underscores and dots — Hermes's
# vocabulary today (``message.delta``, ``tool.confirmation_required``,
# ``run.failed``, etc.). Update this if upstream introduces more exotic
# event names.
_EVENT_LITERAL_RE = re.compile(
    r"""['"]event['"]\s*:\s*['"]([\w.]+)['"]""",
    re.MULTILINE,
)

# Spurious matches go here. None today — kept as a documented escape hatch
# for the future.
_IGNORE_EVENTS: frozenset[str] = frozenset()


def _discover_hermes_event_types() -> set[str]:
    """Walk the Hermes gateway sources and return every emitted event name.

    The conservative grep approach beats AST parsing because Hermes emits
    events from many sites with slightly different surrounding code (some
    inline ``json.dumps``, some using ``_push_event*`` helpers, some
    string-templated). A regex catches them all.

    After Phase 4d (2026-05-04) the Myah adapter — which emits
    ``secret.required``, ``secret.resolved``, ``tool.confirmation_required``,
    and ``status`` — lives in the ``myah-hermes-plugin`` package. The walk
    therefore covers both the gateway and the plugin source roots.
    """
    if not _HERMES_GATEWAY.exists():
        pytest.skip(
            'Hermes submodule not initialised at '
            f'{_HERMES_GATEWAY} — run `git submodule update --init`',
        )

    roots: list[Path] = [_HERMES_GATEWAY]
    if _MYAH_PLUGIN_ROOT.exists():
        roots.append(_MYAH_PLUGIN_ROOT)

    discovered: set[str] = set()
    for root in roots:
        for py_file in root.rglob('*.py'):
            try:
                text = py_file.read_text(encoding='utf-8')
            except (OSError, UnicodeDecodeError):
                # Don't fail the test for an unreadable file — log and continue.
                # This pathology has not been observed but the safety net is cheap.
                continue
            for match in _EVENT_LITERAL_RE.finditer(text):
                discovered.add(match.group(1))
    return discovered - _IGNORE_EVENTS


def _contract_event_literals() -> set[str]:
    """Return the set of ``event`` literal values declared in the contract.

    Walks the discriminated union :data:`HermesEvent` and pulls each
    constituent class's ``event`` field literal value. The ``HermesEvent``
    type is ``Annotated[Union[...], Field(discriminator='event')]``, so
    ``get_args`` returns ``(Union[Class1, Class2, ...], Field(...))``.
    """
    annotated_args = get_args(HermesEvent)
    union_type = annotated_args[0]
    event_classes = get_args(union_type)
    literals: set[str] = set()
    for cls in event_classes:
        annotation = cls.model_fields['event'].annotation
        # ``annotation`` is ``Literal["message.delta"]``; ``get_args``
        # returns ``("message.delta",)``.
        for value in get_args(annotation):
            if isinstance(value, str):
                literals.add(value)
    return literals


# ── Tests ───────────────────────────────────────────────────────────────────


def test_every_hermes_event_is_in_the_contract() -> None:
    """Every event the Hermes gateway emits has a matching contract class.

    Failure here means the platform's stream handler will receive an event
    type the typed-validation gate at ``hermes_stream_handler.py:358``
    rejects with a warning — and the user-visible feature behind that
    event will silently degrade. Add the missing event class to
    ``shared/contract/events.py`` and a dispatch branch to the handler.
    """
    discovered = _discover_hermes_event_types()
    contract = _contract_event_literals()
    missing = discovered - contract
    assert not missing, (
        f'Hermes emits these event types not in the contract: {sorted(missing)}. '
        f'Add the new ``BaseModel`` subclass(es) to '
        f'``platform/shared/contract/events.py``, append to ``HermesEvent`` '
        f'union, then re-run ``bash platform/scripts/generate-ts-contract.sh``.'
    )


def test_contract_does_not_invent_events() -> None:
    """The contract may not declare event types Hermes never emits.

    A contract-only event would silently bake a non-existent string into
    the frontend's exhaustive switches and fail to catch the moment when
    the assumption changes.
    """
    discovered = _discover_hermes_event_types()
    contract = _contract_event_literals()
    invented = contract - discovered
    assert not invented, (
        f"Contract declares these event types Hermes doesn't emit: {sorted(invented)}. "
        f'Either the upstream emitter was removed (delete the contract entry) '
        f'or the discovery regex needs widening.'
    )


def test_at_least_one_hermes_event_was_discovered() -> None:
    """Sanity check: the discovery regex actually finds something.

    A silent regression in the regex (or an unexpected refactor of how
    Hermes emits events) would mask drift forever. Insist on a non-empty
    discovery set so any future refactor surfaces here.
    """
    discovered = _discover_hermes_event_types()
    assert len(discovered) >= 5, (
        f'Hermes event discovery regex found only {len(discovered)} events — '
        f'something is wrong with the regex or the submodule layout. '
        f'Discovered: {sorted(discovered)}'
    )


# ── Aux task coverage (Phase 3 cross-check, gracefully skipped if absent) ──
#
# Phase 3 of Workstream I introduces ``shared.contract.enums.AuxTask`` and
# ``AUX_ALLOWED_TASKS``. Phase 5 (this file) was authored before Phase 3
# landed, so the test below uses ``pytest.importorskip`` to handle the
# pre-Phase-3 state without failing CI.


_AUX_ALLOWED_RE = re.compile(
    r'_AUX_ALLOWED_TASKS\s*=\s*frozenset\s*\(\s*\{([^}]*)\}',
    re.MULTILINE | re.DOTALL,
)
_AUX_TASK_STRING_RE = re.compile(r"['\"]([a-z_]+)['\"]")


def _discover_hermes_aux_tasks() -> set[str]:
    """Parse the ``_AUX_ALLOWED_TASKS`` frozenset from the Myah adapter.

    Source: ``agent/hermes/plugins/myah-hermes-plugin/myah_hermes_plugin/
    myah_platform/adapter.py`` — a literal ``frozenset({...})`` block.
    Phase 4d (2026-05-04) moved the adapter out of
    ``agent/hermes/gateway/platforms/myah.py`` into the plugin package; the
    pre-Phase-4d location is checked as a fallback so this test stays
    correct on older submodule pointers.

    The contents are extracted textually rather than importing Hermes
    Python (which would require its own dependency tree on every CI run).
    """
    candidate_paths = (_MYAH_PLUGIN_ADAPTER, _HERMES_PLATFORMS / 'myah.py')
    adapter_path = next((p for p in candidate_paths if p.exists()), None)
    if adapter_path is None:
        pytest.skip(
            'Myah adapter source not found — checked '
            f'{candidate_paths}. Hermes submodule may not be initialised.',
        )
    text = adapter_path.read_text(encoding='utf-8')
    match = _AUX_ALLOWED_RE.search(text)
    if not match:
        pytest.skip(
            '_AUX_ALLOWED_TASKS literal not found in '
            f'{adapter_path} — upstream may have refactored the structure. '
            'Update the discovery regex when that happens.',
        )
    inner = match.group(1)
    return set(_AUX_TASK_STRING_RE.findall(inner))


def test_every_hermes_aux_task_is_in_the_contract() -> None:
    """Every aux task Hermes accepts has an enum entry on the platform side.

    Skipped until Phase 3 ships ``AuxTask`` and ``AUX_ALLOWED_TASKS``; once
    they exist this test guarantees the cross-tier allow-list cannot drift.
    """
    enums_module = pytest.importorskip(
        'shared.contract.enums',
        reason='Phase 3 contract enums not yet present',
    )
    aux_task_enum = getattr(enums_module, 'AuxTask', None)
    if aux_task_enum is None:
        pytest.skip('Phase 3 AuxTask enum not yet present in shared.contract.enums')
    discovered = _discover_hermes_aux_tasks()
    contract = {member.value for member in aux_task_enum}
    missing = discovered - contract
    assert not missing, (
        f'Hermes allows these aux tasks not in the contract: {sorted(missing)}. '
        f'Add them to ``AuxTask`` in ``platform/shared/contract/enums.py``.'
    )
    invented = contract - discovered
    assert not invented, (
        f"Contract declares these aux tasks Hermes doesn't accept: {sorted(invented)}. "
        f'Remove them or update the upstream allow-list.'
    )


# ── Tooling: helper to debug locally ────────────────────────────────────────


def _summarise() -> dict[str, Iterable[str]]:
    """Convenience helper — invoked manually, not by pytest.

    Run with: ``cd platform && .venv/bin/python -c
    "from shared.contract.__tests__.test_contract_completeness import _summarise; print(_summarise())"``
    """
    return {
        'discovered_events': sorted(_discover_hermes_event_types()),
        'contract_events': sorted(_contract_event_literals()),
    }
