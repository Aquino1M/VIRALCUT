from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from app.config import DATA_DIR, FFMPEG_BIN, ASR_CACHE_MAX_GB

CACHE_ROOT = DATA_DIR / "cache" / "asr"


def _sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def source_identity(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    stat = source.stat()
    return {
        "path_hint": source.name,
        "size": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "sha256": _sha256_file(source),
    }


def _stable_key(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def segment_cache_key(path: str | Path, *, model: str, language: str | None, vad: bool, backend_quality: str = "whisper") -> str:
    ident = source_identity(path)
    return _stable_key({
        "source": ident["sha256"],
        "size": ident["size"],
        "pass": "segments",
        "quality": backend_quality,
        "model": str(model),
        "language": language or "auto",
        "vad": bool(vad),
    })


def word_window_cache_key(path: str | Path, start: float, end: float, *, model: str, language: str | None, backend_quality: str = "whisper") -> str:
    ident = source_identity(path)
    return _stable_key({
        "source": ident["sha256"],
        "size": ident["size"],
        "pass": "words",
        "quality": backend_quality,
        "model": str(model),
        "language": language or "auto",
        "start_ms": int(round(float(start) * 1000)),
        "end_ms": int(round(float(end) * 1000)),
    })


def _json_path(kind: str, key: str) -> Path:
    return Path(CACHE_ROOT) / kind / f"{key}.json"


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        os.utime(path, None)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def load_segment_transcript(key: str) -> dict | None:
    return _read_json(_json_path("segments", key))


def save_segment_transcript(key: str, value: dict) -> None:
    _write_json(_json_path("segments", key), value)


def load_word_window(key: str) -> dict | None:
    return _read_json(_json_path("words", key))


def save_word_window(key: str, value: dict) -> None:
    _write_json(_json_path("words", key), value)


def get_or_create_normalized_audio(path: str | Path) -> Path:
    source = Path(path)
    ident = source_identity(source)
    out = Path(CACHE_ROOT) / "audio" / f"{ident['sha256']}.wav"
    if out.exists() and out.stat().st_size > 44:
        os.utime(out, None)
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".wav.tmp")
    cmd = [
        FFMPEG_BIN, "-y", "-loglevel", "error", "-i", str(source), "-vn",
        "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(tmp),
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(proc.stderr[-2000:] or "Falha ao normalizar áudio para ASR")
    tmp.replace(out)
    return out


def cleanup_lru(max_bytes: int | None = None) -> dict[str, int]:
    root = Path(CACHE_ROOT)
    if not root.exists():
        return {"removed_files": 0, "removed_bytes": 0, "remaining_bytes": 0}
    if max_bytes is None:
        max_bytes = max(256 * 1024 * 1024, int(float(ASR_CACHE_MAX_GB) * (1024 ** 3)))
    files = [p for p in root.rglob("*") if p.is_file() and not p.name.endswith(".tmp")]
    total = sum(p.stat().st_size for p in files)
    removed_files = 0
    removed_bytes = 0
    if total > max_bytes:
        files.sort(key=lambda p: p.stat().st_atime if p.exists() else time.time())
        for p in files:
            if total <= max_bytes:
                break
            try:
                size = p.stat().st_size
                p.unlink()
                total -= size
                removed_bytes += size
                removed_files += 1
            except OSError:
                continue
    return {"removed_files": removed_files, "removed_bytes": removed_bytes, "remaining_bytes": max(0, total)}
