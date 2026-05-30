"""Tests for Hermes profile discovery/selection used by ``myah install``."""

from __future__ import annotations

from pathlib import Path

import pytest
from myah.lib.cli.hermes_profiles import (
    HermesProfile,
    list_hermes_profiles,
    resolve_hermes_profile,
)


def test_list_profiles_includes_default_and_sorted_named_profiles(tmp_path: Path) -> None:
    root = tmp_path / '.hermes'
    (root / 'profiles' / 'work').mkdir(parents=True)
    (root / 'profiles' / 'myah').mkdir(parents=True)
    (root / 'profiles' / 'not-a-dir').write_text('ignore me', encoding='utf-8')

    profiles = list_hermes_profiles(root)

    assert profiles == [
        HermesProfile(name='default', home=root, exists=True, is_default=True),
        HermesProfile(name='myah', home=root / 'profiles' / 'myah', exists=True, is_default=False),
        HermesProfile(name='work', home=root / 'profiles' / 'work', exists=True, is_default=False),
    ]


def test_resolve_current_uses_hermes_home_env_when_set(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    custom = tmp_path / 'custom-home'
    monkeypatch.setenv('HERMES_HOME', str(custom))

    selected = resolve_hermes_profile(profile=None, create_profile=False)

    assert selected.name == 'current'
    assert selected.home == custom
    assert selected.exists is False
    assert selected.is_default is False


def test_resolve_current_defaults_to_default_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.delenv('HERMES_HOME', raising=False)

    selected = resolve_hermes_profile(profile=None, create_profile=False)

    assert selected.name == 'default'
    assert selected.home == tmp_path / '.hermes'
    assert selected.is_default is True


def test_resolve_default_ignores_hermes_home_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.setenv('HERMES_HOME', str(tmp_path / 'custom-current'))

    selected = resolve_hermes_profile(profile='default', create_profile=False)

    assert selected.name == 'default'
    assert selected.home == tmp_path / '.hermes'
    assert selected.is_default is True


def test_resolve_named_profile_maps_to_profiles_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / '.hermes'
    existing = root / 'profiles' / 'myah'
    existing.mkdir(parents=True)
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.delenv('HERMES_HOME', raising=False)

    selected = resolve_hermes_profile(profile='myah', create_profile=False)

    assert selected.name == 'myah'
    assert selected.home == existing
    assert selected.exists is True
    assert selected.is_default is False


def test_missing_named_profile_requires_create_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.delenv('HERMES_HOME', raising=False)

    with pytest.raises(ValueError, match='does not exist'):
        resolve_hermes_profile(profile='myah', create_profile=False)


@pytest.mark.parametrize('bad_name', ['', '.', '..', 'bad/name', 'bad name'])
def test_invalid_profile_names_are_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bad_name: str) -> None:
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.delenv('HERMES_HOME', raising=False)

    with pytest.raises(ValueError, match='Invalid Hermes profile name'):
        resolve_hermes_profile(profile=bad_name, create_profile=True)


def test_create_profile_makes_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.delenv('HERMES_HOME', raising=False)

    selected = resolve_hermes_profile(profile='myah', create_profile=True)

    assert selected.name == 'myah'
    assert selected.home == tmp_path / '.hermes' / 'profiles' / 'myah'
    assert selected.home.is_dir()
    assert selected.exists is True


def test_create_default_profile_makes_default_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.delenv('HERMES_HOME', raising=False)

    selected = resolve_hermes_profile(profile='default', create_profile=True)

    assert selected.name == 'default'
    assert selected.home == tmp_path / '.hermes'
    assert selected.home.is_dir()
    assert selected.is_default is True
