"""
Anti-SaaS-fork enforcement gate (Phase 1B).

Asserts that SaaS-enabling identifiers — sign-up / login / admin user
management / API-key management — are NOT importable from the OSS
``myah`` Python package. If any of these become importable, the build
fails: adding them back to ``platform-oss/`` is a policy violation, not
a refactor.

These identifiers live in ``platform-hosted/backend/myah/routers/...``
in the hosted variant. The Docker overlay
(``platform-hosted/Dockerfile:131-135``) drops the hosted version on
top of the OSS variant at image-build time, which is why the hosted
production image still has them.

The full disposition catalogue is in
``docs/oss-launch/auths-disposition.md`` — that doc is the
authoritative move list. Updates to this test follow updates to that
doc.

Reference: spec \u00a76 (Auth & Anti-SaaS Surgical Removal),
plan Phase 1B Task B.8.
"""

import importlib

import pytest


# Functions deleted from ``myah.routers.auths`` per Phase 1B audit.
# Order matches docs/oss-launch/auths-disposition.md \u00a71 column 1.
FORBIDDEN_AUTH_IDENTIFIERS = [
    'myah.routers.auths.signin',
    'myah.routers.auths.signup',
    'myah.routers.auths.signup_handler',
    'myah.routers.auths.signout',
    'myah.routers.auths.update_password',
    'myah.routers.auths.add_user',
    'myah.routers.auths.get_admin_details',
    'myah.routers.auths.get_admin_config',
    'myah.routers.auths.update_admin_config',
    'myah.routers.auths.generate_api_key',
    'myah.routers.auths.delete_api_key',
    'myah.routers.auths.get_api_key',
    'myah.routers.auths.token_exchange',
    'myah.routers.auths._provision_container_background',
]


# Admin user-management endpoints deleted from ``myah.routers.users``
# per Phase 1B audit. Order matches docs/oss-launch/auths-disposition.md
# \u00a72 (the ``OSS-delete + hosted-keep`` rows).
FORBIDDEN_USERS_IDENTIFIERS = [
    'myah.routers.users.get_users',
    'myah.routers.users.get_all_users',
    'myah.routers.users.get_default_user_permissions',
    'myah.routers.users.update_default_user_permissions',
    'myah.routers.users.get_user_by_id',
    'myah.routers.users.get_user_oauth_sessions_by_id',
    'myah.routers.users.update_user_by_id',
    'myah.routers.users.delete_user_by_id',
    'myah.routers.users.get_user_groups_by_id',
]


ALL_FORBIDDEN_IDENTIFIERS = (
    FORBIDDEN_AUTH_IDENTIFIERS + FORBIDDEN_USERS_IDENTIFIERS
)


@pytest.mark.parametrize('dotted_path', ALL_FORBIDDEN_IDENTIFIERS)
def test_oss_does_not_export_saas_identifier(dotted_path):
    """Each SaaS-enabling identifier MUST NOT be importable from the OSS package.

    A failure here means a SaaS-enabling function snuck back into
    ``platform-oss/``. Either move it back to ``platform-hosted/`` or, if
    the identifier is now genuinely OSS-safe (single-user mode), update
    the audit doc and remove the entry from the forbidden list above.
    """
    module_path, _, name = dotted_path.rpartition('.')
    try:
        module = importlib.import_module(module_path)
    except ImportError:
        # Whole module absent is also a valid outcome — the module's
        # removal achieves the same SaaS-fork friction. No regression.
        return

    assert not hasattr(module, name), (
        f'OSS variant must NOT export `{dotted_path}` \u2014 this is a '
        f'SaaS-enabling surface. Move the function to '
        f'`platform-hosted/backend/myah/routers/...` instead, where the '
        f'Docker overlay (platform-hosted/Dockerfile:131-135) will '
        f're-instate it in the hosted image. See '
        f'docs/oss-launch/auths-disposition.md.'
    )
