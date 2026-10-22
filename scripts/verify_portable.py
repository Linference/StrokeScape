"""Exercise the extracted Windows release with no developer runtime on PATH."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import time
import urllib.request
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('archive', type=Path)
    args = parser.parse_args()
    run = ROOT / 'build' / 'portable-verification' / uuid.uuid4().hex[:10]
    run.mkdir(parents=True)
    with zipfile.ZipFile(args.archive) as source:
        for item in source.infolist():
            if not (run / item.filename).resolve().is_relative_to(run.resolve()):
                raise RuntimeError('Unsafe archive entry')
        source.extractall(run)
    bundle = run / 'StrokeScape'
    assert (bundle / '_internal/browser/chrome-win64/chrome.exe').is_file()
    assert (bundle / '_internal/bin/ffmpeg.exe').is_file()
    assert not (bundle / 'UserData').exists()
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    url = f'http://127.0.0.1:{port}'
    environment = os.environ.copy()
    for key in ('HUIXU_BROWSER', 'HUIXU_FFMPEG', 'PYTHONPATH', 'PYTHONHOME', 'VIRTUAL_ENV'):
        environment.pop(key, None)
    environment['PATH'] = str(Path(os.environ['SystemRoot']) / 'System32')
    environment['HUIXU_DATA'] = str(run / 'test-data')
    process = subprocess.Popen([str(bundle / 'StrokeScape.exe'), '--no-browser', '--port', str(port)],
                               cwd=bundle, env=environment, creationflags=subprocess.CREATE_NO_WINDOW)

    def request(path, body=None, raw=False):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(url + path, data=data, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=60) as response:
            payload = response.read()
        return payload if raw else json.loads(payload)

    def wait_for(check, seconds=180):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f'Portable app exited: {process.returncode}')
            result = check()
            if result:
                return result
            time.sleep(0.5)
        raise TimeoutError('Portable verification timed out')

    try:
        def ready():
            try:
                return request('/api/health')
            except (OSError, ValueError):
                return None
        health = wait_for(ready, 90)
        print('Extracted EXE started with a clean PATH.', flush=True)
        assert b'StrokeScape' in request('/', raw=True)
        hardware = request('/api/hardware')
        assert hardware['ffmpeg'] and hardware['encoders'], hardware
        assert not hardware['cuda']['available'], 'CPU portable release unexpectedly imports CUDA'
        task = request('/api/tasks/sample', {'budget': 320, 'maxEdge': 320, 'duration': 15, 'device': 'cpu'})
        task_id = task['id']

        def generated():
            state = request('/api/tasks/' + task_id)
            if state['status'] in ('failed', 'cancelled'):
                raise RuntimeError(state)
            return state if state['status'] == 'done' else None
        task = wait_for(generated)
        work = request(f'/api/tasks/{task_id}/work')
        strokes = work['strokes']
        assert len(strokes) == 320, len(strokes)
        assert all(a['s'] + a['dt'] <= b['s'] + 1e-7 for a, b in zip(strokes, strokes[1:]))
        assert len(request(f'/api/tasks/{task_id}/html', raw=True)) > 10000
        print('Stroke generation, serial timeline and HTML export passed.', flush=True)
        request(f'/api/tasks/{task_id}/video', {'fps': 24, 'hardware': False})

        def encoded():
            state = request('/api/tasks/' + task_id).get('export_state') or {}
            if state.get('status') in ('failed', 'cancelled'):
                raise RuntimeError(state)
            return state if state.get('status') == 'done' else None
        video_state = wait_for(encoded, 240)
        video = request(f'/api/tasks/{task_id}/video', raw=True)
        assert len(video) > 1000 and b'ftyp' in video[:40]
        (run / 'painting.mp4').write_bytes(video)
        result = {'health': health, 'hardware': hardware, 'strokes': len(strokes),
                  'videoBytes': len(video), 'video': video_state,
                  'cleanPath': True, 'extractedArchive': str(args.archive.resolve())}
        (run / 'verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'PASS: real MP4 exported using bundled browser and FFmpeg. Evidence: {run}', flush=True)
    finally:
        # Only stop the exact process tree created above; never touch the user's running studio.
        if process.poll() is None:
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                           capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            process.wait(timeout=20)


if __name__ == '__main__':
    main()
