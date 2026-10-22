"""Run a reproducible fixed-image budget comparison on the CPU feedback canvas.

python -m scripts.compare_budgets docs/media/sample-source.png --edge 512
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path

from PIL import Image

from backend.api import Settings
from backend.engine import paint


def main():
    parser = argparse.ArgumentParser(description='同图、同尺寸、同笔刷、同种子的笔触预算实验')
    parser.add_argument('source', type=Path)
    parser.add_argument('--edge', type=int, default=512)
    parser.add_argument('--budgets', default='20000,60000,150000,500000')
    parser.add_argument('--output', type=Path, default=Path('artifacts/budget-comparison'))
    options = parser.parse_args()
    options.output.mkdir(parents=True, exist_ok=True)
    budgets = [int(value) for value in options.budgets.split(',')]
    digest = hashlib.sha256(options.source.read_bytes()).hexdigest()
    rows = []
    for budget in budgets:
        settings = Settings(preset='sketch', budget=budget, maxEdge=options.edge, duration=30,
                            device='cpu', brush='classic', seed=42, adaptiveStop=False, naturalOrder=True).model_dump()
        def preview(canvas, count):
            if count == budget:
                Image.fromarray(canvas).save(options.output / f'feedback-{budget}.png')
        work = paint(options.source, settings, {}, lambda *_: None, lambda: False, preview=preview)
        stats = work['stats']
        row = dict(requested=budget, actual=len(work['strokes']), width=work['width'], height=work['height'],
                   seconds=stats['computeSeconds'], mae=stats['mae'], psnr=stats['psnr'], meanJump=stats['meanJump'])
        rows.append(row)
        print(json.dumps(row), flush=True)
        with (options.output / 'results.csv').open('w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(row))
            writer.writeheader()
            writer.writerows(rows)
        (options.output / 'experiment.json').write_text(json.dumps({'sourceSha256': digest, 'settings':settings,
            'metricSource':'OpenCV feedback, approximate; not final Canvas or perceptual quality', 'results':rows},ensure_ascii=False,indent=2),encoding='utf-8')
        del work


if __name__ == '__main__':
    main()
