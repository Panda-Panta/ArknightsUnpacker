from contextlib import closing
from http.client import HTTPConnection
from urllib.parse import urlsplit

import pytest

from arknights_unpacker.level_preview_server import LevelPreviewServer, missing_preview_runtime


@pytest.fixture
def preview(tmp_path):
    player, runtime, assets = (tmp_path / name for name in ('player', 'runtime', 'assets'))
    for folder in (player, runtime, assets):
        folder.mkdir()
    for name in ('scene.html', 'scene.js', 'battle_lighting.js'):
        (player / name).write_bytes(name.encode())
    for name in missing_preview_runtime(runtime):
        path = runtime / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(name.encode())
    for name in ('fixture.json', 'scene-layout.json', 'stage.glb', 'actors/e1/actor.skel',
                 'actors/e1/textures/body.png', 'private.json'):
        path = assets / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(name.encode())
    server = LevelPreviewServer(assets, player, runtime)
    try:
        yield server, assets
    finally:
        server.close()


def _fetch(server, file='', *, headers=None, method='GET', absolute=False):
    url = urlsplit(server.url)
    path = file if absolute else url.path.removesuffix('scene.html') + file
    with closing(HTTPConnection(url.hostname, url.port, timeout=3)) as connection:
        connection.request(method, path, headers=headers or {})
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()


def test_replay_serves_only_allowlisted_assets_on_its_own_loopback_origin(preview):
    server, _ = preview
    for file in ('scene.html', 'fixture.json', 'scene-layout.json', 'stage.glb', 'actors/e1/actor.skel',
                 'actors/e1/textures/body.png', 'three/three.module.js', 'pixi-spine.umd.js'):
        status, headers, body = _fetch(server, file)
        assert status == 200 and body == file.encode()
        assert headers['Cache-Control'] == 'no-store'
        assert headers['X-Content-Type-Options'] == 'nosniff'
    assert _fetch(server, 'scene.js', method='HEAD')[2] == b''
    assert _fetch(server, '/scene.html', absolute=True)[0] == 404
    for forbidden in ('private.json', 'actors/e1/', '../fixture.json', '%2E%2e/fixture.json',
                      'actors%5ce1%5cactor.skel'):
        assert _fetch(server, forbidden)[0] == 404
    assert _fetch(server, 'fixture.json', headers={'Host': 'other.example'})[0] == 403
    assert _fetch(server, 'fixture.json', headers={'Origin': 'http://evil.example'})[0] == 403
    assert _fetch(server, 'fixture.json', headers={'Sec-Fetch-Site': 'same-site'})[0] == 403
    server.close()
    with pytest.raises(ConnectionError):
        _fetch(server, 'fixture.json')


def test_replay_rejects_asset_symlinks(preview, tmp_path):
    server, assets = preview
    private = tmp_path / 'elsewhere.glb'
    private.write_bytes(b'private')
    try:
        (assets / 'linked.glb').symlink_to(private)
    except OSError as error:
        pytest.skip(f'Symlinks unavailable: {error}')
    assert _fetch(server, 'linked.glb')[0] == 404
