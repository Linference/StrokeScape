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
from .projects import export_project, import_project

pool: ProcessPoolExecutor | None = None
exports: ThreadPoolExecutor | None = None
futures: dict = {}
export_futures: dict = {}
submit_lock = threading.RLock()
Image.MAX_IMAGE_PIXELS = 24_000_000


class Settings(BaseModel):
    preset: Literal["sketch", "standard", "fine"] = "standard"
    brush: Literal["classic", "pencil", "marker", "dry", "watercolor", "oil", "pointillism", "colored_pencil"] = "classic"
    duration: int = Field(default=90, ge=15, le=600)
    device: Literal["auto", "cpu", "gpu"] = "auto"
    seed: int = Field(default=42, ge=0, le=2**32 - 1)
    budget: int | None = Field(default=None, ge=200, le=500000)
    maxEdge: int | None = Field(default=None, ge=128, le=2560)
    brushScale: float = Field(default=1, ge=.3, le=3)
    opacityScale: float = Field(default=1, ge=.2, le=1.5)
    texture: float = Field(default=1, ge=0, le=2)
    gaps: float = Field(default=1, ge=0, le=2)
    adaptiveStop: bool = False
    stopThreshold: float = Field(default=.03, ge=.001, le=.5)
    naturalOrder: bool = True


class Metadata(BaseModel):
    title: str = Field(min_length=1, max_length=80)
    tags: list[str] = Field(default_factory=list, max_length=12)


class Refinement(BaseModel):
    region: list[int] = Field(min_length=4, max_length=4)
    budget: int = Field(default=5000, ge=200, le=100000)
    settings: Settings


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
        def preview(canvas, count):
            image = Image.fromarray(canvas)
            image.thumbnail((640, 640))
            temporary = directory / 'preview.partial.png'
            image.save(temporary, 'PNG')
            try:
                temporary.replace(directory / 'preview.png')
            except PermissionError:
                pass  # A reader may briefly hold the previous frame on Windows.
        base_path = directory / 'base.json'
        base = json.loads(base_path.read_text(encoding='utf-8')) if base_path.exists() else None
        region = json.loads((directory / 'region.json').read_text()) if base else None
        work = paint(directory / "input.png", settings, cuda,
                     lambda value, stage: storage.update(task_id, progress=value, stage=stage), cancel.exists,
                     preview=preview, base=base, region=region)
        if base:
            work['refinements'] = [*base.get('refinements', []), {'region': region, 'addedCount': work['stats']['addedCount']}]
        temporary = directory / "work.partial.json"
        temporary.write_text(json.dumps(work, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        if cancel.exists():
            raise Cancelled()
        temporary.replace(directory / "work.json")
        storage.update(task_id, status="done", progress=1, stage="绘制方案已就绪", stats=work["stats"])
        base_path.unlink(missing_ok=True)
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


def require_task(task_id: str, include_deleted=False) -> dict:
    try:
        storage.task_dir(task_id)
    except ValueError:
        raise HTTPException(404, "找不到这幅作品")
    task = storage.get(task_id)
    if task is None or (task.get('deleted_at') and not include_deleted):
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
        with Image.open(storage.task_dir(task_id) / 'input.png') as source:
            image = Image.new('RGB', source.size, '#f7f4eb')
            image.thumbnail((640, 640))
            image.save(storage.task_dir(task_id) / 'preview.png')
        futures[task_id] = pool.submit(generate_worker, task_id, settings.model_dump(), caps["cuda"])
    return storage.get(task_id)


@app.get("/api/health")
def health():
    return {"ok": True, "name": "绘序成境", "version": "0.1.0"}


@app.get("/api/hardware")
def hardware(refresh: bool = False):
    return capabilities(refresh)


@app.get("/api/tasks")
def list_tasks(trash: bool = False):
    return storage.all_tasks(trash)


@app.post('/api/projects/import')
async def upload_project(file: UploadFile = File(...)):
    content = bytearray()
    while chunk := await file.read(1024 * 1024):
        content.extend(chunk)
        if len(content) > 160 * 1024 * 1024:
            raise HTTPException(413, '工程文件过大，上限为 160 MB')
    try:
        return await asyncio.to_thread(import_project, bytes(content), Settings)
    except (ValueError, OSError, KeyError) as exc:
        raise HTTPException(422, f'无法导入工程：{exc}')


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


def ensure_idle(task_id, task):
    if task['status'] in ('queued', 'running', 'cancelling'):
        raise HTTPException(409, '请先取消生成，等待任务停止后再删除作品')
    if (task.get('export_state') or {}).get('status') in ('queued', 'running'):
        raise HTTPException(409, '请先取消视频导出，等待任务停止后再操作')
    if any(future is not None and not future.done() for future in (futures.get(task_id), export_futures.get(task_id))):
        raise HTTPException(409, '任务仍在收尾，请稍后再操作')


@app.delete("/api/tasks/{task_id}")
def delete_task(task_id: str):
    with submit_lock:
        task = require_task(task_id)
        ensure_idle(task_id, task)
        storage.trash_task(task_id)
        futures.pop(task_id, None)
        export_futures.pop(task_id, None)
    return {'id': task_id, 'deleted': True, 'recoverable': True}


@app.post('/api/tasks/{task_id}/restore')
def restore_task(task_id: str):
    with submit_lock:
        task = require_task(task_id, True)
        storage.restore_task(task_id)
    return require_task(task_id)


@app.delete('/api/tasks/{task_id}/permanent')
def purge_task(task_id: str):
    with submit_lock:
        task = require_task(task_id, True)
        ensure_idle(task_id, task)
        if not task.get('deleted_at'):
            raise HTTPException(409, '请先将作品移入回收站')
        try:
            storage.delete_task(task_id)
        except KeyError:
            raise HTTPException(404, '找不到这幅作品')
        except ValueError as exc:
            raise HTTPException(409, str(exc))
        except OSError:
            raise HTTPException(409, '作品文件被占用或无法删除，请关闭相关文件后重试')
        futures.pop(task_id, None)
        export_futures.pop(task_id, None)
    return {'id': task_id, 'deleted': True}


@app.patch('/api/tasks/{task_id}')
def edit_metadata(task_id: str, metadata: Metadata):
    with submit_lock:
        require_task(task_id)
        title = metadata.title.strip()
        tags = list(dict.fromkeys(tag.strip() for tag in metadata.tags if tag.strip()))
        if not title or any(len(tag) > 24 for tag in tags):
            raise HTTPException(422, '名称不能为空，标签每个最多 24 字')
        storage.update(task_id, title=title, tags=tags)
    return require_task(task_id)


@app.get('/api/tasks/{task_id}/project')
def download_project(task_id: str):
    with submit_lock:
        task = require_task(task_id)
        if task['status'] != 'done':
            raise HTTPException(409, '请先完成笔触生成')
        path = export_project(task)
    return FileResponse(path, media_type='application/zip', filename=task['title'] + '.strokescape')


@app.post('/api/tasks/{task_id}/refine')
def refine_task(task_id: str, options: Refinement):
    with submit_lock:
        parent = require_task(task_id)
        if parent['status'] != 'done':
            raise HTTPException(409, '请先完成作品生成')
        base_path = storage.task_dir(task_id) / 'work.json'
        base = json.loads(base_path.read_text(encoding='utf-8'))
        x, y, w, h = options.region
        if x < 0 or y < 0 or w < 2 or h < 2 or x + w > base['width'] or y + h > base['height']:
            raise HTTPException(422, '请选择画布内至少 2 × 2 像素的区域')
        if len(base['strokes']) + options.budget > 500000:
            raise HTTPException(422, '追加后总笔触不能超过 500,000 笔，请减少追加数量')
        settings = options.settings.model_copy(update={'budget': options.budget, 'maxEdge': max(128, base['width'], base['height'])})
        new_id = uuid.uuid4().hex
        directory = storage.task_dir(new_id)
        directory.mkdir()
        try:
            shutil.copyfile(storage.task_dir(task_id) / 'input.png', directory / 'input.png')
            shutil.copyfile(base_path, directory / 'base.json')
            (directory / 'region.json').write_text(json.dumps(options.region))
            task = queue_task(new_id, (parent['title'][:74] + ' · 精修'), settings)
            storage.update(new_id, tags=parent.get('tags') or [])
            return require_task(new_id)
        except Exception:
            shutil.rmtree(directory)
            raise


@app.get("/api/tasks/{task_id}/source")
def source_image(task_id: str):
    require_task(task_id, True)
    return FileResponse(storage.task_dir(task_id) / "input.png", media_type="image/png")


@app.get('/api/tasks/{task_id}/preview')
def preview_image(task_id: str):
    require_task(task_id)
    path = storage.task_dir(task_id) / 'preview.png'
    if not path.is_file():
        raise HTTPException(404, '预览尚未准备好')
    return FileResponse(path, media_type='image/png', headers={'Cache-Control': 'no-store'})


@app.get("/api/tasks/{task_id}/work")
def work_data(task_id: str):
    task = require_task(task_id)
    if task["status"] != "done":
        raise HTTPException(409, "作品尚未生成完成")
    return FileResponse(storage.task_dir(task_id) / "work.json", media_type="application/json")


@app.post("/api/tasks/{task_id}/cancel")
def cancel_task(task_id: str):
    with submit_lock:
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
    with submit_lock:
        task = require_task(task_id)
        new_id = uuid.uuid4().hex
        directory = storage.task_dir(new_id)
        directory.mkdir(parents=True)
        try:
            shutil.copyfile(storage.task_dir(task_id) / "input.png", directory / "input.png")
            return queue_task(new_id, task["title"], settings)
        except Exception:
            shutil.rmtree(directory)
            raise


@app.get("/api/tasks/{task_id}/html")
def download_html(task_id: str):
    with submit_lock:
        task = require_task(task_id)
        if task["status"] != "done":
            raise HTTPException(409, "作品尚未生成完成")
        path = create_html(task_id)
    return FileResponse(path, media_type="text/html", filename=f"{task['title']} · 绘序成境.html")


@app.post("/api/tasks/{task_id}/video")
def start_video(task_id: str, options: VideoSettings):
    with submit_lock:
        task = require_task(task_id)
        if task["status"] != "done":
            raise HTTPException(409, "请先完成笔触生成")
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
    with submit_lock:
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
