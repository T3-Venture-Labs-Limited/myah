import base64
import os
import random
from pathlib import Path
from typing import Annotated

import typer
import uvicorn

app = typer.Typer()

KEY_FILE = Path.cwd() / '.webui_secret_key'


def version_callback(value: bool) -> None:
    if value:
        from myah.env import VERSION

        typer.echo(f'Myah version: {VERSION}')
        raise typer.Exit()


def _bootstrap_secret_key(echo=typer.echo) -> None:
    """Bridge KEY_FILE → env vars for the secret key.

    When neither MYAH_SECRET_KEY nor WEBUI_SECRET_KEY is set in the
    environment, fall back to the on-disk KEY_FILE (generating one if
    missing). Populate BOTH env vars so downstream code that bypasses
    env.py's back-compat shim still sees the legacy WEBUI_SECRET_KEY.

    Phase B.2a closes the env.py-bypass loophole: env.py's _env() helper
    reads MYAH_SECRET_KEY first, but this bootstrap previously wrote only
    WEBUI_SECRET_KEY. After this change the canonical name reaches the
    environment too, and the legacy name is kept for any direct
    os.environ['WEBUI_SECRET_KEY'] consumers.
    """
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


@app.command()
def main(
    version: Annotated[bool | None, typer.Option('--version', callback=version_callback)] = None,
):
    pass


@app.command()
def serve(
    host: str = '0.0.0.0',
    port: int = 8080,
):
    os.environ['FROM_INIT_PY'] = 'true'
    _bootstrap_secret_key()

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

    import myah.main  # noqa: F401
    from myah.env import UVICORN_WORKERS  # Import the workers setting

    uvicorn.run(
        'myah.main:app',
        host=host,
        port=port,
        forwarded_allow_ips='*',
        workers=UVICORN_WORKERS,
    )


@app.command()
def dev(
    host: str = '0.0.0.0',
    port: int = 8080,
    reload: bool = True,
):
    uvicorn.run(
        'myah.main:app',
        host=host,
        port=port,
        reload=reload,
        forwarded_allow_ips='*',
    )


if __name__ == '__main__':
    app()
