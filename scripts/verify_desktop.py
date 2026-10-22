"""Smoke-test the native WebView2 window without interacting with user windows."""
import json
import argparse
import threading
from pathlib import Path

import webview

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--width', type=int, default=1440)
args = parser.parse_args()
result = {}
window = webview.create_window('绘序成境 · 桌面运行时验证', 'http://127.0.0.1:8765',
                               width=args.width, height=940, hidden=True)


def loaded():
    try:
        result.update(window.evaluate_js("""JSON.parse(JSON.stringify({
          title:document.title, width:innerWidth, height:innerHeight,
          hasWorkspace:!!document.querySelector('.workspace-grid'),
          bodyWidth:document.documentElement.scrollWidth
        }))"""))
    except Exception as exc:
        result['error'] = str(exc)
    finally:
        window.destroy()


window.events.loaded += loaded
timer = threading.Timer(25, window.destroy)
timer.daemon = True
timer.start()
webview.start(gui='edgechromium')
timer.cancel()
target = ROOT / 'artifacts' / f'desktop-verification-{args.width}.json'
target.parent.mkdir(exist_ok=True)
target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
assert result.get('hasWorkspace'), result
assert result['bodyWidth'] <= result['width'], result
print(json.dumps(result, ensure_ascii=True), flush=True)
