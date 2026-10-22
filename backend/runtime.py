"""Locate read-only app resources separately from writable user works."""
from __future__ import annotations

import os
import sys
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))
RESOURCE_ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1])).resolve()
APP_HOME = Path(sys.executable).resolve().parent if FROZEN else RESOURCE_ROOT
VERSION = "0.1.0"


def default_data_dir() -> Path:
    configured = os.environ.get("HUIXU_DATA")
    if configured:
        return Path(configured).expanduser().resolve()
    if not FROZEN:
        return APP_HOME / "data"
    return APP_HOME / "UserData"


def bundled_browser() -> Path | None:
    folder = RESOURCE_ROOT / "browser"
    for candidate in (folder / "chrome-win64" / "chrome.exe", folder / "chrome-win" / "chrome.exe"):
        if candidate.is_file():
            return candidate
    return None
