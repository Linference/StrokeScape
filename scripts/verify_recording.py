"""Compare real-time recording against screenshot export on an identical work."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--edge', type=int, default=320)
    parser.add_argument('--budget', type=int, default=320)
    parser.add_argument('--compare', action='store_true')
    args = parser.parse_args()
    run = ROOT / 'build' / 'recording-verification' / uuid.uuid4().hex[:10]
    os.environ['HUIXU_DATA'] = str(run)
    binary = ROOT / 'packaging/runtime/bin/ffmpeg.exe'
    browser = ROOT / 'release/staging/StrokeScape/_internal/browser/chrome-win64/chrome.exe'
    if binary.is_file():
        os.environ['HUIXU_FFMPEG'] = str(binary)
    if browser.is_file():
        os.environ['HUIXU_BROWSER'] = str(browser)
    from backend import storage
    from backend.demo import create_sample
    from backend.engine import paint
    from backend.exporter import encode_video, browser_options, shared_renderer
    from backend.hardware import ffmpeg_path
    from PIL import Image
    import numpy as np
    from playwright.sync_api import sync_playwright

    storage.init()
    sample = run / 'sample.png'
    create_sample(sample)
    task_id = uuid.uuid4().hex
    directory = storage.task_dir(task_id)
    directory.mkdir()
    settings = {'budget': args.budget, 'maxEdge': args.edge, 'preset': 'sketch', 'duration': 15, 'seed': 42, 'device': 'cpu'}
    work = paint(sample, settings, {}, lambda *_: None, lambda: False)
    storage.create(task_id, 'Recording verification', settings)
    storage.update(task_id, status='done', stats=work['stats'])
    (directory / 'work.json').write_text(json.dumps(work), encoding='utf-8')
    ffmpeg = ffmpeg_path()
    ffprobe = str(Path(ffmpeg).with_name('ffprobe.exe'))
    evidence = {'size': [work['width'], work['height']], 'budget': args.budget, 'durationSeconds': 15, 'modes': {}}
    for mode in (['frames', 'realtime'] if args.compare else ['realtime']):
        print('Starting ' + mode, flush=True)
        started = time.perf_counter()
        encode_video(task_id, {'fps': 24, 'hardware': False, 'mode': mode}, ['libopenh264', 'mpeg4'])
        result = storage.get(task_id)['export_state']
        assert result['status'] == 'done', result
        video = directory / ('painting-' + mode + '.mp4')
        shutil.copy2(directory / 'painting.mp4', video)
        info = json.loads(subprocess.check_output([ffprobe, '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(video)], creationflags=subprocess.CREATE_NO_WINDOW))
        duration = float(info['format']['duration'])
        assert abs(duration - 15) < 0.7, duration
        stream = info['streams'][0]
        assert stream['width'] == work['width'] + work['width'] % 2
        assert stream['height'] == work['height'] + work['height'] % 2
        evidence['modes'][mode] = {'state': result, 'wallSeconds': round(time.perf_counter() - started, 2),
                                 'duration': duration, 'frames': stream.get('nb_frames'), 'codec': stream['codec_name']}
        print(json.dumps(evidence['modes'][mode], ensure_ascii=True), flush=True)

    # Compare decoded recording against the exact Canvas renderer at start and end.
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, **browser_options())
        page = browser.new_page(viewport={'width': work['width'], 'height': work['height']})
        page.set_content('<canvas id="c"></canvas>')
        page.add_script_tag(content=shared_renderer())
        page.evaluate('w => {window.r = new StrokeRenderer(document.getElementById("c"), w, {cacheLimit:0})}', work)
        errors = {}
        for name, timestamp in [('start', 0), ('final', work['durationMs'])]:
            page.evaluate('t => r.render(t)', timestamp)
            reference = run / (name + '-reference.png')
            # Validation only: the new production export never takes screenshots.
            page.locator('canvas').screenshot(path=str(reference))
            target = run / (name + '-decoded.png')
            seek = ['-sseof', '-0.3'] if name == 'final' else ['-ss', '0']
            filters = ['-vf', 'reverse'] if name == 'final' else []
            subprocess.run([ffmpeg, '-y', '-v', 'error', *seek, '-i', str(video), *filters, '-frames:v', '1', str(target)],
                           check=True, creationflags=subprocess.CREATE_NO_WINDOW)
            expected = np.asarray(Image.open(reference).convert('RGB')).astype(float)
            actual = np.asarray(Image.open(target).convert('RGB'))[:work['height'], :work['width']].astype(float)
            errors[name] = round(float(np.abs(expected - actual).mean()), 3)
            assert errors[name] < 12, errors
        browser.close()
    evidence['decodedCanvasMAE'] = errors

    # Cancellation must stop promptly and remove partial video data.
    cancel = directory / 'export.cancel'
    timer = threading.Timer(2, cancel.touch)
    timer.start()
    started = time.perf_counter()
    try:
        encode_video(task_id, {'fps': 24, 'mode': 'realtime'}, ['libopenh264'])
    finally:
        timer.cancel()
        cancel.unlink(missing_ok=True)
    assert storage.get(task_id)['export_state']['status'] == 'cancelled'
    assert time.perf_counter() - started < 8
    assert not (directory / 'recording.partial').exists()
    assert not (directory / 'painting.partial.mp4').exists()
    evidence['cancellation'] = 'passed'
    (run / 'verification.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
    print('PASS ' + str(run), flush=True)


if __name__ == '__main__':
    main()
