"""Deterministic structure-guided painter with local residual feedback.

GPU acceleration is deliberately limited to dense feature extraction; stroke
selection/raster updates stay on CPU. The renderer's canonical output is Canvas.
"""
from __future__ import annotations

import math
import time
from pathlib import Path
from typing import Callable

import cv2
import numpy as np
from PIL import Image, ImageOps

PAPER = [247, 244, 235]
PRESETS = {"sketch": 18000, "standard": 60000, "fine": 150000}
PRESET_EDGES = {"sketch": 960, "standard": 1440, "fine": 1920}
LAYERS = ["铺底", "塑形", "勾线", "细节"]


class Cancelled(Exception):
    pass


def load_image(path: str | Path, max_edge: int = 960) -> np.ndarray:
    with Image.open(path) as original:
        image = ImageOps.exif_transpose(original).convert("RGBA")
        image.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
        background = Image.new("RGBA", image.size, tuple(PAPER) + (255,))
        return np.asarray(Image.alpha_composite(background, image).convert("RGB")).copy()


def cpu_features(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32) / 255
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    xx = cv2.GaussianBlur(gx * gx, (0, 0), 2)
    yy = cv2.GaussianBlur(gy * gy, (0, 0), 2)
    xy = cv2.GaussianBlur(gx * gy, (0, 0), 2)
    direction = 0.5 * np.arctan2(2 * xy, xx - yy) + math.pi / 2
    edge = np.sqrt(gx * gx + gy * gy)
    coherence = np.sqrt((xx - yy) ** 2 + 4 * xy ** 2) / (xx + yy + 1e-6)
    return direction, edge, coherence


def features(rgb: np.ndarray, mode: str, cuda: dict) -> tuple:
    # Host/device transfers dominate tiny images. The threshold is a heuristic,
    # not a claim of measured speedup.
    use_gpu = cuda.get("available") and (mode == "gpu" or (mode == "auto" and rgb.shape[0] * rgb.shape[1] >= 300_000))
    reason = None
    if use_gpu:
        try:
            import cupy as cp
            from cupyx.scipy.ndimage import gaussian_filter, sobel
            with cp.cuda.Device(cuda.get("device", 0)):
                image = cp.asarray(rgb, dtype=cp.float32) / 255
                gray = image[..., 0] * 0.299 + image[..., 1] * 0.587 + image[..., 2] * 0.114
                gx, gy = sobel(gray, axis=1, mode="mirror"), sobel(gray, axis=0, mode="mirror")
                xx, yy, xy = [gaussian_filter(v, 2, mode="mirror") for v in (gx * gx, gy * gy, gx * gy)]
                direction = 0.5 * cp.arctan2(2 * xy, xx - yy) + math.pi / 2
                edge = cp.sqrt(gx * gx + gy * gy)
                coherence = cp.sqrt((xx - yy) ** 2 + 4 * xy ** 2) / (xx + yy + 1e-6)
                result = tuple(cp.asnumpy(v) for v in (direction, edge, coherence))
                cp.get_default_memory_pool().free_all_blocks()
                return (*result, "cuda", None)
        except Exception as exc:
            detail = str(exc).strip() or type(exc).__name__
            reason = f"GPU 特征计算失败，已回退 CPU：{detail[:500]}"
    elif mode != "cpu":
        reason = cuda.get("reason") if not cuda.get("available") else "当前图像较小，自动选择 CPU"
    return (*cpu_features(rgb), "cpu", reason)


def draw_local(canvas: np.ndarray, points: list[float], color: list[int], width: float, opacity: float):
    pts = np.array(points, dtype=np.float32).reshape(-1, 2)
    height, image_width = canvas.shape[:2]
    pad = math.ceil(width) + 2
    x0 = max(0, int(pts[:, 0].min()) - pad)
    y0 = max(0, int(pts[:, 1].min()) - pad)
    x1 = min(image_width, int(pts[:, 0].max()) + pad + 1)
    y1 = min(height, int(pts[:, 1].max()) + pad + 1)
    if x1 <= x0 or y1 <= y0:
        return
    roi = canvas[y0:y1, x0:x1]
    paint = roi.copy()
    local = np.round(pts - [x0, y0]).astype(np.int32)
    thick = max(1, round(width))
    cv2.polylines(paint, [local], False, color, thick, cv2.LINE_AA)
    for p in (local[0], local[-1]):
        cv2.circle(paint, tuple(p), max(1, thick // 2), color, -1, cv2.LINE_AA)
    cv2.addWeighted(paint, opacity, roi, 1 - opacity, 0, dst=roi)
    return x0, y0, x1, y1


def schedule(strokes: list[dict], duration_ms: float) -> list[int]:
    """Strict serial timing; weights reflect length and layer importance."""
    weights = []
    for stroke in strokes:
        points = stroke["p"]
        length = sum(math.hypot(points[i] - points[i - 2], points[i + 1] - points[i - 1])
                     for i in range(2, len(points), 2))
        weights.append((length ** 0.55 + 1.5) * (1.35 if stroke["l"] == 2 else 1))
    # Allocate cumulative integer ticks to avoid accumulated duration rounding at
    # 150k+ strokes. One tick is 0.0001 milliseconds.
    total_ticks = round(duration_ms * 10000)
    available_ticks = total_ticks - 200 * 3 * 10000
    drawn_ticks = 0
    gap_ticks = 0
    cumulative = 0.0
    previous = 0
    counts = [0, 0, 0, 0]
    weight_sum = max(sum(weights), 1)
    for index, (stroke, weight) in enumerate(zip(strokes, weights)):
        if stroke["l"] != previous:
            gap_ticks += 200 * 10000
            previous = stroke["l"]
        cumulative += weight
        end_ticks = available_ticks if index == len(strokes) - 1 else round(available_ticks * cumulative / weight_sum)
        stroke["s"] = (drawn_ticks + gap_ticks) / 10000
        stroke["dt"] = (end_ticks - drawn_ticks) / 10000
        drawn_ticks = end_ticks
        counts[stroke["l"]] += 1
    return counts


def paint(path: str | Path, settings: dict, cuda: dict,
          progress: Callable[[float, str], None], cancelled: Callable[[], bool]) -> dict:
    started = time.perf_counter()
    max_edge = settings.get("maxEdge") or PRESET_EDGES[settings["preset"]]
    rgb = load_image(path, max_edge)
    height, width = rgb.shape[:2]
    short = min(height, width)
    progress(0.03, "分析颜色、轮廓与结构方向")
    direction, edge, coherence, backend, fallback = features(rgb, settings["device"], cuda)
    analysis_seconds = time.perf_counter() - started
    edge = edge / max(float(np.percentile(edge, 98)), 0.01)
    edge = np.clip(edge, 0, 1)
    rng = np.random.default_rng(settings.get("seed", 42))
    canvas = np.full_like(rgb, PAPER)
    budget = int(settings.get("budget") or PRESETS[settings["preset"]])
    # Additional budget primarily serves detail, rather than repeatedly laying
    # down thousands of unnecessary broad base strokes.
    coarse_budget = min(budget, 30000)
    counts = [round(coarse_budget * v) for v in (0.08, 0.20, 0.12)]
    counts.append(budget - sum(counts))
    strokes = []
    density = max(1.0, budget / 18000)
    sigmas = [max(0.6, short * scale) for scale in (0.016, 0.006, 0.001)]
    sigmas.append(max(0.35, short * 0.001 / math.sqrt(density)))
    blurred = [cv2.GaussianBlur(rgb, (0, 0), sigma) for sigma in sigmas]
    painting_started = time.perf_counter()
    last_progress = 0
    for layer, count in enumerate(counts):
        source = blurred[layer]
        source_float = source.astype(np.float32)
        brush = max(1, short * (0.070, 0.027, 0.004, 0.009)[layer])
        base_length = short * (0.16, 0.075, 0.035, 0.025)[layer]
        importance = 0.65 + edge * (2.2 if layer == 2 else 0.9)
        if layer == 2:
            importance *= 0.06 + edge
        scores = (np.mean(np.abs(source_float - canvas), axis=2) + 3) * importance
        scores_flat = scores.reshape(-1)
        for index in range(count):
            if index % 64 == 0 and cancelled():
                raise Cancelled()
            choices = rng.integers(0, width * height, size=14 if layer > 0 else 5)
            selected = int(choices[np.argmax(scores_flat[choices] * rng.uniform(0.65, 1.25, len(choices)))])
            y, x = divmod(selected, width)
            # Follow the structure tensor's tangent in both directions.
            angle = float(direction[y, x])
            if coherence[y, x] < 0.12:
                angle = float(rng.uniform(0, math.pi))
            length = max(2, base_length * rng.uniform(0.55, 1.35))
            stroke_width = max(0.7, brush * rng.uniform(0.65, 1.2))
            if layer == 3:
                refinement = density ** -0.32 * (1 - 0.45 * index / max(count, 1))
                stroke_width = max(0.6, stroke_width * refinement)
                length = max(1.5, length * refinement)
            halves = []
            for sign in (-1, 1):
                px, py = float(x), float(y)
                previous_angle = angle
                segment = [[px, py]]
                for _ in range(3):
                    local_angle = float(direction[int(py), int(px)])
                    if math.cos(local_angle - previous_angle) < 0:
                        local_angle += math.pi
                    local_angle = previous_angle + 0.35 * math.atan2(math.sin(local_angle - previous_angle), math.cos(local_angle - previous_angle))
                    nx = min(float(width - 1), max(0.0, px + sign * math.cos(local_angle) * length / 6))
                    ny = min(float(height - 1), max(0.0, py + sign * math.sin(local_angle) * length / 6))
                    if math.hypot(nx - px, ny - py) < 0.1:
                        break
                    segment.append([nx, ny])
                    px, py, previous_angle = nx, ny, local_angle
                halves.append(segment)
            points = list(reversed(halves[0])) + halves[1][1:]
            if len(points) < 2:
                points = [[float(x), float(y)], [float(min(width - 1, x + 1)), float(min(height - 1, y + 1))]]
            flat = [round(v, 2) for point in points for v in point]
            color = [int(v) for v in source[y, x]]
            opacity = (0.90, 0.91, 0.79, 0.96)[layer]
            bounds = draw_local(canvas, flat, color, stroke_width, opacity)
            if bounds:
                x0, y0, x1, y1 = bounds
                # Only this region changed. Updating its residual after every
                # stroke is exact for the CPU feedback canvas and avoids repeated
                # full-image scans as stroke budgets grow.
                local_error = np.mean(np.abs(source_float[y0:y1, x0:x1] - canvas[y0:y1, x0:x1]), axis=2)
                scores[y0:y1, x0:x1] = (local_error + 3) * importance[y0:y1, x0:x1]
            strokes.append({"p": flat, "c": "#" + "".join(f"{v:02x}" for v in color),
                            "w": round(stroke_width, 2), "o": opacity, "l": layer})
            done = len(strokes)
            if done - last_progress >= 128:
                progress(0.06 + 0.89 * done / budget, f"{LAYERS[layer]} · {done:,} / {budget:,} 笔")
                last_progress = done
    if cancelled():
        raise Cancelled()
    painting_seconds = time.perf_counter() - painting_started
    progress(0.97, "编排逐笔时间轴")
    layer_counts = schedule(strokes, settings["duration"] * 1000)
    return {"version": 1, "width": width, "height": height, "paper": "#f7f4eb",
            "durationMs": round(strokes[-1]["s"] + strokes[-1]["dt"], 4),
            "strokes": strokes, "layers": layer_counts, "settings": {**settings, "budget": budget, "maxEdge": max_edge},
            "stats": {"count": len(strokes), "computeSeconds": round(time.perf_counter() - started, 2),
                      "analysisSeconds": round(analysis_seconds, 4), "paintingSeconds": round(painting_seconds, 4),
                      "workingMaxEdge": max_edge,
                      "backend": backend, "gpuScope": "图像结构分析" if backend == "cuda" else None,
                      "fallback": fallback, "seed": settings.get("seed", 42)}}
