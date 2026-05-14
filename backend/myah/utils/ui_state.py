"""Build the [USER_REFERENCED] context block from a Myah ui_state payload.

The frontend ships every chat-completion request with a ``ui_state`` object
describing what the user has attached from the artifact pane (code lines,
markdown paragraphs, spreadsheet ranges, image regions, video regions). The
agent needs to *see* that content alongside the user's prose — otherwise the
question "how many functions did I highlight" returns "0" because the agent
never receives the highlighted code.

Two delivery paths exist:

1. **Hermes ``channel_prompt``** (eventual target, blocked on
   `nousresearch/hermes-agent#17`). The Myah platform adapter inside Hermes
   would lift ``ui_state`` into ``MessageEvent.channel_prompt`` so the agent
   gets editor context cache-cheaply.

2. **Inline ``[USER_REFERENCED]`` block in the message body** (this module).
   Until #17 lands, we surface the references directly in the user's
   message text — the agent treats it as part of the prompt. The block is
   wrapped in clear sentinels so the agent recognises where the user's
   actual question starts.

Once #17 ships and the submodule is bumped, delete the call site in
``openai.py`` and let ``channel_prompt`` carry the same payload.

Format invariants:

- Single ``[USER_REFERENCED]`` open + ``[/USER_REFERENCED]`` close per request.
- Each ref's filename + summary line is prefixed with ``— `` for skim-ability.
- Code-lines previews are wrapped in a fenced code block tagged with the
  language so the agent's tokenizer / pretty-printer treats it as code.
- Sheet-cells previews use a ``tsv`` fence; image / video regions emit a
  short text description (no binary blobs survive the JSON round-trip
  anyway).
- Previews are truncated at 1500 chars to bound the prompt size — the
  frontend already truncates at this length, so this is defence in depth.
"""

from __future__ import annotations

from typing import Any

_REF_BLOCK_OPEN = '[USER_REFERENCED]'
_REF_BLOCK_CLOSE = '[/USER_REFERENCED]'
_PREVIEW_TRUNCATE = 1500


def _truncate_preview(preview: str) -> str:
    if len(preview) <= _PREVIEW_TRUNCATE:
        return preview
    omitted = len(preview) - _PREVIEW_TRUNCATE
    return preview[:_PREVIEW_TRUNCATE] + f' ... [content truncated, {omitted} chars omitted]'


def _format_ref(ref: dict[str, Any]) -> list[str]:
    """Render a single ref into a list of output lines."""
    kind = ref.get('kind') or ''
    filename = ref.get('filename') or 'unknown'
    summary = ref.get('summary') or ''
    out: list[str] = ['', f'— {filename} · {summary}']

    preview = ref.get('preview')
    anchor = ref.get('anchor') or {}

    if kind == 'code-lines' and isinstance(preview, str):
        language = anchor.get('language') or ''
        out.append(f'```{language}')
        out.append(_truncate_preview(preview))
        out.append('```')
    elif kind == 'doc-text' and isinstance(preview, str):
        out.append('```')
        out.append(_truncate_preview(preview))
        out.append('```')
    elif kind == 'sheet-cells' and isinstance(preview, str):
        # Frontend already serialises the cell matrix to TSV.
        out.append('```tsv')
        out.append(_truncate_preview(preview))
        out.append('```')
    elif kind == 'image-region' and isinstance(anchor, dict):
        x = anchor.get('xPct', 0)
        y = anchor.get('yPct', 0)
        w = anchor.get('wPct', 0)
        h = anchor.get('hPct', 0)
        out.append(f'(image region — {w:.0f}% × {h:.0f}% at {x:.0f}%, {y:.0f}%)')
    elif kind == 'video-region' and isinstance(anchor, dict):
        s = anchor.get('startSeconds', 0.0)
        e = anchor.get('endSeconds', 0.0)
        # Render as a single moment when start == end (spatial-region picks
        # use a single timestamp), otherwise as a duration. Append spatial
        # bbox metadata when the user dragged on the frame too — the agent
        # then knows BOTH "when" and "where".
        if abs(e - s) < 1e-6:
            line = f'(video moment — @ {s:.2f}s'
        else:
            line = f'(video range — {s:.2f}s..{e:.2f}s'
        x = anchor.get('xPct')
        y = anchor.get('yPct')
        w = anchor.get('wPct')
        h = anchor.get('hPct')
        if all(isinstance(v, (int, float)) for v in (x, y, w, h)):
            line += f' · region {w:.0f}% × {h:.0f}% at {x:.0f}%, {y:.0f}%'
        line += ')'
        out.append(line)

    return out


def build_user_ref_block(ui_state: dict | None) -> str:
    """Build a ``[USER_REFERENCED]`` block from a ui_state payload.

    Returns an empty string when ``ui_state`` is missing, malformed, or
    contains no ``selectionRefs`` — callers can safely concatenate the
    return value to the message text without a guard.
    """
    if not isinstance(ui_state, dict):
        return ''
    refs = ui_state.get('selectionRefs')
    if not isinstance(refs, list) or len(refs) == 0:
        return ''

    lines: list[str] = [
        _REF_BLOCK_OPEN,
        (
            'The user has attached the following selections from their workspace '
            'as context for the question that follows. Treat these as part of '
            'their question — they are referring to this content explicitly.'
        ),
    ]
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        lines.extend(_format_ref(ref))
    lines.append(_REF_BLOCK_CLOSE)
    lines.append('')
    return '\n'.join(lines)


def prepend_user_ref_block(message: str, ui_state: dict | None) -> str:
    """Return ``message`` with a ``[USER_REFERENCED]`` block prepended when
    ``ui_state`` carries any selection refs. No-op otherwise.
    """
    block = build_user_ref_block(ui_state)
    if not block:
        return message
    return block + message
