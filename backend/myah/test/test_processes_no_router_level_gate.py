"""Per Task 2.3: router-level _raise_if_oss_mode_unless_webhook dep
must be removed so per-chat endpoints can work in OSS."""

from myah.routers import processes


def test_router_has_no_oss_gate_dependency():
    """The router definition must NOT have a 501-gate dependency.

    Per-route gates remain on container-only endpoints (Task 2.4 §3.5)
    but the blanket router-level gate is gone.
    """
    router = processes.router
    deps = getattr(router, 'dependencies', []) or []
    for dep in deps:
        callable_obj = getattr(dep, 'dependency', None) or dep
        name = getattr(callable_obj, '__name__', repr(callable_obj))
        assert '_raise_if_oss_mode' not in name, (
            f'Router-level gate {name} should be removed; use per-route gates instead.'
        )
