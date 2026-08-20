from __future__ import annotations

import json
import math
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from threading import Lock
from typing import Callable

from app.config import (
    BASE_DIR,
    FFMPEG_BIN,
    FFPROBE_BIN,
    WHISPER_BACKEND,
    WHISPER_BEAM_SIZE,
    WHISPER_COMPUTE_TYPE,
    WHISPER_CPU_THREADS,
    WHISPER_DEVICE,
    WHISPER_MODEL,
    WHISPER_NUM_WORKERS,
    WHISPER_CHUNK_SECONDS,
)

ProgressCallback = Callable[[float, str], None]

_faster_model = None
_faster_model_runtime = None
_faster_model_key = None
_directml_model = None
_directml_whisper = None
_directml_model_key = None
_faster_lock = Lock()
_directml_lock = Lock()


def _directml_vendor_root() -> Path:
    return BASE_DIR / "vendor" / "directml_whisper"


def _directml_is_available() -> bool:
    vendor = _directml_vendor_root() / "whisper" / "__init__.py"
    if not vendor.exists():
        return False
    try:
        import torch_directml  # noqa: F401
        return True
    except Exception:
        return False


def resolve_backend(
    preferred: str | None = None,
    *,
    platform_name: str | None = None,
    directml_available: bool | None = None,
    gpu_vendor: str | None = None,
) -> str:
    """Resolve the ASR backend without importing heavyweight ML packages.

    - directml: AMD/Intel/NVIDIA via DirectX 12 on Windows.
    - faster-whisper: CPU fallback, or CUDA when explicitly configured on NVIDIA.
    - auto: prefers DirectML on Windows only when the optional setup is installed.
    """
    pref = (preferred or WHISPER_BACKEND or "auto").strip().lower()
    aliases = {
        "dml": "directml",
        "amd": "directml",
        "faster_whisper": "faster-whisper",
        "faster": "faster-whisper",
        "cpu": "faster-whisper",
    }
    pref = aliases.get(pref, pref)
    if pref in {"directml", "faster-whisper"}:
        return pref
    if pref != "auto":
        return "faster-whisper"

    explicit_platform = platform_name is not None
    platform_name = platform_name or sys.platform
    if directml_available is None:
        directml_available = _directml_is_available()
    if gpu_vendor is None and not explicit_platform:
        try:
            from .hardware import detect_capabilities
            gpu_vendor = str(detect_capabilities().get("gpu_vendor") or "cpu")
        except Exception:
            gpu_vendor = None
    # NVIDIA has the strongest faster-whisper path through CUDA. Do not route it
    # through DirectML merely because DirectML also happens to be installed.
    if str(gpu_vendor or "").lower() == "nvidia":
        return "faster-whisper"
    if platform_name.startswith("win") and directml_available:
        return "directml"
    return "faster-whisper"


def select_faster_runtime(
    *, configured_device: str | None = None, configured_compute: str | None = None, capabilities: dict | None = None
) -> tuple[str, str]:
    device_cfg = str(configured_device if configured_device is not None else WHISPER_DEVICE or "auto").strip().lower()
    compute_cfg = str(configured_compute if configured_compute is not None else WHISPER_COMPUTE_TYPE or "auto").strip().lower()
    if capabilities is None:
        try:
            from .hardware import detect_capabilities
            capabilities = detect_capabilities()
        except Exception:
            capabilities = {"gpu_vendor": "cpu"}
    vendor = str((capabilities or {}).get("gpu_vendor") or "cpu").lower()
    if device_cfg == "auto":
        device = "cuda" if vendor == "nvidia" else "cpu"
    else:
        device = device_cfg
    if compute_cfg == "auto":
        compute = "float16" if device == "cuda" else "int8"
    else:
        compute = compute_cfg
    return device, compute




def transcription_model_name(hardware_profile: dict | None = None) -> str:
    return str(((hardware_profile or {}).get("transcription") or {}).get("model") or WHISPER_MODEL)

def faster_model_config(hardware_profile: dict | None = None) -> dict:
    route = dict((hardware_profile or {}).get("transcription") or {})
    model = str(route.get("model") or WHISPER_MODEL)
    threads = max(1, int(route.get("cpu_threads") or WHISPER_CPU_THREADS))
    vendor = str((hardware_profile or {}).get("gpu_vendor") or "cpu").lower()
    backend = str(route.get("backend") or "").lower()
    capabilities = {"gpu_vendor": "nvidia" if backend == "cuda" else vendor}
    if backend == "cuda":
        device, compute = select_faster_runtime(configured_device="cuda", configured_compute="auto", capabilities=capabilities)
    elif backend == "cpu":
        device, compute = "cpu", "int8"
    else:
        device, compute = select_faster_runtime(configured_device="auto", configured_compute="auto", capabilities=capabilities)
    return {
        "model": model,
        "device": device,
        "compute_type": compute,
        "cpu_threads": threads,
        "num_workers": max(1, int(route.get("num_workers") or WHISPER_NUM_WORKERS)),
    }

def _get_faster_model(hardware_profile: dict | None = None):
    global _faster_model, _faster_model_runtime, _faster_model_key
    with _faster_lock:
        cfg = faster_model_config(hardware_profile)
        desired = (cfg["device"], cfg["compute_type"])
        key = (cfg["model"], cfg["device"], cfg["compute_type"], cfg["cpu_threads"], cfg["num_workers"])
        if _faster_model is not None and _faster_model_key == key:
            return _faster_model
        from faster_whisper import WhisperModel
        device, compute_type = desired
        try:
            model = WhisperModel(
                cfg["model"], device=device, compute_type=compute_type,
                cpu_threads=cfg["cpu_threads"], num_workers=cfg["num_workers"],
            )
            _faster_model_runtime = (device, compute_type)
            _faster_model_key = key
        except Exception:
            # Auto hardware route remains portable: CUDA can be advertised by
            # the GPU while the CTranslate2 CUDA runtime is unavailable.
            if str(WHISPER_DEVICE or "auto").strip().lower() != "auto" or device == "cpu":
                raise
            model = WhisperModel(
                cfg["model"], device="cpu", compute_type="int8",
                cpu_threads=cfg["cpu_threads"], num_workers=cfg["num_workers"],
            )
            _faster_model_runtime = ("cpu", "int8")
            _faster_model_key = (cfg["model"], "cpu", "int8", cfg["cpu_threads"], cfg["num_workers"])
        _faster_model = model
    return _faster_model


def _get_directml_model(hardware_profile: dict | None = None):
    global _directml_model, _directml_whisper, _directml_model_key
    with _directml_lock:
        model_name = transcription_model_name(hardware_profile)
        if _directml_model is not None and _directml_whisper is not None and _directml_model_key == model_name:
            return _directml_model, _directml_whisper

        vendor_root = _directml_vendor_root()
        if not (vendor_root / "whisper" / "__init__.py").exists():
            raise RuntimeError(
                "Backend DirectML não instalado. Execute setup_amd_gpu.bat e reinicie o ViralClip."
            )
        if str(vendor_root) not in sys.path:
            sys.path.insert(0, str(vendor_root))

        import torch_directml
        import whisper as dml_whisper

        device = torch_directml.device(torch_directml.default_device())
        try:
            model = dml_whisper.load_model(
                model_name,
                device=device,
                use_dml_attn=True,
            )
        except TypeError:
            # Compatibility with an older DirectML sample checkout.
            model = dml_whisper.load_model(model_name, device=device)

        _directml_model = model
        _directml_whisper = dml_whisper
        _directml_model_key = model_name
        return _directml_model, _directml_whisper


def _notify(callback: ProgressCallback | None, fraction: float, backend: str) -> None:
    if callback is not None:
        callback(max(0.0, min(1.0, float(fraction))), backend)


def _transcribe_faster_whisper(
    video_path: str | Path,
    language: str | None,
    progress_callback: ProgressCallback | None,
    hardware_profile: dict | None = None,
    *,
    word_timestamps: bool = True,
) -> dict:
    model = _get_faster_model(hardware_profile)
    runtime_label = "faster-whisper " + (("CUDA" if (_faster_model_runtime or ("cpu",))[0] == "cuda" else "CPU"))
    segments_iter, info = model.transcribe(
        str(video_path),
        language=language or None,
        vad_filter=True,
        word_timestamps=bool(word_timestamps),
        beam_size=max(1, WHISPER_BEAM_SIZE),
        condition_on_previous_text=False,
    )

    total_duration = float(getattr(info, "duration", 0.0) or 0.0)
    segments = []
    for idx, s in enumerate(segments_iter):
        words = []
        for w in ((s.words or []) if word_timestamps else []):
            words.append(
                {
                    "start": float(w.start or s.start),
                    "end": float(w.end or s.end),
                    "word": (w.word or "").strip(),
                }
            )
        segments.append(
            {
                "id": idx,
                "start": float(s.start),
                "end": float(s.end),
                "text": (s.text or "").strip(),
                "words": words,
            }
        )
        if total_duration > 0:
            _notify(progress_callback, float(s.end) / total_duration, runtime_label)

    duration = segments[-1]["end"] if segments else total_duration
    _notify(progress_callback, 1.0, runtime_label)
    return {
        "language": getattr(info, "language", language or "unknown"),
        "duration": duration,
        "segments": segments,
        "backend": "faster-whisper",
        "runtime": (_faster_model_runtime or ("cpu", "int8"))[0],
    }


def _probe_duration(path: str | Path) -> float:
    proc = subprocess.run(
        [
            FFPROBE_BIN,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if proc.returncode != 0:
        return 0.0
    try:
        return max(0.0, float(proc.stdout.strip()))
    except ValueError:
        return 0.0


def _extract_audio_chunk(source: str | Path, start: float, duration: float, out_path: Path) -> None:
    cmd = [
        FFMPEG_BIN,
        "-y",
        "-loglevel",
        "error",
        "-ss",
        f"{start:.3f}",
        "-t",
        f"{duration:.3f}",
        "-i",
        str(source),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        str(out_path),
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr[-2500:] or "Falha ao extrair áudio para o DirectML")


def _dml_transcribe_one(model, audio_path: Path, language: str | None, *, word_timestamps: bool) -> dict:
    kwargs = {
        "language": language or None,
        "verbose": False,
        "fp16": False,
        "condition_on_previous_text": False,
    }
    # V3.4 makes the mode explicit. A failing word-level DirectML path is
    # handled by the benchmark/fallback layer instead of silently changing mode.
    return model.transcribe(str(audio_path), word_timestamps=bool(word_timestamps), **kwargs)


def _transcribe_directml(
    video_path: str | Path,
    language: str | None,
    progress_callback: ProgressCallback | None,
    hardware_profile: dict | None = None,
    *,
    word_timestamps: bool = True,
) -> dict:
    model, _whisper = _get_directml_model(hardware_profile)
    total_duration = _probe_duration(video_path)
    if total_duration <= 0:
        raise RuntimeError("Não foi possível detectar a duração do vídeo para a transcrição DirectML.")

    chunk_seconds = max(30.0, float(WHISPER_CHUNK_SECONDS))
    chunk_count = max(1, int(math.ceil(total_duration / chunk_seconds)))
    merged_segments: list[dict] = []
    detected_language = language or "unknown"

    temp_dir = Path(tempfile.mkdtemp(prefix="viralclip_dml_"))
    try:
        for chunk_index in range(chunk_count):
            start = chunk_index * chunk_seconds
            length = min(chunk_seconds, max(0.1, total_duration - start))
            wav = temp_dir / f"chunk_{chunk_index:04d}.wav"
            _extract_audio_chunk(video_path, start, length, wav)
            result = _dml_transcribe_one(model, wav, language, word_timestamps=word_timestamps)
            detected_language = result.get("language") or detected_language

            for local_seg in result.get("segments", []):
                seg_start = float(local_seg.get("start", 0.0)) + start
                seg_end = float(local_seg.get("end", 0.0)) + start
                words = []
                for w in (local_seg.get("words") or []) if word_timestamps else []:
                    words.append(
                        {
                            "start": float(w.get("start", 0.0)) + start,
                            "end": float(w.get("end", 0.0)) + start,
                            "word": str(w.get("word", "")).strip(),
                        }
                    )
                merged_segments.append(
                    {
                        "id": len(merged_segments),
                        "start": seg_start,
                        "end": seg_end,
                        "text": str(local_seg.get("text", "")).strip(),
                        "words": words,
                    }
                )

            _notify(
                progress_callback,
                (chunk_index + 1) / chunk_count,
                "Whisper DirectML / GPU AMD",
            )
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    duration = merged_segments[-1]["end"] if merged_segments else total_duration
    return {
        "language": detected_language,
        "duration": duration,
        "segments": merged_segments,
        "backend": "directml",
    }



def _profile_for_backend(hardware_profile: dict | None, backend_id: str) -> dict:
    profile = dict(hardware_profile or {})
    route = dict(profile.get("transcription") or {})
    if backend_id == "faster-whisper-cuda":
        route["backend"] = "cuda"
    elif backend_id == "faster-whisper-cpu":
        route["backend"] = "cpu"
    elif backend_id == "directml":
        route["backend"] = "directml"
    profile["transcription"] = route
    return profile


def _offset_transcript(transcript: dict, offset: float) -> dict:
    out = dict(transcript)
    segments = []
    for idx, raw in enumerate(transcript.get("segments") or []):
        seg = dict(raw)
        seg["id"] = idx
        seg["start"] = float(seg.get("start") or 0.0) + offset
        seg["end"] = float(seg.get("end") or 0.0) + offset
        words = []
        for raw_word in seg.get("words") or []:
            word = dict(raw_word)
            word["start"] = float(word.get("start") or 0.0) + offset
            word["end"] = float(word.get("end") or 0.0) + offset
            words.append(word)
        seg["words"] = words
        segments.append(seg)
    out["segments"] = segments
    return out


def _transcribe_segments_backend(
    video_path: str | Path,
    language: str | None = None,
    progress_callback: ProgressCallback | None = None,
    hardware_profile: dict | None = None,
    *,
    backend_id: str,
) -> dict:
    profile = _profile_for_backend(hardware_profile, backend_id)
    if backend_id == "directml":
        return _transcribe_directml(video_path, language, progress_callback, profile, word_timestamps=False)
    return _transcribe_faster_whisper(video_path, language, progress_callback, profile, word_timestamps=False)


def _transcribe_words_backend(
    video_path: str | Path,
    start: float,
    end: float,
    language: str | None = None,
    progress_callback: ProgressCallback | None = None,
    hardware_profile: dict | None = None,
    *,
    backend_id: str,
) -> dict:
    start = max(0.0, float(start))
    end = max(start + 0.05, float(end))
    profile = _profile_for_backend(hardware_profile, backend_id)
    temp_dir = Path(tempfile.mkdtemp(prefix="viralclip_asr_window_"))
    try:
        wav = temp_dir / "window.wav"
        _extract_audio_chunk(video_path, start, end - start, wav)
        if backend_id == "directml":
            result = _transcribe_directml(wav, language, progress_callback, profile, word_timestamps=True)
        else:
            result = _transcribe_faster_whisper(wav, language, progress_callback, profile, word_timestamps=True)
        result = _offset_transcript(result, start)
        result["duration"] = end - start
        return result
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _preferred_backend_id(hardware_profile: dict | None) -> str:
    profile = hardware_profile or {}
    selected = str((profile.get("asr") or {}).get("selected_backend") or "").strip()
    if selected:
        return selected
    route = str((profile.get("transcription") or {}).get("backend") or "").lower()
    mapping = {
        "cuda": "faster-whisper-cuda",
        "directml": "directml",
        "vulkan": "whispercpp-vulkan",
        "cpu": "faster-whisper-cpu",
        "faster-whisper": "faster-whisper-cpu",
    }
    return mapping.get(route, "faster-whisper-cpu")


def _backend_attempt_order(hardware_profile: dict | None, requested: str | None = None) -> list[str]:
    from .asr_backends import candidate_backend_ids
    profile = hardware_profile or {}
    preferred = requested or _preferred_backend_id(profile)
    order = [preferred] + candidate_backend_ids(profile)
    seen = set()
    return [bid for bid in order if bid and not (bid in seen or seen.add(bid))]


def transcribe_segments(
    video_path: str | Path,
    language: str | None = None,
    progress_callback: ProgressCallback | None = None,
    hardware_profile: dict | None = None,
    backend_id: str | None = None,
) -> dict:
    from .asr_backends import get_backend
    last_error = None
    for bid in _backend_attempt_order(hardware_profile, backend_id):
        try:
            return get_backend(bid).transcribe_segments(
                video_path, language=language, progress_callback=progress_callback, hardware_profile=hardware_profile
            )
        except Exception as exc:
            last_error = exc
            _notify(progress_callback, 0.0, f"{bid} indisponível; tentando fallback")
    raise RuntimeError(f"Nenhum backend ASR funcionou: {last_error}")


def transcribe_words(
    video_path: str | Path,
    start: float,
    end: float,
    language: str | None = None,
    progress_callback: ProgressCallback | None = None,
    hardware_profile: dict | None = None,
    backend_id: str | None = None,
) -> dict:
    from .asr_backends import get_backend
    last_error = None
    for bid in _backend_attempt_order(hardware_profile, backend_id):
        try:
            return get_backend(bid).transcribe_words(
                video_path, start, end, language=language, progress_callback=progress_callback, hardware_profile=hardware_profile
            )
        except Exception as exc:
            last_error = exc
            _notify(progress_callback, 0.0, f"{bid} indisponível; tentando fallback")
    raise RuntimeError(f"Nenhum backend ASR conseguiu refinar a janela: {last_error}")


def release_asr_models() -> None:
    global _faster_model, _faster_model_runtime, _faster_model_key
    global _directml_model, _directml_whisper, _directml_model_key
    with _faster_lock:
        _faster_model = None
        _faster_model_runtime = None
        _faster_model_key = None
    with _directml_lock:
        _directml_model = None
        _directml_whisper = None
        _directml_model_key = None


def warm_selected_backend(profile: dict | None = None) -> dict:
    profile = profile or {}
    backend_id = _preferred_backend_id(profile)
    if backend_id.startswith("faster-whisper"):
        _get_faster_model(_profile_for_backend(profile, backend_id))
        return {"ok": True, "backend": backend_id, "resident": True}
    if backend_id == "directml":
        _get_directml_model(profile)
        return {"ok": True, "backend": backend_id, "resident": True}
    if backend_id == "whispercpp-vulkan":
        from . import whispercpp
        exe = whispercpp.find_executable()
        status = whispercpp.validate_runtime(exe) if exe else {"ok": False, "error": "runtime ausente"}
        return {"backend": backend_id, "resident": False, **status}
    return {"ok": False, "backend": backend_id, "resident": False}

def transcribe(
    video_path: str | Path,
    language: str | None = None,
    progress_callback: ProgressCallback | None = None,
    hardware_profile: dict | None = None,
) -> dict:
    preferred = None
    if hardware_profile:
        preferred = str((hardware_profile.get("transcription") or {}).get("backend") or "auto")
        if preferred in {"cuda", "cpu", "openvino", "vulkan"}:
            preferred = "faster-whisper"
    backend = resolve_backend(preferred)
    if backend == "directml":
        try:
            return _transcribe_directml(video_path, language, progress_callback, hardware_profile)
        except Exception as exc:
            # When AUTO is selected, a driver/backend problem should not destroy
            # the job. Fall back to the tested CPU path and expose this in UI.
            if (WHISPER_BACKEND or "auto").strip().lower() == "auto":
                _notify(progress_callback, 0.0, f"DirectML indisponível ({exc}); usando CPU")
                return _transcribe_faster_whisper(video_path, language, progress_callback, hardware_profile)
            raise
    return _transcribe_faster_whisper(video_path, language, progress_callback, hardware_profile)


def save_transcript(transcript: dict, path: str | Path) -> None:
    Path(path).write_text(json.dumps(transcript, ensure_ascii=False, indent=2), encoding="utf-8")
