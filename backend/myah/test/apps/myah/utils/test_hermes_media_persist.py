"""Tests for hermes_media_persist.persist_and_rewrite."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── collect_refs_outside_code tests ──────────────────────────────────────


def test_collect_refs_finds_media_tag():
    from myah.utils.hermes_media_persist import _collect_refs_outside_code

    refs = _collect_refs_outside_code('Look: MEDIA:/cache/images/shot.png here')
    assert len(refs) == 1
    assert refs[0].value == '/cache/images/shot.png'
    assert refs[0].is_media_tag is True


def test_collect_refs_skips_media_in_code_fence():
    from myah.utils.hermes_media_persist import _collect_refs_outside_code

    text = '```\nMEDIA:/inside/fence.png\n```'
    refs = _collect_refs_outside_code(text)
    assert len(refs) == 0


def test_collect_refs_skips_media_in_inline_code():
    from myah.utils.hermes_media_persist import _collect_refs_outside_code

    text = 'Use `MEDIA:/path/to/file.png` in your prompt'
    refs = _collect_refs_outside_code(text)
    assert len(refs) == 0


def test_collect_refs_finds_markdown_image():
    from myah.utils.hermes_media_persist import _collect_refs_outside_code

    refs = _collect_refs_outside_code('![cat](https://cdn.example.com/cat.jpg)')
    assert len(refs) == 1
    assert refs[0].value == 'https://cdn.example.com/cat.jpg'
    assert refs[0].is_media_tag is False
    assert refs[0].alt_text == 'cat'


def test_collect_refs_skips_platform_file_urls():
    from myah.utils.hermes_media_persist import _collect_refs_outside_code

    refs = _collect_refs_outside_code('![img](/api/v1/files/abc123/content)')
    assert len(refs) == 0


def test_collect_refs_skips_data_urls():
    from myah.utils.hermes_media_persist import _collect_refs_outside_code

    refs = _collect_refs_outside_code('![img](data:image/png;base64,abc)')
    assert len(refs) == 0


def test_collect_refs_deduplicates():
    from myah.utils.hermes_media_persist import _collect_refs_outside_code

    text = 'MEDIA:/shot.png and MEDIA:/shot.png again'
    refs = _collect_refs_outside_code(text)
    assert len(refs) == 1  # deduplicated by original string


def test_collect_refs_markdown_image_with_container_path_is_internal():
    """Regression: the agent writes ![car1](/data/cars/car1.jpg) — that URL is
    a filesystem path inside the Hermes container, NOT an http(s) URL. Previously
    we hard-coded is_external=True for all markdown images, which routed the
    ref to a direct HTTP GET (that would fail against '/data/cars/car1.jpg'),
    producing a 'media expired' placeholder instead of the actual image. Must
    be classified as internal so _persist_ref uses the agent media proxy.
    """
    from myah.utils.hermes_media_persist import _collect_refs_outside_code

    refs = _collect_refs_outside_code('![car1](/data/cars/car1.jpg)')
    assert len(refs) == 1
    assert refs[0].value == '/data/cars/car1.jpg'
    assert refs[0].is_external is False, (
        'Container paths like /data/cars/car1.jpg must be classified as internal '
        'so we fetch via the agent /myah/v1/media proxy, not a direct HTTP GET.'
    )
    assert refs[0].alt_text == 'car1'


def test_collect_refs_markdown_image_with_http_url_is_external():
    """External URLs must still be classified as external (direct HTTP GET)."""
    from myah.utils.hermes_media_persist import _collect_refs_outside_code

    refs = _collect_refs_outside_code('![cat](https://cdn.example.com/cat.jpg)')
    assert len(refs) == 1
    assert refs[0].is_external is True


# ── Bare-path tests ──────────────────────────────────────────────────────


def test_collect_refs_matches_bare_image_path():
    from myah.utils.hermes_media_persist import _collect_refs_outside_code

    refs = _collect_refs_outside_code('See /data/.hermes/cache/images/foo.png for details')
    assert len(refs) == 1
    assert refs[0].value == '/data/.hermes/cache/images/foo.png'
    assert refs[0].is_bare_path is True
    assert refs[0].is_media_tag is False


def test_collect_refs_skips_code_fenced_bare_paths():
    from myah.utils.hermes_media_persist import _collect_refs_outside_code

    text = '```\n/data/.hermes/cache/images/foo.png\n```'
    refs = _collect_refs_outside_code(text)
    assert len(refs) == 0


def test_collect_refs_bare_paths_inside_inline_code_are_detected():
    """Bare paths inside backtick spans ARE detected — this is intentional per the
    _collect_refs_outside_code docstring (T3-1001 2026-04-24): the agent commonly
    formats filenames as `path`, and the strict extension + prefix whitelist
    on _BARE_PATH_RE protects against false positives. Only MEDIA: tags and
    markdown images are skipped inside inline code."""
    from myah.utils.hermes_media_persist import _collect_refs_outside_code

    text = '`/data/.hermes/cache/images/foo.png`'
    refs = _collect_refs_outside_code(text)
    assert len(refs) == 1
    assert refs[0].value == '/data/.hermes/cache/images/foo.png'
    assert refs[0].is_bare_path is True


def test_collect_refs_rejects_non_cache_paths():
    from myah.utils.hermes_media_persist import _collect_refs_outside_code

    refs = _collect_refs_outside_code('see /etc/passwd.png here')
    assert len(refs) == 0


def test_collect_refs_rejects_cache_path_with_truly_unknown_extension():
    """.txt and .log are now in _BARE_PATH_EXTS — test an actually unsupported extension."""
    from myah.utils.hermes_media_persist import _collect_refs_outside_code

    refs = _collect_refs_outside_code(' /data/.hermes/cache/notes.xyz99999 ')
    assert len(refs) == 0


def test_collect_refs_txt_extension_now_matches():
    """.txt is in _BARE_PATH_EXTS — the old rejection test is now wrong; .txt must match."""
    from myah.utils.hermes_media_persist import _collect_refs_outside_code

    refs = _collect_refs_outside_code(' /data/.hermes/cache/log.txt ')
    assert len(refs) == 1
    assert refs[0].value == '/data/.hermes/cache/log.txt'


def test_collect_refs_matches_root_path():
    """Files at /root/<filename> are the agent's default working dir."""
    from myah.utils.hermes_media_persist import _collect_refs_outside_code

    refs = _collect_refs_outside_code('Saved to /root/financials.xlsx')
    assert len(refs) == 1
    assert refs[0].value == '/root/financials.xlsx'
    assert refs[0].is_bare_path is True


def test_collect_refs_matches_users_path():
    """OSS-Myah users on macOS will have terminal.cwd under /Users/<name>."""
    from myah.utils.hermes_media_persist import _collect_refs_outside_code

    refs = _collect_refs_outside_code('Generated /Users/jane/workspace/report.csv')
    assert len(refs) == 1
    assert refs[0].value == '/Users/jane/workspace/report.csv'


def test_collect_refs_still_rejects_etc_path():
    """Path traversal defense — /etc/<file>.<ext> must NOT match."""
    from myah.utils.hermes_media_persist import _collect_refs_outside_code

    refs = _collect_refs_outside_code('see /etc/passwd.png')
    assert len(refs) == 0


# ── Video extension coverage ───────────────────────────────────────────
# Without these, agents using yt-dlp (which defaults to .mkv), ffmpeg
# screen-capture (often .mp4 or .mov), or saving any video output would
# have their files silently dropped from the rewrite pass.


@pytest.mark.parametrize(
    'ext',
    ['mp4', 'mov', 'webm', 'mkv', 'm4v', 'avi'],
)
def test_collect_refs_matches_bare_video_extensions(ext: str):
    """Common video container formats must all be detected as bare paths."""
    from myah.utils.hermes_media_persist import _collect_refs_outside_code

    refs = _collect_refs_outside_code(f'Recorded /data/clip.{ext} successfully.')
    assert len(refs) == 1, f'.{ext} bare path was not detected'
    assert refs[0].value == f'/data/clip.{ext}'
    assert refs[0].is_bare_path is True


@pytest.mark.parametrize(
    'ext',
    ['mp4', 'mov', 'webm', 'mkv', 'm4v', 'avi'],
)
def test_collect_refs_matches_media_tag_video_extensions(ext: str):
    """MEDIA: tags wrapping video paths must also be detected."""
    from myah.utils.hermes_media_persist import _collect_refs_outside_code

    refs = _collect_refs_outside_code(f'Saved: MEDIA:/data/clip.{ext}')
    assert len(refs) == 1, f'MEDIA: tag with .{ext} was not detected'
    assert refs[0].value == f'/data/clip.{ext}'
    assert refs[0].is_media_tag is True


# ── persist_and_rewrite integration tests ──────────────────────────────


def test_persist_and_rewrite_empty_text_returns_unchanged():
    from myah.utils.hermes_media_persist import persist_and_rewrite

    result = asyncio.get_event_loop().run_until_complete(
        persist_and_rewrite(
            user_id='u1',
            chat_id='c1',
            message_text='Hello, no media here.',
            agent_base_url='http://localhost:8642',
            agent_bearer='tok',
        )
    )
    assert result == 'Hello, no media here.'


def test_persist_and_rewrite_successful_media_tag():
    from myah.utils.hermes_media_persist import persist_and_rewrite

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = b'\xff\xd8\xff' + b'\x00' * 50
    mock_response.headers = {'Content-Type': 'image/jpeg'}

    mock_file_item = MagicMock()
    mock_file_item.id = 'stored-file-id'

    async def run():
        with (
            patch('httpx.AsyncClient') as mock_client_class,
            patch('myah.utils.hermes_media_persist.Storage') as mock_storage,
            patch('myah.utils.hermes_media_persist.Files') as mock_files,
        ):
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            mock_storage.upload_file.return_value = (None, 'storage/path/file.jpg')
            mock_files.insert_new_file.return_value = mock_file_item

            result = await persist_and_rewrite(
                user_id='u1',
                chat_id='c1',
                message_text='Here is the image: MEDIA:/cache/images/shot.jpg',
                agent_base_url='http://localhost:8642',
                agent_bearer='tok',
            )
        return result

    result = asyncio.get_event_loop().run_until_complete(run())
    assert '/api/v1/files/stored-file-id/content' in result
    assert 'MEDIA:/cache/images/shot.jpg' not in result


def test_persist_and_rewrite_on_fetch_failure_substitutes_placeholder():
    from myah.utils.hermes_media_persist import persist_and_rewrite

    async def run():
        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=Exception('connection refused'))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = await persist_and_rewrite(
                user_id='u1',
                chat_id='c1',
                message_text='MEDIA:/cache/images/shot.png',
                agent_base_url='http://localhost:8642',
                agent_bearer='tok',
            )
        return result

    result = asyncio.get_event_loop().run_until_complete(run())
    # Should contain the SVG placeholder
    assert 'data:image/svg+xml' in result or 'media expired' in result
    assert 'MEDIA:/cache/images/shot.png' not in result


def test_persist_and_rewrite_preserves_code_block():
    from myah.utils.hermes_media_persist import persist_and_rewrite

    text = 'Normal: MEDIA:/shot.png\n```\nMEDIA:/skip.png\n```'

    async def run():
        with patch(
            'myah.utils.hermes_media_persist._persist_ref',
            new=AsyncMock(return_value='/api/v1/files/new-id/content'),
        ) as mock_persist:
            result = await persist_and_rewrite(
                user_id='u1',
                chat_id='c1',
                message_text=text,
                agent_base_url='http://agent',
                agent_bearer='tok',
            )
        return result, mock_persist

    result, mock_persist = asyncio.get_event_loop().run_until_complete(run())
    # Only one ref should have been processed (the one outside the code block)
    assert mock_persist.call_count == 1
    assert 'MEDIA:/skip.png' in result  # code block content unchanged


def test_persist_and_rewrite_inserts_chat_file():
    """After a successful file persist, Chats.insert_chat_files must be called
    with the produced file_id, chat_id, message_id, and user_id."""
    from myah.utils.hermes_media_persist import persist_and_rewrite

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = b'\xff\xd8\xff' + b'\x00' * 50
    mock_response.headers = {'Content-Type': 'image/jpeg'}

    mock_file_item = MagicMock()
    mock_file_item.id = 'agent-file-id'

    insert_calls = []

    async def run():
        with (
            patch('httpx.AsyncClient') as mock_client_class,
            patch('myah.utils.hermes_media_persist.Storage') as mock_storage,
            patch('myah.utils.hermes_media_persist.Files') as mock_files,
            patch('myah.utils.hermes_media_persist.Chats') as mock_chats,
        ):
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            mock_storage.upload_file.return_value = (None, 'storage/path/file.jpg')
            mock_files.insert_new_file.return_value = mock_file_item
            mock_chats.insert_chat_files.side_effect = lambda **kw: insert_calls.append(kw)

            result = await persist_and_rewrite(
                user_id='u1',
                chat_id='chat-abc',
                message_id='msg-xyz',
                message_text='Here is the image: MEDIA:/cache/images/shot.jpg',
                agent_base_url='http://localhost:8642',
                agent_bearer='tok',
            )
        return result

    result = asyncio.get_event_loop().run_until_complete(run())

    assert '/api/v1/files/agent-file-id/content' in result
    assert insert_calls, 'Chats.insert_chat_files must be called after a successful file persist'
    call = insert_calls[0]
    assert call['chat_id'] == 'chat-abc'
    assert call['message_id'] == 'msg-xyz'
    assert 'agent-file-id' in call['file_ids']
    assert call['user_id'] == 'u1'


def test_persist_and_rewrite_skips_chat_file_when_no_message_id():
    """When message_id is absent (empty string), insert_chat_files must NOT be called."""
    from myah.utils.hermes_media_persist import persist_and_rewrite

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = b'\xff\xd8\xff' + b'\x00' * 50
    mock_response.headers = {'Content-Type': 'image/jpeg'}

    mock_file_item = MagicMock()
    mock_file_item.id = 'agent-file-id-2'

    insert_calls = []

    async def run():
        with (
            patch('httpx.AsyncClient') as mock_client_class,
            patch('myah.utils.hermes_media_persist.Storage') as mock_storage,
            patch('myah.utils.hermes_media_persist.Files') as mock_files,
            patch('myah.utils.hermes_media_persist.Chats') as mock_chats,
        ):
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            mock_storage.upload_file.return_value = (None, 'storage/path/file.jpg')
            mock_files.insert_new_file.return_value = mock_file_item
            mock_chats.insert_chat_files.side_effect = lambda **kw: insert_calls.append(kw)

            await persist_and_rewrite(
                user_id='u1',
                chat_id='chat-abc',
                message_id='',  # no message_id
                message_text='MEDIA:/cache/images/shot.jpg',
                agent_base_url='http://localhost:8642',
                agent_bearer='tok',
            )

    asyncio.get_event_loop().run_until_complete(run())
    assert insert_calls == [], 'insert_chat_files must NOT be called when message_id is empty'


def test_persist_and_rewrite_chat_file_failure_does_not_abort():
    """If insert_chat_files raises, persist_and_rewrite must still return the rewritten URL."""
    from myah.utils.hermes_media_persist import persist_and_rewrite

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = b'\xff\xd8\xff' + b'\x00' * 50
    mock_response.headers = {'Content-Type': 'image/jpeg'}

    mock_file_item = MagicMock()
    mock_file_item.id = 'agent-file-id-3'

    async def run():
        with (
            patch('httpx.AsyncClient') as mock_client_class,
            patch('myah.utils.hermes_media_persist.Storage') as mock_storage,
            patch('myah.utils.hermes_media_persist.Files') as mock_files,
            patch('myah.utils.hermes_media_persist.Chats') as mock_chats,
        ):
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            mock_storage.upload_file.return_value = (None, 'storage/path/file.jpg')
            mock_files.insert_new_file.return_value = mock_file_item
            mock_chats.insert_chat_files.side_effect = RuntimeError('DB down')

            result = await persist_and_rewrite(
                user_id='u1',
                chat_id='chat-abc',
                message_id='msg-xyz',
                message_text='MEDIA:/cache/images/shot.jpg',
                agent_base_url='http://localhost:8642',
                agent_bearer='tok',
            )
        return result

    result = asyncio.get_event_loop().run_until_complete(run())
    # The rewrite must still succeed — ChatFile failure must not abort the pipeline
    assert '/api/v1/files/agent-file-id-3/content' in result
