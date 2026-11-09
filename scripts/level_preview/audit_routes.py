"""Count route features and blockers across the active client level data."""
from argparse import ArgumentParser
from collections import Counter, defaultdict
from contextlib import nullcontext
import gzip
import hashlib
import json
from pathlib import Path
import re
import struct
from uuid import uuid4

from arknights_unpacker.contracts import CancelToken
from arknights_unpacker.extraction.decoder import decode_table_bytes
from arknights_unpacker.extraction.level_catalog import _collect_levels
from arknights_unpacker.extraction.level_routes import build_level_routes
from arknights_unpacker.extraction.level_scenes import find_level_scenes
from arknights_unpacker.extraction.manifest import read_resource_manifest
from arknights_unpacker.extraction.unity import load_bundle, raw_text
from arknights_unpacker.library.discover import discover_installation, safe_path
from arknights_unpacker.library.resolver import load_catalog
from arknights_unpacker.paths import atomic_json, validate_output


_LEVEL_FIELDS = ('mapData', 'routes', 'extraRoutes', 'waves', 'branches', 'enabledHiddenGroups', 'options')
_DECODE_ERRORS = (OSError, ValueError, TypeError, KeyError, AttributeError, IndexError, RuntimeError, struct.error)
_AUDIT_SCOPE = (
    'Base LevelData default spawn actions, including the candidate routes of random groups. '
    'Hidden groups use the base enabledHiddenGroups. Branches and mode-dependent waves are counted '
    'separately. This audits route planning and exact scene binding only, without loading render assets, '
    'checking actor prefabs, applying tags, or simulating combat.'
)


def _indexed_levels(root):
    installation = discover_installation(root)
    catalog = load_catalog(installation)
    version = catalog.manifest['versionId']
    manifest_name = catalog.manifest['manifestName']
    candidates = [safe_path(installation.source_roots[layer], manifest_name)
                  for layer in ('hot', 'base') if layer in installation.source_roots]
    index_path = next((path for path in candidates if path.is_file()), None)
    if index_path is None:
        raise FileNotFoundError(f'活动资源索引未安装：{manifest_name}')
    index = read_resource_manifest(index_path)
    cancel = CancelToken()
    levels = _collect_levels(index['assets'], catalog.resources, cancel)
    scenes = find_level_scenes(index, catalog.resources, levels, cancel)
    paths = defaultdict(set)
    for row in index['assets']:
        if row['assetName'] in levels:
            paths[row['assetName']].add(row['path'])
    groups = defaultdict(list)
    for level_id, bundle in levels.items():
        resource = catalog.resources.get(bundle)
        if resource and resource.path:
            groups[bundle].append(level_id)
    header = {'resource_version': version, 'indexed_levels': len(levels),
              'installed_levels': sum(map(len, groups.values())), 'installed_bundles': len(groups)}
    yield header
    for bundle, ids in groups.items():
        resource = catalog.resources[bundle]
        try:
            path = Path(resource.path)
            before = path.stat()
            payload = path.read_bytes()
            after = path.stat()
            if len(payload) != resource.size or (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise OSError('资源包大小已变更或读取期间变化。')
            digest = resource.expected_hash
            if re.fullmatch('[0-9a-fA-F]{32}', digest) and hashlib.md5(payload).hexdigest() != digest.lower():
                raise OSError('资源包内容摘要与活动清单不匹配。')
            environment = load_bundle(path, data=payload)
            container = environment.container
        except _DECODE_ERRORS as error:
            for level_id in ids:
                yield {'id': level_id, 'scene': scenes.get(level_id), 'error': f'{type(error).__name__}: {error}'}
            continue
        for level_id in ids:
            record = {'id': level_id, 'scene': scenes.get(level_id)}
            try:
                if len(paths[level_id]) != 1:
                    raise ValueError('关卡缺少唯一的资源包内路径。')
                asset = container[next(iter(paths[level_id]))].deref()
                if asset.type.name != 'TextAsset':
                    raise ValueError('索引资源不是关卡 TextAsset。')
                level, _ = decode_table_bytes(raw_text(asset.read()), 'prts___levels')
                record['level'] = {key: level[key] for key in _LEVEL_FIELDS if key in level}
            except _DECODE_ERRORS as error:
                record['error'] = f'{type(error).__name__}: {error}'
            yield record


def _route_refs(level):
    groups = set(level.get('enabledHiddenGroups') or ())
    refs = set()
    random = False
    for wave in level.get('waves') or ():
        for fragment in wave.get('fragments') or ():
            for action in fragment.get('actions') or ():
                group = action.get('hiddenGroup')
                if (action.get('actionType', 0) != 0 or action.get('count', 1) <= 0
                        or (group is not None and group not in groups)):
                    continue
                refs.add((bool(action.get('useExtraRoute')), action.get('routeIndex', 0)))
                random |= bool(action.get('randomSpawnGroupKey') or action.get('randomSpawnGroupPackKey'))
    return refs, random


def _checkpoint_feature(checkpoint):
    offset = checkpoint.get('reachOffset') or {}
    flags = []
    if offset.get('x') or offset.get('y'):
        flags.append('reachOffset')
    if checkpoint.get('randomizeReachOffset'):
        flags.append('randomizeReachOffset')
    if checkpoint.get('reachDistance'):
        flags.append('reachDistance')
    kind = f"type={checkpoint.get('type')}"
    return ' + '.join((kind, *flags))


def _route_plan(level, refs):
    selected = {'routes': [], 'extraRoutes': []}
    errors = Counter()
    for extra, route_index in sorted(refs, key=lambda ref: (ref[0], str(ref[1]))):
        field = 'extraRoutes' if extra else 'routes'
        source = level.get(field) or ()
        if not isinstance(route_index, int) or not 0 <= route_index < len(source):
            errors['关卡未定义这条路线。'] += 1
            continue
        selected[field].append(source[route_index])
    try:
        _, unavailable = build_level_routes({**level, **selected})
    except _DECODE_ERRORS as error:
        errors[str(error)] += sum(map(len, selected.values()))
    else:
        errors.update(unavailable.values())
    features = Counter(_checkpoint_feature(checkpoint) for routes in selected.values() for route in routes
                       for checkpoint in route.get('checkpoints') or ())
    return features, errors


def _sorted_features(counts, stages):
    return {name: {'occurrences': count, 'stages': len(stages[name]), 'stage_ids': sorted(stages[name])}
            for name, count in sorted(counts.items(), key=lambda item: (-len(stages[item[0]]), item[0]))}


def _audit(records, snapshot=None):
    header = next(records)
    print(header, flush=True)
    if snapshot is not None:
        snapshot.write(json.dumps(header) + '\n')
    features, blockers = Counter(), Counter()
    feature_stages, blocker_stages = defaultdict(set), defaultdict(set)
    results = []
    for number, record in enumerate(records, 1):
        if snapshot is not None:
            snapshot.write(json.dumps(record) + '\n')
        row = {key: value for key, value in record.items() if key != 'level'}
        results.append(row)
        if 'error' not in record:
            level = record['level']
            refs, random = _route_refs(level)
            row.update(referenced_routes=len(refs), random_groups=random, runtime_branches=bool(level.get('branches')),
                       mode_dependent_waves=any(wave.get('advancedWaveTag') for wave in level.get('waves') or ()))
            if refs:
                seen, errors = _route_plan(level, refs)
                features.update(seen)
                blockers.update(errors)
                for feature in seen:
                    feature_stages[feature].add(record['id'])
                for reason in errors:
                    blocker_stages[reason].add(record['id'])
                row.update(route_ready=not errors, route_blockers=dict(errors))
        if number % 250 == 0:
            print(f'{number}/{header["installed_levels"]} levels audited', flush=True)
    decoded = [row for row in results if 'error' not in row]
    ready = [row for row in decoded if row.get('route_ready')]
    summary = {**header, 'decoded_levels': len(decoded), 'decode_errors': len(results) - len(decoded),
               'levels_with_default_spawns': sum(bool(row['referenced_routes']) for row in decoded),
               'route_ready_levels': len(ready), 'route_blocked_levels': sum(row.get('route_ready') is False for row in decoded),
               'route_ready_with_bound_scene': sum((row.get('scene') or {}).get('kind') == 'scene'
                                                   and row['scene']['available'] for row in ready),
               'levels_with_random_groups': sum(row['random_groups'] for row in decoded),
               'levels_with_runtime_branches': sum(row['runtime_branches'] for row in decoded),
               'levels_with_mode_dependent_waves': sum(row['mode_dependent_waves'] for row in decoded)}
    return {'scope': _AUDIT_SCOPE, 'summary': summary, 'checkpoint_features': _sorted_features(features, feature_stages),
            'route_blockers': _sorted_features(blockers, blocker_stages), 'levels': sorted(results, key=lambda row: row['id'])}


def main():
    parser = ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--game-root', type=Path)
    source.add_argument('--from-snapshot', type=Path, help='Reuse an explicitly selected previous LevelData snapshot.')
    parser.add_argument('--save-snapshot', type=Path, help='Save decoded route data to gzip JSON lines for local re-audits.')
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    report_path = args.report.resolve()
    if args.from_snapshot:
        if args.save_snapshot or args.from_snapshot.resolve() == report_path:
            parser.error('A cached input requires a separate report and no snapshot output.')
        with gzip.open(args.from_snapshot, 'rt', encoding='utf-8') as stream:
            report = _audit(map(json.loads, stream))
    else:
        report_path = validate_output(args.report, args.game_root)
        snapshot_path = validate_output(args.save_snapshot, args.game_root) if args.save_snapshot else None
        if snapshot_path == report_path:
            parser.error('Report and snapshot must be separate files.')
        temporary = None
        if snapshot_path:
            snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = snapshot_path.with_name(snapshot_path.name + '.' + uuid4().hex + '.tmp')
        try:
            with gzip.open(temporary, 'wt', encoding='utf-8', compresslevel=1) if temporary else nullcontext(None) as stream:
                report = _audit(_indexed_levels(args.game_root), stream)
            if temporary:
                temporary.replace(snapshot_path)
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(report_path, report)
    print(report['summary'], flush=True)


if __name__ == '__main__':
    main()
