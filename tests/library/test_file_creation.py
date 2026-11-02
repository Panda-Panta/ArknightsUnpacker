"""Creation time is filesystem metadata, separate from scan observation history."""
from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from arknights_unpacker.contracts import GameInstallation, ScanOptions
from arknights_unpacker.library import compare_files, scan_installation
from arknights_unpacker.library import scan as scan_module
from arknights_unpacker.library.serialization import dumps_snapshot, loads_snapshot
from arknights_unpacker.library.store import CatalogStore


@pytest.fixture
def installation(tmp_path):
    root = tmp_path / 'game'
    root.mkdir()
    path = root / 'sample.ab'
    path.write_bytes(b'resource')
    return GameInstallation(root, 'fixture-profile', base_root=root), path


def test_scan_captures_real_birth_time_and_preserves_first_observation(installation):
    source, path = installation
    expected = getattr(path.stat(), 'st_birthtime_ns', None)
    if expected is None:
        pytest.skip('filesystem does not expose nanosecond birth time')
    first = scan_installation(source)
    assert first.complete
    assert first.files[0].created_ns == expected
    assert first.files[0].first_seen_at == first.started_at
    first.files[0].first_seen_at = 123.25
    second = scan_installation(source, baseline=first)
    assert second.complete
    assert second.files[0].created_ns == expected
    assert second.files[0].first_seen_at == 123.25
    assert not compare_files(first, second).changes


def test_scan_does_not_substitute_ctime_or_first_seen_for_missing_birth_time(installation, monkeypatch):
    source, path = installation
    original = os.scandir

    class Entry:
        def __init__(self, entry):
            self.entry = entry

        def __getattr__(self, name):
            return getattr(self.entry, name)

        def stat(self, **kwargs):
            info = self.entry.stat(**kwargs)
            # Simulate a platform whose ctime means metadata-change time.
            return SimpleNamespace(st_mode=info.st_mode, st_size=info.st_size,
                                   st_mtime_ns=info.st_mtime_ns, st_ctime_ns=1234567890123456789)

    class Entries:
        def __init__(self, folder):
            self.entries = original(folder)

        def __enter__(self):
            return (Entry(entry) for entry in self.entries.__enter__())

        def __exit__(self, *args):
            return self.entries.__exit__(*args)

    monkeypatch.setattr(scan_module.os, 'scandir', Entries)
    snapshot = scan_installation(source)
    assert snapshot.complete
    assert snapshot.files[0].created_ns is None
    assert snapshot.files[0].first_seen_at == snapshot.started_at


def test_hashed_record_uses_creation_time_from_final_stat(installation, monkeypatch):
    source, path = installation
    before = path.stat()
    final_stat = SimpleNamespace(st_size=before.st_size, st_mtime_ns=before.st_mtime_ns,
                                st_birthtime_ns=1234567890123456789)
    monkeypatch.setattr(scan_module, '_digest', lambda *args: ('d' * 64, final_stat))
    snapshot = scan_installation(source, ScanOptions(strict=True))
    assert snapshot.complete
    assert snapshot.files[0].hash_status == 'verified'
    assert snapshot.files[0].created_ns == final_stat.st_birthtime_ns
    assert snapshot.files[0].first_seen_at == snapshot.started_at


def test_hashed_record_retains_unknown_when_final_stat_has_no_creation_time(installation, monkeypatch):
    source, path = installation
    before = path.stat()
    final_stat = SimpleNamespace(st_size=before.st_size, st_mtime_ns=before.st_mtime_ns,
                                st_ctime_ns=1234567890123456789)
    monkeypatch.setattr(scan_module, '_digest', lambda *args: ('d' * 64, final_stat))
    snapshot = scan_installation(source, ScanOptions(strict=True))
    assert snapshot.complete
    assert snapshot.files[0].created_ns is None


def test_old_snapshot_defaults_unknown_without_accessing_source(installation, monkeypatch):
    source, _ = installation
    snapshot = scan_installation(source)
    envelope = json.loads(dumps_snapshot(snapshot))
    del envelope['snapshot']['files'][0]['created_ns']

    def unavailable(*args, **kwargs):
        raise AssertionError('restoring a saved snapshot must not stat source files')

    monkeypatch.setattr(Path, 'stat', unavailable)
    restored = loads_snapshot(json.dumps(envelope))
    assert restored.files[0].created_ns is None
    assert restored.files[0].first_seen_at == snapshot.started_at


def test_creation_time_survives_json_and_store_round_trip(installation, tmp_path):
    source, _ = installation
    snapshot = scan_installation(source)
    snapshot.files[0].created_ns = 1234567890123456789
    restored = loads_snapshot(dumps_snapshot(snapshot))
    assert restored.files[0].created_ns == 1234567890123456789
    assert restored.files[0].first_seen_at == snapshot.started_at
    store = CatalogStore(tmp_path / 'catalog.sqlite')
    store.save_scan(restored)
    stored = store.latest_scan(source.profile_id)
    assert stored.files[0].created_ns == 1234567890123456789
    assert stored.files[0].first_seen_at == snapshot.started_at
