"""Shared normalizer for Hermes container base URLs.

Every Myah <-> Hermes HTTP call resolves the container URL through
``_agent_url(record.host_port)`` and then strips the trailing ``/v1``
suffix inline. We centralize the strip logic here so every call site
stays in sync when the resolution rules change.
"""
from typing import Optional


def resolve_user_agent_base(url: Optional[str]) -> Optional[str]:
    """Return the bearer-authenticated base URL for a Hermes container.

    Strips a trailing ``/v1`` suffix and a trailing slash.
    Returns ``None`` if the input URL is empty or None.

    Args:
        url: The raw URL returned by ``_agent_url(host_port)``, e.g.
             ``"http://localhost:8642/v1"`` or ``"https://agent.myah.local:8642"``.

    Returns:
        Normalized base URL with ``/v1`` and trailing slashes removed,
        or ``None`` if the input is falsy.
    """
    if not url:
        return None
    url = url.strip()
    if not url:
        return None
    if url.endswith('/v1'):
        url = url[: -len('/v1')]
    return url.rstrip('/')
