from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from app.db import execute, fetchall, fetchone, now_iso

PLATFORMS = {"tiktok", "instagram", "youtube", "facebook", "kwai"}
STATUSES = {"draft", "scheduled", "ready", "published", "error"}


def _owned_clip(user_id: int, clip_id: str) -> bool:
    return bool(fetchone("SELECT 1 FROM clips c JOIN projects p ON p.id=c.project_id WHERE c.id=? AND p.user_id=?", (clip_id, user_id)))


def _decorate(row) -> dict[str, Any] | None:
    if not row:
        return None
    item = dict(row)
    export_path = str(item.get("export_path") or "")
    item["export_path"] = export_path or None
    item["export_ready"] = bool(export_path and Path(export_path).is_file())
    return item


def get_item(user_id: int, item_id: str) -> dict[str, Any] | None:
    row = fetchone("SELECT q.*,c.title,c.video_path export_path,p.title project_title FROM publish_queue q JOIN clips c ON c.id=q.clip_id JOIN projects p ON p.id=c.project_id WHERE q.id=? AND q.user_id=?", (item_id, user_id))
    return _decorate(row)


def enqueue(user_id: int, clip_id: str, *, platform: str, scheduled_at: str | None = None, caption: str = "") -> dict[str, Any]:
    if not _owned_clip(user_id, clip_id):
        raise ValueError("clip_not_found")
    platform = str(platform or "").lower().strip()
    if platform not in PLATFORMS:
        raise ValueError("platform_invalid")
    item_id = uuid.uuid4().hex[:20]
    status = "scheduled" if scheduled_at else "draft"
    now = now_iso()
    execute("INSERT INTO publish_queue(id,user_id,clip_id,platform,status,scheduled_at,caption,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (item_id, user_id, clip_id, platform, status, scheduled_at or None, caption or "", now, now))
    return get_item(user_id, item_id) or {}


def list_items(user_id: int, status: str | None = None) -> list[dict[str, Any]]:
    if status in STATUSES:
        rows = fetchall("SELECT q.*,c.title,c.video_path export_path,p.title project_title FROM publish_queue q JOIN clips c ON c.id=q.clip_id JOIN projects p ON p.id=c.project_id WHERE q.user_id=? AND q.status=? ORDER BY COALESCE(q.scheduled_at,q.created_at),q.created_at", (user_id, status))
    else:
        rows = fetchall("SELECT q.*,c.title,c.video_path export_path,p.title project_title FROM publish_queue q JOIN clips c ON c.id=q.clip_id JOIN projects p ON p.id=c.project_id WHERE q.user_id=? ORDER BY COALESCE(q.scheduled_at,q.created_at),q.created_at", (user_id,))
    return [_decorate(r) for r in rows]


def update_status(user_id: int, item_id: str, status: str, *, external_url: str | None = None, error_message: str | None = None) -> dict[str, Any] | None:
    if status not in STATUSES:
        raise ValueError("status_invalid")
    if not get_item(user_id, item_id):
        return None
    execute("UPDATE publish_queue SET status=?,external_url=?,error_message=?,updated_at=? WHERE id=? AND user_id=?",
            (status, external_url, error_message, now_iso(), item_id, user_id))
    return get_item(user_id, item_id)
