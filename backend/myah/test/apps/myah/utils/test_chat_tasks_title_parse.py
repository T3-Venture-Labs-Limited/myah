# Tests for the title-parse layer introduced in PR 1b.
#
# Covers:
#   _looks_invalid_title  — Task 1 helper
#   _sanitize_title       — Task 2 forgiving sanitizer

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest


# ---------------------------------------------------------------------------
# Minimal stub harness — mirrors test_tasks_aux_routing.py pattern
# ---------------------------------------------------------------------------

def _load_chat_tasks_module():
    """Load chat_tasks.py with its heavy dependencies stubbed out."""

    def _make(name, **attrs):
        m = ModuleType(name)
        for k, v in attrs.items():
            setattr(m, k, v)
        return m

    mods = {
        'myah.constants': _make(
            'myah.constants',
            TASKS=SimpleNamespace(
                TITLE_GENERATION='title_generation',
                FOLLOW_UP_GENERATION='follow_up_generation',
            ),
        ),
        'myah.models.chats': _make(
            'myah.models.chats',
            Chats=SimpleNamespace(
                get_messages_map_by_chat_id=lambda *a, **kw: {},
                update_chat_title_by_id=lambda *a, **kw: None,
                upsert_message_to_chat_by_id_and_message_id=lambda *a, **kw: None,
            ),
        ),
        'myah.socket.main': _make(
            'myah.socket.main',
            get_event_call=lambda *a, **kw: None,
            get_event_emitter=lambda *a, **kw: None,
        ),
        'myah.routers.tasks': _make(
            'myah.routers.tasks',
            _fetch_title_via_aux=None,
            _fetch_follow_ups_via_aux=None,
            _UNSET=object(),  # sentinel — just needs to be a unique object
        ),
        'myah.utils.misc': _make(
            'myah.utils.misc',
            get_message_list=lambda *a, **kw: [],
            get_last_user_message=lambda *a, **kw: '',
            get_last_user_message_item=lambda *a, **kw: None,
        ),
    }

    for name, mod in mods.items():
        sys.modules.setdefault(name, mod)

    chat_tasks_path = (
        Path(__file__).resolve().parent.parent.parent.parent.parent
        / 'utils'
        / 'chat_tasks.py'
    )
    spec = importlib.util.spec_from_file_location('myah.utils.chat_tasks', chat_tasks_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules['myah.utils.chat_tasks'] = module
    spec.loader.exec_module(module)
    module._stub_keys = list(mods.keys()) + ['myah.utils.chat_tasks']
    return module


@pytest.fixture(scope='module')
def chat_tasks_mod():
    return _load_chat_tasks_module()


# ---------------------------------------------------------------------------
# Task 1: _looks_invalid_title
# ---------------------------------------------------------------------------

_SHOULD_REJECT = [
    # LLM acknowledgements
    'ok',
    'Ok',
    'OK, done',
    'done',
    'Done',
    'all set',
    # Chinese reasoning leaks
    '测试完成',
    '完成',
    '用户',
    # Reasoning preamble — "the user …"
    'The user is asking about weather',
    'The user wants to know X',
    # LLM first-person phrases
    'Let me think about this',
    "I'll generate a title",
    'I will create',
    # "Sure / Here is …" openings
    'Sure, here is the title:',
    'Here is your title',
    "Here's the title",
    # Empty / whitespace / too short
    '',
    ' ',
    'x',
]

_SHOULD_ACCEPT = [
    # Real titles with emoji
    '📉 Stock Market Trends',
    '🍪 Perfect Chocolate Chip Recipe',
    # "user" as a non-prefix word is fine
    'User Research Insights',
    # "Okra" starts with "Ok" but is a real word — word-boundary match must pass it
    'Okra Recipe Recommendations',
    # "Done and dusted" — "done" followed by non-word char should still be rejected
    # BUT per spec: "Done and dusted: chapter review" should ACCEPT.
    # Resolution: spec says err toward accepting on borderlines — accept it.
    'Done and dusted: chapter review',
    # Normal multi-word titles
    'Machine Learning Basics',
    'How to Cook Pasta',
    'Python Async Programming',
]


@pytest.mark.parametrize('title', _SHOULD_REJECT)
def test_looks_invalid_title_rejects(chat_tasks_mod, title):
    assert chat_tasks_mod._looks_invalid_title(title) is True, (
        f'Expected _looks_invalid_title({title!r}) to return True (reject), but it returned False'
    )


@pytest.mark.parametrize('title', _SHOULD_ACCEPT)
def test_looks_invalid_title_accepts(chat_tasks_mod, title):
    assert chat_tasks_mod._looks_invalid_title(title) is False, (
        f'Expected _looks_invalid_title({title!r}) to return False (accept), but it returned True'
    )


# ---------------------------------------------------------------------------
# Task 2: _sanitize_title
# ---------------------------------------------------------------------------

_SANITIZE_CASES = [
    # JSON path — extract and use title value
    ('{"title": "Hello World"}', 'Hello World'),
    # JSON embedded in prose — find/rfind slice still extracts it
    ('Here is the JSON: {"title": "Neat Title"} thanks.', 'Neat Title'),
    # Plain text — returned as-is after strip
    ('The Great Debate', 'The Great Debate'),
    # Surrounding double quotes stripped
    ('"The Great Debate"', 'The Great Debate'),
    # Surrounding single quotes stripped
    ("'Single-Quoted Title'", 'Single-Quoted Title'),
    # "Title:" prefix dropped
    ('Title: Session on Recipes', 'Session on Recipes'),
    # lowercase "title:" also dropped
    ('title: Lowercase Prefix', 'Lowercase Prefix'),
    # 100-char string truncated to 77 + '...'
    ('A' * 100, 'A' * 77 + '...'),
    # Padded whitespace stripped
    ('  Padded  ', 'Padded'),
    # Empty string → None
    ('', None),
    # 'ok' passes through strip/prefix — then _looks_invalid_title → None
    ('ok', None),
    # Reasoning preamble → None
    ('The user is asking for a summary', None),
    # "Sure, here is..." — no Title: prefix applies, full string fails invalidity check → None
    ('Sure, here is the title: "My Chat"', None),
    # Regression 2026-04-22: pure JSON envelope with empty title must reject,
    # NOT fall through to plain-text where `{"title": ""}` leaked as the title.
    ('{"title": ""}', None),
    ('{"title": "   "}', None),
    ('{"title": null}', None),
    ('{}', None),
    # Pure JSON envelope without a title key → reject
    ('{"foo": "bar"}', None),
    # Malformed pure JSON envelope → reject (not fall through to plain-text)
    ('{malformed', None),
    ('{"title": broken', None),
    # Whitespace-padded JSON envelope still counts as pure envelope
    ('  {"title": ""}  ', None),
    ('\n{"title": ""}\n', None),
]


@pytest.mark.parametrize('raw,expected', _SANITIZE_CASES)
def test_sanitize_title(chat_tasks_mod, raw, expected):
    result = chat_tasks_mod._sanitize_title(raw)
    assert result == expected, f'_sanitize_title({raw!r}) returned {result!r}, expected {expected!r}'
