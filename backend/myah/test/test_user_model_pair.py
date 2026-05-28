"""Tests for the (default_provider, default_model) pair on User.

The pair mirrors Hermes upstream's canonical {provider, model} shape at
every persistence and runtime boundary — see
`docs/superpowers/specs/2026-05-24-default-model-canonical-format-design.md`.
"""

import pytest
from pydantic import ValidationError

from myah.models.users import User, UserModel


def _user_kwargs(**overrides):
    base = dict(
        id='u1',
        name='Alice',
        email='a@example.com',
        role='admin',
        profile_image_url='/x',
        last_active_at=0,
        updated_at=0,
        created_at=0,
    )
    base.update(overrides)
    return base


def test_user_sa_model_has_default_provider_column():
    """SQLAlchemy declarative reflection must expose the new column."""
    cols = {c.name for c in User.__table__.columns}
    assert 'default_provider' in cols, f'default_provider missing from User columns: {cols}'


def test_user_pydantic_model_accepts_default_provider():
    """Pydantic UserModel must accept the new optional field."""
    instance = UserModel(**_user_kwargs(
        default_model='gpt-4o-mini', default_provider='openai',
    ))
    assert instance.default_provider == 'openai'
    assert instance.default_model == 'gpt-4o-mini'


# ── Pydantic validator: both-or-neither + reject composite ────────────────────


def test_user_model_rejects_default_model_without_provider():
    """Half-pair (model only) is rejected at the API boundary."""
    with pytest.raises(ValidationError, match='must both be set or both be null'):
        UserModel(**_user_kwargs(default_model='gpt-4o-mini', default_provider=None))


def test_user_model_rejects_provider_without_model():
    """Half-pair (provider only) is rejected at the API boundary."""
    with pytest.raises(ValidationError, match='must both be set or both be null'):
        UserModel(**_user_kwargs(default_model=None, default_provider='openai'))


def test_user_model_rejects_composite_in_default_model():
    """The '::' separator is Myah's composite marker; reject it in storage.
    Composite belongs only on Svelte iteration keys, never in the DB."""
    with pytest.raises(ValidationError, match="no '::' composite"):
        UserModel(**_user_kwargs(
            default_model='openai::gpt-4o-mini', default_provider='openai',
        ))


def test_user_model_accepts_slash_in_model_id():
    """Vendor-namespaced model ids (e.g. 'anthropic/claude-opus-4.6' on
    OpenRouter) are pass-through to the provider; the slash is NOT a Myah
    provider prefix and must be allowed."""
    instance = UserModel(**_user_kwargs(
        default_model='anthropic/claude-opus-4.6', default_provider='openrouter',
    ))
    assert instance.default_model == 'anthropic/claude-opus-4.6'


def test_user_model_rejects_separators_in_default_provider():
    """A bare provider id never contains '/' or '::'; both indicate a buggy
    writer storing composite/slash where the provider id belongs."""
    with pytest.raises(ValidationError, match='must be a bare provider id'):
        UserModel(**_user_kwargs(
            default_model='gpt-4o-mini', default_provider='openai/gpt-4o-mini',
        ))
    with pytest.raises(ValidationError, match='must be a bare provider id'):
        UserModel(**_user_kwargs(
            default_model='gpt-4o-mini', default_provider='openai::gpt-4o-mini',
        ))


def test_user_model_accepts_both_null():
    """Both-null is the canonical 'no default set' state."""
    instance = UserModel(**_user_kwargs(default_model=None, default_provider=None))
    assert instance.default_model is None
    assert instance.default_provider is None
