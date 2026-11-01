"""A legacy data-only result is cached without changing snapshots or baseline mode."""
from dataclasses import replace
import json
from pathlib import Path
import sqlite3

import pytest

from arknights_unpacker.application import AppServices
from arknights_unpacker.contracts import DecodedTable, TableSourceSet
from arknights_unpacker.gamedata import load_gamedata


def saved_payloads(database):
    with sqlite3.connect(database) as connection:
        data = connection.execute('SELECT profile_id,id,payload FROM data_snapshots ORDER BY profile_id,id').fetchall()
        scans = connection.execute('SELECT profile_id,id,payload FROM scans ORDER BY profile_id,id').fetchall()
    return data, scans


def test_legacy_restore_compares_once_and_keeps_snapshots_and_automatic_baseline(tmp_path, monkeypatch):
    import arknights_unpacker.gamedata as gamedata

    fixture = json.loads((Path(__file__).parents[1] / 'gamedata/fixtures/fixed_reference.json').read_text('utf-8'))
    data = load_gamedata(TableSourceSet(
        tables={name: DecodedTable(name, value) for name, value in fixture['tables'].items()},
        version=fixture['version'], resource_version=fixture['resource_version'], locale='zh_CN'))
    old = replace(data, snapshot_id='legacy-old', created_at=1)
    current = replace(data, snapshot_id='legacy-current', created_at=2)
    game = tmp_path / 'game'
    bundles = game / 'Arknights_Data/StreamingAssets/AB/Windows'
    bundles.mkdir(parents=True)
    (bundles / 'sample.ab').write_bytes(b'UnityFS-fixture')
    directory = tmp_path / 'data'
    initial = AppServices(directory)
    initial.scan(game)
    profile = initial.installation.profile_id
    initial.store.save_data_snapshot(profile, old)
    initial.store.save_data_snapshot(profile, current)
    initial.shutdown()
    database = directory / 'catalog.sqlite3'
    # Older stores can have saved snapshots without the newer visible-result row.
    with sqlite3.connect(database) as connection:
        connection.execute("DELETE FROM result_state WHERE kind='data'")
    original_payloads = saved_payloads(database)
    original_compare = gamedata.compare_entities
    calls = []

    def compare(before, after):
        calls.append((before.snapshot_id if before else None, after.snapshot_id))
        return original_compare(before, after)

    monkeypatch.setattr(gamedata, 'compare_entities', compare)
    comparisons = []
    for _ in range(2):
        restored = AppServices(directory)
        monkeypatch.setattr(restored.runner, 'run', lambda *args, **kwargs: pytest.fail('restore decoded the game'))
        result = restored.restore(game)
        comparisons.append(result['entity_changes'])
        assert restored.baseline is None
        assert restored.gamedata == current
        assert restored.store.latest_data_snapshot(profile) == current
        restored.shutdown()
        assert saved_payloads(database) == original_payloads
    assert calls == [('legacy-old', 'legacy-current')]
    assert comparisons[0] == comparisons[1]
    assert comparisons[0].baseline_id == old.snapshot_id
    with sqlite3.connect(database) as connection:
        cached = connection.execute("SELECT snapshot_id,baseline FROM result_state WHERE profile_id=? AND kind='data'", (profile,)).fetchone()
    assert cached == (current.snapshot_id, None)
