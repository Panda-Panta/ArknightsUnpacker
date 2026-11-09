"""Sample the original Spine animations for the native replay player."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import re
from secrets import token_urlsafe
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Event, Thread
from time import monotonic
from urllib.parse import unquote

from PIL import Image

from .level_preview_server import _CONTENT_TYPE, _CSP, _SEGMENT, _regular_file
from .paths import atomic_json, resource_root


_SCRIPTS = ('bake.html', 'bake.js')
_RUNTIME = ('pixi.min.js', 'pixi-spine.umd.js')
_ACTOR_ID = re.compile(r'[A-Za-z0-9_#-]+')
_HIDDEN = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
_TIMEOUT = 180


def _input_file(root, relative):
    parts = relative.split('/')
    if any(not _SEGMENT.fullmatch(part) or part.endswith(('.', ' ')) for part in parts):
        raise ValueError(f'原生角色图集资源路径无效：{relative}')
    path = _regular_file(root, parts)
    if path is None:
        raise FileNotFoundError(f'原生角色图集资源缺失：{root / relative}')
    return path


def _actor_inputs(assets, configs):
    files = {}
    expected = {}
    for actor_id, config in configs.items():
        if not _ACTOR_ID.fullmatch(actor_id):
            raise ValueError(f'原生角色标识无效：{actor_id}')
        for relative in (config['skeleton'], config['atlas'], *config['texturePages']):
            if not relative.startswith('actors/'):
                raise ValueError(f'原生角色资源不在本次回放目录：{relative}')
            files[relative] = _input_file(assets, relative)
        modes = ['move']
        if config.get('idleClip'):
            modes.append('idle')
        if attack := config.get('periodicAttack'):
            if phases := attack.get('phases'):
                modes.extend(f'attack-{index}' for index in range(len(phases)))
            else:
                modes.append('attack')
        expected[actor_id] = {mode: f'{actor_id}-{mode}.png' for mode in modes}
    return files, expected


def _find_edge():
    for name, default in (('ProgramFiles(x86)', 'C:/Program Files (x86)'), ('ProgramFiles', 'C:/Program Files')):
        edge = Path(os.environ.get(name, default)) / 'Microsoft/Edge/Application/msedge.exe'
        if edge.is_file():
            return edge
    raise FileNotFoundError('准备原生角色动画需要 Microsoft Edge，未找到本机的 msedge.exe。')


def _launch_edge(edge, profile, url, log):
    command = [str(edge), '--headless=new', '--use-angle=swiftshader', '--enable-unsafe-swiftshader',
               '--no-first-run', '--no-default-browser-check', '--disable-background-networking',
               '--disable-component-update', '--disable-extensions', '--disable-sync', '--no-proxy-server',
               '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1', f'--user-data-dir={profile}', url]
    options = {'cwd': edge.parent, 'stdout': subprocess.DEVNULL, 'stderr': log, 'creationflags': _HIDDEN}
    if sys.platform != 'win32' or not getattr(sys, 'frozen', False):
        return subprocess.Popen(command, **options)

    # The dedicated replay worker must launch system Edge with the system DLL search path.
    import ctypes

    bundled = os.path.normcase(os.path.normpath(sys._MEIPASS))
    env = os.environ.copy()
    search = [part for part in env.get('PATH', '').split(os.pathsep) if part]
    paths = (os.path.normcase(os.path.normpath(part.strip('"'))) for part in search)
    env['PATH'] = os.pathsep.join(part for part, path in zip(search, paths)
                                if path != bundled and not path.startswith(bundled + os.sep))
    set_directory = ctypes.WinDLL('kernel32', use_last_error=True).SetDllDirectoryW
    set_directory.argtypes = [ctypes.c_wchar_p]
    if not set_directory(None):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return subprocess.Popen(command, env=env, **options)
    finally:
        set_directory(sys._MEIPASS)


def _stop_edge(process):
    if process.poll() is not None:
        return
    if sys.platform == 'win32':
        taskkill = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32/taskkill.exe'
        try:
            subprocess.run([str(taskkill), '/F', '/T', '/PID', str(process.pid)], timeout=4,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=_HIDDEN)
        except (OSError, subprocess.TimeoutExpired):
            pass  # Terminate the owned browser directly if its process tree is already closing.
    if process.poll() is None:
        process.kill()
    process.wait(timeout=5)


def _bake(edge, files, request, names, temporary, staging, cancel):
    prefix = '/' + token_urlsafe(24) + '/'
    done = Event()
    closing = Event()
    result = {}

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(5)

        def log_message(self, *_args):
            pass

        def _relative(self):
            host = f'127.0.0.1:{self.server.server_port}'
            origins = self.headers.get_all('Origin', [])
            if (closing.is_set() or self.headers.get_all('Host', []) != [host]
                    or ((self.command == 'POST' or origins) and origins != [f'http://{host}'])
                    or self.headers.get('Sec-Fetch-Site') in ('same-site', 'cross-site')):
                self.send_error(403)
                return None
            path = self.path.partition('?')[0]
            if not path.startswith(prefix):
                self.send_error(404)
                return None
            return unquote(path[len(prefix):])

        def _reply(self, body=b'', content_type='text/plain'):
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Security-Policy', _CSP)
            self.send_header('Cross-Origin-Resource-Policy', 'same-origin')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            if body:
                try:
                    self.wfile.write(body)
                except ConnectionError:
                    pass

        def do_GET(self):
            relative = self._relative()
            if relative is None:
                return
            if relative == 'config':
                self._reply(request, 'application/json; charset=utf-8')
                return
            path = files.get(relative)
            if path is None:
                self.send_error(404)
                return
            self._reply(path.read_bytes(), _CONTENT_TYPE[path.suffix.lower()])

        def do_POST(self):
            relative = self._relative()
            if relative is None:
                return
            name = relative.removeprefix('atlas/')
            atlas = relative.startswith('atlas/') and name in names
            if done.is_set() or not (atlas or relative in ('done', 'error')):
                self.send_error(404)
                return
            lengths = self.headers.get_all('Content-Length', [])
            if len(lengths) != 1 or not re.fullmatch(r'[0-9]{1,8}', lengths[0]):
                self.send_error(400)
                return
            size = int(lengths[0])
            if not 0 < size <= (32 * 1024 * 1024 if atlas else 1024 * 1024):
                self.send_error(413)
                return
            try:
                body = self.rfile.read(size)
                if len(body) != size or closing.is_set():
                    return
                if atlas:
                    with (staging / name).open('xb') as stream:
                        stream.write(body)
                elif relative == 'done':
                    result['index'] = json.loads(body)
                else:
                    result['error'] = body.decode('utf-8', errors='replace')
            except (OSError, ValueError) as error:
                result['error'] = str(error)
                done.set()
                self.send_error(400)
                return
            try:
                self._reply()
            finally:
                if not atlas:
                    done.set()

    log_path = temporary / 'edge.log'
    with ThreadingHTTPServer(('127.0.0.1', 0), Handler) as server:
        thread = Thread(target=server.serve_forever, kwargs={'poll_interval': .05}, daemon=True)
        thread.start()
        url = f'http://127.0.0.1:{server.server_port}{prefix}bake.html'
        failure = None
        try:
            cancel.check()
            with log_path.open('wb') as log:
                process = _launch_edge(edge, temporary / 'profile', url, log)
                try:
                    deadline = monotonic() + _TIMEOUT
                    while not done.wait(.1):
                        cancel.check()
                        if process.poll() is not None:
                            failure = f'Edge 退出，代码 {process.returncode}。'
                            break
                        if monotonic() >= deadline:
                            failure = '等待原版角色动画采样超时。'
                            break
                finally:
                    closing.set()
                    _stop_edge(process)
        finally:
            server.shutdown()
            thread.join()
    cancel.check()
    if failure:
        with log_path.open('rb') as log:
            log.seek(max(0, log_path.stat().st_size - 2048))
            detail = log.read().decode('utf-8', errors='replace').strip()
        raise RuntimeError(f'{failure}\n{detail}' if detail else failure)
    if 'error' in result:
        raise RuntimeError(f'原生角色动画采样失败：{result["error"]}')
    return result['index']


def _validate(staging, index, expected, cancel):
    if not isinstance(index, dict) or index.keys() != expected.keys():
        raise ValueError('原生角色动画索引不完整。')
    for actor_id, clips in expected.items():
        actor = index[actor_id]
        size = actor.get('size') if isinstance(actor, dict) else None
        if (not isinstance(size, list) or len(size) != 2
                or any(not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0 for value in size)):
            raise ValueError(f'原生角色图集的角色尺寸无效：{actor_id}')
        for mode, filename in clips.items():
            cancel.check()
            spec = actor.get(mode, {})
            frames, columns = spec.get('frames'), spec.get('columns')
            if (spec.get('file') != filename or spec.get('frameWidth') != 256 or spec.get('frameHeight') != 256
                    or type(frames) is not int or not 1 <= frames <= 120
                    or type(columns) is not int or not 1 <= columns <= min(frames, 8)
                    or not isinstance(spec.get('fps'), (int, float)) or not math.isfinite(spec['fps']) or spec['fps'] <= 0
                    or not isinstance(spec.get('duration'), (int, float)) or not math.isfinite(spec['duration'])
                    or spec['duration'] <= 0):
                raise ValueError(f'原生角色图集数据无效：{filename}')
            with Image.open(staging / filename) as image:
                if (image.format != 'PNG' or image.mode != 'RGBA'
                        or image.size != (256 * columns, 256 * ((frames + columns - 1) // columns))):
                    raise ValueError(f'原生角色图集尺寸或通道无效：{filename}')
                image.verify()


def prepare_native_atlases(assets: Path, runtime: Path, *, emit, cancel) -> Path:
    """Publish a complete atlas directory inside an active replay lease."""
    cancel.check()
    assets, runtime = Path(assets).resolve(), Path(runtime).resolve()
    output = assets / 'native-actors'
    if output.exists():
        raise FileExistsError(f'回放目录已包含原生角色图集：{output}')
    fixture = json.loads(_input_file(assets, 'fixture.json').read_text(encoding='utf-8'))
    layout = json.loads(_input_file(assets, 'scene-layout.json').read_text(encoding='utf-8'))
    configs = {**fixture['actors'], **layout.get('predefinedActors', {}).get('configs', {})}
    with TemporaryDirectory(prefix='.native-bake-', dir=assets, ignore_cleanup_errors=True) as scratch:
        temporary = Path(scratch)
        staging = temporary / 'atlases'
        staging.mkdir()
        index = {}
        if configs:
            emit({'message': f'正在准备 {len(configs)} 种原版角色的原生动画图集…'})
            files, expected = _actor_inputs(assets, configs)
            scripts = resource_root().resolve() / 'scripts' / 'level_preview' / 'native_bake'
            files.update({name: _input_file(scripts, name) for name in _SCRIPTS})
            files.update({name: _input_file(runtime, name) for name in _RUNTIME})
            names = {name for clips in expected.values() for name in clips.values()}
            request = json.dumps({'actors': configs, 'actorScale': layout.get('actorScale', 1)},
                                 allow_nan=False).encode('utf-8')
            # Edge adds its own nested cache directories. Keep its profile
            # short even when the application data directory is deeply nested.
            with TemporaryDirectory(prefix='ak-spine-', ignore_cleanup_errors=True) as profile:
                index = _bake(_find_edge(), files, request, names, Path(profile), staging, cancel)
            _validate(staging, index, expected, cancel)
        atomic_json(staging / 'index.json', index)
        cancel.check()
        staging.rename(output)
    return output
