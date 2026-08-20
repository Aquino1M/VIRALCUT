from __future__ import annotations

import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from app.config import OUTPUT_DIR
from app.db import execute, fetchall, fetchone, now_iso
from . import editor as editor_service
from . import preview as preview_service
from . import face_tracking
from .render import generate_thumbnail, render_edited_clip
from . import timeline as timeline_service
from .timeline_render import render_timeline_clip

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="viralclip-render")


def recover_interrupted_renders() -> int:
    """Mark volatile render jobs as retryable after the process restarts."""
    rows = fetchall("SELECT id FROM clip_renders WHERE status IN ('queued','rendering')")
    for row in rows:
        execute(
            "UPDATE clip_renders SET status='error',progress=100,error_message=?,updated_at=? WHERE id=?",
            ("Render interrompido ao fechar o ViralClip. Renderize novamente.", now_iso(), row["id"]),
        )
    return len(rows)


def create_render_record(clip_id: str, kind: str, settings_hash: str | None = None, editor_revision: int | None = None, snapshot: dict[str, Any] | None = None) -> str:
    if kind not in {"preview", "project_preview", "final"}:
        raise ValueError("kind inválido")
    render_id = uuid.uuid4().hex[:20]
    now = now_iso()
    execute(
        "INSERT INTO clip_renders(id,clip_id,kind,status,progress,settings_hash,editor_revision,snapshot_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (render_id, clip_id, kind, "queued", 0, settings_hash, editor_revision, json.dumps(snapshot, ensure_ascii=False) if snapshot is not None else None, now, now),
    )
    return render_id


def get_render_record(render_id: str) -> dict[str, Any] | None:
    row = fetchone("SELECT * FROM clip_renders WHERE id=?", (render_id,))
    return dict(row) if row else None


def update_render_record(render_id: str, **fields: Any) -> None:
    allowed = {"status", "progress", "settings_hash", "video_path", "error_message", "encoder", "resolution", "file_size", "render_seconds"}
    sets = []
    params = []
    for key, value in fields.items():
        if key not in allowed:
            continue
        sets.append(f"{key}=?")
        params.append(value)
    sets.append("updated_at=?")
    params.append(now_iso())
    params.append(render_id)
    execute(f"UPDATE clip_renders SET {', '.join(sets)} WHERE id=?", params)


def enqueue_clip_render(clip_id: str, kind: str, *, preview_offset: float = 0.0, editor_revision: int | None = None) -> str:
    state = editor_service.get_or_create_edit_state(clip_id)
    current_revision = int(state.get("revision") or 1)
    if editor_revision is not None and int(editor_revision) != current_revision:
        raise ValueError("editor_revision_stale")
    editor_revision = current_revision
    timeline_data = timeline_service.get_or_create_timeline(clip_id)
    cues_snapshot = editor_service.list_caption_cues(clip_id)
    immutable_snapshot = {"editor": state, "timeline": timeline_data, "cues": cues_snapshot}
    cache_state = {"editor": state, "timeline": timeline_data}
    state_hash = preview_service.settings_hash(cache_state)
    existing = fetchone(
        "SELECT id FROM clip_renders WHERE clip_id=? AND kind=? AND status IN ('queued','rendering') AND settings_hash=? AND editor_revision=? ORDER BY created_at DESC LIMIT 1",
        (clip_id, kind, state_hash, editor_revision),
    )
    if existing:
        return str(existing["id"])
    if kind == "final":
        cached_final = fetchone(
            "SELECT * FROM clip_renders WHERE clip_id=? AND kind='final' AND status='done' AND settings_hash=? AND editor_revision=? ORDER BY created_at DESC LIMIT 1",
            (clip_id, state_hash, editor_revision),
        )
        if cached_final and cached_final["video_path"] and Path(cached_final["video_path"]).exists():
            execute(
                "UPDATE clips SET video_path=?,render_status='rendered',render_encoder=?,render_seconds=?,file_size=?,updated_at=? WHERE id=?",
                (cached_final["video_path"], cached_final["encoder"], cached_final["render_seconds"], cached_final["file_size"], now_iso(), clip_id),
            )
            return str(cached_final["id"])
    if kind in {"preview", "project_preview"}:
        cached = preview_service.cached_project_preview(clip_id, cache_state) if kind == "project_preview" else preview_service.cached_preview(clip_id, cache_state)
        if cached:
            rid = create_render_record(clip_id, kind, state_hash, editor_revision, immutable_snapshot)
            update_render_record(rid, status="done", progress=100, video_path=str(cached), resolution="540x960", file_size=cached.stat().st_size)
            if kind == "project_preview":
                execute("UPDATE clips SET preview_path=?,render_status='preview',updated_at=? WHERE id=?", (str(cached), now_iso(), clip_id))
            return rid
    rid = create_render_record(clip_id, kind, state_hash, editor_revision, immutable_snapshot)
    _executor.submit(_render_worker, rid, preview_offset)
    return rid


def _render_worker(render_id: str, preview_offset: float) -> None:
    record = get_render_record(render_id)
    if not record or record.get("status") != "queued":
        return
    clip = fetchone(
        "SELECT c.*,p.source_path,p.transcript_path,p.settings_json,p.tracking_path FROM clips c JOIN projects p ON p.id=c.project_id WHERE c.id=?",
        (record["clip_id"],),
    )
    if not clip:
        update_render_record(render_id, status="error", progress=100, error_message="Corte não encontrado")
        return
    if not clip["source_path"] or not Path(clip["source_path"]).exists():
        update_render_record(render_id, status="error", progress=100, error_message="Fonte local indisponível")
        return

    try:
        immutable = json.loads(record.get("snapshot_json") or "{}") if isinstance(record, dict) else {}
    except Exception:
        immutable = {}
    state = immutable.get("editor") or editor_service.get_or_create_edit_state(clip["id"])
    record_revision = int(record.get("editor_revision") or state.get("revision") or 1)
    if record_revision != int(editor_service.get_or_create_edit_state(clip["id"]).get("revision") or 1):
        update_render_record(render_id, status="error", progress=100, error_message="Edição substituída por uma revisão mais nova.")
        return
    timeline_data = immutable.get("timeline") or timeline_service.get_or_create_timeline(clip["id"])
    try:
        project_settings = json.loads(clip["settings_json"] or "{}")
    except Exception:
        project_settings = {}
    state.setdefault("aspect_ratio", project_settings.get("aspect_ratio") or "9:16")
    tracking_data = face_tracking.load_tracks(clip["tracking_path"]) if clip["tracking_path"] else face_tracking.empty_tracking("Tracking não disponível")
    clip_tracking = face_tracking.slice_tracks(tracking_data, float(clip["start_time"]), float(clip["end_time"]))
    cues = immutable.get("cues") if isinstance(immutable, dict) and "cues" in immutable else editor_service.list_caption_cues(clip["id"])
    transcript = None
    if not cues and clip["transcript_path"] and Path(clip["transcript_path"]).exists():
        try:
            transcript = json.loads(Path(clip["transcript_path"]).read_text(encoding="utf-8"))
        except Exception:
            transcript = None

    is_short_preview = record["kind"] == "preview"
    is_project_preview = record["kind"] == "project_preview"
    is_preview = is_short_preview or is_project_preview
    if is_project_preview:
        out_path = preview_service.project_preview_path(clip["id"], {"editor": state, "timeline": timeline_data})
    elif is_short_preview:
        out_path = preview_service.preview_path(clip["id"], {"editor": state, "timeline": timeline_data})
    else:
        out_dir = OUTPUT_DIR / clip["project_id"]
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{clip['id']}_final_{render_id[:6]}.mp4"

    started = time.perf_counter()
    update_render_record(render_id, status="rendering", progress=12)
    try:
        result = render_timeline_clip(
            Path(clip["source_path"]),
            out_path,
            float(clip["start_time"]),
            float(clip["end_time"]),
            state,
            timeline_data,
            caption_cues=cues or None,
            transcript=transcript,
            tracking=clip_tracking,
            preview=is_preview,
            preview_offset=0.0 if is_project_preview else preview_offset,
            preview_duration=max(0.1, float(clip["end_time"]) - float(clip["start_time"])) if is_project_preview else 8.0,
            progress_callback=lambda pct, _msg: update_render_record(render_id, status="rendering", progress=min(99, max(1, int(pct)))),
        )
        elapsed = time.perf_counter() - started
        size = out_path.stat().st_size if out_path.exists() else 0
        current_revision = int(editor_service.get_or_create_edit_state(clip["id"]).get("revision") or 1)
        if record_revision != current_revision:
            out_path.unlink(missing_ok=True)
            update_render_record(render_id, status="error", progress=100, error_message="Edição mudou durante o render. Gere novamente.", render_seconds=elapsed)
            return
        update_render_record(
            render_id,
            status="done",
            progress=100,
            video_path=str(out_path),
            encoder=result.get("encoder"),
            resolution=result.get("resolution"),
            file_size=size,
            render_seconds=elapsed,
        )
        if is_project_preview:
            thumb = out_path.with_suffix(".jpg")
            try:
                generate_thumbnail(out_path, thumb, "")
            except Exception:
                thumb = None
            if thumb and thumb.exists() and thumb.stat().st_size > 0:
                execute("UPDATE clips SET preview_path=?,thumbnail_path=?,render_status='preview',updated_at=? WHERE id=?", (str(out_path), str(thumb), now_iso(), clip["id"]))
            else:
                execute("UPDATE clips SET preview_path=?,render_status='preview',updated_at=? WHERE id=?", (str(out_path), now_iso(), clip["id"]))
        elif not is_preview:
            execute(
                "UPDATE clips SET video_path=?,render_status='rendered',render_encoder=?,render_seconds=?,file_size=?,updated_at=? WHERE id=?",
                (str(out_path), result.get("encoder"), elapsed, size, now_iso(), clip["id"]),
            )
    except Exception as exc:
        update_render_record(render_id, status="error", progress=100, error_message=str(exc))
