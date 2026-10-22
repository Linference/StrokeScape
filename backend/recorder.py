"""Real-time Canvas/MediaRecorder export with streamed, bounded-memory chunks."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import secrets
import subprocess
import threading
import time

from . import storage


class RecordingSink:
    """Receive encoded browser chunks locally; never collect a whole video in RAM."""
    def __init__(self, path: Path, cancelled):
        self.path = path
        self.cancelled = cancelled
        self.token = secrets.token_hex(24)
        self.error = None
        self.size = 0
        sink = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                if self.path != f'/{sink.token}/':
                    self.send_error(404)
                    return
                body = b'<!doctype html><meta charset="utf-8"><style>body{margin:0}canvas{display:block}</style><canvas id="c"></canvas>'
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                if self.path != f'/{sink.token}/chunk':
                    self.send_error(404)
                    return
                if sink.cancelled():
                    self.send_error(409)
                    return
                try:
                    length = int(self.headers.get('Content-Length', '0'))
                    if not 0 < length <= 64 * 1024 * 1024:
                        self.send_error(413)
                        return
                    remaining = length
                    with sink.path.open('ab') as output:
                        while remaining:
                            chunk = self.rfile.read(min(remaining, 1024 * 1024))
                            if not chunk:
                                raise OSError('Incomplete video chunk')
                            output.write(chunk)
                            remaining -= len(chunk)
                    sink.size += length
                    self.send_response(204)
                    self.send_header('Content-Length', '0')
                    self.end_headers()
                except (OSError, ValueError) as exc:
                    sink.error = str(exc)
                    self.send_error(500)

        self.server = HTTPServer(('127.0.0.1', 0), Handler)
        self.server.timeout = 1
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': 0.1}, daemon=True)

    def __enter__(self):
        self.path.write_bytes(b'')
        self.thread.start()
        return self

    @property
    def url(self):
        return f'http://127.0.0.1:{self.server.server_port}/{self.token}/'

    def __exit__(self, *_):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


def run_ffmpeg(command, log: Path, cancelled):
    flags = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
    with log.open('wb') as errors:
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=errors, **flags)
        try:
            while process.poll() is None:
                if cancelled():
                    raise InterruptedError()
                time.sleep(0.1)
            return process.returncode == 0
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=10)


def record_video(task_id: str, options: dict, encoders: list[str], executable: str,
                 browser_options: dict, renderer_source: str):
    directory = storage.task_dir(task_id)
    cancel = directory / 'export.cancel'
    source = directory / 'recording.partial'
    temporary = directory / 'painting.partial.mp4'
    work = json.loads((directory / 'work.json').read_text(encoding='utf-8'))
    started = time.perf_counter()
    fps = options.get('fps', 30)
    state = {'status': 'running', 'mode': 'realtime', 'phase': 'preparing', 'progress': 0}

    def update(**fields):
        state.update(fields)
        storage.update(task_id, export_state=state)

    try:
        update()
        from playwright.sync_api import sync_playwright
        with RecordingSink(source, cancel.exists) as sink, sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, **browser_options,
                args=['--disable-background-timer-throttling', '--disable-renderer-backgrounding', '--disable-backgrounding-occluded-windows'])
            try:
                page = browser.new_page(viewport={'width': work['width'], 'height': work['height']})
                page.goto(sink.url)
                page.add_script_tag(content=renderer_source)
                page.add_script_tag(content=(storage.ROOT / 'public/recording.js').read_text(encoding='utf-8'))
                metadata = page.evaluate('({work,fps}) => startStrokeRecording(work,fps)', {'work': work, 'fps': fps})
                update(encoder='浏览器 H.264' if metadata['mime'].startswith('video/mp4') else '浏览器 VP8', mime=metadata['mime'])
                deadline = started + work['durationMs'] / 1000 + 120
                while True:
                    if cancel.exists():
                        page.evaluate('cancelStrokeRecording()')
                        raise InterruptedError()
                    current = page.evaluate('recordingState')
                    if sink.error:
                        raise RuntimeError(sink.error)
                    if current['status'] == 'failed':
                        raise RuntimeError(current.get('error', '画布录制失败'))
                    if current['status'] == 'cancelled':
                        raise InterruptedError()
                    if current['status'] == 'done':
                        break
                    if time.perf_counter() > deadline:
                        raise TimeoutError('画布录制超时，请重试或选择逐帧导出')
                    update(phase='recording' if current['status'] == 'recording' else 'preparing',
                           progress=min(0.94, current['elapsedMs'] / work['durationMs'] * 0.94),
                           elapsedMs=current['elapsedMs'], frames=current['frames'])
                    time.sleep(0.35)
                update(phase='packaging', progress=0.95, frames=current['frames'], elapsedMs=work['durationMs'])
            finally:
                browser.close()
        recording_seconds = time.perf_counter() - started
        if cancel.exists():
            raise InterruptedError()
        if not source.is_file() or source.stat().st_size < 100:
            raise RuntimeError('浏览器未输出有效视频')
        command = [executable, '-y', '-hide_banner', '-loglevel', 'error', '-i', str(source), '-map', '0:v:0', '-an']
        log = directory / 'encode.log'
        encoder = 'copy'
        success = False
        if metadata['mime'].startswith('video/mp4'):
            # MediaRecorder already encoded H.264. Only normalize the MP4 container.
            success = run_ffmpeg(command + ['-c:v', 'copy', '-movflags', '+faststart', str(temporary)], log, cancel.exists)
        if not success:
            for encoder in encoders:
                update(phase='encoding', progress=0.96, encoder=encoder)
                parameters = ['-c:v', encoder, '-pix_fmt', 'yuv420p', '-movflags', '+faststart']
                if encoder == 'libx264':
                    parameters += ['-preset', 'veryfast', '-crf', '19']
                elif encoder == 'libopenh264':
                    parameters += ['-b:v', '6M']
                elif encoder == 'mpeg4':
                    parameters += ['-q:v', '3']
                if run_ffmpeg(command + parameters + [str(temporary)], log, cancel.exists):
                    success = True
                    break
        if not success:
            raise RuntimeError(log.read_text(encoding='utf-8', errors='replace')[-1600:] if log.exists() else '没有可用的 MP4 编码器')
        temporary.replace(directory / 'painting.mp4')
        update(status='done', phase='done', progress=1, encoder='浏览器 H.264 · 直接封装' if encoder == 'copy' else encoder,
               recordingSeconds=round(recording_seconds, 2), seconds=round(time.perf_counter() - started, 2),
               bytes=(directory / 'painting.mp4').stat().st_size)
    except InterruptedError:
        update(status='cancelled', progress=0)
    except Exception as exc:
        update(status='failed', error=str(exc)[-1800:])
    finally:
        source.unlink(missing_ok=True)
        temporary.unlink(missing_ok=True)
