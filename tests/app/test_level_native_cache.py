from pathlib import Path

import pytest

from arknights_unpacker import level_native_atlases, level_native_cache
from arknights_unpacker.contracts import CancelToken, CancelledError, null_progress
from arknights_unpacker.extraction import level_replay_assets


def test_native_replay_reuses_complete_assets_and_rebuilds_missing_files(tmp_path, monkeypatch):
    calls = []

    def extract(**args):
        calls.append(args['resource_version'])
        assets = args['output']
        (assets / 'fixture.json').write_text('{}')
        (assets / 'scene-layout.json').write_text('{}')
        return {'level_id': args['level_id'], 'resource_version': args['resource_version'], 'seed': len(calls)}

    def bake(assets, *_args, **_kwargs):
        actors = assets / 'native-actors'
        actors.mkdir()
        (actors / 'index.json').write_text('{}')
        (actors / 'enemy.png').write_bytes(b'atlas')

    monkeypatch.setattr(level_replay_assets, 'prepare_level_playback', extract)
    monkeypatch.setattr(level_native_atlases, 'prepare_native_atlases', bake)
    options = {'game_root': str(tmp_path / 'game'), 'level_id': 'campaign/test',
               'output': str(tmp_path / 'data/preview/lease'), 'resource_version': 'v1'}

    def prepare(cancel=None, **changes):
        return level_native_cache.prepare_cached_native_replay(
            tmp_path / 'data/runtime', {**options, **changes},
            emit=null_progress, cancel=cancel or CancelToken())

    first = prepare()
    assert not first['native_cache_hit']
    assert prepare() == {**first, 'native_cache_hit': True}
    identity = {key: value for key, value in options.items() if key != 'output'}
    cached = level_native_cache.cached_native_replay(tmp_path / 'data', {**identity, 'caption': 'Displayed name'})
    assert cached == {**first, 'native_cache_hit': True}
    assert calls == ['v1']
    assert prepare(resource_version='v2')['native_assets'] != first['native_assets']

    (Path(first['native_assets']) / 'native-actors/enemy.png').unlink()
    rebuilt = prepare()
    assert rebuilt['native_assets'] != first['native_assets']
    assert rebuilt['seed'] == 3
    assert prepare() == {**rebuilt, 'native_cache_hit': True}

    def cancel_bake(_assets, *_args, cancel, **_kwargs):
        cancel.cancel()

    monkeypatch.setattr(level_native_atlases, 'prepare_native_atlases', cancel_bake)
    root = tmp_path / 'data/native-level-replays'
    generations = set(root.glob('*/assets-*'))
    with pytest.raises(CancelledError):
        prepare(resource_version='v3')
    assert len(list(root.glob('*/ready.json'))) == 2
    assert set(root.glob('*/assets-*')) == generations
