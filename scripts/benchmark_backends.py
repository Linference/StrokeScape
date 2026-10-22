"""Same-image, same-budget CPU/CUDA core-generation benchmark (no video)."""
import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.engine import paint, load_image
from backend.hardware import detect_cuda
from backend.storage import DATA

parser = argparse.ArgumentParser()
parser.add_argument('--budget', type=int, default=18000)
parser.add_argument('--edge', type=int, default=960)
parser.add_argument('--repeats', type=int, default=3)
args = parser.parse_args()
cuda = detect_cuda()
assert cuda['available'], cuda
source = DATA / 'sample.png'
settings = {'preset': 'fine', 'duration': 180, 'budget': args.budget, 'maxEdge': args.edge, 'seed': 42}
records = {'cpu': [], 'gpu': []}
for repeat in range(args.repeats):
    for backend in (['cpu', 'gpu'] if repeat % 2 == 0 else ['gpu', 'cpu']):
        start = time.perf_counter()
        work = paint(source, settings | {'device': backend}, cuda, lambda *args: None, lambda: False)
        elapsed = time.perf_counter() - start
        if backend == 'gpu':
            assert work['stats']['backend'] == 'cuda', work['stats']
        records[backend].append({'seconds': elapsed, 'stats': work['stats']})
        print(f'{backend} run {repeat + 1}: {elapsed:.3f}s', flush=True)
        del work
medians = {key: statistics.median(item['seconds'] for item in values) for key, values in records.items()}
image = load_image(source, args.edge)
result = {'gpu': cuda['name'], 'image': 'bundled procedural landscape', 'size': [image.shape[1], image.shape[0]],
          'budget': args.budget, 'repeats': args.repeats, 'medians': medians,
          'speedup': medians['cpu'] / medians['gpu'], 'records': records,
          'scope': 'core generation only; excludes queueing, JSON serialization and video export'}
target = ROOT / 'artifacts' / f'backend-benchmark-{args.budget}.json'
target.parent.mkdir(exist_ok=True)
target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({k: v for k, v in result.items() if k != 'records'}, ensure_ascii=True, indent=2), flush=True)
