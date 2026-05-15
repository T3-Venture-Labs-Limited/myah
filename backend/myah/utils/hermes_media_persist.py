"""Persistence helper for agent-produced media references.

At run.completed, scans assistant message text for MEDIA:<path> tags and
external markdown image URLs, fetches each reference's bytes (via the Hermes
media proxy or direct HTTP), uploads them to platform Storage, and rewrites
the text so chat history renders correctly after container cache cleanup.

Code-fence / inline-code aware: uses a simple state machine to skip text
inside fenced code blocks (```) and inline code (`) before scanning.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import mimetypes
import re
from dataclasses import dataclass, field
from uuid import uuid4

import httpx
from loguru import logger

from myah.models.chats import Chats
from myah.models.files import FileForm, Files
from myah.storage.provider import Storage

# ── Regex patterns ─────────────────────────────────────────────────────────

# MEDIA:<path> — path must start with / or a letter; only ASCII printable path chars allowed.
# The lookahead stops at any whitespace, punctuation, emoji, or non-ASCII char.
_MEDIA_RE = re.compile(r'MEDIA:([\x21-\x7E]+?)(?=[^\x21-\x7E]|$)')

# Markdown image — ![alt](url) where url is not already a platform file URL
_MD_IMAGE_RE = re.compile(r'!\[([^\]]*)\]\(([^)]+)\)')

# ── Myah: Bare-path detection (extension + prefix hybrid) ───────────────────
# Matches agent-produced file paths written verbatim in prose (no MEDIA: tag,
# no markdown image syntax). Matched paths are fetched via the agent media
# proxy and uploaded to platform Storage so the chat survives container cache
# cleanup.
#
# Design rationale (intentional divergence from upstream extension-only approach):
# We require an absolute path under one of the well-known agent workspace
# prefixes so we never accidentally match arbitrary system paths (e.g.
# /etc/passwd.png). The extension list is derived from FILE_TYPE_REGISTRY
# in fileTypeRegistry.ts — must be kept in sync.
#
# Allowed prefixes (extended T3-1001 dogfooding 2026-04-24): the agent
# routinely writes to /tmp/, /workspace/, /data/, and the older
# /data/.hermes/cache/ path. Also /root/ (Hermes' default terminal.cwd
# inside the Myah Docker container) and /Users/<name>/ (macOS OSS Hermes
# deployments). All are accepted — the extension list and the platform's
# per-user agent container sandbox protect us from matching host paths the
# agent never writes to.
#
# Preceding boundary: whitespace, newline, (, [, {, >, =, ", ', ` or string start.
# Trailing boundary: whitespace, closing punctuation, or end-of-string.
# T3-1001 dogfooding 2026-04-24: extension list expanded to match
# _ARTIFACT_EXTENSIONS in artifact_triggers.py. Without code/config types,
# bare paths like /data/.hermes/cache/script.py would not be detected and
# the agent's response would render the raw path in inline code with no
# clickable file pill.
_BARE_PATH_EXTS = (
    # images
    r'png|jpg|jpeg|webp|gif|avif|svg'
    # audio / video
    r'|mp3|ogg|opus|wav|m4a'
    r'|mp4|mov|webm|mkv|m4v|avi'
    # docs
    r'|pdf|docx|xlsx|xls|pptx|ipynb'
    # text / markup
    r'|md|markdown|csv|tsv'
    r'|json|jsonl'
    r'|html|htm'
    r'|txt|log'
    # databases (artifact panel uses SqliteRenderer)
    r'|db|sqlite|sqlite3'
    # code
    r'|py|ts|js|tsx|jsx'
    r'|go|rs|java|cpp|c|rb|sh'
    r'|yaml|yml|toml'
)
_BARE_PATH_RE = re.compile(
    r'(?:^|(?<=[\s\n\r\t(\[{>="\'`]))'
    r'((?:/data/\.hermes/cache|/tmp|/workspace|/data|/root|/Users/[^/\s]+|/home/[^/\s]+)/[^\s<>\'"`,]+?'
    r'\.(?:' + _BARE_PATH_EXTS + r'))'
    r'(?=[\s<>\'")\]}`]|$)',
    re.IGNORECASE,
)
# ────────────────────────────────────────────────────────────────────────────

# ── Placeholder SVG for failed persists ─────────────────────────────────────

_PLACEHOLDER_SVG = (
    'data:image/svg+xml;utf8,'
    "<svg xmlns='http://www.w3.org/2000/svg' width='240' height='60'>"
    "<rect width='100%' height='100%' fill='%23eeeeee'/>"
    "<text x='50%' y='55%' font-size='12' fill='%23888' "
    "text-anchor='middle' font-family='sans-serif'>media expired</text></svg>"
)


# ── Ref dataclass ──────────────────────────────────────────────────────────


@dataclass
class _MediaRef:
    original: str  # exact substring to replace in the message text
    value: str  # the path or URL to fetch
    is_external: bool  # True if http(s), False if container path
    is_media_tag: bool  # True if MEDIA:<x>, False if ![alt](url) or bare path
    alt_text: str = field(default='')
    # ── Myah: bare-path refs ──────────────────────────────────────────────
    is_bare_path: bool = field(default=False)  # True if plain /data/.hermes/cache/... path
    # ─────────────────────────────────────────────────────────────────────


# ── Public entry point ────────────────────────────────────────────────────


async def persist_and_rewrite(
    *,
    user_id: str,
    chat_id: str,
    message_id: str = '',
    message_text: str,
    agent_base_url: str,
    agent_bearer: str,
) -> str:
    """Persist all media refs in message_text and rewrite them to platform URLs.

    Args:
        user_id: Platform user ID (used to associate file ownership).
        chat_id: Chat ID (stored in file meta for quota sweeper).
        message_id: Message ID — used to link produced files to the chat via ChatFile.
        message_text: The final assistant message text from run.completed.
        agent_base_url: Base URL of the Hermes container (e.g. http://localhost:8642).
        agent_bearer: AGENT_BEARER_TOKEN for fetching from /myah/v1/media.

    Returns:
        Rewritten message text with all media refs replaced.
    """
    refs = _collect_refs_outside_code(message_text)
    if not refs:
        return message_text

    results = await asyncio.gather(
        *(
            _persist_ref(
                ref=r,
                user_id=user_id,
                chat_id=chat_id,
                message_id=message_id,
                agent_base_url=agent_base_url,
                agent_bearer=agent_bearer,
            )
            for r in refs
        ),
        return_exceptions=True,
    )

    # Build substitution map (longest-match first to avoid prefix collisions)
    substitutions: list[tuple[str, str]] = []
    for r, result in zip(refs, results):
        if isinstance(result, Exception) or not result:
            logger.warning(f'[persist_and_rewrite] failed for {r.value!r}: {result!r}')
            replacement = _placeholder_replacement(r)
        else:
            replacement = _build_replacement(r, result)
        substitutions.append((r.original, replacement))

    rewritten = message_text
    for old, new in sorted(substitutions, key=lambda s: -len(s[0])):
        rewritten = rewritten.replace(old, new)

    # T3-1001 dogfooding 2026-04-24: When a bare path lived inside inline
    # code (e.g. `**File:** \`/data/.hermes/cache/x.csv\``), str.replace
    # above only swaps the path itself — the surrounding backticks remain,
    # producing `\`MEDIA:/api/v1/files/.../content\``. Marked then tokenises
    # the backtick span as a <code> block BEFORE the frontend's media
    # tokenizer runs, so the preview never renders. Strip the wrapping
    # backticks so the MEDIA: tag becomes real prose the tokenizer can see.
    # Safe because MEDIA: values never contain characters that would break
    # markdown if left un-coded (we control the allowed character set in
    # _MEDIA_RE).
    rewritten = re.sub(r'`(MEDIA:[^`\s]+)`', r'\1', rewritten)

    return rewritten


# ── Collect refs outside code blocks ─────────────────────────────────────


def _collect_refs_outside_code(text: str) -> list[_MediaRef]:
    """Walk text, skipping fenced code blocks but allowing bare-path matches
    inside inline code spans.

    Uses a simple state machine: tracks ``` fences and ` inline-code spans.

    **Inline code policy (T3-1001 dogfooding 2026-04-24):** Bare paths that
    appear inside backtick spans (e.g. the agent writes ``File: `/tmp/x.csv`
    created``) ARE detected and persisted. The agent's natural way of
    formatting filenames is to wrap them in backticks, and the strict
    extension + workspace-prefix whitelist on _BARE_PATH_RE protects us
    from false positives. MEDIA: tags and ![alt](url) markdown images
    inside inline code are still skipped because they have separate
    semantics (a literal string the agent is showing, not asking the
    platform to render).
    """
    refs: list[_MediaRef] = []
    i = 0
    n = len(text)
    seen: set[str] = set()  # deduplicate identical originals

    in_inline_code = False
    inline_code_end = -1

    while i < n:
        # Skip fenced code blocks (```)
        if text[i : i + 3] == '```':
            end = text.find('```', i + 3)
            if end == -1:
                break  # unclosed fence — rest is code
            i = end + 3
            in_inline_code = False
            continue

        # Track inline code (`) but DON'T skip — bare paths inside backticks
        # are valid agent output (e.g. `**File:** \`/tmp/x.csv\``).
        if text[i] == '`':
            if in_inline_code and i >= inline_code_end:
                in_inline_code = False
            elif not in_inline_code:
                end = text.find('`', i + 1)
                if end != -1:
                    in_inline_code = True
                    inline_code_end = end
            # Either way, advance past the backtick and keep scanning.
            i += 1
            continue

        # Try MEDIA: match at current position. Skip when inside inline code
        # — MEDIA: tags inside backticks are usually documentation/examples.
        if not in_inline_code:
            m = _MEDIA_RE.match(text, i)
            if m and m.group(0) not in seen:
                val = m.group(1)
                seen.add(m.group(0))
                refs.append(
                    _MediaRef(
                        original=m.group(0),
                        value=val,
                        is_external=_is_external(val),
                        is_media_tag=True,
                    )
                )
                i = m.end()
                continue

            # Try markdown image match (also skipped inside inline code)
            m2 = _MD_IMAGE_RE.match(text, i)
            if m2 and m2.group(0) not in seen:
                url = m2.group(2)
                if not url.startswith('/api/v1/files/') and not url.startswith('data:'):
                    seen.add(m2.group(0))
                    refs.append(
                        _MediaRef(
                            original=m2.group(0),
                            value=url,
                            # When the agent writes ![alt](/data/cars/car1.jpg), the URL
                            # is a container filesystem path — NOT an http(s) URL. We
                            # must route to the agent media proxy to fetch it. Only
                            # classify as external when the URL really starts with http://
                            # or https://; otherwise treat it as a container path.
                            is_external=_is_external(url),
                            is_media_tag=False,
                            alt_text=m2.group(1),
                        )
                    )
                    i = m2.end()
                    continue

        # ── Myah: bare cache-path match (allowed even inside inline code) ─
        # _BARE_PATH_RE uses lookbehind for boundary, so we search from i
        # rather than anchoring with match(). Accept the match only when it
        # starts at exactly i (i.e. the boundary char is at i-1 or i==0).
        m3 = _BARE_PATH_RE.search(text, i)
        if m3 and m3.start(1) == i and m3.group(1) not in seen:
            path = m3.group(1)
            seen.add(path)
            refs.append(
                _MediaRef(
                    original=path,
                    value=path,
                    is_external=False,
                    is_media_tag=False,
                    is_bare_path=True,
                )
            )
            i = m3.end(1)
            continue
        # ─────────────────────────────────────────────────────────────────

        i += 1

    return refs


def _is_external(val: str) -> bool:
    return val.startswith('http://') or val.startswith('https://')


# ── Fetch + upload ────────────────────────────────────────────────────────


async def _persist_ref(
    *,
    ref: _MediaRef,
    user_id: str,
    chat_id: str,
    message_id: str = '',
    agent_base_url: str,
    agent_bearer: str,
) -> str | None:
    """Fetch bytes for one ref, upload to Storage, return platform file URL."""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            if ref.is_external:
                resp = await client.get(ref.value)
            else:
                resp = await client.get(
                    f'{agent_base_url.rstrip("/")}/myah/v1/media',
                    params={'path': ref.value},
                    headers={'Authorization': f'Bearer {agent_bearer}'},
                )
            if resp.status_code != 200:
                return None
            content = resp.content
            mime = (resp.headers.get('Content-Type') or 'application/octet-stream').split(';')[0].strip()
    except Exception:
        return None

    # Derive filename
    raw_name = ref.value.split('/')[-1] or f'agent_media_{uuid4().hex[:8]}'
    # Strip query strings
    raw_name = raw_name.split('?')[0] or f'agent_media_{uuid4().hex[:8]}'
    ext = mimetypes.guess_extension(mime) or ''
    if ext and not raw_name.lower().endswith(ext):
        raw_name = f'{raw_name}{ext}'

    file_id = uuid4().hex
    storage_filename = f'{file_id}_{raw_name}'

    try:
        _, path = Storage.upload_file(io.BytesIO(content), storage_filename, {})
    except Exception:
        return None

    file_item = Files.insert_new_file(
        user_id,
        FileForm(
            id=file_id,
            filename=raw_name,
            path=path,
            hash=hashlib.sha256(content).hexdigest(),
            meta={
                'name': raw_name,
                'content_type': mime,
                'size': len(content),
                'source': 'agent_output',
                'chat_id': chat_id,
            },
            data={'status': 'completed'},
        ),
    )
    if not file_item:
        return None

    # ── Myah: link agent-produced file to chat via ChatFile ──────────────────
    if chat_id and message_id:
        try:
            Chats.insert_chat_files(
                chat_id=chat_id,
                message_id=message_id,
                file_ids=[file_item.id],
                user_id=user_id,
            )
        except Exception as _cf_exc:
            logger.warning(f'[CHAT_FILES] failed to link agent-produced file to chat: {_cf_exc}')
            try:
                import sentry_sdk

                sentry_sdk.add_breadcrumb(
                    category='chat_files',
                    level='warning',
                    data={'error': str(_cf_exc)},
                )
            except Exception:
                pass
    # ────────────────────────────────────────────────────────────────────────

    return f'/api/v1/files/{file_item.id}/content'


# ── Replacement helpers ───────────────────────────────────────────────────

_IMAGE_EXTS = {'png', 'jpg', 'jpeg', 'webp', 'gif', 'avif', 'svg'}


def _is_image_ref(value: str) -> bool:
    """Return True if `value` looks like an image filename or URL."""
    name = value.split('?')[0].split('/')[-1].lower()
    if '.' not in name:
        return False
    ext = name.rsplit('.', 1)[1]
    return ext in _IMAGE_EXTS


def _build_replacement(r: _MediaRef, persisted_url: str) -> str:
    # T3-1001 dogfooding 2026-04-24: append the original filename as a
    # query param so the frontend's MEDIA: tokenizer can correctly classify
    # the file kind. Without this, /api/v1/files/<id>/content URLs fall
    # back to 'image' (per kindOf in media-extension.ts), and a CSV/MD/code
    # file is rendered with <img>, which fails. The filename is encoded so
    # spaces and unicode survive the URL.
    from urllib.parse import quote

    original_name = r.value.split('/')[-1] or 'file'
    sep = '&' if '?' in persisted_url else '?'
    rewritten_url = f'{persisted_url}{sep}name={quote(original_name)}'

    if r.is_media_tag or r.is_bare_path:
        return f'MEDIA:{rewritten_url}'

    # Markdown image: `![alt](url)`. If the underlying file is an image, keep
    # the markdown image syntax so it renders inline. If it's a non-image
    # (CSV, MD, code, JSON, etc.) the agent mistakenly used image syntax —
    # rewrite to MEDIA: so the file pill renders instead of a broken <img>.
    if _is_image_ref(r.value):
        return f'![{r.alt_text}]({rewritten_url})'
    return f'MEDIA:{rewritten_url}'


def _placeholder_replacement(r: _MediaRef) -> str:
    # T3-1001 dogfooding 2026-04-24: ALWAYS emit a markdown image, never
    # MEDIA:<data-url>. The MEDIA: tokenizer only matches printable-ASCII
    # paths with no whitespace, but _PLACEHOLDER_SVG contains spaces inside
    # the inline SVG content, so tokenization truncates and the SVG body
    # bleeds out as raw text. Markdown ![alt](data:...) renders cleanly via
    # the standard image renderer regardless of how the original ref was
    # produced (MEDIA tag, bare path, or markdown image).
    alt = r.alt_text or 'media expired'
    return f'![{alt}]({_PLACEHOLDER_SVG})'


# ── Tool-arg-based file persistence ────────────────────────────────────────
# 2026-05-05 dogfooding (Bug 1b): persist files based on the path argument of
# write_file / patch tool calls, not just bare paths in agent prose.
#
# Why: when the agent calls write_file(path='fibonacci.py'), the file is saved
# inside the container at /root/fibonacci.py (the default cwd). The agent's
# PROSE then says "Created `fibonacci.py`" — a bare filename with no leading
# slash. The prose-scanning persist (`persist_and_rewrite`) requires absolute
# paths under known workspace prefixes, so the file is never persisted to
# platform Storage and never appears in the chat.files explorer.
#
# This helper closes that gap: for every successful write_file/patch call in
# the run, we resolve the path argument against a list of candidate cwds
# (/root, /workspace, /tmp, /data), fetch from the agent media proxy, and
# upload to platform Storage. If all candidates 404 we skip — no harm done.

# Candidate working directories the agent may have used. Order matters — the
# first one that returns 200 wins. /root is the Hermes default container cwd;
# /workspace is the spec-blessed alternative; /tmp and /data are common
# alternates. ~ is expanded to /root because that's the agent container's
# HOME env var.
_CWD_CANDIDATES: tuple[str, ...] = ('/root', '/workspace', '/tmp', '/data')

_RELATIVE_PATH_CHARS_RE = re.compile(r'^[A-Za-z0-9._/-]+$')


def _normalise_tool_path(raw: str) -> str | None:
    """Normalise a tool-arg path into a candidate string for media-proxy fetch.

    Returns None when the input doesn't look like a real file path (empty,
    URL, contains shell-meta characters, etc.). When a relative path is
    given, the FIRST candidate cwd is prepended; callers should iterate
    `iter_candidate_paths` to try alternates if the first fails.
    """
    if not raw or not isinstance(raw, str):
        return None
    p = raw.strip()
    if not p or p.startswith(('http://', 'https://', 'data:')):
        return None
    if p.startswith('~/'):
        p = '/root/' + p[2:]
    if not _RELATIVE_PATH_CHARS_RE.match(p):
        # Reject paths with whitespace, quotes, or shell metachars — those
        # almost certainly aren't real filesystem paths the agent wrote to.
        return None
    return p


def _iter_candidate_paths(raw: str) -> list[str]:
    """Return the list of paths to try, in priority order.

    Absolute paths (`/foo`) → just [/foo].
    Relative paths (`fibonacci.py`) → [/root/fibonacci.py, /workspace/fibonacci.py, ...].
    """
    norm = _normalise_tool_path(raw)
    if not norm:
        return []
    if norm.startswith('/'):
        return [norm]
    return [f'{cwd}/{norm}' for cwd in _CWD_CANDIDATES]


async def persist_tool_paths(
    *,
    user_id: str,
    chat_id: str,
    message_id: str,
    paths: list[str],
    agent_base_url: str,
    agent_bearer: str,
) -> list[tuple[str, str]]:
    """Fetch + persist files referenced by tool-arg paths.

    Each entry in `paths` is the raw `path` argument of a write_file / patch /
    similar tool call. For each, we try every candidate cwd; the first that
    returns 200 wins. The fetched bytes are uploaded to platform Storage and
    linked to the chat via Chats.insert_chat_files (handled inside
    `_persist_ref`).

    Returns a list of (resolved_path, file_id) tuples for paths that were
    successfully persisted. Failures are silently dropped — the chat continues
    rendering without the artifact rather than 500-ing.
    """
    persisted: list[tuple[str, str]] = []
    for raw in paths:
        candidates = _iter_candidate_paths(raw)
        for candidate in candidates:
            ref = _MediaRef(
                original=candidate,
                value=candidate,
                is_external=False,
                is_media_tag=False,
                is_bare_path=True,
            )
            try:
                url = await _persist_ref(
                    ref=ref,
                    user_id=user_id,
                    chat_id=chat_id,
                    message_id=message_id,
                    agent_base_url=agent_base_url,
                    agent_bearer=agent_bearer,
                )
            except Exception as e:
                logger.warning(f'[persist_tool_paths] error persisting {candidate!r}: {e}')
                continue
            if url:
                # Extract file_id from /api/v1/files/{id}/content for caller use.
                m = re.search(r'/api/v1/files/([^/]+)/content', url)
                if m:
                    persisted.append((candidate, m.group(1)))
                break  # first successful candidate wins
    return persisted
