"""Keep completed native replay assets local to one game resource revision."""
from hashlib import sha256
import json
from pathlib import Path
import re
import shutil
import stat
from uuid import uuid4

from .level_preview_server import _SEGMENT, _regular_file
from .paths import atomic_json, validate_output


_CACHE_FORMAT = 3
_PREWARM_MAX_BYTES = 2 * 1024 ** 3
_SLOT = re.compile(r'[a-f0-9]{64}')
_GENERATION = re.compile(r'assets-[a-f0-9]{32}')
_REQUIRED = {'fixture.json', 'scene-layout.json', 'native-actors/index.json'}


class NativeReplayPrewarmBudgetError(ValueError):
    def __init__(self):
        super().__init__('原生回放后台缓存已达容量上限，可点击播放出怪手动准备。')


def _ready_record(slot):
    try:
        marker = _regular_file(slot.parent, [slot.name, 'ready.json'])
        if marker is None:
            return None
        record = json.loads(marker.read_text(encoding='utf-8'))
        if _GENERATION.fullmatch(record['generation']) and _REQUIRED <= record['files'].keys():
            return record
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        pass
    return None


def _cached_result(slot, identity):
    record = _ready_record(slot)
    if record is None:
        return None
    try:
        generation, files, result = record['generation'], record['files'], record['result']
        if (result['level_id'] != identity['level_id']
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


def _ordinary_directory(info):
    return stat.S_ISDIR(info.st_mode) and not (
        getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def _check_prewarm_budget(root, incoming_bytes, cancel):
    remaining = _PREWARM_MAX_BYTES - incoming_bytes
    if remaining < 0:
        raise NativeReplayPrewarmBudgetError()
    try:
        info = root.lstat()
    except FileNotFoundError:
        return
    if not _ordinary_directory(info):
        raise ValueError('原生回放缓存路径越界。')

    # Complete generations are immutable and record sizes at publication.
    # Read only the small receipts instead of enumerating cached asset files.
    for slot in root.iterdir():
        cancel.check()
        if not _SLOT.fullmatch(slot.name) or (record := _ready_record(slot)) is None:
            continue
        try:
            info = (slot / record['generation']).lstat()
        except FileNotFoundError:
            continue
        sizes = record['files'].values()
        if _ordinary_directory(info) and all(type(size) is int and size >= 0 for size in sizes):
            remaining -= sum(sizes)
            if remaining < 0:
                raise NativeReplayPrewarmBudgetError()


def _cache_slot(data_root, options):
    game_root = Path(options['game_root']).resolve()
    data_root = Path(data_root)
    root = data_root / 'native-level-replays'
    if validate_output(data_root, game_root) != data_root or root == game_root:
        raise ValueError('原生回放缓存路径越界。')
    archive = options.get('crisis_info')
    # The display caption can arrive asynchronously after opening the catalog.
    identity = {**options, 'game_root': game_root.as_posix().casefold(), 'cache_format': _CACHE_FORMAT,
                'crisis_info': sha256(Path(archive).read_bytes()).hexdigest() if archive else None}
    identity.pop('caption', None)
    key = sha256(json.dumps(identity, sort_keys=True).encode('utf-8')).hexdigest()
    slot = root / key
    # Another worker can create either directory while Windows resolves a
    # missing path. Check each existing component without following links.
    for directory in (root, slot):
        try:
            info = directory.lstat()
        except FileNotFoundError:
            break
        if not _ordinary_directory(info):
            raise ValueError('原生回放缓存路径越界。')
    return slot, identity


def cached_native_replay(data_root, options):
    return _cached_result(*_cache_slot(data_root, options))


def prepare_cached_native_replay(runtime, options, *, emit, cancel, prewarm=False):
    cancel.check()
    options = options.copy()
    output = Path(options.pop('output')).resolve()
    slot, identity = _cache_slot(output.parent.parent, options)
    if (ready := _cached_result(slot, identity)) is not None:
        cancel.check()
        emit({'message': '正在使用已准备的原版关卡和角色动画…'})
        return ready
    if prewarm:
        _check_prewarm_budget(slot.parent, 1, cancel)

    from PySide6.QtCore import QLockFile
    from .extraction.level_replay_assets import prepare_level_playback
    from .level_native_atlases import prepare_native_atlases

    generation = f'assets-{uuid4().hex}'
    assets = slot / generation
    slot.parent.mkdir(parents=True, exist_ok=True)
    slot.mkdir(exist_ok=True)
    assets.mkdir()
    published = False
    try:
        result = prepare_level_playback(**options, output=assets, emit=emit, cancel=cancel)
        prepare_native_atlases(assets, runtime, emit=emit, cancel=cancel)
        cancel.check()
        files = {path.relative_to(assets).as_posix(): path.stat().st_size
                 for path in assets.rglob('*') if path.is_file()}
        if not _REQUIRED <= files.keys():
            raise ValueError('原生回放缓存缺少关卡或角色索引。')
        lock = QLockFile(str(slot.parent / '.publish.lock'))
        lock.setStaleLockTime(0)
        if not lock.tryLock(2000):
            raise OSError('原生回放缓存正在发布，请稍后重试。')
        try:
            cancel.check()
            if (ready := _cached_result(slot, identity)) is not None:
                return ready
            if prewarm:
                _check_prewarm_budget(slot.parent, sum(files.values()), cancel)
            # Keep a previous generation intact for any viewer still using it.
            cancel.check()
            atomic_json(slot / 'ready.json', {'generation': generation, 'files': files, 'result': result})
            published = True
        finally:
            lock.unlock()
        return {**result, 'native_assets': str(assets), 'native_cache_hit': False}
    finally:
        if not published and assets.resolve() == assets:
            shutil.rmtree(assets, ignore_errors=True)
