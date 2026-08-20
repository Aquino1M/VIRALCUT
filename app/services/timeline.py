from __future__ import annotations

import json
import uuid
from copy import deepcopy
from typing import Any

from app.db import execute, fetchone, now_iso

SCHEMA_VERSION = 3
TRACK_ORDER = ["video", "broll", "captions", "text", "overlays", "sfx", "music", "effects"]
TRACK_LABELS = {
    "video": "Vídeo principal",
    "broll": "B-roll",
    "captions": "Legendas",
    "text": "Textos",
    "overlays": "Overlays",
    "sfx": "Efeitos sonoros",
    "music": "Música",
    "effects": "Efeitos",
}


def _loads(value: str | None, fallback: Any) -> Any:
    try:
        return json.loads(value) if value else deepcopy(fallback)
    except Exception:
        return deepcopy(fallback)


def _geometry(aspect_ratio: str) -> tuple[int, int]:
    return {
        "9:16": (1080, 1920),
        "4:5": (1080, 1350),
        "1:1": (1080, 1080),
        "16:9": (1920, 1080),
    }.get(aspect_ratio or "9:16", (1080, 1920))


def _track(track_type: str, items: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "id": f"track-{track_type}",
        "type": track_type,
        "name": TRACK_LABELS[track_type],
        "hidden": False,
        "locked": track_type == "video",
        "muted": False,
        "items": items or [],
    }


def _base_timeline(clip_id: str) -> dict[str, Any]:
    from . import editor

    row = fetchone(
        "SELECT c.*,p.settings_json,p.source_path FROM clips c JOIN projects p ON p.id=c.project_id WHERE c.id=?",
        (clip_id,),
    )
    if not row:
        raise ValueError("clipe não encontrado")
    project_settings = _loads(row["settings_json"], {})
    state = editor.get_or_create_edit_state(clip_id)
    aspect = state.get("aspect_ratio") or project_settings.get("aspect_ratio") or "9:16"
    width, height = _geometry(aspect)
    duration = max(0.01, float(row["end_time"] or 0) - float(row["start_time"] or 0))
    source = row["clean_path"] or row["source_path"] or row["video_path"]
    video_item = {
        "id": "video-main",
        "type": "video",
        "assetId": "source-main",
        "from": 0.0,
        "duration": duration,
        "sourceStart": 0.0,
        "playbackRate": 1.0,
        "opacity": 1.0,
        "x": 0,
        "y": 0,
        "width": width,
        "height": height,
        "rotation": 0,
        "volumeDb": 0,
        "fadeIn": 0,
        "fadeOut": 0,
        "zIndex": 0,
    }
    cues = editor.list_caption_cues(clip_id)
    caption_items = [
        {
            "id": f"caption-{c.get('id') or i}",
            "type": "captions",
            "from": float(c["start_time"]),
            "duration": max(0.01, float(c["end_time"]) - float(c["start_time"])),
            "text": c["text"],
            "speakerId": c.get("speaker_id"),
            "wordIndex": c.get("word_index", i),
            "zIndex": 40,
        }
        for i, c in enumerate(cues)
    ]
    tracks = []
    for kind in TRACK_ORDER:
        if kind == "video":
            tracks.append(_track(kind, [video_item]))
        elif kind == "captions":
            tracks.append(_track(kind, caption_items))
        else:
            tracks.append(_track(kind))
    return {
        "schemaVersion": SCHEMA_VERSION,
        "clipId": clip_id,
        "composition": {"width": width, "height": height, "fps": 30, "duration": duration, "aspectRatio": aspect},
        "tracks": tracks,
        "assets": {
            "source-main": {"id": "source-main", "type": "video", "path": str(source or ""), "duration": duration}
        },
        "markers": [],
        "settings": {
            "captionPresetId": state.get("caption_preset_id"),
            "layoutPresetId": state.get("layout_preset_id"),
        },
        "metadata": {"generatedBy": "viralclip-v3", "autoEdit": None},
    }


def validate_timeline(value: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("timeline inválida")
    out = deepcopy(value)
    out["schemaVersion"] = SCHEMA_VERSION
    comp = out.setdefault("composition", {})
    comp["width"] = max(2, int(comp.get("width") or 1080))
    comp["height"] = max(2, int(comp.get("height") or 1920))
    comp["fps"] = max(1.0, float(comp.get("fps") or 30))
    comp["duration"] = max(0.01, float(comp.get("duration") or 0.01))
    tracks = out.get("tracks")
    if not isinstance(tracks, list):
        tracks = []
    existing = {str(t.get("type")): t for t in tracks if isinstance(t, dict) and t.get("type")}
    normalized: list[dict[str, Any]] = []
    for kind in TRACK_ORDER:
        track = deepcopy(existing.get(kind) or _track(kind))
        track.setdefault("id", f"track-{kind}")
        track["type"] = kind
        track.setdefault("name", TRACK_LABELS[kind])
        track["hidden"] = bool(track.get("hidden", False))
        track["locked"] = bool(track.get("locked", kind == "video"))
        track["muted"] = bool(track.get("muted", False))
        if not isinstance(track.get("items"), list):
            track["items"] = []
        normalized.append(track)
    # Preserve future/unknown tracks after the standard tracks.
    normalized.extend(deepcopy(t) for t in tracks if isinstance(t, dict) and t.get("type") not in TRACK_ORDER)
    out["tracks"] = normalized
    out.setdefault("assets", {})
    out.setdefault("markers", [])
    out.setdefault("settings", {})
    out.setdefault("metadata", {})
    return out


def get_or_create_timeline(clip_id: str) -> dict[str, Any]:
    row = fetchone("SELECT timeline_json FROM clip_timelines WHERE clip_id=?", (clip_id,))
    if row:
        return validate_timeline(_loads(row["timeline_json"], {}))
    data = _base_timeline(clip_id)
    return save_timeline(clip_id, data)


def save_timeline(clip_id: str, value: dict[str, Any]) -> dict[str, Any]:
    data = validate_timeline(value)
    data["clipId"] = clip_id
    now = now_iso()
    execute(
        """
        INSERT INTO clip_timelines(clip_id,schema_version,timeline_json,updated_at) VALUES(?,?,?,?)
        ON CONFLICT(clip_id) DO UPDATE SET schema_version=excluded.schema_version,timeline_json=excluded.timeline_json,updated_at=excluded.updated_at
        """,
        (clip_id, SCHEMA_VERSION, json.dumps(data, ensure_ascii=False), now),
    )
    return data


def track(data: dict[str, Any], track_type: str) -> dict[str, Any]:
    for item in data.get("tracks") or []:
        if item.get("type") == track_type:
            return item
    new = _track(track_type)
    data.setdefault("tracks", []).append(new)
    return new


def new_item_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"
