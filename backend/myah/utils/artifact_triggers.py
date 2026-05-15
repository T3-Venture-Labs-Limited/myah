# KEEP IN SYNC WITH platform/src/lib/utils/artifact-triggers.ts
# and platform/src/lib/utils/artifact-triggers.fixture.json
#
# These constants are intentionally inlined here rather than read from the
# fixture JSON at runtime.  The fixture file lives under platform/src/,
# which is build-time-only — it is NOT copied into the production Docker
# image (only platform/backend/ and the compiled build/ output are).
# Reading the file at module-import time would crash uvicorn on startup
# with FileNotFoundError.  Inline the data; update both files together.

import json
import re

ARTIFACT_TOOL_NAMES: frozenset[str] = frozenset(
    {
        # Direct file-write tools (registered in agent/hermes/tools/file_tools.py).
        # write_file and patch are the two real Hermes file-mutating tools; the
        # previous list also contained display_file/create_document/edit_file,
        # which are NOT registered Hermes tools and could therefore never match
        # a real tool.completed event.
        'write_file',
        'patch',
        # Execution tools that produce files via stdout path scanning
        # (extract_path_from_tool_result handles them).
        'execute_code',
        'terminal',
        # Media-generating tools — without these listed, tool.completed events
        # for image/audio/screenshot tools would not fire artifact triggers.
        'image_generate',
        'text_to_speech',
        'browser_get_images',
    }
)

_ARTIFACT_EXTENSIONS: frozenset[str] = frozenset(
    {
        # Documents / data
        'pdf',
        'docx',
        'xlsx',
        'xls',
        'pptx',
        'csv',
        'tsv',
        'md',
        'markdown',
        'json',
        'jsonl',
        'ipynb',
        'html',
        'htm',
        'db',
        'sqlite',
        'sqlite3',
        'py',
        'ts',
        'js',
        'tsx',
        'jsx',
        'go',
        'rs',
        'java',
        'cpp',
        'c',
        'rb',
        'sh',
        'yaml',
        'yml',
        'toml',
        'txt',
        # Image (image_generate, browser_get_images)
        'png',
        'jpg',
        'jpeg',
        'gif',
        'webp',
        'svg',
        # Audio (text_to_speech)
        'mp3',
        'wav',
        'm4a',
        'ogg',
        'flac',
        # Video (terminal/execute_code via ffmpeg)
        'mp4',
        'webm',
        'mov',
        'mkv',
    }
)


def is_artifact_trigger_tool(tool_name: str) -> bool:
    return tool_name in ARTIFACT_TOOL_NAMES


def is_artifact_extension(filename_or_path: str) -> bool:
    ext = filename_or_path.rsplit('.', 1)[-1].lower() if '.' in filename_or_path else ''
    return ext in _ARTIFACT_EXTENSIONS


# T3-1001 dogfooding 2026-04-24: regex used as a *fallback* when neither a
# bare-path string nor an explicit `path`/`filename` key is present. Matches
# absolute paths in workspace prefixes ending in an artifact-capable
# extension. Mirrors the prefix list in hermes_media_persist._BARE_PATH_RE.
_TOOL_OUTPUT_PATH_RE = re.compile(
    r'(?:^|[\s\n\r\t(\[{>="\'`])'
    r'((?:/data/\.hermes/cache|/tmp|/workspace|/data|/root|/Users/[^/\s]+|/home/[^/\s]+)/'
    r'[^\s<>\'"`,]+?'
    r'\.(?:[a-zA-Z0-9]{1,8}))'
    r'(?=[\s<>\'")\]}`]|$)'
)


def extract_path_from_tool_result(result) -> str | None:
    if result is None:
        return None
    if isinstance(result, str):
        stripped = result.strip()
        if stripped.startswith('/'):
            return stripped
        try:
            parsed = json.loads(stripped)
            return extract_path_from_tool_result(parsed)
        except (json.JSONDecodeError, ValueError):
            # Fallback: scan the string body for an artifact-extension path.
            # Used for execute_code / terminal results whose stdout
            # mentions the saved file path.
            for match in _TOOL_OUTPUT_PATH_RE.finditer(stripped):
                candidate = match.group(1)
                if is_artifact_extension(candidate):
                    return candidate
            return None
    if not isinstance(result, dict):
        return None
    for key in ('path', 'filename', 'file_path', 'filepath'):
        val = result.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    # T3-1001: terminal/execute_code use 'output' for captured stdout — scan it.
    for key in ('output', 'stdout', 'result'):
        val = result.get(key)
        if isinstance(val, str):
            for match in _TOOL_OUTPUT_PATH_RE.finditer(val):
                candidate = match.group(1)
                if is_artifact_extension(candidate):
                    return candidate
    # Double-stringified
    for val in result.values():
        if isinstance(val, str):
            try:
                inner = json.loads(val)
                path = extract_path_from_tool_result(inner)
                if path:
                    return path
            except (json.JSONDecodeError, ValueError):
                pass
    return None
