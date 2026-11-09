"""Prepare interactive replay assets from the active client installation."""
from argparse import ArgumentParser
import json
from pathlib import Path

from arknights_unpacker.contracts import CancelToken, null_progress
from arknights_unpacker.extraction.engine import validate_output_root
from arknights_unpacker.extraction.gameplay import load_level_data
from arknights_unpacker.extraction.level_replay import build_level_replay
from arknights_unpacker.extraction.level_tags import load_level_tags
from arknights_unpacker.extraction.level_variants import apply_level_tags
from arknights_unpacker.extraction.manifest import share_resource_manifest_reads
from arknights_unpacker.paths import atomic_json

from .level_actor_assets import extract_actors
from .level_scenes import level_scene_sources


def prepare_replay(game_root, level_id, resource_version, output, *, caption=None, tag_ids=None,
                   crisis_info=None, seed=None, emit=null_progress, cancel=None):
    cancel = cancel or CancelToken()
    output = validate_output_root(output, [Path(game_root).resolve()])
    source, level = load_level_data(game_root, level_id, resource_version, emit=emit, cancel=cancel)
    selection = None
    if tag_ids is not None or crisis_info is not None or level_id.startswith('gamedata/levels/obt/recalrune/'):
        options = load_level_tags(game_root, level_id, resource_version, crisis_info_path=crisis_info,
                                  emit=emit, cancel=cancel)
        if not options['tags']:
            raise ValueError('该关卡没有可应用的指标数据。')
        if tag_ids is None:
            tag_ids = [tag['id'] for tag in options['tags'] if tag['selected']]
        selection = apply_level_tags(level, options['tags'], tag_ids, graph=options.get('graph'))
        if selection['unapplied']:
            raise ValueError('；'.join(selection['unapplied']))
        level = selection['level']
    enemy_levels = {row['id']: row.get('level', 0) for row in level.get('enemyDbRefs') or ()}
    groups = set(level.get('enabledHiddenGroups') or ())
    enemy_ids = {
        action['key']
        for wave in level.get('waves') or ()
        for fragment in wave.get('fragments') or ()
        for action in fragment.get('actions') or ()
        if action.get('actionType') == 0 and action.get('key')
        and (action.get('hiddenGroup') is None or action['hiddenGroup'] in groups)
    }
    emit({'message': '正在读取游戏原始敌人骨骼和移动动画…'})
    actors = extract_actors(game_root, sorted(enemy_ids), resource_version, output,
                           enemy_levels=enemy_levels, cancel=cancel)
    replay = build_level_replay(level, actors, seed=seed, cancel=cancel)
    if not replay['complete']:
        detail = ' '.join(replay['diagnostics']) or '无法确定完整的波次时间轴。'
        raise ValueError(detail)
    replay.update(levelId=level_id, resourceVersion=source.resource_version,
                  caption=caption or level_id.rsplit('/', 1)[-1])
    if selection is not None:
        replay['selectedTags'] = selection['selected_ids']
    output.mkdir(parents=True, exist_ok=True)
    atomic_json(output / 'fixture.json', replay)
    return replay, level


@share_resource_manifest_reads()
def prepare_level_playback(game_root, level_id, resource_version, output, *, scene=None,
                           caption=None, tag_ids=None, crisis_info=None, seed=None, emit=null_progress, cancel=None):
    from .level_replay_tiles import configure_scene_tiles
    from .level_scene_assets import extract_scene

    cancel = cancel or CancelToken()
    output = validate_output_root(output, [Path(game_root).resolve()])
    sources = tuple(level_scene_sources(level_id))
    if not sources:
        raise ValueError('无效的关卡数据路径。')
    scene_asset = sources[0][0]
    if scene is not None and (scene.get('kind') != 'scene' or scene.get('asset') != scene_asset):
        raise ValueError('该关卡使用地图预制体或组装规则，当前播放器尚未支持。')
    if scene is not None and not scene['available']:
        raise ValueError('原始地图场景资源未安装，请在游戏客户端下载后重新扫描。')
    replay, level = prepare_replay(game_root, level_id, resource_version, output, caption=caption,
                                   tag_ids=tag_ids, crisis_info=crisis_info, seed=seed, emit=emit, cancel=cancel)
    emit({'message': '正在提取游戏原场景、材质和光照…'})
    info = extract_scene(game_root, scene_asset, resource_version, output, cancel=cancel)
    if info['layoutDiagnostics']:
        raise ValueError(' '.join(info['layoutDiagnostics']))
    layout_path = output / 'scene-layout.json'
    layout = json.loads(layout_path.read_text(encoding='utf-8'))
    configure_scene_tiles(game_root, resource_version, level, output, layout, cancel=cancel)
    cancel.check()
    atomic_json(layout_path, layout)
    return {'level_id': level_id, 'resource_version': resource_version, 'duration': replay['duration'],
            'spawns': len(replay['events']), 'diagnostics': replay['diagnostics'], 'seed': replay['seed']}


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('game_root', type=Path)
    parser.add_argument('level_id')
    parser.add_argument('resource_version')
    parser.add_argument('output', type=Path)
    parser.add_argument('--caption')
    parser.add_argument('--tag', action='append', help='Apply an indicator ID; repeat to select a connected set.')
    parser.add_argument('--crisis-info', type=Path, help='Season JSON for the selected Crisis Contract stage.')
    parser.add_argument('--seed', type=int, help='Reuse a recorded replay seed.')
    parser.add_argument('--fixture-only', action='store_true', help='Export the time axis and actors only.')
    args = parser.parse_args()
    options = dict(caption=args.caption, tag_ids=args.tag, crisis_info=args.crisis_info, seed=args.seed)
    if args.fixture_only:
        replay, _ = prepare_replay(args.game_root, args.level_id, args.resource_version, args.output, **options)
        print(f"{len(replay['events'])} spawns, {replay['duration']:.1f} battle seconds, seed {replay['seed']}")
    else:
        info = prepare_level_playback(args.game_root, args.level_id, args.resource_version, args.output, **options)
        print(f"{info['spawns']} spawns, {info['duration']:.1f} battle seconds, seed {info['seed']}")


if __name__ == '__main__':
    main()
