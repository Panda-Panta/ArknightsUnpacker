from dataclasses import replace
import sqlite3

from arknights_unpacker.contracts import (EntityChangeSet, FileChange, FileChangeSet,
                                         FileRecord, GameDataSnapshot, ScanSnapshot)
from arknights_unpacker.library import CatalogStore, dumps_snapshot


def test_store_reopens_last_partial_scan_diff_and_retains_complete_baseline(tmp_path):
    path = tmp_path / 'catalog.sqlite3'
    store = CatalogStore(path)
    first = ScanSnapshot('complete', 'profile', str(tmp_path / 'game'), 1, 2, [FileRecord('one.ab', 1, 1)])
    second = replace(first, snapshot_id='partial', started_at=3, complete=False, errors=['read denied'], baseline_id='complete')
    changes = FileChangeSet('complete', 'partial', diagnostics=['扫描不完整，基线保持不变'])
    store.save_scan(first)
    store.save_scan(second, changes)
    reopened = CatalogStore(path)
    saved, saved_changes = reopened.latest_scan_result('profile')
    assert saved == second and saved_changes == changes
    assert reopened.latest_scan('profile') == first


def test_data_result_remembers_diff_and_selected_comparison_baseline(tmp_path):
    path = tmp_path / 'catalog.sqlite3'
    store = CatalogStore(path)
    baseline = GameDataSnapshot('imported', '1', 'r1', {}, created_at=1)
    data = GameDataSnapshot('current', '2', 'r2', {}, created_at=2)
    changes = EntityChangeSet('imported', 'current', modules=[{'equip_id': 'new-module', 'kind': 'added'}])
    store.save_data_snapshot('profile', data, changes, baseline=baseline)
    reopened = CatalogStore(path)
    saved, diff, explicit = reopened.latest_data_result('profile')
    assert saved == data and diff == changes and explicit == baseline
    assert reopened.latest_data_snapshot('profile') == data
    assert reopened.latest_data_result('different-profile') == (None, None, None)


def test_v2_upgrade_backs_up_and_restores_legacy_diff_against_earlier_snapshot(tmp_path):
    path = tmp_path / 'old.sqlite3'
    first = ScanSnapshot('first', 'profile', str(tmp_path / 'game'), 1, 2, [FileRecord('old.ab', 1, 1)])
    new_file = FileRecord('new.ab', 2, 3)
    second = replace(first, snapshot_id='second', started_at=3, files=[*first.files, new_file], baseline_id='first')
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE scans(id TEXT PRIMARY KEY,profile_id TEXT NOT NULL,started REAL NOT NULL,finished REAL NOT NULL,complete INTEGER NOT NULL,payload TEXT NOT NULL)')
        for scan in (first, second):
            db.execute('INSERT INTO scans VALUES(?,?,?,?,?,?)', (scan.snapshot_id, scan.profile_id, scan.started_at, scan.finished_at, 1, dumps_snapshot(scan)))
        db.execute('PRAGMA user_version=2')
    store = CatalogStore(path)
    saved, diff = store.latest_scan_result('profile')
    assert saved == second
    assert diff.baseline_id == 'first'
    assert diff.changes == [FileChange('added', 'new.ab', None, new_file)]
    backups = list(tmp_path.glob('old.sqlite3.v2-backup-*.sqlite'))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 2
        assert db.execute('SELECT COUNT(*) FROM scans').fetchone()[0] == 2
    CatalogStore(path)
    assert len(list(tmp_path.glob('old.sqlite3.v2-backup-*.sqlite'))) == 1
