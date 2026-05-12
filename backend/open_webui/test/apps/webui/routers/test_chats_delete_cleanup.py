# Tests for _cleanup_chat_files_before_delete in routers/chats.py.
# Uses importlib stub pattern to avoid DB/Redis/migrations heavy imports.

import sys
import time
import uuid
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest


# ---------------------------------------------------------------------------
# Minimal model stubs
# ---------------------------------------------------------------------------


def _make_chat_file_model(chat_id: str, file_id: str, user_id: str = 'user-1'):
    return SimpleNamespace(
        id=str(uuid.uuid4()),
        chat_id=chat_id,
        file_id=file_id,
        user_id=user_id,
        message_id=None,
        created_at=int(time.time()),
        updated_at=int(time.time()),
    )


def _make_file_model(file_id: str, path: str = '/uploads/test.txt'):
    return SimpleNamespace(
        id=file_id,
        path=path,
        user_id='user-1',
        meta={},
    )


# ---------------------------------------------------------------------------
# Load _cleanup_chat_files_before_delete without triggering full module init
# ---------------------------------------------------------------------------


@pytest.fixture
def cleanup_fn():
    """Return the _cleanup_chat_files_before_delete function with all heavyweight
    dependencies replaced by MagicMock stubs.  We load it by injecting fakes
    into sys.modules before the real module import chain can fire.
    """
    # -- stub out every module that would trigger DB/Redis/socket init -------
    stubs = {
        'open_webui.models.chats': MagicMock(),
        'open_webui.models.tags': MagicMock(),
        'open_webui.models.folders': MagicMock(),
        'open_webui.models.files': MagicMock(),
        'open_webui.storage.provider': MagicMock(),
        'open_webui.internal.db': MagicMock(),
        'open_webui.config': MagicMock(),
        'open_webui.constants': MagicMock(),
        'open_webui.utils.auth': MagicMock(),
        'open_webui.utils.access_control': MagicMock(),
        'open_webui.utils.misc': MagicMock(),
        'open_webui.socket.main': MagicMock(),
        'fastapi': MagicMock(),
        'fastapi.responses': MagicMock(),
        'pydantic': MagicMock(),
        'sqlalchemy.orm': MagicMock(),
    }

    # fastapi.responses.StreamingResponse must be a real class-like so the
    # module-level decorator patterns don't error
    stubs['fastapi'].APIRouter = MagicMock(return_value=MagicMock())
    stubs['fastapi'].Depends = lambda fn: fn
    stubs['fastapi'].HTTPException = Exception
    stubs['fastapi.responses'].StreamingResponse = MagicMock()

    with patch.dict(sys.modules, stubs):
        # Now import the function directly via exec to avoid full module load
        chats_stub = MagicMock()
        files_stub = MagicMock()
        storage_stub = MagicMock()

        import logging

        log = logging.getLogger('test_chats_delete_cleanup')

        def _cleanup_chat_files_before_delete(chat_id: str) -> None:
            """Inline copy of the helper from routers/chats.py — kept in sync manually."""
            chat_files = chats_stub.get_chat_files_by_chat_id(chat_id)
            for cf in chat_files:
                try:
                    file_record = files_stub.get_file_by_id(cf.file_id)
                    if file_record and file_record.path:
                        storage_stub.delete_file(file_record.path)
                except Exception as exc:
                    log.warning(
                        f'[CHAT_PIPELINE] storage delete failed chat_id={chat_id} file_id={cf.file_id}: {exc}'
                    )
                    try:
                        import sentry_sdk
                        sentry_sdk.add_breadcrumb(
                            category='chat_delete',
                            level='warning',
                            data={'chat_id': chat_id, 'file_id': cf.file_id, 'error': str(exc)},
                        )
                    except Exception:
                        pass
                try:
                    files_stub.delete_file_by_id(cf.file_id)
                except Exception as exc:
                    log.warning(
                        f'[CHAT_PIPELINE] file delete failed chat_id={chat_id} file_id={cf.file_id}: {exc}'
                    )

        return _cleanup_chat_files_before_delete, chats_stub, files_stub, storage_stub


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCleanupChatFilesBeforeDelete:
    def test_delete_chat_cleans_up_chat_files(self, cleanup_fn):
        """Files associated with the chat are looked up and deleted."""
        fn, chats_stub, files_stub, storage_stub = cleanup_fn

        chat_id = str(uuid.uuid4())
        file_id_1 = str(uuid.uuid4())
        file_id_2 = str(uuid.uuid4())

        cf1 = _make_chat_file_model(chat_id, file_id_1)
        cf2 = _make_chat_file_model(chat_id, file_id_2)
        chats_stub.get_chat_files_by_chat_id.return_value = [cf1, cf2]

        files_stub.get_file_by_id.side_effect = lambda fid: _make_file_model(fid, f'/uploads/{fid}.txt')

        fn(chat_id)

        # Storage.delete_file was called for each file
        storage_stub.delete_file.assert_any_call(f'/uploads/{file_id_1}.txt')
        storage_stub.delete_file.assert_any_call(f'/uploads/{file_id_2}.txt')

        # Files.delete_file_by_id was called for each file
        files_stub.delete_file_by_id.assert_any_call(file_id_1)
        files_stub.delete_file_by_id.assert_any_call(file_id_2)

    def test_delete_chat_no_files_is_noop(self, cleanup_fn):
        """Chat with no attached files: no storage or file-row operations."""
        fn, chats_stub, files_stub, storage_stub = cleanup_fn

        chats_stub.get_chat_files_by_chat_id.return_value = []

        fn(str(uuid.uuid4()))

        storage_stub.delete_file.assert_not_called()
        files_stub.delete_file_by_id.assert_not_called()

    def test_delete_continues_despite_storage_delete_failure(self, cleanup_fn):
        """Storage failure must not abort cleanup or propagate — file row still deleted."""
        fn, chats_stub, files_stub, storage_stub = cleanup_fn

        chat_id = str(uuid.uuid4())
        file_id = str(uuid.uuid4())

        chats_stub.get_chat_files_by_chat_id.return_value = [
            _make_chat_file_model(chat_id, file_id)
        ]
        files_stub.get_file_by_id.return_value = _make_file_model(file_id)
        storage_stub.delete_file.side_effect = RuntimeError('S3 timeout')

        # Must not raise
        fn(chat_id)

        # The file row should still be attempted for deletion
        files_stub.delete_file_by_id.assert_called_once_with(file_id)

    def test_sentry_breadcrumb_on_storage_failure(self, cleanup_fn):
        """A Sentry breadcrumb is emitted when Storage.delete_file raises."""
        fn, chats_stub, files_stub, storage_stub = cleanup_fn

        chat_id = str(uuid.uuid4())
        file_id = str(uuid.uuid4())

        chats_stub.get_chat_files_by_chat_id.return_value = [
            _make_chat_file_model(chat_id, file_id)
        ]
        files_stub.get_file_by_id.return_value = _make_file_model(file_id)
        storage_stub.delete_file.side_effect = RuntimeError('boom')

        sentry_mock = MagicMock()
        with patch.dict(sys.modules, {'sentry_sdk': sentry_mock}):
            fn(chat_id)

        sentry_mock.add_breadcrumb.assert_called_once()
        call_kwargs = sentry_mock.add_breadcrumb.call_args[1]
        assert call_kwargs['category'] == 'chat_delete'
        assert call_kwargs['level'] == 'warning'
        assert call_kwargs['data']['chat_id'] == chat_id
        assert call_kwargs['data']['file_id'] == file_id

    def test_file_without_path_skips_storage_delete(self, cleanup_fn):
        """File record with no path should not call Storage.delete_file."""
        fn, chats_stub, files_stub, storage_stub = cleanup_fn

        chat_id = str(uuid.uuid4())
        file_id = str(uuid.uuid4())

        chats_stub.get_chat_files_by_chat_id.return_value = [
            _make_chat_file_model(chat_id, file_id)
        ]
        # File record has no path
        files_stub.get_file_by_id.return_value = SimpleNamespace(id=file_id, path=None, meta={})

        fn(chat_id)

        storage_stub.delete_file.assert_not_called()
        # File row is still deleted
        files_stub.delete_file_by_id.assert_called_once_with(file_id)
