import base64
import os
import random
from pathlib import Path
from typing import Annotated

import typer
import uvicorn

app = typer.Typer(
    context_settings={'help_option_names': ['-h', '--help']},
)

KEY_FILE = Path.cwd() / '.myah_secret_key'
LEGACY_KEY_FILE = Path.cwd() / '.webui_secret_key'

# SQLite WAL/SHM/journal sibling suffixes that travel with the main DB file.
# SQLite locates them by filename (not inode), so renaming the main DB
# without renaming siblings would orphan any uncommitted WAL transactions
# from a non-clean shutdown.
_SQLITE_SIBLING_SUFFIXES = ('-wal', '-shm', '-journal')


def version_callback(value: bool) -> None:
    if value:
        from myah.env import VERSION

        typer.echo(f'Myah version: {VERSION}')
        raise typer.Exit()


def _migrate_legacy_secret_key_file(
    legacy: Path | None = None,
    new: Path | None = None,
    echo=typer.echo,
) -> None:
    """Rename .webui_secret_key → .myah_secret_key if the legacy file exists.

    Idempotent. Safe to call on every boot. Logs a one-line notice on
    migration so operators can confirm the rename happened.

    ``legacy`` and ``new`` default to the module-level ``LEGACY_KEY_FILE``
    and ``KEY_FILE`` constants. They are resolved at *call time* (not at
    function-definition time) so that pytest ``monkeypatch.setattr`` on
    those constants flows through to this helper.

    Edge cases:
    - Both files exist: leave both alone; the new file wins (KEY_FILE reads
      it). Log a warning so the operator can investigate and remove the
      stale legacy file by hand.
    - Only legacy exists: rename to new.
    - Only new exists: no-op.
    - Neither exists: no-op (caller will create .myah_secret_key with a
      fresh secret).
    - Permission/OS error during rename: caught and logged; caller proceeds
      to the fresh-secret path rather than crashing the boot.
    """
    if legacy is None:
        legacy = LEGACY_KEY_FILE
    if new is None:
        new = KEY_FILE
    if not legacy.exists():
        return
    if new.exists():
        echo(
            f'Warning: both {legacy.name} and {new.name} exist; using {new.name} '
            f'and leaving the legacy file in place. Remove {legacy.name} manually '
            f'once you have confirmed the migration.'
        )
        return
    try:
        legacy.rename(new)
        echo(f'Migrated legacy secret file: {legacy.name} → {new.name}')
    except OSError as exc:
        echo(f'Warning: could not migrate legacy secret file {legacy.name}: {exc}')


def _bootstrap_secret_key(echo=typer.echo) -> None:
    """Bridge KEY_FILE → env vars for the secret key.

    When neither MYAH_SECRET_KEY nor WEBUI_SECRET_KEY is set in the
    environment, fall back to the on-disk KEY_FILE (generating one if
    missing). Populate BOTH env vars so downstream code that bypasses
    env.py's back-compat shim still sees the legacy WEBUI_SECRET_KEY.

    Phase B.2a closed the env.py-bypass loophole: env.py's _env() helper
    reads MYAH_SECRET_KEY first, but this bootstrap previously wrote only
    WEBUI_SECRET_KEY. After that change the canonical name reaches the
    environment too, and the legacy name is kept for any direct
    os.environ['WEBUI_SECRET_KEY'] consumers.

    Phase B.3b adds the on-disk filename migration. The legacy
    ``.webui_secret_key`` file is renamed to ``.myah_secret_key`` BEFORE
    the env-var short-circuit, so an upgrade scenario (legacy file on
    disk + neither env var set) preserves the existing secret rather
    than regenerating it and invalidating every active session.
    """
    _migrate_legacy_secret_key_file(echo=echo)
    if os.getenv('MYAH_SECRET_KEY') or os.getenv('WEBUI_SECRET_KEY'):
        return
    echo('Loading MYAH_SECRET_KEY from file, not provided as an environment variable.')
    if not KEY_FILE.exists():
        echo(f'Generating a new secret key and saving it to {KEY_FILE}')
        KEY_FILE.write_bytes(base64.b64encode(random.randbytes(12)))
    echo(f'Loading MYAH_SECRET_KEY from {KEY_FILE}')
    secret = KEY_FILE.read_text().strip()
    os.environ['MYAH_SECRET_KEY'] = secret
    # Legacy back-compat: env.py reads MYAH_SECRET_KEY first, but downstream
    # code that bypasses env.py still expects WEBUI_SECRET_KEY in the
    # environment. Populate both so the bridge is bypass-safe.
    os.environ['WEBUI_SECRET_KEY'] = secret


def _resolve_data_dir() -> Path:
    """Resolve DATA_DIR the same way env.py does, without importing env.py.

    env.py's import path also locks DATABASE_URL based on this directory, so
    we must agree with it. Order: explicit DATA_DIR env var → '<cwd>/data'
    fallback (matches `/app/backend/data` inside the container, where
    Dockerfile sets WORKDIR=/app/backend).
    """
    data_dir = os.environ.get('DATA_DIR')
    if data_dir:
        return Path(data_dir)
    return Path.cwd() / 'data'


def _migrate_legacy_db_filename(data_dir: Path | None = None, echo=typer.echo) -> None:
    """Rename legacy ``webui.db`` → ``myah.db`` on first boot after upgrade.

    Idempotent. Safe to call on every boot. Mirrors the ``ollama.db``
    precedent at env.py lines 296-301 but lives here so we can decouple it
    from env.py's already-busy import-time side effects.

    Edge cases:

    * Both files exist (legacy + new): leave both alone, log a warning. The
      caller may have a deliberate dual-state (e.g. a half-restored backup).
      We must NOT delete the legacy file.
    * Only legacy exists: rename to new. Log notice. Carry WAL/SHM/journal
      siblings across in lock-step so SQLite's filename-based recovery
      logic finds them under the new name.
    * Only new exists: no-op. Typical post-migration steady state.
    * Neither exists: no-op. Fresh install — env.py's default path will
      create ``myah.db`` on first DB connection.
    * Permission / OSError during rename: swallow + log. env.py's default
      lookup will create a fresh ``myah.db`` regardless. Boot must not
      crash because of a filesystem hiccup on a pre-migration artifact.
    """
    data_dir = data_dir if data_dir is not None else _resolve_data_dir()
    legacy = data_dir / 'webui.db'
    new = data_dir / 'myah.db'

    if not legacy.exists():
        return  # fresh install or already migrated
    if new.exists():
        # Deliberate-dual-state escape hatch. Never auto-delete the legacy
        # file: it may contain data the operator wants to recover.
        echo(
            f'Warning: both {legacy.name} and {new.name} exist under '
            f'{data_dir}. Leaving both in place; only {new.name} will be '
            f'used by Myah. Remove or back up {legacy.name} manually.'
        )
        return

    try:
        legacy.rename(new)
        echo(f'Migrated legacy database file: {legacy} → {new}')
    except OSError as exc:
        echo(
            f'Warning: failed to rename legacy {legacy} → {new}: {exc}. '
            f'Continuing boot; Myah will create a fresh database.'
        )
        return

    # Renaming SQLite siblings keeps WAL recovery working after a non-clean
    # shutdown. Each sibling is best-effort: if a particular suffix is
    # missing or the rename fails, log and continue rather than abort the
    # already-completed main-file rename.
    for suffix in _SQLITE_SIBLING_SUFFIXES:
        sibling = data_dir / f'webui.db{suffix}'
        if not sibling.exists():
            continue
        target = data_dir / f'myah.db{suffix}'
        try:
            sibling.rename(target)
        except OSError as exc:
            echo(f'Warning: failed to rename SQLite sibling {sibling} → {target}: {exc}')


@app.callback(invoke_without_command=True)
def root(
    ctx: typer.Context,
    version: Annotated[
        bool | None,
        typer.Option(
            '--version', '-v',
            callback=version_callback,
            is_eager=True,
            help='Show the Myah version and exit.',
        ),
    ] = None,
) -> None:
    """Myah CLI root callback — wires `--version`/`-v` at the top level.

    Other options handled at the per-command level. Empty `ctx.invoked_subcommand`
    falls through to the help text.
    """
    if version:
        # version_callback already exits via typer.Exit().
        return
    if ctx.invoked_subcommand is None:
        # No subcommand → print help instead of doing nothing silently.
        typer.echo(ctx.get_help())


@app.command()
def main(
    version: Annotated[bool | None, typer.Option('--version', callback=version_callback)] = None,
):
    pass


def _build_uvicorn_kwargs(host: str, port: int, reload: bool) -> dict:
    """Pure helper that builds the kwargs dict for uvicorn.run().

    Extracted so it can be unit-tested without the import-myah-main side
    effect of `serve`. Returns a dict that callers pass to uvicorn.run().

    Reads UVICORN_WORKERS from os.getenv directly (NOT from myah.env)
    to avoid pulling in env.py's module-load side effects (DB engine,
    Sentry init). This keeps the helper truly pure for testing.
    Independent reviewer C6 caught the original `from myah.env import UVICORN_WORKERS`
    pulling in the full stack.
    """
    workers_str = os.getenv('UVICORN_WORKERS', '1')
    workers = int(workers_str) if workers_str.isdigit() else 1

    return {
        'app': 'myah.main:app',
        'host': host,
        'port': port,
        'reload': reload,
        'forwarded_allow_ips': '*',
        # workers + reload are mutually exclusive in uvicorn
        'workers': 1 if reload else workers,
    }


@app.command()
def serve(
    host: str = '0.0.0.0',
    port: int = 8080,
    reload: bool = False,
):
    """Run the Myah platform via uvicorn.

    Production container's CMD is `myah serve` (no flags). Local dev can
    use `myah serve --reload` to enable hot-reload (formerly `myah dev`).
    """
    os.environ['FROM_INIT_PY'] = 'true'
    _bootstrap_secret_key()
    # Phase B.3a: rename legacy webui.db → myah.db before any DB import.
    # MUST run before `import myah.main` below, which triggers env.py and
    # the lazy DB-engine wiring against the new default path.
    _migrate_legacy_db_filename()

    if os.getenv('USE_CUDA_DOCKER', 'false') == 'true':
        typer.echo('CUDA is enabled, appending LD_LIBRARY_PATH to include torch/cudnn & cublas libraries.')
        LD_LIBRARY_PATH = os.getenv('LD_LIBRARY_PATH', '').split(':')
        os.environ['LD_LIBRARY_PATH'] = ':'.join(
            LD_LIBRARY_PATH
            + [
                '/usr/local/lib/python3.11/site-packages/torch/lib',
                '/usr/local/lib/python3.11/site-packages/nvidia/cudnn/lib',
            ]
        )
        try:
            import torch

            assert torch.cuda.is_available(), 'CUDA not available'
            typer.echo('CUDA seems to be working')
        except Exception as e:
            typer.echo(
                'Error when testing CUDA but USE_CUDA_DOCKER is true. '
                'Resetting USE_CUDA_DOCKER to false and removing '
                f'LD_LIBRARY_PATH modifications: {e}'
            )
            os.environ['USE_CUDA_DOCKER'] = 'false'
            os.environ['LD_LIBRARY_PATH'] = ':'.join(LD_LIBRARY_PATH)

    # Side-effecting imports (FastAPI app + Sentry + DB engine wiring).
    # Note: this is run only when `serve` is invoked. The `_build_uvicorn_kwargs`
    # helper above does NOT trigger this import, so it can be unit-tested.
    import myah.main  # noqa: F401

    uvicorn.run(**_build_uvicorn_kwargs(host=host, port=port, reload=reload))


# The old top-level `dev` command (uvicorn with --reload=True) is REMOVED.
# Its behavior is preserved via `myah serve --reload`.
# The `dev` name is now a subcommand group for developer-only commands.

# Register the new CLI surface. Import is at the bottom of the module to
# avoid circular import issues (cli modules import the `app` from here).
from myah.cli import register_commands  # noqa: E402

register_commands(app)


if __name__ == '__main__':
    app()
