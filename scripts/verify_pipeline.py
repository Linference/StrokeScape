"""Exercise the real local API and video pipeline with a small reproducible job.

Run while launch.py is serving: python scripts/verify_pipeline.py
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
BASE = 'http://127.0.0.1:8765/api'


def request(path, data=None):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(BASE + path, data=body, headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=25) as response:
        return json.load(response)


def wait(task_id, export=False):
    deadline = time.monotonic() + 240
    last = None
    while time.monotonic() < deadline:
        task = request('/tasks/' + task_id)
        state = task['export_state'] if export else task
        status = state.get('status')
        if status != last:
            print(('video' if export else 'generation') + ': ' + str(status), flush=True)
            last = status
        if status == 'done':
            return task
        if status in ('failed', 'cancelled', 'interrupted'):
            raise AssertionError(state)
        time.sleep(.6)
    raise TimeoutError(task_id)


def main():
    settings = {'preset': 'sketch', 'budget': 320, 'duration': 15,
                'device': 'cpu', 'seed': 42, 'maxEdge': 320}
    with urllib.request.urlopen(BASE + '/sample') as response:
        source = response.read()
    boundary = 'HuixuPipelineBoundary'
    multipart = (f'--{boundary}\r\nContent-Disposition: form-data; name="options"\r\n\r\n'
                 + json.dumps(settings) + f'\r\n--{boundary}\r\nContent-Disposition: form-data; '
                 'name="file"; filename="pipeline-verification.png"\r\nContent-Type: image/png\r\n\r\n').encode()
    multipart += source + f'\r\n--{boundary}--\r\n'.encode()
    req = urllib.request.Request(BASE + '/tasks', data=multipart,
                                 headers={'Content-Type': 'multipart/form-data; boundary=' + boundary})
    with urllib.request.urlopen(req, timeout=30) as response:
        task = json.load(response)
    task_id = task['id']
    completed = wait(task_id)
    work = request('/tasks/' + task_id + '/work')
    assert len(work['strokes']) == 320
    assert abs(work['durationMs'] - 15000) < .1
    for previous, current in zip(work['strokes'], work['strokes'][1:]):
        assert previous['s'] + previous['dt'] <= current['s'] + 1e-7
    with urllib.request.urlopen(BASE + '/tasks/' + task_id + '/html') as response:
        html = response.read().decode()
    assert 'class StrokeRenderer' in html and 'https://' not in html
    request('/tasks/' + task_id + '/video', {'fps': 24, 'hardware': True})
    video = wait(task_id, True)['export_state']
    with urllib.request.urlopen(BASE + '/tasks/' + task_id + '/video') as response:
        payload = response.read()
    assert len(payload) > 1000 and b'ftyp' in payload[:32]
    result = {'taskId': task_id, 'count': len(work['strokes']), 'size': [work['width'], work['height']],
              'durationMs': work['durationMs'], 'generationSeconds': completed['stats']['computeSeconds'],
              'video': video, 'htmlBytes': len(html.encode()), 'checks': [
                  'actual multipart image upload', 'actual background generation', 'exact budget', 'strict serial schedule',
                  'standalone HTML', 'actual MP4 export', 'download endpoints']}
    target = ROOT / 'artifacts' / 'pipeline-verification.json'
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=True, indent=2), flush=True)


if __name__ == '__main__':
    main()
