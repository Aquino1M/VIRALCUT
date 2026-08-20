from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from app.config import PREVIEW_DIR


def settings_hash(state: dict[str, Any]) -> str:
    raw = json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def preview_path(clip_id: str, state: dict[str, Any]) -> Path:
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    return PREVIEW_DIR / f"{clip_id}_{settings_hash(state)}.mp4"


def cached_preview(clip_id: str, state: dict[str, Any]) -> Path | None:
    path = preview_path(clip_id, state)
    return path if path.exists() and path.stat().st_size > 0 else None


def project_preview_path(clip_id: str, state: dict[str, Any]) -> Path:
    folder = PREVIEW_DIR / "project"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{clip_id}_{settings_hash(state)}.mp4"


def cached_project_preview(clip_id: str, state: dict[str, Any]) -> Path | None:
    path = project_preview_path(clip_id, state)
    return path if path.exists() and path.stat().st_size > 0 else None


def edit_state_fingerprint(state: dict[str, Any], tracking: dict[str, Any] | None, aspect_ratio: str = "9:16") -> str:
    layout_only = {
        "layout_preset_id": (state or {}).get("layout_preset_id") or "auto",
        "layout_config": (state or {}).get("layout_config") or {},
        "aspect_ratio": aspect_ratio or "9:16",
        "tracking_version": (tracking or {}).get("version"),
        "tracking_backend": (tracking or {}).get("backend"),
        "tracks": [
            {"id": t.get("id"), "samples": t.get("samples") or []}
            for t in ((tracking or {}).get("tracks") or [])
        ],
    }
    raw = json.dumps(layout_only, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def clean_layout_path(clip_id: str, state: dict[str, Any], tracking: dict[str, Any] | None, aspect_ratio: str = "9:16") -> Path:
    folder = PREVIEW_DIR / "clean"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{clip_id}_{edit_state_fingerprint(state, tracking, aspect_ratio)}.mp4"
