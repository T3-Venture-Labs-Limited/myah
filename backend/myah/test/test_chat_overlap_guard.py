from myah.utils.chat_overlap_guard import (
    first_user_text_from_messages,
    is_hermes_queue_command,
    should_reject_overlapping_chat_run,
)


def test_rejects_normal_prompt_when_active_task_exists():
    assert should_reject_overlapping_chat_run('hello', ['task-1']) is True


def test_allows_queue_command_when_active_task_exists():
    assert should_reject_overlapping_chat_run('/queue steer this', ['task-1']) is False


def test_allows_when_no_active_task_exists():
    assert should_reject_overlapping_chat_run('hello', []) is False


def test_queue_command_detection_ignores_case_and_leading_space():
    assert is_hermes_queue_command('  /QUEUE steer this') is True
    assert is_hermes_queue_command('/queue') is True
    assert is_hermes_queue_command('/queuefoo') is False


def test_extracts_last_user_string_content():
    assert (
        first_user_text_from_messages(
            {
                'messages': [
                    {'role': 'user', 'content': 'first'},
                    {'role': 'assistant', 'content': 'answer'},
                    {'role': 'user', 'content': 'second'},
                ]
            }
        )
        == 'second'
    )


def test_extracts_openai_list_text_content():
    assert (
        first_user_text_from_messages(
            {
                'messages': [
                    {
                        'role': 'user',
                        'content': [
                            {'type': 'text', 'text': 'hello'},
                            {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,...'}},
                            {'type': 'text', 'text': 'world'},
                        ],
                    }
                ]
            }
        )
        == 'hello\nworld'
    )


def test_extract_ignores_malformed_messages():
    assert first_user_text_from_messages({'messages': [None, 'bad', {'role': 'assistant'}]}) == ''
    assert first_user_text_from_messages({'messages': 'bad'}) == ''
