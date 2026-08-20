from __future__ import annotations

from pathlib import Path
from typing import Any

from app.config import BASE_DIR
from . import assets, hardware
from .timeline import SCHEMA_VERSION

API_VERSION = 1
WORKER_PROTOCOL_VERSION = 1


def _version() -> str:
    try:
        return (BASE_DIR / "VERSION").read_text(encoding="utf-8").strip() or "3.2.0"
    except Exception:
        return "3.2.0"


def health_payload() -> dict[str, Any]:
    return {
        "status": "ok",
        "product": "ViralClip Studio",
        "version": _version(),
        "api_version": API_VERSION,
        "worker_protocol": WORKER_PROTOCOL_VERSION,
        "timeline_schema": SCHEMA_VERSION,
        "local_first": True,
        "heavy_processing": "local-worker",
        "compute_orchestrator": "adaptive-compute-fabric",
        "browser_acceleration": "webgpu-optional",
    }


def _compact_asr(profile: dict[str, Any]) -> dict[str, Any]:
    raw = dict(profile.get("asr") or {})
    results = dict(raw.get("results") or {})
    selected = str(raw.get("selected_backend") or "").strip() or None
    selected_result = dict(results.get(selected) or {}) if selected else {}
    candidates: dict[str, Any] = {}
    for backend_id, value in results.items():
        item = dict(value or {})
        error = item.get("error")
        candidates[str(backend_id)] = {
            "ok": bool(item.get("ok")),
            "x_realtime": item.get("x_realtime"),
            "init_ms": item.get("init_ms"),
            "error": (str(error).replace(str(BASE_DIR), "<local>")[:240] if error else None),
        }
    return {
        "selected_backend": selected,
        "x_realtime": selected_result.get("x_realtime"),
        "last_benchmark": raw.get("benchmarked_at"),
        "fallback_reason": raw.get("fallback_reason"),
        "candidates": candidates,
    }


def capabilities_payload() -> dict[str, Any]:
    profile = hardware.load_or_build_profile()
    return {
        **health_payload(),
        "hardware": profile,
        "asr": _compact_asr(profile),
        "assets": assets.starter_pack_status(),
        "features": {
            "auto_edit": True,
            "timeline": True,
            "broll_library": True,
            "hardware_render": True,
            "local_worker_ready": True,
            "saas_bridge_ready": True,
            "studio_shell": True,
            "source_first_create": True,
            "mobile_navigation": True,
            "asset_manager": True,
            "templates_catalog": True,
            "brand_kit": True,
            "window_tracking": True,
            "persistent_jobs": True,
            "watchdog": True,
            "webgpu_preview": True,
            "worker_pairing": True,
            "smart_director": True,
            "viral_score_v2": True,
            "studio_templates": True,
            "named_brand_kits": True,
            "publish_queue": True,
            "viralytics": True,
            "render_cache": True,
            "waveform_cache": True,
            "performance_modes": True,
            "pwa_shell": True,
            "compute_fabric": True,
            "lightning_free_cpu_only": True,
            "resumable_cloud_upload": True,
            "cloud_result_cache": True,
            "viral_score_v3": True,
            "semantic_search": True,
            "prompt_to_edit": True,
            "revision_history": True,
            "creator_intelligence": True,
            "quality_guard_v2": True,
            "auto_edit_v2": True,
        },
    }
