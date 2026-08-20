from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import time
from pathlib import Path
from typing import Any

from app.config import BASE_DIR, DATA_DIR, FFMPEG_BIN
from .asr_backends import BACKENDS, backend_available, candidate_backend_ids, get_backend

BENCHMARK_PATH = DATA_DIR / "asr_benchmark.json"
SAMPLE_PATH = DATA_DIR / "cache" / "asr" / "benchmark_4s.wav"


def _viralclip_version() -> str:
    try:
        return (BASE_DIR / "VERSION").read_text(encoding="utf-8").strip()
    except Exception:
        return "unknown"


def environment_signature(profile: dict) -> str:
    payload = {
        "gpu_vendor": profile.get("gpu_vendor"),
        "gpu_name": profile.get("gpu_name"),
        "driver": profile.get("driver"),
        "platform": profile.get("platform"),
        "python": platform.python_version(),
        "viralclip": _viralclip_version(),
        "model": ((profile.get("transcription") or {}).get("model") or "small"),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def ensure_benchmark_sample() -> Path:
    path = Path(SAMPLE_PATH)
    if path.exists() and path.stat().st_size > 44:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    # Local deterministic audio. It benchmarks runtime/decoder throughput without user media or network.
    proc = subprocess.run([
        FFMPEG_BIN, "-y", "-loglevel", "error", "-f", "lavfi", "-i",
        "sine=frequency=440:sample_rate=16000:duration=4", "-ac", "1", "-ar", "16000", str(path),
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr[-1500:] or "Falha ao criar amostra local de benchmark ASR")
    return path


def run_backend_benchmark(backend_id: str, profile: dict, sample_path: str | Path | None = None) -> dict[str, Any]:
    sample = Path(sample_path) if sample_path else ensure_benchmark_sample()
    adapter = get_backend(backend_id)
    started = time.monotonic()
    try:
        result = adapter.transcribe_segments(sample, language=None, progress_callback=None, hardware_profile=profile)
        elapsed = max(0.001, time.monotonic() - started)
        duration = float(result.get("duration") or 4.0) or 4.0
        return {
            "ok": True,
            "x_realtime": round(duration / elapsed, 3),
            "init_ms": None,
            "infer_ms": int(round(elapsed * 1000)),
            "error": None,
        }
    except Exception as exc:
        return {
            "ok": False,
            "x_realtime": 0.0,
            "init_ms": None,
            "infer_ms": int(round((time.monotonic() - started) * 1000)),
            "error": f"{type(exc).__name__}: {exc}"[:500],
        }


def _load_persisted() -> dict | None:
    path = Path(BENCHMARK_PATH)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _save(data: dict) -> None:
    path = Path(BENCHMARK_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def benchmark_backends(profile: dict, *, force: bool = False) -> dict:
    signature = environment_signature(profile)
    persisted = None if force else _load_persisted()
    if persisted and persisted.get("environment_signature") == signature:
        return persisted

    results: dict[str, dict[str, Any]] = {}
    candidates = candidate_backend_ids(profile)
    for backend_id in candidates:
        if not backend_available(backend_id):
            results[backend_id] = {"ok": False, "x_realtime": 0.0, "error": "runtime indisponível"}
            continue
        result = run_backend_benchmark(backend_id, profile)
        results[backend_id] = dict(result)

    requested_quality = "whisper"
    winners: list[tuple[float, float, str]] = []
    for backend_id, result in results.items():
        descriptor = BACKENDS.get(backend_id)
        if not descriptor or descriptor.quality_class != requested_quality or not result.get("ok"):
            continue
        xrt = float(result.get("x_realtime") or 0.0)
        startup = float(result.get("init_ms") or 10**9)
        winners.append((xrt, -startup, backend_id))
    winners.sort(reverse=True)
    selected = winners[0][2] if winners else "faster-whisper-cpu"
    fallback_reason = None
    if not winners:
        fallback_reason = "Nenhum acelerador passou no benchmark; CPU é o fallback obrigatório."
    elif selected != candidates[0]:
        first = results.get(candidates[0]) or {}
        fallback_reason = first.get("error") or f"{candidates[0]} foi mais lento no benchmark"
    data = {
        "environment_signature": signature,
        "selected_backend": selected,
        "benchmarked_at": time.time(),
        "results": results,
        "fallback_reason": fallback_reason,
    }
    _save(data)
    return data


def selected_backend(profile: dict, *, force: bool = False) -> str:
    persisted = (profile.get("asr") or {}).get("selected_backend")
    if persisted and not force:
        return str(persisted)
    return str(benchmark_backends(profile, force=force).get("selected_backend") or "faster-whisper-cpu")
