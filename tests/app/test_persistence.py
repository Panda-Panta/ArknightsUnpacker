"""Application restart regressions: saved results must survive without decoding."""
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from arknights_unpacker.application import AppServices
from arknights_unpacker.contracts import EntityChangeSet, GameDataSnapshot


def make_game(folder):
    game = folder / 'game'
    bundles = game / 'Arknights_Data/StreamingAssets/AB/Windows'
    bundles.mkdir(parents=True)
    (bundles / 'one.ab').write_bytes(b'first')
    return game, bundles


def test_default_data_root_belongs_to_program_not_working_directory(tmp_path, monkeypatch):
    from arknights_unpacker import paths
    source_root = Path(paths.__file__).resolve().parents[2]
    monkeypatch.chdir(tmp_path)
    assert paths.default_data_root() == source_root / 'data'
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', str(tmp_path / 'portable' / 'ArknightsUnpacker.exe'))
    monkeypatch.setattr(sys, '_MEIPASS', str(tmp_path / 'portable' / '_internal'), raising=False)
    assert paths.default_data_root() == tmp_path / 'portable' / 'data'


def test_restart_restores_exact_scan_changes_without_live_game_and_next_scan_compares(tmp_path, monkeypatch):
    game, bundles = make_game(tmp_path)
    data_dir = tmp_path / 'app-data'
    first = AppServices(data_dir)
    before = first.scan(game, strict=True)
    (bundles / 'one.ab').write_bytes(b'second')
    after = first.scan(game, strict=True)
    assert after['changes'].changes[0].kind == 'modified'
    first.shutdown()
    offline = game.with_name('offline-game')
    game.rename(offline)
    restored = AppServices(data_dir)
    monkeypatch.setattr(restored.runner, 'run', lambda *args, **kwargs: pytest.fail('restore decoded game'))
    result = restored.restore(game)
    assert result['snapshot'] == after['snapshot']
    assert result['changes'] == after['changes']
    assert result['changes'].baseline_id == before['snapshot'].snapshot_id
    assert restored.file_changes == after['changes']
    assert restored.installation.root == game
    assert result['catalog'].installation.profile_id == restored.installation.profile_id
    offline.rename(game)
    (bundles / 'new.ab').write_bytes(b'new-file')
    next_scan = restored.scan(game, strict=True)
    assert next_scan['changes'].baseline_id == after['snapshot'].snapshot_id
    assert [(item.kind, Path(item.path).name) for item in next_scan['changes'].changes] == [('added', 'new.ab')]
    restored.shutdown()


def test_restart_keeps_saved_entity_diff_and_partial_observation(tmp_path, monkeypatch):
    import arknights_unpacker.gamedata as gamedata_module
    from arknights_unpacker.library import discover_installation
    game, _ = make_game(tmp_path)
    data_dir = tmp_path / 'app-data'
    first = AppServices(data_dir)
    profile = discover_installation(game).profile_id
    baseline = GameDataSnapshot('old', '1', 'r1', {}, created_at=1, locale='zh_CN')
    current = GameDataSnapshot('new', '2', 'r2', {'character_table': {'char_new': {'name': '新干员'}}}, created_at=2, locale='zh_CN')
    expected = EntityChangeSet('old', 'new', operators=[{'char_id': 'char_new', 'kind': 'added', 'name': '新干员'}])
    first.store.save_data_snapshot(profile, baseline)
    monkeypatch.setattr(first.runner, 'run', lambda *args, **kwargs: {})
    monkeypatch.setattr(gamedata_module, 'load_gamedata', lambda sources: current)
    monkeypatch.setattr(gamedata_module, 'compare_entities', lambda old, new: expected)
    first.load_data(game)
    first.shutdown()
    restored = AppServices(data_dir)
    monkeypatch.setattr(restored.runner, 'run', lambda *args, **kwargs: pytest.fail('restore decoded game'))
    result = restored.restore(game)
    assert result['gamedata'] == current
    assert result['entity_changes'] == expected
    assert restored.operators(changes_only=True)[0]['name'] == '新干员'
    partial = replace(current, complete=False, created_at=3, diagnostics=['partial read'])
    monkeypatch.setattr(restored.runner, 'run', lambda *args, **kwargs: {})
    monkeypatch.setattr(gamedata_module, 'load_gamedata', lambda sources: partial)
    partial_data = restored.load_data(game)
    partial_changes = restored.entity_changes
    restored.shutdown()
    third = AppServices(data_dir)
    third.restore(game)
    assert third.gamedata == partial_data
    assert not third.gamedata.complete
    assert third.entity_changes == partial_changes
    assert third.store.latest_data_snapshot(profile).snapshot_id == current.snapshot_id
    third.shutdown()


def test_switch_installation_clears_all_prior_results(tmp_path):
    game, _ = make_game(tmp_path)
    other = tmp_path / 'other-game'
    other.mkdir()
    (other / 'other.ab').write_bytes(b'other')
    service = AppServices(tmp_path / 'app-data')
    service.scan(game)
    service.gamedata = GameDataSnapshot('stale', '1', 'r1', {})
    service.entity_changes = EntityChangeSet(None, 'stale')
    service.baseline = service.gamedata
    service._installation(other)
    assert all(getattr(service, name) is None for name in ('scan_snapshot', 'file_changes', 'catalog', 'gamedata', 'entity_changes', 'baseline'))
    service.shutdown()


def test_partial_scan_survives_restart_without_becoming_next_baseline(tmp_path):
    from arknights_unpacker.contracts import CancelToken
    game, bundles = make_game(tmp_path)
    data_dir = tmp_path / 'app-data'
    first = AppServices(data_dir)
    complete = first.scan(game, strict=True)['snapshot']
    token = CancelToken()
    token.cancel()
    partial = first.scan(game, strict=True, cancel=token)
    assert not partial['snapshot'].complete
    first.shutdown()
    reopened = AppServices(data_dir)
    cached = reopened.restore(game)
    assert cached['snapshot'] == partial['snapshot']
    assert cached['changes'] == partial['changes']
    (bundles / 'new.ab').write_bytes(b'new')
    next_scan = reopened.scan(game, strict=True)
    assert next_scan['changes'].baseline_id == complete.snapshot_id
    assert [item.kind for item in next_scan['changes'].changes] == ['added']
    reopened.shutdown()


def test_cancelled_restore_preserves_selected_session_and_does_not_decode(tmp_path):
    from arknights_unpacker.contracts import CancelToken, CancelledError
    game, _ = make_game(tmp_path)
    service = AppServices(tmp_path / 'app-data')
    scanned = service.scan(game)
    token = CancelToken()
    token.cancel()
    with pytest.raises(CancelledError):
        service.restore(game, cancel=token)
    assert service.scan_snapshot == scanned['snapshot']
    assert service.file_changes == scanned['changes']
    service.shutdown()


def test_manual_comparison_selection_and_diff_survive_restart(tmp_path):
    game, _ = make_game(tmp_path)
    data_dir = tmp_path / 'app-data'
    first = AppServices(data_dir)
    first._installation(game)
    profile = first.installation.profile_id
    first.gamedata = GameDataSnapshot('current', '2', 'r2', {}, created_at=2, locale='zh_CN')
    first.store.save_data_snapshot(profile, first.gamedata)
    baseline = GameDataSnapshot('older', '1', 'r1', {}, created_at=1, locale='zh_CN')
    first.store.save_data_snapshot(profile, baseline)
    changes = first.compare_snapshot('older')
    first.shutdown()
    second = AppServices(data_dir)
    second.restore(game)
    assert second.gamedata.snapshot_id == 'current'
    assert second.baseline == baseline
    assert second.entity_changes == changes
    second.shutdown()


def test_default_portable_migrates_old_state_using_sqlite_backup_and_keeps_source(tmp_path, monkeypatch):
    from arknights_unpacker import application, paths
    legacy = tmp_path / 'legacy'
    legacy.mkdir()
    portable = tmp_path / 'portable' / 'data'
    (legacy / 'settings.json').write_text(json.dumps({'hours': 36}), encoding='utf-8')
    (legacy / 'queue').mkdir()
    (legacy / 'queue' / ('a' * 32 + '.json')).write_text('{"old": true}', encoding='utf-8')
    (legacy / 'jobs').mkdir()
    (legacy / 'jobs' / 'large-unneeded.bin').write_bytes(b'unneeded scratch')
    db = sqlite3.connect(legacy / 'catalog.sqlite3')
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('CREATE TABLE committed_evidence(value TEXT)')
    db.execute("INSERT INTO committed_evidence VALUES('WAL content')")
    db.commit()
    monkeypatch.setattr(application, 'default_data_root', lambda: portable)
    monkeypatch.setattr(paths, 'legacy_data_root', lambda: legacy)
    try:
        service = AppServices()
        assert service.data_root == portable
        assert service.config['hours'] == 36
        with sqlite3.connect(portable / 'catalog.sqlite3') as copied:
            assert copied.execute('SELECT value FROM committed_evidence').fetchone()[0] == 'WAL content'
        assert (portable / 'queue' / ('a' * 32 + '.json')).exists()
        assert not (portable / 'jobs' / 'large-unneeded.bin').exists()
        assert (legacy / 'settings.json').exists()
        service.config['hours'] = 48
        service.save_config()
        service.shutdown()
        reopened = AppServices()
        assert reopened.config['hours'] == 48
        reopened.shutdown()
    finally:
        db.close()


def test_explicit_data_root_does_not_import_legacy_or_ignore_write_error(tmp_path, monkeypatch):
    from arknights_unpacker import paths
    legacy = tmp_path / 'legacy'
    legacy.mkdir()
    (legacy / 'settings.json').write_text('{"hours": 99}', encoding='utf-8')
    monkeypatch.setattr(paths, 'legacy_data_root', lambda: legacy)
    service = AppServices(tmp_path / 'explicit')
    assert service.config['hours'] == 24
    service.shutdown()
    readonly = tmp_path / 'readonly'
    original_mkdir = Path.mkdir
    def deny(path, *args, **kwargs):
        if path == readonly:
            raise PermissionError('write denied')
        return original_mkdir(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'mkdir', deny)
    with pytest.raises(PermissionError, match=r'--data-dir'):
        AppServices(readonly)


def test_existing_portable_state_blocks_legacy_import_without_overwrite(tmp_path, monkeypatch):
    from arknights_unpacker import application, paths
    legacy = tmp_path / 'legacy'
    portable = tmp_path / 'portable' / 'data'
    legacy.mkdir()
    portable.mkdir(parents=True)
    (legacy / 'settings.json').write_text('{"hours": 99}', encoding='utf-8')
    (portable / 'settings.json').write_text('{"hours": 12}', encoding='utf-8')
    (legacy / 'queue').mkdir()
    (legacy / 'queue' / 'old.json').write_text('{}', encoding='utf-8')
    monkeypatch.setattr(application, 'default_data_root', lambda: portable)
    monkeypatch.setattr(paths, 'legacy_data_root', lambda: legacy)
    service = AppServices()
    assert service.config['hours'] == 12
    assert not (portable / 'queue').exists()
    assert json.loads((legacy / 'settings.json').read_text(encoding='utf-8'))['hours'] == 99
    service.shutdown()


def test_failed_legacy_read_does_not_publish_partial_state_and_retry_imports(tmp_path, monkeypatch):
    from arknights_unpacker import application, paths
    legacy = tmp_path / 'legacy'
    legacy.mkdir()
    portable = tmp_path / 'portable' / 'data'
    settings = legacy / 'settings.json'
    settings.write_text('{"hours": 36}', encoding='utf-8')
    with sqlite3.connect(legacy / 'catalog.sqlite3') as db:
        db.execute('CREATE TABLE original(value TEXT)')
        db.execute("INSERT INTO original VALUES('preserve')")
    monkeypatch.setattr(application, 'default_data_root', lambda: portable)
    monkeypatch.setattr(paths, 'legacy_data_root', lambda: legacy)
    original_open = Path.open
    def denied(path, *args, **kwargs):
        if path == settings and args and args[0] == 'rb':
            raise PermissionError('source temporarily unavailable')
        return original_open(path, *args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(Path, 'open', denied)
        with pytest.raises(PermissionError, match='temporarily unavailable'):
            AppServices()
    assert not (portable / 'catalog.sqlite3').exists()
    assert not (portable / 'settings.json').exists()
    assert settings.read_text(encoding='utf-8') == '{"hours": 36}'
    service = AppServices()
    assert service.config['hours'] == 36
    with sqlite3.connect(service.data_root / 'catalog.sqlite3') as db:
        assert db.execute('SELECT value FROM original').fetchone()[0] == 'preserve'
    service.shutdown()


_CRASH_IMPORT = '''
import os
from pathlib import Path
import sys
from arknights_unpacker import paths
legacy, portable = map(Path, sys.argv[1:])
paths.legacy_data_root = lambda: legacy
old_copy, old_rename = paths.shutil.copyfileobj, paths.os.rename
def crash_copy(incoming, outgoing, *args, **kwargs):
    result = old_copy(incoming, outgoing, *args, **kwargs)
    if Path(outgoing.name).parent == portable:
        outgoing.flush()
        os.fsync(outgoing.fileno())
        os._exit(37)
    return result
def crash_rename(source, destination, *args, **kwargs):
    result = old_rename(source, destination, *args, **kwargs)
    dest = Path(destination)
    if dest == portable or dest.parent == portable:
        os._exit(37)
    return result
paths.shutil.copyfileobj = crash_copy
paths.os.rename = crash_rename
paths.migrate_legacy_data(portable)
'''


@pytest.mark.parametrize('existing_target', [False, True])
def test_hard_termination_during_legacy_publish_resumes_every_saved_record(tmp_path, monkeypatch, existing_target):
    from arknights_unpacker import application, paths
    legacy = tmp_path / 'legacy'
    legacy.mkdir()
    portable = tmp_path / 'portable' / 'data'
    if existing_target:
        portable.mkdir(parents=True)
        (portable / 'unknown-user-file.txt').write_text('keep this', encoding='utf-8')
    (legacy / 'settings.json').write_text('{"hours": 72}', encoding='utf-8')
    (legacy / 'queue').mkdir()
    (legacy / 'queue' / ('a' * 32 + '.json')).write_text('{"title": "retained task"}', encoding='utf-8')
    with sqlite3.connect(legacy / 'catalog.sqlite3') as db:
        db.execute('CREATE TABLE original(value TEXT)')
        db.execute("INSERT INTO original VALUES('preserve')")
    child = subprocess.run([sys.executable, '-c', _CRASH_IMPORT, str(legacy), str(portable)], check=False)
    assert child.returncode == 37
    monkeypatch.setattr(application, 'default_data_root', lambda: portable)
    monkeypatch.setattr(paths, 'legacy_data_root', lambda: legacy)
    service = AppServices()
    assert service.config['hours'] == 72
    assert (portable / 'queue' / ('a' * 32 + '.json')).read_text(encoding='utf-8') == '{"title": "retained task"}'
    with sqlite3.connect(service.data_root / 'catalog.sqlite3') as db:
        assert db.execute('SELECT value FROM original').fetchone()[0] == 'preserve'
    assert (legacy / 'settings.json').read_text(encoding='utf-8') == '{"hours": 72}'
    if existing_target:
        assert (portable / 'unknown-user-file.txt').read_text(encoding='utf-8') == 'keep this'
    service.shutdown()


def test_interrupted_import_does_not_overwrite_new_portable_settings(tmp_path, monkeypatch):
    from arknights_unpacker import application, paths
    legacy = tmp_path / 'legacy'
    legacy.mkdir()
    portable = tmp_path / 'portable' / 'data'
    portable.mkdir(parents=True)
    (portable / 'unknown-user-file.txt').write_text('keep this', encoding='utf-8')
    (legacy / 'settings.json').write_text('{"hours": 72}', encoding='utf-8')
    with sqlite3.connect(legacy / 'catalog.sqlite3') as db:
        db.execute('CREATE TABLE original(value TEXT)')
        db.execute("INSERT INTO original VALUES('preserve')")
    child = subprocess.run([sys.executable, '-c', _CRASH_IMPORT, str(legacy), str(portable)], check=False)
    assert child.returncode == 37
    assert (portable / '.legacy-import.json').is_file()
    (portable / 'settings.json').write_text('{"hours": 99}', encoding='utf-8')
    monkeypatch.setattr(application, 'default_data_root', lambda: portable)
    monkeypatch.setattr(paths, 'legacy_data_root', lambda: legacy)
    with pytest.raises(PermissionError, match='不同内容'):
        AppServices()
    assert (portable / 'settings.json').read_text(encoding='utf-8') == '{"hours": 99}'
    assert (portable / 'unknown-user-file.txt').read_text(encoding='utf-8') == 'keep this'
    assert (legacy / 'settings.json').read_text(encoding='utf-8') == '{"hours": 72}'


def test_failed_atomic_directory_publish_keeps_originals_and_retries(tmp_path, monkeypatch):
    from arknights_unpacker import application, paths
    legacy = tmp_path / 'legacy'
    legacy.mkdir()
    portable = tmp_path / 'portable' / 'data'
    (legacy / 'settings.json').write_text('{"hours": 72}', encoding='utf-8')
    monkeypatch.setattr(application, 'default_data_root', lambda: portable)
    monkeypatch.setattr(paths, 'legacy_data_root', lambda: legacy)
    old_rename = paths.os.rename
    def denied(source, destination, *args, **kwargs):
        if Path(destination) == portable:
            raise PermissionError('publishing blocked')
        return old_rename(source, destination, *args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(paths.os, 'rename', denied)
        with pytest.raises(PermissionError, match='publishing blocked'):
            AppServices()
    assert not portable.exists()
    assert (legacy / 'settings.json').read_text(encoding='utf-8') == '{"hours": 72}'
    service = AppServices()
    assert service.config['hours'] == 72
    service.shutdown()
