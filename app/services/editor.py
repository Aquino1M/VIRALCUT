from __future__ import annotations

import json
import uuid
from copy import deepcopy
from typing import Any

from app.db import execute, executemany, fetchall, fetchone, now_iso

DEFAULT_TRACKS = {
    "video": {"visible": True, "locked": True, "muted": False, "z": 0},
    "captions": {"visible": True, "locked": False, "muted": False, "z": 40},
    "text": {"visible": True, "locked": False, "muted": False, "z": 50},
    "overlays": {"visible": True, "locked": False, "muted": False, "z": 60},
    "cta": {"visible": True, "locked": False, "muted": False, "z": 70},
}


def _loads(value: str | None, fallback: Any):
    if not value:
        return deepcopy(fallback)
    try:
        return json.loads(value)
    except Exception:
        return deepcopy(fallback)


def _project_defaults(clip_id: str) -> dict[str, Any]:
    row = fetchone(
        "SELECT p.settings_json FROM clips c JOIN projects p ON p.id=c.project_id WHERE c.id=?",
        (clip_id,),
    )
    settings = _loads(row["settings_json"] if row else None, {})
    return {
        "caption_preset_id": settings.get("caption_preset_id") or settings.get("caption_style") or "green-fresh",
        "layout_preset_id": settings.get("layout_preset_id") or settings.get("video_layout") or (
            "single" if settings.get("crop_style") in {"smart", "crop"} else "center"
        ),
        "caption_config": settings.get("caption_config") or {},
        "layout_config": settings.get("layout_config") or {},
        "aspect_ratio": settings.get("aspect_ratio") or "9:16",
        "overlays": settings.get("overlays") or [],
        "tracks": deepcopy(DEFAULT_TRACKS),
    }


def get_or_create_edit_state(clip_id: str) -> dict[str, Any]:
    row = fetchone("SELECT * FROM clip_edits WHERE clip_id=?", (clip_id,))
    if not row:
        defaults = _project_defaults(clip_id)
        save_edit_state(clip_id, defaults)
        row = fetchone("SELECT * FROM clip_edits WHERE clip_id=?", (clip_id,))
    defaults = _project_defaults(clip_id)
    return {
        "clip_id": clip_id,
        "aspect_ratio": (row["aspect_ratio"] if "aspect_ratio" in row.keys() else None) or defaults.get("aspect_ratio") or "9:16",
        "revision": int(row["revision"] if "revision" in row.keys() else 1),
        "caption_preset_id": row["caption_preset_id"],
        "layout_preset_id": row["layout_preset_id"],
        "caption_config": _loads(row["caption_config_json"], {}),
        "layout_config": _loads(row["layout_config_json"], {}),
        "overlays": _loads(row["overlay_config_json"], []),
        "tracks": _loads(row["tracks_json"], DEFAULT_TRACKS),
        "updated_at": row["updated_at"],
    }


def save_edit_state(clip_id: str, state: dict[str, Any]) -> dict[str, Any]:
    current = _project_defaults(clip_id)
    if fetchone("SELECT 1 FROM clip_edits WHERE clip_id=?", (clip_id,)):
        existing = get_or_create_edit_state(clip_id)
        current.update(existing)
    current.update({k: v for k, v in state.items() if k in {
        "caption_preset_id", "layout_preset_id", "caption_config", "layout_config", "overlays", "tracks", "aspect_ratio"
    }})
    current["tracks"] = {**deepcopy(DEFAULT_TRACKS), **(current.get("tracks") or {})}
    now = now_iso()
    execute(
        """
        INSERT INTO clip_edits(clip_id,caption_preset_id,layout_preset_id,caption_config_json,layout_config_json,overlay_config_json,tracks_json,aspect_ratio,updated_at)
        VALUES(?,?,?,?,?,?,?,?,?)
        ON CONFLICT(clip_id) DO UPDATE SET
            caption_preset_id=excluded.caption_preset_id,
            layout_preset_id=excluded.layout_preset_id,
            caption_config_json=excluded.caption_config_json,
            layout_config_json=excluded.layout_config_json,
            overlay_config_json=excluded.overlay_config_json,
            tracks_json=excluded.tracks_json,
            aspect_ratio=excluded.aspect_ratio,
            updated_at=excluded.updated_at
        """,
        (
            clip_id,
            current.get("caption_preset_id") or "green-fresh",
            current.get("layout_preset_id") or "auto",
            json.dumps(current.get("caption_config") or {}, ensure_ascii=False),
            json.dumps(current.get("layout_config") or {}, ensure_ascii=False),
            json.dumps(current.get("overlays") or [], ensure_ascii=False),
            json.dumps(current.get("tracks") or DEFAULT_TRACKS, ensure_ascii=False),
            current.get("aspect_ratio") or "9:16",
            now,
        ),
    )
    row = fetchone("SELECT * FROM clip_edits WHERE clip_id=?", (clip_id,))
    return {
        "clip_id": clip_id,
        "aspect_ratio": current.get("aspect_ratio") or "9:16",
        "revision": int(row["revision"] if "revision" in row.keys() else current.get("revision") or 1),
        "caption_preset_id": row["caption_preset_id"],
        "layout_preset_id": row["layout_preset_id"],
        "caption_config": _loads(row["caption_config_json"], {}),
        "layout_config": _loads(row["layout_config_json"], {}),
        "overlays": _loads(row["overlay_config_json"], []),
        "tracks": _loads(row["tracks_json"], DEFAULT_TRACKS),
        "updated_at": row["updated_at"],
    }


def list_caption_cues(clip_id: str) -> list[dict[str, Any]]:
    rows = fetchall(
        "SELECT id,clip_id,start_time,end_time,text,word_index,speaker_id,confidence,highlight,emoji FROM caption_cues WHERE clip_id=? ORDER BY start_time,word_index,id",
        (clip_id,),
    )
    return [dict(r) for r in rows]


def replace_caption_cues(clip_id: str, cues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    execute("DELETE FROM caption_cues WHERE clip_id=?", (clip_id,))
    now = now_iso()
    cleaned = []
    for i, cue in enumerate(cues):
        start = max(0.0, float(cue.get("start_time", 0)))
        end = max(start + 0.01, float(cue.get("end_time", start + 0.2)))
        text = str(cue.get("text", "")).strip()
        if not text:
            continue
        cleaned.append((clip_id, start, end, text, int(cue.get("word_index", i)), cue.get("speaker_id"), cue.get("confidence"), int(bool(cue.get("highlight"))), cue.get("emoji"), now, now))
    if cleaned:
        executemany(
            "INSERT INTO caption_cues(clip_id,start_time,end_time,text,word_index,speaker_id,confidence,highlight,emoji,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            cleaned,
        )
    return list_caption_cues(clip_id)


def mark_clip_dirty(clip_id: str) -> int:
    get_or_create_edit_state(clip_id)
    stamp = now_iso()
    execute("UPDATE clip_edits SET revision=COALESCE(revision,1)+1,updated_at=? WHERE clip_id=?", (stamp, clip_id))
    execute("UPDATE clips SET preview_path=NULL,thumbnail_path=NULL,render_status='edited',updated_at=? WHERE id=?", (stamp, clip_id))
    row = fetchone("SELECT revision FROM clip_edits WHERE clip_id=?", (clip_id,))
    return int(row["revision"] if row and row["revision"] is not None else 1)


def save_user_preset(user_id: int, preset_type: str, name: str, config: dict[str, Any], *, favorite: bool = False, preset_id: str | None = None) -> dict[str, Any]:
    preset_id = preset_id or uuid.uuid4().hex[:16]
    if preset_type not in {"caption", "layout", "combined"}:
        raise ValueError("preset_type inválido")
    now = now_iso()
    execute(
        "INSERT INTO user_presets(id,user_id,preset_type,name,config_json,favorite,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
        (preset_id, user_id, preset_type, name.strip() or "Preset", json.dumps(config, ensure_ascii=False), int(favorite), now, now),
    )
    return get_user_preset(user_id, preset_id)


def get_user_preset(user_id: int, preset_id: str) -> dict[str, Any] | None:
    row = fetchone("SELECT * FROM user_presets WHERE id=? AND user_id=?", (preset_id, user_id))
    if not row:
        return None
    d = dict(row)
    d["config"] = _loads(d.pop("config_json"), {})
    d["favorite"] = bool(d["favorite"])
    return d


def list_user_presets(user_id: int, preset_type: str | None = None) -> list[dict[str, Any]]:
    if preset_type:
        rows = fetchall("SELECT * FROM user_presets WHERE user_id=? AND preset_type=? ORDER BY favorite DESC, updated_at DESC", (user_id, preset_type))
    else:
        rows = fetchall("SELECT * FROM user_presets WHERE user_id=? ORDER BY favorite DESC, updated_at DESC", (user_id,))
    out = []
    for r in rows:
        d = dict(r)
        d["config"] = _loads(d.pop("config_json"), {})
        d["favorite"] = bool(d["favorite"])
        out.append(d)
    return out


def save_editor_snapshot(clip_id: str, state: dict[str, Any], cues: list[dict[str, Any]], timeline_data: dict[str, Any]) -> dict[str, Any]:
    """Persist the editor-visible state as one revisioned snapshot.

    The legacy tables remain the storage format for backwards compatibility, but the
    revision is the render barrier: a render may only claim to be current when it
    matches this revision.
    """
    from . import timeline as timeline_service

    current = get_or_create_edit_state(clip_id)
    merged = {**current, **(state or {})}
    saved_state = save_edit_state(clip_id, merged)
    saved_cues = replace_caption_cues(clip_id, cues or [])

    ratio = saved_state.get("aspect_ratio") or "9:16"
    geometry = {"9:16": (1080, 1920), "4:5": (1080, 1350), "1:1": (1080, 1080), "16:9": (1920, 1080)}
    tl = deepcopy(timeline_data or timeline_service.get_or_create_timeline(clip_id))
    comp = tl.setdefault("composition", {})
    if ratio.lower() != "original":
        w, h = geometry.get(ratio, (1080, 1920))
        comp.update({"width": w, "height": h, "aspectRatio": ratio})
    else:
        comp["aspectRatio"] = "Original"
    saved_timeline = timeline_service.save_timeline(clip_id, tl)

    next_revision = mark_clip_dirty(clip_id)
    saved_state = get_or_create_edit_state(clip_id)
    return {"revision": next_revision, "state": saved_state, "cues": saved_cues, "timeline": saved_timeline}
