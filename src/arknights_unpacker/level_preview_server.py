"""Serve a single generated level preview on an unguessable loopback URL."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
from secrets import token_urlsafe
import stat
from threading import Event, Thread
from urllib.parse import unquote


_PLAYER_FILES = ('scene.html', 'scene.js', 'battle_lighting.js')
_RUNTIME_FILES = (
    'pixi.min.js', 'pixi-spine.umd.js', 'three/three.module.js', 'three/three.core.js',
    'three/GLTFLoader.js', 'three/BufferGeometryUtils.js',
)
_SEGMENT = re.compile(r'[^/\\:\x00-\x1f\x7f?*<>"|]+')
_CONTENT_TYPE = {
    '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8',
    '.json': 'application/json', '.glb': 'model/gltf-binary', '.png': 'image/png',
    '.atlas': 'text/plain; charset=utf-8', '.skel': 'application/octet-stream',
}
_CSP = (
    "default-src 'none'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
    "style-src 'unsafe-inline'; connect-src 'self' blob:; img-src 'self' data: blob:; "
    "worker-src 'self' blob:; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
)


def _regular_file(root, parts):
    path = root
    try:
        for part in parts:
            path /= part
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                return None
        if not stat.S_ISREG(info.st_mode) or path.resolve(strict=True) != path:
            return None
    except (OSError, RuntimeError):
        return None
    return path


def missing_preview_runtime(runtime_root):
    root = Path(runtime_root).resolve()
    return tuple(name for name in _RUNTIME_FILES if _regular_file(root, name.split('/')) is None)


def _is_generated_asset(parts):
    name = parts[-1]
    suffix = Path(name).suffix.lower()
    if len(parts) == 1:
        return (name in {'fixture.json', 'scene-layout.json'} or suffix == '.glb'
                or (name.startswith('atlas-') and suffix == '.png'))
    if len(parts) >= 3 and parts[0] == 'actors':
        return suffix == '.png' or (len(parts) == 3 and name in {'actor.json', 'actor.skel', 'actor.atlas'})
    return len(parts) == 2 and parts[0] == 'enemy' and suffix == '.png'


class LevelPreviewServer:
    def __init__(self, asset_root, player_root, runtime_root):
        asset_root, player_root, runtime_root = map(lambda path: Path(path).resolve(),
                                                  (asset_root, player_root, runtime_root))
        missing = missing_preview_runtime(runtime_root)
        if missing:
            raise FileNotFoundError('关卡播放运行库缺少 ' + '、'.join(missing))
        for name in _PLAYER_FILES:
            if _regular_file(player_root, [name]) is None:
                raise FileNotFoundError(f'关卡播放器文件缺少 {name}')

        prefix = '/' + token_urlsafe(24) + '/'
        closing = self._closing = Event()

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_GET(self):
                self._send_file()

            def do_HEAD(self):
                self._send_file()

            def _send_file(self):
                host = f'127.0.0.1:{self.server.server_port}'
                origins = self.headers.get_all('Origin', [])
                if (closing.is_set() or self.headers.get_all('Host', []) != [host]
                        or (origins and origins != [f'http://{host}'])
                        or self.headers.get('Sec-Fetch-Site') in ('same-site', 'cross-site')):
                    self.send_error(403)
                    return
                url_path = self.path.partition('?')[0]
                if not url_path.startswith(prefix):
                    self.send_error(404)
                    return
                relative = unquote(url_path[len(prefix):])
                parts = relative.split('/')
                if any(not _SEGMENT.fullmatch(part) or part.endswith(('.', ' ')) for part in parts):
                    self.send_error(404)
                    return
                if relative in _PLAYER_FILES:
                    root = player_root
                elif relative in _RUNTIME_FILES:
                    root = runtime_root
                elif _is_generated_asset(parts):
                    root = asset_root
                else:
                    self.send_error(404)
                    return

                path = _regular_file(root, parts)
                if path is None:
                    self.send_error(404)
                    return
                try:
                    body = path.read_bytes() if self.command == 'GET' else None
                    size = len(body) if body is not None else path.stat().st_size
                except OSError:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header('Content-Type', _CONTENT_TYPE[path.suffix.lower()])
                self.send_header('Content-Length', str(size))
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Content-Security-Policy', _CSP)
                self.send_header('Cross-Origin-Resource-Policy', 'same-origin')
                self.send_header('Referrer-Policy', 'no-referrer')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.end_headers()
                if body is not None:
                    try:
                        self.wfile.write(body)
                    except ConnectionError:
                        pass

        self._server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.url = f'http://127.0.0.1:{self._server.server_port}{prefix}scene.html'
        thread = Thread(target=self._server.serve_forever, kwargs={'poll_interval': .05}, daemon=True)
        try:
            thread.start()
        except RuntimeError:
            self._server.server_close()
            raise

    def close(self):
        if not self._closing.is_set():
            self._closing.set()
            self._server.shutdown()
            self._server.server_close()
