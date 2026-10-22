"""Verify CUDA availability and a real GPU-backed worker job via the local API."""
import json
import time
import urllib.request
from pathlib import Path

BASE = 'http://127.0.0.1:8765/api'


def request(path, data=None):
    payload = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(BASE + path, data=payload, headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=35) as response:
        return json.load(response)


capabilities = request('/hardware?refresh=true')
assert capabilities['cuda']['available'], capabilities['cuda']
task = request('/tasks/sample', {'preset': 'sketch', 'budget': 600, 'duration': 30,
                                'device': 'gpu', 'seed': 42, 'maxEdge': 512})
deadline = time.monotonic() + 90
while time.monotonic() < deadline:
    task = request('/tasks/' + task['id'])
    if task['status'] in ('failed', 'cancelled', 'interrupted'):
        raise AssertionError(task['error'] or task['stage'])
    if task['status'] == 'done':
        break
    time.sleep(.5)
else:
    raise TimeoutError('GPU worker job')
assert task['stats']['backend'] == 'cuda', task['stats']
assert task['stats']['fallback'] is None, task['stats']
result = {'cuda': capabilities['cuda'], 'taskId': task['id'], 'stats': task['stats']}
path = Path(__file__).resolve().parents[1] / 'artifacts' / 'gpu-verification.json'
path.parent.mkdir(exist_ok=True)
path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(result, ensure_ascii=True, indent=2), flush=True)
