from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from threading import Event, Thread
import argparse
import json
import os
import subprocess

from PIL import Image

parser = argparse.ArgumentParser(description='Render a local, extracted Arknights map preview fixture.')
parser.add_argument('assets', type=Path, help='Directory containing the scene, textures, fixture and local runtime files.')
parser.add_argument('--output-dir', type=Path, help='Defaults to the assets directory.')
parser.add_argument('--frames', type=int, default=60)
parser.add_argument('--fps', type=int, default=30)
parser.add_argument('--start', type=float, default=0)
parser.add_argument('--video', action='store_true')
parser.add_argument('--view', action='store_true')
args = parser.parse_args()
if args.frames < 1 or args.fps < 1 or args.start < 0:
    parser.error('Capture needs positive frames and fps and a nonnegative start time.')
assets = args.assets.resolve()
out = args.output_dir.resolve() if args.output_dir else assets
source = Path(__file__).resolve().parent
if not all((assets / name).is_file() for name in ('fixture.json', 'scene-layout.json')):
    parser.error('The assets directory needs fixture.json and scene-layout.json.')
out.mkdir(parents=True, exist_ok=True)
renderer_files = {'/scene.html', '/scene.js', '/battle_lighting.js'}
done = Event()
frames = {}
errors = []
receipt = {}

class Handler(SimpleHTTPRequestHandler):
    def translate_path(self, path):
        path_only = path.split('?', 1)[0]
        if path_only in renderer_files:
            return str(source / path_only[1:])
        return super().translate_path(path)

    def log_message(self, *args):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
        if self.path.startswith('/frame/'):
            frames[int(self.path.rsplit('/', 1)[-1])] = body
        elif self.path == '/done':
            receipt.update(json.loads(body))
            done.set()
        elif self.path == '/error':
            errors.append(body.decode(errors='replace'))
            done.set()
        self.send_response(200)
        self.end_headers()

edge = Path(os.environ.get('ProgramFiles(x86)', 'C:/Program Files (x86)')) / 'Microsoft/Edge/Application/msedge.exe'
with ThreadingHTTPServer(('127.0.0.1', 0), partial(Handler, directory=str(assets))) as server:
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    target = f'http://127.0.0.1:{server.server_port}/scene.html'
    if args.view:
        os.startfile(target)
        print(target, flush=True)
        done.wait()
        raise SystemExit()
    command = [
        str(edge), '--headless=new', '--use-angle=swiftshader', '--enable-unsafe-swiftshader',
        '--no-first-run', '--no-default-browser-check', '--disable-background-networking',
        f'--user-data-dir={out / "edge-scene-profile"}',
        f'{target}?capture={args.frames}&fps={args.fps}&start={args.start}',
    ]
    with (out / 'scene-render.log').open('wb') as log:
        proc = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=log,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            for _ in range(120):
                if done.wait(1):
                    break
                if proc.poll() is not None:
                    raise RuntimeError(f'Edge exited {proc.returncode}. Frames captured: {len(frames)}.')
            if not done.is_set():
                raise RuntimeError(f'Capture timed out. Frames captured: {len(frames)}.')
            if errors:
                raise RuntimeError(errors)
        finally:
            if proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=15)
            server.shutdown()

assert len(frames) == args.frames
def image_at(index):
    return Image.open(BytesIO(frames[index])).convert('RGB')

first_frame = image_at(0)
first_frame.save(out / 'scene-empty.png')
actor_frame = round((receipt['spawn'] + 1 - args.start) * args.fps)
image_at(max(0, min(actor_frame, args.frames - 1))).save(out / 'scene-frame.png')
if args.video:
    width, height = first_frame.size
    staging = out / 'scene-motion.rendering.mp4'
    command = ['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pixel_format', 'rgb24',
               '-video_size', f'{width}x{height}', '-framerate', str(args.fps), '-i', '-',
               '-an', '-c:v', 'libx264', '-crf', '18', '-pix_fmt', 'yuv420p',
               '-movflags', '+faststart', str(staging)]
    with subprocess.Popen(command, stdin=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW) as encoder:
        for index in range(args.frames):
            encoder.stdin.write(image_at(index).tobytes())
        encoder.stdin.close()
        if encoder.wait():
            raise RuntimeError('MP4 encoding failed.')
    staging.replace(out / 'scene-motion.mp4')
elif args.frames > 1:
    first_frame.save(out / 'scene-motion.webp', save_all=True,
                     append_images=(image_at(index) for index in range(1, args.frames)),
                     duration=round(1000 / args.fps), loop=0, quality=91)
receipt.update(frameCount=len(frames))
(out / 'scene-result.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(receipt, ensure_ascii=False))
