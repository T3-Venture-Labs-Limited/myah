"""Tests for artifact_triggers utility."""

import json
from pathlib import Path

import pytest

from myah.utils.artifact_triggers import (
    ARTIFACT_TOOL_NAMES,
    is_artifact_trigger_tool,
    is_artifact_extension,
    extract_path_from_tool_result,
)

# Load fixture for cross-validation
_FIXTURE_PATH = Path(__file__).parents[6] / 'src' / 'lib' / 'utils' / 'artifact-triggers.fixture.json'
_FIXTURE = json.loads(_FIXTURE_PATH.read_text())


# ── ARTIFACT_TOOL_NAMES ───────────────────────────────────────────────────────


def test_artifact_tool_names_matches_fixture():
    assert ARTIFACT_TOOL_NAMES == frozenset(_FIXTURE['tool_names'])


# ── is_artifact_trigger_tool ──────────────────────────────────────────────────


def test_write_file_is_trigger():
    assert is_artifact_trigger_tool('write_file') is True


def test_patch_is_trigger():
    assert is_artifact_trigger_tool('patch') is True


def test_image_generate_is_trigger():
    assert is_artifact_trigger_tool('image_generate') is True


def test_text_to_speech_is_trigger():
    assert is_artifact_trigger_tool('text_to_speech') is True


def test_browser_get_images_is_trigger():
    assert is_artifact_trigger_tool('browser_get_images') is True


def test_display_file_not_trigger():
    """display_file is not a registered Hermes tool — must not match."""
    assert is_artifact_trigger_tool('display_file') is False


def test_create_document_not_trigger():
    """create_document is not a registered Hermes tool — must not match."""
    assert is_artifact_trigger_tool('create_document') is False


def test_edit_file_not_trigger():
    """edit_file is not a registered Hermes tool — must not match."""
    assert is_artifact_trigger_tool('edit_file') is False


def test_browser_vision_not_trigger():
    assert is_artifact_trigger_tool('browser_vision') is False


def test_empty_string_not_trigger():
    assert is_artifact_trigger_tool('') is False


# ── is_artifact_extension ─────────────────────────────────────────────────────


def test_pdf_is_artifact_extension():
    assert is_artifact_extension('report.pdf') is True


def test_md_is_artifact_extension():
    assert is_artifact_extension('notes.md') is True


def test_markdown_is_artifact_extension():
    assert is_artifact_extension('notes.markdown') is True


def test_csv_is_artifact_extension():
    assert is_artifact_extension('data.csv') is True


def test_py_is_artifact_extension():
    assert is_artifact_extension('script.py') is True


def test_json_is_artifact_extension():
    assert is_artifact_extension('config.json') is True


def test_png_is_artifact_extension():
    """Phase 1 Task 1.3: media extensions are now artifact-eligible on the
    Python side so image_generate / browser_get_images tool.completed events
    fire artifact triggers. Note: the TS-side isArtifactExtension still
    returns False for media (delegates to fileTypeRegistry which marks them
    capability:'inline'). Phase 2B will reconcile."""
    assert is_artifact_extension('chart.png') is True


def test_jpg_is_artifact_extension():
    assert is_artifact_extension('photo.jpg') is True


def test_svg_is_artifact_extension():
    assert is_artifact_extension('icon.svg') is True


def test_mp3_is_artifact_extension():
    assert is_artifact_extension('out.mp3') is True


def test_wav_is_artifact_extension():
    assert is_artifact_extension('clip.wav') is True


def test_mp4_is_artifact_extension():
    assert is_artifact_extension('demo.mp4') is True


def test_webm_is_artifact_extension():
    assert is_artifact_extension('clip.webm') is True


def test_unknown_ext_not_artifact():
    assert is_artifact_extension('archive.rar') is False


def test_no_extension_not_artifact():
    assert is_artifact_extension('Makefile') is False


def test_path_based_input():
    assert is_artifact_extension('/data/.hermes/cache/report.pdf') is True


# ── extract_path_from_tool_result ─────────────────────────────────────────────


def test_none_returns_none():
    assert extract_path_from_tool_result(None) is None


def test_absolute_string_path():
    path = '/data/.hermes/cache/docs/report.md'
    assert extract_path_from_tool_result(path) == path


def test_relative_string_returns_none():
    assert extract_path_from_tool_result('relative/path.txt') is None


def test_dict_with_path_key():
    assert (
        extract_path_from_tool_result({'path': '/data/.hermes/cache/docs/report.md'})
        == '/data/.hermes/cache/docs/report.md'
    )


def test_dict_with_filename_key():
    assert extract_path_from_tool_result({'filename': 'out.pdf'}) == 'out.pdf'


def test_dict_with_file_path_key():
    assert extract_path_from_tool_result({'file_path': '/tmp/result.xlsx'}) == '/tmp/result.xlsx'


def test_dict_with_filepath_key():
    assert extract_path_from_tool_result({'filepath': '/tmp/result.db'}) == '/tmp/result.db'


def test_double_stringified_json_string():
    double_stringified = '{"path": "/data/file.txt"}'
    assert extract_path_from_tool_result(double_stringified) == '/data/file.txt'


def test_dict_with_double_stringified_value():
    obj = {'result': '{"path": "/data/output.csv"}'}
    assert extract_path_from_tool_result(obj) == '/data/output.csv'


def test_number_returns_none():
    assert extract_path_from_tool_result(42) is None


def test_empty_dict_returns_none():
    assert extract_path_from_tool_result({}) is None


def test_empty_path_string_falls_through_to_filename():
    assert extract_path_from_tool_result({'path': '', 'filename': 'out.txt'}) == 'out.txt'


def test_extract_path_finds_root_path_in_stdout():
    """When agent uses bash/execute_code to write a file to /root."""
    result = {'stdout': 'Saved spreadsheet to /root/financials.xlsx\nDone.', 'exit_code': 0}
    assert extract_path_from_tool_result(result) == '/root/financials.xlsx'


def test_extract_path_finds_users_path_in_stdout():
    """OSS-Myah on macOS: agent writes under /Users/<name>/."""
    result = {'output': 'Created /Users/jane/work/data.csv'}
    assert extract_path_from_tool_result(result) == '/Users/jane/work/data.csv'


def test_extract_path_still_rejects_etc_in_stdout():
    """Regression: /etc paths must not be surfaced as artifacts."""
    result = {'stdout': 'wrote to /etc/hosts.txt'}
    assert extract_path_from_tool_result(result) is None
