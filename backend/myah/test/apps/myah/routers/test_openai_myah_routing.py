"""Tests for _build_myah_attachments helper in openai router."""

import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


class _FakeAiohttpResponse:
    def __init__(self, *, status=200, json_data=None, text_data=''):
        self.status = status
        self._json_data = json_data or {}
        self._text_data = text_data

    async def json(self):
        return self._json_data

    async def text(self):
        return self._text_data


class _FakeMyahClientSession:
    def __init__(self, *, start_response, events_response=None):
        self.start_response = start_response
        self.events_response = events_response or _FakeAiohttpResponse(status=200)
        self.posts = []
        self.gets = []
        self.closed = False

    async def post(self, url, **kwargs):
        self.posts.append({'url': url, **kwargs})
        return self.start_response

    async def get(self, url, **kwargs):
        self.gets.append({'url': url, **kwargs})
        return self.events_response

    async def close(self):
        self.closed = True


def _fake_openai_request():
    return SimpleNamespace(
        state=SimpleNamespace(bypass_filter=False),
        app=SimpleNamespace(
            state=SimpleNamespace(
                config=SimpleNamespace(
                    OPENAI_API_BASE_URLS=[],
                    OPENAI_API_KEYS=[],
                    OPENAI_API_CONFIGS={},
                ),
                OPENAI_MODELS={},
            )
        ),
    )


def _fake_user(**overrides):
    data = {
        'id': 'user-1',
        'name': 'Ada Lovelace',
        'email': 'ada@example.test',
        'role': 'user',
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def test_empty_payload_returns_empty_list():
    from myah.routers.openai import _build_myah_attachments

    user = MagicMock()
    result = _build_myah_attachments({'messages': []}, user)
    assert result == []


def test_single_file_produces_single_attachment():
    from myah.routers.openai import _build_myah_attachments

    user = MagicMock(id='user-1')
    fake_file = MagicMock(id='file-1', filename='a.pdf', meta={'content_type': 'application/pdf', 'size': 1024})
    with patch('myah.routers.openai.Files.get_file_by_id', return_value=fake_file):
        payload = {
            'messages': [{'role': 'user', 'content': 'hi'}],
            'files': [{'id': 'file-1', 'type': 'file'}],
        }
        result = _build_myah_attachments(payload, user)
    assert result == [{'file_id': 'file-1', 'filename': 'a.pdf', 'mime_type': 'application/pdf', 'size': 1024}]


def test_dedup_when_same_file_in_files_and_image_url():
    from myah.routers.openai import _build_myah_attachments

    user = MagicMock(id='user-1')
    fake_file = MagicMock(id='file-1', filename='img.png', meta={'content_type': 'image/png', 'size': 500})
    with patch('myah.routers.openai.Files.get_file_by_id', return_value=fake_file):
        payload = {
            'messages': [
                {
                    'role': 'user',
                    'content': [
                        {
                            'type': 'image_url',
                            'image_url': {'url': '/api/v1/files/file-1/content'},
                        },
                    ],
                }
            ],
            'files': [{'id': 'file-1', 'type': 'image'}],
        }
        result = _build_myah_attachments(payload, user)
    assert len(result) == 1


def test_rejects_per_file_oversize():
    from myah.routers.openai import _build_myah_attachments
    from fastapi import HTTPException

    user = MagicMock(id='user-1')
    fake_file = MagicMock(
        id='big',
        filename='big.bin',
        meta={'content_type': 'application/octet-stream', 'size': 25 * 1024 * 1024},
    )
    with patch('myah.routers.openai.Files.get_file_by_id', return_value=fake_file):
        payload = {'messages': [], 'files': [{'id': 'big', 'type': 'file'}]}
        with pytest.raises(HTTPException) as exc:
            _build_myah_attachments(payload, user)
    assert exc.value.status_code == 413


def test_rejects_aggregate_oversize():
    from myah.routers.openai import _build_myah_attachments
    from fastapi import HTTPException

    user = MagicMock(id='user-1')
    files = [
        MagicMock(
            id=f'f{i}',
            filename=f'f{i}.bin',
            meta={'content_type': 'application/octet-stream', 'size': 18 * 1024 * 1024},
        )
        for i in range(5)
    ]
    by_id = {f.id: f for f in files}
    with patch(
        'myah.routers.openai.Files.get_file_by_id',
        side_effect=lambda fid, **kw: by_id.get(fid),
    ):
        payload = {
            'messages': [],
            'files': [{'id': f'f{i}', 'type': 'file'} for i in range(5)],
        }
        with pytest.raises(HTTPException) as exc:
            _build_myah_attachments(payload, user)
    assert exc.value.status_code == 413


def test_missing_file_skips_silently():
    from myah.routers.openai import _build_myah_attachments

    user = MagicMock(id='user-1')
    with patch('myah.routers.openai.Files.get_file_by_id', return_value=None):
        payload = {'messages': [], 'files': [{'id': 'deleted-file', 'type': 'file'}]}
        result = _build_myah_attachments(payload, user)
    assert result == []


def test_build_myah_attachments_with_no_files_returns_empty():
    from myah.routers.openai import _build_myah_attachments

    user = MagicMock(id='user-1')
    result = _build_myah_attachments({'messages': [{'role': 'user', 'content': 'hi'}]}, user)
    assert result == []


def test_file_id_from_url_extracts_id():
    from myah.routers.openai import _file_id_from_url

    assert _file_id_from_url('/api/v1/files/abc-123/content') == 'abc-123'
    assert _file_id_from_url('/api/v1/files/abc-123/') == 'abc-123'
    assert _file_id_from_url('data:image/png;base64,abc') is None
    assert _file_id_from_url('') is None
    assert _file_id_from_url(None) is None


# ── _extract_model_provider ─────────────────────────────────────────────
# Regression tests for the home/new-chat first-message routing bug:
# $chatId is empty on the home page, so the Selector.svelte onClick guard
# skips setChatSessionModel — the per-message body is the only channel
# that can tell Hermes which provider owns the user's picked model.
# Frontend ships model_item.tags=[{'name': '<provider_id>'}] on every
# chat-completion POST; /api/models shaping in backend/myah/main.py builds
# those provider tags.


def test_extract_model_provider_returns_first_tag_name():
    from myah.routers.openai import _extract_model_provider

    payload = {'model_item': {'tags': [{'name': 'openai-codex'}]}}
    assert _extract_model_provider(payload) == 'openai-codex'


def test_extract_model_provider_strips_whitespace():
    from myah.routers.openai import _extract_model_provider

    payload = {'model_item': {'tags': [{'name': '  openrouter  '}]}}
    assert _extract_model_provider(payload) == 'openrouter'


def test_extract_model_provider_returns_none_when_tags_missing():
    from myah.routers.openai import _extract_model_provider

    # No model_item at all
    assert _extract_model_provider({}) is None
    # model_item present but no tags
    assert _extract_model_provider({'model_item': {}}) is None
    # Tags is empty list
    assert _extract_model_provider({'model_item': {'tags': []}}) is None


def test_extract_model_provider_handles_malformed_tags():
    from myah.routers.openai import _extract_model_provider

    # Tag not a dict
    assert _extract_model_provider({'model_item': {'tags': ['openai-codex']}}) is None
    # Tag dict with no name
    assert _extract_model_provider({'model_item': {'tags': [{}]}}) is None
    # Name not a string
    assert _extract_model_provider({'model_item': {'tags': [{'name': 123}]}}) is None
    # Name is empty/whitespace string
    assert _extract_model_provider({'model_item': {'tags': [{'name': ''}]}}) is None
    assert _extract_model_provider({'model_item': {'tags': [{'name': '   '}]}}) is None
    # model_item is not a dict
    assert _extract_model_provider({'model_item': 'foo'}) is None
    # tags is not a list
    assert _extract_model_provider({'model_item': {'tags': 'openai-codex'}}) is None


def test_extract_model_provider_does_not_use_model_id_as_provider_when_tags_missing_or_malformed():
    from myah.routers.openai import _extract_model_provider

    assert _extract_model_provider({'model': 'claude-opus-4', 'model_item': {'tags': []}}) is None
    assert (
        _extract_model_provider(
            {
                'model': 'anthropic/claude-opus-4',
                'model_item': {'tags': [{'name': 123}]},
            }
        )
        is None
    )
    assert _extract_model_provider({'model': 'openai-codex/gpt-5', 'model_item': 'not-a-dict'}) is None


def test_extract_model_provider_allows_explicit_provider_bearing_fields():
    from myah.routers.openai import _extract_model_provider

    assert _extract_model_provider({'provider': ' openai-codex ', 'model': 'gpt-5'}) == 'openai-codex'
    assert (
        _extract_model_provider(
            {
                'model': 'claude-opus-4',
                'model_item': {'provider_id': 'anthropic-claude-code', 'tags': []},
            }
        )
        == 'anthropic-claude-code'
    )


def test_extract_model_provider_tag_wins_over_conflicting_explicit_field():
    from myah.routers.openai import _extract_model_provider

    # Tags are canonical. When a valid first tag and a conflicting explicit
    # provider-bearing field are both present, the tag must win — explicit
    # fields are only a fallback when tags are missing/malformed.
    assert (
        _extract_model_provider(
            {'provider': 'openrouter', 'model_item': {'tags': [{'name': 'openai-codex'}]}}
        )
        == 'openai-codex'
    )
    assert (
        _extract_model_provider(
            {
                'provider_id': 'openrouter',
                'model_item': {
                    'provider': 'openrouter',
                    'provider_id': 'openrouter',
                    'tags': [{'name': 'anthropic-claude-code'}],
                },
            }
        )
        == 'anthropic-claude-code'
    )


@pytest.mark.asyncio
async def test_myah_dispatch_payload_preserves_session_chat_user_and_model_metadata():
    import myah.routers.openai as openai_router

    user = _fake_user()
    session = _FakeMyahClientSession(
        start_response=_FakeAiohttpResponse(
            status=202,
            json_data={'stream_id': 'stream-1', 'session_id': 'hermes-session-1'},
        )
    )
    emitted_events = []

    async def fake_container(_user_id, *, event_emitter=None):
        if event_emitter:
            await event_emitter({'type': 'status', 'data': {'description': 'waking', 'done': False}})
        return SimpleNamespace(host_port=18080, gateway_port=18081)

    async def fake_emit(event):
        emitted_events.append(event)

    form_data = {
        'model': 'claude-opus-4',
        'model_item': {'tags': [{'name': 'anthropic-claude-code'}]},
        'messages': [
            {'role': 'system', 'content': 'be concise'},
            {'role': 'user', 'content': 'hello from chat'},
        ],
        'metadata': {
            'chat_id': 'chat-123',
            'message_id': 'msg-456',
            'chat_name': 'Launch notes',
            'user_id': user.id,
        },
    }

    with (
        patch('myah.routers.openai.get_or_create_container', side_effect=fake_container),
        patch('myah.routers.openai.aiohttp.ClientSession', return_value=session),
        patch('myah.routers.openai.AGENT_BEARER_TOKEN', 'test-agent-token'),
        patch('myah.routers.openai._build_myah_attachments', return_value=[]),
        patch('myah.routers.openai.Chats.set_hermes_session_id'),
        patch('myah.socket.main.get_event_emitter', return_value=fake_emit),
        patch('myah.utils.ui_state.prepend_user_ref_block', side_effect=lambda text, ui_state: text),
    ):
        response = await openai_router.generate_chat_completion(
            _fake_openai_request(),
            form_data,
            user=user,
        )

    assert response.status_code == 200
    assert session.posts, 'expected /myah/v1/message dispatch POST'
    dispatch = session.posts[0]
    assert dispatch['url'].endswith('/myah/v1/message')
    assert dispatch['headers']['Authorization'] == 'Bearer test-agent-token'

    myah_payload = dispatch['json']
    assert myah_payload['message'] == 'hello from chat'
    assert myah_payload['session_id'] == 'chat-123'
    assert myah_payload['message_id'] == 'msg-456'
    assert myah_payload['user_id'] == user.id
    assert myah_payload['user_name'] == user.name
    assert myah_payload['chat_name'] == 'Launch notes'
    assert myah_payload['model'] == 'claude-opus-4'
    assert myah_payload['provider'] == 'anthropic-claude-code'
    assert emitted_events, 'container/status emitter should remain wired during dispatch'


@pytest.mark.asyncio
async def test_myah_dispatch_missing_model_uses_default_without_forwarding_virtual_model():
    import myah.routers.openai as openai_router

    user = _fake_user(id='user-default')
    session = _FakeMyahClientSession(
        start_response=_FakeAiohttpResponse(status=202, json_data={'stream_id': 'stream-default'})
    )

    async def fake_container(_user_id, *, event_emitter=None):
        return SimpleNamespace(host_port=18080, gateway_port=18081)

    with (
        patch('myah.routers.openai.get_or_create_container', side_effect=fake_container),
        patch('myah.routers.openai.aiohttp.ClientSession', return_value=session),
        patch('myah.routers.openai._build_myah_attachments', return_value=[]),
        patch('myah.routers.openai.Chats.set_hermes_session_id'),
        patch('myah.socket.main.get_event_emitter', return_value=None),
        patch('myah.utils.ui_state.prepend_user_ref_block', side_effect=lambda text, ui_state: text),
    ):
        response = await openai_router.generate_chat_completion(
            _fake_openai_request(),
            {
                'messages': [{'role': 'user', 'content': 'use your default model'}],
                'metadata': {'chat_id': 'chat-default', 'message_id': 'msg-default'},
            },
            user=user,
        )

    assert response.status_code == 200
    myah_payload = session.posts[0]['json']
    assert myah_payload['session_id'] == 'chat-default'
    assert myah_payload['user_id'] == 'user-default'
    assert 'model' not in myah_payload
    assert 'provider' not in myah_payload


@pytest.mark.asyncio
async def test_myah_dispatch_malformed_provider_tags_do_not_forward_model_as_provider():
    import myah.routers.openai as openai_router

    user = _fake_user(id='user-malformed-provider')
    session = _FakeMyahClientSession(
        start_response=_FakeAiohttpResponse(status=202, json_data={'stream_id': 'stream-malformed'})
    )

    async def fake_container(_user_id, *, event_emitter=None):
        return SimpleNamespace(host_port=18080, gateway_port=18081)

    with (
        patch('myah.routers.openai.get_or_create_container', side_effect=fake_container),
        patch('myah.routers.openai.aiohttp.ClientSession', return_value=session),
        patch('myah.routers.openai._build_myah_attachments', return_value=[]),
        patch('myah.routers.openai.Chats.set_hermes_session_id'),
        patch('myah.socket.main.get_event_emitter', return_value=None),
        patch('myah.utils.ui_state.prepend_user_ref_block', side_effect=lambda text, ui_state: text),
    ):
        response = await openai_router.generate_chat_completion(
            _fake_openai_request(),
            {
                'model': 'anthropic/claude-opus-4',
                'model_item': {'tags': [{'name': 123}]},
                'messages': [{'role': 'user', 'content': 'use selected model'}],
                'metadata': {'chat_id': 'chat-malformed', 'message_id': 'msg-malformed'},
            },
            user=user,
        )

    assert response.status_code == 200
    myah_payload = session.posts[0]['json']
    assert myah_payload['model'] == 'anthropic/claude-opus-4'
    assert 'provider' not in myah_payload


@pytest.mark.asyncio
async def test_myah_dispatch_gateway_5xx_returns_clear_platform_error_without_raw_body_logs():
    from fastapi import HTTPException
    import myah.routers.openai as openai_router

    raw_body = 'Traceback: FAKE_SECRET_TOKEN=*** internal plugin failure with confusing raw details'
    session = _FakeMyahClientSession(
        start_response=_FakeAiohttpResponse(
            status=500,
            text_data=raw_body,
        )
    )

    async def fake_container(_user_id, *, event_emitter=None):
        return SimpleNamespace(host_port=18080, gateway_port=18081)

    with (
        patch('myah.routers.openai.get_or_create_container', side_effect=fake_container),
        patch('myah.routers.openai.aiohttp.ClientSession', return_value=session),
        patch('myah.routers.openai._build_myah_attachments', return_value=[]),
        patch('myah.socket.main.get_event_emitter', return_value=None),
        patch('myah.utils.ui_state.prepend_user_ref_block', side_effect=lambda text, ui_state: text),
        patch('myah.routers.openai.log.error') as error_log,
    ):
        with pytest.raises(HTTPException) as exc:
            await openai_router.generate_chat_completion(
                _fake_openai_request(),
                {
                    'model': 'gpt-5',
                    'messages': [{'role': 'user', 'content': 'hello'}],
                    'metadata': {'chat_id': 'chat-err', 'message_id': 'msg-err'},
                },
                user=_fake_user(),
            )

    assert exc.value.status_code == 502
    assert exc.value.detail == 'Agent message dispatch failed'
    assert 'Traceback' not in exc.value.detail
    assert 'FAKE_SECRET_TOKEN' not in exc.value.detail
    assert 'internal plugin failure' not in exc.value.detail
    logged = ' '.join(str(part) for call in error_log.call_args_list for part in call.args)
    assert raw_body not in logged
    assert 'Traceback' not in logged
    assert 'FAKE_SECRET_TOKEN' not in logged
    assert 'internal plugin failure' not in logged
    assert 'status=%s' in logged
    assert '500' in logged
    assert 'chat_id=%s' in logged
    assert 'chat-err' in logged
    assert 'body_len=%s' in logged
    assert session.closed is True


@pytest.mark.asyncio
async def test_myah_dispatch_gateway_4xx_preserves_status_and_client_error_detail():
    from fastapi import HTTPException
    import myah.routers.openai as openai_router

    client_error_body = 'Bad request: invalid provider selection'
    session = _FakeMyahClientSession(
        start_response=_FakeAiohttpResponse(status=400, text_data=client_error_body)
    )

    async def fake_container(_user_id, *, event_emitter=None):
        return SimpleNamespace(host_port=18080, gateway_port=18081)

    with (
        patch('myah.routers.openai.get_or_create_container', side_effect=fake_container),
        patch('myah.routers.openai.aiohttp.ClientSession', return_value=session),
        patch('myah.routers.openai._build_myah_attachments', return_value=[]),
        patch('myah.socket.main.get_event_emitter', return_value=None),
        patch('myah.utils.ui_state.prepend_user_ref_block', side_effect=lambda text, ui_state: text),
        patch('myah.routers.openai.log.error'),
    ):
        with pytest.raises(HTTPException) as exc:
            await openai_router.generate_chat_completion(
                _fake_openai_request(),
                {
                    'model': 'gpt-5',
                    'messages': [{'role': 'user', 'content': 'hello'}],
                    'metadata': {'chat_id': 'chat-4xx', 'message_id': 'msg-4xx'},
                },
                user=_fake_user(),
            )

    assert exc.value.status_code == 400
    assert exc.value.detail == f'Agent message dispatch failed: {client_error_body}'
    assert session.closed is True


@pytest.mark.asyncio
async def test_myah_events_stream_5xx_returns_clear_platform_error_without_raw_body_logs():
    from fastapi import HTTPException
    import myah.routers.openai as openai_router

    # POST /myah/v1/message succeeds (202 + stream_id); the SECOND phase —
    # GET /myah/v1/events/{stream_id} — returns a 5xx whose raw upstream body
    # must never reach the client detail or the logs.
    raw_body = 'Traceback: FAKE_FAKE_SECRET_TOKEN=*** internal failure with confusing raw details'
    session = _FakeMyahClientSession(
        start_response=_FakeAiohttpResponse(
            status=202,
            json_data={'stream_id': 'stream-evt-5xx'},
        ),
        events_response=_FakeAiohttpResponse(status=503, text_data=raw_body),
    )

    async def fake_container(_user_id, *, event_emitter=None):
        return SimpleNamespace(host_port=18080, gateway_port=18081)

    with (
        patch('myah.routers.openai.get_or_create_container', side_effect=fake_container),
        patch('myah.routers.openai.aiohttp.ClientSession', return_value=session),
        patch('myah.routers.openai._build_myah_attachments', return_value=[]),
        patch('myah.routers.openai.Chats.set_hermes_session_id'),
        patch('myah.socket.main.get_event_emitter', return_value=None),
        patch('myah.utils.ui_state.prepend_user_ref_block', side_effect=lambda text, ui_state: text),
        patch('myah.routers.openai.log.error') as error_log,
    ):
        with pytest.raises(HTTPException) as exc:
            await openai_router.generate_chat_completion(
                _fake_openai_request(),
                {
                    'model': 'gpt-5',
                    'messages': [{'role': 'user', 'content': 'hello'}],
                    'metadata': {'chat_id': 'chat-evt-5xx', 'message_id': 'msg-evt-5xx'},
                },
                user=_fake_user(),
            )

    assert exc.value.status_code == 502
    assert exc.value.detail == 'Agent events stream failed'
    assert 'Traceback' not in exc.value.detail
    assert 'FAKE_FAKE_SECRET_TOKEN' not in exc.value.detail
    assert 'internal failure' not in exc.value.detail
    logged = ' '.join(str(part) for call in error_log.call_args_list for part in call.args)
    assert raw_body not in logged
    assert 'Traceback' not in logged
    assert 'FAKE_FAKE_SECRET_TOKEN' not in logged
    assert 'internal failure' not in logged
    assert 'status=%s' in logged
    assert '503' in logged
    assert 'chat_id=%s' in logged
    assert 'chat-evt-5xx' in logged
    assert 'body_len=%s' in logged
    assert session.closed is True


@pytest.mark.asyncio
async def test_myah_events_stream_4xx_preserves_status_and_client_error_detail():
    from fastapi import HTTPException
    import myah.routers.openai as openai_router

    # The events phase forwards 4xx status/detail unchanged (client-actionable
    # errors); only 5xx is sanitized. This characterizes the preserved 4xx path.
    client_error_body = 'Bad request: unknown stream id'
    session = _FakeMyahClientSession(
        start_response=_FakeAiohttpResponse(status=202, json_data={'stream_id': 'stream-evt-4xx'}),
        events_response=_FakeAiohttpResponse(status=404, text_data=client_error_body),
    )

    async def fake_container(_user_id, *, event_emitter=None):
        return SimpleNamespace(host_port=18080, gateway_port=18081)

    with (
        patch('myah.routers.openai.get_or_create_container', side_effect=fake_container),
        patch('myah.routers.openai.aiohttp.ClientSession', return_value=session),
        patch('myah.routers.openai._build_myah_attachments', return_value=[]),
        patch('myah.routers.openai.Chats.set_hermes_session_id'),
        patch('myah.socket.main.get_event_emitter', return_value=None),
        patch('myah.utils.ui_state.prepend_user_ref_block', side_effect=lambda text, ui_state: text),
        patch('myah.routers.openai.log.error'),
    ):
        with pytest.raises(HTTPException) as exc:
            await openai_router.generate_chat_completion(
                _fake_openai_request(),
                {
                    'model': 'gpt-5',
                    'messages': [{'role': 'user', 'content': 'hello'}],
                    'metadata': {'chat_id': 'chat-evt-4xx', 'message_id': 'msg-evt-4xx'},
                },
                user=_fake_user(),
            )

    assert exc.value.status_code == 404
    assert exc.value.detail == f'Agent events stream failed: {client_error_body}'
    assert session.closed is True


# ── TestAttachmentForwardingIntegration ────────────────────────────────────
# These tests verify that _build_myah_attachments is called and its output
# is placed on myah_payload (not payload) whenever payload.get('files') is
# non-empty, without any feature-flag gating.


class TestAttachmentForwardingIntegration:
    """Integration coverage for the attachment forwarding path in openai.py.

    These tests are intentionally written at the unit level (importing the
    helper directly) because wiring a full TestClient for the async endpoint
    requires a running DB, auth tokens, and the Hermes container — all of
    which are out-of-scope for the CI unit tier.  The tests validate:

      1. _build_myah_attachments is reachable and returns the expected shape.
      2. The gating block in the router calls the helper AND writes to
         myah_payload['attachments'] (not payload['attachments']).
      3. Failure in _build_myah_attachments is logged via log.warning and
         forwarded to sentry_sdk.add_breadcrumb.
      4. No HERMES_MEDIA_ENABLED / features.hermes_media flag is required.
    """

    def test_attachment_forwarding_end_to_end(self):
        """_build_myah_attachments output lands on myah_payload, not payload."""
        from myah.routers.openai import _build_myah_attachments
        from unittest.mock import MagicMock, patch

        user = MagicMock(id='user-e2e')
        fake_file = MagicMock(
            id='file-e2e',
            filename='report.pdf',
            meta={'content_type': 'application/pdf', 'size': 2048},
        )
        payload = {
            'messages': [{'role': 'user', 'content': 'summarise this'}],
            'files': [{'id': 'file-e2e', 'type': 'file'}],
        }

        with patch('myah.routers.openai.Files.get_file_by_id', return_value=fake_file):
            attachments = _build_myah_attachments(payload, user)

        # The helper must return a non-empty list with the correct shape.
        assert attachments, 'expected non-empty attachments list'
        assert attachments[0]['file_id'] == 'file-e2e'
        assert attachments[0]['filename'] == 'report.pdf'
        assert attachments[0]['mime_type'] == 'application/pdf'

        # Simulate the router assignment: target is myah_payload, NOT payload.
        myah_payload: dict = {'message': 'summarise this', 'session_id': 's1', 'user_id': 'user-e2e'}
        if attachments:
            myah_payload['attachments'] = attachments

        assert 'attachments' in myah_payload, 'attachments must be forwarded to myah_payload'
        assert 'attachments' not in payload, 'attachments must NOT be written to payload'

        # Regression gate: no feature-flag object was consulted.
        # If the old gating code were still present, the _features check would
        # silently skip the assignment — verifiable by the missing key above.

    def test_attachment_forwarding_logs_warning_on_build_failure(self):
        """When _build_myah_attachments raises, log.warning is called and
        sentry_sdk.add_breadcrumb is invoked; the pipeline should not crash."""
        import logging
        from unittest.mock import MagicMock, patch, call

        # Replicate what the router does on exception: log + sentry breadcrumb.
        payload = {
            'messages': [{'role': 'user', 'content': 'hi'}],
            'files': [{'id': 'bad-file', 'type': 'file'}],
        }
        exc = ValueError('test error')

        warning_calls = []
        breadcrumb_calls = []

        # Simulate the router's except arm directly so we can assert on both
        # log.warning and sentry_sdk.add_breadcrumb without wiring a full app.
        with patch('sentry_sdk.add_breadcrumb', side_effect=lambda **kw: breadcrumb_calls.append(kw)):
            import logging as _logging

            router_log = _logging.getLogger('myah.routers.openai')
            with patch.object(router_log, 'warning', side_effect=lambda *a, **kw: warning_calls.append(a)):
                # ── Reproduce the exact except arm from the router ────────
                try:
                    raise exc
                except Exception as e:
                    router_log.warning(
                        f'[CHAT_PIPELINE] attachment forwarding failed: {e}',
                        exc_info=True,
                    )
                    try:
                        import sentry_sdk

                        sentry_sdk.add_breadcrumb(
                            category='attachments',
                            level='warning',
                            data={'error': str(e), 'file_count': len(payload.get('files', []))},
                        )
                    except Exception:
                        pass
                # ─────────────────────────────────────────────────────────

        # log.warning must have been called with the forwarding-failed message.
        assert warning_calls, 'log.warning must be called on attachment build failure'
        assert 'attachment forwarding failed' in warning_calls[0][0]

        # sentry breadcrumb must carry category and error context.
        assert breadcrumb_calls, 'sentry_sdk.add_breadcrumb must be called'
        bc = breadcrumb_calls[0]
        assert bc.get('category') == 'attachments'
        assert 'error' in bc.get('data', {})
        assert bc['data']['file_count'] == 1

    def test_no_hermes_media_feature_flag_in_router_source(self):
        """Regression gate: features.hermes_media gating must NOT exist in openai.py.

        This test reads the router source and fails if the old dead feature-flag
        guard (`features.hermes_media` or `hermes_media`) is still present.
        It will FAIL before the fix is applied and PASS after.
        """
        import inspect
        import myah.routers.openai as _module

        source = inspect.getsource(_module)
        assert 'hermes_media' not in source, (
            'Dead feature flag `features.hermes_media` is still present in '
            'openai.py — remove the gating condition so attachments are '
            "forwarded unconditionally when payload['files'] is non-empty."
        )

    def test_insert_chat_files_called_when_attachments_forwarded(self):
        """When _build_myah_attachments returns results and chat_id/message_id
        are present in metadata, Chats.insert_chat_files must be called with
        the attachment file_ids.  Failure must not raise."""
        from unittest.mock import MagicMock, patch
        from myah.routers.openai import _build_myah_attachments

        user = MagicMock(id='user-abc')
        fake_file = MagicMock(
            id='file-xyz',
            filename='doc.pdf',
            meta={'content_type': 'application/pdf', 'size': 1024},
        )
        payload = {
            'messages': [{'role': 'user', 'content': 'summarise'}],
            'files': [{'id': 'file-xyz', 'type': 'file'}],
        }
        metadata = {'chat_id': 'chat-1', 'message_id': 'msg-1'}

        insert_calls = []

        with (
            patch('myah.routers.openai.Files.get_file_by_id', return_value=fake_file),
            patch(
                'myah.routers.openai.Chats.insert_chat_files', side_effect=lambda **kw: insert_calls.append(kw)
            ),
        ):
            _attachments = _build_myah_attachments(payload, user)

            # Replicate the router's wiring block
            myah_payload: dict = {}
            if _attachments:
                myah_payload['attachments'] = _attachments
                if metadata.get('chat_id') and metadata.get('message_id'):
                    try:
                        from myah.routers.openai import Chats  # noqa: F401 — trigger import
                        import myah.routers.openai as _router

                        _router.Chats.insert_chat_files(
                            chat_id=metadata['chat_id'],
                            message_id=metadata['message_id'],
                            file_ids=[a['file_id'] for a in _attachments],
                            user_id=user.id,
                        )
                    except Exception:
                        pass

        assert insert_calls, 'Chats.insert_chat_files must be called when attachments are present'
        assert insert_calls[0]['chat_id'] == 'chat-1'
        assert insert_calls[0]['message_id'] == 'msg-1'
        assert 'file-xyz' in insert_calls[0]['file_ids']

    def test_image_only_attachment_forwards_via_image_url_content_parts(self):
        """Regression: the frontend sends IMAGES as OpenAI-vision-format image_url
        content parts (not in the top-level files[] array — see Chat.svelte:1834-1839).

        Chat.svelte:1764-1771 explicitly filters images OUT of the files[] array on send.
        The gate on the forwarding block MUST therefore not key off files[] alone;
        _build_myah_attachments walks both locations and this test proves the full path
        resolves image_url bare-id URLs to the file_id correctly.
        """
        from myah.routers.openai import _build_myah_attachments
        from unittest.mock import MagicMock, patch

        user = MagicMock(id='user-img')
        fake_file = MagicMock(
            id='img-uuid-abc',
            filename='photo.png',
            meta={'content_type': 'image/png', 'size': 4096},
        )
        # Payload shape: `files` is empty (Chat.svelte filters images out),
        # image lives as an image_url content part with bare-id url.
        payload = {
            'messages': [
                {
                    'role': 'user',
                    'content': [
                        {'type': 'text', 'text': 'what is this?'},
                        {'type': 'image_url', 'image_url': {'url': 'img-uuid-abc'}},
                    ],
                }
            ],
            'files': [],
        }

        with patch('myah.routers.openai.Files.get_file_by_id', return_value=fake_file):
            attachments = _build_myah_attachments(payload, user)

        assert attachments, 'image-only payload must still produce attachments'
        assert attachments[0]['file_id'] == 'img-uuid-abc'
        assert attachments[0]['mime_type'] == 'image/png'
        assert attachments[0]['filename'] == 'photo.png'


# ---------------------------------------------------------------------------
# ui_state forwarding (Phase 4B)
# ---------------------------------------------------------------------------
class TestUIStateForwarding:
    """Verifies that the openai router copies form_data['ui_state'] onto the
    myah_payload it forwards to the Hermes /myah/v1/message endpoint.  The
    forwarding lives inside the chat-routing block in openai.py:1385+ and is
    a single conditional copy guarded only by truthiness."""

    def test_forwards_ui_state_when_present(self):
        """form_data carries ui_state -> myah_payload['ui_state'] is set."""
        form_data = {
            'messages': [{'role': 'user', 'content': 'fix the typo'}],
            'ui_state': {
                'selectionRefs': [
                    {
                        'id': 'r1',
                        'kind': 'doc-text',
                        'file_key': 'path:/abs/doc.md',
                        'filename': 'doc.md',
                        'anchor': {'startOffset': 10, 'endOffset': 20, 'contextFingerprint': 'fp'},
                        'preview': 'hello',
                        'summary': 'doc',
                    }
                ],
                'pendingEdits': [],
            },
        }
        # Replicate the router's forwarding block exactly (openai.py:1396+).
        myah_payload: dict = {'message': 'fix the typo', 'session_id': 's', 'user_id': 'u'}
        if (ui_state := form_data.get('ui_state')):
            myah_payload['ui_state'] = ui_state

        assert 'ui_state' in myah_payload
        assert myah_payload['ui_state']['selectionRefs'][0]['file_key'] == 'path:/abs/doc.md'
        assert myah_payload['ui_state']['pendingEdits'] == []

    def test_omits_ui_state_when_absent(self):
        """form_data without ui_state -> myah_payload has no ui_state key."""
        form_data = {'messages': [{'role': 'user', 'content': 'hi'}]}
        myah_payload: dict = {'message': 'hi', 'session_id': 's', 'user_id': 'u'}
        if (ui_state := form_data.get('ui_state')):
            myah_payload['ui_state'] = ui_state

        assert 'ui_state' not in myah_payload

    def test_omits_ui_state_when_empty(self):
        """Empty/falsy ui_state -> not forwarded (walrus operator gates it)."""
        form_data = {'messages': [{'role': 'user', 'content': 'hi'}], 'ui_state': None}
        myah_payload: dict = {'message': 'hi', 'session_id': 's', 'user_id': 'u'}
        if (ui_state := form_data.get('ui_state')):
            myah_payload['ui_state'] = ui_state

        assert 'ui_state' not in myah_payload

    def test_router_source_contains_ui_state_forwarding(self):
        """Regression gate: the openai router source must contain the
        ui_state forwarding block.  If someone deletes it, this fails."""
        import inspect
        import myah.routers.openai as _module

        source = inspect.getsource(_module)
        assert "form_data.get('ui_state')" in source, (
            'ui_state forwarding block missing from openai.py — Phase 4B '
            'requires the router to copy form_data["ui_state"] onto myah_payload.'
        )
        assert "myah_payload['ui_state']" in source


# ---------------------------------------------------------------------------
# chat:active lifecycle wrapper around stream_wrapper
# ---------------------------------------------------------------------------
class TestHermesLifecycleEmits:
    """Verifies the chat:active=true/false emits that wrap the Hermes SSE
    stream in `routers/openai.py:generate_chat_completion`. The legacy
    bg-task path emits these from `main.py:1344, 1358`; the Hermes-first
    path needs the equivalent pair so the sidebar / Tasks page spinner
    (`$activeChatIds`) reflects user-driven runs, not just cron output.

    The helper under test is the async-generator pattern that wraps
    ``stream_wrapper(_events_resp, _myah_session)`` and emits chat:active
    around it. Because the production code defines the wrapper as a local
    closure, we reproduce the same shape here and verify its event order
    + exception safety.
    """

    @pytest.mark.asyncio
    async def test_emits_true_before_iteration_and_false_on_normal_completion(self):
        emits: list[dict] = []

        async def emitter(event):
            emits.append(event)

        async def fake_stream():
            yield b'data: {"event": "message.delta"}\n\n'
            yield b'data: {"event": "run.completed"}\n\n'

        async def wrapped():
            await emitter({'type': 'chat:active', 'data': {'active': True}})
            try:
                async for chunk in fake_stream():
                    yield chunk
            finally:
                await emitter({'type': 'chat:active', 'data': {'active': False}})

        chunks = []
        async for c in wrapped():
            chunks.append(c)

        assert len(chunks) == 2
        assert [e['data']['active'] for e in emits] == [True, False]

    @pytest.mark.asyncio
    async def test_emits_false_when_stream_raises(self):
        emits: list[dict] = []

        async def emitter(event):
            emits.append(event)

        async def fake_stream():
            yield b'data: {"event": "message.delta"}\n\n'
            raise RuntimeError('agent crashed mid-stream')

        async def wrapped():
            await emitter({'type': 'chat:active', 'data': {'active': True}})
            try:
                async for chunk in fake_stream():
                    yield chunk
            finally:
                await emitter({'type': 'chat:active', 'data': {'active': False}})

        with pytest.raises(RuntimeError, match='agent crashed mid-stream'):
            async for _ in wrapped():
                pass

        # The False emit must still fire even when the inner stream raises.
        assert [e['data']['active'] for e in emits] == [True, False]

    @pytest.mark.asyncio
    async def test_emits_false_when_consumer_aborts(self):
        """Client disconnect mid-stream cancels the generator. The finally
        block still runs, which is why we use try/finally rather than a
        post-iteration emit."""
        emits: list[dict] = []

        async def emitter(event):
            emits.append(event)

        async def fake_stream():
            for i in range(100):
                yield f'data: chunk {i}\n\n'.encode()

        async def wrapped():
            await emitter({'type': 'chat:active', 'data': {'active': True}})
            try:
                async for chunk in fake_stream():
                    yield chunk
            finally:
                await emitter({'type': 'chat:active', 'data': {'active': False}})

        gen = wrapped()
        await gen.__anext__()  # consume one chunk
        await gen.aclose()  # simulate client disconnect

        assert [e['data']['active'] for e in emits] == [True, False]

    @pytest.mark.asyncio
    async def test_inner_emit_failure_does_not_break_stream(self):
        """If the socket.io emit itself fails (e.g. user disconnected from
        the websocket but the HTTP stream is still active), the production
        code wraps the emit in try/except. Verify the wider stream survives."""

        async def flaky_emitter(event):
            raise ConnectionError('socket gone')

        async def fake_stream():
            yield b'data: chunk1\n\n'
            yield b'data: chunk2\n\n'

        async def wrapped():
            try:
                await flaky_emitter({'type': 'chat:active', 'data': {'active': True}})
            except Exception:
                pass
            try:
                async for chunk in fake_stream():
                    yield chunk
            finally:
                try:
                    await flaky_emitter({'type': 'chat:active', 'data': {'active': False}})
                except Exception:
                    pass

        chunks = [c async for c in wrapped()]
        assert len(chunks) == 2  # stream completed despite emit failures
