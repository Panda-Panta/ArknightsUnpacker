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
    result = services.scan(game)
    catalog = services.gameplay_catalog
    assert 'level_catalog' not in result['snapshot'].manifest_versions
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


def test_gameplay_level_worker_returns_level_summary(tmp_path, monkeypatch):
    from arknights_unpacker.contracts import DecodedTable, TableSourceSet
    from arknights_unpacker.extraction import gameplay
    from arknights_unpacker.jobs import worker_entry

    level_name = LEVEL.rsplit('/', 1)[-1]
    level = {'mapData': {'map': {'rowSize': 7, 'columnSize': 9}}, 'routes': [{}],
             'waves': [{}, {}], 'enemyDbRefs': [{'id': 'enemy_01'}]}

    def load_tables(_root, _cache, _emit, _cancel, *, logical_names, expected_resource_version, **_kwargs):
        assert logical_names == {level_name: LEVEL}
        return TableSourceSet(tables={level_name: DecodedTable(level_name, level)},
                              resource_version=expected_resource_version)

    monkeypatch.setattr(gameplay, 'load_local_tables', load_tables)
    result = tmp_path / 'result.json'
    request = tmp_path / 'request.json'
    request.write_text(json.dumps({
        'operation': 'gameplay_level', 'result_file': str(result),
        'args': {'root': str(tmp_path), 'logical_path': LEVEL, 'resource_version': 'resource-1'},
    }), encoding='utf-8')
    status = worker_entry(str(request))
    payload = json.loads(result.read_text(encoding='utf-8'))
    assert status == 0, payload
    assert payload['value'] == {
        'level_id': level_name, 'map_size': [7, 9], 'route_count': 1, 'wave_count': 2,
        'enemy_ids': ['enemy_01'], 'resource_version': 'resource-1', 'diagnostics': [],
    }
