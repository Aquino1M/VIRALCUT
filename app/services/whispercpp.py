from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from app.config import DATA_DIR

RUNTIME_DIR = DATA_DIR / "runtime" / "whispercpp"
DEFAULT_TIMEOUT = 60 * 60


def find_executable() -> Path | None:
    root = Path(RUNTIME_DIR)
    manifest = root / "runtime.json"
    if manifest.exists():
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            candidate = Path(str(data.get("executable") or ""))
            if not candidate.is_absolute():
                candidate = root / candidate
            if candidate.exists():
                return candidate
        except Exception:
            pass
    names = ("whisper-cli.exe", "main.exe", "whisper-cli", "main")
    for name in names:
        direct = root / name
        if direct.exists():
            return direct
    if root.exists():
        for name in names:
            found = next(root.rglob(name), None)
            if found:
                return found
    return None


def validate_runtime(path: str | Path) -> dict[str, Any]:
    exe = Path(path)
    if not exe.exists():
        return {"ok": False, "error": "executável ausente"}
    try:
        proc = subprocess.run([str(exe), "--help"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=15)
        text = (proc.stdout or "").strip()
        return {"ok": proc.returncode == 0 or bool(text), "returncode": proc.returncode, "version_text": text[:500]}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:500]}


def find_model(model: str) -> Path | None:
    explicit = os.getenv("WHISPERCPP_MODEL_PATH", "").strip()
    if explicit and Path(explicit).exists():
        return Path(explicit)
    root = Path(RUNTIME_DIR) / "models"
    aliases = [
        root / f"ggml-{model}.bin",
        root / f"ggml-{model}.gguf",
        root / f"{model}.bin",
        root / f"{model}.gguf",
    ]
    return next((p for p in aliases if p.exists()), None)


def build_command(exe: Path, audio: Path, model: Path, *, word_timestamps: bool, language: str | None, output_prefix: Path | None = None) -> list[str]:
    prefix = output_prefix or audio.with_suffix("")
    cmd = [
        str(exe), "-m", str(model), "-f", str(audio), "--output-json", "-of", str(prefix),
        "--print-progress",
    ]
    if language:
        cmd += ["-l", str(language)]
    if word_timestamps:
        # Full JSON/tokens gives the adapter the richest timestamps supported by
        # the installed whisper.cpp version; older builds safely ignore token detail.
        cmd += ["--output-json-full"]
    return cmd


def _normalise_json(data: dict, *, backend: str, source_offset: float = 0.0) -> dict:
    result = data.get("result") if isinstance(data.get("result"), dict) else data
    language = result.get("language") or data.get("language") or "unknown"
    raw_segments = data.get("transcription") or data.get("segments") or result.get("segments") or []
    segments: list[dict] = []
    for idx, seg in enumerate(raw_segments if isinstance(raw_segments, list) else []):
        offsets = seg.get("offsets") if isinstance(seg, dict) else {}
        start = seg.get("start", offsets.get("from", 0) if isinstance(offsets, dict) else 0)
        end = seg.get("end", offsets.get("to", start) if isinstance(offsets, dict) else start)
        # whisper.cpp full JSON may expose offsets in milliseconds.
        if isinstance(offsets, dict) and ("from" in offsets or "to" in offsets):
            start = float(start or 0) / 1000.0
            end = float(end or 0) / 1000.0
        start = float(start or 0) + source_offset
        end = float(end or start) + source_offset
        words: list[dict] = []
        for token in seg.get("tokens") or seg.get("words") or []:
            if not isinstance(token, dict):
                continue
            wstart = token.get("start", token.get("t0", 0))
            wend = token.get("end", token.get("t1", wstart))
            if "t0" in token or "t1" in token:
                wstart = float(wstart or 0) * 0.01
                wend = float(wend or 0) * 0.01
            words.append({
                "start": float(wstart or 0) + source_offset,
                "end": float(wend or wstart or 0) + source_offset,
                "word": str(token.get("word") or token.get("text") or "").strip(),
            })
        segments.append({
            "id": idx,
            "start": start,
            "end": end,
            "text": str(seg.get("text") or "").strip(),
            "words": words,
        })
    duration = segments[-1]["end"] - source_offset if segments else 0.0
    return {"language": language, "duration": duration, "segments": segments, "backend": backend, "runtime": "vulkan"}


def run_whispercpp(audio_path: str | Path, *, model: str, language: str | None = None, word_timestamps: bool = False, source_offset: float = 0.0, timeout: int = DEFAULT_TIMEOUT) -> dict:
    exe = find_executable()
    model_path = find_model(model)
    if not exe:
        raise RuntimeError("whisper.cpp não instalado/validado")
    if not model_path:
        raise RuntimeError(f"Modelo whisper.cpp '{model}' não encontrado em {Path(RUNTIME_DIR) / 'models'}")
    with tempfile.TemporaryDirectory(prefix="viralclip_whispercpp_") as td:
        prefix = Path(td) / "result"
        cmd = build_command(exe, Path(audio_path), model_path, word_timestamps=word_timestamps, language=language, output_prefix=prefix)
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout)
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout or "whisper.cpp falhou")[-2500:])
        candidates = [prefix.with_suffix(".json"), Path(str(prefix) + ".json")]
        json_path = next((p for p in candidates if p.exists()), None)
        if json_path is None:
            try:
                data = json.loads(proc.stdout)
            except Exception as exc:
                raise RuntimeError("whisper.cpp não produziu JSON válido") from exc
        else:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        return _normalise_json(data, backend="whispercpp-vulkan", source_offset=source_offset)


def transcribe_segments(audio_path: str | Path, *, model: str, language: str | None = None, progress_callback=None, **_kwargs) -> dict:
    if progress_callback:
        progress_callback(0.0, "whisper.cpp Vulkan")
    result = run_whispercpp(audio_path, model=model, language=language, word_timestamps=False)
    if progress_callback:
        progress_callback(1.0, "whisper.cpp Vulkan")
    return result


def transcribe_words(audio_path: str | Path, start: float, end: float, *, model: str, language: str | None = None, progress_callback=None, **_kwargs) -> dict:
    from app.config import FFMPEG_BIN
    with tempfile.TemporaryDirectory(prefix="viralclip_whispercpp_window_") as td:
        wav = Path(td) / "window.wav"
        proc = subprocess.run([
            FFMPEG_BIN, "-y", "-loglevel", "error", "-ss", f"{start:.3f}", "-t", f"{max(0.1, end-start):.3f}",
            "-i", str(audio_path), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav),
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr[-2000:] or "Falha ao preparar janela para whisper.cpp")
        if progress_callback:
            progress_callback(0.0, "whisper.cpp Vulkan")
        result = run_whispercpp(wav, model=model, language=language, word_timestamps=True, source_offset=float(start))
        if progress_callback:
            progress_callback(1.0, "whisper.cpp Vulkan")
        return result
