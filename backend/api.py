from __future__ import annotations

import asyncio
import io
import json
import multiprocessing
import shutil
import threading
import uuid
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field
from typing import Literal

from . import storage
from .demo import create_sample
from .engine import Cancelled, paint
from .exporter import create_html, encode_video
from .hardware import capabilities

pool: ProcessPoolExecutor | None = None
exports: ThreadPoolExecutor | None = None
futures: dict = {}
export_futures: dict = {}
submit_lock = threading.Lock()
Image.MAX_IMAGE_PIXELS = 24_000_000


class Settings(BaseModel):
    preset: Literal["sketch", "standard", "fine"] = "standard"
    duration: int = Field(default=90, ge=15, le=600)
    device: Literal["auto", "cpu", "gpu"] = "auto"
    seed: int = Field(default=42, ge=0, le=2**32 - 1)
    budget: int | None = Field(default=None, ge=200, le=200000)
    maxEdge: int | None = Field(default=None, ge=128, le=2560)


class VideoSettings(BaseModel):
    fps: Literal[24, 30, 60] = 30
    hardware: bool = True
    mode: Literal["realtime", "frames"] = "realtime"


def generate_worker(task_id: str, settings: dict, cuda: dict):
    directory = storage.task_dir(task_id)
    cancel = directory / "generate.cancel"
    try:
        if cancel.exists():
            raise Cancelled()
        storage.update(task_id, status="running", stage="准备画布", progress=0.01, error=None)
        work = paint(directory / "input.png", settings, cuda,
                     lambda value, stage: storage.update(task_id, progress=value, stage=stage), cancel.exists)
        temporary = directory / "work.partial.json"
        temporary.write_text(json.dumps(work, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        if cancel.exists():
            raise Cancelled()
        temporary.replace(directory / "work.json")
        storage.update(task_id, status="done", progress=1, stage="绘制方案已就绪", stats=work["stats"])
    except Cancelled:
        storage.update(task_id, status="cancelled", stage="已取消生成")
    except Exception as exc:
        storage.update(task_id, status="failed", stage="生成失败", error=f"{type(exc).__name__}: {exc}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global pool, exports
    storage.init()
    sample = storage.DATA / "sample.png"
    if not sample.exists():
        create_sample(sample)
    pool = ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn"))
    exports = ThreadPoolExecutor(max_workers=1, thread_name_prefix="video-export")
    yield
    for task in storage.all_tasks():
        if task["status"] in ("queued", "running", "cancelling"):
            (storage.task_dir(task["id"]) / "generate.cancel").touch()
        if (task.get("export_state") or {}).get("status") in ("queued", "running"):
            (storage.task_dir(task["id"]) / "export.cancel").touch()
    pool.shutdown(wait=False, cancel_futures=True)
    exports.shutdown(wait=False, cancel_futures=True)


app = FastAPI(title="绘序成境 · Local Studio", lifespan=lifespan)


@app.middleware("http")
async def local_access_only(request, call_next):
    # Reject cross-origin browser requests from external websites to the local app.
    from fastapi.responses import JSONResponse
    if request.url.hostname not in ("127.0.0.1", "localhost", "testserver"):
        return JSONResponse({"detail": "仅允许本地访问"}, status_code=403)
    origin = request.headers.get("origin")
    if origin:
        parsed = urlsplit(origin)
        if parsed.hostname not in ("127.0.0.1", "localhost") or parsed.scheme not in ("http", "https"):
            return JSONResponse({"detail": "不接受外部网站发起的请求"}, status_code=403)
    return await call_next(request)


def require_task(task_id: str) -> dict:
    try:
        storage.task_dir(task_id)
    except ValueError:
        raise HTTPException(404, "找不到这幅作品")
    task = storage.get(task_id)
    if task is None:
        raise HTTPException(404, "找不到这幅作品")
    return task


def queue_task(task_id: str, title: str, settings: Settings):
    caps = capabilities()
    if settings.device == "gpu" and not caps["cuda"]["available"]:
        raise HTTPException(422, caps["cuda"]["reason"] or "GPU 计算不可用，请选择自动或 CPU")
    with submit_lock:
        pending = sum(item["status"] in ("queued", "running", "cancelling") for item in storage.all_tasks())
        if pending >= 6:
            raise HTTPException(429, "任务队列已满，请等待当前作品完成")
        storage.create(task_id, title, settings.model_dump())
        futures[task_id] = pool.submit(generate_worker, task_id, settings.model_dump(), caps["cuda"])
    return storage.get(task_id)


@app.get("/api/health")
def health():
    return {"ok": True, "name": "绘序成境", "version": "0.1.0"}


@app.get("/api/hardware")
def hardware(refresh: bool = False):
    return capabilities(refresh)


@app.get("/api/tasks")
def list_tasks():
    return storage.all_tasks()


@app.get("/api/sample")
def sample_image():
    return FileResponse(storage.DATA / "sample.png", media_type="image/png")


@app.post("/api/tasks/sample")
def sample_task(settings: Settings):
    task_id = uuid.uuid4().hex
    directory = storage.task_dir(task_id)
    directory.mkdir(parents=True)
    shutil.copyfile(storage.DATA / "sample.png", directory / "input.png")
    try:
        return queue_task(task_id, "山间来信", settings)
    except Exception:
        # Only the directory created above can be removed here.
        shutil.rmtree(directory)
        raise


@app.post("/api/tasks")
async def upload_task(file: UploadFile = File(...), options: str = Form("{}")):
    from pydantic import ValidationError
    try:
        settings = Settings.model_validate_json(options)
    except ValidationError as exc:
        raise HTTPException(422, "生成参数无效：" + str(exc))
    content = bytearray()
    while chunk := await file.read(1024 * 1024):
        content.extend(chunk)
        if len(content) > 24 * 1024 * 1024:
            raise HTTPException(413, "图片文件请控制在 24 MB 以内")
    try:
        with Image.open(io.BytesIO(content)) as image:
            if image.width * image.height > 24_000_000:
                raise HTTPException(413, "图片像素过多，请缩小到 2400 万像素以内")
            image = ImageOps.exif_transpose(image).convert("RGBA")
            if min(image.size) < 16:
                raise HTTPException(422, "图片的宽和高至少为 16 像素")
            image.thumbnail((4096, 4096), Image.Resampling.LANCZOS)
            normalized = io.BytesIO()
            image.save(normalized, "PNG")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise HTTPException(422, "无法读取图片，请使用有效的 PNG、JPEG 或 WebP 图片")
    task_id = uuid.uuid4().hex
    directory = storage.task_dir(task_id)
    directory.mkdir(parents=True)
    (directory / "input.png").write_bytes(normalized.getvalue())
    title = Path((file.filename or "未命名作品").replace("\\", "/")).stem[:80] or "未命名作品"
    try:
        return await asyncio.to_thread(queue_task, task_id, title, settings)
    except Exception:
        shutil.rmtree(directory)
        raise


@app.get("/api/tasks/{task_id}")
def task_details(task_id: str):
    return require_task(task_id)


@app.get("/api/tasks/{task_id}/source")
def source_image(task_id: str):
    require_task(task_id)
    return FileResponse(storage.task_dir(task_id) / "input.png", media_type="image/png")


@app.get("/api/tasks/{task_id}/work")
def work_data(task_id: str):
    task = require_task(task_id)
    if task["status"] != "done":
        raise HTTPException(409, "作品尚未生成完成")
    return FileResponse(storage.task_dir(task_id) / "work.json", media_type="application/json")


@app.post("/api/tasks/{task_id}/cancel")
def cancel_task(task_id: str):
    task = require_task(task_id)
    if task["status"] in ("queued", "running"):
        (storage.task_dir(task_id) / "generate.cancel").touch()
        future = futures.get(task_id)
        if future and future.cancel():
            storage.update(task_id, status="cancelled", stage="已取消生成")
        else:
            storage.update(task_id, status="cancelling", stage="正在停止生成…")
    return require_task(task_id)


@app.post("/api/tasks/{task_id}/retry")
def retry_task(task_id: str, settings: Settings):
    task = require_task(task_id)
    new_id = uuid.uuid4().hex
    directory = storage.task_dir(new_id)
    directory.mkdir(parents=True)
    shutil.copyfile(storage.task_dir(task_id) / "input.png", directory / "input.png")
    try:
        return queue_task(new_id, task["title"], settings)
    except Exception:
        shutil.rmtree(directory)
        raise


@app.get("/api/tasks/{task_id}/html")
def download_html(task_id: str):
    task = require_task(task_id)
    if task["status"] != "done":
        raise HTTPException(409, "作品尚未生成完成")
    path = create_html(task_id)
    return FileResponse(path, media_type="text/html", filename=f"{task['title']} · 绘序成境.html")


@app.post("/api/tasks/{task_id}/video")
def start_video(task_id: str, options: VideoSettings):
    task = require_task(task_id)
    if task["status"] != "done":
        raise HTTPException(409, "请先完成笔触生成")
    with submit_lock:
        if (task.get("export_state") or {}).get("status") in ("queued", "running"):
            raise HTTPException(409, "该作品正在导出")
        if sum((t.get("export_state") or {}).get("status") in ("queued", "running") for t in storage.all_tasks()) >= 3:
            raise HTTPException(429, "导出队列已满，请稍后重试")
        caps = capabilities()
        software = {"libx264", "libopenh264", "h264_mf", "mpeg4"}
        encoders = caps["encoders"] if options.hardware else [e for e in caps["encoders"] if e in software]
        if not caps["ffmpeg"] or (options.mode == "frames" and not encoders):
            raise HTTPException(422, "未检测到可用的视频编码器")
        (storage.task_dir(task_id) / "export.cancel").unlink(missing_ok=True)
        storage.update(task_id, export_state={"status": "queued", "progress": 0, "mode": options.mode})
        export_futures[task_id] = exports.submit(encode_video, task_id, options.model_dump(), encoders)
    return require_task(task_id)


@app.post("/api/tasks/{task_id}/video/cancel")
def cancel_video(task_id: str):
    task = require_task(task_id)
    if (task.get("export_state") or {}).get("status") in ("queued", "running"):
        (storage.task_dir(task_id) / "export.cancel").touch()
        future = export_futures.get(task_id)
        if future and future.cancel():
            storage.update(task_id, export_state={"status": "cancelled"})
    return require_task(task_id)


@app.get("/api/tasks/{task_id}/video")
def download_video(task_id: str):
    task = require_task(task_id)
    path = storage.task_dir(task_id) / "painting.mp4"
    if (task.get("export_state") or {}).get("status") != "done" or not path.is_file():
        raise HTTPException(409, "视频尚未导出完成")
    return FileResponse(path, media_type="video/mp4", filename=f"{task['title']} · 绘序成境.mp4")


web = storage.ROOT / "web-dist"
if web.is_dir():
    app.mount("/", StaticFiles(directory=web, html=True), name="studio")
