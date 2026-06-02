"""Regression tests for legacy folder-parent move validation."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from myah.routers import folders


@pytest.mark.asyncio
async def test_legacy_folder_parent_route_rejects_self_move_without_update():
    source = SimpleNamespace(id='folder-1', user_id='user-1', name='Reports', parent_id=None)

    with (
        patch.object(folders.Folders, 'get_folder_by_id_and_user_id', return_value=source),
        patch.object(folders.Folders, 'update_folder_parent_id_by_id_and_user_id') as mock_update,
    ):
        with pytest.raises(HTTPException) as exc_info:
            await folders.update_folder_parent_id_by_id(
                id='folder-1',
                form_data=folders.FolderParentIdForm(parent_id='folder-1'),
                user=MagicMock(id='user-1'),
                db=MagicMock(),
            )

    assert exc_info.value.status_code == 422
    mock_update.assert_not_called()


@pytest.mark.asyncio
async def test_legacy_folder_parent_route_rejects_descendant_move_without_update():
    source = SimpleNamespace(id='folder-1', user_id='user-1', name='Reports', parent_id=None)
    target = SimpleNamespace(id='child-folder', user_id='user-1', name='Child', parent_id='folder-1')

    with (
        patch.object(folders.Folders, 'get_folder_by_id_and_user_id', side_effect=[source, target]),
        patch.object(folders.Folders, 'get_descendant_ids', return_value=['child-folder']),
        patch.object(folders.Folders, 'update_folder_parent_id_by_id_and_user_id') as mock_update,
    ):
        with pytest.raises(HTTPException) as exc_info:
            await folders.update_folder_parent_id_by_id(
                id='folder-1',
                form_data=folders.FolderParentIdForm(parent_id='child-folder'),
                user=MagicMock(id='user-1'),
                db=MagicMock(),
            )

    assert exc_info.value.status_code == 422
    mock_update.assert_not_called()


@pytest.mark.asyncio
async def test_legacy_folder_parent_route_rejects_missing_parent_without_update():
    source = SimpleNamespace(id='folder-1', user_id='user-1', name='Reports', parent_id=None)

    with (
        patch.object(folders.Folders, 'get_folder_by_id_and_user_id', side_effect=[source, None]),
        patch.object(folders.Folders, 'update_folder_parent_id_by_id_and_user_id') as mock_update,
    ):
        with pytest.raises(HTTPException) as exc_info:
            await folders.update_folder_parent_id_by_id(
                id='folder-1',
                form_data=folders.FolderParentIdForm(parent_id='missing-parent'),
                user=MagicMock(id='user-1'),
                db=MagicMock(),
            )

    assert exc_info.value.status_code == 404
    mock_update.assert_not_called()


@pytest.mark.asyncio
async def test_legacy_folder_parent_route_rejects_duplicate_sibling_name_without_update():
    source = SimpleNamespace(id='folder-1', user_id='user-1', name='Reports', parent_id=None)
    target = SimpleNamespace(id='target-parent', user_id='user-1', name='Parent', parent_id=None)
    duplicate = SimpleNamespace(id='other-folder', user_id='user-1', name='Reports', parent_id='target-parent')

    with (
        patch.object(folders.Folders, 'get_folder_by_id_and_user_id', side_effect=[source, target]),
        patch.object(folders.Folders, 'get_descendant_ids', return_value=[]),
        patch.object(folders.Folders, 'get_folder_by_parent_id_and_user_id_and_name', return_value=duplicate),
        patch.object(folders.Folders, 'update_folder_parent_id_by_id_and_user_id') as mock_update,
    ):
        with pytest.raises(HTTPException) as exc_info:
            await folders.update_folder_parent_id_by_id(
                id='folder-1',
                form_data=folders.FolderParentIdForm(parent_id='target-parent'),
                user=MagicMock(id='user-1'),
                db=MagicMock(),
            )

    assert exc_info.value.status_code == 400
    mock_update.assert_not_called()
