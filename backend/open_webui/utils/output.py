"""Output item formatting utilities.

Pure functions for generating IDs, serializing OR-aligned output items
to HTML, and extracting render_ui compositions from message content.
"""

import html
import json
import re
from uuid import uuid4


def output_id(prefix: str) -> str:
    """Generate OR-style ID: prefix + 24-char hex UUID."""
    return f'{prefix}_{uuid4().hex[:24]}'


def split_content_and_whitespace(content):
    content_stripped = content.rstrip()
    original_whitespace = content[len(content_stripped) :] if len(content) > len(content_stripped) else ''
    return content_stripped, original_whitespace


def is_opening_code_block(content):
    backtick_segments = content.split('```')
    # Even number of segments means the last backticks are opening a new block
    return len(backtick_segments) > 1 and len(backtick_segments) % 2 == 0


def extract_render_ui_from_content(output: list, event_emitter=None, metadata: dict | None = None) -> list:
    """Scan message items in *output* for JSON code fences that look like
    render_ui calls (containing a ``composition`` or ``blocks`` key).

    When found, the code fence is stripped from the message text and replaced
    with a synthetic ``function_call`` + ``function_call_output`` item pair so
    the frontend renders the data as a DeclarativeUI visual component instead of
    a raw JSON code block.

    Returns a new output list (the original is not mutated in-place).
    """
    import re
    import uuid as _uuid

    # Pattern 1: JSON code fences with composition/blocks keys
    CODE_FENCE_RE = re.compile(r'```(?:json)?\s*\n(\{[\s\S]*?\})\n```', re.MULTILINE)
    # Pattern 2: [RENDER_UI]{json}[/RENDER_UI] markers from render_ui tool handler
    RENDER_MARKER_RE = re.compile(r'\[RENDER_UI\](.*?)\[/RENDER_UI\]', re.DOTALL)

    def _make_synthetic_items(parsed: dict, new_output: list) -> bool:
        """Create synthetic function_call + function_call_output items.
        Returns True if items were added."""
        if not isinstance(parsed, dict):
            return False
        if 'composition' not in parsed and 'blocks' not in parsed:
            return False

        call_id = f'synth_{_uuid.uuid4().hex[:20]}'
        arguments = json.dumps(parsed)

        new_output.append(
            {
                'type': 'function_call',
                'id': f'fc_{_uuid.uuid4().hex[:24]}',
                'call_id': call_id,
                'name': 'render_ui',
                'arguments': arguments,
                'status': 'completed',
            }
        )

        # Build declarative spec
        declarative = None
        if 'blocks' in parsed:
            declarative = parsed
        elif 'composition' in parsed:
            try:
                from open_webui.utils.agui_compositions import expand_composition

                declarative = expand_composition(parsed['composition'], parsed.get('data', {}))
            except (KeyError, Exception):
                pass

        result_item: dict = {
            'type': 'function_call_output',
            'id': f'fco_{_uuid.uuid4().hex[:24]}',
            'call_id': call_id,
            'output': [{'type': 'input_text', 'text': 'Rendered successfully.'}],
            'status': 'completed',
        }
        if declarative:
            result_item['declarative'] = declarative
        new_output.append(result_item)
        return True

    new_output: list = []
    for item in output:
        if item.get('type') != 'message':
            new_output.append(item)
            continue

        # Collect all text parts into a single string so we can scan across parts
        parts = item.get('content', [])
        full_text = ''.join(p.get('text', '') for p in parts if p.get('type') == 'output_text')
        if not full_text:
            new_output.append(item)
            continue

        cleaned = full_text
        found_any = False

        # Scan for [RENDER_UI] markers (from render_ui tool handler output)
        for match in RENDER_MARKER_RE.finditer(cleaned):
            try:
                parsed = json.loads(match.group(1))
            except (json.JSONDecodeError, TypeError):
                continue
            if _make_synthetic_items(parsed, new_output):
                cleaned = cleaned.replace(match.group(0), '', 1)
                found_any = True

        # Also strip "Rendered successfully." lines left behind by the marker extraction
        if found_any:
            cleaned = re.sub(r'Rendered successfully\.\s*', '', cleaned)

        # Scan for JSON code fences (agent wrote JSON in text instead of calling tool)
        for match in CODE_FENCE_RE.finditer(cleaned):
            try:
                parsed = json.loads(match.group(1))
            except (json.JSONDecodeError, TypeError):
                continue
            if _make_synthetic_items(parsed, new_output):
                cleaned = cleaned.replace(match.group(0), '', 1)
                found_any = True

        if found_any:
            # Rebuild the message item with stripped text
            cleaned = cleaned.strip()
            if cleaned:
                new_item = dict(item)
                new_item['content'] = [{'type': 'output_text', 'text': cleaned}]
                new_output.append(new_item)
            # (if nothing remains, drop the message item entirely)
        else:
            new_output.append(item)

    return new_output


def serialize_output(output: list) -> str:
    """
    Convert OR-aligned output items to HTML for display.
    For LLM consumption, use convert_output_to_messages() instead.
    """
    content = ''

    # First pass: collect function_call_output items by call_id for lookup
    tool_outputs = {}
    for item in output:
        if item.get('type') == 'function_call_output':
            tool_outputs[item.get('call_id')] = item

    # Second pass: render items in order
    for idx, item in enumerate(output):
        item_type = item.get('type', '')

        if item_type == 'message':
            for content_part in item.get('content', []):
                if 'text' in content_part:
                    text = content_part.get('text', '').strip()
                    if text:
                        content = f'{content}{text}\n'

        elif item_type == 'function_call':
            # Render tool call inline with its result (if available)
            if content and not content.endswith('\n'):
                content += '\n'

            call_id = item.get('call_id', '')
            name = item.get('name', '')
            arguments = item.get('arguments', '')

            result_item = tool_outputs.get(call_id)
            if result_item:
                result_text = ''
                for result_output in result_item.get('output', []):
                    if 'text' in result_output:
                        output_text = result_output.get('text', '')
                        result_text += str(output_text) if not isinstance(output_text, str) else output_text
                files = result_item.get('files')
                embeds = result_item.get('embeds', '')
                declarative = result_item.get('declarative')

                declarative_attr = f' declarative="{html.escape(json.dumps(declarative))}"' if declarative else ''
                content += f'<details type="tool_calls" done="true" id="{call_id}" name="{name}" arguments="{html.escape(json.dumps(arguments))}" result="{html.escape(json.dumps(result_text, ensure_ascii=False))}" files="{html.escape(json.dumps(files)) if files else ""}" embeds="{html.escape(json.dumps(embeds))}"{declarative_attr}>\n<summary>Tool Executed</summary>\n</details>\n'
            else:
                content += f'<details type="tool_calls" done="false" id="{call_id}" name="{name}" arguments="{html.escape(json.dumps(arguments))}">\n<summary>Executing...</summary>\n</details>\n'

        elif item_type == 'function_call_output':
            # Already handled inline with function_call above
            pass

        elif item_type == 'reasoning':
            reasoning_content = ''
            # Check for 'summary' (new structure) or 'content' (legacy/fallback)
            source_list = item.get('summary', []) or item.get('content', [])
            for content_part in source_list:
                if 'text' in content_part:
                    reasoning_content += content_part.get('text', '')
                elif 'summary' in content_part:  # Handle potential nested logic if any
                    pass

            reasoning_content = reasoning_content.strip()

            duration = item.get('duration')
            status = item.get('status', 'in_progress')

            # Infer completion: if this reasoning item is NOT the last item,
            # render as done (a subsequent item means reasoning is complete)
            is_last_item = idx == len(output) - 1

            if content and not content.endswith('\n'):
                content += '\n'

            display = html.escape(
                '\n'.join(
                    (f'> {line}' if not line.startswith('>') else line) for line in reasoning_content.splitlines()
                )
            )

            if status == 'completed' or duration is not None or not is_last_item:
                content = f'{content}<details type="reasoning" done="true" duration="{duration or 0}">\n<summary>Thought for {duration or 0} seconds</summary>\n{display}\n</details>\n'
            else:
                content = f'{content}<details type="reasoning" done="false">\n<summary>Thinking…</summary>\n{display}\n</details>\n'

        elif item_type == 'open_webui:code_interpreter':
            content_stripped, original_whitespace = split_content_and_whitespace(content)
            if is_opening_code_block(content_stripped):
                content = content_stripped.rstrip('`').rstrip() + original_whitespace
            else:
                content = content_stripped + original_whitespace

            if content and not content.endswith('\n'):
                content += '\n'

            # Render the code_interpreter item as a <details> block
            # so the frontend Collapsible renders "Analyzing..."/"Analyzed".
            code = item.get('code', '').strip()
            lang = item.get('lang', 'python')
            status = item.get('status', 'in_progress')
            duration = item.get('duration')
            is_last_item = idx == len(output) - 1

            # Build inner content: code block
            display = ''
            if code:
                display = f'```{lang}\n{code}\n```'

            # Build output attribute as HTML-escaped JSON for CodeBlock.svelte
            ci_output = item.get('output')
            output_attr = ''
            if ci_output:
                if isinstance(ci_output, dict):
                    output_json = json.dumps(ci_output, ensure_ascii=False)
                else:
                    output_json = json.dumps({'result': str(ci_output)}, ensure_ascii=False)
                output_attr = f' output="{html.escape(output_json)}"'

            if status == 'completed' or duration is not None or not is_last_item:
                content += f'<details type="code_interpreter" done="true" duration="{duration or 0}"{output_attr}>\n<summary>Analyzed</summary>\n{display}\n</details>\n'
            else:
                content += f'<details type="code_interpreter" done="false"{output_attr}>\n<summary>Analyzing…</summary>\n{display}\n</details>\n'

    return content.strip()
