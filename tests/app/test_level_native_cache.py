from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from threading import Barrier

import pytest

from arknights_unpacker import level_native_atlases, level_native_cache
from arknights_unpacker.contracts import CancelToken, CancelledError, null_progress
from arknights_unpacker.extraction import level_replay_assets


@pytest.fixture
def native_replay(tmp_path, monkeypatch):
    (tmp_path / 'data').mkdir()
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

    def prepare(cancel=None, *, prewarm=False, **changes):
        return level_native_cache.prepare_cached_native_replay(
            tmp_path / 'data/runtime', {**options, **changes},
            emit=null_progress, cancel=cancel or CancelToken(), prewarm=prewarm)

    return prepare, calls, options


def test_native_replay_reuses_complete_assets_and_rebuilds_missing_files(tmp_path, monkeypatch, native_replay):
    prepare, calls, options = native_replay
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


def test_prewarm_budget_checks_before_extracting_and_again_before_publishing(tmp_path, monkeypatch, native_replay):
    prepare, calls, _ = native_replay
    root = tmp_path / 'data/native-level-replays'
    cached = prepare()
    size = sum(path.stat().st_size for path in Path(cached['native_assets']).rglob('*') if path.is_file())
    monkeypatch.setattr(level_native_cache, '_PREWARM_MAX_BYTES', size)

    assert prepare(prewarm=True) == {**cached, 'native_cache_hit': True}
    with pytest.raises(level_native_cache.NativeReplayPrewarmBudgetError, match='手动准备'):
        prepare(prewarm=True, resource_version='v2')
    assert calls == ['v1']

    monkeypatch.setattr(level_native_cache, '_PREWARM_MAX_BYTES', 2 * size - 1)
    with pytest.raises(level_native_cache.NativeReplayPrewarmBudgetError, match='手动准备'):
        prepare(prewarm=True, resource_version='v2')
    assert calls == ['v1', 'v2']
    assert list(root.glob('*/assets-*')) == [Path(cached['native_assets'])]
    assert len(list(root.glob('*/ready.json'))) == 1

    assert not prepare(resource_version='v2')['native_cache_hit']
    assert len(list(root.glob('*/ready.json'))) == 2


def test_concurrent_prewarm_publication_respects_shared_budget(tmp_path, monkeypatch, native_replay):
    prepare, _, _ = native_replay
    monkeypatch.setattr(level_native_cache, '_PREWARM_MAX_BYTES', 11)
    barrier = Barrier(2, timeout=10)
    bake = level_native_atlases.prepare_native_atlases

    def simultaneous(*args, **kwargs):
        bake(*args, **kwargs)
        barrier.wait()

    monkeypatch.setattr(level_native_atlases, 'prepare_native_atlases', simultaneous)

    def warm(version):
        try:
            return prepare(prewarm=True, resource_version=version)
        except level_native_cache.NativeReplayPrewarmBudgetError:
            return None
        except Exception:
            barrier.abort()
            raise

    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(warm, version) for version in ('v1', 'v2')]
        errors = [error for future in futures if (error := future.exception()) is not None]
        if errors:
            raise ExceptionGroup('Concurrent prewarm failed', errors)
        results = [future.result() for future in futures]
    assert sum(result is not None for result in results) == 1
    root = tmp_path / 'data/native-level-replays'
    assert len(list(root.glob('*/assets-*'))) == len(list(root.glob('*/ready.json'))) == 1


def test_prewarm_budget_does_not_count_linked_slots(tmp_path, monkeypatch, native_replay):
    prepare, _, options = native_replay
    cached = prepare()
    generation = Path(cached['native_assets'])
    source = generation.parent / 'ready.json'
    record = json.loads(source.read_text(encoding='utf-8'))
    monkeypatch.setattr(level_native_cache, '_PREWARM_MAX_BYTES', 2 * sum(record['files'].values()))

    outside = tmp_path / 'unmanaged'
    outside.mkdir()
    (outside / source.name).write_text(json.dumps(record), encoding='utf-8')
    (outside / generation.name).mkdir()
    identity = {key: value for key, value in options.items() if key != 'output'}
    slot, _ = level_native_cache._cache_slot(tmp_path / 'data', {**identity, 'resource_version': 'v3'})
    try:
        slot.symlink_to(outside, target_is_directory=True)
    except OSError as error:
        pytest.skip(f'Symlinks unavailable: {error}')

    assert not prepare(prewarm=True, resource_version='v2')['native_cache_hit']
    with pytest.raises(ValueError, match='缓存路径越界'):
        prepare(resource_version='v3')
