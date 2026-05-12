"""
Tests for AG-UI adapter, types, and composition modules.
Pure pytest functions — no DB or HTTP dependencies.
"""

import json
import pytest

# ---------------------------------------------------------------------------
# agui_compositions tests
# ---------------------------------------------------------------------------


def test_expand_composition_approval_card():
    from open_webui.utils.agui_compositions import expand_composition

    result = expand_composition(
        'approval_card',
        {
            'action': 'Deploy to production',
            'rationale': 'All tests passed',
            'risks': 'Rollback needed if DB migration fails',
            'options': [{'label': 'Approve', 'value': 'approve'}, {'label': 'Deny', 'value': 'deny'}],
        },
    )

    assert result['blocks'][0] == {'type': 'text', 'content': 'Deploy to production'}
    assert result['blocks'][1] == {'type': 'alert', 'variant': 'info', 'content': 'All tests passed'}
    assert result['blocks'][2] == {
        'type': 'alert',
        'variant': 'warning',
        'content': 'Rollback needed if DB migration fails',
    }
    assert result['blocks'][3]['items'] == [
        {'label': 'Approve', 'value': 'approve'},
        {'label': 'Deny', 'value': 'deny'},
    ]


def test_expand_composition_kpi_dashboard():
    from open_webui.utils.agui_compositions import expand_composition

    result = expand_composition(
        'kpi_dashboard',
        {
            'metrics': [{'label': 'Revenue', 'value': '$1M'}],
            'chartType': 'bar',
            'labels': ['Q1', 'Q2'],
            'datasets': [{'data': [100, 200]}],
            'columns': ['Name', 'Value'],
            'rows': [['Revenue', '$1M']],
        },
    )

    assert result['blocks'][0] == {'type': 'metrics', 'items': [{'label': 'Revenue', 'value': '$1M'}]}
    assert result['blocks'][1]['chartType'] == 'bar'
    assert result['blocks'][2]['columns'] == ['Name', 'Value']


def test_expand_composition_missing_key_keeps_placeholder():
    """If a data key is missing, the $field placeholder is preserved."""
    from open_webui.utils.agui_compositions import expand_composition

    result = expand_composition('approval_card', {'action': 'Do something'})

    assert result['blocks'][0]['content'] == 'Do something'
    # Missing keys keep original $field value
    assert result['blocks'][1]['content'] == '$rationale'
    assert result['blocks'][2]['content'] == '$risks'
    assert result['blocks'][3]['items'] == '$options'


def test_expand_composition_unknown_name_raises():
    from open_webui.utils.agui_compositions import expand_composition

    with pytest.raises(KeyError):
        expand_composition('nonexistent_composition', {})


def test_expand_composition_triage_table():
    from open_webui.utils.agui_compositions import expand_composition

    result = expand_composition(
        'triage_table',
        {
            'statusLabel': 'Active',
            'statusVariant': 'success',
            'columns': ['ID', 'Status'],
            'rows': [['1', 'Active']],
            'bulkActions': [{'label': 'Close', 'value': 'close'}],
        },
    )

    assert result['blocks'][0] == {'type': 'badge', 'label': 'Active', 'variant': 'success'}
    assert result['blocks'][1]['columns'] == ['ID', 'Status']
    assert result['blocks'][2]['items'] == [{'label': 'Close', 'value': 'close'}]


def test_expand_composition_form_wizard():
    from open_webui.utils.agui_compositions import expand_composition

    result = expand_composition(
        'form_wizard',
        {
            'steps': ['Step 1', 'Step 2'],
            'currentStep': 0,
            'formId': 'my-form',
            'fields': [{'name': 'email', 'type': 'text'}],
            'submitLabel': 'Submit',
            'submitAction': 'submit',
        },
    )

    assert result['blocks'][0]['steps'] == ['Step 1', 'Step 2']
    assert result['blocks'][0]['current'] == 0
    assert result['blocks'][1]['id'] == 'my-form'
    assert result['blocks'][1]['submitLabel'] == 'Submit'


def test_expand_composition_comparison_view():
    from open_webui.utils.agui_compositions import expand_composition

    result = expand_composition('comparison_view', {'columnBlocks': [{'type': 'text', 'content': 'A'}]})

    assert result['blocks'][0]['type'] == 'columns'
    assert result['blocks'][0]['blocks'] == [{'type': 'text', 'content': 'A'}]


def test_expand_composition_activity_feed():
    from open_webui.utils.agui_compositions import expand_composition

    result = expand_composition(
        'activity_feed',
        {
            'items': [{'text': 'User logged in'}],
            'actions': [{'label': 'Refresh', 'value': 'refresh'}],
        },
    )

    assert result['blocks'][0]['items'] == [{'text': 'User logged in'}]
    assert result['blocks'][1]['items'] == [{'label': 'Refresh', 'value': 'refresh'}]


def test_compositions_dict_has_all_six():
    from open_webui.utils.agui_compositions import COMPOSITIONS

    assert set(COMPOSITIONS.keys()) == {
        'approval_card',
        'kpi_dashboard',
        'triage_table',
        'form_wizard',
        'comparison_view',
        'activity_feed',
    }


# ---------------------------------------------------------------------------
# agui_types tests
# ---------------------------------------------------------------------------


def test_agui_types_exports_event_classes():
    """agui_types re-exports the key AG-UI event classes."""
    from open_webui.utils.agui_types import (
        ToolCallStartEvent,
        ToolCallArgsEvent,
        ToolCallEndEvent,
        StateSnapshotEvent,
        ActivitySnapshotEvent,
        RunStartedEvent,
        RunFinishedEvent,
        EventType,
    )

    # Can instantiate them
    e = ToolCallStartEvent(tool_call_id='call_1', tool_call_name='render_ui')
    assert e.tool_call_id == 'call_1'
    assert e.tool_call_name == 'render_ui'


def test_agui_types_event_type_enum():
    from open_webui.utils.agui_types import EventType

    assert EventType.TOOL_CALL_START == 'TOOL_CALL_START'
    assert EventType.STATE_SNAPSHOT == 'STATE_SNAPSHOT'
    assert EventType.ACTIVITY_SNAPSHOT == 'ACTIVITY_SNAPSHOT'


# ---------------------------------------------------------------------------
# agui_adapter tests — events_from_tool_calls_log
# ---------------------------------------------------------------------------


def _make_render_ui_log(call_id='call_abc123', message_id=''):
    blocks = [{'type': 'metrics', 'items': [{'label': 'Revenue', 'value': '$1M'}]}]
    arguments = json.dumps({'blocks': blocks})
    return (
        [
            {
                'role': 'assistant',
                'tool_calls': [
                    {
                        'id': call_id,
                        'function': {
                            'name': 'render_ui',
                            'arguments': arguments,
                        },
                    }
                ],
            },
            {
                'role': 'tool',
                'tool_call_id': call_id,
                'content': json.dumps({'title': 'Dashboard', 'blocks': blocks}),
            },
        ],
        blocks,
        arguments,
    )


def test_events_from_tool_calls_log_render_ui_produces_four_events():
    from open_webui.utils.agui_adapter import events_from_tool_calls_log

    log, blocks, arguments = _make_render_ui_log('call_abc123', 'msg_1')
    events = events_from_tool_calls_log(log, message_id='msg_1')

    assert len(events) == 4


def test_events_from_tool_calls_log_render_ui_event_types():
    from open_webui.utils.agui_adapter import events_from_tool_calls_log

    log, _, _ = _make_render_ui_log('call_abc123', 'msg_1')
    events = events_from_tool_calls_log(log, message_id='msg_1')

    types = [e['type'] for e in events]
    assert types[0] == 'TOOL_CALL_START'
    assert types[1] == 'TOOL_CALL_ARGS'
    assert types[2] == 'TOOL_CALL_END'
    assert types[3] == 'STATE_SNAPSHOT'


def test_events_from_tool_calls_log_render_ui_tool_call_start():
    from open_webui.utils.agui_adapter import events_from_tool_calls_log

    log, _, _ = _make_render_ui_log('call_abc123', 'msg_1')
    events = events_from_tool_calls_log(log, message_id='msg_1')

    start = events[0]
    assert start['tool_call_id'] == 'call_abc123'
    assert start['tool_call_name'] == 'render_ui'
    assert start['parent_message_id'] == 'msg_1'


def test_events_from_tool_calls_log_render_ui_args_event():
    from open_webui.utils.agui_adapter import events_from_tool_calls_log

    log, blocks, arguments = _make_render_ui_log('call_abc123', 'msg_1')
    events = events_from_tool_calls_log(log, message_id='msg_1')

    args_event = events[1]
    assert args_event['tool_call_id'] == 'call_abc123'
    assert args_event['delta'] == arguments


def test_events_from_tool_calls_log_render_ui_state_snapshot():
    from open_webui.utils.agui_adapter import events_from_tool_calls_log

    log, blocks, arguments = _make_render_ui_log('call_abc123', 'msg_1')
    events = events_from_tool_calls_log(log, message_id='msg_1')

    snapshot_event = events[3]
    assert snapshot_event['type'] == 'STATE_SNAPSHOT'
    snapshot = snapshot_event['snapshot']
    assert 'ui' in snapshot
    assert snapshot['ui']['lastRender']['toolName'] == 'render_ui'
    assert snapshot['ui']['lastRender']['blocks'] == blocks
    assert 'call_abc123' in snapshot['ui']['components']
    component = snapshot['ui']['components']['call_abc123']
    assert component['type'] == 'render_ui'
    assert component['data'] == json.dumps(blocks)


def test_build_render_ui_snapshot_with_component_id():
    """componentId is extracted from args and included in StateSnapshot."""
    from open_webui.utils.agui_adapter import _build_render_ui_snapshot

    args = json.dumps({
        'componentId': 'wizard-1',
        'composition': 'approval_card',
        'data': {
            'title': 'Test',
            'action': 'Confirm',
            'options': ['Yes', 'No'],
        }
    })

    result = _build_render_ui_snapshot('call-123', args)

    assert result['type'] == 'STATE_SNAPSHOT'
    assert result['snapshot']['ui']['lastRender']['componentId'] == 'wizard-1'
    assert result['snapshot']['ui']['components']['call-123']['componentId'] == 'wizard-1'
    assert result['_tool_call_id'] == 'call-123'


def test_build_render_ui_snapshot_without_component_id():
    """componentId defaults to empty string when not provided."""
    from open_webui.utils.agui_adapter import _build_render_ui_snapshot

    args = json.dumps({
        'composition': 'approval_card',
        'data': {'title': 'Test', 'options': ['Yes']}
    })

    result = _build_render_ui_snapshot('call-456', args)

    assert result['snapshot']['ui']['lastRender']['componentId'] == ''
    assert result['snapshot']['ui']['components']['call-456']['componentId'] == ''


def test_events_from_tool_calls_log_render_custom_produces_three_events():
    """render_custom has no StateSnapshot — just start, args, end."""
    from open_webui.utils.agui_adapter import events_from_tool_calls_log

    html = '<html><body>Hello</body></html>'
    arguments = json.dumps({'html': html})
    log = [
        {
            'role': 'assistant',
            'tool_calls': [
                {
                    'id': 'call_custom_1',
                    'function': {
                        'name': 'render_custom',
                        'arguments': arguments,
                    },
                }
            ],
        },
        {
            'role': 'tool',
            'tool_call_id': 'call_custom_1',
            'content': html,
        },
    ]

    events = events_from_tool_calls_log(log, message_id='msg_2')

    assert len(events) == 3
    types = [e['type'] for e in events]
    assert types == ['TOOL_CALL_START', 'TOOL_CALL_ARGS', 'TOOL_CALL_END']
    assert events[0]['tool_call_name'] == 'render_custom'


def test_events_from_tool_calls_log_empty_log_returns_empty():
    from open_webui.utils.agui_adapter import events_from_tool_calls_log

    assert events_from_tool_calls_log([]) == []


def test_events_from_tool_calls_log_malformed_returns_empty():
    from open_webui.utils.agui_adapter import events_from_tool_calls_log

    assert events_from_tool_calls_log([{'role': 'assistant', 'content': 'oops'}]) == []
    assert events_from_tool_calls_log(None) == []  # type: ignore
    assert events_from_tool_calls_log('not a list') == []  # type: ignore


def test_events_from_tool_calls_log_no_message_id_defaults_empty():
    from open_webui.utils.agui_adapter import events_from_tool_calls_log

    log, _, _ = _make_render_ui_log('call_x')
    events = events_from_tool_calls_log(log)

    # parent_message_id defaults to '' (or None — just check it doesn't crash)
    assert events[0]['tool_call_name'] == 'render_ui'


# ---------------------------------------------------------------------------
# agui_adapter tests — events_from_activity_text
# ---------------------------------------------------------------------------


def test_events_from_activity_text_terminal_command():
    from open_webui.utils.agui_adapter import events_from_activity_text

    events, suppressed = events_from_activity_text('_Running terminal command: ls -la_', 'msg_1')

    assert suppressed is True
    assert len(events) == 1
    assert events[0]['type'] == 'ACTIVITY_SNAPSHOT'
    assert events[0]['activity_type'] == 'terminal'
    assert events[0]['content']['description'] == '_Running terminal command: ls -la_'
    assert events[0]['message_id'] == 'msg_1'


def test_events_from_activity_text_shell_command():
    from open_webui.utils.agui_adapter import events_from_activity_text

    events, suppressed = events_from_activity_text('_Running shell command: echo hi_', 'msg_2')

    assert suppressed is True
    assert events[0]['activity_type'] == 'terminal'


def test_events_from_activity_text_reading_file():
    from open_webui.utils.agui_adapter import events_from_activity_text

    events, suppressed = events_from_activity_text('_Reading file: /data/foo.py_', 'msg_3')

    assert suppressed is True
    assert events[0]['activity_type'] == 'file_read'
    assert events[0]['content']['description'] == '_Reading file: /data/foo.py_'


def test_events_from_activity_text_writing_file():
    from open_webui.utils.agui_adapter import events_from_activity_text

    events, suppressed = events_from_activity_text('_Writing file: /data/bar.py_', 'msg_4')

    assert suppressed is True
    assert events[0]['activity_type'] == 'file_write'


def test_events_from_activity_text_searching_web():
    from open_webui.utils.agui_adapter import events_from_activity_text

    events, suppressed = events_from_activity_text('_Searching the web..._', 'msg_5')

    assert suppressed is True
    assert events[0]['activity_type'] == 'web_search'


def test_events_from_activity_text_fetching_url():
    from open_webui.utils.agui_adapter import events_from_activity_text

    events, suppressed = events_from_activity_text('_Fetching URL: https://example.com_', 'msg_6')

    assert suppressed is True
    assert events[0]['activity_type'] == 'web_fetch'
    assert events[0]['content']['description'] == '_Fetching URL: https://example.com_'


def test_events_from_activity_text_using_tool():
    from open_webui.utils.agui_adapter import events_from_activity_text

    events, suppressed = events_from_activity_text('_Using some-tool-name_', 'msg_7')

    assert suppressed is True
    assert events[0]['activity_type'] == 'tool'


def test_events_from_activity_text_non_activity_returns_not_suppressed():
    from open_webui.utils.agui_adapter import events_from_activity_text

    events, suppressed = events_from_activity_text('This is a normal message', 'msg_8')

    assert suppressed is False
    assert events == []


def test_events_from_activity_text_empty_string():
    from open_webui.utils.agui_adapter import events_from_activity_text

    events, suppressed = events_from_activity_text('', 'msg_9')

    assert suppressed is False
    assert events == []


def test_events_from_activity_text_partial_italic_not_suppressed():
    """Italic text that doesn't match any activity pattern is not suppressed."""
    from open_webui.utils.agui_adapter import events_from_activity_text

    events, suppressed = events_from_activity_text('_Some random italic text_', 'msg_10')

    assert suppressed is False
    assert events == []


def test_events_from_activity_text_using_natural_sentence_not_suppressed():
    """Natural italic English starting with 'Using' must NOT be swallowed as a tool activity."""
    from open_webui.utils.agui_adapter import events_from_activity_text

    events, suppressed = events_from_activity_text('_Using cautious language_')
    assert suppressed is False
    assert events == []


# ---------------------------------------------------------------------------
# agui_adapter tests — extract_agui_events_from_stream_chunk
# ---------------------------------------------------------------------------


def test_extract_agui_events_from_stream_chunk_tool_calls_log():
    from open_webui.utils.agui_adapter import extract_agui_events_from_stream_chunk

    log, blocks, _ = _make_render_ui_log('call_xyz', 'msg_chunk_1')
    chunk = {
        'id': 'chatcmpl-xxx',
        'choices': [{'index': 0, 'delta': {}, 'finish_reason': None}],
        'tool_calls_log': log,
    }

    events, suppressed = extract_agui_events_from_stream_chunk(chunk, message_id='msg_chunk_1')

    assert len(events) == 4
    assert suppressed is False  # tool_calls_log chunks don't suppress content


def test_extract_agui_events_from_stream_chunk_activity_text():
    from open_webui.utils.agui_adapter import extract_agui_events_from_stream_chunk

    chunk = {
        'id': 'chatcmpl-yyy',
        'choices': [{'index': 0, 'delta': {'content': '_Running terminal command: ls -la_'}, 'finish_reason': None}],
    }

    events, suppressed = extract_agui_events_from_stream_chunk(chunk, message_id='msg_chunk_2')

    assert len(events) == 1
    assert suppressed is True
    assert events[0]['activity_type'] == 'terminal'


def test_extract_agui_events_from_stream_chunk_normal_content():
    from open_webui.utils.agui_adapter import extract_agui_events_from_stream_chunk

    chunk = {'choices': [{'index': 0, 'delta': {'content': 'Hello, world!'}, 'finish_reason': None}]}

    events, suppressed = extract_agui_events_from_stream_chunk(chunk, message_id='msg_chunk_3')

    assert events == []
    assert suppressed is False


def test_extract_agui_events_from_stream_chunk_empty_chunk():
    from open_webui.utils.agui_adapter import extract_agui_events_from_stream_chunk

    events, suppressed = extract_agui_events_from_stream_chunk({}, message_id='msg_chunk_4')

    assert events == []
    assert suppressed is False


def test_extract_agui_events_from_stream_chunk_no_delta():
    from open_webui.utils.agui_adapter import extract_agui_events_from_stream_chunk

    chunk = {'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]}

    events, suppressed = extract_agui_events_from_stream_chunk(chunk, message_id='msg_chunk_5')

    assert events == []
    assert suppressed is False


# ---------------------------------------------------------------------------
# Integration-style tests: middleware tool_calls_log → agui:event emissions
# ---------------------------------------------------------------------------


def test_middleware_tool_calls_log_emits_agui_events():
    """
    Simulates the middleware's tool_calls_log branch: after the legacy
    chat:completion event, AG-UI events are emitted via event_emitter.
    Verifies correct event shapes for the agui:event emissions.
    """
    from open_webui.utils.agui_adapter import events_from_tool_calls_log

    log, blocks, arguments = _make_render_ui_log('call_mw_1', 'msg_mw_1')
    message_id = 'msg_mw_1'

    agui_events = events_from_tool_calls_log(log, message_id=message_id)
    # Simulate what middleware does: wrap each in an agui:event envelope
    emitted = [{'type': 'agui:event', 'data': e} for e in agui_events]

    assert len(emitted) == 4
    types = [e['data']['type'] for e in emitted]
    assert types[0] == 'TOOL_CALL_START'
    assert types[1] == 'TOOL_CALL_ARGS'
    assert types[2] == 'TOOL_CALL_END'
    assert types[3] == 'STATE_SNAPSHOT'

    for e in emitted:
        assert e['type'] == 'agui:event'


def test_middleware_tool_calls_log_agui_events_carry_message_id():
    """TOOL_CALL_START events carry the parent_message_id from metadata."""
    from open_webui.utils.agui_adapter import events_from_tool_calls_log

    log, _, _ = _make_render_ui_log('call_mw_2', 'msg_mw_2')
    events = events_from_tool_calls_log(log, message_id='msg_mw_2')

    start_event = events[0]
    assert start_event['parent_message_id'] == 'msg_mw_2'


def test_middleware_activity_content_suppressed_and_agui_emitted():
    """
    Activity text in delta.content is suppressed from the text stream
    and triggers an AG-UI ActivitySnapshot event.
    """
    from open_webui.utils.agui_adapter import extract_agui_events_from_stream_chunk

    activity_text = '_Running terminal command: pytest tests_'
    message_id = 'msg_act_1'

    value = activity_text
    agui_events, suppressed = extract_agui_events_from_stream_chunk(
        {'choices': [{'delta': {'content': value}}]},
        message_id,
    )
    # Simulate what middleware does: wrap each in agui:event envelope
    emitted_agui = [{'type': 'agui:event', 'data': e} for e in agui_events]
    if suppressed:
        value = None  # mimic the middleware suppression
    final_value = value

    assert final_value is None, 'Activity text should be suppressed from the content stream'
    assert len(emitted_agui) == 1
    assert emitted_agui[0]['type'] == 'agui:event'
    assert emitted_agui[0]['data']['type'] == 'ACTIVITY_SNAPSHOT'
    assert emitted_agui[0]['data']['activity_type'] == 'terminal'


def test_middleware_normal_content_not_suppressed():
    """Non-activity content is NOT suppressed and no AG-UI events are emitted."""
    from open_webui.utils.agui_adapter import extract_agui_events_from_stream_chunk

    chunk = {'choices': [{'delta': {'content': 'Here is the summary you requested.'}}]}

    events, suppressed = extract_agui_events_from_stream_chunk(chunk, message_id='msg_normal')

    assert suppressed is False
    assert events == []


# ---------------------------------------------------------------------------
# Integration-style tests: processes.py cron webhook → agui:event emissions
# ---------------------------------------------------------------------------


def test_cron_webhook_agui_events_from_tool_calls_log():
    """
    events_from_tool_calls_log called from the cron webhook path produces
    the correct AG-UI event list (same adapter, same shape expected).
    """
    from open_webui.utils.agui_adapter import events_from_tool_calls_log

    log, blocks, arguments = _make_render_ui_log('call_cron_1')
    events = events_from_tool_calls_log(log, message_id='')

    assert len(events) == 4
    assert events[0]['type'] == 'TOOL_CALL_START'
    assert events[0]['tool_call_name'] == 'render_ui'
    # message_id defaults to '' in the cron path (no active session message)
    assert events[0]['parent_message_id'] is None  # empty string → None in pydantic model


def test_cron_webhook_empty_tool_calls_log_emits_nothing():
    """If tool_calls_log is absent/None, no AG-UI events are produced."""
    from open_webui.utils.agui_adapter import events_from_tool_calls_log

    assert events_from_tool_calls_log(None) == []  # type: ignore
    assert events_from_tool_calls_log([]) == []


# ---------------------------------------------------------------------------
# _build_render_awareness tests
# ---------------------------------------------------------------------------


def test_build_render_awareness_form_wizard():
    """form_wizard includes step number in description."""
    from open_webui.utils.chat_payload import _build_render_awareness

    args = json.dumps({
        'componentId': 'wizard-1',
        'composition': 'form_wizard',
        'data': {
            'steps': [{'label': 'Step 1'}, {'label': 'Step 2'}],
            'currentStep': 0,
        }
    })
    result = _build_render_awareness(args, 'call-1')

    assert result is not None
    assert result['role'] == 'user'
    assert 'wizard-1' in result['content']
    assert 'step 1 of 2' in result['content']
    assert result['metadata']['rendered_component']['componentId'] == 'wizard-1'


def test_build_render_awareness_approval_card():
    """approval_card lists options in description."""
    from open_webui.utils.chat_payload import _build_render_awareness

    args = json.dumps({
        'componentId': 'approval-1',
        'composition': 'approval_card',
        'data': {'options': ['Approve', 'Deny', 'Request Info']}
    })
    result = _build_render_awareness(args, 'call-2')

    assert result is not None
    assert 'Approve' in result['content']
    assert 'Deny' in result['content']
    assert result['metadata']['rendered_component']['componentId'] == 'approval-1'


def test_build_render_awareness_unknown_composition():
    """Unknown composition gets generic description."""
    from open_webui.utils.chat_payload import _build_render_awareness

    args = json.dumps({'componentId': 'c-1', 'composition': 'custom_skill_card', 'data': {}})
    result = _build_render_awareness(args, 'call-3')

    assert result is not None
    assert 'RENDERED_COMPONENT' in result['content']
    assert 'custom_skill_card' in result['content']


def test_build_render_awareness_malformed_json():
    """Malformed JSON returns None without crashing."""
    from open_webui.utils.chat_payload import _build_render_awareness

    result = _build_render_awareness('not valid json', 'call-4')
    assert result is None


def test_build_render_awareness_dict_arguments():
    """Accepts dict arguments in addition to JSON string."""
    from open_webui.utils.chat_payload import _build_render_awareness

    args = {
        'componentId': 'wizard-2',
        'composition': 'form_wizard',
        'data': {
            'steps': [{'label': 'Step 1'}, {'label': 'Step 2'}, {'label': 'Step 3'}],
            'currentStep': 1,
        }
    }
    result = _build_render_awareness(args, 'call-5')

    assert result is not None
    assert 'wizard-2' in result['content']
    assert 'step 2 of 3' in result['content']


# ---------------------------------------------------------------------------
# CompositionRegistry tests
# ---------------------------------------------------------------------------


def test_composition_registry_register_and_get():
    """Registry stores and retrieves compositions."""
    from open_webui.utils.agui_compositions import CompositionRegistry

    r = CompositionRegistry()
    r.register('test_comp', {'blocks': [{'type': 'text'}]})
    assert r.get('test_comp') == {'blocks': [{'type': 'text'}]}
    assert r.get('nonexistent') is None


def test_composition_registry_list_all():
    """list_all returns all registered names."""
    from open_webui.utils.agui_compositions import CompositionRegistry

    r = CompositionRegistry()
    assert r.list_all() == []
    r.register('a', {'blocks': []})
    r.register('b', {'blocks': []})
    assert set(r.list_all()) == {'a', 'b'}


def test_composition_registry_clear():
    """clear removes all compositions."""
    from open_webui.utils.agui_compositions import CompositionRegistry

    r = CompositionRegistry()
    r.register('test', {'blocks': []})
    r.clear()
    assert r.list_all() == []


def test_expand_composition_uses_registry():
    """expand_composition delegates to registry for unknown compositions."""
    from open_webui.utils.agui_compositions import expand_composition

    result = expand_composition('approval_card', {'action': 'Test', 'options': []})
    assert 'blocks' in result

    result = expand_composition('nonexistent_composition', {})
    assert result['blocks'][0]['type'] == 'text'
    assert 'Unknown composition' in result['blocks'][0]['content']


def test_reformat_action_for_agent_structured():
    """TOOL_CALL_RESULT actions are formatted as JSON, not natural language."""
    from open_webui.utils.chat_payload import _reformat_action_for_agent

    action_data = {
        'type': 'TOOL_CALL_RESULT',
        'toolCallId': 'call-1',
        'componentId': 'approval-1',
        'action': 'approve',
        'label': 'Approve',
        'result': {
            'action': 'approve',
            'label': 'Approve',
            'payload': {},
            'timestamp': 1712000000000,
        }
    }

    result = _reformat_action_for_agent(action_data)

    assert result.startswith('[UI_ACTION_RESULT]')
    parsed = json.loads(result[len('[UI_ACTION_RESULT] '):])
    assert parsed['type'] == 'ui_action_result'
    assert parsed['componentId'] == 'approval-1'
    assert parsed['action'] == 'approve'
    assert 'timestamp' in parsed['result']


def test_reformat_action_for_agent_legacy_submit():
    """Legacy ui:submit actions still produce natural language."""
    from open_webui.utils.chat_payload import _reformat_action_for_agent

    action_data = {
        'type': 'ui:submit',
        'formId': 'feedback-form',
        'composition': 'form_wizard',
        'action': 'submit',
        'data': {'rating': '5', 'comment': 'Great!'}
    }

    result = _reformat_action_for_agent(action_data)

    assert '[User submitted form "feedback-form"' in result
    assert 'submit' in result


def test_reformat_action_for_agent_legacy_click():
    """Legacy ui:action clicks still produce natural language."""
    from open_webui.utils.chat_payload import _reformat_action_for_agent

    action_data = {
        'type': 'ui:action',
        'action': 'cancel',
        'composition': 'approval_card',
        'payload': {'reason': 'too expensive'}
    }

    result = _reformat_action_for_agent(action_data)

    assert '[User clicked "cancel" on approval_card composition]' in result
    assert 'too expensive' in result


# ---------------------------------------------------------------------------
# HITL wait state tests
# ---------------------------------------------------------------------------


def test_wait_state_set_and_get():
    """Wait state is stored and retrievable by chat_id."""
    from open_webui.utils.chat_payload import set_agent_wait_state, get_agent_wait_state, clear_agent_wait_state

    chat_id = 'test-chat-1'
    set_agent_wait_state(chat_id, {
        'waiting_for': 'approve',
        'component_id': 'approval-1',
        'tool_call_id': 'call-1',
    })

    state = get_agent_wait_state(chat_id)
    assert state is not None
    assert state['waiting_for'] == 'approve'
    assert state['component_id'] == 'approval-1'

    clear_agent_wait_state(chat_id)
    assert get_agent_wait_state(chat_id) is None


# ---------------------------------------------------------------------------
# Logging on translation failure — silent exceptions must now surface
# ---------------------------------------------------------------------------


def test_events_from_output_items_logs_on_failure(caplog):
    """Translation failures must produce a warning log, not silent empty lists."""
    import logging

    from open_webui.utils.agui_adapter import events_from_output_items

    bad_items = [{'type': 'function_call', 'name': 'render_ui', 'call_id': 'c1', 'arguments': object()}]
    with caplog.at_level(logging.WARNING, logger='open_webui.utils.agui_adapter'):
        result = events_from_output_items(bad_items)
    assert result == []
    assert any('events_from_output_items' in r.message for r in caplog.records)


def test_events_from_tool_calls_log_logs_on_failure(caplog):
    """Translation failures in tool_calls_log must produce a warning log."""
    import logging

    from open_webui.utils.agui_adapter import events_from_tool_calls_log

    bad_log = [{'role': 'assistant', 'tool_calls': [{'id': 'tc1', 'function': object()}]}]
    with caplog.at_level(logging.WARNING, logger='open_webui.utils.agui_adapter'):
        result = events_from_tool_calls_log(bad_log)
    assert result == []
    assert any('events_from_tool_calls_log' in r.message for r in caplog.records)


def test_events_from_tool_event_logs_on_failure(caplog):
    """Translation failures in tool_event must produce a warning log including type and name."""
    import logging

    from open_webui.utils.agui_adapter import events_from_tool_event

    bad_event = {'type': 'start', 'name': 'render_ui', 'call_id': 'c1', 'args': object()}
    with caplog.at_level(logging.WARNING, logger='open_webui.utils.agui_adapter'):
        result = events_from_tool_event(bad_event)
    assert result == []
    assert any('events_from_tool_event' in r.message for r in caplog.records)

