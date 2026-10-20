from __future__ import annotations
import json
from pathlib import Path
import pytest
from arknights_unpacker.contracts import CancelToken, ScanOptions
from arknights_unpacker.library import discover_installation, load_catalog, scan_installation, compare_files, recent_files, CatalogStore

@pytest.fixture
def game(tmp_path):
    root=tmp_path/'明日 方舟'
    base=root/'Arknights_Data/StreamingAssets/AB/Windows'
    hot=root/'Arknights_Data/PersistentData/Bundles'
    base.mkdir(parents=True); hot.mkdir(parents=True)
    return root,base,hot

def manifest(folder, entries):
    (folder/'hot_update_list.json').write_text(json.dumps({'versionId':'v1','manifestVersion':'V078','abInfos':entries}),encoding='utf8')

def entry(name, md5='a'*32, size=3, **extra):
    return dict(name=name,md5=md5,abSize=size,totalSize=999,**extra)

def test_current_stale_optional_short_and_traversal(game):
    root,base,hot=game
    names=['x.ab','stale.ab','anon/a.bin']
    for name in names:
        p=base/name;p.parent.mkdir(exist_ok=True);p.write_bytes(b'abc')
    (hot/'x.ab').write_bytes(b'abc')
    manifest(base,[entry('x.ab'),entry('stale.ab'),entry('anon/a.bin','abcd')])
    manifest(hot,[entry('x.ab'),entry('stale.ab','b'*32,size=4),entry('anon/a.bin','abcd'),entry('v.ab',type='voice_en'),entry('absent.ab'),entry('../escape.ab')])
    catalog=load_catalog(discover_installation(root))
    assert catalog.resources['x.ab'].layer=='hot'
    assert catalog.resources['stale.ab'].status=='stale'
    assert catalog.resources['v.ab'].status=='not_installed_optional'
    assert catalog.resources['absent.ab'].status=='missing'
    assert catalog.resources['anon/a.bin'].metadata['hash_kind']=='short_token'
    assert catalog.resources['anon/a.bin'].status=='unverified'
    assert '../escape.ab' not in catalog.resources
    assert catalog.diagnostics

def test_scan_diff_strict_and_cancel(game,tmp_path):
    import os
    root,base,hot=game
    p=base/'x.ab';p.write_bytes(b'abc')
    old=scan_installation(discover_installation(root),ScanOptions(strict=True))
    p.write_bytes(b'def');os.utime(p,ns=(old.files[0].mtime_ns,old.files[0].mtime_ns))
    new=scan_installation(discover_installation(root),ScanOptions(strict=True),baseline=old)
    assert [c.kind for c in compare_files(old,new).changes]==['modified']
    p.touch();same=scan_installation(discover_installation(root),ScanOptions(strict=True),baseline=new)
    assert [c.kind for c in compare_files(new,same).changes]==['metadata_only']
    assert compare_files(None,old).changes==[]
    token=CancelToken();token.cancel()
    partial=scan_installation(discover_installation(root),ScanOptions(),cancel=token)
    assert not partial.complete
    assert not compare_files(old,partial).changes
    store=CatalogStore(tmp_path/'db.sqlite');store.save_scan(old);store.save_scan(partial)
    assert store.latest_scan(old.profile_id).snapshot_id==old.snapshot_id
    assert len(store.list_scans(old.profile_id))==2

def test_recent_fixed_window_and_no_future(game):
    from arknights_unpacker.contracts import ScanSnapshot,FileRecord
    s=ScanSnapshot('x','p','r',100000,100001,[FileRecord('a',1,int((100000-1800)*1e9)),FileRecord('b',1,int(100001*1e9))])
    assert [f.path for f in recent_files(s,.5)]==['a']
    for h in [0,-1,float('nan'),float('inf')]:
        with pytest.raises(ValueError):recent_files(s,h)

def test_resource_only_and_unknown(game):
    root,base,hot=game;(base/'anon').mkdir();(base/'anon/a.bin').write_bytes(b'abc')
    (root/'mmkv').mkdir();(root/'mmkv/account').write_bytes(b'private')
    snapshot=scan_installation(discover_installation(root),ScanOptions(resource_only=True))
    assert len(snapshot.files)==1 and snapshot.files[0].layer=='base'
    with pytest.raises(ValueError):discover_installation(root/'mmkv')

def test_same_metadata_fast_is_explicit_and_strict_detects(game):
    import os
    root,base,hot=game;p=base/'a.ab';p.write_bytes(b'aaa')
    old=scan_installation(discover_installation(root),ScanOptions(strict=True))
    stamp=p.stat().st_mtime_ns;p.write_bytes(b'bbb');os.utime(p,ns=(stamp,stamp))
    fast=scan_installation(discover_installation(root),ScanOptions(),baseline=old)
    assert fast.files[0].hash_status=='metadata_unchanged'
    assert compare_files(old,fast).changes==[]
    strict=scan_installation(discover_installation(root),ScanOptions(strict=True),baseline=old)
    assert compare_files(old,strict).changes[0].kind=='modified'

def test_removed_rename_and_coverage(game):
    root,base,hot=game;p=base/'a.ab';p.write_bytes(b'aaa')
    old=scan_installation(discover_installation(root),ScanOptions(strict=True))
    p.rename(base/'b.ab')
    new=scan_installation(discover_installation(root),ScanOptions(strict=True),baseline=old)
    assert {x.kind for x in compare_files(old,new).changes}=={'added','removed'}
    narrowed=scan_installation(discover_installation(root),ScanOptions(resource_only=True))
    assert not compare_files(old,narrowed).changes

def test_unstable_hash_no_complete_baseline(game,monkeypatch):
    import arknights_unpacker.library.scan as scan_module
    root,base,hot=game;(base/'a.ab').write_bytes(b'aaa')
    def unstable(*args):raise OSError('unstable: concurrently written')
    monkeypatch.setattr(scan_module,'_digest',unstable)
    result=scan_installation(discover_installation(root),ScanOptions(strict=True))
    assert not result.complete and result.files[0].hash_status=='unstable'

def test_data_snapshots_roundtrip_and_threads(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from arknights_unpacker.contracts import GameDataSnapshot
    from arknights_unpacker.library import dumps_snapshot,loads_snapshot
    store=CatalogStore(tmp_path/'catalog.sqlite')
    good=GameDataSnapshot('good','v','r',{'character_table':{'汉字':'值'}},created_at=1)
    bad=GameDataSnapshot('bad','v','r',{},complete=False,created_at=2)
    with ThreadPoolExecutor(max_workers=1) as pool:pool.submit(store.save_data_snapshot,'p',good).result()
    store.save_data_snapshot('p',bad)
    assert store.latest_data_snapshot('p')==good
    assert store.get_data_snapshot('bad')==bad
    assert loads_snapshot(dumps_snapshot(good))==good
    assert len(store.list_data_snapshots('p'))==2

def test_no_manifest_and_reparse(game):
    import os
    root,base,hot=game
    assert not load_catalog(discover_installation(root)).resources
    target=root.parent/'external';target.mkdir();(target/'x.ab').write_bytes(b'private')
    try:os.symlink(target,base/'linked',target_is_directory=True)
    except OSError:pytest.skip('创建符号链接需要开发者模式或权限')
    result=scan_installation(discover_installation(root),ScanOptions(strict=True))
    assert not result.files and not result.complete


def test_snapshot_resolution_uses_captured_metadata(game):
    root,base,hot=game;(base/'x.ab').write_bytes(b'abc')
    manifest(base,[entry('x.ab')])
    snap=scan_installation(discover_installation(root),ScanOptions(strict=True))
    (base/'x.ab').unlink()
    from arknights_unpacker.library import resolve_resources
    assert resolve_resources(snap).resources['x.ab'].status=='current'


def test_changed_manifest_rehashes_same_metadata(game):
    import os
    root,base,hot=game;p=base/'x.ab';p.write_bytes(b'aaa')
    manifest(base,[entry('x.ab')])
    old=scan_installation(discover_installation(root),ScanOptions(strict=True))
    stamp=p.stat().st_mtime_ns;p.write_bytes(b'bbb');os.utime(p,ns=(stamp,stamp))
    manifest(base,[entry('x.ab','b'*32)])
    new=scan_installation(discover_installation(root),ScanOptions(),baseline=old)
    assert next(f for f in new.files if f.path.endswith('x.ab')).hash_status=='verified'
    assert any(c.kind=='modified' and c.path.endswith('x.ab') for c in compare_files(old,new).changes)

def test_single_resource_folder_without_manifest(tmp_path):
    (tmp_path/'a.ab').write_bytes(b'UnityFS')
    installation=discover_installation(tmp_path)
    assert installation.base_root==tmp_path
    assert load_catalog(installation).diagnostics


def test_permission_failure_keeps_complete_baseline(game,tmp_path,monkeypatch):
    import arknights_unpacker.library.scan as scan_module
    root,base,hot=game;(base/'a.ab').write_bytes(b'aaa')
    installation=discover_installation(root)
    good=scan_installation(installation,ScanOptions(strict=True))
    def denied(*args):raise PermissionError('read denied')
    monkeypatch.setattr(scan_module,'_digest',denied)
    failed=scan_installation(installation,ScanOptions(strict=True))
    assert not failed.complete and failed.files[0].hash_status=='error'
    store=CatalogStore(tmp_path/'failure.sqlite');store.save_scan(good);store.save_scan(failed)
    assert store.latest_scan(good.profile_id).snapshot_id==good.snapshot_id
    assert not compare_files(good,failed).changes

def test_recent_nanosecond_boundary():
    from arknights_unpacker.contracts import ScanSnapshot,FileRecord
    end=1_700_000_000
    snapshot=ScanSnapshot('id','profile','root',end,end,[FileRecord('future',1,end*10**9+1),FileRecord('edge',1,(end-1800)*10**9)])
    assert [f.path for f in recent_files(snapshot,.5)]==['edge']

def test_second_fast_metadata_only_ab_never_reads_payload_and_strict_still_detects(game, monkeypatch):
    import os
    import arknights_unpacker.library.scan as scan_module
    root, base, hot = game
    payload = base / 'ordinary.ab'
    payload.write_bytes(b'aaa')
    installation = discover_installation(root)
    first = scan_installation(installation, ScanOptions())
    assert first.files[0].sha256 is None
    assert first.files[0].hash_status == 'metadata_only'
    original_digest = scan_module._digest
    def forbidden_digest(*args):
        raise AssertionError('unchanged ordinary AB payload must not be read in fast mode')
    monkeypatch.setattr(scan_module, '_digest', forbidden_digest)
    second = scan_installation(installation, ScanOptions(), baseline=first)
    assert second.complete and second.files[0].sha256 is None
    assert second.files[0].hash_status == 'metadata_unchanged'
    third = scan_installation(installation, ScanOptions(), baseline=second)
    assert third.complete and third.files[0].sha256 is None
    monkeypatch.setattr(scan_module, '_digest', original_digest)
    strict_before = scan_installation(installation, ScanOptions(strict=True), baseline=third)
    stamp = payload.stat().st_mtime_ns
    payload.write_bytes(b'bbb')
    os.utime(payload, ns=(stamp, stamp))
    strict_after = scan_installation(installation, ScanOptions(strict=True), baseline=strict_before)
    assert compare_files(strict_before, strict_after).changes[0].kind == 'modified'


def test_fast_new_file_is_hashed_after_metadata_only_baseline(game):
    import hashlib
    root, base, hot = game
    (base / 'existing.ab').write_bytes(b'old')
    installation = discover_installation(root)
    first = scan_installation(installation, ScanOptions())
    (base / 'new.ab').write_bytes(b'new')
    second = scan_installation(installation, ScanOptions(), baseline=first)
    added = next(record for record in second.files if record.path.endswith('/new.ab'))
    existing = next(record for record in second.files if record.path.endswith('/existing.ab'))
    assert added.sha256 == hashlib.sha256(b'new').hexdigest()
    assert added.hash_status == 'verified'
    assert existing.sha256 is None

def test_arknights_data_entry_discovers_same_installation_profile(game):
    root, base, hot = game
    from_root = discover_installation(root)
    from_data = discover_installation(root / 'Arknights_Data')
    assert from_data.root == from_root.root
    assert from_data.profile_id == from_root.profile_id
    assert from_data.base_root == base and from_data.hot_root == hot


def test_identical_data_id_remains_in_both_profiles(tmp_path):
    from arknights_unpacker.contracts import GameDataSnapshot
    store = CatalogStore(tmp_path / 'profiles.sqlite')
    data = GameDataSnapshot('same-content', 'v', 'r', {'x': 1}, created_at=1)
    store.save_data_snapshot('profile-A', data)
    store.save_data_snapshot('profile-B', data)
    assert len(store.list_data_snapshots('profile-A')) == 1
    assert len(store.list_data_snapshots('profile-B')) == 1
    assert store.get_data_snapshot('same-content', profile_id='profile-A') == data
    assert store.get_data_snapshot('same-content', profile_id='profile-B') == data
    assert store.get_data_snapshot('same-content', profile_id='profile-C') is None


def test_v1_migration_preserves_data_and_creates_readable_backup(tmp_path):
    import sqlite3
    from arknights_unpacker.contracts import GameDataSnapshot
    from arknights_unpacker.library import dumps_snapshot
    path = tmp_path / 'existing.sqlite'
    original = GameDataSnapshot('old-id', 'v', 'r', {'text': '原始资料'}, created_at=1)
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE data_snapshots(id TEXT PRIMARY KEY,profile_id TEXT NOT NULL,created REAL NOT NULL,complete INTEGER NOT NULL,version TEXT NOT NULL,resource_version TEXT NOT NULL,payload TEXT NOT NULL)')
        db.execute('INSERT INTO data_snapshots VALUES(?,?,?,?,?,?,?)', ('old-id', 'A', 1, 1, 'v', 'r', dumps_snapshot(original)))
        db.execute('PRAGMA user_version=1')
    store = CatalogStore(path)
    assert store.latest_data_snapshot('A') == original
    store.save_data_snapshot('B', original)
    assert store.latest_data_snapshot('A') == original
    backups = list(tmp_path.glob('existing.sqlite.v1-backup-*.sqlite'))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 1
        assert db.execute('SELECT profile_id FROM data_snapshots').fetchall() == [('A',)]
    with sqlite3.connect(path) as db:
        from arknights_unpacker.library.store import SCHEMA_VERSION
        assert db.execute('PRAGMA user_version').fetchone()[0] == SCHEMA_VERSION
    CatalogStore(path)
    assert len(list(tmp_path.glob('existing.sqlite.v1-backup-*.sqlite'))) == 1


def test_store_rejects_newer_schema_without_downgrade(tmp_path):
    import sqlite3
    path = tmp_path / 'future.sqlite'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE future_evidence(value TEXT)')
        db.execute("INSERT INTO future_evidence VALUES('preserve')")
        db.execute('PRAGMA user_version=99')
    with pytest.raises(ValueError, match='99'):
        CatalogStore(path)
    with sqlite3.connect(path) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 99
        assert db.execute('SELECT value FROM future_evidence').fetchone()[0] == 'preserve'

def test_partial_same_content_id_cannot_replace_complete_baseline(tmp_path):
    from dataclasses import replace
    from arknights_unpacker.contracts import GameDataSnapshot
    store = CatalogStore(tmp_path / 'observations.sqlite')
    good = GameDataSnapshot('same-content-id', 'v', 'r', {'a': 1}, created_at=1)
    partial = replace(good, complete=False, created_at=2, diagnostics=['manifest changed during read'])
    store.save_data_snapshot('profile', good)
    store.save_data_snapshot('profile', partial)
    assert store.latest_data_snapshot('profile') == good
    assert store.get_data_snapshot('same-content-id', profile_id='profile') == good
    history = store.list_data_snapshots('profile')
    assert len(history) == 2
    partial_id = next(row['snapshot_id'] for row in history if not row['complete'])
    saved_partial = store.get_data_snapshot(partial_id, profile_id='profile')
    assert saved_partial is not None and not saved_partial.complete
    assert saved_partial.diagnostics == partial.diagnostics
    assert saved_partial.sources['_content_snapshot_id'] == good.snapshot_id
    assert partial.snapshot_id == 'same-content-id'
    store.save_data_snapshot('other-profile', good)
    assert len(store.list_data_snapshots('other-profile')) == 1
    assert len(store.list_data_snapshots('profile')) == 2
    assert store.get_data_snapshot(partial_id, profile_id='other-profile') is None
