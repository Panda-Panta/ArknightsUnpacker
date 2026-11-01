"""Saved comparisons are re-evaluated without decoding or changing the baseline choice."""
from dataclasses import replace
import json
from pathlib import Path

import pytest

from arknights_unpacker.application import AppServices
from arknights_unpacker.contracts import DecodedTable, EntityChangeSet, TableSourceSet
from arknights_unpacker.gamedata import load_gamedata


@pytest.mark.parametrize('explicit', [False, True])
def test_restore_recomputes_saved_changes_from_the_original_baseline(tmp_path, monkeypatch, explicit):
    fixture = json.loads((Path(__file__).parents[1] / 'gamedata/fixtures/fixed_reference.json').read_text('utf-8'))
    data = load_gamedata(TableSourceSet(
        tables={name: DecodedTable(name, raw) for name, raw in fixture['tables'].items()},
        version=fixture['version'], resource_version=fixture['resource_version'], locale='zh_CN'))
    old = replace(data, snapshot_id='original-baseline', created_at=1)
    current = replace(data, snapshot_id='current', created_at=2)
    unrelated = replace(data, snapshot_id='later-snapshot', created_at=3)
    stale = EntityChangeSet(old.snapshot_id, current.snapshot_id,
        operators=[{'id': char_id, 'kind': 'modified'} for char_id in data.tables['_indexes']['operators']],
        modules=[{'id': 'uniequip_002_angel', 'kind': 'modified'}])
    game = tmp_path / 'game'
    bundles = game / 'Arknights_Data/StreamingAssets/AB/Windows'
    bundles.mkdir(parents=True)
    (bundles / 'sample.ab').write_bytes(b'fixture')
    service = AppServices(tmp_path / 'data')
    service._installation(game)
    profile_id = service.installation.profile_id
    service.store.save_data_snapshot(profile_id, old)
    service.store.save_data_snapshot(profile_id, current, stale, baseline=old if explicit else None)
    service.store.save_data_snapshot(profile_id, unrelated)
    service.store.save_data_changes(profile_id, current, stale, baseline=old if explicit else None)
    service.shutdown()
    restored = AppServices(tmp_path / 'data')
    monkeypatch.setattr(restored.runner, 'run', lambda *args, **kwargs: pytest.fail('restore decoded the game'))
    result = restored.restore(game)
    changes = result['entity_changes']
    assert changes.baseline_id == old.snapshot_id
    assert changes.current_id == current.snapshot_id
    assert changes.operators == [] and changes.modules == []
    assert restored.baseline == (old if explicit else None)
    assert restored.store.latest_data_snapshot(profile_id).snapshot_id == unrelated.snapshot_id
    assert restored.store.get_data_snapshot(current.snapshot_id, profile_id=profile_id) == current
    restored.shutdown()
    # Rules are versioned so subsequent launches do not repeat a full comparison.
    reopened = AppServices(tmp_path / 'data')
    monkeypatch.setattr('arknights_unpacker.gamedata.compare_entities',
                        lambda *args: pytest.fail('unchanged rules repeated the comparison'))
    assert reopened.restore(game)['entity_changes'] == changes
    assert reopened.baseline == (old if explicit else None)
    reopened.shutdown()
