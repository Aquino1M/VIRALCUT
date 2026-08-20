from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .captions import list_caption_presets
from .layouts import list_layout_presets

_ALLOWED_UPLOAD_EXTS = {".mp4", ".mov", ".mkv", ".avi"}
_LAYOUT_IDS = {x["id"] for x in list_layout_presets()}
_CAPTION_IDS = {x["id"] for x in list_caption_presets()}


def classify_source_url(url: str) -> str:
    host = (urlparse((url or "").strip()).hostname or "").lower()
    if host in {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "music.youtube.com"} or host.endswith(".youtube.com"):
        return "youtube"
    if host in {"twitch.tv", "www.twitch.tv", "m.twitch.tv"} or host.endswith(".twitch.tv"):
        return "twitch"
    if host in {"kick.com", "www.kick.com"} or host.endswith(".kick.com"):
        return "kick"
    if host in {"drive.google.com", "docs.google.com"} or host.endswith(".googleusercontent.com"):
        return "gdrive"
    return "url"


def validate_upload_filename(filename: str | None) -> bool:
    return bool(filename and Path(filename).suffix.lower() in _ALLOWED_UPLOAD_EXTS)


def normalize_project_settings(raw: dict[str, Any] | None) -> dict[str, Any]:
    raw = dict(raw or {})
    try:
        source_duration = max(0.0, float(raw.get("source_duration") or 0))
    except Exception:
        source_duration = 0.0
    try:
        start_range = max(0.0, float(raw.get("start_range") or 0))
    except Exception:
        start_range = 0.0
    try:
        end_range = float(raw.get("end_range") or 0)
    except Exception:
        end_range = 0.0
    if end_range <= 0:
        end_range = source_duration if source_duration > 0 else 0.0
    if source_duration > 0:
        start_range = min(start_range, source_duration)
        end_range = min(max(start_range, end_range), source_duration)
    else:
        end_range = max(start_range, end_range)

    layout_id = str(raw.get("layout_preset_id") or raw.get("video_layout") or "auto")
    if layout_id not in _LAYOUT_IDS:
        layout_id = "auto"
    caption_id = str(raw.get("caption_preset_id") or raw.get("caption_style") or "green-fresh")
    legacy = {"bold": "green-fresh", "large": "mrbeast", "minimal": "minimal-clean"}
    caption_id = legacy.get(caption_id, caption_id)
    if caption_id not in _CAPTION_IDS:
        caption_id = "green-fresh"

    def _bool(name: str, default: bool = False) -> bool:
        value = raw.get(name, default)
        if isinstance(value, str):
            return value.lower() in {"1", "true", "on", "yes", "sim"}
        return bool(value)

    def _num(name: str, default: float, minimum: float | None = None, maximum: float | None = None):
        try:
            value = float(raw.get(name, default))
        except Exception:
            value = default
        if minimum is not None:
            value = max(minimum, value)
        if maximum is not None:
            value = min(maximum, value)
        return value

    min_duration = _num("min_duration", 20, 5, 600)
    max_duration = max(min_duration + 1, _num("max_duration", 90, 6, 900))
    target_duration = _num("target_duration", 60, 10, 600)
    num_clips = int(_num("num_clips", 5, 1, 100))
    aspect_ratio = str(raw.get("aspect_ratio") or "9:16")
    if aspect_ratio not in {"9:16", "1:1", "16:9", "4:5"}:
        aspect_ratio = "9:16"

    auto_style = str(raw.get("auto_edit_style") or "podcast-viral")
    if auto_style not in {"podcast-viral", "noticias", "politica", "financas", "fofoca", "documentario", "gaming", "storytelling", "mrbeast-like"}:
        auto_style = "podcast-viral"
    auto_intensity = str(raw.get("auto_edit_intensity") or "normal")
    if auto_intensity not in {"clean", "normal", "viral", "hyper"}:
        auto_intensity = "normal"

    return {
        "prompt": str(raw.get("prompt") or raw.get("custom_keywords") or "").strip(),
        "goal": str(raw.get("goal") or "shorts"),
        "num_clips": num_clips,
        "min_duration": min_duration,
        "max_duration": max_duration,
        "target_duration": target_duration,
        "manual_ranges": str(raw.get("manual_ranges") or "").strip(),
        "clip_duration_policy": str(raw.get("clip_duration_policy") or "auto"),
        "start_range": start_range,
        "end_range": end_range,
        "language": (str(raw.get("language") or "").strip() or None),
        "target_languages": raw.get("target_languages") or [],
        "aspect_ratio": aspect_ratio,
        "layout_preset_id": layout_id,
        "layout_config": raw.get("layout_config") or {},
        "caption_preset_id": caption_id,
        "caption_font": str(raw.get("caption_font") or "Bangers"),
        "caption_config": raw.get("caption_config") or {},
        "captions": _bool("captions", True),
        "emojis": _bool("emojis", True),
        "use_llm": _bool("use_llm", True),
        "cta_enabled": _bool("cta_enabled", False),
        "overlays": raw.get("overlays") or [],
        "custom_keywords": str(raw.get("custom_keywords") or raw.get("prompt") or "").strip(),
        "youtube_cookies": str(raw.get("youtube_cookies") or ""),
        "crop_style": str(raw.get("crop_style") or "smart"),
        "auto_edit_enabled": _bool("auto_edit_enabled", False),
        "auto_edit_style": auto_style,
        "auto_edit_intensity": auto_intensity,
    }


def sort_sql(sort: str) -> str:
    return {
        "score": "score DESC, start_time ASC",
        "time": "start_time ASC",
        "duration": "(end_time-start_time) DESC",
        "title": "title COLLATE NOCASE ASC",
    }.get(sort, "score DESC, start_time ASC")


def page_size(value: Any) -> int:
    try:
        n = int(value)
    except Exception:
        n = 12
    allowed = [12, 24, 36, 48, 60, 72, 84, 96]
    return n if n in allowed else 12


def is_remote_source_type(source_type: str | None) -> bool:
    return (source_type or "").lower() in {"youtube", "twitch", "kick", "gdrive", "url"}
