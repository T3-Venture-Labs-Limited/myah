"""Chat-completion payload preparation and AG-UI action helpers.

This module is the surviving slice of the OWI ``utils/middleware.py`` after the
Hermes-First pivot. The dead OWI streaming/non-streaming response chain was
removed in PR 4 (T3-987). Today this file holds:

- ``process_chat_payload`` -- unique caller from main.py for inbound chat
  completion requests; runs auth, model resolution, params merging, file
  loading, and AG-UI action interception before delegating to the chat handler.
- ``apply_params_to_form_data``, ``load_messages_from_db``,
  ``process_messages_with_output`` -- payload-prep helpers used only by
  ``process_chat_payload``.
- ``_parse_ui_action``, ``_reformat_action_for_agent``,
  ``_build_render_awareness`` -- AG-UI action interception used by
  ``process_chat_payload`` and tested by test_agui_adapter.py.
- ``set/get/clear_agent_wait_state`` -- HITL wait-state registry.
- ``get_system_oauth_token`` -- shared OAuth token resolver.

For chat *response* handling (SSE parsing, output-item rendering), see
``utils/hermes_stream_handler.py``.
"""

import json
import logging
import re
import sys

from myah.env import (
    GLOBAL_LOG_LEVEL,
)
from myah.models.chats import Chats
from myah.models.folders import Folders
from myah.models.users import UserModel
from myah.socket.main import (
    get_event_call,
    get_event_emitter,
)
from myah.utils.misc import (
    convert_logit_bias_input_to_json,
    convert_output_to_messages,
    deep_update,
    get_last_user_message,
    get_message_list,
    get_system_message,
    merge_system_messages,
    set_last_user_message_content,
    strip_empty_content_blocks,
)
from myah.utils.payload import apply_system_prompt_to_body

logging.basicConfig(stream=sys.stdout, level=GLOBAL_LOG_LEVEL)
log = logging.getLogger(__name__)








_UI_ACTION_RE = re.compile(r'\[UI_ACTION\](.*?)\[/UI_ACTION\]', re.DOTALL)


def _parse_ui_action(content: str) -> dict | None:
    """Extract a structured UI action from message content."""
    match = _UI_ACTION_RE.search(content)
    if not match:
        return None
    try:
        return json.loads(match.group(1).strip())
    except (json.JSONDecodeError, TypeError):
        return None


def _reformat_action_for_agent(action: dict) -> str:
    """Convert UI action result into structured format for agent consumption."""
    action_type = action.get('type', '')
    component_id = action.get('componentId', '')
    tool_call_id = action.get('toolCallId', '')
    result = action.get('result', {})

    if action_type == 'TOOL_CALL_RESULT':
        structured = {
            'type': 'ui_action_result',
            'componentId': component_id,
            'toolCallId': tool_call_id,
            'action': result.get('action', ''),
            'label': result.get('label', ''),
            'result': result,
        }
        log.bind(
            step='action_result',
            component_id=component_id,
            action=result.get('action', ''),
        ).debug('Forwarding structured UI action result to agent')
        return f'[UI_ACTION_RESULT] {json.dumps(structured, default=str)}'

    action_name = action.get('action', 'unknown')
    composition = action.get('composition', '')
    form_id = action.get('formId', '')
    data = action.get('data', {})
    payload = action.get('payload', {})

    if action_type == 'ui:submit':
        data_str = json.dumps(data, indent=2) if data else '{}'
        return (
            f'[User submitted form "{form_id}" on {composition} composition]\n'
            f'Action: {action_name}\n'
            f'Form data:\n{data_str}'
        )
    else:
        payload_str = f'\nPayload: {json.dumps(payload)}' if payload else ''
        return f'[User clicked "{action_name}" on {composition} composition]{payload_str}'


def _build_render_awareness(arguments: str | dict, call_id: str) -> dict | None:
    """Build a synthetic user message describing the rendered component.

    This lets the agent see what UI it rendered in subsequent conversation turns,
    so it can reason about why it rendered something and respond appropriately
    to questions like "why did you show me that?".
    """
    try:
        parsed = arguments if isinstance(arguments, dict) else json.loads(arguments)
        composition = parsed.get('composition', 'unknown')
        component_id = parsed.get('componentId', '')
        data = parsed.get('data', {})

        if composition == 'form_wizard':
            steps = data.get('steps', [])
            current = data.get('currentStep', 0)
            step_count = len(steps)
            description = (
                f"Rendered a form wizard (step {current + 1} of {step_count}) with component ID '{component_id}'."
            )
        elif composition == 'approval_card':
            options = data.get('options', data.get('actions', []))
            description = f'Rendered an approval card with options: {", ".join(options)}. Awaiting your response.'
        elif composition == 'kpi_dashboard':
            metrics = data.get('metrics', [])
            description = f"Rendered a KPI dashboard with {len(metrics)} metrics (ID: '{component_id}')."
        elif composition == 'email_reply':
            description = f"Rendered an email reply interface (ID: '{component_id}')."
        else:
            description = f"Rendered UI component '{composition}' (ID: '{component_id}')."

        log.bind(step='render_awareness', component_id=component_id, composition=composition).debug(
            'Built render awareness', call_id=call_id
        )

        return {
            'role': 'user',
            'content': f'[RENDERED_COMPONENT] {description}',
            'metadata': {
                'rendered_component': {
                    'componentId': component_id,
                    'composition': composition,
                    'callId': call_id,
                }
            },
        }
    except Exception:
        log.warning('Failed to build render awareness message', exc_info=True)
        return None


# ── HITL wait state ──────────────────────────────────────────────────────────────


import datetime as dt

_wait_states: dict[str, dict] = {}
_WAITE_EXPIRY_SECONDS = 300


def set_agent_wait_state(chat_id: str, state: dict) -> None:
    _wait_states[chat_id] = {
        **state,
        'set_at': dt.datetime.utcnow().isoformat(),
    }


def get_agent_wait_state(chat_id: str) -> dict | None:
    state = _wait_states.get(chat_id)
    if not state:
        return None
    set_at = dt.datetime.fromisoformat(state['set_at'])
    if dt.datetime.utcnow() - set_at > dt.timedelta(seconds=_WAITE_EXPIRY_SECONDS):
        del _wait_states[chat_id]
        return None
    return state


def clear_agent_wait_state(chat_id: str) -> None:
    _wait_states.pop(chat_id, None)



















def apply_params_to_form_data(form_data, model):
    params = form_data.pop('params', {})
    custom_params = params.pop('custom_params', {})

    open_webui_params = {
        'stream_response': bool,
        'stream_delta_chunk_size': int,
        'function_calling': str,
        'reasoning_tags': list,
        'system': str,
    }

    for key in list(params.keys()):
        if key in open_webui_params:
            del params[key]

    if custom_params:
        # Attempt to parse custom_params if they are strings
        for key, value in custom_params.items():
            if isinstance(value, str):
                try:
                    # Attempt to parse the string as JSON
                    custom_params[key] = json.loads(value)
                except json.JSONDecodeError:
                    # If it fails, keep the original string
                    pass

        # If custom_params are provided, merge them into params
        params = deep_update(params, custom_params)

    if isinstance(params, dict):
        for key, value in params.items():
            if value is not None:
                form_data[key] = value

    if 'logit_bias' in params and params['logit_bias'] is not None:
        try:
            logit_bias = convert_logit_bias_input_to_json(params['logit_bias'])

            if logit_bias:
                form_data['logit_bias'] = json.loads(logit_bias)
        except Exception as e:
            log.exception(f'Error parsing logit_bias: {e}')

    return form_data


# ── Myah: convert_url_images_to_base64 removed ──────────────────────────────
# Upstream Open WebUI inlined image bytes as data:image/...;base64 URLs
# because OpenAI's vision API requires that. Myah routes every interactive
# chat through the Hermes gateway (/myah/v1/message), and the gateway's
# adapter at agent/hermes/gateway/platforms/myah.py fetches file bytes
# itself from GET /api/v1/files/{id}/content using MYAH_PLATFORM_BEARER.
# Rewriting the image URL here destroys the file_id that _build_myah_attachments
# needs to forward the attachment reference — the agent then has nothing to
# fetch. Removed together with utils/files.get_image_base64_from_url (its
# sole caller) to keep the Hermes-native pass-through intact.
# ────────────────────────────────────────────────────────────────────────────


def load_messages_from_db(chat_id: str, message_id: str) -> list[dict] | None:
    """
    Load the message chain from DB up to message_id,
    keeping only LLM-relevant fields (role, content, output).
    """
    messages_map = Chats.get_messages_map_by_chat_id(chat_id)
    if not messages_map:
        return None

    db_messages = get_message_list(messages_map, message_id)
    if not db_messages:
        return None

    return [{k: v for k, v in msg.items() if k in ('role', 'content', 'output', 'files')} for msg in db_messages]


def process_messages_with_output(messages: list[dict]) -> list[dict]:
    """
    Process messages with OR-aligned output items for LLM consumption.

    For assistant messages with 'output' field, produces properly formatted
    OpenAI-style messages (tool_calls + tool results). Strips 'output' before LLM.
    """
    processed = []

    for message in messages:
        if message.get('role') == 'assistant' and message.get('output'):
            # Use output items for clean OpenAI-format messages
            output_messages = convert_output_to_messages(message['output'], raw=True)
            if output_messages:
                processed.extend(output_messages)
                continue

        # Strip 'output' field before adding (LLM shouldn't see it)
        clean_message = {k: v for k, v in message.items() if k != 'output'}
        processed.append(clean_message)

    return processed


async def process_chat_payload(request, form_data, user, metadata, model):
    # Bind correlation fields so all log lines in this request include message_id
    _message_id = (metadata or {}).get('message_id', '')
    _chat_id_ctx = (metadata or {}).get('chat_id', '')
    if _message_id:
        log.debug('Processing chat payload message_id=%s chat_id=%s', _message_id, _chat_id_ctx)

    # Set Sentry user context and message_id tag for this request.
    # Use the current scope (not new_scope) so the context propagates to
    # all downstream code in this request, including the stream handler
    # and background tasks.
    try:
        import sentry_sdk as _sentry

        if user:
            _sentry.set_user({'id': user.id, 'email': getattr(user, 'email', '')})
        if _message_id:
            _sentry.set_tag('message_id', _message_id)
        if _chat_id_ctx:
            _sentry.set_tag('chat_id', _chat_id_ctx)
    except Exception as _exc:
        log.debug('Sentry context not set: %s', _exc)

    # Pipeline Inlet -> Filter Inlet -> Chat Memory -> Chat Web Search -> Chat Image Generation
    # -> Chat Code Interpreter (Form Data Update) -> (Default) Chat Tools Function Calling
    # -> Chat Files

    form_data = apply_params_to_form_data(form_data, model)

    # Load messages from DB when available — DB preserves structured 'output' items
    # which the frontend strips, causing tool calls to be merged into content.
    chat_id = metadata.get('chat_id')
    parent_message_id = metadata.get('parent_message_id')

    if chat_id and parent_message_id and not chat_id.startswith('local:'):
        db_messages = load_messages_from_db(chat_id, parent_message_id)
        if db_messages:
            system_message = get_system_message(form_data.get('messages', []))
            form_data['messages'] = [system_message, *db_messages] if system_message else db_messages

            # Inject image files into content as image_url parts (mirrors frontend logic)
            for message in form_data['messages']:
                image_files = [
                    f
                    for f in message.get('files', [])
                    if f.get('type') == 'image' or (f.get('content_type') or '').startswith('image/')
                ]
                if message.get('role') == 'user' and image_files:
                    text_content = message.get('content', '')
                    if isinstance(text_content, str):
                        message['content'] = [
                            {'type': 'text', 'text': text_content},
                            *[
                                {
                                    'type': 'image_url',
                                    'image_url': {'url': f['url']},
                                }
                                for f in image_files
                                if f.get('url')
                            ],
                        ]
                # Strip files field — it's been incorporated into content
                message.pop('files', None)

    # Process messages with OR-aligned output items for clean LLM messages
    form_data['messages'] = process_messages_with_output(form_data.get('messages', []))

    system_message = get_system_message(form_data.get('messages', []))
    if system_message:  # Chat Controls/User Settings
        try:
            form_data = apply_system_prompt_to_body(
                system_message.get('content'), form_data, metadata, user, replace=True
            )  # Required to handle system prompt variables
        except Exception:
            pass

    # Phase 4B: removed [CURRENT_UI_STATE] injection — silently dropped
    # today (the Hermes-first chat path forwards only the user's last
    # message, not the OpenAI-format system message). Replaced by the
    # ui_state field flowing through routers/openai.py → myah_payload →
    # Hermes adapter → channel_prompt (gateway/platforms/myah.py Myah
    # marker block). See spec §7.

    # Myah: convert_url_images_to_base64 deleted — image URLs are forwarded
    # to the Hermes gateway as-is so _build_myah_attachments can resolve
    # file_ids and the agent adapter can fetch bytes directly.

    event_emitter = get_event_emitter(metadata)
    event_caller = get_event_call(metadata)

    extra_params = {
        '__event_emitter__': event_emitter,
        '__event_call__': event_caller,
        '__user__': user.model_dump() if isinstance(user, UserModel) else {},
        '__metadata__': metadata,
        '__oauth_token__': await get_system_oauth_token(request, user),
        '__request__': request,
        '__model__': model,
        '__chat_id__': metadata.get('chat_id'),
        '__message_id__': metadata.get('message_id'),
    }
    # Initialize events to store additional event to be sent to the client
    events = []
    sources = []

    # Folder "Project" handling
    # Check if the request has chat_id and is inside of a folder
    # Uses lightweight column query — only fetches folder_id, not the full chat JSON blob
    chat_id = metadata.get('chat_id', None)
    folder_id = None
    if chat_id and user:
        folder_id = Chats.get_chat_folder_id(chat_id, user.id)

    # Fallback: use folder_id from metadata (temporary chats have no DB record)
    if not folder_id:
        folder_id = metadata.get('folder_id', None)

    if folder_id and user:
        folder = Folders.get_folder_by_id_and_user_id(folder_id, user.id)

        if folder and folder.data:
            if 'system_prompt' in folder.data:
                form_data = apply_system_prompt_to_body(folder.data['system_prompt'], form_data, metadata, user)
            if 'files' in folder.data:
                form_data['files'] = [
                    *folder.data['files'],
                    *form_data.get('files', []),
                ]

    user_message = get_last_user_message(form_data['messages'])

    # ── UI Action interception ──────────────────────────────────────────────────
    _ui_action = _parse_ui_action(user_message) if user_message else None
    if _ui_action and metadata.get('is_agui_action'):
        backend_result = None
        try:
            from myah.utils.agui_action_handlers import handle_known_action

            backend_result = await handle_known_action(_ui_action, metadata)
        except ImportError:
            pass
        reformatted = _reformat_action_for_agent(_ui_action)
        if backend_result:
            reformatted += f'\n\n[System note: {backend_result}]'
        set_last_user_message_content(reformatted, form_data['messages'])
        # Refresh user_message with the reformatted content
        user_message = reformatted
    # ───────────────────────────────────────────────────────────────────────────

    form_data.pop('variables', None)

    features = form_data.pop('features', None) or {}
    extra_params['__features__'] = features

    tool_ids = form_data.pop('tool_ids', None)
    terminal_id = form_data.pop('terminal_id', None)
    files = form_data.pop('files', None)

    # legacy: drop skill_ids from stale clients (Skills migrated to Hermes filesystem)
    form_data.pop('skill_ids', None)

    if files:
        if not files:
            files = []

        for file_item in files:
            if file_item.get('type', 'file') == 'folder':
                # Get folder files
                folder_id = file_item.get('id', None)
                if folder_id:
                    folder = Folders.get_folder_by_id_and_user_id(folder_id, user.id)
                    if folder and folder.data and 'files' in folder.data:
                        files = [f for f in files if f.get('id', None) != folder_id]
                        files = [*files, *folder.data['files']]

        # files = [*files, *[{"type": "url", "url": url, "name": url} for url in urls]]
        # Remove duplicate files based on their content
        files = list({json.dumps(f, sort_keys=True): f for f in files}.values())

    metadata = {
        **metadata,
        'tool_ids': tool_ids,
        'terminal_id': terminal_id,
        'files': files,
    }
    form_data['metadata'] = metadata

    # If there are citations, add them to the data_items
    sources = [
        source
        for source in sources
        if source.get('source', {}).get('name', '') or source.get('source', {}).get('id', '')
    ]

    if len(sources) > 0:
        events.append({'sources': sources})

    # Strip empty text content blocks from multimodal messages
    # to prevent errors from providers like Gemini and Claude
    form_data['messages'] = strip_empty_content_blocks(form_data.get('messages', []))

    # Merge any duplicate system messages into a single message at position 0
    # to prevent template parsing errors with strict chat templates (e.g. Qwen)
    form_data['messages'] = merge_system_messages(form_data.get('messages', []))

    return form_data, metadata, events








async def get_system_oauth_token(request, user):
    oauth_token = None
    try:
        if request.cookies.get('oauth_session_id', None):
            oauth_token = await request.app.state.oauth_manager.get_oauth_token(
                user.id,
                request.cookies.get('oauth_session_id', None),
            )
    except Exception as e:
        log.error(f'Error getting OAuth token: {e}')
    return oauth_token


