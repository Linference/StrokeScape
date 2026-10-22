"""Capability detection: physical adapters, CUDA compute and actual encode probes."""
from __future__ import annotations

import csv
import importlib.util
import io
import logging
import os
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from .runtime import RESOURCE_ROOT

_cache: dict | None = None
_cache_time = 0.0
_lock = threading.Lock()
logger = logging.getLogger(__name__)


def run(args: list[str], timeout: float = 8) -> subprocess.CompletedProcess:
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    return subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout, **options)


def ffmpeg_path() -> str | None:
    configured = os.environ.get("HUIXU_FFMPEG")
    if configured and os.path.isfile(configured):
        return configured
    bundled = RESOURCE_ROOT / "bin" / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    return str(bundled) if bundled.is_file() else shutil.which("ffmpeg")


def windows_adapters() -> list[dict]:
    adapters = []
    if os.name != "nt":
        return adapters
    try:
        import winreg
        path = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as root:
            for index in range(winreg.QueryInfoKey(root)[0]):
                child = winreg.EnumKey(root, index)
                if not child.isdigit():
                    continue
                try:
                    with winreg.OpenKey(root, child) as key:
                        name = winreg.QueryValueEx(key, "DriverDesc")[0]
                        try:
                            ram = winreg.QueryValueEx(key, "HardwareInformation.qwMemorySize")[0]
                            if isinstance(ram, bytes):
                                ram = int.from_bytes(ram, "little")
                        except OSError:
                            ram = None
                        adapters.append({"name": name, "memoryMb": round(ram / 2**20) if ram else None})
                except OSError:
                    continue
    except OSError:
        pass
    return adapters


def detect_cuda() -> dict:
    info = {"available": False, "name": None, "freeMb": None, "totalMb": None,
            "reason": "未安装可选的 CuPy 加速组件"}
    try:
        if importlib.util.find_spec("cupy") is None:
            return info
        import cupy as cp
        if not cp.is_available():
            info["reason"] = "CUDA 设备或驱动不可用"
            return info
        best = None
        for device in range(cp.cuda.runtime.getDeviceCount()):
            with cp.cuda.Device(device):
                free, total = cp.cuda.runtime.memGetInfo()
                if best is None or free > best[1]:
                    best = (device, free, total)
        device, free, total = best
        with cp.cuda.Device(device):
            sample = cp.arange(64, dtype=cp.float32)
            if float(cp.sum(sample).get()) != 2016:
                raise RuntimeError("GPU 计算自检未通过")
            props = cp.cuda.runtime.getDeviceProperties(device)
            name = props["name"]
            info.update(available=True, device=device,
                        name=name.decode() if isinstance(name, bytes) else str(name),
                        freeMb=round(free / 2**20), totalMb=round(total / 2**20), reason=None)
    except Exception as exc:
        detail = str(exc).strip() or repr(exc)
        info["errorType"] = type(exc).__name__
        info["errorDetail"] = detail[:3000]
        lowered = detail.lower()
        if any(token in lowered for token in ("dll", "nvrtc", "not found", "cannot load", "failed to load")):
            info["reason"] = "CUDA 运行组件加载失败"
            info["hint"] = "如刚安装过 CuPy 或 CUDA 组件，请完整重启软件；仍失败时根据下方详细错误检查缺失组件。"
        elif "driver" in lowered:
            info["reason"] = "CUDA 驱动初始化失败"
            info["hint"] = "检查 NVIDIA 驱动与当前 CUDA 运行环境的兼容性。"
        elif "memory" in lowered:
            info["reason"] = "GPU 显存分配失败"
            info["hint"] = "关闭占用显存的程序后重新检测。"
        else:
            info["reason"] = "CUDA 计算自检未通过"
            info["hint"] = "如果刚安装过加速组件，请完整重启软件；详细错误可用于定位具体原因。"
        logger.warning("CUDA self-test failed: %s: %s", type(exc).__name__, detail)
    return info


def probe_encoder(executable: str, encoder: str) -> bool:
    try:
        proc = run([executable, "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                    "-i", "color=c=white:s=128x128:r=24", "-frames:v", "1", "-an",
                    "-c:v", encoder, "-pix_fmt", "yuv420p", "-f", "null", "-"], timeout=10)
        return proc.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def capabilities(refresh: bool = False) -> dict:
    global _cache, _cache_time
    with _lock:
        if _cache is not None and not refresh and time.monotonic() - _cache_time < 120:
            return _cache
        adapters = windows_adapters()
        smi = shutil.which("nvidia-smi")
        if smi:
            try:
                proc = run([smi, "--query-gpu=name,memory.total,memory.free,driver_version",
                            "--format=csv,noheader,nounits"], timeout=5)
                if proc.returncode == 0:
                    names = {item["name"] for item in adapters}
                    for row in csv.reader(io.StringIO(proc.stdout)):
                        if len(row) >= 4 and row[0].strip() not in names:
                            adapters.append({"name": row[0].strip(), "memoryMb": int(row[1]),
                                             "freeMb": int(row[2]), "driver": row[3].strip()})
            except (ValueError, OSError, subprocess.TimeoutExpired):
                pass
        cuda = detect_cuda()
        executable = ffmpeg_path()
        candidates = ["h264_nvenc", "h264_qsv", "h264_amf", "libx264", "libopenh264", "h264_mf", "mpeg4"]
        encoders = []
        if executable:
            with ThreadPoolExecutor(max_workers=4) as executor:
                results = list(executor.map(lambda name: probe_encoder(executable, name), candidates))
            encoders = [name for name, usable in zip(candidates, results) if usable]
        _cache = {"adapters": adapters, "cuda": cuda,
                  "cpu": os.cpu_count() or 1, "ffmpeg": bool(executable),
                  "encoders": encoders, "preferredEncoder": encoders[0] if encoders else None,
                  "platform": "Windows" if os.name == "nt" else os.name}
        _cache_time = time.monotonic()
        return _cache
