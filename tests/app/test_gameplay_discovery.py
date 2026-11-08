import json

import pytest

from arknights_unpacker.application import AppServices


ACTIVITY = 'gamedata/excel/activity_table071163'
LEVEL = 'gamedata/levels/activities/act3autochess/level_act3autochess_01'
ROGUELIKE = 'gamedata/excel/roguelike_topic_tablec913b6'


@pytest.fixture
def gameplay_installation(tmp_path):
    game = tmp_path / 'game'
    game.mkdir()
    entries = []
    for name in ('activity.ab', 'levels.ab', 'rogue.ab'):
        (game / name).write_bytes(b'asset')
        entries.append({'name': name, 'abSize': 5, 'md5': 'abcd'})
    (game / 'manifest.idx').write_bytes(b'index')
    manifest = {'manifestName': 'manifest.idx', 'manifestVersion': 'V079',
                'versionId': 'resource-1', 'abInfos': entries}
    (game / 'hot_update_list.json').write_text(json.dumps(manifest), encoding='utf-8')
    return game


def test_scan_discovers_pages_and_restart_restores_without_game(gameplay_installation, tmp_path, monkeypatch):
    from arknights_unpacker.extraction import gameplay

    def read_index(path):
        assert path.name == 'manifest.idx'
        return {'assets': [
            {'assetName': ACTIVITY, 'bundle': 'activity.ab'},
            {'assetName': LEVEL, 'bundle': 'levels.ab'},
            {'assetName': LEVEL, 'bundle': 'levels.ab'},
            {'assetName': ROGUELIKE, 'bundle': 'rogue.ab'},
            {'assetName': 'gamedata/levels/activities/ordinary/level_01', 'bundle': 'levels.ab'},
        ]}

    monkeypatch.setattr(gameplay, 'read_resource_manifest', read_index)
    game = gameplay_installation
    services = AppServices(tmp_path / 'data', tmp_path / 'exports')
    monkeypatch.setattr(services.runner, 'run', lambda *a, **kw: pytest.fail('scan decoded gameplay'))
    services.scan(game)
    catalog = services.gameplay_catalog
    levels = services.level_catalog
    assert catalog['resource_version'] == 'resource-1'
    assert [mode['id'] for mode in catalog['modes']] == ['autochess', 'roguelike']
    autochess, roguelike = catalog['modes']
    assert autochess['supported'] and autochess['available']
    assert autochess['resources'] == [ACTIVITY]
    assert autochess['level_paths'] == [LEVEL]
    assert roguelike['resources'] == [ROGUELIKE] and not roguelike['supported']
    services.shutdown()

    game.rename(tmp_path / 'offline')
    restored = AppServices(tmp_path / 'data', tmp_path / 'exports')
    try:
        monkeypatch.setattr(gameplay, 'read_resource_manifest',
                            lambda *a: pytest.fail('restore read the game index'))
        restored.restore(game)
        assert restored.gameplay_catalog == catalog
        assert restored.level_catalog == levels
    finally:
        restored.shutdown()


def test_index_error_does_not_fail_resource_scan(gameplay_installation, tmp_path):
    services = AppServices(tmp_path / 'data', tmp_path / 'exports')
    try:
        result = services.scan(gameplay_installation)
        assert result['snapshot'].complete
        assert services.gameplay_catalog['modes'] == []
        assert services.gameplay_catalog['diagnostics']
    finally:
        services.shutdown()


def test_level_catalog_keeps_last_readable_baseline(gameplay_installation, tmp_path, monkeypatch):
    from arknights_unpacker.extraction import gameplay

    game = gameplay_installation
    new_level = 'gamedata/levels/obt/main/level_main_01-02'
    index = {'assets': [{'assetName': LEVEL, 'bundle': 'levels.ab'}]}
    broken = False

    def read_index(path):
        if broken:
            raise ValueError('invalid index')
        return index

    def change_version(version):
        path = game / 'hot_update_list.json'
        manifest = json.loads(path.read_text(encoding='utf-8'))
        manifest['versionId'] = version
        path.write_text(json.dumps(manifest), encoding='utf-8')

    monkeypatch.setattr(gameplay, 'read_resource_manifest', read_index)
    services = AppServices(tmp_path / 'data', tmp_path / 'exports')
    try:
        services.scan(game)
        assert [(row['id'], row['is_new']) for row in services.level_catalog['levels']] == [(LEVEL, False)]

        broken = True
        change_version('resource-2')
        services.scan(game)
        assert not services.level_catalog['levels']

        broken = False
        change_version('resource-3')
        index['assets'].append({'assetName': new_level, 'bundle': 'levels.ab'})
        for _ in range(2):
            services.scan(game)
            assert [row['id'] for row in services.level_catalog['levels'] if row['is_new']] == [new_level]
    finally:
        services.shutdown()


def test_gameplay_job_checks_catalog_and_only_loads_requested_assets(gameplay_installation, tmp_path, monkeypatch):
    services = AppServices(tmp_path / 'data', tmp_path / 'exports')
    services.gameplay_catalog = {
        'root': str(gameplay_installation), 'resource_version': 'resource-1',
        'modes': [{'id': 'autochess', 'supported': True, 'available': True,
                   'resources': [ACTIVITY], 'level_paths': [LEVEL]}],
    }
    calls = []

    def worker(operation, args, emit, cancel):
        calls.append((operation, args))
        return {'resource_version': args['resource_version']}

    monkeypatch.setattr(services.runner, 'run', worker)
    try:
        with pytest.raises(ValueError, match='重新扫描'):
            services.load_gameplay(gameplay_installation, 'autochess', 'resource-0')
        with pytest.raises(ValueError, match='关卡'):
            services.load_gameplay_level(gameplay_installation, 'gamedata/other/level_01', 'resource-1')
        assert calls == []
        services.load_gameplay(gameplay_installation, 'autochess', 'resource-1')
        services.load_gameplay_level(gameplay_installation, LEVEL, 'resource-1')
        assert [(kind, args['logical_path']) for kind, args in calls] == [
            ('gameplay', ACTIVITY), ('gameplay_level', LEVEL),
        ]
    finally:
        services.shutdown()


def test_level_animation_cache_follows_the_scanned_resource_version(gameplay_installation, tmp_path):
    from arknights_unpacker.level_preview_cache import preview_directory, preview_filename

    services = AppServices(tmp_path / 'data', tmp_path / 'exports')
    game = gameplay_installation.resolve()
    services.level_catalog = {'root': str(game), 'resource_version': 'resource-1',
                              'levels': [{'id': LEVEL, 'available': True}]}
    directory = preview_directory(services.data_root, game, 'resource-1')
    directory.mkdir(parents=True)
    clip = directory / preview_filename(LEVEL)
    clip.touch()
    try:
        assert services.level_preview_clips(game, 'resource-1') == {LEVEL: clip}
        with pytest.raises(ValueError, match='重新扫描'):
            services.level_preview_clips(tmp_path / 'another-game', 'resource-1')
        services.level_catalog['resource_version'] = 'resource-2'
        assert services.level_preview_clips(game, 'resource-2') == {}
    finally:
        services.shutdown()
