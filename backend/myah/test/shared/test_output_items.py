"""Tests for the typed Hermes output-item contract.

The contract source of truth is ``platform/shared/contract/output_items.py``;
this module exercises the Pydantic validators directly so a regression in
field types or in the discriminated-union membership fails before the TS
codegen step ever runs.
"""
from __future__ import annotations

from shared.contract.output_items import ArtifactCardItem, OutputItem
from pydantic import TypeAdapter


def test_artifact_card_item_validates_minimal_fields() -> None:
    item = ArtifactCardItem(
        type='artifact_card',
        id='card-1',
        file_id='abc-123',
        filename='forecast.xlsx',
        mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        mtime=1234567890.0,
        kind='xlsx',
        summary='Forecast for Q3-Q4',
    )
    assert item.type == 'artifact_card'
    assert item.kind == 'xlsx'
    assert item.file_id == 'abc-123'
    assert item.path is None  # path is optional when file_id provided


def test_artifact_card_item_accepts_path_only() -> None:
    """Either file_id or path is acceptable — the in-flight emission path
    only has access to the container path, not a Myah file_id."""
    item = ArtifactCardItem(
        type='artifact_card',
        id='card-2',
        path='/data/.hermes/output/foo.md',
        filename='foo.md',
        kind='markdown',
        mtime=0.0,
    )
    assert item.path == '/data/.hermes/output/foo.md'
    assert item.file_id is None


def test_output_item_union_accepts_artifact_card() -> None:
    adapter = TypeAdapter(OutputItem)
    item = adapter.validate_python({
        'type': 'artifact_card',
        'id': 'card-1',
        'filename': 'foo.txt',
        'kind': 'text',
        'mtime': 0.0,
    })
    assert item.type == 'artifact_card'


def test_artifact_card_item_rejects_unknown_kind() -> None:
    """Pydantic should reject a kind value not in the Literal whitelist."""
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ArtifactCardItem(
            type='artifact_card',
            id='card-3',
            filename='x',
            kind='not-a-real-kind',  # type: ignore[arg-type]
            mtime=0.0,
        )
