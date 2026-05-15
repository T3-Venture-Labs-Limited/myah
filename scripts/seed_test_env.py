"""Seed a fresh myah.db for E2E testing.

Creates a deterministic test user with:
- Known email/password (defaults: e2e@test.local / e2e-password)
- 'admin' role (first user in a fresh DB is admin anyway; we enforce it)

Safe to run against an empty OR existing DB:
- Existing user with the same email -> rotates password (idempotent)

Provider credentials (OpenRouter key etc.) are NOT seeded here — they live
in the Hermes agent container's volume and are managed via the Hermes-native
provider catalog (POST /myah/api/providers/{id}/credential inside the
container). The myah-e2e-testing skill handles credential injection after
the container starts.

After running, log in with the printed credentials at the worktree's
frontend URL. The first chat will provision a per-user agent container
automatically via the existing /api/v1/containers path.

Usage:

    # From the repo root, using an isolated DATA_DIR for a worktree:
    cd platform
    DATA_DIR=/abs/path/to/worktree/platform/backend/data \\
      .venv/bin/python scripts/seed_test_env.py

Exit codes:
    0 - seeded successfully
    2 - DATA_DIR does not exist (create it first with mkdir -p)
    3 - unexpected DB error
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


# Before importing anything from myah, make sure DATA_DIR is resolved.
# myah.env locks the DB path at import time via DATA_DIR, so this must
# come first.
def _bootstrap_data_dir(cli_data_dir: str | None) -> Path:
    data_dir = cli_data_dir or os.environ.get('DATA_DIR')
    if not data_dir:
        # Fall back to platform/backend/data relative to this script.
        script_dir = Path(__file__).resolve().parent
        data_dir = str((script_dir.parent / 'backend' / 'data').resolve())
    path = Path(data_dir).resolve()
    if not path.exists():
        print(f'error: DATA_DIR does not exist: {path}', file=sys.stderr)
        print('create it first: mkdir -p <data_dir>', file=sys.stderr)
        sys.exit(2)
    # Lock the env so myah.env picks it up on import.
    os.environ['DATA_DIR'] = str(path)
    return path


def _load_dotenv_e2e(repo_root: Path) -> None:
    """Load .env.e2e at repo root if present, without adding a runtime dep.

    We do NOT use python-dotenv because this script is standalone. Only
    KEY=value lines are parsed; comments and blank lines are ignored.
    Existing env vars are NOT overridden.
    """
    env_file = repo_root / '.env.e2e'
    if not env_file.exists():
        return
    for raw in env_file.read_text(encoding='utf-8').splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        if '=' not in line:
            continue
        key, _, value = line.partition('=')
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _resolve_repo_root() -> Path:
    """platform/scripts/seed_test_env.py -> repo root is two parents up."""
    return Path(__file__).resolve().parent.parent.parent


def main() -> int:
    parser = argparse.ArgumentParser(description='Seed a test user into myah.db.')
    parser.add_argument('--data-dir', help='Override DATA_DIR (defaults to platform/backend/data).')
    parser.add_argument('--email', default='e2e@test.local', help='Test user email.')
    parser.add_argument('--password', default='e2e-password', help='Test user password.')
    parser.add_argument('--name', default='E2E Test User', help='Display name.')
    parser.add_argument('--role', default='admin', choices=('admin', 'user'), help='User role.')
    parser.add_argument('--quiet', action='store_true', help='Suppress informational output.')
    args = parser.parse_args()

    repo_root = _resolve_repo_root()
    _load_dotenv_e2e(repo_root)
    data_dir = _bootstrap_data_dir(args.data_dir)

    # Imports are deferred until AFTER DATA_DIR is set, so myah.env picks
    # up the worktree-specific DB path rather than the main workspace's.
    platform_backend = Path(__file__).resolve().parent.parent / 'backend'
    sys.path.insert(0, str(platform_backend))

    try:
        from myah.models.auths import Auths
        from myah.models.users import Users
        from myah.utils.auth import get_password_hash
    except ImportError as err:
        print(f'error: could not import myah (is the venv active?): {err}', file=sys.stderr)
        return 3

    # Create or update the auth + user.
    hashed_password = get_password_hash(args.password)
    existing_user = Users.get_user_by_email(args.email)

    if existing_user:
        # Rotate the password so the script is repeatable.
        from myah.internal.db import get_db
        from myah.models.auths import Auth

        with get_db() as db:
            auth = db.query(Auth).filter_by(id=existing_user.id).first()
            if auth:
                auth.password = hashed_password
                db.commit()
        user = existing_user
        if not args.quiet:
            print(f'updated existing user: {args.email} (id={user.id})')
    else:
        user = Auths.insert_new_auth(
            email=args.email,
            password=hashed_password,
            name=args.name,
            role=args.role,
        )
        if not user:
            print('error: insert_new_auth returned None', file=sys.stderr)
            return 3
        if not args.quiet:
            print(f'created user: {args.email} (id={user.id}, role={args.role})')

    if not args.quiet:
        print('')
        print(f'  email:    {args.email}')
        print(f'  password: {args.password}')
        print(f'  role:     {args.role}')
        print(f'  user id:  {user.id}')
        print(f'  data dir: {data_dir}')
        print('')
        print('Provider credentials must be seeded via the Hermes agent container')
        print('after it starts. The myah-e2e-testing skill handles this step.')
        print('log in at the worktree frontend URL to start testing.')
    else:
        # Machine-parsable single line
        print(f'{args.email} {user.id}')

    return 0


if __name__ == '__main__':
    sys.exit(main())
