from pathlib import Path

import pytest

from arknights_unpacker.contracts import (
    FileChange,
    FileChangeSet,
    FileRecord,
    GameInstallation,
    ResolvedResource,
    ResourceCatalog,
    ScanSnapshot,
)
from arknights_unpacker.ui.workbench.resources import WorkbenchResources


def _snapshot(root, rows, snapshot_id='scan'):
    for row in rows:
        path = root / row.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    return ScanSnapshot(snapshot_id, 'profile', str(root), 1, 2, rows)


def _names(result):
    return [row['name'] for row in result['rows']]


def test_directory_rows_navigation_pagination_and_recursive_search(tmp_path):
    index = WorkbenchResources()
    snapshot = _snapshot(tmp_path, [
        FileRecord('avg/direct.ab', 32, 1),
        FileRecord('avg/backgrounds/city.AB', 8, 1, category='剧情背景'),
        FileRecord('avg/backgrounds/interior/gray.ab', 4, 1, category='剧情背景'),
        FileRecord('avg/stories/story.bin', 2, 1),
        FileRecord('outside/blue.ab', 10, 1, category='剧情背景'),
    ])
    index.refresh(tmp_path, snapshot, None, None)

    root = index.query({})
    assert _names(root) == ['avg', 'outside']
    assert root['directoryCount'] == 2 and root['fileCount'] == 0
    assert all(row['kind'] == 'directory' and not row['extractable'] for row in root['rows'])

    settings = {'folder': 'avg', 'sort': 'size', 'pageSize': 2}
    first = index.query(settings)
    assert _names(first) == ['backgrounds', 'stories']
    assert first['total'] == 3 and first['fileCount'] == 1
    assert _names(index.query({**settings, 'page': 2})) == ['direct.ab']
    assert _names(index.query({'folder': 'avg/backgrounds'})) == ['interior', 'city.AB']

    recursive = index.query({'folder': 'avg', 'recursive': True, 'abOnly': True, 'query': '背景'})
    assert _names(recursive) == ['city.AB', 'gray.ab']
    # Selecting an explicit category searches the whole active source, while the
    # saved folder remains available when the category filter is cleared.
    filtered = index.query({'folder': 'avg/stories', 'category': '剧情背景'})
    assert filtered['folder'] == 'avg/stories'
    assert _names(filtered) == ['blue.ab', 'city.AB', 'gray.ab']


def test_effective_resources_join_right_observation_and_exclude_stale_candidates(tmp_path):
    index = WorkbenchResources()
    records = [
        FileRecord('base/images/city.ab', 88, 10**9, layer='base',
                   created_ns=5 * 10**8, first_seen_at=0.8),
        FileRecord('hot/images/city.ab', 28, 2 * 10**9, layer='hot',
                   created_ns=13 * 10**8, first_seen_at=1.7),
    ]
    snapshot = _snapshot(tmp_path, records)
    changes = FileChangeSet('base-scan', snapshot.snapshot_id, [FileChange('modified', records[1].path)])
    catalog = ResourceCatalog(GameInstallation(tmp_path, 'profile'), {
        'logical/city.ab': ResolvedResource('logical/city.ab', str(tmp_path / records[1].path),
                                            'hot', 'current', '剧情插图', 28),
        'logical/absent.ab': ResolvedResource('logical/absent.ab', None, '', 'missing', '剧情插图'),
        'logical/older.ab': ResolvedResource('logical/older.ab', None, '', 'stale', '剧情插图'),
        'logical/outside.ab': ResolvedResource('logical/outside.ab', str(tmp_path.parent / 'other.ab'),
                                              'base', 'current', '剧情插图'),
    })
    index.refresh(tmp_path, snapshot, changes, catalog)

    raw = index.query({'folder': 'hot/images'})['rows'][0]
    assert raw['source'] == '热更新' and raw['status'] == '已修改'
    assert _names(index.query({'layer': 'effective'})) == ['hot', 'logical']
    effective = index.query({'layer': 'effective', 'folder': 'hot/images'})['rows'][0]
    assert (effective['size'], effective['modified'], effective['created'], effective['observed']) == (28, 2.0, 1.3, 1.7)
    assert index.paths([effective['id']]) == [str(tmp_path / records[1].path)]
    assert index.directory_paths('hot', 'effective') == [str(tmp_path / records[1].path)]

    missing = index.query({'layer': 'effective', 'folder': 'logical'})['rows']
    assert [row['status'] for row in missing[:2]] == ['未安装', '仅有旧版']
    assert all(row['size'] is None and not row['previewable'] for row in missing)
    for row in missing:
        with pytest.raises(ValueError):
            index.paths([row['id']])
    with pytest.raises(ValueError):
        index.directory_paths('../', 'effective')


@pytest.mark.parametrize('sort', ['modified', 'created', 'observed', 'size'])
def test_sort_uses_numeric_precision_and_keeps_unknown_last(tmp_path, sort):
    base = 1_700_000_000 * 10**9
    index = WorkbenchResources()
    snapshot = _snapshot(tmp_path, [
        FileRecord('first.ab', 900_000, base + 1, created_ns=base + 2, first_seen_at=1.13),
        FileRecord('second.ab', 2_000_000, base + 2, created_ns=base + 3, first_seen_at=1.8),
        FileRecord('unknown.ab', None, 0),
    ])
    index.refresh(tmp_path, snapshot, None, None)
    assert _names(index.query({'sort': sort})) == ['first.ab', 'second.ab', 'unknown.ab']
    assert _names(index.query({'sort': sort, 'descending': True})) == ['second.ab', 'first.ab', 'unknown.ab']


def test_selection_invalidates_on_rebuild_and_rejects_unavailable_files(tmp_path):
    root = tmp_path / 'game'
    index = WorkbenchResources()
    records = [FileRecord('media/example.png', 5, 1), FileRecord('application.exe', 55, 1)]
    snapshot = _snapshot(root, records)
    index.refresh(root, snapshot, None, None)

    row = index.query({'folder': 'media'})['rows'][0]
    identity = row['id']
    index.refresh(root, snapshot, None, None)
    assert index.query({'folder': 'media'})['rows'][0]['id'] == identity
    assert list(map(Path, index.directory_paths('', 'raw'))) == [root / records[0].path]
    unsupported = index.query({'query': '.exe'})['rows'][0]
    assert not unsupported['extractable']
    with pytest.raises(ValueError):
        index.paths([unsupported['id']], extraction=True)

    (root / records[0].path).unlink()
    with pytest.raises(ValueError):
        index.paths([identity])

    index.refresh(root, _snapshot(root, records, 'rescan'), None, None)
    new = index.query({'folder': 'media'})['rows'][0]['id']
    assert new != identity
    with pytest.raises(ValueError):
        index.paths([identity])

    index.refresh(tmp_path / 'other', snapshot, None, None)
    assert index.query({})['total'] == 0
    with pytest.raises(ValueError):
        index.paths([new])
