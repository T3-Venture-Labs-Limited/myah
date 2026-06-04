def first_user_text_from_messages(form_data: dict) -> str:
    """Return the newest user text from an OpenAI-style chat payload.

    Handles string content, list content with text parts, and malformed entries
    without raising so this can safely run as a pre-flight guard.
    """
    messages = form_data.get('messages') or []
    if not isinstance(messages, list):
        return ''

    for message in reversed(messages):
        if not isinstance(message, dict) or message.get('role') != 'user':
            continue

        content = message.get('content')
        if isinstance(content, str):
            return content.strip()

        if isinstance(content, list):
            parts: list[str] = []
            for part in content:
                if isinstance(part, dict):
                    text = part.get('text')
                    if isinstance(text, str):
                        parts.append(text)
            return '\n'.join(parts).strip()

    return ''


def is_hermes_queue_command(text: str) -> bool:
    command = text.strip().lower()
    return command == '/queue' or command.startswith('/queue ')


def should_reject_overlapping_chat_run(user_text: str, active_task_ids: list[str]) -> bool:
    return bool(active_task_ids) and not is_hermes_queue_command(user_text)
