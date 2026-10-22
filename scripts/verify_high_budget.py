"""Exercise the fine preset through the actual worker and HTML export."""
import json
import time
import urllib.request
from pathlib import Path

BASE = 'http://127.0.0.1:8765/api'


def request(path, data=None):
    payload = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(BASE + path, data=payload, headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=60) as response:
        return json.load(response)


task = request('/tasks/sample', {'preset': 'fine', 'duration': 300, 'device': 'auto', 'seed': 42})
deadline = time.monotonic() + 240
last = None
while time.monotonic() < deadline:
    task = request('/tasks/' + task['id'])
    stage = task['stage']
    if stage != last:
        print(stage.encode('ascii', 'backslashreplace').decode(), flush=True)
        last = stage
    if task['status'] == 'done':
        break
    if task['status'] in ('failed', 'cancelled', 'interrupted'):
        raise AssertionError(task['error'] or task['stage'])
    time.sleep(1)
else:
    raise TimeoutError(task['id'])
work = request('/tasks/' + task['id'] + '/work')
assert len(work['strokes']) == 150000
assert work['settings']['maxEdge'] == 1920
assert all(stroke['dt'] > 0 for stroke in work['strokes'])
for previous, current in zip(work['strokes'], work['strokes'][1:]):
    assert previous['s'] + previous['dt'] <= current['s'] + 1e-7
assert abs(work['durationMs'] - 300000) < .001
with urllib.request.urlopen(BASE + '/tasks/' + task['id'] + '/html', timeout=90) as response:
    html_bytes = len(response.read())
result = {'taskId': task['id'], 'stats': task['stats'], 'layers': work['layers'],
          'size': [work['width'], work['height']], 'durationMs': work['durationMs'], 'htmlBytes': html_bytes}
output = Path(__file__).resolve().parents[1] / 'artifacts' / 'high-budget-verification.json'
output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(result, ensure_ascii=True, indent=2), flush=True)
