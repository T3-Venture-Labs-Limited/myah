from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.responses import Response
from fastapi.testclient import TestClient

from myah.utils.security_headers import SecurityHeadersMiddleware, set_security_headers


def derive_spa_url_paths(routes_dir: Path) -> list[str]:
    paths: list[str] = []
    for page in routes_dir.rglob('+page.svelte'):
        segments: list[str] = []
        for seg in page.relative_to(routes_dir).parent.parts:
            if seg.startswith('(') and seg.endswith(')'):
                continue
            segments.append('id' if seg.startswith('[') and seg.endswith(']') else seg)
        paths.append('/'.join(segments))
    return paths


def test_baseline_headers_present_without_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    for env_var in (
        'CACHE_CONTROL',
        'HSTS',
        'PERMISSIONS_POLICY',
        'REFERRER_POLICY',
        'XCONTENT_TYPE',
        'XDOWNLOAD_OPTIONS',
        'XFRAME_OPTIONS',
        'XPERMITTED_CROSS_DOMAIN_POLICIES',
        'CONTENT_SECURITY_POLICY',
        'REPORTING_ENDPOINTS',
    ):
        monkeypatch.delenv(env_var, raising=False)

    headers = set_security_headers()

    assert headers['X-Robots-Tag'] == 'noindex, nofollow'
    assert headers['X-Content-Type-Options'] == 'nosniff'
    assert headers['X-Frame-Options'] == 'SAMEORIGIN'
    assert headers['Referrer-Policy'] == 'strict-origin-when-cross-origin'


def test_env_var_overrides_baseline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('REFERRER_POLICY', 'no-referrer')

    headers = set_security_headers()

    assert headers['Referrer-Policy'] == 'no-referrer'
    assert headers['X-Robots-Tag'] == 'noindex, nofollow'


@pytest.fixture
def headered_client() -> TestClient:
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get('/')
    async def _root():
        return {'ok': True}

    @app.get('/asset')
    async def _asset():
        return Response(
            content='x',
            media_type='application/javascript',
            headers={'Cache-Control': 'public, max-age=31536000, immutable'},
        )

    return TestClient(app)


def test_response_carries_noindex_header(headered_client: TestClient) -> None:
    r = headered_client.get('/')
    assert r.status_code == 200
    assert r.headers['x-robots-tag'] == 'noindex, nofollow'
    assert r.headers['x-content-type-options'] == 'nosniff'


def test_global_cache_control_does_not_clobber_immutable(
    headered_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv('CACHE_CONTROL', 'no-store, max-age=0')
    r = headered_client.get('/asset')
    assert r.status_code == 200
    assert r.headers['cache-control'] == 'public, max-age=31536000, immutable'


def test_global_cache_control_still_applies_to_normal_responses(
    headered_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv('CACHE_CONTROL', 'no-store, max-age=0')
    r = headered_client.get('/')
    assert r.headers['cache-control'] == 'no-store, max-age=0'


# db_session sets MYAH_DEPLOYMENT_MODE=oss, so is_spa_route runs in OSS mode:
# hosted-only routes (admin, integrations, memory) must NOT match — OSS has no
# such pages, so they 404 instead of returning a 200 shell.
_SPA_ROUTE_CASES_OSS = [
    ('', True),
    ('.', True),
    ('auth', True),
    ('error', True),
    ('notes/new', True),
    ('agent/skills', False),
    ('agent/skills/create', False),
    ('agent/skills/edit', False),
    ('c/abc-123', True),
    ('notes/some-id', True),
    ('spaces/xyz', True),
    ('totally-fake', False),
    ('wp-login.php', False),
    ('.env', False),
    ('sitemap.xml', False),
    ('c/abc/garbage', False),
    ('notes/a/b', False),
    # hosted-only -> False in OSS mode
    ('admin', False),
    ('admin/users', False),
    ('admin/users/general', False),
    ('admin/settings/database', False),
    ('agent/integrations', False),
    ('agent/memory', False),
]


@pytest.mark.parametrize('path,expected', _SPA_ROUTE_CASES_OSS)
def test_is_spa_route_oss_mode(db_session, path: str, expected: bool) -> None:
    from myah.main import is_spa_route

    assert is_spa_route(path) is expected


def test_is_spa_route_hosted_mode(db_session, monkeypatch) -> None:
    import myah.main as main_mod

    monkeypatch.setattr(main_mod, '_is_oss_mode', lambda: False)
    monkeypatch.setattr(
        main_mod,
        '_load_hosted_spa_routes',
        lambda: (
            frozenset(
                {
                    '/admin',
                    '/admin/settings',
                    '/admin/users',
                    '/agent/integrations',
                    '/agent/memory',
                    '/agent/skills',
                    '/agent/skills/create',
                    '/agent/skills/edit',
                    '/skills/install',
                }
            ),
            (re.compile(r'^/admin/settings/[^/]+$'), re.compile(r'^/admin/users/[^/]+$')),
        ),
    )

    for path in (
        'admin',
        'agent/integrations',
        'agent/memory',
        'agent/skills',
        'agent/skills/create',
        'agent/skills/edit',
        'skills/install',
        'admin/users/general',
        'admin/settings/db',
    ):
        assert main_mod.is_spa_route(path) is True, path
    # OSS routes still match in hosted mode
    assert main_mod.is_spa_route('c/abc') is True
    # multi-segment under a hosted dynamic route still 404s
    assert main_mod.is_spa_route('admin/users/general/extra') is False
    assert main_mod.is_spa_route('totally-fake') is False


@pytest.fixture
def spa_client(db_session, tmp_path) -> TestClient:
    from myah.main import SPAStaticFiles

    build = tmp_path / 'build'
    (build / '_app' / 'immutable' / 'chunks').mkdir(parents=True)
    (build / 'index.html').write_text('<!doctype html><html>shell</html>', encoding='utf-8')
    (build / '_app' / 'immutable' / 'chunks' / 'x.js').write_text('// js', encoding='utf-8')
    (build / 'favicon.ico').write_text('icon', encoding='utf-8')

    app = FastAPI()
    app.mount('/', SPAStaticFiles(directory=str(build), html=True), name='spa')
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize('path', ['/', '/auth', '/c/abc-123', '/notes/xyz', '/agent/tools/create'])
def test_valid_spa_routes_serve_shell(spa_client: TestClient, path: str) -> None:
    r = spa_client.get(path)
    assert r.status_code == 200, f'GET {path} -> {r.status_code}'
    assert '<html' in r.text.lower()


@pytest.mark.parametrize(
    'path',
    [
        '/totally-fake',
        '/wp-login.php',
        '/.env',
        '/sitemap.xml',
        '/sitemap_index.xml',
        '/wp-sitemap.xml',
        '/c/abc/garbage',
        '/notes/a/b',
        # hosted-only routes 404 in OSS (spa_client runs under db_session = OSS mode)
        '/admin',
        '/admin/users/general',
        '/agent/integrations',
        '/agent/skills',
        '/agent/skills/create',
        '/agent/skills/edit',
    ],
)
def test_invalid_public_urls_return_404(spa_client: TestClient, path: str) -> None:
    r = spa_client.get(path)
    assert r.status_code == 404, f'GET {path} -> {r.status_code}'
    assert '<html' not in r.text.lower()


def test_missing_js_returns_404(spa_client: TestClient) -> None:
    assert spa_client.get('/_app/immutable/chunks/missing.js').status_code == 404


def test_immutable_asset_has_long_lived_cache(spa_client: TestClient) -> None:
    r = spa_client.get('/_app/immutable/chunks/x.js')
    assert r.status_code == 200
    assert r.headers['cache-control'] == 'public, max-age=31536000, immutable'


def test_allowlist_covers_every_oss_route(db_session) -> None:
    from myah.main import is_spa_route

    routes_dir = Path(__file__).resolve().parents[3] / 'src' / 'routes'
    uncovered = sorted(p for p in derive_spa_url_paths(routes_dir) if not is_spa_route(p))
    assert not uncovered, (
        f'OSS SvelteKit routes missing from the SPA allowlist in main.py: {uncovered}. '
        'Add them to _SPA_STATIC_ROUTES / _SPA_DYNAMIC_ROUTES.'
    )


_PARAM_LESS_EDIT_PAGES = ('agent/tools/edit',)


def test_param_less_edit_routes_serve_shell_but_path_params_404(db_session) -> None:
    from myah.main import is_spa_route

    for base in _PARAM_LESS_EDIT_PAGES:
        assert is_spa_route(base) is True, f'{base} should serve the shell (query-param page)'
        assert is_spa_route(f'{base}/some-id') is False, (
            f'{base}/<id> must 404 — the page is param-less and reads the entity from the '
            'query string. A path-param deep link is an unsupported/omitted route.'
        )


def test_edit_pages_link_via_query_params_not_path_params() -> None:
    oss_root = Path(__file__).resolve().parents[3]
    monorepo_root = oss_root.parent
    src_roots = [oss_root / 'src']
    hosted_src_root = monorepo_root / 'platform-hosted' / 'src'
    if hosted_src_root.exists():
        src_roots.append(hosted_src_root)

    sources = '\n'.join(
        p.read_text(encoding='utf-8')
        for src_root in src_roots
        for p in src_root.rglob('*.svelte')
    )

    assert 'skills/edit?name=' in sources, 'skills edit deep link should use ?name= query param'
    assert 'tools/edit?id=' in sources, 'tools edit deep link should use ?id= query param'

    offenders = [
        m for m in re.findall(r'agent/(?:skills|tools)/edit/[^"\'`)\s?]+', sources)
        if not m.endswith('/edit')
    ]
    assert not offenders, (
        'Found path-param deep links to the param-less edit pages: '
        f'{sorted(set(offenders))}. These 404 under the SPA allowlist — use a query param '
        '(?name=/?id=) or add a [param] route to platform-oss/src/routes.'
    )
