from __future__ import annotations

import os
import platform
import re
import subprocess
import sys
from dataclasses import dataclass
from typing import Callable, Any

CommandRunner = Callable[[list[str]], str]


def _run(cmd: list[str]) -> str:
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=15)
        return proc.stdout or ""
    except Exception:
        return ""


def _memory_mb() -> int:
    try:
        if hasattr(os, "sysconf") and "SC_PHYS_PAGES" in os.sysconf_names:
            return int(os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") / (1024 * 1024))
    except Exception:
        pass
    try:
        import ctypes
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong), ("sullAvailExtendedVirtual", ctypes.c_ulonglong)]
        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(stat)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
        return int(stat.ullTotalPhys / (1024 * 1024))
    except Exception:
        return 0


def _windows_gpu_text(runner: CommandRunner) -> str:
    text = runner(["wmic", "path", "win32_VideoController", "get", "name"])
    if text.strip():
        return text
    return runner([
        "powershell", "-NoProfile", "-Command",
        "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name",
    ])


def _vendor_from_text(text: str) -> tuple[str, str]:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip() and ln.strip().lower() != "name"]
    joined = " ".join(lines)
    low = joined.lower()
    # Prefer discrete vendors when Windows reports both an iGPU and dGPU.
    if "nvidia" in low or "geforce" in low or "quadro" in low:
        name = next((ln for ln in lines if any(x in ln.lower() for x in ("nvidia", "geforce", "quadro"))), joined or "NVIDIA GPU")
        return "nvidia", name
    if "amd" in low or "radeon" in low:
        name = next((ln for ln in lines if any(x in ln.lower() for x in ("amd", "radeon"))), joined or "AMD GPU")
        return "amd", name
    if "intel" in low or "arc" in low or "iris" in low:
        name = next((ln for ln in lines if any(x in ln.lower() for x in ("intel", "arc", "iris"))), joined or "Intel GPU")
        return "intel", name
    return "cpu", "CPU only"


def _nvidia_vram(runner: CommandRunner) -> tuple[str | None, int]:
    out = runner(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"])
    first = next((ln.strip() for ln in out.splitlines() if ln.strip()), "")
    if not first:
        return None, 0
    parts = [p.strip() for p in first.split(",")]
    if len(parts) < 2:
        return parts[0] or None, 0
    try:
        return parts[0] or None, int(float(re.sub(r"[^0-9.]", "", parts[1]) or 0))
    except Exception:
        return parts[0] or None, 0


def _encoder_choice(vendor: str, encoders_text: str) -> str:
    low = (encoders_text or "").lower()
    if vendor == "nvidia" and "h264_nvenc" in low:
        return "h264_nvenc"
    if vendor == "amd" and "h264_amf" in low:
        return "h264_amf"
    if vendor == "intel" and "h264_qsv" in low:
        return "h264_qsv"
    # On hybrid systems accept any supported hardware encoder before CPU.
    for enc in ("h264_nvenc", "h264_amf", "h264_qsv"):
        if enc in low:
            return enc
    return "libx264"


def detect_capabilities(*, platform_name: str | None = None, command_runner: CommandRunner | None = None) -> dict[str, Any]:
    runner = command_runner or _run
    platform_name = platform_name or sys.platform
    gpu_text = ""
    if platform_name.startswith("win"):
        gpu_text = _windows_gpu_text(runner)
    elif platform_name.startswith("linux"):
        gpu_text = runner(["sh", "-lc", "lspci | grep -Ei 'vga|3d|display'"])
    else:
        gpu_text = runner(["sh", "-lc", "system_profiler SPDisplaysDataType 2>/dev/null"])

    vendor, gpu_name = _vendor_from_text(gpu_text)
    vram_mb = 0
    if vendor == "nvidia":
        detected_name, vram_mb = _nvidia_vram(runner)
        if detected_name:
            gpu_name = detected_name

    encoders = runner(["ffmpeg", "-hide_banner", "-encoders"])
    encoder = _encoder_choice(vendor, encoders)

    if vendor == "nvidia":
        ai_backend = "cuda"
    elif vendor == "amd":
        ai_backend = "directml" if platform_name.startswith("win") else "vulkan"
    elif vendor == "intel":
        ai_backend = "directml" if platform_name.startswith("win") else "openvino"
    else:
        ai_backend = "cpu"

    caps: dict[str, Any] = {
        "platform": platform_name,
        "os": platform.system() or platform_name,
        "gpu_vendor": vendor,
        "gpu_name": gpu_name,
        "vram_mb": int(vram_mb or 0),
        "video_encoder": encoder,
        "ai_backend": ai_backend,
        "ffmpeg_hardware_encoders": [enc for enc in ("h264_nvenc", "h264_amf", "h264_qsv") if enc in encoders.lower()],
        "cpu_threads": int(os.cpu_count() or 1),
        "ram_mb": _memory_mb(),
        "python": platform.python_version(),
    }
    caps["profile"] = recommended_profile(caps)
    return caps


def recommended_profile(capabilities: dict[str, Any]) -> dict[str, Any]:
    vendor = str(capabilities.get("gpu_vendor") or "cpu")
    vram = int(capabilities.get("vram_mb") or 0)
    ram = int(capabilities.get("ram_mb") or 0)
    threads = int(capabilities.get("cpu_threads") or 1)
    if vendor != "cpu" and (vram >= 8000 or (vram == 0 and ram >= 24000 and threads >= 8)):
        return {
            "name": "turbo",
            "label": "TURBO",
            "preview_scale": 0.5,
            "tracking_fps": 2.5,
            "whisper_model": "small",
            "max_parallel_renders": 2,
        }
    if vendor != "cpu" or (ram >= 12000 and threads >= 6):
        return {
            "name": "balanced",
            "label": "BALANCEADO",
            "preview_scale": 0.5,
            "tracking_fps": 1.8,
            "whisper_model": "small",
            "max_parallel_renders": 1,
        }
    return {
        "name": "eco",
        "label": "ECO",
        "preview_scale": 0.4,
        "tracking_fps": 1.0,
        "whisper_model": "base",
        "max_parallel_renders": 1,
    }

# V3.2 persistent hardware profile. The profile is advisory: every heavy
# operation still has a CPU fallback if a driver disappears after setup.
from pathlib import Path
import json
import time
from app.config import DATA_DIR

HARDWARE_PROFILE_VERSION = 3
PROFILE_PATH = DATA_DIR / "hardware_profile.json"


def _encoder_benchmark(encoder: str, runner: CommandRunner) -> tuple[bool, str | None]:
    if encoder == "libx264":
        return True, None
    output = runner([
        "ffmpeg", "-hide_banner", "-y", "-f", "lavfi", "-i", "color=c=black:s=160x90:d=0.1",
        "-frames:v", "1", "-c:v", encoder, "-f", "null", "-",
    ])
    low = (output or "").lower()
    if not output or any(x in low for x in ("error initializing", "unknown encoder", "failed to", "cannot load", "no capable devices")):
        return False, "Encoder anunciado pelo FFmpeg, mas falhou no teste rápido."
    return True, None


def build_hardware_profile(*, platform_name: str | None = None, command_runner: CommandRunner | None = None) -> dict[str, Any]:
    runner = command_runner or _run
    caps = detect_capabilities(platform_name=platform_name, command_runner=runner)
    preferred = str(caps.get("video_encoder") or "libx264")
    verified, fallback_reason = _encoder_benchmark(preferred, runner)
    encoder = preferred if verified else "libx264"
    base_profile = dict(caps.get("profile") or recommended_profile(caps))
    profile_name = str(base_profile.get("name") or "balanced")
    if profile_name == "turbo":
        analysis_width = 720; tracking_fps = float(base_profile.get("tracking_fps") or 2.5); threads = max(4, min(12, int(caps.get("cpu_threads") or 4)))
    elif profile_name == "eco":
        analysis_width = 480; tracking_fps = float(base_profile.get("tracking_fps") or 1.0); threads = max(1, min(3, int(caps.get("cpu_threads") or 2)))
    else:
        analysis_width = 640; tracking_fps = float(base_profile.get("tracking_fps") or 1.8); threads = max(2, min(6, int(caps.get("cpu_threads") or 4)))
    vendor = str(caps.get("gpu_vendor") or "cpu").lower()
    transcription_backend = "cpu" if vendor == "cpu" else "auto"
    model = str(base_profile.get("whisper_model") or ("base" if profile_name == "eco" else "small"))
    return {
        "version": HARDWARE_PROFILE_VERSION,
        "generated_at": time.time(),
        "platform": caps.get("platform"),
        "os": caps.get("os"),
        "gpu_vendor": caps.get("gpu_vendor"),
        "gpu_name": caps.get("gpu_name"),
        "vram_mb": int(caps.get("vram_mb") or 0),
        "ram_mb": int(caps.get("ram_mb") or 0),
        "cpu_threads": int(caps.get("cpu_threads") or 1),
        "profile": base_profile,
        "render": {"encoder": encoder, "preferred_encoder": preferred, "verified": bool(verified), "fallback_reason": fallback_reason},
        "transcription": {"backend": transcription_backend, "model": model, "cpu_threads": threads},
        "asr": {
            "environment_signature": None,
            "selected_backend": None,
            "benchmarked_at": None,
            "results": {},
            "fallback_reason": None,
        },
        "analysis": {"tracking_fps": tracking_fps, "width": analysis_width, "scene_prepass": True},
    }


def load_or_build_profile(*, force: bool = False, run_asr_benchmark: bool | None = None) -> dict[str, Any]:
    path = Path(PROFILE_PATH)
    if not force and path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if int(data.get("version") or 0) == HARDWARE_PROFILE_VERSION:
                return data
        except Exception:
            pass
    data = build_hardware_profile()
    # V3.4 chooses ASR by a real persisted benchmark, never by vendor alone.
    should_benchmark = bool(force) if run_asr_benchmark is None else bool(run_asr_benchmark)
    if should_benchmark:
        try:
            from . import asr_benchmark
            data["asr"] = asr_benchmark.benchmark_backends(data, force=force)
        except Exception as exc:
            data["asr"] = {
                **dict(data.get("asr") or {}),
                "fallback_reason": f"Benchmark ASR não concluído: {type(exc).__name__}: {exc}"[:500],
            }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def render_route(profile: dict[str, Any] | None = None) -> dict[str, Any]:
    profile = profile or load_or_build_profile()
    return dict(profile.get("render") or {"encoder": "libx264"})


def transcription_route(profile: dict[str, Any] | None = None) -> dict[str, Any]:
    profile = profile or load_or_build_profile()
    route = dict(profile.get("transcription") or {"backend": "cpu", "model": "base"})
    selected = str((profile.get("asr") or {}).get("selected_backend") or "").strip()
    if selected:
        route["selected_backend"] = selected
    return route

# V4.2 runtime load snapshot used by Adaptive Compute. Optional dependencies and
# vendor tools are best-effort; absence never prevents local fallback.
def runtime_load(command_runner: CommandRunner | None = None) -> dict[str, Any]:
    runner = command_runner or _run
    cpu_percent = 0.0
    ram_percent = 0.0
    ram_available_mb = 0
    try:
        import psutil
        cpu_percent = float(psutil.cpu_percent(interval=0.05))
        mem = psutil.virtual_memory()
        ram_percent = float(mem.percent)
        ram_available_mb = int(mem.available / (1024 * 1024))
    except Exception:
        pass
    gpu_percent = None
    vram_percent = None
    try:
        raw = runner(["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total", "--format=csv,noheader,nounits"])
        first = next((x.strip() for x in raw.splitlines() if x.strip()), "")
        if first:
            parts = [x.strip() for x in first.split(",")]
            gpu_percent = float(parts[0])
            used, total = float(parts[1]), float(parts[2])
            vram_percent = round(used / max(1.0, total) * 100.0, 1)
    except Exception:
        pass
    return {
        "cpu_percent": round(cpu_percent, 1),
        "ram_percent": round(ram_percent, 1),
        "ram_available_mb": ram_available_mb,
        "gpu_percent": gpu_percent,
        "vram_percent": vram_percent,
    }
