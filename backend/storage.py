from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from .runtime import RESOURCE_ROOT, default_data_dir

ROOT = RESOURCE_ROOT
DATA = default_data_dir()


def init():
    DATA.mkdir(parents=True, exist_ok=True)
    with connect() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at TEXT NOT NULL,
            status TEXT NOT NULL, progress REAL DEFAULT 0, stage TEXT DEFAULT '',
            settings TEXT NOT NULL, stats TEXT, error TEXT,
            export_state TEXT DEFAULT '{}'
        )""")
        db.execute("UPDATE tasks SET status='interrupted', stage='上次任务被中断，可重新生成' WHERE status IN ('queued','running','cancelling')")
        rows = db.execute("SELECT id, export_state FROM tasks").fetchall()
        for row in rows:
            state = json.loads(row["export_state"] or "{}")
            if state.get("status") in ("queued", "running"):
                db.execute("UPDATE tasks SET export_state=? WHERE id=?",
                           (json.dumps({"status": "failed", "error": "导出被中断，请重试"}, ensure_ascii=False), row["id"]))


def connect():
    db = sqlite3.connect(DATA / "studio.sqlite3", timeout=20)
    db.row_factory = sqlite3.Row
    return db


def task_dir(task_id: str) -> Path:
    # Only internal UUIDs may address storage.
    if len(task_id) != 32 or any(c not in "0123456789abcdef" for c in task_id):
        raise ValueError("无效的作品编号")
    return DATA / task_id


def create(task_id: str, title: str, settings: dict):
    with connect() as db:
        db.execute("INSERT INTO tasks(id,title,created_at,status,settings,stage) VALUES(?,?,?,?,?,?)",
                   (task_id, title, datetime.now(timezone.utc).isoformat(), "queued",
                    json.dumps(settings, ensure_ascii=False), "等待生成"))


def update(task_id: str, **fields):
    allowed = {"status", "progress", "stage", "stats", "error", "export_state", "title"}
    if not fields or not set(fields) <= allowed:
        raise ValueError("无效字段")
    fields = {key: json.dumps(value, ensure_ascii=False) if isinstance(value, dict) else value for key, value in fields.items()}
    with connect() as db:
        db.execute("UPDATE tasks SET " + ",".join(f"{key}=?" for key in fields) + " WHERE id=?",
                   [*fields.values(), task_id])


def decode(row):
    if row is None:
        return None
    result = dict(row)
    for key in ("settings", "stats", "export_state"):
        result[key] = json.loads(result[key]) if result[key] else None
    return result


def get(task_id: str):
    with connect() as db:
        return decode(db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone())


def all_tasks():
    with connect() as db:
        return [decode(row) for row in db.execute("SELECT * FROM tasks ORDER BY created_at DESC LIMIT 100")]
