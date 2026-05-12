"""Tests for the _resolve_aux_default helper in open_webui.config.

Isolation note: This module uses a deferred import pattern to avoid caching
the real 'open_webui.config' in sys.modules at collection time. The
test_agent_config.py module (in a sibling directory) loads agent_config.py
via importlib with a stubbed 'open_webui.config'. If the real module is
already in sys.modules when that stub is injected, the stub is ignored.

By deferring the import inside _get_resolver() and cleaning up via the
autouse fixture, we ensure both test files can coexist in the same pytest
session regardless of execution order.
"""
import sys

import pytest


@pytest.fixture(autouse=True)
def _isolate_openwebui_modules():
    """Clean open_webui.* from sys.modules before and after each test."""
    to_remove = [k for k in sys.modules if k.startswith('open_webui')]
    for key in to_remove:
        sys.modules.pop(key, None)
    yield
    to_remove = [k for k in sys.modules if k.startswith('open_webui')]
    for key in to_remove:
        sys.modules.pop(key, None)


def _get_resolver():
    import importlib
    mod = importlib.import_module('open_webui.config')
    return mod._resolve_aux_default


def test_resolve_aux_default_non_specialized_task():
    resolve = _get_resolver()
    result = resolve('openrouter', 'title_generation', catalog={'openrouter': ['google/gemini-3-flash-preview']})
    assert result == 'google/gemini-3-flash-preview'


def test_resolve_aux_default_vision_exact_match():
    resolve = _get_resolver()
    result = resolve('zai', 'vision', catalog={'zai': ['glm-5v-turbo', 'glm-4.5-flash']})
    assert result == 'glm-5v-turbo'


def test_resolve_aux_default_vision_incapable_returns_none():
    resolve = _get_resolver()
    result = resolve('deepseek', 'vision', catalog={'deepseek': ['deepseek-chat']})
    assert result is None


def test_resolve_aux_default_vision_falls_through_to_default():
    resolve = _get_resolver()
    result = resolve('anthropic', 'vision', catalog={'anthropic': ['claude-haiku-4-5-20251001']})
    assert result == 'claude-haiku-4-5-20251001'


def test_resolve_aux_default_unknown_provider():
    resolve = _get_resolver()
    result = resolve('atlantis', 'title_generation', catalog={})
    assert result is None


def test_resolve_aux_default_unknown_task():
    resolve = _get_resolver()
    result = resolve('openrouter', 'research', catalog={'openrouter': ['x']})
    assert result is None


def test_resolve_aux_default_membership_guard_falls_back_to_first_catalog_entry():
    resolve = _get_resolver()
    result = resolve('openrouter', 'title_generation', catalog={'openrouter': ['anthropic/claude-opus']})
    assert result == 'anthropic/claude-opus'


def test_resolve_aux_default_membership_guard_returns_none_on_empty_catalog():
    resolve = _get_resolver()
    result = resolve('openrouter', 'title_generation', catalog={'openrouter': []})
    assert result is None


def test_resolve_aux_default_no_catalog_skips_guard():
    resolve = _get_resolver()
    result = resolve('openrouter', 'title_generation', catalog=None)
    assert result == 'google/gemini-3-flash-preview'
