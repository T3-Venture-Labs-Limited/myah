"""Reusable plain-data samples for the platform↔Hermes event contract.

The payloads in :data:`EVENT_SAMPLES` mirror representative SSE event
shapes known from the upstream snapshot. Keep this module intentionally
model-free so route/provider tests can import sample data without depending
on concrete Pydantic classes.
"""
from __future__ import annotations

from typing import Any

EVENT_SAMPLES: dict[str, dict[str, Any]] = {
    'approval.request': {
        'event': 'approval.request',
        'command': 'rm -rf /tmp/foo',
        'description': 'Command requires approval: rm -rf /tmp/foo',
        'pattern_key': 'dangerous_rm',
        'pattern_keys': ['dangerous_rm'],
        'choices': ['once', 'session', 'always', 'deny'],
        'run_id': 'run_abc',
        'timestamp': 1714400002.0,
    },
    'approval.responded': {
        'event': 'approval.responded',
        'choice': 'once',
        'resolved': 1,
        'run_id': 'run_abc',
        'timestamp': 1714400003.0,
    },
    'message.delta': {
        'event': 'message.delta',
        'delta': 'Hello world',
        'run_id': 'run_abc',
        'stream_id': 'run_abc',
        'timestamp': 1714400000.0,
    },
    'reasoning.available': {
        'event': 'reasoning.available',
        'text': 'Full chain-of-thought transcript.',
        'run_id': 'run_abc',
    },
    'reasoning.delta': {
        'event': 'reasoning.delta',
        'text': 'Considering the problem...',
        'run_id': 'run_abc',
        'timestamp': 1714400001.0,
    },
    'run.cancelled': {
        'event': 'run.cancelled',
        'run_id': 'run_abc',
    },
    'run.completed': {
        'event': 'run.completed',
        'output': 'Final response text',
        'usage': {'input_tokens': 100, 'output_tokens': 50, 'total_tokens': 150},
        'model': 'anthropic/claude-sonnet-4-6',
        'provider': 'openrouter',
        'run_id': 'run_abc',
    },
    'run.failed': {
        'event': 'run.failed',
        'error': 'LLM provider returned 429',
        'run_id': 'run_abc',
    },
    'secret.required': {
        'event': 'secret.required',
        'var_name': 'OPENAI_API_KEY',
        'prompt': 'Enter your OpenAI API key',
        'help': 'https://platform.openai.com/api-keys',
        'skill_name': 'openai',
        'run_id': 'run_abc',
    },
    'secret.resolved': {
        'event': 'secret.resolved',
        'var_name': 'OPENAI_API_KEY',
        'status': 'stored',
        'run_id': 'run_abc',
    },
    'status': {
        'event': 'status',
        'text': 'working',
        'run_id': 'run_abc',
    },
    'tool.completed': {
        'event': 'tool.completed',
        'tool': 'shell_exec',
        'call_id': 'call_xyz',
        'args': {'command': 'ls -la'},
        'result': 'total 0\ndrwxr-xr-x  2 user staff   64 Apr 25 12:00 .',
        'duration': 0.123,
        'error': False,
        'run_id': 'run_abc',
    },
    'tool.confirmation_required': {
        'event': 'tool.confirmation_required',
        'confirmation_id': 'conf_123',
        'action_type': 'exec_approval',
        'description': 'Command requires approval: rm -rf /tmp/foo',
        'options': ['approve', 'approve_session', 'deny'],
        'metadata': {'risk': 'high'},
        'run_id': 'run_abc',
    },
    'tool.started': {
        'event': 'tool.started',
        'tool': 'shell_exec',
        'call_id': 'call_xyz',
        'args': {'command': 'ls -la'},
        'preview': 'ls -la',
        'run_id': 'run_abc',
    },
}

__all__ = ['EVENT_SAMPLES']
