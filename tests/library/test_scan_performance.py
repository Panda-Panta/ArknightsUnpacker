"""Large sibling inventories should reuse enumeration and root path metadata."""
import json
import os
from pathlib import Path

import pytest

from arknights_unpacker.contracts import ScanOptions
from arknights_unpacker.library import discover_installation, load_catalog, resolve_resources, scan_installation


def test_scan_uses_directory_metadata_without_restatting_each_entry(tmp_path, monkeypatch):
    root = tmp_path / 'game'
    base = root / 'Arknights_Data/StreamingAssets/AB/Windows'
    folder = base / 'avg/images'
    folder.mkdir(parents=True)
    for index in range(40):
        (folder / f'{index}.ab').write_bytes(b'image')
    installation = discover_installation(root)
    original = Path.lstat
    calls = []
    def lstat(path, *args, **kwargs):
        calls.append(path)
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'lstat', lstat)
    result = scan_installation(installation, ScanOptions())
    assert result.complete
    assert len(result.files) == 40
    assert {item.layer for item in result.files} == {'base'}
    assert {item.category for item in result.files} == {'剧情插图'}
    assert not [path for path in calls if path.suffix == '.ab']


def test_snapshot_resolution_derives_layer_prefix_once_not_per_resource(tmp_path, monkeypatch):
    root = tmp_path / 'game'
    base = root / 'Arknights_Data/StreamingAssets/AB/Windows'
    folder = base / 'avg/images'
    folder.mkdir(parents=True)
    names = [f'avg/images/{index}.ab' for index in range(40)]
    for name in names:
        (base / name).write_bytes(b'image')
    (base / 'hot_update_list.json').write_text(json.dumps({'abInfos': [
        {'name': name, 'md5': 'a' * 32, 'abSize': 5} for name in names
    ]}), encoding='utf8')
    snapshot = scan_installation(discover_installation(root), ScanOptions())
    original = Path.relative_to
    calls = []
    def relative_to(path, *args, **kwargs):
        calls.append(path)
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'relative_to', relative_to)
    catalog = resolve_resources(snapshot)
    assert set(catalog.resources) == set(names)
    assert all(item.status == 'current' for item in catalog.resources.values())
    assert len(calls) <= 2


def test_live_catalog_reuses_shared_parent_metadata_for_sibling_resources(tmp_path, monkeypatch):
    root=tmp_path/'game'
    base=root/'Arknights_Data/StreamingAssets/AB/Windows'
    folder=base/'avg/images'
    folder.mkdir(parents=True)
    names=[f'avg/images/{index}.ab' for index in range(40)]
    for name in names:(base/name).write_bytes(b'image')
    (base/'hot_update_list.json').write_text(json.dumps({'abInfos':[
        {'name':name,'md5':'a'*32,'abSize':5} for name in names]}),encoding='utf8')
    installation=discover_installation(root)
    original=Path.lstat
    calls=[]
    def lstat(path,*args,**kwargs):
        calls.append(path)
        return original(path,*args,**kwargs)
    monkeypatch.setattr(Path,'lstat',lstat)
    catalog=load_catalog(installation)
    assert len(catalog.resources)==40
    assert all(item.status=='current' for item in catalog.resources.values())
    assert calls.count(folder)==1
    assert sum(path.suffix=='.ab' for path in calls)==40


def test_live_resolution_keeps_missing_size_stale_and_unsafe_path_rules(tmp_path):
    root = tmp_path / 'game'
    base = root / 'Arknights_Data/StreamingAssets/AB/Windows'
    hot = root / 'Arknights_Data/PersistentData/Bundles'
    base.mkdir(parents=True)
    hot.mkdir(parents=True)
    base_entries = []
    active_entries = []
    for name in ['current.ab', 'stale.ab', 'incomplete.ab']:
        (base / name).write_bytes(b'abc')
        entry = {'name': name, 'md5': 'a' * 32, 'abSize': 3}
        base_entries.append(entry)
        active_entries.append({**entry, **({'md5': 'b' * 32} if name == 'stale.ab' else {})})
    (hot / 'incomplete.ab').write_bytes(b'a')
    (base / 'incomplete.ab').unlink()
    active_entries += [{'name': 'absent.ab', 'md5': 'c' * 32, 'abSize': 3},
                       {'name': '../outside.ab', 'md5': 'd' * 32, 'abSize': 3}]
    for folder, entries in [(base, base_entries), (hot, active_entries)]:
        (folder / 'hot_update_list.json').write_text(json.dumps({'abInfos': entries}), encoding='utf8')
    catalog = load_catalog(discover_installation(root))
    assert {name: item.status for name, item in catalog.resources.items()} == {
        'current.ab': 'current', 'stale.ab': 'stale', 'incomplete.ab': 'incomplete', 'absent.ab': 'missing'}
    assert any('不安全' in message for message in catalog.diagnostics)


@pytest.mark.parametrize('directory_link',[False,True])
def test_live_catalog_rejects_linked_file_and_cached_parent(tmp_path,directory_link):
    root=tmp_path/'game'
    base=root/'Arknights_Data/StreamingAssets/AB/Windows'
    base.mkdir(parents=True)
    outside=tmp_path/'outside'
    outside.mkdir()
    (outside/'one.ab').write_bytes(b'private')
    (outside/'two.ab').write_bytes(b'private')
    if directory_link:
        link=base/'linked'
        target=outside
        names=['linked/one.ab','linked/two.ab']
    else:
        link=base/'linked.ab'
        target=outside/'one.ab'
        names=['linked.ab']
    try:os.symlink(target,link,target_is_directory=directory_link)
    except OSError:pytest.skip('创建符号链接需要开发者模式或权限')
    (base/'hot_update_list.json').write_text(json.dumps({'abInfos':[
        {'name':name,'md5':'a'*32,'abSize':7} for name in names]}),encoding='utf8')
    catalog=load_catalog(discover_installation(root))
    assert not catalog.resources
    assert len([message for message in catalog.diagnostics if '不跟随链接' in message])==len(names)
