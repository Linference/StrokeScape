"""Portable, validated project archives; never extract arbitrary ZIP paths."""
from __future__ import annotations

import io
import hashlib
import json
import math
import re
import shutil
import uuid
import zipfile

from PIL import Image, ImageOps

from . import storage
from .brushes import BRUSHES

HEX = re.compile(r'^#[0-9a-fA-F]{6}$')
MAX_BYTES = 160 * 1024 * 1024


def validate_work(work, settings_model):
    if not isinstance(work, dict) or work.get('version') != 1:
        raise ValueError('不支持的工程版本')
    width, height = work.get('width'), work.get('height')
    if any(type(v) is not int or not 1 <= v <= 2560 for v in (width, height)):
        raise ValueError('画布尺寸无效')
    settings = settings_model.model_validate(work.get('settings', {})).model_dump()
    strokes = work.get('strokes')
    if not isinstance(strokes, list) or not 1 <= len(strokes) <= 500000:
        raise ValueError('笔触数量应为 1–500,000')
    if not HEX.fullmatch(str(work.get('paper', ''))):
        raise ValueError('画布颜色无效')
    duration = work.get('durationMs')
    if type(duration) not in (float, int) or not math.isfinite(duration) or not 1 <= duration <= 600000:
        raise ValueError('时间轴无效')
    end, previous_layer, layers, cleaned = 0, 0, [0, 0, 0, 0], []
    for stroke in strokes:
        if not isinstance(stroke, dict):
            raise ValueError('笔触格式无效')
        points = stroke.get('p')
        if not isinstance(points, list) or not 4 <= len(points) <= 64 or len(points) % 2:
            raise ValueError('笔触路径无效')
        if any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= (width if i % 2 == 0 else height)
               for i, v in enumerate(points)):
            raise ValueError('笔触坐标无效')
        for key, low, high in [('w', .01, 7680), ('o', 0, 1), ('s', 0, duration), ('dt', 1e-8, duration), ('tx', 0, 2), ('g', 0, 2)]:
            value = stroke.get(key, 1 if key in ('tx', 'g') else None)
            if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
                raise ValueError('笔触参数无效')
        if stroke['s'] < end - 1e-6 or stroke['s'] + stroke['dt'] > duration + 1e-6:
            raise ValueError('时间轴必须严格串行')
        end = stroke['s'] + stroke['dt']
        layer = stroke.get('l')
        if type(layer) is not int or not 0 <= layer <= 3 or not HEX.fullmatch(str(stroke.get('c', ''))):
            raise ValueError('笔触图层或颜色无效')
        if layer < previous_layer:
            raise ValueError('绘制图层必须从铺底到细节递进')
        previous_layer = layer
        if stroke.get('b', settings['brush']) not in BRUSHES:
            raise ValueError('笔刷无效')
        seed = stroke.get('seed', settings['seed'])
        if type(seed) is not int or not 0 <= seed <= 2**32 - 1:
            raise ValueError('笔触种子无效')
        clip = stroke.get('clip')
        if clip is not None:
            if not isinstance(clip, list) or len(clip) != 4 or any(type(v) is not int for v in clip):
                raise ValueError('选区无效')
            x, y, w, h = clip
            if min(x, y) < 0 or min(w, h) < 1 or x + w > width or y + h > height:
                raise ValueError('选区超出画布')
        cleaned.append({k: v for k, v in stroke.items() if k in ('p', 'c', 'w', 'o', 'l', 's', 'dt', 'b', 'seed', 'tx', 'g', 'clip')})
        layers[layer] += 1
    if abs(end - duration) > .001:
        raise ValueError('时间轴末帧不完整')
    stats = work.get('stats') or {}
    safe_stats = {key: stats[key] for key in ('computeSeconds', 'analysisSeconds', 'paintingSeconds', 'mae', 'psnr', 'meanJump')
                  if type(stats.get(key)) in (float, int) and math.isfinite(stats[key]) and stats[key] >= 0}
    safe_stats.update(count=len(strokes), backend='imported', seed=settings['seed'])
    safe_stats.setdefault('computeSeconds', 0)
    return dict(version=1, width=width, height=height, paper=work['paper'], durationMs=duration,
                strokes=cleaned, layers=layers, settings=settings, stats=safe_stats)


def export_project(task):
    directory = storage.task_dir(task['id'])
    manifest = {'format': 'StrokeScape', 'version': 1, 'title': task['title'], 'tags': task.get('tags') or []}
    manifest_text = json.dumps(manifest, ensure_ascii=False)
    work_stat = (directory / 'work.json').stat()
    revision = hashlib.sha256((manifest_text + f'{work_stat.st_mtime_ns}:{work_stat.st_size}').encode()).hexdigest()[:20]
    target, partial = directory / f'project-{revision}.strokescape', directory / f'project-{revision}.partial'
    # Downloads may still hold a Windows read handle. Reuse immutable archives
    # instead of replacing an open file; metadata changes get a new revision.
    if target.is_file():
        return target
    with zipfile.ZipFile(partial, 'w', zipfile.ZIP_DEFLATED, compresslevel=3) as archive:
        archive.writestr('manifest.json', manifest_text)
        archive.write(directory / 'input.png', 'input.png')
        archive.write(directory / 'work.json', 'work.json')
    partial.replace(target)
    return target


def import_project(content, settings_model):
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            names = archive.namelist()
            if len(names) != 3 or set(names) != {'manifest.json', 'input.png', 'work.json'}:
                raise ValueError('工程必须且只能包含清单、原图和笔触数据')
            if sum(item.file_size for item in archive.infolist()) > MAX_BYTES:
                raise ValueError('解压数据超过 160 MB 上限')
            if archive.getinfo('manifest.json').file_size > 16384 or archive.getinfo('input.png').file_size > 32 * 1024 * 1024:
                raise ValueError('清单或原图过大')
            manifest = json.loads(archive.read('manifest.json'))
            if manifest.get('format') != 'StrokeScape' or manifest.get('version') != 1:
                raise ValueError('不是受支持的 StrokeScape 工程')
            title, tags = manifest.get('title'), manifest.get('tags', [])
            if not isinstance(title, str) or not title.strip() or len(title) > 80:
                raise ValueError('作品名称无效')
            if not isinstance(tags, list) or len(tags) > 12 or any(not isinstance(t, str) or len(t) > 24 for t in tags):
                raise ValueError('作品标签无效')
            work = validate_work(json.loads(archive.read('work.json')), settings_model)
            source = archive.read('input.png')
            with Image.open(io.BytesIO(source)) as image:
                if image.width * image.height > 24_000_000:
                    raise ValueError('原图像素过多')
                image.load()
                image = ImageOps.exif_transpose(image)
                normalized = io.BytesIO()
                image.convert('RGBA').save(normalized, 'PNG')
                source = normalized.getvalue()
                image.thumbnail((max(work['width'], work['height']),) * 2)
                if image.size != (work['width'], work['height']):
                    raise ValueError('原图与画布比例不匹配')
    except (zipfile.BadZipFile, json.JSONDecodeError, TypeError, AttributeError, RuntimeError, Image.DecompressionBombError) as exc:
        raise ValueError('工程文件损坏或格式错误') from exc
    task_id = uuid.uuid4().hex
    directory = storage.task_dir(task_id)
    directory.mkdir()
    try:
        (directory / 'input.png').write_bytes(source)
        (directory / 'work.json').write_text(json.dumps(work, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
        storage.create(task_id, title.strip(), work['settings'])
        storage.update(task_id, status='done', stage='已导入工程', progress=1, stats=work['stats'], tags=tags)
    except Exception:
        shutil.rmtree(directory)
        raise
    return storage.get(task_id)
