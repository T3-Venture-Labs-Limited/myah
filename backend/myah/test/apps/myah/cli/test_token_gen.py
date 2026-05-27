"""Tests for `myah.lib.cli.token_gen` — Slice 4 sub-phase 4a primitives.

Covers the six pure functions that replace phases 1-4 of
`platform-oss/scripts/setup-myah-oss.sh`:

  - generate_bearer_token
  - generate_fernet_key
  - generate_jwt_secret
  - write_token_to_all_slots (5-slot bearer alignment)
  - migrate_legacy_url (LEGACY_BROKEN_URLS migration)
  - adopt_legacy_webui_key (WEBUI_SECRET_KEY -> MYAH_SECRET_KEY adoption)

All tests use tmp_path; no mocks needed (these are pure file I/O + stdlib).
"""

from __future__ import annotations

import re
from pathlib import Path

from myah.lib.cli.env_loader import parse_env_file
from myah.lib.cli.token_gen import (
    CANONICAL_PLATFORM_BASE_URL,
    adopt_legacy_webui_key,
    generate_bearer_token,
    generate_fernet_key,
    generate_jwt_secret,
    migrate_legacy_url,
    write_token_to_all_slots,
)


# Generators — entropy + shape.


class TestGenerateBearerToken:
    def test_returns_nonempty_string(self) -> None:
        token = generate_bearer_token()
        assert isinstance(token, str)
        # secrets.token_urlsafe(32) deterministically yields a 43-char string
        # (32 bytes -> base64url, no padding). Floor at 40 documents the
        # entropy contract (~190 bits) without locking the exact length.
        assert len(token) >= 40

    def test_two_calls_return_different_values(self) -> None:
        assert generate_bearer_token() != generate_bearer_token()


class TestGenerateFernetKey:
    def test_returns_64_char_lowercase_hex(self) -> None:
        key = generate_fernet_key()
        assert len(key) == 64
        assert re.fullmatch(r'[0-9a-f]{64}', key)

    def test_two_calls_return_different_values(self) -> None:
        assert generate_fernet_key() != generate_fernet_key()


class TestGenerateJwtSecret:
    def test_returns_64_char_lowercase_hex(self) -> None:
        secret = generate_jwt_secret()
        assert len(secret) == 64
        assert re.fullmatch(r'[0-9a-f]{64}', secret)

    def test_two_calls_return_different_values(self) -> None:
        assert generate_jwt_secret() != generate_jwt_secret()


# write_token_to_all_slots — five slots, one truth.


def _read(path: Path) -> dict[str, str]:
    return parse_env_file(path)


class TestWriteTokenToAllSlots:
    def test_fresh_dirs_creates_both_files_with_all_five_slots_aligned(self, tmp_path: Path) -> None:
        hermes_env = tmp_path / 'hermes' / '.env'
        platform_env = tmp_path / 'platform' / '.env'
        token = 'abc-fresh-token-xyz'

        write_token_to_all_slots(token, hermes_env, platform_env)

        assert hermes_env.is_file()
        assert platform_env.is_file()

        platform_vars = _read(platform_env)
        hermes_vars = _read(hermes_env)

        assert platform_vars['MYAH_AGENT_BEARER_TOKEN'] == token
        assert hermes_vars['MYAH_AGENT_BEARER_TOKEN'] == token
        assert hermes_vars['MYAH_ADAPTER_AUTH_KEY'] == token
        assert hermes_vars['API_SERVER_KEY'] == token
        assert hermes_vars['MYAH_PLATFORM_BEARER'] == token

    def test_replaces_stale_values_in_existing_files(self, tmp_path: Path) -> None:
        hermes_env = tmp_path / '.hermes' / '.env'
        platform_env = tmp_path / 'platform-oss' / '.env'
        hermes_env.parent.mkdir(parents=True)
        platform_env.parent.mkdir(parents=True)

        platform_env.write_text('MYAH_AGENT_BEARER_TOKEN=stale-platform\nOTHER=keep\n')
        hermes_env.write_text(
            'MYAH_AGENT_BEARER_TOKEN=stale-hermes\n'
            'MYAH_ADAPTER_AUTH_KEY=stale-adapter\n'
            'API_SERVER_KEY=stale-api\n'
            'MYAH_PLATFORM_BEARER=stale-platform-bearer\n'
        )

        new_token = 'fresh-aligned-token'
        write_token_to_all_slots(new_token, hermes_env, platform_env)

        platform_vars = _read(platform_env)
        hermes_vars = _read(hermes_env)

        assert platform_vars['MYAH_AGENT_BEARER_TOKEN'] == new_token
        assert platform_vars['OTHER'] == 'keep'
        assert hermes_vars['MYAH_AGENT_BEARER_TOKEN'] == new_token
        assert hermes_vars['MYAH_ADAPTER_AUTH_KEY'] == new_token
        assert hermes_vars['API_SERVER_KEY'] == new_token
        assert hermes_vars['MYAH_PLATFORM_BEARER'] == new_token

    def test_preserves_export_prefix_on_existing_lines(self, tmp_path: Path) -> None:
        hermes_env = tmp_path / '.env.hermes'
        platform_env = tmp_path / '.env.platform'
        hermes_env.write_text(
            'export MYAH_AGENT_BEARER_TOKEN=old\n'
            'MYAH_ADAPTER_AUTH_KEY=old\n'
            'export API_SERVER_KEY=old\n'
            'MYAH_PLATFORM_BEARER=old\n'
        )
        platform_env.write_text('export MYAH_AGENT_BEARER_TOKEN=old\n')

        token = 'new-token-value'
        write_token_to_all_slots(token, hermes_env, platform_env)

        hermes_text = hermes_env.read_text()
        platform_text = platform_env.read_text()

        # Lines that originally had `export ` keep the prefix.
        assert f'export MYAH_AGENT_BEARER_TOKEN={token}\n' in hermes_text
        assert f'export API_SERVER_KEY={token}\n' in hermes_text
        # Lines that didn't have `export ` stay normal.
        assert f'MYAH_ADAPTER_AUTH_KEY={token}\n' in hermes_text
        assert f'MYAH_PLATFORM_BEARER={token}\n' in hermes_text
        # And the platform file's `export ` is preserved too.
        assert f'export MYAH_AGENT_BEARER_TOKEN={token}\n' in platform_text

        # No "double" lines without the export prefix snuck in for the exported keys.
        assert hermes_text.count('MYAH_AGENT_BEARER_TOKEN=') == 1
        assert hermes_text.count('API_SERVER_KEY=') == 1

    def test_idempotent_two_calls_same_token_yields_same_content(self, tmp_path: Path) -> None:
        hermes_env = tmp_path / 'h.env'
        platform_env = tmp_path / 'p.env'
        token = 'idempotent-token'

        write_token_to_all_slots(token, hermes_env, platform_env)
        first_hermes = hermes_env.read_text()
        first_platform = platform_env.read_text()

        write_token_to_all_slots(token, hermes_env, platform_env)
        assert hermes_env.read_text() == first_hermes
        assert platform_env.read_text() == first_platform

    def test_realigns_when_one_slot_drifted(self, tmp_path: Path) -> None:
        """Production failure mode: 4 slots aligned, 1 drifted out of sync.

        If `write_token_to_all_slots` only wrote when nothing matched, this
        case would silently leave the drifted slot alone. The guarantee is
        unconditional — every call writes every slot.
        """
        hermes_env = tmp_path / '.hermes' / '.env'
        platform_env = tmp_path / 'platform' / '.env'
        hermes_env.parent.mkdir(parents=True)
        platform_env.parent.mkdir(parents=True)

        aligned = 'aligned-value'
        platform_env.write_text(f'MYAH_AGENT_BEARER_TOKEN={aligned}\n')
        hermes_env.write_text(
            f'MYAH_AGENT_BEARER_TOKEN={aligned}\n'
            f'MYAH_ADAPTER_AUTH_KEY={aligned}\n'
            f'API_SERVER_KEY=drifted-value\n'        # the rogue slot
            f'MYAH_PLATFORM_BEARER={aligned}\n'
        )

        new_token = 'new-canonical-token'
        write_token_to_all_slots(new_token, hermes_env, platform_env)

        hermes_vars = _read(hermes_env)
        platform_vars = _read(platform_env)
        assert platform_vars['MYAH_AGENT_BEARER_TOKEN'] == new_token
        assert hermes_vars['MYAH_AGENT_BEARER_TOKEN'] == new_token
        assert hermes_vars['MYAH_ADAPTER_AUTH_KEY'] == new_token
        assert hermes_vars['API_SERVER_KEY'] == new_token
        assert hermes_vars['MYAH_PLATFORM_BEARER'] == new_token

    def test_preserves_unrelated_lines_in_platform_env(self, tmp_path: Path) -> None:
        hermes_env = tmp_path / 'h.env'
        platform_env = tmp_path / 'p.env'
        platform_env.write_text(
            'OPENAI_API_KEY=xyz\n'
            '# a comment\n'
            'SENTRY_DSN_PLATFORM=https://example.ingest.sentry.io/1\n'
            '\n'
            'LANGFUSE_PUBLIC_KEY=pk-foo\n'
        )

        write_token_to_all_slots('tok', hermes_env, platform_env)

        text = platform_env.read_text()
        assert 'OPENAI_API_KEY=xyz' in text
        assert '# a comment' in text
        assert 'SENTRY_DSN_PLATFORM=https://example.ingest.sentry.io/1' in text
        assert 'LANGFUSE_PUBLIC_KEY=pk-foo' in text
        assert 'MYAH_AGENT_BEARER_TOKEN=tok' in text


# migrate_legacy_url — protect users, preserve customization.


class TestMigrateLegacyUrl:
    CANONICAL = 'http://127.0.0.1:8080'

    def test_missing_file_writes_canonical_and_returns_true(self, tmp_path: Path) -> None:
        env_path = tmp_path / 'hermes' / '.env'

        wrote = migrate_legacy_url(env_path)

        assert wrote is True
        assert env_path.is_file()
        assert _read(env_path)['MYAH_PLATFORM_BASE_URL'] == self.CANONICAL

    def test_existing_file_without_key_writes_canonical_and_returns_true(self, tmp_path: Path) -> None:
        env_path = tmp_path / '.env'
        env_path.write_text('OTHER=keep\n')

        wrote = migrate_legacy_url(env_path)

        assert wrote is True
        vars_ = _read(env_path)
        assert vars_['MYAH_PLATFORM_BASE_URL'] == self.CANONICAL
        assert vars_['OTHER'] == 'keep'

    def test_writes_canonical_when_value_is_empty_string(self, tmp_path: Path) -> None:
        """Key present but value empty (`MYAH_PLATFORM_BASE_URL=`) must
        be treated the same as unset — the gateway can't bind a blank URL."""
        env_path = tmp_path / '.env'
        env_path.write_text('MYAH_PLATFORM_BASE_URL=\nOTHER=keep\n')

        wrote = migrate_legacy_url(env_path)

        assert wrote is True
        vars_ = _read(env_path)
        assert vars_['MYAH_PLATFORM_BASE_URL'] == self.CANONICAL
        assert vars_['OTHER'] == 'keep'

    def test_overwrites_host_docker_internal_legacy(self, tmp_path: Path) -> None:
        env_path = tmp_path / '.env'
        env_path.write_text('MYAH_PLATFORM_BASE_URL=http://host.docker.internal:8080\n')

        wrote = migrate_legacy_url(env_path)

        assert wrote is True
        assert _read(env_path)['MYAH_PLATFORM_BASE_URL'] == self.CANONICAL

    def test_overwrites_obsolete_localhost_8154_legacy(self, tmp_path: Path) -> None:
        env_path = tmp_path / '.env'
        env_path.write_text('MYAH_PLATFORM_BASE_URL=http://localhost:8154\n')

        wrote = migrate_legacy_url(env_path)

        assert wrote is True
        assert _read(env_path)['MYAH_PLATFORM_BASE_URL'] == self.CANONICAL

    def test_preserves_canonical_value_no_write_returns_false(self, tmp_path: Path) -> None:
        env_path = tmp_path / '.env'
        original = f'MYAH_PLATFORM_BASE_URL={self.CANONICAL}\nUNRELATED=x\n'
        env_path.write_text(original)

        wrote = migrate_legacy_url(env_path)

        assert wrote is False
        assert env_path.read_text() == original

    def test_preserves_custom_remote_url(self, tmp_path: Path) -> None:
        env_path = tmp_path / '.env'
        custom = 'https://my-platform.example.com:8080'
        original = f'MYAH_PLATFORM_BASE_URL={custom}\n'
        env_path.write_text(original)

        wrote = migrate_legacy_url(env_path)

        assert wrote is False
        assert env_path.read_text() == original

    def test_preserves_export_prefix_when_overwriting_legacy(self, tmp_path: Path) -> None:
        env_path = tmp_path / '.env'
        env_path.write_text('export MYAH_PLATFORM_BASE_URL=http://localhost:8154\n')

        wrote = migrate_legacy_url(env_path)

        assert wrote is True
        assert f'export MYAH_PLATFORM_BASE_URL={self.CANONICAL}\n' == env_path.read_text()


# adopt_legacy_webui_key — backwards-compat one-shot adoption.


class TestAdoptLegacyWebuiKey:
    def test_missing_file_returns_false(self, tmp_path: Path) -> None:
        env_path = tmp_path / 'never-existed' / '.env'

        adopted = adopt_legacy_webui_key(env_path)

        assert adopted is False
        # Should not have created the file just to confirm a no-op.
        assert not env_path.is_file()

    def test_myah_already_set_with_webui_also_set_returns_false_both_preserved(
        self, tmp_path: Path
    ) -> None:
        env_path = tmp_path / '.env'
        original = (
            'MYAH_SECRET_KEY=existing-myah-value\n'
            'WEBUI_SECRET_KEY=legacy-value\n'
        )
        env_path.write_text(original)

        adopted = adopt_legacy_webui_key(env_path)

        assert adopted is False
        assert env_path.read_text() == original

    def test_myah_unset_webui_set_copies_value_returns_true(self, tmp_path: Path) -> None:
        env_path = tmp_path / '.env'
        env_path.write_text('WEBUI_SECRET_KEY=legacy-value-xyz\nOTHER=keep\n')

        adopted = adopt_legacy_webui_key(env_path)

        assert adopted is True
        vars_ = _read(env_path)
        assert vars_['MYAH_SECRET_KEY'] == 'legacy-value-xyz'
        # WEBUI is NOT removed.
        assert vars_['WEBUI_SECRET_KEY'] == 'legacy-value-xyz'
        assert vars_['OTHER'] == 'keep'

    def test_both_unset_returns_false_no_write(self, tmp_path: Path) -> None:
        env_path = tmp_path / '.env'
        original = 'UNRELATED=x\n'
        env_path.write_text(original)

        adopted = adopt_legacy_webui_key(env_path)

        assert adopted is False
        assert env_path.read_text() == original

    def test_handles_export_prefix_on_webui_key(self, tmp_path: Path) -> None:
        env_path = tmp_path / '.env'
        env_path.write_text('export WEBUI_SECRET_KEY=exported-legacy\n')

        adopted = adopt_legacy_webui_key(env_path)

        assert adopted is True
        vars_ = _read(env_path)
        assert vars_['MYAH_SECRET_KEY'] == 'exported-legacy'
        assert vars_['WEBUI_SECRET_KEY'] == 'exported-legacy'

    def test_empty_webui_value_treated_as_unset(self, tmp_path: Path) -> None:
        """An empty WEBUI_SECRET_KEY shouldn't propagate an empty MYAH_SECRET_KEY."""
        env_path = tmp_path / '.env'
        env_path.write_text('WEBUI_SECRET_KEY=\n')

        adopted = adopt_legacy_webui_key(env_path)

        assert adopted is False
        # MYAH_SECRET_KEY should not have been created with an empty value.
        vars_ = _read(env_path)
        assert 'MYAH_SECRET_KEY' not in vars_


# Defense-in-depth sentinels.


def test_module_imports_only_lightweight_stdlib() -> None:
    """Sentinel: token_gen.py's OWN source should not import heavy modules.

    Note: this only catches new direct imports introduced in token_gen.py
    itself. Transitive cold-start budget (Slice 1 helpers pulling in
    loguru/typer/click) is measured by test_cold_start_benchmark.py — that's
    the binding regression gate; this is a localized sentinel for cheap
    module-top hygiene.
    """
    from myah.lib.cli import token_gen

    source = Path(token_gen.__file__).read_text(encoding='utf-8')
    # Approximate: walk the top-level import block (everything before the first `def`).
    head = source.split('\ndef ', 1)[0]
    forbidden = ('rich', 'yaml', 'click', 'typer', 'httpx', 'requests', 'docker')
    for needle in forbidden:
        assert f'import {needle}' not in head, f'token_gen top-level imports {needle!r}'
        assert f'from {needle}' not in head, f'token_gen top-level imports from {needle!r}'


def test_canonical_platform_base_url_matches_bash_pinned_value() -> None:
    """Defense-in-depth: the canonical URL constant must equal the bash-pinned value.

    Drift between `CANONICAL_PLATFORM_BASE_URL` and the literal at
    `platform-oss/scripts/setup-myah-oss.sh:306-329` would silently
    break attachment fetch + cron deliveries (the bug class catalogued in
    docs/gotchas/2026-05-19-oss-cron-platform-base-url-drift.md). This
    test catches accidental refactoring of the constant before it leaves
    the worktree.
    """
    assert CANONICAL_PLATFORM_BASE_URL == 'http://127.0.0.1:8080'
