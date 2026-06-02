"""Regression tests for the legacy /api/v1/files/ pagination contract."""
from unittest.mock import ANY, MagicMock, patch

import pytest

from myah.models.files import FileListResponse, FileModelResponse
from myah.routers.files import list_files


@pytest.mark.asyncio
async def test_list_files_uses_page_to_apply_paginated_model_query():
    """GET /api/v1/files/?page=N must keep the existing PAGE_SIZE pagination contract."""
    expected = FileListResponse(items=[], total=75)

    with patch('myah.routers.files.Files.get_file_list', return_value=expected) as mock_get_file_list, \
         patch('myah.routers.files.Files.list_files_by_folder') as mock_list_by_folder:
        result = await list_files(
            user=MagicMock(id='user-123', role='user'),
            page=2,
            content=True,
            db=MagicMock(),
        )

    assert result is expected
    mock_get_file_list.assert_called_once_with(user_id='user-123', skip=50, limit=50, db=ANY)
    mock_list_by_folder.assert_not_called()


@pytest.mark.asyncio
async def test_list_files_preserves_admin_bypass_and_content_stripping():
    file_response = FileModelResponse(
        id='file-1',
        user_id='admin-user',
        filename='note.txt',
        data={'content': 'large body', 'metadata': 'kept'},
        meta={'name': 'note.txt'},
        created_at=123,
    )
    expected = FileListResponse(items=[file_response], total=1)

    with patch('myah.routers.files.Files.get_file_list', return_value=expected) as mock_get_file_list:
        result = await list_files(
            user=MagicMock(id='admin-user', role='admin'),
            page=1,
            content=False,
            db=MagicMock(),
        )

    assert result.items[0].data == {'metadata': 'kept'}
    assert mock_get_file_list.call_args.kwargs['user_id'] is None
    assert mock_get_file_list.call_args.kwargs['skip'] == 0
    assert mock_get_file_list.call_args.kwargs['limit'] == 50
