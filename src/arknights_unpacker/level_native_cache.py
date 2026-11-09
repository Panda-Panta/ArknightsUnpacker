"""Keep completed native replay assets local to one game resource revision."""
from hashlib import sha256
import json
from pathlib import Path
import re
import shutil
from uuid import uuid4

from .level_preview_server import _SEGMENT, _regular_file
from .paths import atomic_json, validate_output


_CACHE_FORMAT = 1
_GENERATION = re.compile(r'assets-[a-f0-9]{32}')
_REQUIRED = {'fixture.json', 'scene-layout.json', 'native-actors/index.json'}


def _cached_result(slot, identity):
    try:
        marker = _regular_file(slot.parent, [slot.name, 'ready.json'])
        if marker is None:
            return None
        record = json.loads(marker.read_text(encoding='utf-8'))
        generation, files, result = record['generation'], record['files'], record['result']
        if (not _GENERATION.fullmatch(generation) or not _REQUIRED <= files.keys()
                or result['level_id'] != identity['level_id']
                or result['resource_version'] != identity['resource_version']):
            return None
        for name, size in files.items():
            parts = name.split('/')
            if not all(_SEGMENT.fullmatch(part) and not part.endswith(('.', ' ')) for part in parts):
                return None
            path = _regular_file(slot, [generation, *parts])
            if path is None or path.stat().st_size != size:
                return None
        return {**result, 'native_assets': str(slot / generation), 'native_cache_hit': True}
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return None


def _cache_slot(data_root, options):
    game_root = Path(options['game_root']).resolve()
    root = Path(data_root) / 'native-level-replays'
    if validate_output(root, game_root) != root:
        raise ValueError('原生回放缓存路径越界。')
    archive = options.get('crisis_info')
    # The display caption can arrive asynchronously after opening the catalog.
    identity = {**options, 'game_root': game_root.as_posix().casefold(), 'cache_format': _CACHE_FORMAT,
                'crisis_info': sha256(Path(archive).read_bytes()).hexdigest() if archive else None}
    identity.pop('caption', None)
    key = sha256(json.dumps(identity, sort_keys=True).encode('utf-8')).hexdigest()
    slot = root / key
    if slot.resolve() != slot:
        raise ValueError('原生回放缓存路径越界。')
    return slot, identity


def cached_native_replay(data_root, options):
    return _cached_result(*_cache_slot(data_root, options))


def prepare_cached_native_replay(runtime, options, *, emit, cancel):
    cancel.check()
    options = options.copy()
    output = Path(options.pop('output')).resolve()
    slot, identity = _cache_slot(output.parent.parent, options)
    if (ready := _cached_result(slot, identity)) is not None:
        cancel.check()
        emit({'message': '正在使用已准备的原版关卡和角色动画…'})
        return ready

    from .extraction.level_replay_assets import prepare_level_playback
    from .level_native_atlases import prepare_native_atlases

    generation = f'assets-{uuid4().hex}'
    assets = slot / generation
    assets.mkdir(parents=True, exist_ok=False)
    published = False
    try:
        result = prepare_level_playback(**options, output=assets, emit=emit, cancel=cancel)
        prepare_native_atlases(assets, runtime, emit=emit, cancel=cancel)
        cancel.check()
        files = {path.relative_to(assets).as_posix(): path.stat().st_size
                 for path in assets.rglob('*') if path.is_file()}
        if not _REQUIRED <= files.keys():
            raise ValueError('原生回放缓存缺少关卡或角色索引。')
        cancel.check()
        if (ready := _cached_result(slot, identity)) is not None:
            return ready
        # Readers only open generations referenced by a complete receipt.
        # Keep the previous generation intact for any viewer still using it.
        atomic_json(slot / 'ready.json', {'generation': generation, 'files': files, 'result': result})
        published = True
        return {**result, 'native_assets': str(assets), 'native_cache_hit': False}
    finally:
        if not published and assets.resolve() == assets:
            shutil.rmtree(assets, ignore_errors=True)
