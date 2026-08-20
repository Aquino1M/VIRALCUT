from __future__ import annotations

import hashlib
import json
import os
import subprocess
import uuid
from pathlib import Path
from typing import Iterator

from app.config import FFMPEG_BIN, TEMP_DIR

DEFAULT_CHUNK_SIZE = 16 * 1024 * 1024


def sha256_file(path: str | Path, *, chunk_size: int = 4 * 1024 * 1024) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        while True:
            block = f.read(chunk_size)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def extract_cloud_audio(source: str | Path, *, out_dir: str | Path | None = None) -> Path:
    source = Path(source)
    out_dir = Path(out_dir or (TEMP_DIR / "cloud_audio"))
    out_dir.mkdir(parents=True, exist_ok=True)
    identity = sha256_file(source)[:20]
    out = out_dir / f"{identity}.mono16k.flac"
    if out.exists() and out.stat().st_size > 0:
        return out
    tmp = out.with_suffix(out.suffix + ".tmp")
    cmd = [
        FFMPEG_BIN, "-y", "-loglevel", "error", "-i", str(source), "-vn", "-ac", "1", "-ar", "16000",
        "-c:a", "flac", "-compression_level", "8", str(tmp),
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0 or not tmp.exists():
        tmp.unlink(missing_ok=True)
        raise RuntimeError(proc.stderr[-2500:] or "Falha ao preparar áudio FLAC para o Cloud Worker")
    os.replace(tmp, out)
    return out


def extract_proxy_window(
    source: str | Path,
    start: float,
    end: float,
    *,
    out_dir: str | Path | None = None,
    max_width: int = 480,
) -> Path:
    source = Path(source)
    out_dir = Path(out_dir or (TEMP_DIR / "cloud_proxy"))
    out_dir.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(f"{sha256_file(source)}|{start:.3f}|{end:.3f}|{max_width}".encode()).hexdigest()[:24]
    out = out_dir / f"{key}.mp4"
    if out.exists() and out.stat().st_size > 0:
        return out
    tmp = out.with_suffix(".tmp.mp4")
    duration = max(0.1, float(end) - float(start))
    vf = f"scale='min({max_width},iw)':-2"
    cmd = [
        FFMPEG_BIN, "-y", "-loglevel", "error", "-ss", f"{max(0.0,float(start)):.3f}", "-t", f"{duration:.3f}",
        "-i", str(source), "-vf", vf, "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "30", "-movflags", "+faststart", str(tmp),
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0 or not tmp.exists():
        tmp.unlink(missing_ok=True)
        raise RuntimeError(proc.stderr[-2500:] or "Falha ao preparar proxy para o Cloud Worker")
    os.replace(tmp, out)
    return out


def iter_chunks(path: str | Path, *, chunk_size: int = DEFAULT_CHUNK_SIZE) -> Iterator[tuple[int, bytes, str]]:
    chunk_size = max(1024 * 1024, min(64 * 1024 * 1024, int(chunk_size)))
    with Path(path).open("rb") as f:
        index = 0
        while True:
            data = f.read(chunk_size)
            if not data:
                break
            yield index, data, hashlib.sha256(data).hexdigest()
            index += 1


def file_manifest(path: str | Path, *, chunk_size: int = DEFAULT_CHUNK_SIZE) -> dict:
    p = Path(path)
    size = p.stat().st_size
    total = (size + chunk_size - 1) // chunk_size
    return {
        "name": p.name,
        "size": size,
        "sha256": sha256_file(p),
        "chunk_size": chunk_size,
        "total_chunks": total,
    }
