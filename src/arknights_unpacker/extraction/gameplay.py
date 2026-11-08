"""Discover gameplay from the captured resource index and decode on demand."""
from pathlib import Path
import re
import struct

from ..contracts import ResourceCatalog, ScanSnapshot, null_progress
from ..library.discover import safe_path
from .decoder import decode_table_bytes
from .manifest import read_resource_manifest
from .tables import _table_name, load_local_tables


_MODE_TABLES = {
    'autochess': ('卫戍协议', ('activity_table',)),
    'roguelike': ('集成战略', ('roguelike_topic_table',)),
    'sandbox': ('生息演算', ('sandbox_table', 'sandbox_perm_table')),
    'climb_tower': ('保全派驻', ('climb_tower_table',)),
}
_MODE_BY_TABLE = {table: mode for mode, (_, tables) in _MODE_TABLES.items() for table in tables}
_AUTOCHESS_LEVEL = re.compile(r'gamedata/levels/activities/act[0-9]+v?autochess/(?:[a-z0-9_]+/)*level_[a-z0-9_]+')
_AUTOCHESS_GUIDE = re.compile(r'gamedata/story/activities/(?:act[0-9]+v?autochess|autochess)/')


def discover_game_content(snapshot: ScanSnapshot, catalog: ResourceCatalog, cancel, *, previous_levels=None):
    """Read the active index once for the gameplay and level directories."""
    from .level_catalog import build_level_catalog
    from .level_map_image import find_level_map_images

    active = catalog.manifest
    result = {'root': snapshot.root, 'resource_version': str(active.get('versionId', 'unknown')),
              'modes': [], 'diagnostics': []}
    try:
        cancel.check()
        manifest_name = active.get('manifestName')
        if not manifest_name:
            raise ValueError('资源清单没有可用于识别玩法的索引。')
        if 'unstable: 资源清单在扫描期间变化' in snapshot.errors:
            raise OSError('资源清单在扫描期间变化，请重新扫描。')
        installation = catalog.installation
        records = {item.path.casefold(): item for item in snapshot.files if not item.error}
        for layer in ('hot', 'base'):
            folder = installation.source_roots.get(layer)
            if folder is None:
                continue
            path = safe_path(folder, manifest_name)
            record = records.get(path.relative_to(installation.root).as_posix().casefold())
            if record is not None:
                break
        else:
            raise FileNotFoundError('活动资源索引未安装。')
        observed = record.size, record.mtime_ns
        info = path.stat()
        if (info.st_size, info.st_mtime_ns) != observed:
            raise OSError('资源索引在扫描后发生变化，请重新扫描。')
        index = read_resource_manifest(path)
        info = path.stat()
        if (info.st_size, info.st_mtime_ns) != observed:
            raise OSError('资源索引在识别玩法期间发生变化，请重新扫描。')
        gameplay = _identify(result, index, catalog, cancel)
        levels = build_level_catalog(snapshot.root, result['resource_version'], index, catalog,
                                     previous_levels, cancel)
        images = find_level_map_images(index, catalog.resources, (row['id'] for row in levels['levels']), cancel)
        for row in levels['levels']:
            if row['id'] in images:
                row['map_image'] = images[row['id']]
        return gameplay, levels
    except (OSError, ValueError, TypeError, KeyError, IndexError, struct.error) as error:
        result['diagnostics'].append(f'玩法识别暂不可用：{error}')
        levels = {'root': snapshot.root, 'resource_version': result['resource_version'],
                  'levels': [], 'diagnostics': [f'关卡索引暂不可用：{error}']}
        return result, levels


def _identify(result, index, catalog, cancel):
    tables = {mode: {} for mode in _MODE_TABLES}
    levels = set()
    has_autochess = False
    active_bundles = catalog.resources
    for count, entry in enumerate(index['assets']):
        if count % 2048 == 0:
            cancel.check()
        asset = entry.get('assetName') or entry.get('path') or entry.get('name') or ''
        bundle = active_bundles.get(entry['bundle'])
        if bundle is None:
            continue
        if asset.startswith('gamedata/excel/'):
            name = _table_name(asset, _MODE_BY_TABLE)
            if name:
                tables[_MODE_BY_TABLE[name]][asset] = bool(bundle.path)
        elif _AUTOCHESS_LEVEL.fullmatch(asset):
            has_autochess = True
            if bundle.path:
                levels.add(asset)
        elif _AUTOCHESS_GUIDE.match(asset):
            has_autochess = True
    cancel.check()
    for mode, (name, _) in _MODE_TABLES.items():
        sources = tables[mode]
        autochess = mode == 'autochess'
        recognized = has_autochess if autochess else bool(sources)
        if not recognized:
            continue
        installed = sorted(asset for asset, available in sources.items() if available)
        detail_resource = installed[0] if autochess and len(installed) == 1 else None
        if autochess and len(installed) > 1:
            result['diagnostics'].append('发现多个卫戍协议活动表，无法确定唯一详情来源。')
        result['modes'].append({
            'id': mode, 'name': name, 'supported': autochess,
            'available': bool(detail_resource) if autochess else bool(installed),
            'resources': sorted(sources), 'detail_resource': detail_resource,
            'level_paths': sorted(levels) if autochess else [],
        })
    return result


def _load_source(root, logical_path, name, decode, resource_version, emit, cancel):
    result = load_local_tables(
        Path(root), None, emit, cancel, names={name, 'data_version'},
        decoders={name: decode}, logical_names={name: logical_path},
        expected_resource_version=resource_version,
    )
    table = result.tables.get(name)
    if table is None:
        message = '；'.join(result.diagnostics)
        raise ValueError(message or f'活动索引没有已扫描的资源：{logical_path}。请重新扫描。')
    return result, table.data


def load_autochess(root, logical_path, resource_version, *, emit=null_progress, cancel=None):
    from .autochess import decode_autochess

    def decode(raw, _name):
        seasons = decode_autochess(raw, cancel=cancel)
        return {'seasons': seasons}, {'format': 'autochess_flatbuffers'}

    result, data = _load_source(root, logical_path, 'activity_table', decode, resource_version, emit, cancel)
    return {'game_version': result.version, 'resource_version': result.resource_version,
            'seasons': data['seasons'], 'diagnostics': result.diagnostics}


def load_gameplay_level(root, logical_path, resource_version, *, emit=null_progress, cancel=None):
    if not _AUTOCHESS_LEVEL.fullmatch(logical_path):
        raise ValueError('关卡路径不属于卫戍协议。')
    result, data = load_level_data(root, logical_path, resource_version, emit=emit, cancel=cancel)
    name = logical_path.rsplit('/', 1)[-1]
    grid = (data.get('mapData') or {}).get('map') or {}
    enemy_refs = data.get('enemyDbRefs') or []
    return {'level_id': data.get('levelId') or name,
            'map_size': [grid.get('rowSize'), grid.get('columnSize')],
            'route_count': len(data.get('routes') or []),
            'wave_count': len(data.get('waves') or []),
            'enemy_ids': list(dict.fromkeys(row['id'] for row in enemy_refs if row.get('id'))),
            'diagnostics': result.diagnostics}


def load_level_data(root, logical_path, resource_version, *, emit=null_progress, cancel=None):
    from .level_catalog import is_level_path

    if not is_level_path(logical_path):
        raise ValueError('无效的关卡数据路径。')
    name = logical_path.rsplit('/', 1)[-1]

    def decode(raw, _name):
        return decode_table_bytes(raw, 'prts___levels')

    return _load_source(root, logical_path, name, decode, resource_version, emit, cancel)
