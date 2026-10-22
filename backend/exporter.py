from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import time
from pathlib import Path

from . import storage
from .hardware import ffmpeg_path
from .runtime import bundled_browser


def shared_renderer() -> str:
    return (storage.ROOT / "public" / "renderer.js").read_text(encoding="utf-8")


def standalone(work: dict, title: str = "绘序成境") -> str:
    import html
    data = json.dumps(work, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    return """<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>""" + html.escape(title) + """ · 绘序成境</title>
<style>*{box-sizing:border-box}body{margin:0;background:#eeede7;color:#264b3d;font:14px system-ui;display:flex;min-height:100vh;flex-direction:column;align-items:center;padding:24px}h1{font-size:20px;font-weight:500}canvas{max-width:94vw;max-height:70vh;width:auto;height:auto;box-shadow:0 10px 40px #0001}footer{display:flex;align-items:center;gap:12px;width:min(760px,94vw);padding:22px 0;flex-wrap:wrap}input{flex:1;min-width:120px;accent-color:#264b3d}button,select{border:1px solid #d7d8cf;border-radius:8px;background:#fff;padding:8px 14px;color:inherit;cursor:pointer}small{opacity:.6}</style>
<h1>""" + html.escape(title) + """</h1><canvas id="painting"></canvas>
<footer><button id="play">播放</button><button id="prev">上一笔</button><button id="next">下一笔</button><input id="seek" type="range" min="0" step="1"><span id="clock"></span><select id="speed"><option value="0.5">0.5×</option><option selected value="1">1×</option><option value="2">2×</option><option value="4">4×</option></select><button id="restart">重播</button></footer><small>绘序成境 · 每一笔，皆有来处 · 离线交互作品</small>
<script>""" + shared_renderer() + """</script><script id="work" type="application/json">""" + data + """</script><script>
const work=JSON.parse(document.getElementById('work').textContent),renderer=new StrokeRenderer(document.getElementById('painting'),work);
let time=0,playing=false,last=0;const seek=document.getElementById('seek'),play=document.getElementById('play');seek.max=work.durationMs;
function draw(){renderer.render(time);seek.value=time;document.getElementById('clock').textContent=(time/1000).toFixed(1)+' / '+(work.durationMs/1000).toFixed(1)+'s'}
play.onclick=()=>{if(time>=work.durationMs)time=0;playing=!playing;play.textContent=playing?'暂停':'播放';last=performance.now()};
seek.oninput=()=>{time=Number(seek.value);draw()};document.getElementById('restart').onclick=()=>{time=0;draw()};
document.getElementById('next').onclick=()=>{playing=false;play.textContent='播放';const s=work.strokes.find(s=>s.s+s.dt>time+.001);if(s)time=s.s+s.dt;draw()};
document.getElementById('prev').onclick=()=>{playing=false;play.textContent='播放';for(let i=work.strokes.length-1;i>=0;i--){const s=work.strokes[i];if(s.s<time-.001){time=s.s;break}}draw()};
function tick(now){if(playing){time=Math.min(work.durationMs,time+(now-last)*Number(document.getElementById('speed').value));draw();if(time>=work.durationMs){playing=false;play.textContent='播放'}}last=now;requestAnimationFrame(tick)}draw();requestAnimationFrame(tick);
</script></html>"""


def browser_options() -> dict:
    configured = os.environ.get("HUIXU_BROWSER")
    if configured and Path(configured).is_file():
        return {"executable_path": configured}
    bundled = bundled_browser()
    if bundled:
        return {"executable_path": str(bundled)}
    # Use an installed Chromium-family browser if available, otherwise Playwright's
    # bundled runtime. No browser download occurs during normal use.
    for base in (os.environ.get("PROGRAMFILES(X86)", ""), os.environ.get("PROGRAMFILES", ""), os.environ.get("LOCALAPPDATA", "")):
        for relative in ("Microsoft/Edge/Application/msedge.exe", "Google/Chrome/Application/chrome.exe"):
            path = Path(base) / relative
            if base and path.is_file():
                return {"executable_path": str(path)}
    return {}


def encode_video(task_id: str, options: dict, encoders: list[str]):
    directory = storage.task_dir(task_id)
    work = json.loads((directory / "work.json").read_text(encoding="utf-8"))
    cancel_path = directory / "export.cancel"
    started = time.perf_counter()
    output = directory / "painting.mp4"
    temporary = directory / "painting.partial.mp4"
    executable = ffmpeg_path()
    if not executable or not encoders:
        storage.update(task_id, export_state={"status": "failed", "error": "没有可用的视频编码器，请检查 FFmpeg 组件是否完整"})
        return
    fps = options.get("fps", 30)
    width = work["width"] + work["width"] % 2
    height = work["height"] + work["height"] % 2
    frames = math.ceil(work["durationMs"] / 1000 * fps) + 1
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, **browser_options())
            try:
                page = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=1)
                page.set_content('<html><style>html,body{margin:0;background:#f7f4eb;overflow:hidden}canvas{display:block}</style><canvas id="c"></canvas></html>')
                page.add_script_tag(content=shared_renderer())
                page.evaluate("work => {window.r=new StrokeRenderer(document.getElementById('c'),work,{cacheLimit:0});}", work)
                canvas = page.locator("canvas")
                # A pipe of PNG frames avoids accumulating thousands of files.
                last_error = ""
                for encoder in encoders:
                    if cancel_path.exists():
                        raise InterruptedError()
                    storage.update(task_id, export_state={"status": "running", "progress": 0, "encoder": encoder})
                    command = [executable, "-y", "-hide_banner", "-loglevel", "error", "-f", "image2pipe",
                               "-vcodec", "png", "-framerate", str(fps), "-i", "pipe:0", "-an", "-c:v", encoder,
                               "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2:color=0xf7f4eb", "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
                    if encoder == "libx264":
                        command += ["-preset", "veryfast", "-crf", "19"]
                    elif encoder == "libopenh264":
                        command += ["-b:v", "6M"]
                    elif encoder == "mpeg4":
                        command += ["-q:v", "3"]
                    command.append(str(temporary))
                    log = directory / "encode.log"
                    flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
                    failed = False
                    with log.open("wb") as errors:
                        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=errors, **flags)
                        try:
                            page.evaluate("r.clear()")
                            for frame in range(frames):
                                if cancel_path.exists():
                                    raise InterruptedError()
                                timestamp = min(work["durationMs"], frame * 1000 / fps)
                                page.evaluate("t => r.render(t)", timestamp)
                                process.stdin.write(canvas.screenshot(type="png", timeout=30000))
                                if frame % max(1, fps) == 0:
                                    storage.update(task_id, export_state={"status": "running", "progress": frame / frames,
                                                                         "encoder": encoder, "frame": frame, "frames": frames})
                            process.stdin.close()
                            if process.wait(timeout=90) != 0:
                                failed = True
                        except (BrokenPipeError, OSError):
                            failed = True
                        finally:
                            if process.poll() is None:
                                process.kill()
                            process.wait(timeout=10)
                            if process.stdin and not process.stdin.closed:
                                process.stdin.close()
                    if failed:
                        last_error = log.read_text(encoding="utf-8", errors="replace")[-1600:]
                        continue
                    temporary.replace(output)
                    storage.update(task_id, export_state={"status": "done", "progress": 1, "encoder": encoder,
                                                         "seconds": round(time.perf_counter() - started, 2), "bytes": output.stat().st_size})
                    return
                raise RuntimeError(last_error or "视频编码失败")
            finally:
                browser.close()
    except InterruptedError:
        storage.update(task_id, export_state={"status": "cancelled", "progress": 0})
    except Exception as exc:
        message = str(exc)
        if "Executable doesn't exist" in message:
            message = "未找到浏览器渲染运行时，请运行 python -m playwright install chromium，或安装 Edge / Chrome"
        storage.update(task_id, export_state={"status": "failed", "error": message[-1800:]})
    finally:
        temporary.unlink(missing_ok=True)


def create_html(task_id: str) -> Path:
    directory = storage.task_dir(task_id)
    task = storage.get(task_id)
    work = json.loads((directory / "work.json").read_text(encoding="utf-8"))
    result = directory / "painting.html"
    result.write_text(standalone(work, task["title"]), encoding="utf-8")
    return result
