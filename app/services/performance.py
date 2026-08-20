from __future__ import annotations

from typing import Any

MODES = {
    "basic": {"proxy_height": 360, "card_page_size": 12, "warm_models": False, "browser_preload": "metadata"},
    "balanced": {"proxy_height": 480, "card_page_size": 24, "warm_models": True, "browser_preload": "metadata"},
    "performance": {"proxy_height": 720, "card_page_size": 36, "warm_models": True, "browser_preload": "auto"},
}


def _cores(profile: dict[str, Any]) -> int:
    cpu = profile.get("cpu") or {}
    return int(cpu.get("logical_cores") or cpu.get("threads") or profile.get("logical_cores") or profile.get("cpu_threads") or 0)


def _memory(profile: dict[str, Any]) -> float:
    value = profile.get("memory_gb")
    if value is None:
        value = (profile.get("memory") or {}).get("total_gb")
    if value is None and profile.get("ram_mb") is not None:
        try:
            value = float(profile.get("ram_mb") or 0) / 1024.0
        except Exception:
            value = 0
    try:
        return float(value or 0)
    except Exception:
        return 0.0


def resolve_mode(profile: dict[str, Any] | None, override: str = "auto") -> dict[str, Any]:
    profile = profile or {}
    override = str(override or "auto").lower()
    if override in MODES:
        mode = override
    else:
        cores, memory = _cores(profile), _memory(profile)
        vendor = str(profile.get("gpu_vendor") or (profile.get("gpu") or {}).get("vendor") or "").lower()
        if memory and memory <= 8:
            mode = "basic"
        elif cores and cores <= 4 and vendor in {"", "none", "intel", "cpu"}:
            mode = "basic"
        elif (cores and cores >= 12) and (memory >= 24) and vendor not in {"", "none", "cpu"}:
            mode = "performance"
        else:
            mode = "balanced"
    return {"mode": mode, **MODES[mode], "final_quality_unchanged": True}
