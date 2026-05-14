"""Tests for the shared Hermes URL resolver."""
import pytest

from myah.utils.hermes_routing import resolve_user_agent_base


def test_strips_trailing_v1():
    assert resolve_user_agent_base('https://agent.myah.local:8642/v1') == 'https://agent.myah.local:8642'


def test_strips_trailing_slash():
    assert resolve_user_agent_base('https://agent.myah.local:8642/') == 'https://agent.myah.local:8642'


def test_preserves_clean_url():
    assert resolve_user_agent_base('https://agent.myah.local:8642') == 'https://agent.myah.local:8642'


def test_returns_none_when_none():
    assert resolve_user_agent_base(None) is None


def test_returns_none_on_empty_string():
    assert resolve_user_agent_base('') is None


def test_strips_trailing_slash_after_v1():
    # For 'http://localhost:8642/v1/', endswith('/v1') is False (ends with '/'),
    # so rstrip('/') gives 'http://localhost:8642/v1'
    assert resolve_user_agent_base('http://localhost:8642/v1/') == 'http://localhost:8642/v1'


def test_does_not_strip_v1_in_middle_of_path():
    # /v1 only stripped at the very end of the string
    assert resolve_user_agent_base('http://localhost:8642/v1/api') == 'http://localhost:8642/v1/api'


def test_strips_whitespace_before_processing():
    assert resolve_user_agent_base('  http://localhost:8642/v1  ') == 'http://localhost:8642'


def test_returns_none_on_whitespace_only():
    assert resolve_user_agent_base('   ') is None
