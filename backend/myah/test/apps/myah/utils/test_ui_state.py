"""Tests for ``myah.utils.ui_state.build_user_ref_block`` /
``prepend_user_ref_block``.

These verify the canonical answer to "did the agent receive the user's
selection?" — the backend turns the frontend's ``ui_state.selectionRefs``
into a ``[USER_REFERENCED]`` block prepended to the message text, so the
agent sees the highlighted code as part of the prompt.
"""

from myah.utils.ui_state import build_user_ref_block, prepend_user_ref_block


# ── build_user_ref_block ───────────────────────────────────────────────


def test_no_ui_state_returns_empty():
    assert build_user_ref_block(None) == ''
    assert build_user_ref_block({}) == ''
    assert build_user_ref_block({'selectionRefs': []}) == ''


def test_malformed_ui_state_returns_empty():
    # Not a dict → empty.
    assert build_user_ref_block('garbage') == ''
    # selectionRefs not a list → empty.
    assert build_user_ref_block({'selectionRefs': 'not-a-list'}) == ''


def test_code_lines_ref_renders_with_language_fence():
    ui_state = {
        'selectionRefs': [
            {
                'kind': 'code-lines',
                'filename': 'fibonacci.py',
                'summary': 'fibonacci.py · L21-L39 · 19 lines',
                'anchor': {'startLine': 21, 'endLine': 39, 'language': 'python'},
                'preview': 'def fibonacci_recursive(n):\n    return n',
            }
        ]
    }
    block = build_user_ref_block(ui_state)
    assert block.startswith('[USER_REFERENCED]')
    assert '[/USER_REFERENCED]' in block
    assert 'fibonacci.py' in block
    assert '```python' in block
    assert 'def fibonacci_recursive(n):' in block


def test_doc_text_ref_renders_with_plain_fence():
    ui_state = {
        'selectionRefs': [
            {
                'kind': 'doc-text',
                'filename': 'readme.md',
                'summary': '2 paragraphs · 14 words',
                'anchor': {'startOffset': 0, 'endOffset': 80, 'contextFingerprint': ''},
                'preview': 'This workspace is used for end-to-end testing.',
            }
        ]
    }
    block = build_user_ref_block(ui_state)
    assert 'readme.md' in block
    assert '2 paragraphs · 14 words' in block
    assert 'This workspace is used' in block


def test_sheet_cells_ref_renders_as_tsv():
    ui_state = {
        'selectionRefs': [
            {
                'kind': 'sheet-cells',
                'filename': 'data.csv',
                'summary': 'Sheet1 · A1:B2 · 4 cells',
                'anchor': {'sheet': 'Sheet1', 'range': 'A1:B2'},
                'preview': 'name\tqty\napple\t3',
            }
        ]
    }
    block = build_user_ref_block(ui_state)
    assert '```tsv' in block
    assert 'name\tqty' in block


def test_image_region_describes_without_data_url():
    ui_state = {
        'selectionRefs': [
            {
                'kind': 'image-region',
                'filename': 'pic.png',
                'summary': '50% × 60% region',
                'anchor': {'xPct': 10, 'yPct': 20, 'wPct': 50, 'hPct': 60},
            }
        ]
    }
    block = build_user_ref_block(ui_state)
    assert 'image region' in block
    # No raw bytes / data URL leakage.
    assert 'data:image' not in block


def test_video_region_describes_with_seconds():
    ui_state = {
        'selectionRefs': [
            {
                'kind': 'video-region',
                'filename': 'clip.mp4',
                'summary': '4.00s..8.50s',
                'anchor': {'startSeconds': 4.0, 'endSeconds': 8.5},
            }
        ]
    }
    block = build_user_ref_block(ui_state)
    assert '4.00s' in block
    assert '8.50s' in block
    # Pure time range → "video range" wording, no spatial bbox metadata.
    assert 'video range' in block
    assert 'region' not in block.split('[USER_REFERENCED]', 1)[1].split('—', 1)[0]


def test_video_region_with_spatial_bbox_includes_both():
    ui_state = {
        'selectionRefs': [
            {
                'kind': 'video-region',
                'filename': 'clip.mp4',
                'summary': '7.20s · region 50% × 60%',
                'anchor': {
                    'startSeconds': 7.2,
                    'endSeconds': 7.2,
                    'xPct': 25,
                    'yPct': 30,
                    'wPct': 50,
                    'hPct': 60,
                },
            }
        ]
    }
    block = build_user_ref_block(ui_state)
    # Single-moment timestamp wording.
    assert 'video moment' in block
    assert '7.20s' in block
    # Spatial bbox surfaces with percentages.
    assert '50% × 60%' in block
    assert 'at 25%, 30%' in block


def test_truncates_long_previews():
    long_preview = 'x' * 3000
    ui_state = {
        'selectionRefs': [
            {
                'kind': 'doc-text',
                'filename': 'big.md',
                'summary': 'big · 3000 chars',
                'anchor': {'startOffset': 0, 'endOffset': 3000, 'contextFingerprint': ''},
                'preview': long_preview,
            }
        ]
    }
    block = build_user_ref_block(ui_state)
    assert 'content truncated' in block
    # Bound the total block size — the preview is the dominant chunk.
    assert len(block) < 2300


def test_emits_one_block_for_multiple_refs():
    ui_state = {
        'selectionRefs': [
            {
                'kind': 'code-lines',
                'filename': 'a.py',
                'summary': 'a.py · L1',
                'anchor': {'startLine': 1, 'endLine': 1, 'language': 'python'},
                'preview': 'one',
            },
            {
                'kind': 'code-lines',
                'filename': 'b.py',
                'summary': 'b.py · L1',
                'anchor': {'startLine': 1, 'endLine': 1, 'language': 'python'},
                'preview': 'two',
            },
        ]
    }
    block = build_user_ref_block(ui_state)
    assert block.count('[USER_REFERENCED]') == 1
    assert block.count('[/USER_REFERENCED]') == 1
    assert 'a.py' in block
    assert 'b.py' in block


def test_skips_malformed_individual_refs():
    ui_state = {
        'selectionRefs': [
            'not-a-dict',
            {
                'kind': 'code-lines',
                'filename': 'a.py',
                'summary': 'a.py · L1',
                'anchor': {'startLine': 1, 'endLine': 1, 'language': 'python'},
                'preview': 'one',
            },
        ]
    }
    block = build_user_ref_block(ui_state)
    assert 'a.py' in block
    # Sentinel still wraps the surviving ref.
    assert block.startswith('[USER_REFERENCED]')


# ── prepend_user_ref_block ─────────────────────────────────────────────


def test_prepend_no_ui_state_is_noop():
    assert prepend_user_ref_block('hello', None) == 'hello'
    assert prepend_user_ref_block('hello', {}) == 'hello'
    assert prepend_user_ref_block('hello', {'selectionRefs': []}) == 'hello'


def test_prepend_attaches_block_then_message():
    ui_state = {
        'selectionRefs': [
            {
                'kind': 'code-lines',
                'filename': 'fibonacci.py',
                'summary': 'fibonacci.py · L21',
                'anchor': {'startLine': 21, 'endLine': 21, 'language': 'python'},
                'preview': 'return n',
            }
        ]
    }
    out = prepend_user_ref_block('How many functions did I highlight?', ui_state)
    assert out.startswith('[USER_REFERENCED]')
    assert out.endswith('How many functions did I highlight?')
    assert 'return n' in out
